#!/usr/bin/env python3
"""
Fetch body của mail gốc trong Gmail thread qua IMAP.

Workaround cho Anthropic Gmail connector limitation: connector chỉ trả
text/plain part, mail HTML-only trả body rỗng. Issues #48713, #50298 trên
GitHub Anthropic, chưa fix tại thời điểm viết.

Usage:
  # Verify creds + IMAP login + mailbox accessible (preflight đầu run)
  python3 fetch_email_body.py --check-creds

  # Fetch HTML body của mail gốc trong thread
  python3 fetch_email_body.py --thread-id <hex>

  # Exact match qua Gmail message ID (preferred khi connector cung cấp)
  python3 fetch_email_body.py --thread-id <hex> --gmail-msg-id <hex>

Exit codes:
  0  Thành công, body ra stdout (UTF-8)
  1  Creds missing trong .env (GMAIL_EMAIL/GMAIL_APP_PASSWORD)
  2  IMAP login fail (app password sai hoặc 2FA chưa bật)
  3  Mailbox select fail (không tìm được All Mail / Tất cả thư / INBOX)
  4  Thread ID format invalid (không phải hex 1-16 chars)
  5  Thread thật sự không có message nào
  6  Body parse fail (không có text/html lẫn text/plain trong message)
  7  Network/IMAP transient error / parse metadata fail (caller có thể retry)
"""
import os
import sys
import re
import ssl
import argparse
import imaplib
import email
import email.policy
from pathlib import Path

# Load .env (cùng pattern send_email.py)
ENV_FILE = Path(__file__).resolve().parent.parent / '.env'
if ENV_FILE.exists():
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, v = line.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip())

THREAD_ID_RE = re.compile(r'^[0-9a-fA-F]{1,16}$')
ALL_MAIL_FALLBACKS = ['[Gmail]/All Mail', '[Gmail]/Tất cả thư', 'INBOX']
CHARSET_FALLBACKS = ['utf-8', 'cp1252', 'iso-8859-1', 'gb18030']


class ImapTransientError(Exception):
    """IMAP search/fetch/parse fail không phải vì thread rỗng.

    Caller (cmd_fetch) catch → exit 7 để retry+breaker handle.
    Phân biệt với None return (= thread thật sự empty → exit 5)."""
    pass


def get_creds():
    """Backward-compat: ưu tiên GMAIL_*, fallback SENDER_* (legacy)."""
    email_addr = os.environ.get('GMAIL_EMAIL') or os.environ.get('SENDER_EMAIL')
    password = os.environ.get('GMAIL_APP_PASSWORD') or os.environ.get('SENDER_APP_PASSWORD')
    return email_addr, password


def imap_login(host, port, email_addr, password):
    ctx = ssl.create_default_context()
    conn = imaplib.IMAP4_SSL(host, port, ssl_context=ctx, timeout=30)
    conn.login(email_addr, password)
    return conn


def resolve_all_mail_mailbox(conn):
    """Tìm mailbox All Mail qua SPECIAL-USE \\All flag (locale-independent).

    Returns mailbox name (str) hoặc None nếu không resolve được.
    Gmail trả "[Gmail]/All Mail" hoặc "[Gmail]/Tất cả thư" tùy locale —
    \\All flag là cờ chuẩn không phụ thuộc tên hiển thị.
    """
    typ, data = conn.list('""', '*')
    if typ == 'OK' and data:
        for line in data:
            if not line:
                continue
            # imaplib có thể trả tuple (header_bytes, name_bytes) cho literal mailbox
            if isinstance(line, tuple):
                line = line[0]
            if not isinstance(line, bytes):
                continue
            if b'\\All' not in line:
                continue
            # Format: (\flags) "/" "Mailbox Name"
            # Lấy quoted string cuối cùng (tên mailbox sau separator)
            quoted = re.findall(rb'"([^"]+)"', line)
            if quoted:
                # quoted[-1] = mailbox name (quoted[-2] hoặc trước = separator)
                return quoted[-1].decode('utf-8', errors='replace')
            # Fallback: unquoted atom name (không có space) ở cuối line
            tail = line.rstrip()
            m = re.search(rb'(\S+)$', tail)
            if m:
                return m.group(1).decode('utf-8', errors='replace')
    return None


def find_first_message_uid(conn, thread_id_hex, gmail_msg_id_hex=None):
    """Find UID of mail gốc trong thread.

    Return contract:
      - bytes UID nếu tìm được mail gốc
      - None CHỈ KHI thread thật sự empty (X-GM-THRID search trả 0 UIDs)
      - raise ImapTransientError nếu IMAP fail / parse fail / metadata fetch fail
        → caller map sang exit 7

    Strategy:
      1. Nếu --gmail-msg-id valid hex: search X-GM-MSGID <decimal>
         (Gmail extension, same identifier space với connector messages[].id)
      2. Fallback: UID SEARCH X-GM-THRID + UID FETCH (UID INTERNALDATE)
         → parse `UID <n>` field explicitly → pick earliest INTERNALDATE
    """
    thread_id_int = int(thread_id_hex, 16)

    # --- Primary: X-GM-MSGID exact match ---
    if gmail_msg_id_hex:
        if not THREAD_ID_RE.match(gmail_msg_id_hex):
            print(
                f'WARN: --gmail-msg-id "{gmail_msg_id_hex}" không phải hex 1-16 chars, '
                'skip primary path',
                file=sys.stderr,
            )
        else:
            msg_id_int = int(gmail_msg_id_hex, 16)
            typ, data = conn.uid('SEARCH', None, 'X-GM-MSGID', str(msg_id_int))
            if typ != 'OK':
                raise ImapTransientError(f'X-GM-MSGID search returned typ={typ}')
            if data and data[0]:
                uids = data[0].split()
                if uids:
                    return uids[0]
            # Không match → mail có thể bị move/delete. Fall through to thread fallback.

    # --- Fallback: X-GM-THRID search ---
    typ, data = conn.uid('SEARCH', None, 'X-GM-THRID', str(thread_id_int))
    if typ != 'OK':
        raise ImapTransientError(f'X-GM-THRID search returned typ={typ}')
    if not data or not data[0]:
        return None  # Thread thật sự empty
    uids = data[0].split()
    if not uids:
        return None
    if len(uids) == 1:
        return uids[0]

    # --- Multi-message: pick earliest INTERNALDATE ---
    typ, fetch_data = conn.uid('FETCH', b','.join(uids), '(UID INTERNALDATE)')
    if typ != 'OK':
        raise ImapTransientError(f'UID FETCH metadata returned typ={typ}')

    earliest_uid = None
    earliest_date = None
    parse_count = 0
    for item in fetch_data:
        if not item:
            continue
        # imaplib trả tuple (header_bytes, body_bytes) hoặc raw bytes
        if isinstance(item, tuple):
            line = item[0]
        elif isinstance(item, bytes):
            line = item
        else:
            continue
        # Parse UID explicitly — KHÔNG dùng leading sequence number
        m_uid = re.search(rb'\bUID\s+(\d+)', line)
        m_date = re.search(rb'INTERNALDATE\s+"([^"]+)"', line)
        if not m_uid or not m_date:
            continue
        parse_count += 1
        uid = m_uid.group(1)
        try:
            wrapped = b'INTERNALDATE "' + m_date.group(1) + b'"'
            date = imaplib.Internaldate2tuple(wrapped)
            if earliest_date is None or date < earliest_date:
                earliest_date = date
                earliest_uid = uid
        except Exception:
            continue

    if earliest_uid is None:
        # Có UIDs nhưng không parse được metadata nào → IMAP server response weird
        raise ImapTransientError(
            f'không parse được UID/INTERNALDATE từ {len(uids)} messages '
            f'(parsed {parse_count})'
        )
    return earliest_uid


def fetch_message(conn, uid):
    """Fetch RFC822 raw + parse với policy=default.

    Returns email.message.EmailMessage hoặc None nếu fetch fail.
    """
    typ, data = conn.uid('FETCH', uid, '(RFC822)')
    if typ != 'OK' or not data or data[0] is None:
        return None
    # imaplib trả list, item đầu là tuple (header, body) cho RFC822
    item = data[0]
    if not isinstance(item, tuple) or len(item) < 2:
        return None
    raw = item[1]
    return email.message_from_bytes(raw, policy=email.policy.default)


def extract_body(msg):
    """Extract HTML body (preferred) hoặc plaintext fallback.

    Dùng EmailMessage.get_body(preferencelist=('html','plain')) — handle
    multipart/alternative, multipart/related, multipart/signed correctly.

    Charset fallback chain để decode payload an toàn cho mail có charset
    declared sai (rare edge case).
    """
    body_part = msg.get_body(preferencelist=('html', 'plain'))
    if body_part is None:
        return None

    # policy=default: get_content() returns str (auto-decoded theo charset)
    try:
        content = body_part.get_content()
        if content:
            return content
    except (LookupError, UnicodeDecodeError):
        # Charset declared không recognized hoặc decode fail → manual fallback
        pass

    # Manual fallback: decode payload bytes với charset chain
    payload = body_part.get_payload(decode=True)
    if payload is None:
        return None
    declared = body_part.get_content_charset()
    charsets_to_try = []
    if declared:
        charsets_to_try.append(declared)
    charsets_to_try.extend(c for c in CHARSET_FALLBACKS if c != declared)
    for charset in charsets_to_try:
        try:
            return payload.decode(charset)
        except (UnicodeDecodeError, LookupError):
            continue
    # Last resort: utf-8 với errors=replace (lossy nhưng không crash)
    return payload.decode('utf-8', errors='replace')


def cmd_check_creds():
    """Verify creds + IMAP login + mailbox actually selectable.

    Exit 0 OK, 1 missing creds, 2 auth fail, 3 mailbox/select fail, 7 network.
    """
    email_addr, password = get_creds()
    if not email_addr or not password:
        print('ERROR: GMAIL_EMAIL/GMAIL_APP_PASSWORD chưa set trong .env', file=sys.stderr)
        sys.exit(1)
    host = os.environ.get('IMAP_HOST', 'imap.gmail.com')
    port = int(os.environ.get('IMAP_PORT', '993'))
    try:
        conn = imap_login(host, port, email_addr, password)
    except imaplib.IMAP4.error as e:
        print(f'ERROR: IMAP login fail (auth): {e}', file=sys.stderr)
        sys.exit(2)
    except (OSError, ssl.SSLError) as e:
        print(f'ERROR: IMAP network: {e}', file=sys.stderr)
        sys.exit(7)
    try:
        mailbox = resolve_all_mail_mailbox(conn)
        if not mailbox:
            print(
                'ERROR: không tìm thấy All Mail mailbox '
                '(\\All special-use không có và fallback chain fail)',
                file=sys.stderr,
            )
            sys.exit(3)
        # Actually select để verify mailbox usable, không chỉ exist
        typ, _ = conn.select(f'"{mailbox}"', readonly=True)
        if typ != 'OK':
            print(f'ERROR: select mailbox "{mailbox}" returned {typ}', file=sys.stderr)
            sys.exit(3)
        print(f'OK: {email_addr} -> {mailbox}')
    finally:
        try:
            conn.logout()
        except Exception:
            pass
    sys.exit(0)


def cmd_fetch(thread_id, gmail_msg_id=None):
    if not THREAD_ID_RE.match(thread_id):
        print(
            f'ERROR: --thread-id phải là hex 1-16 chars, got: {thread_id!r}',
            file=sys.stderr,
        )
        sys.exit(4)

    email_addr, password = get_creds()
    if not email_addr or not password:
        print('ERROR: GMAIL_EMAIL/GMAIL_APP_PASSWORD chưa set trong .env', file=sys.stderr)
        sys.exit(1)

    host = os.environ.get('IMAP_HOST', 'imap.gmail.com')
    port = int(os.environ.get('IMAP_PORT', '993'))
    try:
        conn = imap_login(host, port, email_addr, password)
    except imaplib.IMAP4.error as e:
        print(f'ERROR: IMAP login fail (auth): {e}', file=sys.stderr)
        sys.exit(2)
    except (OSError, ssl.SSLError) as e:
        print(f'ERROR: IMAP network/SSL: {e}', file=sys.stderr)
        sys.exit(7)

    try:
        mailbox = resolve_all_mail_mailbox(conn)
        if not mailbox:
            print('ERROR: không tìm thấy All Mail mailbox', file=sys.stderr)
            sys.exit(3)
        typ, _ = conn.select(f'"{mailbox}"', readonly=True)
        if typ != 'OK':
            print(f'ERROR: select mailbox "{mailbox}" returned {typ}', file=sys.stderr)
            sys.exit(3)

        try:
            uid = find_first_message_uid(conn, thread_id, gmail_msg_id)
        except imaplib.IMAP4.error as e:
            print(f'ERROR: IMAP search/fetch: {e}', file=sys.stderr)
            sys.exit(7)
        except ImapTransientError as e:
            print(f'ERROR: IMAP transient (parse/metadata): {e}', file=sys.stderr)
            sys.exit(7)

        if uid is None:
            print(f'ERROR: thread {thread_id} không có message', file=sys.stderr)
            sys.exit(5)

        msg = fetch_message(conn, uid)
        if msg is None:
            uid_str = uid.decode() if isinstance(uid, bytes) else str(uid)
            print(f'ERROR: fetch UID {uid_str} fail', file=sys.stderr)
            sys.exit(7)

        body = extract_body(msg)
        if body is None:
            print(
                f'ERROR: không extract được body từ thread {thread_id} '
                '(không có text/html lẫn text/plain)',
                file=sys.stderr,
            )
            sys.exit(6)
        sys.stdout.write(body)
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def main():
    p = argparse.ArgumentParser(
        description='Fetch mail gốc body từ Gmail thread qua IMAP'
    )
    p.add_argument(
        '--thread-id',
        help='Gmail thread ID (hex 1-16 chars từ connector get_thread)',
    )
    p.add_argument(
        '--gmail-msg-id',
        help=(
            'Optional: Gmail message ID hex (từ connector messages[0].id) '
            '- search qua X-GM-MSGID extension cho exact match. '
            'KHÔNG phải RFC Message-ID header.'
        ),
    )
    p.add_argument(
        '--check-creds',
        action='store_true',
        help='Chỉ verify creds + IMAP login + mailbox select, không fetch.',
    )
    args = p.parse_args()

    if args.check_creds:
        cmd_check_creds()
    elif args.thread_id:
        cmd_fetch(args.thread_id, args.gmail_msg_id)
    else:
        p.error('phải có --thread-id hoặc --check-creds')


if __name__ == '__main__':
    main()
