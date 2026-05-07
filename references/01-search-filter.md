# Bước 1 — Search Gmail + Filter

## Preflight (đầu run, chạy 1 lần)

Verify IMAP creds + mailbox accessible trước khi loop threads. Pipeline cần IMAP để fetch HTML body (workaround Anthropic Gmail connector limit — connector không trả HTML body cho mail HTML-only).

```bash
# KHÔNG suppress stderr — cần thấy actual error message để diagnose
python3 <SKILL_DIR>/scripts/fetch_email_body.py --check-creds
PRE_EC=$?
if [ $PRE_EC -ne 0 ]; then
    case $PRE_EC in
      1) echo "FATAL: GMAIL_EMAIL/GMAIL_APP_PASSWORD chưa set trong .env" ;;
      2) echo "FATAL: app password sai (auth fail)" ;;
      3) echo "FATAL: không resolve/select được All Mail mailbox" ;;
      7) echo "FATAL: IMAP network/SSL fail" ;;
      *) echo "FATAL: preflight exit $PRE_EC" ;;
    esac
    exit 1
fi
```

Nếu preflight fail → run dừng ngay với message rõ. Không tiếp tục loop threads vì sẽ fail mọi thread.

## Search threads

Dùng `imap_search_threads.py` (qua IMAP):

```bash
THREADS_JSON=$(python3 <SKILL_DIR>/scripts/imap_search_threads.py \
    --query 'subject:"DUYỆT - GenK" OR subject:"ĐĂNG - GenK"' \
    --newer-than 2d)
EC=$?
if [ $EC -ne 0 ]; then
    log "[fatal] search_threads fail (exit $EC)"
    exit 1
fi
```

Output là JSON array, mỗi entry có `thread_id` (hex), `latest_subject`, `latest_sender`, `latest_date`, `match_count`. Sorted by latest_date desc.

```bash
MAILS_FOUND=$(echo "$THREADS_JSON" | python3 -c 'import json, sys; print(len(json.load(sys.stdin)))')
```

## Lấy mail GỐC của thread (BATCH MODE — quan trọng để fit trong Cowork timeout)

⚠️ **QUAN TRỌNG**: KHÔNG gọi `imap_get_thread.py --thread-id <id>` trong loop với từng thread. Mỗi call mở fresh IMAP login → ~1-2s × 17 threads = >30s, có thể timeout. Phải dùng **batch mode**: 1 IMAP login cho tất cả threads.

```bash
# Build comma-separated list từ THREADS_JSON
THREAD_IDS=$(echo "$THREADS_JSON" | python3 -c '
import json, sys
threads = json.load(sys.stdin)
print(",".join(t["thread_id"] for t in threads))
')

# 1 call cho tất cả threads
ALL_THREAD_DATA=$(python3 <SKILL_DIR>/scripts/imap_get_thread.py --thread-ids "$THREAD_IDS")
EC=$?
if [ $EC -ne 0 ]; then
    log "[fatal] get_thread batch fail (exit $EC) — kiểm tra IMAP creds + network"
    exit 1
fi
```

Output JSON dict keyed by thread_id:
```json
{
  "19e001b8bf611d9b": {"messages": [...]},
  "19e001701c605c28": {"messages": [...]},
  "19df1462120df2ed": {"error": "thread không có message", "exit_code": 5}
}
```

Per thread access:
```bash
THREAD_DATA=$(echo "$ALL_THREAD_DATA" | python3 -c '
import json, sys
data = json.load(sys.stdin)
t = data["'"$THREAD_ID"'"]
if "error" in t:
    sys.exit(1)
print(json.dumps(t))
')
EC=$?
if [ $EC -ne 0 ]; then
    log "[error] thread $THREAD_ID: get_thread fail (xem ALL_THREAD_DATA)"
    ERRORS=$((ERRORS+1))
    continue
fi
```

Messages **sorted by date asc** — `THREAD_DATA.messages[0]` là mail gốc.

**Tuyệt đối không dùng reply** — body reply không có cấu trúc field DUYỆT.

## Filter 1 — Skip nếu senior reviewer đã reply

### Đọc skip-list 1 lần đầu run

Trước khi loop threads, agent chạy:

```bash
python3 <SKILL_DIR>/scripts/list_reviewers.py
```

Output là JSON array các email (đã lowercase + strip), ví dụ:

```json
["senior1@example.com", "senior2@example.com"]
```

Script đọc env `REVIEWER_EMAILS` trong `<SKILL_DIR>/.env` (comma-separated). Nếu env chưa set → script in `[]` + warning ra stderr → agent **không skip ai cả** (có thể tạo draft trùng với sếp). **Không hardcode email trong agent context** — luôn lấy từ script này.

Lưu kết quả vào biến `REVIEWERS` trong context để dùng cho mọi thread của run.

### Loop check

Loop qua tất cả `messages` của thread. Với mỗi message, lowercase `from` rồi check có chứa **bất kỳ** email nào trong `REVIEWERS` không:

→ Match → **SKIP toàn bộ thread**. Log: `[skip-reviewer] thread <id>: replied by <email>`. Tăng counter `SKIPPED_REVIEWER`.

Lý do: đây là sếp duyệt thủ công. Tạo draft auto sẽ trùng/sai.

## Filter 2 — Idempotency qua Gmail Drafts (BATCH MODE)

⚠️ Tương tự Filter 1, dùng batch mode 1 IMAP login cho tất cả threads:

```bash
ALL_DRAFT_CHECK=$(python3 <SKILL_DIR>/scripts/imap_check_thread_drafted.py --thread-ids "$THREAD_IDS")
EC=$?
if [ $EC -ne 0 ]; then
    log "[fatal] check_drafts batch fail (exit $EC)"
    exit 1
fi
```

Output JSON dict (top-level key `_drafts_mailbox` cho mailbox name):
```json
{
  "_drafts_mailbox": "[Gmail]/Drafts",
  "19e001b8bf611d9b": {"has_draft": false, "draft_count": 0},
  "19df1462120df2ed": {"has_draft": true, "draft_count": 1}
}
```

Per thread skip check:
```bash
HAS_DRAFT=$(echo "$ALL_DRAFT_CHECK" | python3 -c '
import json, sys
data = json.load(sys.stdin)
t = data.get("'"$THREAD_ID"'", {})
print(t.get("has_draft", False))
')
if [ "$HAS_DRAFT" = "True" ]; then
    log "[skip-existing] thread $THREAD_ID: draft đã tồn tại"
    SKIPPED_EXISTING=$((SKIPPED_EXISTING+1))
    continue
fi
```

**Plus dedup ở script layer**: `imap_create_draft.py` tự pre-check `X-Cowork-Dedup-Key` header trước APPEND — race-safe nếu 2 runs concurrent với cùng body.

> 💡 **Tip cho Cowork**: gọi cả 2 batch (`get_thread` + `check_drafted`) ngay sau search threads, cache vào biến shell. Sau đó loop threads dùng cached data — chỉ cần thêm IMAP call cho `imap_create_draft.py` (per draft), `fetch_email_body.py` (per DUYỆT thread cần body). Tổng IMAP login ~5-7 cho run 17 threads, rất xa timeout 45s.

## Phân loại mail_type

Từ `original.subject` (case-insensitive):

- Chứa `DUYỆT - GenK` → `duyet` → tiếp tục `references/02-duyet-pipeline.md`
- Chứa `ĐĂNG - GenK` → `dang` → tiếp tục `references/03-dang-placeholder.md`
- Không match → log warning + skip

## Decision tree tóm tắt (BATCH MODE)

```
preflight: fetch_email_body.py --check-creds → fail → exit 1
REVIEWERS ← list_reviewers.py
threads ← imap_search_threads.py        # 1 IMAP login
THREAD_IDS = ",".join(t.thread_id for t in threads)

# 2 batch calls — tổng 2 IMAP logins cho TẤT CẢ threads metadata + drafts check
all_thread_data ← imap_get_thread.py --thread-ids $THREAD_IDS
all_draft_check ← imap_check_thread_drafted.py --thread-ids $THREAD_IDS

for thread in threads:
    thread_data ← all_thread_data[thread.thread_id]
    if "error" in thread_data: ERRORS += 1; continue

    if any(any(r in m.from.lower() for r in REVIEWERS) for m in thread_data.messages):
        SKIPPED_REVIEWER += 1; log; continue

    if all_draft_check[thread.thread_id].has_draft:
        SKIPPED_EXISTING += 1; log; continue

    original ← thread_data.messages[0]
    if 'DUYỆT - GenK' in original.subject.upper():
        → 02-duyet-pipeline.md   # fetch_email_body + create_draft (per thread)
    elif 'ĐĂNG - GenK' in original.subject.upper():
        → 03-dang-placeholder.md
    else:
        log warning; continue
```

**IMAP login budget per run** (17 threads, ~5 unfiltered DUYỆT):
- 1 (search) + 1 (get_thread batch) + 1 (check_drafted batch) + 5 (fetch_body per DUYỆT) + 5 (create_draft per DUYỆT) = **~13 logins** trong ~25-30s.

## Counters cần track trong run

- `MAILS_FOUND` = tổng threads từ search
- `DRAFTED` = draft tạo thành công
- `SKIPPED_REVIEWER` = skip do sếp đã reply
- `SKIPPED_EXISTING` = skip do đã có draft
- `DANG` = ĐĂNG threads (placeholder)
- `ERRORS` = thread lỗi giữa chừng

→ In ra ở dòng cuối SKILL Bước 3.
