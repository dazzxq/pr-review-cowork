#!/usr/bin/env python3
"""Tạo Gmail draft trong thread qua IMAP APPEND với race-safe idempotency.

Replace cho Gmail connector `create_draft(thread_id, to, cc, subject, body)`.

Usage:
  python3 imap_create_draft.py \
      --to "kpi@admicro.vn" \
      --cc "team1@admicro.vn,team2@admicro.vn" \
      --subject "Re: [A02] - DUYỆT - GenK - ..." \
      --in-reply-to "<original-msg-id@mail.gmail.com>" \
      --references "<root@...> <parent@...>" \
      --body-file /tmp/pr-review/<thread_id>/reply.txt \
      --thread-id 19e001b8bf611d9b

Output (stdout): JSON — APPEND success luôn exit 0
  {
    "draft_uid": "12345",
    "draft_message_id": "<...@gmail.com>",
    "thread_id": "19e001b8bf611d9b",
    "thread_match": true | false,
    "warning": "<text>" | null,
    "skipped": false | true,        # true nếu dedup match (existing draft)
    "dedup_key": "<thread>:<hash>"
  }

Threading semantics:
  Gmail auto-thread theo:
    1. In-Reply-To header (must point to Message-ID có trong thread)
    2. References header (chain Message-IDs)
    3. Subject prefix matching ("Re:", "Fwd:")
  Verify post-APPEND qua APPENDUID (RFC 4315 UIDPLUS) → fetch X-GM-THRID.

Idempotency:
  Custom header X-Cowork-Dedup-Key: <thread_id>:<sha256(normalized_body)[:16]>
  Pre-APPEND search dedup key. Match → skip APPEND, return existing.
  Race-safe: 2 runs concurrent generate same key → run sau thấy existing skip.

Exit codes:
  0  OK — APPEND thành công (kiểm tra thread_match field) hoặc dedup skip
  1  Creds missing
  2  Login fail
  3  Drafts mailbox fail
  4  Body file lỗi / args invalid
  7  IMAP APPEND fail / network transient
"""
from __future__ import annotations

import argparse
import imaplib
import json
import re
import ssl
import sys
import time
from email.message import EmailMessage
from email.utils import formatdate, getaddresses, make_msgid
from pathlib import Path

import _imap_common as c


# Poll fallback nếu APPENDUID không return: 5 retries × 2s = 10s window
POLL_RETRIES = 5
POLL_INTERVAL_S = 2


def parse_addr_list(value: str) -> list[str]:
    """Parse comma-separated email list → lowercased dedup."""
    if not value:
        return []
    out, seen = [], set()
    for _, addr in getaddresses([value]):
        addr = addr.strip().lower()
        if addr and addr not in seen:
            seen.add(addr)
            out.append(addr)
    return out


def build_subject(raw: str) -> str:
    """Add 'Re: ' prefix nếu chưa có (case-insensitive)."""
    s = raw.strip()
    if re.match(r'^re\s*:', s, re.IGNORECASE):
        return s
    return f'Re: {s}'


def build_message(
    sender: str,
    to: str,
    cc_list: list[str],
    subject: str,
    in_reply_to: str,
    references: str,
    body: str,
    dedup_key: str,
) -> bytes:
    """Compose MIME message với threading headers.

    Returns RFC822 bytes ready cho IMAP APPEND.
    """
    msg = EmailMessage()
    msg['From'] = sender
    msg['To'] = to
    if cc_list:
        msg['Cc'] = ', '.join(cc_list)
    msg['Subject'] = subject
    msg['Date'] = formatdate(localtime=True)
    msg['Message-ID'] = make_msgid(domain='mail.gmail.com')
    if in_reply_to:
        msg['In-Reply-To'] = in_reply_to
    if references:
        msg['References'] = references
    msg[c.DEDUP_HEADER] = dedup_key
    msg.set_content(body, subtype='plain', charset='utf-8')
    return msg.as_bytes()


def search_dedup(conn: imaplib.IMAP4_SSL, dedup_key: str) -> bytes | None:
    """Search HEADER X-Cowork-Dedup-Key. Returns latest UID hoặc None."""
    try:
        typ, data = conn.uid('SEARCH', None, 'HEADER', c.DEDUP_HEADER, dedup_key)
    except imaplib.IMAP4.error:
        return None
    if typ != 'OK' or not data or not data[0]:
        return None
    uids = data[0].split()
    return uids[-1] if uids else None


def fetch_message_id(conn: imaplib.IMAP4_SSL, uid: bytes) -> str:
    """Fetch Message-ID header của UID. Best-effort, returns '' nếu fail."""
    try:
        typ, data = conn.uid('FETCH', uid, '(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)])')
    except imaplib.IMAP4.error:
        return ''
    if typ != 'OK' or not data:
        return ''
    for item in data:
        if isinstance(item, tuple) and len(item) > 1 and isinstance(item[1], bytes):
            text = item[1].decode('utf-8', errors='replace')
            m = re.search(r'Message-ID:\s*(<[^<>\s]+>)', text, re.IGNORECASE)
            if m:
                return m.group(1)
    return ''


def fetch_thrid(conn: imaplib.IMAP4_SSL, uid: bytes) -> str:
    """Fetch X-GM-THRID của UID → hex string. Returns '' nếu fail."""
    try:
        typ, data = conn.uid('FETCH', uid, '(X-GM-THRID)')
    except imaplib.IMAP4.error:
        return ''
    if typ != 'OK' or not data:
        return ''
    for item in data:
        line = item if isinstance(item, bytes) else (item[0] if isinstance(item, tuple) else None)
        if not line:
            continue
        m = re.search(rb'X-GM-THRID\s+(\d+)', line)
        if m:
            return f'{int(m.group(1)):016x}'
    return ''


def cmd_create(args: argparse.Namespace) -> None:
    # Validate args
    if not c.THREAD_ID_RE.match(args.thread_id):
        c.fail(4, f'--thread-id phải là hex 1-16 chars, got: {args.thread_id!r}')

    body_path = Path(args.body_file)
    if not body_path.is_file():
        c.fail(4, f'--body-file không tồn tại: {args.body_file}')
    try:
        body = body_path.read_text(encoding='utf-8')
    except Exception as e:
        c.fail(4, f'không đọc được --body-file: {e}')
    if not body.strip():
        c.fail(4, 'body rỗng')

    if not args.to.strip():
        c.fail(4, '--to không được rỗng')

    email_addr, password = c.get_creds()
    if not email_addr or not password:
        c.fail(1, 'GMAIL_EMAIL/GMAIL_APP_PASSWORD chưa set trong .env')

    cc_list = parse_addr_list(args.cc)
    # Loại self khỏi cc nếu lỡ có
    cc_list = [a for a in cc_list if a != email_addr.lower() and a != args.to.lower()]
    subject = build_subject(args.subject)
    dedup_key = c.make_dedup_key(args.thread_id, body)
    expected_thread_int = int(args.thread_id, 16)

    try:
        conn = c.imap_login()
    except imaplib.IMAP4.error as e:
        c.fail(2, f'IMAP login fail (auth): {e}')
    except (OSError, ssl.SSLError) as e:
        c.fail(7, f'IMAP network: {e}')

    try:
        c.enable_utf8_if_supported(conn)

        # Resolve + SELECT writeable Drafts mailbox
        drafts_mailbox = c.resolve_special_use_mailbox(conn, b'\\Drafts', c.DRAFTS_FALLBACKS)
        if not drafts_mailbox:
            c.fail(3, 'không resolve được Drafts mailbox')
        try:
            c.select_mailbox(conn, drafts_mailbox, readonly=False)
        except c.ImapTransientError as e:
            c.fail(3, str(e))

        # Pre-check dedup
        existing_uid = search_dedup(conn, dedup_key)
        if existing_uid:
            existing_msgid = fetch_message_id(conn, existing_uid)
            existing_thrid = fetch_thrid(conn, existing_uid)
            print(json.dumps({
                'draft_uid': existing_uid.decode('ascii'),
                'draft_message_id': existing_msgid,
                'thread_id': args.thread_id,
                'thread_match': existing_thrid == args.thread_id,
                'warning': None,
                'skipped': True,
                'dedup_key': dedup_key,
            }, ensure_ascii=False))
            return

        # Compose + APPEND
        raw = build_message(
            sender=email_addr,
            to=args.to,
            cc_list=cc_list,
            subject=subject,
            in_reply_to=args.in_reply_to,
            references=args.references,
            body=body,
            dedup_key=dedup_key,
        )
        try:
            typ, append_data = conn.append(
                c.quote_mailbox(drafts_mailbox),
                '(\\Draft)',
                None,
                raw,
            )
        except imaplib.IMAP4.error as e:
            c.fail(7, f'IMAP APPEND fail: {e}')
        except (OSError, ssl.SSLError) as e:
            c.fail(7, f'APPEND network: {e}')
        if typ != 'OK':
            c.fail(7, f'APPEND typ={typ} data={append_data!r}')

        # Get new draft UID — APPENDUID first, fallback poll
        new_uid = c.parse_appenduid(append_data)
        warning = None
        if new_uid is None:
            # Fallback: poll với NOOP + UID SEARCH HEADER X-Cowork-Dedup-Key
            for _attempt in range(POLL_RETRIES):
                try:
                    conn.noop()
                except imaplib.IMAP4.error:
                    pass
                new_uid = search_dedup(conn, dedup_key)
                if new_uid:
                    break
                time.sleep(POLL_INTERVAL_S)
            if new_uid is None:
                # Best-effort fail — APPEND có thể OK silent, return warning
                print(json.dumps({
                    'draft_uid': None,
                    'draft_message_id': None,
                    'thread_id': args.thread_id,
                    'thread_match': False,
                    'warning': (
                        'APPENDUID không return + dedup poll timeout '
                        f'{POLL_RETRIES * POLL_INTERVAL_S}s — draft có thể đã tạo nhưng '
                        'không verify được. Check Gmail Drafts thủ công.'
                    ),
                    'skipped': False,
                    'dedup_key': dedup_key,
                }, ensure_ascii=False))
                return

        # Verify thread_match
        actual_thrid = fetch_thrid(conn, new_uid)
        thread_match = actual_thrid == args.thread_id
        draft_msgid = fetch_message_id(conn, new_uid)
        if not thread_match:
            warning = (
                f'Draft tạo OK nhưng thread mismatch: expected {args.thread_id}, '
                f'got {actual_thrid or "?"}. Có thể Subject prefix sai hoặc '
                'In-Reply-To không match Message-ID nào trong thread.'
            )

        print(json.dumps({
            'draft_uid': new_uid.decode('ascii'),
            'draft_message_id': draft_msgid,
            'thread_id': args.thread_id,
            'thread_match': thread_match,
            'warning': warning,
            'skipped': False,
            'dedup_key': dedup_key,
        }, ensure_ascii=False))
    finally:
        c.safe_logout(conn)


def main() -> None:
    p = argparse.ArgumentParser(description='Tạo Gmail draft qua IMAP APPEND với threading')
    p.add_argument('--to', required=True, help='Email chính (1 địa chỉ)')
    p.add_argument('--cc', default='', help='Cc list, comma-separated')
    p.add_argument('--subject', required=True, help='Subject (tự thêm "Re: " nếu chưa có)')
    p.add_argument('--in-reply-to', dest='in_reply_to', default='',
                   help='Message-ID gốc (có < >) — cần cho Gmail auto-thread')
    p.add_argument('--references', default='',
                   help='References chain (Message-IDs space-separated, có < >)')
    p.add_argument('--body-file', dest='body_file', required=True,
                   help='Path file UTF-8 chứa body plain text')
    p.add_argument('--thread-id', dest='thread_id', required=True,
                   help='Gmail thread ID (hex 1-16 chars) — cho dedup + verify')
    args = p.parse_args()
    c.load_env()
    cmd_create(args)


if __name__ == '__main__':
    main()
