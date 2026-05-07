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

## Lấy mail GỐC của thread

Với mỗi thread (loop qua `THREADS_JSON`):

```bash
THREAD_ID=$(...)  # thread_id từ search result
THREAD_DATA=$(python3 <SKILL_DIR>/scripts/imap_get_thread.py --thread-id "$THREAD_ID")
EC=$?
if [ $EC -ne 0 ]; then
    case $EC in
      5) log "[error] thread $THREAD_ID: empty (rare)"; ERRORS=$((ERRORS+1)); continue ;;
      *) log "[error] thread $THREAD_ID: get_thread exit $EC"; ERRORS=$((ERRORS+1)); continue ;;
    esac
fi
```

Output JSON: `{thread_id, messages: [{gmail_msg_id, message_id, from, to, cc, reply_to, subject, in_reply_to, references, date}, ...]}`. Messages **sorted by date asc** — `messages[0]` là mail gốc.

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

## Filter 2 — Idempotency qua Gmail Drafts

Trước khi xử lý, check thread đã có draft chưa:

```bash
DRAFT_CHECK=$(python3 <SKILL_DIR>/scripts/imap_check_thread_drafted.py --thread-id "$THREAD_ID")
HAS_DRAFT=$(echo "$DRAFT_CHECK" | python3 -c 'import json, sys; print(json.load(sys.stdin)["has_draft"])')
if [ "$HAS_DRAFT" = "True" ]; then
    log "[skip-existing] thread $THREAD_ID: draft đã tồn tại"
    SKIPPED_EXISTING=$((SKIPPED_EXISTING+1))
    continue
fi
```

→ **SKIP nếu có draft**. Tăng counter `SKIPPED_EXISTING`.

Đây là cơ chế thay cho local DB: Gmail chính nó là single source of truth. Không cần SQLite.

**Plus dedup ở script layer**: `imap_create_draft.py` tự pre-check `X-Cowork-Dedup-Key` header trước APPEND — race-safe nếu 2 runs concurrent với cùng body.

## Phân loại mail_type

Từ `original.subject` (case-insensitive):

- Chứa `DUYỆT - GenK` → `duyet` → tiếp tục `references/02-duyet-pipeline.md`
- Chứa `ĐĂNG - GenK` → `dang` → tiếp tục `references/03-dang-placeholder.md`
- Không match → log warning + skip

## Decision tree tóm tắt

```
preflight: fetch_email_body.py --check-creds → fail → exit 1
REVIEWERS ← list_reviewers.py
threads ← imap_search_threads.py
for thread in threads:
    thread_data ← imap_get_thread.py --thread-id <thread.thread_id>
    if any(any(r in m.from.lower() for r in REVIEWERS) for m in thread_data.messages):
        SKIPPED_REVIEWER += 1; log; continue

    if imap_check_thread_drafted.py --thread-id <thread.thread_id>.has_draft:
        SKIPPED_EXISTING += 1; log; continue

    original ← thread_data.messages[0]
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
