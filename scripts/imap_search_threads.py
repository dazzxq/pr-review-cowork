#!/usr/bin/env python3
"""Search Gmail threads via IMAP, return JSON list.

Replace cho Gmail connector `search_threads(query, newer_than)`.

Usage:
  python3 imap_search_threads.py \
      --query 'subject:"DUYỆT - GenK" OR subject:"ĐĂNG - GenK"' \
      --newer-than 2d

Output (stdout): JSON array sorted by latest_date desc
  [
    {
      "thread_id": "19e001b8bf611d9b",     # hex (X-GM-THRID)
      "latest_subject": "Re: ...",
      "latest_sender": "Tên <a@b.com>",
      "latest_date": "2026-05-07 08:39:00",
      "match_count": 3
    },
    ...
  ]

Exit codes:
  0  OK (JSON ra stdout, có thể là [] nếu không match)
  1  Creds missing
  2  IMAP login fail
  3  Mailbox select fail
  4  Args invalid
  7  IMAP transient
"""
from __future__ import annotations

import argparse
import imaplib
import json
import re
import ssl
import sys
from datetime import datetime, timedelta
from email.header import decode_header, make_header

import _imap_common as c


def parse_newer_than(s: str) -> int:
    """Parse '2d', '7d', '24h' → days (rounded up cho 'h')."""
    s = s.strip().lower()
    m = re.match(r'^(\d+)\s*([dh])$', s)
    if not m:
        raise ValueError(f'newer-than format invalid: {s!r}, expected e.g. "2d" or "24h"')
    n, unit = int(m.group(1)), m.group(2)
    if unit == 'h':
        return max(1, (n + 23) // 24)
    return n


def imap_since_date(days_ago: int) -> str:
    """IMAP SEARCH SINCE date format: DD-Mon-YYYY (English month name)."""
    dt = datetime.now() - timedelta(days=days_ago)
    return dt.strftime('%d-%b-%Y')


def decode_rfc2047(s: str | bytes) -> str:
    """Decode RFC 2047 encoded-words (e.g. =?UTF-8?B?...?=) trong header."""
    if isinstance(s, bytes):
        s = s.decode('utf-8', errors='replace')
    try:
        return str(make_header(decode_header(s)))
    except Exception:
        return s


def parse_internaldate(line: bytes) -> str:
    """Extract INTERNALDATE → ISO local datetime string. Best-effort."""
    m = re.search(rb'INTERNALDATE\s+"([^"]+)"', line)
    if not m:
        return ''
    raw = m.group(1).decode('ascii', errors='replace')
    try:
        # IMAP format: '07-May-2026 08:39:00 +0700'
        dt = datetime.strptime(raw, '%d-%b-%Y %H:%M:%S %z')
        return dt.strftime('%Y-%m-%d %H:%M:%S')
    except ValueError:
        return raw


def parse_thrid(line: bytes) -> str:
    """Extract X-GM-THRID → hex string. Returns '' nếu không tìm được."""
    m = re.search(rb'X-GM-THRID\s+(\d+)', line)
    if not m:
        return ''
    return f'{int(m.group(1)):016x}'


def parse_header_block(line: bytes) -> tuple[str, str]:
    """Extract Subject + From từ BODY[HEADER.FIELDS (SUBJECT FROM)] response.

    Response phần body chứa raw header text. imaplib trả tuple cho literal:
        (b'<seq> FETCH (...HEADER...{N}', b'<actual headers>')
    Ở đây line đã là bytes của 1 part — tìm Subject/From trong đó.
    """
    # Decode line to text (best-effort)
    text = line.decode('utf-8', errors='replace') if isinstance(line, bytes) else line
    subject = ''
    sender = ''
    # Headers separated by CRLF, có thể folded (next line bắt đầu với space/tab)
    # Đơn giản: regex multiline với non-greedy + lookahead
    m_sub = re.search(r'^Subject:\s*(.*?)(?=\r?\n[^\s]|\r?\n\r?\n|\Z)', text, re.MULTILINE | re.DOTALL)
    m_from = re.search(r'^From:\s*(.*?)(?=\r?\n[^\s]|\r?\n\r?\n|\Z)', text, re.MULTILINE | re.DOTALL)
    if m_sub:
        subject = decode_rfc2047(re.sub(r'\s+', ' ', m_sub.group(1)).strip())
    if m_from:
        sender = decode_rfc2047(re.sub(r'\s+', ' ', m_from.group(1)).strip())
    return subject, sender


def cmd_search(query: str, newer_than: str) -> None:
    if not query.strip():
        c.fail(4, '--query không được rỗng')
    try:
        days = parse_newer_than(newer_than)
    except ValueError as e:
        c.fail(4, str(e))

    email_addr, password = c.get_creds()
    if not email_addr or not password:
        c.fail(1, 'GMAIL_EMAIL/GMAIL_APP_PASSWORD chưa set trong .env')

    try:
        conn = c.imap_login()
    except imaplib.IMAP4.error as e:
        c.fail(2, f'IMAP login fail (auth): {e}')
    except (OSError, ssl.SSLError) as e:
        c.fail(7, f'IMAP network: {e}')

    try:
        # ENABLE UTF-8 cho query có Vietnamese
        c.enable_utf8_if_supported(conn)

        mailbox = c.resolve_special_use_mailbox(conn, b'\\All', c.ALL_MAIL_FALLBACKS)
        if not mailbox:
            c.fail(3, 'không resolve được All Mail mailbox')
        try:
            c.select_mailbox(conn, mailbox, readonly=True)
        except c.ImapTransientError as e:
            c.fail(3, str(e))

        # Search: X-GM-RAW + SINCE
        since = imap_since_date(days)
        try:
            typ, data = conn.uid(
                'SEARCH',
                None,
                'X-GM-RAW',
                c.quote_search_arg(query),
                'SINCE',
                since,
            )
        except imaplib.IMAP4.error as e:
            c.fail(7, f'UID SEARCH X-GM-RAW fail: {e}')
        if typ != 'OK':
            c.fail(7, f'UID SEARCH typ={typ}')

        if not data or not data[0]:
            print('[]')
            return

        uids = data[0].split()
        if not uids:
            print('[]')
            return

        # Fetch metadata: X-GM-THRID + INTERNALDATE + Subject + From
        try:
            typ, fetch_data = conn.uid(
                'FETCH',
                b','.join(uids),
                '(X-GM-THRID INTERNALDATE BODY.PEEK[HEADER.FIELDS (SUBJECT FROM)])',
            )
        except imaplib.IMAP4.error as e:
            c.fail(7, f'UID FETCH metadata: {e}')
        if typ != 'OK':
            c.fail(7, f'UID FETCH typ={typ}')

        # Parse: imaplib trả mỗi message thành 2 items với literal:
        #   [(b'<seq> (X-GM-THRID 12345 INTERNALDATE "..." BODY[...] {N}', b'<headers>'), b')']
        # Group by message bằng cách iterate cẩn thận
        threads = {}  # thread_id_hex → {latest_date, subject, sender, count}
        i = 0
        while i < len(fetch_data):
            item = fetch_data[i]
            if not item:
                i += 1
                continue
            # Header line: tuple (meta, body) hoặc bytes-only
            meta_line = b''
            body_part = b''
            if isinstance(item, tuple):
                meta_line = item[0] if isinstance(item[0], bytes) else b''
                body_part = item[1] if len(item) > 1 and isinstance(item[1], bytes) else b''
                i += 1
            elif isinstance(item, bytes):
                meta_line = item
                i += 1
            else:
                i += 1
                continue
            # Skip closing ')' lines
            if meta_line.strip() == b')':
                continue
            thread_id = parse_thrid(meta_line)
            if not thread_id:
                continue
            internaldate = parse_internaldate(meta_line)
            subject, sender = parse_header_block(body_part) if body_part else ('', '')

            entry = threads.get(thread_id)
            if entry is None:
                threads[thread_id] = {
                    'thread_id': thread_id,
                    'latest_subject': subject,
                    'latest_sender': sender,
                    'latest_date': internaldate,
                    'match_count': 1,
                }
            else:
                entry['match_count'] += 1
                # Cập nhật metadata nếu UID này mới hơn
                if internaldate and internaldate > entry['latest_date']:
                    entry['latest_subject'] = subject or entry['latest_subject']
                    entry['latest_sender'] = sender or entry['latest_sender']
                    entry['latest_date'] = internaldate

        result = sorted(threads.values(), key=lambda t: t['latest_date'], reverse=True)
        print(json.dumps(result, ensure_ascii=False))
    finally:
        c.safe_logout(conn)


def main() -> None:
    p = argparse.ArgumentParser(description='Search Gmail threads qua IMAP')
    p.add_argument('--query', required=True, help='Gmail search query (e.g. subject:"DUYỆT - GenK")')
    p.add_argument(
        '--newer-than',
        default='2d',
        help='Time window: "2d", "7d", "24h" (default 2d)',
    )
    args = p.parse_args()
    c.load_env()
    cmd_search(args.query, args.newer_than)


if __name__ == '__main__':
    main()
