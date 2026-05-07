#!/usr/bin/env python3
"""Check thread(s) đã có draft trong Drafts folder chưa (idempotency).

Replace cho Gmail connector `search_drafts(query=f"thread:{id}")`. Hỗ trợ
single + batch mode để tránh login overhead khi check nhiều threads.

Usage (single):
  python3 imap_check_thread_drafted.py --thread-id <hex>
  → JSON: {"thread_id": ..., "has_draft": ..., "draft_count": ..., "drafts_mailbox": ...}

Usage (batch — 1 IMAP login cho N threads):
  python3 imap_check_thread_drafted.py --thread-ids <hex1>,<hex2>,...
  → JSON dict: {"<hex1>": {"has_draft": bool, "draft_count": N}, ...}
    Plus top-level "_drafts_mailbox" key.

Note: KHÔNG filter "do agent tạo" vs "user tạo thủ công" — Gmail không
expose creator info ở MIME level. Treat any draft trong thread = "đã xử lý".

Exit codes:
  0  OK (single hoặc batch)
  1  Creds missing
  2  Login fail
  3  Drafts mailbox fail
  4  Thread ID invalid (single mode)
  7  Transient
"""
from __future__ import annotations

import argparse
import imaplib
import json
import ssl

import _imap_common as c


def search_thread_in_drafts(conn: imaplib.IMAP4_SSL, thread_id_hex: str) -> int:
    """Search drafts for X-GM-THRID match. Returns count.

    Caller phải đã SELECT Drafts mailbox.
    Raises c.ImapTransientError nếu IMAP fail.
    """
    thread_id_int = int(thread_id_hex, 16)
    try:
        typ, data = conn.uid('SEARCH', None, 'X-GM-THRID', str(thread_id_int))
    except imaplib.IMAP4.error as e:
        raise c.ImapTransientError(f'X-GM-THRID search fail: {e}')
    if typ != 'OK':
        raise c.ImapTransientError(f'X-GM-THRID search typ={typ}')
    uids = data[0].split() if data and data[0] else []
    return len(uids)


def login_and_select_drafts() -> tuple[imaplib.IMAP4_SSL, str]:
    """Login + ENABLE UTF-8 + SELECT Drafts. Returns (conn, mailbox_name).

    Raises SystemExit via c.fail() trên lỗi infra.
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
    mailbox = c.resolve_special_use_mailbox(conn, b'\\Drafts', c.DRAFTS_FALLBACKS)
    if not mailbox:
        c.safe_logout(conn)
        c.fail(3, 'không resolve được Drafts mailbox')
    try:
        c.select_mailbox(conn, mailbox, readonly=True)
    except c.ImapTransientError as e:
        c.safe_logout(conn)
        c.fail(3, str(e))
    return conn, mailbox


def cmd_single(thread_id_hex: str) -> None:
    if not c.THREAD_ID_RE.match(thread_id_hex):
        c.fail(4, f'--thread-id phải là hex 1-16 chars, got: {thread_id_hex!r}')
    conn, mailbox = login_and_select_drafts()
    try:
        try:
            count = search_thread_in_drafts(conn, thread_id_hex)
        except c.ImapTransientError as e:
            c.fail(7, str(e))
        result = {
            'thread_id': thread_id_hex,
            'has_draft': count > 0,
            'draft_count': count,
            'drafts_mailbox': mailbox,
        }
        print(json.dumps(result, ensure_ascii=False))
    finally:
        c.safe_logout(conn)


def cmd_batch(thread_ids: list[str]) -> None:
    conn, mailbox = login_and_select_drafts()
    result: dict = {'_drafts_mailbox': mailbox}
    try:
        for tid in thread_ids:
            tid = tid.strip()
            if not tid:
                continue
            if not c.THREAD_ID_RE.match(tid):
                result[tid] = {'error': 'thread-id format invalid', 'exit_code': 4}
                continue
            try:
                count = search_thread_in_drafts(conn, tid)
            except c.ImapTransientError as e:
                result[tid] = {'error': str(e), 'exit_code': 7}
                continue
            result[tid] = {'has_draft': count > 0, 'draft_count': count}
        print(json.dumps(result, ensure_ascii=False))
    finally:
        c.safe_logout(conn)


def main() -> None:
    p = argparse.ArgumentParser(description='Check thread(s) đã có draft chưa')
    grp = p.add_mutually_exclusive_group(required=True)
    grp.add_argument('--thread-id', help='Single thread ID (hex 1-16 chars)')
    grp.add_argument(
        '--thread-ids',
        help='Batch mode: comma-separated thread IDs (1 login cho N threads)',
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
