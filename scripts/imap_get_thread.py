#!/usr/bin/env python3
"""Get all messages metadata trong Gmail thread(s) via IMAP.

Replace cho Gmail connector `get_thread(id).messages`. Hỗ trợ single + batch
mode để tránh login overhead khi process nhiều threads.

Usage (single):
  python3 imap_get_thread.py --thread-id <hex>
  → JSON object: {"thread_id": ..., "messages": [...]}

Usage (batch — 1 IMAP login cho N threads):
  python3 imap_get_thread.py --thread-ids <hex1>,<hex2>,...
  → JSON dict: {"<hex1>": {"messages": [...]}, "<hex2>": {...}, ...}
    Nếu thread không tồn tại / fail: {"<hex>": {"error": "...", "exit_code": N}}

Message format (cả 2 mode, sorted by INTERNALDATE asc — messages[0] = mail gốc):
  {
    "gmail_msg_id": "19e001701c605c28",
    "uid": "12345",
    "message_id": "<...@mail.gmail.com>",
    "in_reply_to": "<...@mail.gmail.com>" | "",
    "references": "<...> <...>" | "",
    "from": "Tên <a@b.com>",
    "to": ["a@b.com", "c@d.com"],
    "cc": ["e@f.com"],
    "reply_to": "x@y.com" | "",
    "subject": "...",
    "date": "2026-05-07 08:39:00"
  }

Exit codes:
  0  OK (single hoặc batch — batch luôn exit 0 nếu login OK, errors per-thread trong JSON)
  1  Creds missing
  2  Login fail
  3  Mailbox fail
  4  Thread ID format invalid (CHỈ single mode — batch skip invalid IDs với error entry)
  5  Thread không có message nào (CHỈ single mode)
  7  Transient (IMAP/parse fail)
"""
from __future__ import annotations

import argparse
import email
import email.policy
import imaplib
import json
import re
import ssl
import sys
from datetime import datetime
from email.utils import getaddresses

import _imap_common as c


def decode_str_header(value: str | None) -> str:
    """Decode RFC 2047 + normalize whitespace. Returns '' nếu None."""
    if value is None:
        return ''
    # email.policy.default tự decode RFC 2047 → return str. Just normalize space.
    return re.sub(r'\s+', ' ', str(value)).strip()


def parse_addr_list(value: str | None) -> list[str]:
    """Parse address header thành list of email addresses (lowercased, dedup)."""
    if not value:
        return []
    out, seen = [], set()
    for _, addr in getaddresses([str(value)]):
        addr = addr.strip().lower()
        if addr and addr not in seen:
            seen.add(addr)
            out.append(addr)
    return out


def parse_msgid_list(value: str | None) -> str:
    """Parse References header thành space-separated chain. Preserve <>."""
    if not value:
        return ''
    # Tokenize: extract tất cả <...> tokens
    tokens = re.findall(r'<[^<>\s]+>', str(value))
    return ' '.join(tokens)


def parse_internaldate(line: bytes) -> tuple[str, datetime | None]:
    """Extract INTERNALDATE → (ISO string, datetime). Best-effort."""
    m = re.search(rb'INTERNALDATE\s+"([^"]+)"', line)
    if not m:
        return '', None
    raw = m.group(1).decode('ascii', errors='replace')
    try:
        dt = datetime.strptime(raw, '%d-%b-%Y %H:%M:%S %z')
        return dt.strftime('%Y-%m-%d %H:%M:%S'), dt
    except ValueError:
        return raw, None


def parse_uid(line: bytes) -> bytes | None:
    """Extract UID từ FETCH response line."""
    m = re.search(rb'\bUID\s+(\d+)', line)
    return m.group(1) if m else None


def parse_gmail_msg_id(line: bytes) -> str:
    """Extract X-GM-MSGID → hex string. Returns '' nếu không tìm được."""
    m = re.search(rb'X-GM-MSGID\s+(\d+)', line)
    if not m:
        return ''
    return f'{int(m.group(1)):016x}'


def fetch_thread_messages(conn: imaplib.IMAP4_SSL, thread_id_hex: str) -> list[dict]:
    """Fetch + parse messages của 1 thread. Conn phải đã SELECT All Mail.

    Returns: list of message dicts (sorted by date asc).
    Raises: c.ImapTransientError nếu IMAP/parse fail. Returns [] nếu thread empty.
    """
    thread_id_int = int(thread_id_hex, 16)
    try:
        typ, data = conn.uid('SEARCH', None, 'X-GM-THRID', str(thread_id_int))
    except imaplib.IMAP4.error as e:
        raise c.ImapTransientError(f'X-GM-THRID search fail: {e}')
    if typ != 'OK':
        raise c.ImapTransientError(f'X-GM-THRID search typ={typ}')

    if not data or not data[0]:
        return []
    uids = data[0].split()
    if not uids:
        return []

    try:
        typ, fetch_data = conn.uid(
            'FETCH',
            b','.join(uids),
            '(UID X-GM-MSGID INTERNALDATE BODY.PEEK[HEADER])',
        )
    except imaplib.IMAP4.error as e:
        raise c.ImapTransientError(f'UID FETCH metadata: {e}')
    if typ != 'OK':
        raise c.ImapTransientError(f'UID FETCH typ={typ}')

    messages = []
    i = 0
    while i < len(fetch_data):
        item = fetch_data[i]
        if not item:
            i += 1
            continue
        meta_line = b''
        header_bytes = b''
        if isinstance(item, tuple):
            meta_line = item[0] if isinstance(item[0], bytes) else b''
            header_bytes = item[1] if len(item) > 1 and isinstance(item[1], bytes) else b''
            i += 1
        elif isinstance(item, bytes):
            if item.strip() == b')':
                i += 1
                continue
            meta_line = item
            i += 1
        else:
            i += 1
            continue

        uid = parse_uid(meta_line)
        if uid is None:
            continue
        gmail_msg_id = parse_gmail_msg_id(meta_line)
        date_str, dt = parse_internaldate(meta_line)

        try:
            msg = email.message_from_bytes(header_bytes, policy=email.policy.default)
        except Exception:
            msg = None

        from_h = decode_str_header(msg['from']) if msg else ''
        to_list = parse_addr_list(msg.get('to', '')) if msg else []
        cc_list = parse_addr_list(msg.get('cc', '')) if msg else []
        reply_to = decode_str_header(msg.get('reply-to', '')) if msg else ''
        if reply_to:
            rt_addrs = parse_addr_list(reply_to)
            reply_to_addr = rt_addrs[0] if rt_addrs else reply_to
        else:
            reply_to_addr = ''
        subject = decode_str_header(msg['subject']) if msg else ''
        message_id = decode_str_header(msg.get('message-id', '')) if msg else ''
        in_reply_to = decode_str_header(msg.get('in-reply-to', '')) if msg else ''
        references = parse_msgid_list(msg.get('references', '')) if msg else ''

        messages.append({
            'gmail_msg_id': gmail_msg_id,
            'uid': uid.decode('ascii'),
            'message_id': message_id,
            'in_reply_to': in_reply_to,
            'references': references,
            'from': from_h,
            'to': to_list,
            'cc': cc_list,
            'reply_to': reply_to_addr,
            'subject': subject,
            'date': date_str,
            '_dt': dt,
        })

    if not messages:
        raise c.ImapTransientError(
            f'thread {thread_id_hex} parse được 0 messages từ {len(uids)} UIDs'
        )

    messages.sort(key=lambda m: (m['_dt'] is None, m['_dt'] or 0))
    for m in messages:
        m.pop('_dt', None)
    return messages


def login_and_select() -> imaplib.IMAP4_SSL:
    """Login + ENABLE UTF-8 + SELECT All Mail. Caller responsible cho safe_logout.

    Raises: SystemExit qua c.fail() nếu lỗi infra.
    """
    email_addr, password = c.get_creds()
    if not email_addr or not password:
        c.fail(1, 'GMAIL_EMAIL/GMAIL_APP_PASSWORD chưa set trong .env')
    try:
        conn = c.imap_login()
    except imaplib.IMAP4.error as e:
        c.fail(2, f'IMAP login fail (auth): {e}')
    except (OSError, ssl.SSLError) as e:
        c.fail(7, f'IMAP network: {e}')
    c.enable_utf8_if_supported(conn)
    mailbox = c.resolve_special_use_mailbox(conn, b'\\All', c.ALL_MAIL_FALLBACKS)
    if not mailbox:
        c.safe_logout(conn)
        c.fail(3, 'không resolve được All Mail mailbox')
    try:
        c.select_mailbox(conn, mailbox, readonly=True)
    except c.ImapTransientError as e:
        c.safe_logout(conn)
        c.fail(3, str(e))
    return conn


def cmd_single(thread_id_hex: str) -> None:
    """Single thread mode — preserves original output format + exit codes."""
    if not c.THREAD_ID_RE.match(thread_id_hex):
        c.fail(4, f'--thread-id phải là hex 1-16 chars, got: {thread_id_hex!r}')
    conn = login_and_select()
    try:
        try:
            messages = fetch_thread_messages(conn, thread_id_hex)
        except c.ImapTransientError as e:
            c.fail(7, str(e))
        if not messages:
            c.fail(5, f'thread {thread_id_hex} không có message')
        result = {'thread_id': thread_id_hex, 'messages': messages}
        print(json.dumps(result, ensure_ascii=False))
    finally:
        c.safe_logout(conn)


def cmd_batch(thread_ids: list[str]) -> None:
    """Batch mode — 1 login cho N threads. Errors per-thread trong JSON output.

    Exit 0 nếu login OK, regardless của per-thread results.
    """
    conn = login_and_select()
    result = {}
    try:
        for tid in thread_ids:
            tid = tid.strip()
            if not tid:
                continue
            if not c.THREAD_ID_RE.match(tid):
                result[tid] = {'error': 'thread-id format invalid', 'exit_code': 4}
                continue
            try:
                messages = fetch_thread_messages(conn, tid)
            except c.ImapTransientError as e:
                result[tid] = {'error': str(e), 'exit_code': 7}
                continue
            if not messages:
                result[tid] = {'error': 'thread không có message', 'exit_code': 5}
                continue
            result[tid] = {'messages': messages}
        print(json.dumps(result, ensure_ascii=False))
    finally:
        c.safe_logout(conn)


def main() -> None:
    p = argparse.ArgumentParser(description='Get Gmail thread messages metadata qua IMAP')
    grp = p.add_mutually_exclusive_group(required=True)
    grp.add_argument('--thread-id', help='Single Gmail thread ID (hex 1-16 chars)')
    grp.add_argument(
        '--thread-ids',
        help='Batch mode: comma-separated thread IDs (1 login cho N threads — nhanh hơn nhiều cho >5 threads)',
    )
    args = p.parse_args()
    c.load_env()
    if args.thread_id:
        cmd_single(args.thread_id)
    else:
        ids = [x.strip() for x in args.thread_ids.split(',') if x.strip()]
        if not ids:
            c.fail(4, '--thread-ids rỗng sau parse')
        cmd_batch(ids)


if __name__ == '__main__':
    main()
