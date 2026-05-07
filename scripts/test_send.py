#!/usr/bin/env python3
"""
Test SMTP send config — gửi 1 email test CHO CHÍNH BẠN (self-send), an toàn.

Mục đích: verify GMAIL_EMAIL + GMAIL_APP_PASSWORD + network egress trước khi
bật SEND_MODE=true cho production. KHÔNG gửi tới BBT/khách thật.

Usage:
  # Mode 1 — recommend: đọc từ .env
  python3 test_send.py

  # Mode 2 — interactive prompt (password ẩn, không vào shell history)
  python3 test_send.py --interactive

  # Mode 3 — pass args trực tiếp (KHÔNG khuyến khích, lưu vào history)
  python3 test_send.py --email you@gmail.com --password "xxxx xxxx xxxx xxxx"

  # Mode 4 — validate config, không gửi
  python3 test_send.py --dry-run

Sau khi gửi OK → script in CẢNH BÁO ROTATE password vừa dùng (security best practice).

Exit codes: 0 OK, 1 config thiếu, 30 auth fail, 32 SMTP error, 33 network, 99 unknown.
"""
import sys, os, ssl, smtplib, socket, argparse, getpass, time
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from datetime import datetime
from pathlib import Path

# ── Load .env nếu có ───────────────────────────────────────────────────────
ENV_FILE = Path(__file__).resolve().parent.parent / '.env'
if ENV_FILE.exists():
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, v = line.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip())

C_RED    = '\033[91m'
C_GREEN  = '\033[92m'
C_YELLOW = '\033[93m'
C_BLUE   = '\033[94m'
C_BOLD   = '\033[1m'
C_END    = '\033[0m'

def color(text, *codes):
    if not sys.stderr.isatty() and not sys.stdout.isatty():
        return text
    return ''.join(codes) + text + C_END

def fail(msg, code=1):
    print(color(f"❌ ERROR[{code}]: {msg}", C_RED), file=sys.stderr)
    sys.exit(code)

def section(title):
    print()
    print(color(f"━━ {title} ━━", C_BOLD, C_BLUE))

def main():
    parser = argparse.ArgumentParser(
        description='Self-test SMTP send for PR Review Cowork',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('--email', default=None,
                        help='Email Gmail/Workspace (override .env)')
    parser.add_argument('--password', default=None,
                        help='App password (override .env, KHÔNG nên dùng — vào shell history)')
    parser.add_argument('--interactive', '-i', action='store_true',
                        help='Prompt cho email + password (password ẩn)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Chỉ validate config, không gửi mail')
    args = parser.parse_args()

    # ── 1. Lấy credentials ────────────────────────────────────────────────
    section('Bước 1: Đọc credentials')

    # Backward-compat: ưu tiên GMAIL_*, fallback SENDER_* (legacy)
    env_email = (os.environ.get('GMAIL_EMAIL') or os.environ.get('SENDER_EMAIL', '')).strip()
    env_pwd = (os.environ.get('GMAIL_APP_PASSWORD') or os.environ.get('SENDER_APP_PASSWORD', '')).strip()
    email = args.email or env_email or None
    pwd = args.password or env_pwd or None

    source_email = 'CLI arg' if args.email else ('.env' if email else None)
    source_pwd = 'CLI arg' if args.password else ('.env' if pwd else None)

    if args.interactive or (not email or not pwd):
        if not email:
            try:
                email = input('Email Gmail/Workspace: ').strip()
                source_email = 'interactive prompt'
            except EOFError:
                fail('Không có terminal interactive. Set GMAIL_EMAIL trong .env hoặc dùng --email.')
        if not pwd:
            try:
                pwd = getpass.getpass('App password (hidden — paste rồi Enter): ').strip()
                source_pwd = 'interactive prompt'
            except EOFError:
                fail('Không có terminal interactive. Set GMAIL_APP_PASSWORD trong .env hoặc dùng --interactive ở real terminal.')

    if not email:
        fail('Thiếu email — set GMAIL_EMAIL trong .env hoặc dùng --email.', 1)
    if not pwd:
        fail('Thiếu app password — set GMAIL_APP_PASSWORD trong .env hoặc dùng --password/--interactive.', 1)

    # Strip spaces (Google copy có dấu cách)
    pwd_clean = pwd.replace(' ', '')

    smtp_host = os.environ.get('SMTP_HOST', 'smtp.gmail.com').strip()
    try:
        smtp_port = int(os.environ.get('SMTP_PORT', '465').strip())
    except ValueError:
        smtp_port = 465

    print(f"  Email      : {email}  (from {source_email})")
    print(f"  Password   : {'•' * len(pwd_clean)} ({len(pwd_clean)} chars, from {source_pwd})")
    print(f"  SMTP server: {smtp_host}:{smtp_port}")

    if len(pwd_clean) != 16:
        print(color(f"  ⚠️  Password {len(pwd_clean)} ký tự — Google app password chuẩn là 16. "
                    f"Có thể sai paste hoặc bạn đang dùng regular password (sẽ fail auth).", C_YELLOW))

    if args.dry_run:
        section('Dry-run')
        print(color('✓ Config OK — không gửi mail (dry-run).', C_GREEN))
        return

    # ── 2. Build email ─────────────────────────────────────────────────────
    section('Bước 2: Build test email')

    ts_local = datetime.now().strftime('%Y-%m-%d %H:%M:%S %Z').strip()
    subject = f"[TEST] PR Review Cowork — SMTP check {ts_local}"
    body = f"""Đây là email TEST tự động từ PR Review Cowork agent.

Nếu bạn nhận được email này, SMTP send config đã hoạt động OK ✓

═══ Test info ═══
  Timestamp : {ts_local}
  From / To : {email} (self-send)
  SMTP      : {smtp_host}:{smtp_port}

═══ Bước tiếp theo ═══

  1. Verify email này đã đến inbox của {email}.

  2. ⚠️  ROTATE app password ngay lập tức:
     → Vào https://myaccount.google.com/apppasswords
     → Tìm password vừa dùng (tên/timestamp), click REVOKE
     → Tạo password MỚI, paste vào .env

     Lý do: app password đã được paste vào terminal/shell/Cowork log
     có thể bị compromise. Rotate sau test = best practice security.

  3. Đặt `SEND_MODE=true` trong .env (cùng password mới)
     để agent gửi mail thẳng cho BBT thay vì tạo draft.

  4. (Tuỳ chọn) Xoá email test này khỏi inbox để dọn dẹp.

-- PR Review Cowork test_send.py
"""

    msg = EmailMessage()
    msg['From'] = email
    msg['To'] = email
    msg['Subject'] = subject
    msg['Date'] = formatdate(localtime=True)
    msg['Message-ID'] = make_msgid(domain='mail.gmail.com')
    msg.set_content(body, subtype='plain', charset='utf-8')

    print(f"  Subject: {subject}")
    print(f"  Body   : {len(body)} bytes, {len(body.splitlines())} lines")

    # ── 3. SMTP send ──────────────────────────────────────────────────────
    section(f'Bước 3: Gửi qua {smtp_host}:{smtp_port}')

    t0 = time.time()
    ctx = ssl.create_default_context()
    try:
        with smtplib.SMTP_SSL(smtp_host, smtp_port, context=ctx, timeout=30) as s:
            print(f"  → Connected, đang login...")
            s.login(email, pwd_clean)
            print(f"  → Login OK, đang send...")
            s.send_message(msg, from_addr=email, to_addrs=[email])
            print(f"  → Send OK")
        elapsed = time.time() - t0
    except smtplib.SMTPAuthenticationError as e:
        elapsed = time.time() - t0
        fail(f"SMTP authentication failed sau {elapsed:.1f}s.\n"
             f"   Nguyên nhân có thể:\n"
             f"   - Sai email hoặc app password\n"
             f"   - Account chưa bật 2-Step Verification\n"
             f"   - Workspace admin tắt App Passwords\n"
             f"   Detail: {e}", 30)
    except smtplib.SMTPException as e:
        fail(f"SMTP error: {type(e).__name__}: {e}", 32)
    except (socket.timeout, TimeoutError):
        fail(f"Network timeout sau 30s. Có thể Cowork egress chặn {smtp_host}:{smtp_port}.\n"
             f"   Vào Cowork settings → Network egress → allow {smtp_host}:{smtp_port}", 33)
    except OSError as e:
        fail(f"Network error tới {smtp_host}:{smtp_port}: {e}\n"
             f"   Check Cowork egress hoặc kết nối Internet.", 33)
    except Exception as e:
        fail(f"Unknown error: {type(e).__name__}: {e}", 99)

    # ── 4. Success + rotate reminder ──────────────────────────────────────
    section('Bước 4: Kết quả')
    print(color(f'✅ Test email sent successfully', C_GREEN, C_BOLD))
    print(f"   Message-ID : {msg['Message-ID'].strip('<>')}")
    print(f"   Elapsed    : {elapsed:.2f}s")
    print(f"   To         : {email}")

    print()
    print(color('━' * 70, C_YELLOW))
    print(color('⚠️  SECURITY — ROTATE app password NGAY', C_YELLOW, C_BOLD))
    print(color('━' * 70, C_YELLOW))
    print(f"""
Bạn vừa test với app password ở plaintext. Để tránh password lộ vĩnh viễn
(do shell history, .env file, Cowork log...), rotate ngay:

  1. Mở: https://myaccount.google.com/apppasswords
  2. Tìm password vừa dùng (theo tên/timestamp), click {color('REVOKE', C_RED)}
  3. Tạo password mới
  4. Update {color('.env', C_BLUE)} với password mới:
       GMAIL_APP_PASSWORD=<new-password-here>
  5. Set {color('SEND_MODE=true', C_BLUE)} trong .env nếu muốn bật production

Verify email đã đến inbox của {email} trước khi rotate.
""")

if __name__ == '__main__':
    main()
