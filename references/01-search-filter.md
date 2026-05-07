# Bước 1 — Search Gmail + Filter

## Search threads

Dùng Gmail connector `search_threads`:

```
query: (subject:"DUYỆT - GenK" OR subject:"ĐĂNG - GenK") newer_than:2d
```

Trả về list threads có hoạt động trong 48h. Đếm `MAILS_FOUND = len(threads)`.

## Lấy mail GỐC của thread

Với mỗi thread:

```
messages = get_thread(thread_id).messages
original = messages[0]   # mail đầu tiên (chronological)
```

Gmail API trả messages theo thứ tự thời gian, message[0] là mail gốc (DUYỆT/ĐĂNG request đầu tiên). **Tuyệt đối không dùng reply** — body reply không có cấu trúc field DUYỆT.

## Filter 1 — Skip nếu senior reviewer đã reply

### Đọc skip-list 1 lần đầu run

Trước khi loop threads, agent chạy:

```bash
python3 <SKILL_DIR>/scripts/list_reviewers.py
```

Output là JSON array các email (đã lowercase + strip), ví dụ:

```json
["tuanlehoang@genk.vn", "hainguyenquang@genk.vn"]
```

Script đọc env `REVIEWER_EMAILS` trong `<SKILL_DIR>/.env` (comma-separated). Nếu env không set → fallback default 2 sếp. **Không hardcode email trong agent context** — luôn lấy từ script này.

Lưu kết quả vào biến `REVIEWERS` trong context để dùng cho mọi thread của run.

### Loop check

Loop qua tất cả `messages` của thread. Với mỗi message, lowercase `from` rồi check có chứa **bất kỳ** email nào trong `REVIEWERS` không:

→ Match → **SKIP toàn bộ thread**. Log: `[skip-reviewer] thread <id>: replied by <email>`. Tăng counter `SKIPPED_REVIEWER`.

Lý do: đây là sếp duyệt thủ công. Tạo draft auto sẽ trùng/sai.

## Filter 2 — Idempotency qua Gmail Drafts

Trước khi xử lý, check thread đã có draft do agent tạo chưa:

```
drafts = search_drafts(query=f"thread:{thread_id}")
# Nếu drafts không rỗng → đã từng xử lý → skip
```

→ **SKIP nếu có draft**. Log: `[skip-existing] thread <id>: draft đã tồn tại`. Tăng counter `SKIPPED_EXISTING`.

Đây là cơ chế thay cho local DB: Gmail chính nó là single source of truth. Không cần SQLite.

## Phân loại mail_type

Từ `original.subject` (case-insensitive):

- Chứa `DUYỆT - GenK` → `duyet` → tiếp tục `references/02-duyet-pipeline.md`
- Chứa `ĐĂNG - GenK` → `dang` → tiếp tục `references/03-dang-placeholder.md`
- Không match → log warning + skip

## Decision tree tóm tắt

```
REVIEWERS ← json.parse(run("python3 <SKILL_DIR>/scripts/list_reviewers.py"))
threads ← search_threads(query)
for thread in threads:
    messages ← get_thread(thread.id).messages
    if any(any(r in m.from.lower() for r in REVIEWERS) for m in messages):
        SKIPPED_REVIEWER += 1; log; continue

    drafts ← search_drafts(f"thread:{thread.id}")
    if drafts:
        SKIPPED_EXISTING += 1; log; continue

    original ← messages[0]
    if 'DUYỆT - GenK' in original.subject.upper():
        → 02-duyet-pipeline.md
    elif 'ĐĂNG - GenK' in original.subject.upper():
        → 03-dang-placeholder.md
    else:
        log warning; continue
```

## Counters cần track trong run

- `MAILS_FOUND` = tổng threads từ search
- `DRAFTED` = draft tạo thành công
- `SKIPPED_REVIEWER` = skip do sếp đã reply
- `SKIPPED_EXISTING` = skip do đã có draft
- `DANG` = ĐĂNG threads (placeholder)
- `ERRORS` = thread lỗi giữa chừng

→ In ra ở dòng cuối SKILL Bước 3.
