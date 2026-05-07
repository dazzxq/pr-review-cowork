#!/usr/bin/env python3
"""
In danh sách senior reviewer emails dạng JSON array.

Đọc từ env `REVIEWER_EMAILS` (comma-separated). Nếu env không set → dùng default.
Agent gọi script này ở Bước 1 filter để biết những email nào cần skip thread.

Usage:
  python3 list_reviewers.py
  → ["tuanlehoang@genk.vn", "hainguyenquang@genk.vn"]

Mọi entry được lowercase + strip để so sánh case-insensitive an toàn.
"""
import os, sys, json
from pathlib import Path

# Default — áp dụng khi REVIEWER_EMAILS không set trong .env
DEFAULT = ['tuanlehoang@genk.vn', 'hainguyenquang@genk.vn']

# ── Load .env nếu có (cùng pattern với send_email.py) ──────────────────────
ENV_FILE = Path(__file__).resolve().parent.parent / '.env'
if ENV_FILE.exists():
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, v = line.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip())

def main():
    raw = os.environ.get('REVIEWER_EMAILS', '').strip()
    if raw:
        emails = [e.strip().lower() for e in raw.split(',') if e.strip()]
        if not emails:  # env set nhưng toàn whitespace/comma
            emails = DEFAULT
    else:
        emails = DEFAULT
    print(json.dumps(emails))

if __name__ == '__main__':
    main()
