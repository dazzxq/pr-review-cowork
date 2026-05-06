#!/bin/bash
# Setup Cowork-Lite PR Review — chạy 1 lần sau khi tải về
set -e

cd "$(dirname "$0")"

echo "=== PR Review Agent — Cowork-Lite Setup ==="
echo ""

# 1. Check Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Không tìm thấy python3. Cài Python 3.10+ trước (https://python.org hoặc 'brew install python@3.12')"
    exit 1
fi

PYVER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "✓ Python $PYVER"

# 2. Tạo venv
if [[ ! -d ".venv" ]]; then
    echo "→ Tạo venv tại .venv/"
    python3 -m venv .venv
fi

# 3. Install deps
echo "→ Cài deps (markitdown)..."
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -r requirements.txt

# 4. Symlink python để Cowork shell tìm được dễ
if [[ ! -L "python" ]]; then
    ln -sf .venv/bin/python python
fi

# 5. Tạo .env từ template (nếu chưa có)
if [[ ! -f ".env" && -f ".env.example" ]]; then
    cp .env.example .env
    echo "→ Đã tạo .env từ .env.example. Mặc định SEND_MODE=false (chỉ tạo draft)."
    echo "  Bật send mode: edit .env, set SEND_MODE=true + điền SENDER_EMAIL/SENDER_APP_PASSWORD."
fi

echo ""
echo "✓ Setup xong."
echo ""
echo "=== Bước tiếp theo trong Cowork ==="
echo "1. Mở Claude Desktop → Cowork tab"
echo "2. Settings → Connectors → Connect Gmail (OAuth, 1 click)"
echo "3. Trust folder: $(pwd)"
echo "4. Trong Cowork session, gõ:"
echo "   \"Schedule a task every 10 minutes that runs the skill at $(pwd)/SKILL.md\""
echo "5. Click Run now → approve các permission Bash/Gmail → 'Always allow' từng tool"
echo ""
echo "Audit log: xem trong Cowork conversation, mỗi run là 1 session ở Routines tab."
