#!/usr/bin/env python3
"""Check thread đã có draft trong Drafts folder chưa (idempotency).

Replace cho Gmail connector `search_drafts(query=f"thread:{id}")`.

Usage:
  python3 imap_check_thread_drafted.py --thread-id <hex>

Output (stdout): JSON
  {
    "thread_id": "19e001b8bf611d9b",
    "has_draft": true | false,
    "draft_count": N,
    "drafts_mailbox": "[Gmail]/Drafts"
  }

Note: KHÔNG filter "do agent tạo" vs "user tạo thủ công" — Gmail không
expose creator info ở MIME level. Treat any draft trong thread = "đã xử lý".
Trade-off safe: nếu user tạo draft thủ công, agent skip → tránh trùng.

Exit codes:
  0  OK (regardless of has_draft)
  1  Creds missing
  2  Login fail
  3  Drafts mailbox fail
  4  Thread ID invalid
  7  Transient
"""
from __future__ import annotations

import argparse
import imaplib
import json
import ssl
import sys

import _imap_common as c


def cmd_check(thread_id_hex: str) -> None:
    if not c.THREAD_ID_RE.match(thread_id_hex):
        c.fail(4, f'--thread-id phải là hex 1-16 chars, got: {thread_id_hex!r}')

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
        c.enable_utf8_if_supported(conn)

        drafts_mailbox = c.resolve_special_use_mailbox(conn, b'\\Drafts', c.DRAFTS_FALLBACKS)
        if not drafts_mailbox:
            c.fail(3, 'không resolve được Drafts mailbox')
        try:
            c.select_mailbox(conn, drafts_mailbox, readonly=True)
        except c.ImapTransientError as e:
            c.fail(3, str(e))

        thread_id_int = int(thread_id_hex, 16)
        try:
            typ, data = conn.uid('SEARCH', None, 'X-GM-THRID', str(thread_id_int))
        except imaplib.IMAP4.error as e:
            c.fail(7, f'X-GM-THRID search fail: {e}')
        if typ != 'OK':
            c.fail(7, f'X-GM-THRID search typ={typ}')

        uids = data[0].split() if data and data[0] else []
        result = {
            'thread_id': thread_id_hex,
            'has_draft': len(uids) > 0,
            'draft_count': len(uids),
            'drafts_mailbox': drafts_mailbox,
        }
        print(json.dumps(result, ensure_ascii=False))
    finally:
        c.safe_logout(conn)


def main() -> None:
    p = argparse.ArgumentParser(description='Check thread đã có draft chưa')
    p.add_argument('--thread-id', required=True, help='Gmail thread ID (hex 1-16 chars)')
    args = p.parse_args()
    c.load_env()
    cmd_check(args.thread_id)


if __name__ == '__main__':
    main()
