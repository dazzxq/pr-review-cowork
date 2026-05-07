# Test SMTP Send (self-test)

Verify config SMTP trước khi bật `SEND_MODE=true` cho production. **Self-send** an toàn — gửi mail test cho chính bạn, không động tới BBT/khách.

## Khi nào dùng

- Lần đầu setup `.env` với `GMAIL_EMAIL` + `GMAIL_APP_PASSWORD` (hoặc legacy `SENDER_*`)
- Sau khi rotate app password
- Khi nghi ngờ Cowork egress chặn SMTP
- Khi pipeline báo lỗi auth/timeout không rõ nguyên nhân

## Cách chạy

### Từ Cowork conversation

User gõ: *"test the SMTP send config"* hoặc *"run send test"* — Cowork agent đọc file này, gọi:

```bash
python3 <SKILL_DIR>/scripts/test_send.py
```

Agent relay output cho user thấy.

### Từ terminal (standalone)

```bash
cd ~/pr-review-cowork

# Mode 1: dùng .env có sẵn
python3 scripts/test_send.py

# Mode 2: interactive (password ẩn, không vào history)
python3 scripts/test_send.py --interactive

# Mode 3: dry-run (validate config, không gửi)
python3 scripts/test_send.py --dry-run
```

## Quy trình full

```
[1] User edit .env:
      GMAIL_EMAIL=you@gmail.com
      GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx

[2] User chạy test:
      python3 scripts/test_send.py

[3] Script:
      • Đọc credentials
      • Build email "[TEST] PR Review Cowork — SMTP check ..."
      • Gửi tới chính email của user
      • Nếu OK → in ✅ + ROTATE warning
      • Nếu fail → exit code rõ ràng, không retry

[4] User mở Gmail → verify email test đến

[5] User ROTATE password (bắt buộc):
      • Vào https://myaccount.google.com/apppasswords
      • Revoke password vừa dùng test
      • Tạo password mới
      • Update .env

[6] User set SEND_MODE=true trong .env

[7] Production ready
```

## Exit codes

| Exit | Ý nghĩa | Action |
|------|---------|--------|
| 0 | Test gửi thành công | User verify inbox + ROTATE password |
| 1 | Config thiếu (email/password trống) | Điền .env hoặc dùng --interactive |
| 30 | SMTP auth failed | Check: sai password, 2FA chưa bật, Workspace tắt app pwd |
| 32 | SMTP server từ chối / lỗi khác | Xem stderr, check rate limit |
| 33 | Network/timeout | Cowork egress: allow `smtp.gmail.com:465` |
| 99 | Unknown | Báo bug |

## Lý do PHẢI ROTATE sau test

Khi bạn paste app password vào:
- Terminal → vào shell history (`~/.zsh_history`, `~/.bash_history`)
- `.env` file → có thể bị backup, sync vào cloud, commit nhầm
- Cowork conversation log → server-side log của Anthropic
- Process memory → có thể bị dump

→ Password đó **không còn an toàn**. Rotate = revoke cái cũ + tạo mới = clean slate.

## Edge cases test_send.py handle

1. `.env` không có / trống → exit 1 với hướng dẫn
2. Password có dấu cách (Google copy) → tự strip
3. Password ≠ 16 ký tự → warn nhưng vẫn try (đề phòng có exotic case)
4. `--interactive` ở Cowork shell (không có TTY) → exit 1 với fallback hướng dẫn
5. SMTP server unreachable → exit 33 với gợi ý egress
6. Rate limit (gửi quá nhiều test trong 1h) → exit 32, đợi vài phút
7. Email pattern sai → SMTP auth fail (Gmail tự reject) → exit 30

## Tích hợp với SEND_MODE

Test script **KHÔNG check `SEND_MODE`** — bạn có thể test ngay cả khi `SEND_MODE=false` (chưa muốn bật production). Khi test pass + rotate xong, mới flip `SEND_MODE=true`.

## Sample output (success)

```
━━ Bước 1: Đọc credentials ━━
  Email      : you@gmail.com  (from .env)
  Password   : •••••••••••••••• (16 chars, from .env)
  SMTP server: smtp.gmail.com:465

━━ Bước 2: Build test email ━━
  Subject: [TEST] PR Review Cowork — SMTP check 2026-05-07 10:30:15
  Body   : 1247 bytes, 28 lines

━━ Bước 3: Gửi qua smtp.gmail.com:465 ━━
  → Connected, đang login...
  → Login OK, đang send...
  → Send OK

━━ Bước 4: Kết quả ━━
✅ Test email sent successfully
   Message-ID : 16abc...@mail.gmail.com
   Elapsed    : 1.34s
   To         : you@gmail.com

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚠️  SECURITY — ROTATE app password NGAY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Bạn vừa test với app password ở plaintext. ...
  1. Mở: https://myaccount.google.com/apppasswords
  2. Tìm password vừa dùng, click REVOKE
  3. Tạo password mới
  4. Update .env với password mới
  5. Set SEND_MODE=true trong .env nếu muốn bật production
```
