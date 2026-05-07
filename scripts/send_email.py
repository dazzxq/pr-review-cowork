#!/usr/bin/env python3
"""
Gửi reply email qua SMTP (Gmail/Workspace) — chỉ chạy khi SEND_MODE=true.

Dùng bởi Cowork agent khi config bật send mode. Agent build trước:
  - Body reply (file UTF-8)
  - Headers từ thread gốc (subject, message-id, references, to, cc)

Usage:
  python3 send_email.py \
    --to pr-ops@example.com \
    --cc "publish-list1@example.com,publish-list2@example.com,editorial@example.com" \
    --subject "Re: [A02] - DUYỆT - GenK - ..." \
    --in-reply-to "<3C1AYAUB6TU4.16LXBGJFUXDL2@example.com>" \
    --references "<...>" \
    --body-file /tmp/pr-review/<thread_id>/reply.txt

Exit codes:
  0   gửi thành công, JSON ra stdout
  10  config: SEND_MODE chưa true
  11  config: SENDER_EMAIL trống
  12  config: SENDER_APP_PASSWORD trống
  20  body file không tồn tại / không đọc được
  30  SMTP authentication failed (creds sai)
  31  SMTP server từ chối recipient
  32  SMTP server lỗi khác
  33  Network/timeout
  99  Unknown

Stderr in lỗi human-readable cho agent đọc + fallback sang draft.
"""
import os, sys, json, ssl, argparse, smtplib, socket
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, getaddresses
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

def truthy(v):
    return str(v or '').strip().lower() in ('true', '1', 'yes', 'on')

def fail(code, msg):
    print(f"ERROR[{code}]: {msg}", file=sys.stderr)
    sys.exit(code)

def parse_email_list(s):
    """Trả list email addresses (lowercased, dedup) từ chuỗi 'a@b.com,c@d.com' hoặc empty."""
    if not s:
        return []
    out, seen = [], set()
    for _, addr in getaddresses([s]):
        addr = addr.strip().lower()
        if addr and addr not in seen:
            seen.add(addr); out.append(addr)
    return out

def main():
    parser = argparse.ArgumentParser(description='SMTP send reply for Cowork PR review')
    parser.add_argument('--to', required=True, help='Email chính (1 địa chỉ)')
    parser.add_argument('--cc', default='', help='Cc list, comma-separated')
    parser.add_argument('--subject', required=True, help='Subject (đã có Re:)')
    parser.add_argument('--in-reply-to', required=True, dest='in_reply_to',
                        help='Message-ID gốc (có < >)')
    parser.add_argument('--references', default='', dest='references',
                        help='References chain (có < >)')
    parser.add_argument('--body-file', required=True, dest='body_file',
                        help='Path file UTF-8 chứa body plain text')
    args = parser.parse_args()

    # ── 1. Validate config ─────────────────────────────────────────────────
    if not truthy(os.environ.get('SEND_MODE')):
        fail(10, "SEND_MODE chưa bật. Set SEND_MODE=true trong .env nếu muốn gửi mail thẳng.")
    # Backward-compat: ưu tiên GMAIL_*, fallback SENDER_* (legacy)
    sender = (os.environ.get('GMAIL_EMAIL') or os.environ.get('SENDER_EMAIL', '')).strip()
    if not sender:
        fail(11, "GMAIL_EMAIL (hoặc SENDER_EMAIL) trống trong .env. Điền email Gmail/Workspace của bạn.")
    pwd = (os.environ.get('GMAIL_APP_PASSWORD') or os.environ.get('SENDER_APP_PASSWORD', '')).strip()
    if not pwd:
        fail(12, "GMAIL_APP_PASSWORD (hoặc SENDER_APP_PASSWORD) trống trong .env. "
                 "Tạo app password tại https://myaccount.google.com/apppasswords "
                 "(yêu cầu 2FA đã bật).")
    # Strip space trong app password (Google hiển thị có dấu cách)
    pwd = pwd.replace(' ', '')

    smtp_host = os.environ.get('SMTP_HOST', 'smtp.gmail.com').strip()
    try:
        smtp_port = int(os.environ.get('SMTP_PORT', '465').strip())
    except ValueError:
        smtp_port = 465

    # ── 2. Validate body file ──────────────────────────────────────────────
    body_path = Path(args.body_file)
    if not body_path.is_file():
        fail(20, f"body-file không tồn tại: {args.body_file}")
    try:
        body = body_path.read_text(encoding='utf-8')
    except Exception as e:
        fail(20, f"Không đọc được body-file: {e}")
    if not body.strip():
        fail(20, "body-file rỗng")

    # ── 3. Build message ───────────────────────────────────────────────────
    cc_list = parse_email_list(args.cc)
    # Loại self khỏi cc nếu lỡ có
    cc_list = [a for a in cc_list if a != sender.lower() and a != args.to.lower()]

    msg = EmailMessage()
    msg['From'] = sender
    msg['To'] = args.to
    if cc_list:
        msg['Cc'] = ', '.join(cc_list)
    msg['Subject'] = args.subject
    msg['Date'] = formatdate(localtime=True)
    msg['Message-ID'] = make_msgid(domain='mail.gmail.com')
    msg['In-Reply-To'] = args.in_reply_to
    msg['References'] = (args.references + ' ' + args.in_reply_to).strip() if args.references else args.in_reply_to
    msg.set_content(body, subtype='plain', charset='utf-8')

    recipients = [args.to] + cc_list

    # ── 4. SMTP send ───────────────────────────────────────────────────────
    ctx = ssl.create_default_context()
    try:
        with smtplib.SMTP_SSL(smtp_host, smtp_port, context=ctx, timeout=30) as s:
            s.login(sender, pwd)
            refused = s.send_message(msg, from_addr=sender, to_addrs=recipients)
            if refused:
                fail(31, f"SMTP từ chối recipients: {refused}")
    except smtplib.SMTPAuthenticationError as e:
        fail(30, f"SMTP auth failed (sai SENDER_EMAIL/SENDER_APP_PASSWORD, "
                 f"hoặc 2FA chưa bật, hoặc Workspace admin tắt app password): {e}")
    except smtplib.SMTPRecipientsRefused as e:
        fail(31, f"SMTP từ chối tất cả recipients: {e.recipients}")
    except smtplib.SMTPException as e:
        fail(32, f"SMTP error: {type(e).__name__}: {e}")
    except (socket.timeout, TimeoutError) as e:
        fail(33, f"SMTP timeout (network slow hoặc Cowork egress chặn smtp.gmail.com:{smtp_port}): {e}")
    except OSError as e:
        fail(33, f"Network error tới {smtp_host}:{smtp_port} "
                 f"(check Cowork egress allow smtp.gmail.com): {e}")
    except Exception as e:
        fail(99, f"Unknown error: {type(e).__name__}: {e}")

    # ── 5. Output JSON success ─────────────────────────────────────────────
    print(json.dumps({
        'mode': 'sent',
        'message_id': msg['Message-ID'].strip('<>'),
        'to': args.to,
        'cc': cc_list,
        'subject': args.subject,
        'sender': sender,
    }, ensure_ascii=False))

if __name__ == '__main__':
    main()
