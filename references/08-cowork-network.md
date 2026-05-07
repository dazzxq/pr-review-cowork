# Cowork Network Egress Test

Verify Cowork VM cho phép outbound network tới các endpoint cần thiết. Phải chạy **trong Cowork conversation** (qua shell trong VM của Cowork) — chạy local terminal chỉ test máy bạn, không phản ánh sandbox của Cowork.

## Khi nào dùng

- Lần đầu setup, trước khi để task scheduled chạy
- Khi pipeline báo lỗi "fetch fail" / SMTP timeout / DNS fail
- Sau khi đổi network egress settings của Cowork
- Sau khi update Claude Desktop (config có thể reset)

## Cách chạy từ Cowork

User gõ trong Cowork conversation:

```
Test the cowork network reachability
```

Cowork agent đọc file này, gọi:

```bash
python3 <SKILL_DIR>/scripts/test_cowork_network.py
```

→ relay output cho user thấy kết quả các endpoint.

## Endpoints kiểm tra

| Endpoint | Cần khi | Bị chặn → hậu quả |
|----------|---------|-------------------|
| `bizflycloud.vn:443` | LUÔN | Không tải được Bizfly Drive → toàn bộ DUYỆT pipeline fail |
| `smtp.gmail.com:465` | `SEND_MODE=true` | SMTP fail → fallback sang draft mode (vẫn an toàn) |
| `www.google.com:443` | Control | Cowork không có Internet (rare, chắc Cowork bug) |

## Cowork Network Egress configuration

Cowork mặc định **chặn outbound** đa số domain (chỉ Anthropic API + một số package managers được auto-allow). Cần config thủ công.

### Pro / Max plan (single-user)

Mở Claude Desktop:
1. **Settings** → tìm mục về "Code execution" / "Network egress" / "Allowed domains"
2. Mode dropdown: chọn **"All domains"** (đề xuất, vì additional-domains list có known bugs)
3. Restart Cowork session

Note: theo các bug report ([anthropics/claude-code#30112](https://github.com/anthropics/claude-code/issues/30112), [#38984](https://github.com/anthropics/claude-code/issues/38984), [#51400](https://github.com/anthropics/claude-code/issues/51400)), tính năng "Package managers only + additional domains" chưa stable — domain custom add vào không được apply. Nếu cần restrict, dùng "All domains" và chấp nhận trade-off.

### Team / Enterprise plan

**Organization Settings** → **Capabilities** → **Code execution** → **Allow network egress**

Admin config:
- Mode: "All domains" (recommended)
- Hoặc "Package managers only + additional" với:
  - `bizflycloud.vn`, `*.bfcplatform.vn` (tenant subdomain)
  - `smtp.gmail.com` (chỉ khi cần SEND_MODE)
  - `*.gmail.com`

→ User cần restart Cowork session sau khi admin đổi setting.

## Sample output

### All OK

```
━━ Cowork network reachability test ━━

  bizflycloud.vn:443  — Bizfly infra
    ✓ OK (45 ms)

  smtp.gmail.com:465  — SMTP send
    ✓ OK (39 ms)

  www.google.com:443  — Internet control
    ✓ OK (25 ms)

━━ Kết quả ━━
✅ Tất cả endpoint reachable.
  → Network egress đã OK. Sẵn sàng cho production.
```

### Bị chặn

```
  bizflycloud.vn:443  — Bizfly infra
    ✗ FAIL: timeout sau 15s (connection blocked silent)

❌ 1/3 endpoint bị block:
   • bizflycloud.vn:443 — timeout sau 15s

━━ Cách fix ━━
Nếu chạy TRONG COWORK:
   1. Mở Claude Desktop → Settings → "Code execution" / "Network egress"
   2. Đổi mode → "All domains"
   3. Restart Cowork session
   4. Run lại
```

## Phân loại failure mode

| Triệu chứng | Nguyên nhân khả năng |
|-------------|----------------------|
| `DNS resolution failed (EAI_AGAIN/NXDOMAIN)` | Cowork chặn DNS lookup, hoặc domain không tồn tại |
| `timeout sau 15s` | Cowork firewall drop silent (mặc định "Package managers only") |
| `connection refused` | Server từ chối (rare) hoặc proxy chặn |
| `OS error (proxy block?)` | MITM proxy của Cowork chặn ([#30861](https://github.com/anthropics/claude-code/issues/30861)) |

## Khi không thể allowlist (workspace lock-down)

Nếu admin không cho phép expand egress:

- **Bizfly fail** → flow này không dùng được trong Cowork. Phải dùng Path A (launchd local) hoặc workaround khác (như chạy fetch trên máy local rồi sync).
- **SMTP fail** → giữ `SEND_MODE=false`. Cowork connector `create_draft` không cần SMTP egress, vẫn chạy được. User chỉ phải approve manual trong Gmail.

## Phân biệt với `test_send.py`

- **`test_cowork_network.py`** (file này): kiểm tra **endpoint reachable không** từ environment. Không cần creds. Chạy đầu tiên.
- **`test_send.py`**: kiểm tra **SMTP credentials có đúng không** + send self-test mail. Cần email + password. Chạy sau khi network OK.

Trình tự đúng: `test_cowork_network.py` → fix egress nếu fail → `test_send.py` → rotate creds → `SEND_MODE=true` → production.
