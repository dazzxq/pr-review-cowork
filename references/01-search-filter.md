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

## Filter 1 — Skip nếu sếp đã reply

Loop qua tất cả `messages` của thread. Nếu **bất kỳ** message nào có `from` chứa 1 trong:

- `tuanlehoang@genk.vn`
- `hainguyenquang@genk.vn`

→ **SKIP toàn bộ thread**. Log: `[skip-reviewer] thread <id>: replied by <email>`. Tăng counter `SKIPPED_REVIEWER`.

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
threads ← search_threads(query)
for thread in threads:
    messages ← get_thread(thread.id).messages
    if any(m.from in {tuanlehoang, hainguyenquang} for m in messages):
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
