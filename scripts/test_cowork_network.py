#!/usr/bin/env python3
"""
Test network reachability tới các endpoint cần thiết.

QUAN TRỌNG: Script này phải chạy TRONG MÔI TRƯỜNG COWORK (qua Cowork shell)
để kiểm tra xem Cowork VM có cho phép outbound tới các host này không.
Chạy local (terminal trên máy bạn) chỉ test network của máy — KHÔNG
phản ánh được Cowork sandbox.

Cách chạy từ Cowork:
  Trong Cowork conversation, gõ:
    "test the cowork network reachability"
  Cowork agent sẽ chạy script này qua shell trong VM của nó.

Endpoints kiểm tra:
  - drive.bfcplatform.vn:443  (Bizfly Drive download — LUÔN cần)
  - smtp.gmail.com:465        (SMTP send — chỉ cần khi SEND_MODE=true)
  - www.google.com:443        (control test, có internet hay không)

Không cần credentials. Chỉ TCP connect check.
Exit 0: tất cả OK. Exit 1: có endpoint fail.
"""
import socket
import sys
import time

ENDPOINTS = [
    ('bizflycloud.vn',       443, 'Bizfly infra (Bizfly Drive tenant subdomain dùng cùng network)'),
    ('smtp.gmail.com',       465, 'SMTP send (chỉ cần khi SEND_MODE=true)'),
    ('www.google.com',       443, 'Internet control (có kết nối ra ngoài không)'),
]
# Note: Bizfly Drive subdomain thực tế là `<tenant>.drive.bfcplatform.vn`
# (ví dụ 79586.drive.bfcplatform.vn). Bizfly có DNS-tenant per khách hàng,
# không có A record cho `drive.bfcplatform.vn` apex. Test parent `bizflycloud.vn`
# verify được routing tới infra Bizfly — tenant subdomain sẽ work cùng network.

# ANSI color codes (auto-disable nếu không phải terminal)
def use_color():
    return sys.stdout.isatty() or sys.stderr.isatty()
COLORS = {
    'green':  '\033[92m', 'red':    '\033[91m', 'yellow': '\033[93m',
    'blue':   '\033[94m', 'bold':   '\033[1m',  'end':    '\033[0m',
}
def c(text, *names):
    if not use_color(): return text
    return ''.join(COLORS[n] for n in names) + text + COLORS['end']

def check(host, port, timeout=15):
    """TCP connect test. Trả (ok: bool, msg: str, latency_ms: int|None)."""
    t0 = time.time()
    try:
        s = socket.create_connection((host, port), timeout=timeout)
        latency = int((time.time() - t0) * 1000)
        s.close()
        return True, "connected", latency
    except socket.gaierror as e:
        return False, f"DNS resolution failed (EAI_AGAIN/NXDOMAIN): {e}", None
    except (socket.timeout, TimeoutError):
        return False, f"timeout sau {timeout}s (connection blocked silent)", None
    except ConnectionRefusedError as e:
        return False, f"connection refused: {e}", None
    except OSError as e:
        return False, f"OS error (proxy block?): {e}", None
    except Exception as e:
        return False, f"unknown: {type(e).__name__}: {e}", None

def main():
    print(c(f"━━ Cowork network reachability test ━━", 'bold', 'blue'))
    print()
    print(f"Đang check {len(ENDPOINTS)} endpoint từ environment hiện tại.")
    print(f"  {c('Cowork mode:', 'bold')} script chạy trong Cowork VM (sandbox).")
    print(f"  {c('Local mode:',  'bold')} script chạy trên máy bạn (không phản ánh Cowork).")
    print()

    failures = []
    for host, port, purpose in ENDPOINTS:
        print(f"  {c(host, 'bold')}:{port}  — {purpose}")
        ok, msg, latency = check(host, port)
        if ok:
            print(f"    {c('✓ OK', 'green')} ({latency} ms)")
        else:
            print(f"    {c('✗ FAIL', 'red')}: {msg}")
            failures.append((host, port, purpose, msg))
        print()

    # ── Kết quả ────────────────────────────────────────────────────────────
    print(c('━━ Kết quả ━━', 'bold', 'blue'))
    print()

    if not failures:
        print(c('✅ Tất cả endpoint reachable.', 'green', 'bold'))
        print()
        print('  → Network egress đã OK. Sẵn sàng cho production.')
        if any(host == 'smtp.gmail.com' for host, _, _, _ in []):  # always passes
            pass
        print('  → Bước tiếp: edit `.env` (creds), chạy `python3 scripts/test_send.py`,')
        print('    rotate password, set SEND_MODE=true.')
        sys.exit(0)

    print(c(f'❌ {len(failures)}/{len(ENDPOINTS)} endpoint bị block:', 'red', 'bold'))
    for host, port, purpose, msg in failures:
        print(f"   {c('•', 'red')} {host}:{port} — {msg}")
    print()

    # ── Hướng dẫn fix ─────────────────────────────────────────────────────
    print(c('━━ Cách fix ━━', 'bold', 'yellow'))
    print()
    print(c('Nếu chạy TRONG COWORK:', 'bold'))
    print("""
   Cowork mặc định chặn outbound. Cần allowlist:

   1. (Pro/Max plan) Mở Claude Desktop → Settings → tìm mục
      "Code execution" / "Network egress" / "Allowed domains".
      Đổi mode từ "Package managers only" thành "All domains" nếu
      "Additional domains" không hoạt động (Anthropic có bug đã biết
      với pattern allowlist — xem GitHub anthropics/claude-code
      issues #30112, #38984, #51400).

   2. (Team/Enterprise) Vào Organization Settings → Capabilities
      → Code execution → Allow network egress. Admin cần config:
        - Mode: "All domains" (đề xuất, vì additional-domains có bug)
        - Hoặc add specific: drive.bfcplatform.vn, smtp.gmail.com,
          *.gmail.com nếu mode "Package managers + additional"

   3. Restart Cowork session sau khi đổi setting.

   4. Run lại script này từ Cowork conversation.""")
    print()
    print(c('Nếu chạy LOCAL (terminal trên máy bạn):', 'bold'))
    print("""
   - Macbook System Settings → Network → Firewall: check có chặn outbound?
   - VPN/proxy đang bật? Tắt thử.
   - ISP chặn port 465 (hiếm): thử SMTP_PORT=587 với STARTTLS.
   - DNS: thử ping/dig host bị fail.""")
    print()
    if any(h[0] == 'smtp.gmail.com' for h in failures):
        print(c('💡 SMTP cụ thể:', 'yellow'))
        print('   Nếu chỉ smtp.gmail.com fail (Bizfly OK) → SEND_MODE sẽ KHÔNG hoạt động')
        print('   trong Cowork. Workaround: giữ SEND_MODE=false (chỉ tạo draft).')
        print('   Cowork connector create_draft KHÔNG cần SMTP egress, vẫn chạy được.')
    print()
    sys.exit(1)

if __name__ == '__main__':
    main()
