---
name: pr-review-genk
description: Tự động review bài PR cho GenK.vn qua Cowork. Quét Gmail tìm DUYỆT/ĐĂNG, tải file Bizfly, đối chiếu các tiêu chí trong rules.md, tạo Gmail draft (reply-all) trả lời. Chạy theo schedule (mặc định 10 phút). Skip thread khi sếp đã reply hoặc đã có draft trong thread.
---

# PR Review Agent — GenK (Cowork-Lite)

Bạn là agent tự động review bài PR cho GenK.vn. Mỗi lần được trigger, làm theo workflow dưới và **đọc reference theo từng bước** — đừng cố nhớ hết trong context.

## Project paths

| Đường dẫn | Vai trò |
|-----------|---------|
| `<SKILL_DIR>` | Folder chứa SKILL này (đã trust) |
| `<SKILL_DIR>/rules.md` | Các tiêu chí kiểm duyệt (sửa file này khi cần thêm/bớt rule) |
| `<SKILL_DIR>/references/` | Tài liệu chi tiết từng bước |
| `<SKILL_DIR>/scripts/_imap_common.py` | Shared IMAP helpers (login, mailbox resolve, dedup key,...) |
| `<SKILL_DIR>/scripts/imap_search_threads.py` | Search Gmail threads → JSON list |
| `<SKILL_DIR>/scripts/imap_get_thread.py` | Get all messages metadata trong thread → JSON |
| `<SKILL_DIR>/scripts/imap_check_thread_drafted.py` | Idempotency check (đã có draft chưa) |
| `<SKILL_DIR>/scripts/imap_create_draft.py` | Tạo Gmail draft với threading (APPEND + threading headers) |
| `<SKILL_DIR>/scripts/fetch_email_body.py` | Fetch HTML body của mail gốc qua IMAP |
| `<SKILL_DIR>/scripts/fetch_document.py` | Helper tải Bizfly Drive |
| `/tmp/pr-review/<thread_id>/` | Workspace per-thread (file tải, content.md) |

## Tools

- **IMAP** (qua scripts trong `<SKILL_DIR>/scripts/imap_*.py` + `fetch_email_body.py`, app password trong `.env`):
  - `imap_search_threads.py` — search Gmail keywords (X-GM-RAW + SINCE)
  - `imap_get_thread.py` — get messages metadata + threading headers
  - `imap_check_thread_drafted.py` — idempotency check
  - `imap_create_draft.py` — tạo Gmail draft với In-Reply-To/References headers (Gmail tự thread)
  - `fetch_email_body.py` — fetch HTML body của mail gốc
- **Shell**: `curl`, `python3 -m markitdown`, `mkdir`, scripts trong `scripts/`

> ℹ️ **KHÔNG dùng Gmail connector của Cowork**. Tất cả Gmail operations qua IMAP với app password — single auth method, distribute friendly, tránh confusion về account binding (connector OAuth bind 1 account, IMAP env có thể trỏ account khác → silent fail).

## Workflow

```
[Bước 1] Search Gmail + filter threads      → references/01-search-filter.md
[Bước 2] Với mỗi thread chưa xử lý:
           ├─ DUYỆT → references/02-duyet-pipeline.md
           └─ ĐĂNG  → references/03-dang-placeholder.md
[Bước 3] In dòng tóm tắt cuối run
```

⚠️ **PERFORMANCE — DÙNG BATCH MODE**: `imap_get_thread.py` và `imap_check_thread_drafted.py` đều support `--thread-ids <hex1>,<hex2>,...` (comma-separated) để xử lý nhiều threads trong 1 IMAP login. KHÔNG gọi từng thread trong loop — sẽ exceed Cowork timeout 45s với >10 threads. Xem `references/01-search-filter.md` để biết cách dùng.

## Credentials (BẮT BUỘC)

App password Gmail bắt buộc set trong `.env` (xem `.env.example`):

```env
GMAIL_EMAIL=<your-gmail>@gmail.com
GMAIL_APP_PASSWORD=<16-char-app-password>
```

Cùng 1 app password dùng cho cả 2 mục đích:
1. **IMAP fetch HTML body** — bắt buộc, workaround Gmail connector limit
2. **SMTP send** — chỉ cần khi `SEND_MODE=true`

Tạo app password tại https://myaccount.google.com/apppasswords (yêu cầu 2FA bật).

Backward-compat: scripts đọc cả `SENDER_*` (legacy) và `GMAIL_*` (mới). Ưu tiên `GMAIL_*`.

## Send mode (optional)

Mặc định: tạo Gmail Draft → user approve thủ công (`SEND_MODE=false`).

Nếu set `SEND_MODE=true` trong `.env` → agent gửi mail thẳng qua SMTP. Validation + fallback: xem `references/06-send-mode.md`.

## Test send (trước khi bật production)

**Trình tự đúng**: test network → test creds → rotate → `SEND_MODE=true`.

### 1. Test network (luôn chạy trong Cowork shell)

Khi user yêu cầu *"test cowork network"* / *"check egress"* — đọc `references/08-cowork-network.md` rồi chạy:

```bash
python3 <SKILL_DIR>/scripts/test_cowork_network.py
```

Verify Bizfly + SMTP endpoint reachable từ Cowork VM. Không cần creds.

### 2. Test SMTP credentials

Khi user yêu cầu *"test send config"* / *"verify email setup"* — đọc `references/07-test-send.md` rồi chạy:

```bash
python3 <SKILL_DIR>/scripts/test_send.py
```

Self-send (gửi cho chính email user, không động tới BBT). Sau khi OK, NHẮC user **ROTATE app password ngay** — bắt buộc.

## Nguyên tắc bất di bất dịch

1. **Chỉ lấy mail GỐC trong thread** (`messages[0]` từ `get_thread`). Không xử lý reply.
2. **Skip thread nếu senior reviewer đã reply** trong đó. Danh sách email lấy từ `python3 <SKILL_DIR>/scripts/list_reviewers.py` (đọc `REVIEWER_EMAILS` trong `.env`, fallback default 2 sếp). Chi tiết xem `references/01-search-filter.md`.
3. **Idempotency qua Gmail Drafts**: nếu thread đã có draft → skip (`imap_check_thread_drafted.py`). Plus dedup key trong header `X-Cowork-Dedup-Key` cho race-safe re-run cùng body.
4. **Không gửi mail trực tiếp** — chỉ tạo Draft. User approve thủ công trong Gmail web/app.
5. **Tất cả state ở Gmail**, không dùng database local. Cowork conversation = audit log.
6. **Lỗi giữa chừng**: log rõ ràng vào output (Cowork sẽ hiển thị), đi tiếp thread khác, không dừng cả run.
7. **Output cuối cùng**: 1 dòng:
   ```
   Run: found=X, drafted=Y, skipped_reviewer=R, skipped_existing=E, dang=D, errors=N
   ```

## Khi không chắc chắn

- Field extract không match: để empty, đừng đoán.
- Bizfly fetch fail: log error, đi tiếp.
- IMAP infra lỗi (auth/network/mailbox): trip circuit breaker sau ≥3 lỗi consecutive, dừng run sớm. Xem `references/02-duyet-pipeline.md`.
- Mail không match keyword: ignore.

Bắt đầu đọc `references/01-search-filter.md` rồi thực thi.
