# Bước 2a — DUYỆT Pipeline

Áp dụng khi `mail_type='duyet'`. Tuần tự 6 step. Nếu lỗi giữa chừng: log + đi thread tiếp.

**Init đầu run** (trước khi loop threads):
```bash
IMAP_FAILS=0           # Counter cho circuit breaker (Step 1a)
IMAP_MAX_FAILS=${IMAP_MAX_FAILS:-3}  # Default 3, override qua env
```

## Step 1 — Fetch HTML body + extract field từ mail GỐC

### Step 1a — Fetch HTML body qua IMAP

**Tại sao cần IMAP**: Anthropic Gmail connector chỉ trả `text/plain` part. Mail DUYỆT từ kpi.admicro.vn là HTML-only → connector trả body rỗng → không parse được Bizfly URL. Workaround: fetch raw RFC822 qua IMAP, parse text/html part. Issues #48713, #50298 trên GitHub Anthropic, chưa fix.

```bash
fetch_with_retry() {
    python3 <SKILL_DIR>/scripts/fetch_email_body.py \
        --thread-id "$1" \
        --gmail-msg-id "$2"
}

# Pass --gmail-msg-id từ connector messages[0].id để X-GM-MSGID exact match
BODY=$(fetch_with_retry "$THREAD_ID" "$MSG_ID")
EC=$?

# Deterministic retry cho transient (exit 7) — sleep 5s + retry once
if [ $EC -eq 7 ]; then
    sleep 5
    BODY=$(fetch_with_retry "$THREAD_ID" "$MSG_ID")
    EC=$?
fi

case $EC in
  0)
    # Success — reset breaker counter
    IMAP_FAILS=0
    ;;
  1|2|3)
    # Infra issue (creds/auth/mailbox) — trip breaker
    IMAP_FAILS=$((IMAP_FAILS+1))
    log "[error] thread $THREAD_ID: IMAP infra (exit $EC) — fail $IMAP_FAILS/$IMAP_MAX_FAILS"
    if [ $IMAP_FAILS -ge $IMAP_MAX_FAILS ]; then
        log "[fatal] dừng run sớm: $IMAP_FAILS lỗi IMAP infra liên tiếp"
        exit 1
    fi
    ERRORS=$((ERRORS+1)); continue
    ;;
  4|5|6)
    # Data issue (bad thread-id, empty thread, no body) — KHÔNG trip breaker, KHÔNG reset
    log "[error] thread $THREAD_ID: data issue exit $EC"
    ERRORS=$((ERRORS+1)); continue
    ;;
  7)
    # Transient sau retry vẫn fail — count vào breaker
    IMAP_FAILS=$((IMAP_FAILS+1))
    log "[error] thread $THREAD_ID: IMAP transient (exit 7) sau retry — fail $IMAP_FAILS/$IMAP_MAX_FAILS"
    if [ $IMAP_FAILS -ge $IMAP_MAX_FAILS ]; then
        log "[fatal] dừng run sớm: $IMAP_FAILS lỗi transient liên tiếp"
        exit 1
    fi
    ERRORS=$((ERRORS+1)); continue
    ;;
  *)
    log "[error] thread $THREAD_ID: unknown exit $EC"
    ERRORS=$((ERRORS+1)); continue
    ;;
esac
```

**Retry semantics**:
- `exit 7` (transient network/SSL/parse) → sleep 5s → retry **once**
  - Retry success → reset `IMAP_FAILS=0`
  - Retry fail (any exit) → fall through case branch để count vào breaker
- `exit 1/2/3` (infra creds/auth/mailbox) → KHÔNG retry, count vào breaker
- `exit 4/5/6` (data per-thread) → KHÔNG retry, KHÔNG count, KHÔNG reset (data lỗi không nên hide infra issue đang xen kẽ)

**Exit codes** từ `fetch_email_body.py`:

| Code | Ý nghĩa |
|------|---------|
| 0 | OK, body ra stdout |
| 1 | Creds missing trong .env |
| 2 | IMAP login fail (auth) |
| 3 | Mailbox select fail |
| 4 | Thread ID format invalid |
| 5 | Thread thật sự không có message |
| 6 | Body parse fail (không text/html lẫn text/plain) |
| 7 | Network/IMAP transient / parse metadata |

### Step 1b — Extract field từ HTML body

Body fetched ở Step 1a là HTML đơn giản (mail từ kpi.admicro.vn):

```html
<p>Bạn có yêu cầu <strong>Duyệt bài</strong> như sau:</p>
<p>Site (Kênh): GenK - ... - Giá trị đăng bài: 3,000,000vnd</p>
<p>Số Hợp đồng: QC2031025 - Nhãn hàng: Vi Tính Nguyên Kim - Ngày giờ đăng:</p>
<p>Link file Nội dung bài viết: <a href='https://...drive.bfcplatform.vn/.../<token>'>file.docx</a></p>
<p>Tiêu đề bài viết: Doanh nghiệp tối ưu chi phí, gia tăng hiệu suất nhờ HP Poly</p>
```

Extract (regex hoặc đọc thông minh, case-insensitive cho key):

| Cần lấy | Pattern |
|---------|---------|
| `nhan_hang` | sau `Nhãn hàng:` |
| `tieu_de_bai` | sau `Tiêu đề bài viết:` hoặc `Tiêu đề:` (BẮT BUỘC — dùng cho reply) |
| `bizfly_url` | href đầu tiên chứa `drive.bfcplatform.vn` hoặc `drive.bizfly.vn` (BẮT BUỘC — không có thì lỗi) |

Field optional (`so_hop_dong`, `gia_tri`...) — không cần extract trong Cowork-Lite. Reply không in lại các trường này.

**Nếu `bizfly_url` rỗng**: log `[error] thread <id>: không tìm thấy Bizfly URL`, tăng `ERRORS`, đi thread tiếp (data issue, không trip breaker).

## Step 2 — Fetch Bizfly document

```bash
mkdir -p /tmp/pr-review/<thread_id>
python3 <SKILL_DIR>/scripts/fetch_document.py \
  "<bizfly_url>" /tmp/pr-review/<thread_id>/
```

- Exit 0 → stdout là path file đã tải. Lưu `DOC_FILE`.
- Exit ≠ 0 → log `[error] thread <id>: Bizfly fetch fail`, `ERRORS += 1`, đi thread tiếp.

## Step 3 — Convert sang markdown

```bash
python3 -m markitdown "<DOC_FILE>" > /tmp/pr-review/<thread_id>/content.md
```

Yêu cầu deps `markitdown` đã install (xem `setup.sh` hoặc `requirements.txt`).

## Step 4 — Review tiêu chí (INLINE)

**Đọc `<SKILL_DIR>/rules.md`** — danh sách tiêu chí (số lượng có thể thay đổi, đừng hardcode).

**Đọc `/tmp/pr-review/<thread_id>/content.md`** — nội dung bài.

Tự reason xem mỗi tiêu chí 1-6 có vi phạm không. Cấu trúc kết quả (nội bộ, không cần ghi DB):

```json
{
  "verdict": "pass" | "fail",
  "violations": [
    {
      "rule_id": 1-6,
      "rule_name": "<tên tiêu chí ngắn>",
      "excerpt": "<trích nguyên văn ≤200 ký tự>",
      "details": "<vì sao vi phạm>",
      "suggestion": "<cách sửa cụ thể, tiếng Việt có dấu>"
    }
  ],
  "summary": "<tóm tắt 1-2 câu>"
}
```

Quy tắc:
- `verdict='pass'` ⟺ `violations=[]`
- Mỗi `rule_id` chỉ xuất hiện 1 lần (gộp nhiều ví dụ vào details/excerpt)
- `excerpt` lấy nguyên văn, không paraphrase

## Step 5 — Build reply text → file

Đọc `references/04-reply-templates.md` để lấy template chuẩn (PASS/FAIL). Build text plain UTF-8.

**LƯU NGAY ra file** (cần thiết cho cả 2 path send/draft phía sau):
```bash
cat > /tmp/pr-review/<thread_id>/reply.txt << 'EOF'
<reply text>
EOF
```

Thay `<TIEU_DE_BAI>`, `<rule_id>`, `<rule_name>`, `<details>`, `<suggestion>`, `<summary>` bằng giá trị thực trước khi viết file.

## Step 6 — Gửi/Draft (theo SEND_MODE)

Đọc `references/04-reply-templates.md` mục "Addressing" để build `to` + `cc` (Reply-To + reply-all, loại self).

### Check SEND_MODE từ `.env`

```bash
SEND_MODE=$(grep -E '^SEND_MODE=' <SKILL_DIR>/.env 2>/dev/null | cut -d= -f2 | tr -d ' "')
```

Nếu `SEND_MODE=true` → nhánh **6A**. Mặc định / khác → nhánh **6B**.

### Nhánh 6A — Send qua SMTP

```bash
python3 <SKILL_DIR>/scripts/send_email.py \
  --to "<to_email>" \
  --cc "<cc1,cc2,cc3>" \
  --subject "Re: <original_subject>" \
  --in-reply-to "<<original_message_id>>" \
  --references "<<original_references_chain>>" \
  --body-file /tmp/pr-review/<thread_id>/reply.txt
```

Xử lý exit code:
- **Exit 0** → gửi OK. Parse JSON output. `SENT += 1`. Log: `[ok-sent] thread <id>: gửi tới <to>, cc=<n>`.
- **Exit 10/11/12** → config thiếu (SEND_MODE/GMAIL_EMAIL/GMAIL_APP_PASSWORD). Log error rõ cho user. **FALLBACK** sang 6B (tạo draft).
- **Exit 30** → SMTP auth failed (sai password). Log error. **FALLBACK** sang 6B.
- **Exit 31/32/33** → SMTP/network error. Log error. **FALLBACK** sang 6B.
- **Exit 20/99** → body file lỗi / unknown. Log error, count `ERRORS += 1`, đi thread tiếp (không fallback vì có thể repeat lỗi).

Output stderr của script đã human-readable — relay nguyên văn cho user thấy trong Cowork log.

### Nhánh 6B — Tạo Gmail Draft (default)

Dùng Gmail connector:
```
create_draft(
  thread_id: <thread_id>,
  to: <to_email>,
  cc: <cc_list joined by ", ">,
  subject: "Re: <original_subject>",  (chỉ thêm "Re: " nếu chưa có)
  body: <reply text — đọc từ file /tmp/pr-review/<thread_id>/reply.txt>,
)
```

Xử lý:
- Thành công → `DRAFTED += 1`. Log: `[ok-draft] thread <id>: drafted (verdict=<v>, violations=<n>)`.
- Connector lỗi → `ERRORS += 1`. Log: `[error] thread <id>: create_draft fail: <msg>`. Đi thread tiếp.

## Cleanup tmp

Có thể xoá `/tmp/pr-review/<thread_id>/` sau khi xong (tuỳ chọn). Nếu giữ lại: thư mục tự dọn theo policy `/tmp/` của hệ thống.
