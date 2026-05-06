# SEND_MODE — gửi mail thẳng qua SMTP

**Mặc định: OFF**. Agent tạo Gmail Draft (an toàn, user approve thủ công). 
Bật mode này khi đã review đủ + tự tin để auto-send.

## So sánh

| | SEND_MODE=false (default) | SEND_MODE=true |
|---|---|---|
| Cách hoạt động | Gmail connector tạo Draft (OAuth) | SMTP send (app password) |
| Auth | OAuth qua Cowork connector | App password trong `.env` |
| User action | Phải mở Gmail Drafts → Send tay | Không cần — mail tự đi |
| Bảo mật | Cao (OAuth refresh token, revoke dễ) | Thấp hơn (password tĩnh trong file) |
| Reversibility | Cao (xoá draft trước khi send) | Thấp (mail đã đi rồi) |
| Phù hợp | Demo / test / QA pipeline | Production khi tin pipeline 100% |

## Bật SEND_MODE

### 1. Tạo `.env` từ template

```bash
cd <SKILL_DIR>
cp .env.example .env
```

`.env` đã được `.gitignore` — không lo commit nhầm.

### 2. Tạo Google App Password

- Vào https://myaccount.google.com/apppasswords
- Yêu cầu: 2-Step Verification đã bật (https://myaccount.google.com/signinoptions/two-step-verification)
- Tạo password mới, đặt tên gợi nhớ ("PR Review Cowork")
- Copy 16 ký tự (Google hiển thị có dấu cách, OK paste cả dấu cách — script tự strip)

### 3. Điền `.env`

```bash
SEND_MODE=true
SENDER_EMAIL=your@gmail.com           # email Gmail/Workspace của bạn
SENDER_APP_PASSWORD=xxxx xxxx xxxx xxxx
```

### 4. (Cowork) Allow SMTP egress

Cowork mặc định chặn outbound network. Mở Cowork settings → Network egress → allow:
```
smtp.gmail.com:465
```

Nếu Cowork chưa cho phép, agent sẽ exit 33 (network error) và fallback sang draft.

## Validation behavior — script `send_email.py`

Script validate theo thứ tự, exit ngay khi gặp lỗi:

| Exit | Vấn đề | Hành động của agent |
|------|--------|---------------------|
| 0 | OK, mail đã gửi | Log success, count SENT |
| 10 | `SEND_MODE` chưa true | Fallback sang draft |
| 11 | `SENDER_EMAIL` trống | Fallback sang draft + log warning |
| 12 | `SENDER_APP_PASSWORD` trống | Fallback sang draft + log warning |
| 20 | Body file lỗi (không có / rỗng) | Log error, count ERROR, KHÔNG fallback (lỗi nội bộ) |
| 30 | SMTP auth failed | Fallback sang draft + log error rõ |
| 31 | Recipient bị reject | Fallback sang draft + log error |
| 32 | SMTP exception khác | Fallback sang draft + log error |
| 33 | Network/timeout (Cowork egress chặn?) | Fallback sang draft + log error |
| 99 | Unknown | Fallback sang draft + log error |

Stderr của script đã chứa thông điệp tiếng Việt human-readable. Agent **relay nguyên văn** vào Cowork conversation để user thấy.

## Edge cases được handle

1. **Account không bật 2FA** → tạo app password fail từ trước. Khi gửi → exit 30 (auth fail).
2. **Workspace admin tắt app password** → tương tự, exit 30. User cần liên hệ IT.
3. **App password có dấu cách** (Google copy với spaces) → script tự strip.
4. **`SENDER_EMAIL` khác account đã connect Cowork** → vẫn gửi được (SMTP auth dùng SENDER_EMAIL), nhưng Sent Mail đi vào account đó, không phải account Cowork. Khuyến nghị: trùng nhau.
5. **Self trong cc list** → script tự loại.
6. **`to` cũng có trong `cc`** (lỡ duplicate) → script tự loại khỏi cc.
7. **Empty body** → exit 20.
8. **Mất kết nối giữa chừng** → exit 33, fallback draft.
9. **Gmail rate limit** (gửi quá nhiều/giờ) → exit 32, fallback. User check Gmail Sent Mail vs Drafts để xác định mail nào đã đi.
10. **`.env` syntax sai** (e.g. comment không có `#`) → script vẫn chạy với fallback OS env, hoặc treat dòng đó như var. Lỗi sẽ surface qua exit 11/12.

## Output khi gửi thành công

JSON ra stdout:
```json
{
  "mode": "sent",
  "message_id": "<random@mail.gmail.com>",
  "to": "kpi_2@admicro.vn",
  "cc": ["dangtin@admicro.vn", "genk@admicro.vn", "..."],
  "subject": "Re: [A02] - DUYỆT - GenK - ...",
  "sender": "your@gmail.com"
}
```

Agent count `SENT += 1`. Mail đã đi, Gmail tự lưu copy vào `[Gmail]/Sent Mail`.

## Tắt SEND_MODE tạm thời

Đổi `.env`:
```
SEND_MODE=false
```

Lần run kế tiếp về draft mode. Không cần restart Cowork hay xoá credentials.

## Xoá credentials hoàn toàn

```bash
rm <SKILL_DIR>/.env
```

Hoặc revoke app password tại https://myaccount.google.com/apppasswords (Google sẽ vô hiệu hoá ngay).
