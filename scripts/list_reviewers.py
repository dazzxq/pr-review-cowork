#!/usr/bin/env python3
"""
In danh sách senior reviewer emails dạng JSON array.

Đọc từ env `REVIEWER_EMAILS` (comma-separated, set trong .env). Agent gọi script này
ở Bước 1 filter để biết những email nào cần skip thread (sếp duyệt thủ công).

Usage:
  python3 list_reviewers.py
  → ["senior1@example.com", "senior2@example.com"]   (nếu .env có set)
  → []                                                (nếu chưa set, kèm warning)

Nếu env rỗng → in `[]` ra stdout + warning ra stderr. Agent vẫn chạy nhưng
sẽ KHÔNG skip thread của ai cả (có thể tạo draft trùng với sếp).

Mọi entry được lowercase + strip để so sánh case-insensitive an toàn.
"""
import os, sys, json
from pathlib import Path

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
    emails = [e.strip().lower() for e in raw.split(',') if e.strip()] if raw else []
    if not emails:
        print(
            "WARNING: REVIEWER_EMAILS chưa set trong .env — agent sẽ KHÔNG skip "
            "thread mà sếp đã reply (có thể tạo draft trùng).",
            file=sys.stderr,
        )
    print(json.dumps(emails))

if __name__ == '__main__':
    main()
