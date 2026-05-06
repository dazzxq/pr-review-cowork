#!/bin/bash
# Setup Cowork-Lite PR Review — idempotent, chạy lại an toàn không hỏng gì.
set -e

cd "$(dirname "$0")"

echo "=== PR Review Agent — Cowork-Lite Setup ==="
echo ""

# ── 1. Tìm Python 3.10+ ────────────────────────────────────────────────────
PYTHON=""
for cmd in python3.13 python3.12 python3.11 python3.10; do
    if command -v "$cmd" &> /dev/null; then
        PYTHON="$cmd"
        break
    fi
done

# Fallback: check `python3` xem có ≥ 3.10 không (macOS system thường là 3.9)
if [[ -z "$PYTHON" ]] && command -v python3 &> /dev/null; then
    if python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
        PYTHON="python3"
    fi
fi

if [[ -z "$PYTHON" ]]; then
    echo "❌ Không tìm thấy Python 3.10+ (markitdown yêu cầu)."
    echo ""
    echo "   macOS:   brew install python@3.12"
    echo "   Linux:   apt install python3.12  (hoặc pyenv)"
    echo "   Windows: tải từ https://python.org"
    echo ""
    if command -v python3 &> /dev/null; then
        CUR=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
        echo "   (Hiện tại có python3 = $CUR — quá cũ.)"
    fi
    exit 1
fi

PYVER=$($PYTHON -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")')
echo "✓ Python $PYVER ($PYTHON)"

# ── 2. Tạo venv (skip nếu đã có) ───────────────────────────────────────────
if [[ ! -d ".venv" ]]; then
    echo "→ Tạo venv tại .venv/"
    $PYTHON -m venv .venv
else
    # Verify venv hợp lệ (đôi khi venv tạo lỗi để lại folder rỗng)
    if [[ ! -x ".venv/bin/python" ]]; then
        echo "⚠️  .venv/ không hợp lệ — tạo lại"
        rm -rf .venv
        $PYTHON -m venv .venv
    else
        VENV_VER=$(.venv/bin/python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
        if python3 -c "import sys; sys.exit(0 if (${VENV_VER}+0.0) >= 3.10 else 1)" 2>/dev/null; then
            echo "✓ venv đã có (.venv/, Python $VENV_VER)"
        else
            echo "⚠️  venv đang dùng Python $VENV_VER quá cũ — tạo lại với $PYTHON"
            rm -rf .venv
            $PYTHON -m venv .venv
        fi
    fi
fi

# ── 3. Cài markitdown (skip nếu đã có) ─────────────────────────────────────
if .venv/bin/python -c "import markitdown" 2>/dev/null; then
    MD_VER=$(.venv/bin/python -c "from importlib.metadata import version; print(version('markitdown'))" 2>/dev/null || echo "?")
    echo "✓ markitdown đã cài (v$MD_VER)"
else
    echo "→ Cài markitdown + deps..."
    .venv/bin/pip install --quiet --upgrade pip
    .venv/bin/pip install --quiet -r requirements.txt
    MD_VER=$(.venv/bin/python -c "from importlib.metadata import version; print(version('markitdown'))" 2>/dev/null || echo "?")
    echo "✓ markitdown đã cài (v$MD_VER)"
fi

# ── 4. Symlink python (cho Cowork shell tiện gọi) ─────────────────────────
if [[ ! -L "python" ]]; then
    ln -sf .venv/bin/python python
fi

# ── 5. Tạo .env từ template (skip nếu đã có) ──────────────────────────────
if [[ -f ".env" ]]; then
    echo "✓ .env đã có (giữ nguyên config hiện tại)"
elif [[ -f ".env.example" ]]; then
    cp .env.example .env
    echo "→ Đã tạo .env từ .env.example. Mặc định SEND_MODE=false (chỉ tạo draft)."
    echo "  Bật send mode: edit .env, set SEND_MODE=true + điền SENDER_EMAIL/SENDER_APP_PASSWORD."
fi

echo ""
echo "✓ Setup xong."
echo ""
echo "=== Bước tiếp theo trong Cowork ==="
echo "1. Mở Claude Desktop → tab Cowork"
echo "2. Settings → Connectors → Connect Gmail (OAuth, 1 click)"
echo "3. Trust folder: $(pwd)"
echo "4. Trong Cowork session, gõ:"
echo "   \"Schedule a task every 10 minutes that runs the skill at $(pwd)/SKILL.md\""
echo "5. Click Run now → approve các permission Bash/Gmail → 'Always allow' từng tool"
echo ""
echo "=== Test SMTP (trước khi bật SEND_MODE) ==="
echo "  python3 scripts/test_send.py        # đọc credentials từ .env"
echo "  python3 scripts/test_send.py -i     # interactive prompt (password ẩn)"
echo "  python3 scripts/test_send.py --dry-run   # validate config, không gửi"
echo ""
echo "Audit log: xem trong Cowork conversation, mỗi run là 1 session ở Routines tab."
