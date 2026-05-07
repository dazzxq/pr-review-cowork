# PR Review Agent — GenK (Cowork-Lite)

Tự động review bài PR (Public Relations) cho [GenK.vn](https://genk.vn) qua [Claude Cowork](https://claude.com/product/cowork). Mỗi 10 phút, agent quét Gmail tìm mail `DUYỆT - GenK` / `ĐĂNG - GenK`, tải file Word đính kèm từ Bizfly Drive, đối chiếu với 6 tiêu chí kiểm duyệt, và tự tạo Gmail draft trả lời (hoặc gửi thẳng nếu bật `SEND_MODE`).

**Bạn chỉ cần approve draft trong Gmail là xong.**

---

## 📚 Mục lục

- [Tại sao có project này?](#tại-sao-có-project-này)
- [Kiến trúc](#kiến-trúc)
- [Flow hoạt động chi tiết](#flow-hoạt-động-chi-tiết)
- [Setup (5 phút)](#setup-5-phút)
- [Cấu hình `.env`](#cấu-hình-env)
- [Test SMTP trước khi gửi production](#test-smtp-trước-khi-gửi-production)
- [Bật SEND_MODE (auto-send mail)](#bật-send_mode-auto-send-mail)
- [Quản lý tiêu chí review](#quản-lý-tiêu-chí-review)
- [Cấu hình senior reviewers (skip-list)](#cấu-hình-senior-reviewers-skip-list)
- [Cấu trúc folder](#cấu-trúc-folder)
- [Tools sử dụng](#tools-sử-dụng)
- [Trade-offs & giới hạn](#trade-offs--giới-hạn)
- [Troubleshooting](#troubleshooting)
- [Bảo mật](#bảo-mật)
- [Audit log](#audit-log)
- [So với pipeline launchd local](#so-với-pipeline-launchd-local)

---

## Tại sao có project này?

Quy trình review bài PR ở GenK trước đây thủ công:

1. Mail từ vận hành tới với subject `[A02] - DUYỆT - GenK - <hợp đồng> - <nhãn hàng>`
2. BBT click link Bizfly Drive → tải file Word → đọc bài
3. Đối chiếu 6 tiêu chí (tiêu đề, sapo, khẳng định tuyệt đối, cảm xúc, dẫn nguồn, viết tắt TP.HCM)
4. Soạn reply: nếu pass → "Đã duyệt", nếu fail → liệt kê vi phạm
5. Gửi reply hoặc lưu draft

Mỗi bài tốn ~5-10 phút, tuần ~30-50 bài → 3-5 giờ/tuần. Nhiều bài lặp lại pattern (cùng client, cùng vi phạm).

**Project này tự động hoá toàn bộ flow trên.** Agent đọc rules, review bài, tạo draft đầy đủ vi phạm + đề nghị sửa. BBT chỉ cần đọc draft + Send (hoặc tự gửi nếu bật `SEND_MODE`).

---

## Kiến trúc

```
┌──────────────────────────────────────────────────────────────────┐
│                      Claude Desktop App                          │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │  Cowork — Scheduled Tasks (Routines tab)                   │  │
│  │     ⏰ */10 * * * * → fire SKILL.md                        │  │
│  └──────────────┬─────────────────────────────────────────────┘  │
│                 │                                                 │
│  ┌──────────────▼─────────────────────────────────────────────┐  │
│  │  Cowork Agent (Claude reasoning)                           │  │
│  │  • Đọc SKILL.md → orchestrator                             │  │
│  │  • Load references/*.md theo từng bước                     │  │
│  │  • Reason inline cho 6 tiêu chí (không subprocess)         │  │
│  └──────┬─────────────────────┬─────────────────────┬─────────┘  │
│         │                     │                     │             │
│  ┌──────▼──────┐    ┌─────────▼────────┐   ┌────────▼─────────┐  │
│  │ Gmail       │    │ Shell (VM)       │   │ Local files      │  │
│  │ Connector   │    │ • python3        │   │ • SKILL.md       │  │
│  │ (OAuth)     │    │ • sqlite3        │   │ • rules.md       │  │
│  │             │    │ • curl           │   │ • references/    │  │
│  │ • search    │    │ • markitdown     │   │ • scripts/       │  │
│  │ • get_thread│    │                  │   │ • .env           │  │
│  │ • create    │    │                  │   │                  │  │
│  │   _draft    │    │                  │   │                  │  │
│  └──────┬──────┘    └─────────┬────────┘   └──────────────────┘  │
└─────────│─────────────────────│──────────────────────────────────┘
          │                     │
          ▼                     ▼
   ┌──────────────┐   ┌────────────────────────┐
   │ Gmail        │   │ External services      │
   │ • Inbox      │   │ • Bizfly Drive         │
   │ • Drafts     │   │   (drive.bfcplatform.vn│
   │ • Sent Mail  │   │    /s/<token>/download)│
   │              │   │ • SMTP smtp.gmail.com  │
   │              │   │   (chỉ khi SEND_MODE)  │
   └──────────────┘   └────────────────────────┘
```

### Components

| Component | Vai trò |
|-----------|---------|
| **Cowork Schedule** | Trigger task mỗi 10 phút (min interval Cowork = 1 phút) |
| **SKILL.md** | Orchestrator top-level (~60 dòng, progressive disclosure) |
| **references/*.md** | Tài liệu chi tiết từng bước, load on-demand |
| **rules.md** | Single source of truth cho tiêu chí review |
| **Gmail Connector** | OAuth, không cần app password — search/read/draft mail |
| **fetch_document.py** | Tải file Bizfly Drive qua HTTP direct (không cần browser) |
| **markitdown** | Convert .docx → markdown để LLM đọc dễ |
| **send_email.py** | SMTP send (chỉ khi `SEND_MODE=true`) |
| **test_send.py** | Self-test SMTP trước khi production |

### Tại sao không dùng database?

Phiên bản này **stateless** — không SQLite, không local DB. Tất cả state ở Gmail:
- Mail mới → trong INBOX
- Đã xử lý → có DRAFT trong cùng thread
- Đã gửi → trong SENT MAIL

Idempotency check: agent search Gmail Drafts trước khi xử lý thread. Nếu thread đã có draft → skip.

Lợi ích:
- Setup nhanh (không cần migrate DB)
- Distribute dễ (zip 1 folder là chạy)
- Audit log ở Cowork conversation history
- Không lo SQLite corruption / migration

---

## Flow hoạt động chi tiết

```
┌─ Cowork scheduled task fires (every 10 min) ─────────────────────┐
│                                                                  │
│ [Bước 1] Search Gmail                                            │
│   query = "(subject:'DUYỆT - GenK' OR subject:'ĐĂNG - GenK')     │
│            newer_than:2d"                                        │
│   → list of threads (max ~30 trong 48h)                          │
│                                                                  │
│ [Bước 2] Với mỗi thread:                                         │
│                                                                  │
│   ┌─ Filter 1: skip-replier ──────────────────────────────────┐  │
│   │ messages = get_thread(thread_id).messages                 │  │
│   │ if any(m.from in {senior_reviewers}):                     │  │
│   │     SKIPPED_REVIEWER += 1                                 │  │
│   │     log "[skip-reviewer] thread <id>"                     │  │
│   │     → next thread                                         │  │
│   └────────────────────────────────────────────────────────────┘  │
│                                                                  │
│   ┌─ Filter 2: idempotency ──────────────────────────────────┐   │
│   │ drafts = search_drafts(f"thread:{thread_id}")            │   │
│   │ if drafts:                                                │   │
│   │     SKIPPED_EXISTING += 1                                 │   │
│   │     log "[skip-existing] thread <id>"                     │   │
│   │     → next thread                                         │   │
│   └────────────────────────────────────────────────────────────┘  │
│                                                                  │
│   ┌─ Phân loại theo subject của messages[0] (mail GỐC) ───────┐  │
│   │ if 'DUYỆT - GenK' in subject: → DUYỆT pipeline             │  │
│   │ if 'ĐĂNG - GenK' in subject:  → ĐĂNG placeholder (skip)    │  │
│   └────────────────────────────────────────────────────────────┘  │
│                                                                  │
│   ┌─ DUYỆT Pipeline (6 step) ────────────────────────────────┐   │
│   │                                                          │   │
│   │ Step 1: Extract field từ body original mail              │   │
│   │   • nhan_hang, tieu_de_bai, bizfly_url (regex HTML)      │   │
│   │   • Nếu thiếu bizfly_url → ERROR, next                   │   │
│   │                                                          │   │
│   │ Step 2: Fetch Bizfly document                            │   │
│   │   • python3 scripts/fetch_document.py <url> <out>        │   │
│   │   • Bizfly = Nextcloud → /s/<token>/download trả raw     │   │
│   │   • 0.5s/file, không cần browser                         │   │
│   │                                                          │   │
│   │ Step 3: Convert sang markdown                            │   │
│   │   • python3 -m markitdown <file.docx> > content.md       │   │
│   │                                                          │   │
│   │ Step 4: Review tiêu chí (INLINE — Cowork tự reason)      │   │
│   │   • Đọc rules.md (6 tiêu chí hiện tại, có thể thêm/bớt)  │   │
│   │   • Đọc content.md                                       │   │
│   │   • Output: {verdict, violations[], summary}             │   │
│   │                                                          │   │
│   │ Step 5: Build reply text → file                          │   │
│   │   • Template PASS/FAIL từ references/04-reply-templates  │   │
│   │   • Lưu /tmp/pr-review/<thread_id>/reply.txt             │   │
│   │                                                          │   │
│   │ Step 6: Branch theo SEND_MODE                            │   │
│   │   ├─ SEND_MODE=true (production):                        │   │
│   │   │   • python3 scripts/send_email.py --to ... --cc ...  │   │
│   │   │   • SMTP gửi thẳng                                   │   │
│   │   │   • Nếu fail → fallback sang draft + log error       │   │
│   │   │                                                      │   │
│   │   └─ SEND_MODE=false (default):                          │   │
│   │       • Cowork connector create_draft(thread_id, ...)    │   │
│   │       • Tạo Draft trong Gmail, user approve thủ công     │   │
│   │                                                          │   │
│   └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│   ┌─ ĐĂNG Placeholder ─────────────────────────────────────┐     │
│   │ • Workflow ĐĂNG chưa triển khai                       │     │
│   │ • Log "[dang-skip] thread <id>", DANG += 1            │     │
│   └────────────────────────────────────────────────────────┘     │
│                                                                  │
│ [Bước 3] In dòng tóm tắt cuối run                                │
│   "Run: found=10, sent=2, drafted=3, fallback=0,                 │
│         skipped_reviewer=4, skipped_existing=1, dang=2,          │
│         errors=0"                                                │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

### Reply-All addressing logic

Mail PR thường có nhiều người trong loop. Khi reply, agent tự build reply-all:

```
Example mail từ vận hành:
  From:     'Vận hành đăng tin' via GenK | Ban Biên Tập <editorial@example.com>
  Reply-To: Vận hành đăng tin <pr-ops@example.com>
  To:       publish-list1@example.com, publish-list2@example.com, editorial@example.com
  Cc:       manager@example.com

Agent tự tính:
  draft.to = "pr-ops@example.com"  (Reply-To, fallback From nếu không có Reply-To)
  draft.cc = ["publish-list1@example.com", "publish-list2@example.com",
              "editorial@example.com", "manager@example.com"]
              (gộp original.To + original.Cc, loại self và loại trùng to)
```

Logic này được implement trong cả `send_email.py` lẫn ở reference cho Cowork connector.

### Reply templates (tối giản)

**PASS** (verdict='pass'):
```
Dear team,

Nội dung bài viết đã được duyệt.

Trân trọng.
```

**FAIL** (verdict='fail'):
```
Dear team,

Bài viết chưa đạt do các điểm sau:

- #3 Khẳng định tuyệt đối: tìm thấy "tốt nhất", "số 1", "hàng đầu". Đề nghị: thay bằng diễn đạt trung tính.
- #6 Viết tắt thành phố Hồ Chí Minh: 3 chỗ dùng "TP.HCM". Đề nghị: viết đầy đủ.

Vui lòng chỉnh sửa và gửi lại.

Trân trọng.
```

Mỗi vi phạm = 1 dòng. Không hardcode "tất cả N tiêu chí" trong text → khi user thêm/bớt tiêu chí trong `rules.md`, template tự thích nghi.

---

## Setup (5 phút)

### Yêu cầu

- macOS hoặc Windows
- [Claude Desktop](https://claude.ai/download) + tài khoản **Pro** hoặc **Max**
- Python 3.10+ (cho `markitdown` convert .docx)
- Gmail/Workspace account có nhận mail DUYỆT/ĐĂNG GenK

### Bước 1: Tải về

```bash
git clone <this-repo-url> ~/pr-review-cowork
# hoặc tải zip + giải nén vào ~/pr-review-cowork/
cd ~/pr-review-cowork
```

### Bước 2: Chạy setup script

#### macOS / Linux (bash)

```bash
chmod +x setup.sh
./setup.sh
```

#### Windows (PowerShell)

```powershell
.\setup.ps1
```

Nếu PowerShell báo *"running scripts is disabled on this system"*, dán 1 dòng này (gồm cả 2 lệnh, ngăn cách bằng `;`):

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force; .\setup.ps1
```

`-Scope Process` = chỉ áp dụng cho session PowerShell hiện tại (đóng cửa sổ là về như cũ, không cần admin). `-Force` để PowerShell không hỏi confirm.

> ⚠️ Nếu bạn copy 2 dòng tách biệt (`Set-ExecutionPolicy ...` rồi `.\setup.ps1`) thì PHẢI nhấn **Enter** sau dòng 1 và đợi prompt mới xuất hiện, không paste 2 dòng cùng lúc — PowerShell sẽ hiểu `.\setup.ps1` là argument của `Set-ExecutionPolicy` và báo lỗi `PositionalParameterNotFound`.

> ⚠️ **Đừng dùng `chmod` hay `./setup.sh` trên PowerShell/CMD** — đó là Unix command, Windows native shell không hiểu. Dùng `setup.ps1` thay thế. (Trừ khi bạn đang trong **Git Bash** — khi đó `setup.sh` chạy được như Mac.)

Cả 2 script đều idempotent — chạy lại an toàn — và làm cùng việc:

- Check Python 3.10+ (Windows tự ưu tiên `py -3.13/3.12/3.11/3.10`)
- Tạo `.venv/` Python virtual environment
- Install `markitdown[all]` (chỉ dependency duy nhất)
- Tạo `.env` từ `.env.example` (nếu chưa có)
- In hướng dẫn các bước tiếp theo

### Bước 3: Cowork Connectors + Network Egress

**3.1. Connect Gmail** (OAuth)
- Mở **Claude Desktop** → **Settings** → **Connectors**
- Click **Connect Gmail** → "Allow" trong popup OAuth

**3.2. Bật network egress cho bash sandbox** ⚠️ QUAN TRỌNG
- **Settings → Capabilities → Code execution → Allow network egress**
- Chọn mode **"All domains"** (recommended — additional-domains list có known bugs)
- Hoặc add specific: `bizflycloud.vn`, `*.bfcplatform.vn`, `smtp.gmail.com`

⚠️ **Mặc định bash sandbox AIR-GAPPED** — không có network interface, chỉ loopback. Bỏ qua bước này → tất cả script (`fetch_document.py`, `send_email.py`, `test_*.py`) sẽ fail vì không reach được Bizfly/Gmail. Xem `references/08-cowork-network.md` để biết chi tiết.

**3.3. Verify network reach** (sau khi đổi setting, chạy test)
- Mở 1 Cowork session bất kỳ, **trust folder `~/pr-review-cowork/`** trong session đó
- Gõ:
  ```
  Run python3 ~/pr-review-cowork/scripts/test_cowork_network.py and show full output.
  ```
- Expected: 3/3 endpoint ✓ OK (`bizflycloud.vn:443`, `smtp.gmail.com:465`, `www.google.com:443`)
- Nếu fail → quay lại 3.2 đổi mode hoặc liên hệ workspace admin

### Bước 4: Tạo scheduled task — KHÔNG QUÊN folder

Trong any Cowork session, gõ:

```
Create a scheduled task that runs every 10 minutes:
- Working folder: ~/pr-review-cowork/
- Skill: SKILL.md in that folder
- Description: PR Review Agent for GenK
```

⚠️ **Phải chỉ định working folder** rõ ràng. Nếu không, Cowork sẽ tạo task không có context folder → khi fire, agent không thấy SKILL.md/scripts → improvise generic action.

Verify: vào **Routines** tab → click task → check field "Working folder" có set đúng đường dẫn không.

### Bước 5: Run lần đầu + approve permissions

1. Mở **Routines** → click task vừa tạo → **Run now**
2. Cowork sẽ chạy và prompt xin permission cho từng tool:
   - Bash (chạy Python scripts)
   - Gmail search/read/draft
   - File read/write
3. Click **"Always allow"** cho từng tool → các run sau auto-approve
4. Đọc output run đầu — verify Cowork đã đọc đúng SKILL.md (không phải improvise generic). Output cuối phải có dòng:
   ```
   Run: found=X, drafted=Y, ...
   ```
   Nếu không thấy dòng này → task đang chạy generic action, không phải SKILL.md → quay lại Bước 4 check folder.

✅ **Done.** Cứ mỗi 10 phút (khi máy mở + Claude Desktop running), task sẽ tự chạy.

---

## Cấu hình `.env`

File `.env` được tạo từ `.env.example` lúc `setup.sh`. Mặc định mọi thứ off — chỉ tạo Gmail Draft, an toàn.

```bash
# ─── Mode ────────────────────────────────────────────────────────
# false = chỉ tạo Gmail Draft (mặc định, an toàn)
# true  = gửi thẳng qua SMTP (cần credentials)
SEND_MODE=false

# ─── SMTP credentials (chỉ cần khi SEND_MODE=true) ──────────────
SENDER_EMAIL=
SENDER_APP_PASSWORD=

# ─── SMTP server (mặc định OK cho Gmail/Workspace) ──────────────
SMTP_HOST=smtp.gmail.com
SMTP_PORT=465
```

**`.env` đã được `.gitignore`** — không commit secrets vào repo.

---

## Test SMTP trước khi gửi production

⚠️ **Bắt buộc** test 2 bước trước khi để agent gửi mail thật cho BBT.

### Bước 1: Test network egress (chạy TRONG Cowork)

Cowork mặc định chặn outbound network. Verify trước rằng VM của Cowork có thể reach Bizfly + SMTP host.

Trong Cowork conversation (folder `~/pr-review-cowork/` đã được trust trong session đó), gõ **prompt cụ thể**:

```
Run python3 ~/pr-review-cowork/scripts/test_cowork_network.py and show full output.
```

⚠️ **Tránh prompt vague** như `"test the cowork network reachability"` — Cowork sẽ improvise với generic domains thay vì chạy đúng script. Phải invoke script trực tiếp bằng path.

Expected output: 3/3 endpoint ✓ OK với latency:
- `bizflycloud.vn:443` ✓ OK (~1000ms ổn)
- `smtp.gmail.com:465` ✓ OK (~50ms)
- `www.google.com:443` ✓ OK (~100ms)

Nếu fail → Settings → Capabilities → Code execution → Allow network egress → "All domains" (xem `references/08-cowork-network.md`).

KHÔNG nên chỉ chạy local terminal — vì local network ≠ Cowork sandbox network.

### Bước 2: Test SMTP credentials (self-send)

Sau khi network OK, test self-send (gửi cho chính bạn, không động tới BBT/khách):

```bash
# Mode 1 — đọc từ .env (recommend cho Cowork)
python3 scripts/test_send.py

# Mode 2 — interactive prompt (password ẩn, không vào shell history)
python3 scripts/test_send.py --interactive

# Mode 3 — dry-run validate, không gửi
python3 scripts/test_send.py --dry-run
```

Hoặc trong Cowork conversation (folder đã trust):
```
Run python3 ~/pr-review-cowork/scripts/test_send.py and show full output. Do not echo any credentials in your response — the script reads from .env.
```

Câu cuối quan trọng: ngăn Cowork lỡ paste password vào conversation log.

### Sample output (success)

```
━━ Bước 1: Đọc credentials ━━
  Email      : you@gmail.com  (from .env)
  Password   : •••••••••••••••• (16 chars, from .env)
  SMTP server: smtp.gmail.com:465

━━ Bước 2: Build test email ━━
  Subject: [TEST] PR Review Cowork — SMTP check 2026-05-07 10:30:15
  Body   : 1247 bytes, 28 lines

━━ Bước 3: Gửi qua smtp.gmail.com:465 ━━
  → Connected, đang login...
  → Login OK, đang send...
  → Send OK

━━ Bước 4: Kết quả ━━
✅ Test email sent successfully
   Message-ID : 16abc...@mail.gmail.com
   Elapsed    : 1.34s
   To         : you@gmail.com

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚠️  SECURITY — ROTATE app password NGAY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  1. Mở: https://myaccount.google.com/apppasswords
  2. Tìm password vừa dùng, click REVOKE
  3. Tạo password mới + paste vào .env
  4. Set SEND_MODE=true để bật production
```

### Exit codes

| Exit | Ý nghĩa |
|------|---------|
| 0 | OK, mail đã đi tới inbox |
| 1 | Config thiếu (email/password trống) |
| 30 | SMTP auth failed (sai pwd, 2FA chưa bật, Workspace tắt app pwd) |
| 32 | SMTP error khác |
| 33 | Network/timeout (Cowork egress chặn?) |
| 99 | Unknown |

Chi tiết: `references/07-test-send.md`.

---

## Bật SEND_MODE (auto-send mail)

⚠️ Chỉ bật khi đã `test_send.py` pass + đã rotate password vừa test.

### Setup credentials

1. Tạo Google App Password tại [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
   - Yêu cầu: account đã bật **2-Step Verification**
   - Nếu là Workspace: admin có thể đã tắt App Password — liên hệ IT
2. Edit `.env`:
   ```bash
   SEND_MODE=true
   SENDER_EMAIL=your@gmail.com
   SENDER_APP_PASSWORD=xxxx xxxx xxxx xxxx   # 16 ký tự, có thể có space
   ```
3. **Cowork settings → Network egress → allow `smtp.gmail.com:465`** (Cowork mặc định chặn outbound)

### Validation logic

Khi `SEND_MODE=true`, mỗi mail đi qua:

| Exit | Vấn đề | Hành động |
|------|--------|-----------|
| 0 | Gửi thành công | `SENT += 1`, log success |
| 10 | `SEND_MODE` chưa true | Fallback draft (impossible reach normally) |
| 11 | `SENDER_EMAIL` trống | Fallback draft + log warning |
| 12 | `SENDER_APP_PASSWORD` trống | Fallback draft + log warning |
| 20 | Body file lỗi | Log error, count ERROR (không fallback — lỗi nội bộ) |
| 30 | SMTP auth failed | Fallback draft + log error rõ |
| 31-33 | SMTP/network | Fallback draft + log error |
| 99 | Unknown | Fallback draft + log error |

**Fallback an toàn**: khi gặp bất kỳ lỗi config/network nào, agent tự fallback sang draft mode → không bao giờ bỏ sót mail. User thấy log error ngay trong Cowork conversation và biết cần fix gì.

Chi tiết edge cases: `references/06-send-mode.md`.

### Tắt SEND_MODE tạm thời

```bash
# Edit .env
SEND_MODE=false
```

Lần run kế tiếp về draft mode. Không cần restart Cowork hay xoá creds.

### Xoá credentials hoàn toàn

```bash
rm .env
```

Hoặc revoke app password tại [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords) → Google sẽ vô hiệu hoá ngay.

---

## Quản lý tiêu chí review

`rules.md` là **single source of truth**. Sửa file này, không cần đụng SKILL/references/code.

### Format mỗi tiêu chí

```markdown
## Tiêu chí N (rule_id=N) — <Tên ngắn>

<Mô tả phát hiện vi phạm. Ví dụ: tìm các cụm từ X, Y, Z.>

- Đạt → ✅
- Vi phạm → ❌ kèm details/excerpt/suggestion
```

### Thêm tiêu chí mới

Append vào cuối `rules.md`:

```markdown
## Tiêu chí 7 (rule_id=7) — Cấm spam tên thương hiệu

Đếm số lần tên thương hiệu xuất hiện trong bài (không tính tiêu đề + sapo).
- ≤ 5 lần → ✅
- > 5 lần → ❌
```

→ Lần run kế tiếp agent tự đọc, áp dụng, output violation với `rule_id=7`. **Không touch SKILL, code, hay template.**

### Bớt / sửa tiêu chí

- Xoá: delete section đó. ID không cần renumber liên tục.
- Sửa: edit body, save. Hiệu lực ngay từ run kế tiếp.

### Lưu ý

- Body PASS template không nhắc "đã đạt N tiêu chí" — chỉ nói "đã được duyệt" → tự thích nghi với số lượng tiêu chí
- Số `rule_id` xuất hiện trong reply theo từng vi phạm cụ thể, không tổng hợp
- Tiêu chí mới có thể là phức tạp (yêu cầu LLM reason đa bước) — Cowork agent xử lý được

---

## Cấu hình senior reviewers (skip-list)

Mặc định, agent skip thread nếu **bất kỳ** message nào trong thread có `from` chứa các email senior reviewers — vì sếp duyệt thủ công thì agent không nên tạo draft trùng.

### Sửa skip-list

Mở `.env` (file đã được tạo bởi `setup.sh` từ `.env.example`), tìm dòng:

```env
REVIEWER_EMAILS=senior1@example.com,senior2@example.com
```

Đổi placeholder bên phải thành email thật của team bạn (comma-separated, lowercase, không dấu cách quanh dấu phẩy). Bỏ trống / xoá dòng này → script in `[]` + warning ra stderr → agent **không skip ai cả** (có thể tạo draft trùng với sếp).

Lần run kế tiếp agent tự áp dụng — không cần sửa `SKILL.md` hay `references/`.

### Logic

```
REVIEWERS = run("python3 scripts/list_reviewers.py")  # JSON array từ env hoặc default
for thread in threads:
    messages = get_thread(thread.id).messages
    if any(any(r in m.from.lower() for r in REVIEWERS) for m in messages):
        skip thread
```

`scripts/list_reviewers.py` đọc env `REVIEWER_EMAILS` (qua `.env`) → in JSON array → agent parse 1 lần đầu run, dùng cho mọi thread.

---

## Cấu trúc folder

```
pr-review-cowork/
├── README.md                      ← file này
├── SKILL.md                       ← top-level Cowork orchestrator (~60 dòng)
├── rules.md                       ← Tiêu chí review (sửa khi cần thêm/bớt)
├── .env.example                   ← Template config
├── .env                           ← Config thật (gitignored, tạo bởi setup.sh)
├── .gitignore                     ← Exclude .env, .venv
├── setup.sh                       ← One-shot setup macOS/Linux (venv + deps + .env)
├── setup.ps1                      ← One-shot setup Windows PowerShell (cùng logic)
├── requirements.txt               ← markitdown[all]
│
├── references/                    ← Tài liệu chi tiết, load on-demand
│   ├── 01-search-filter.md        ← Gmail search + skip-replier + idempotency
│   ├── 02-duyet-pipeline.md       ← DUYỆT pipeline 6 step + SEND_MODE branch
│   ├── 03-dang-placeholder.md     ← ĐĂNG (chưa triển khai)
│   ├── 04-reply-templates.md      ← Template PASS/FAIL + reply-all addressing
│   ├── 06-send-mode.md            ← Setup SEND_MODE + edge cases
│   ├── 07-test-send.md            ← Self-test SMTP + rotate reminder
│   └── 08-cowork-network.md       ← Test Cowork egress + cách config allowlist
│
├── scripts/
│   ├── fetch_document.py          ← Tải Bizfly Drive (curl direct, no browser)
│   ├── list_reviewers.py          ← In JSON skip-list (đọc REVIEWER_EMAILS từ .env)
│   ├── send_email.py              ← SMTP send (production, SEND_MODE=true)
│   ├── test_send.py               ← Self-test SMTP + rotate reminder
│   └── test_cowork_network.py     ← TCP probe Bizfly/SMTP/Internet (no creds)
│
└── .venv/                         ← Tạo bởi setup.sh (gitignored)
```

**Tổng: ~1,300 dòng code/docs**, 0 dependency ngoài `markitdown` (cho .docx convert).

---

## Tools sử dụng

### Gmail Connector (Cowork native)

OAuth-based, không cần app password cho phần draft. Tools available:

- `search_threads(query)` — search Gmail với Gmail query syntax
- `get_thread(id)` — đọc full messages của 1 thread
- `search_drafts(query)` — search trong Drafts folder (cho idempotency)
- `create_draft(thread_id, to, cc, subject, body)` — tạo draft

### Shell (Cowork VM)

Cowork VM có:
- Python 3 (cho markitdown, scripts)
- curl, bash, sqlite3 (không dùng nhưng có sẵn)
- File I/O trong folder đã trust

Network egress mặc định **bị hạn chế** — phải allowlist domain. Cần allow:
- `*.drive.bfcplatform.vn` (Bizfly Drive)
- `smtp.gmail.com:465` (chỉ khi SEND_MODE=true)

### `markitdown`

Convert .docx (và nhiều format khác) → markdown sạch để Cowork agent đọc. Cài qua `pip install markitdown[all]`.

### `fetch_document.py`

Helper Python tải file từ Bizfly Drive. Dùng `urllib` stdlib + rewrite URL pattern:
```
https://<host>/apps/onlyoffice/s/<token>  →  https://<host>/s/<token>/download
```

Không cần browser → 0.5s/file thay vì 30s+ với headless browser.

### `send_email.py` + `test_send.py`

SMTP via stdlib `smtplib`. App password từ `.env`. Strict validation, exit codes có ý nghĩa cho fallback logic.

---

## Trade-offs & giới hạn

### Cowork limitations

1. **Máy phải mở + Desktop app running** mỗi lúc task fire. Nếu máy sleep / app đóng → run bị skip. Có catch-up 1 lần khi wake up (cho missed run gần nhất).
   - Mitigation: Settings → Desktop app → General → bật "Keep computer awake"
2. **Min interval 1 phút** (đủ cho use case này, nhưng nếu muốn realtime hơn → không khả thi)
3. **Permission prompt lần đầu** cho từng tool — phải click "Always allow" để các run sau auto
4. **Cowork connector chỉ tạo draft, không send mail** → đó là lý do `SEND_MODE` cần SMTP riêng (không qua connector)

### Gmail API limitations

1. **Rate limit**: Gmail API có quota — nếu quá nhiều thread/giờ có thể bị throttle
2. **Search latency**: query Gmail có thể chậm 2-5s khi inbox lớn
3. **Threading**: Gmail dùng `In-Reply-To` + `References` headers. Khi agent tạo draft, connector tự handle. Khi `send_email.py` gửi, script set headers thủ công.

### SMTP limitations (khi SEND_MODE=true)

1. **App password yêu cầu 2FA** đã bật. Workspace có thể bị admin tắt
2. **Gmail SMTP rate limit**: ~500 mail/ngày cho Gmail thường, ~2000 cho Workspace
3. **Sent Mail**: SMTP send vẫn được Gmail tự lưu vào `[Gmail]/Sent Mail` (auto, qua header)

### Markitdown limitations

1. Convert .docx tốt nhất, .pdf OK nhưng đôi khi mất layout, .xlsx có thể chỉ ra text
2. Không xử lý được password-protected files
3. Image trong file → embed base64 trong markdown (có thể làm bài dài)

---

## Troubleshooting

### "Cowork agent improvise generic test, không chạy script của tôi"

**Triệu chứng**: gõ `"test the cowork network reachability"` → Cowork không chạy `test_cowork_network.py` mà tự bịa ra test với generic domains (google, github, npm...).

**Nguyên nhân**: folder `~/pr-review-cowork/` chưa được trust trong **task/session đó** → Cowork không thấy SKILL.md/scripts → improvise.

**Fix**:
1. Vào Routines tab → click task → check field "Working folder"
2. Nếu trống/sai → Edit task, set folder = `~/pr-review-cowork/`, save
3. Hoặc trong session hiện tại: gõ `"trust folder ~/pr-review-cowork"`
4. Re-prompt với invocation cụ thể:
   ```
   Run python3 ~/pr-review-cowork/scripts/test_cowork_network.py
   ```

### "Bash sandbox is fully network-isolated" / "DNS unreachable"

**Triệu chứng**: bất kỳ script Python/curl nào trong Cowork shell đều fail với DNS lookup error hoặc timeout.

**Nguyên nhân**: Cowork mặc định air-gap bash (chỉ loopback, không routes).

**Fix**: Settings → Capabilities → **Code execution → Allow network egress** → đổi mode sang **"All domains"**. Restart Cowork session, re-test.

Chi tiết + edge cases: `references/08-cowork-network.md`.

### "Task không chạy"

1. Check Routines tab → task status có "Active" không
2. Check máy đang awake + Claude Desktop đang running
3. Click "Run now" → xem có lỗi permission nào pending không
4. Check working folder trong task config có đúng `~/pr-review-cowork/` không (xem case "improvise" ở trên)

### "Gmail connector không tìm thấy"

Settings → Connectors → reconnect Gmail (OAuth refresh token có thể đã expire).

### "Bizfly fetch fail"

```bash
# Test thủ công
python3 scripts/fetch_document.py "https://...drive.bfcplatform.vn/.../s/<token>" /tmp/test/
```

Nếu fail:
- Link có thể đã hết hạn → liên hệ vận hành xin link mới
- Network egress Cowork chặn `*.bfcplatform.vn` → allowlist domain
- Bizfly thay đổi URL format → sửa `BIZFLY_RE` trong script

### "markitdown báo lỗi"

```bash
./setup.sh   # cài lại deps
# hoặc thủ công
.venv/bin/pip install --upgrade 'markitdown[all]'
```

### "Test send fail exit 30 (auth)"

- Verify email + password chính xác
- 2FA đã bật chưa? (https://myaccount.google.com/signinoptions/two-step-verification)
- Workspace admin có tắt App Passwords không? Hỏi IT
- App password có 16 ký tự không? (`len(pwd.replace(' ', ''))`)

### "Test send fail exit 33 (network)"

- Cowork egress chặn `smtp.gmail.com:465` → allowlist
- Firewall máy chặn outbound port 465 → check Mac/Windows firewall
- ISP chặn SMTP (hiếm) → thử dùng port 587 với STARTTLS

### "Draft tạo sai thread"

- Verify `thread_id` trong log → có khớp original mail không?
- Cowork connector phải nhận đúng `thread_id` parameter — check `references/02-duyet-pipeline.md`

### "Agent xử lý mail của thread cũ rồi tạo draft trùng"

- Idempotency dựa vào `search_drafts(thread:<id>)` — nếu user xoá draft cũ, agent sẽ thấy thread chưa có draft → tạo lại
- Mitigation: đừng xoá draft mà chưa send (hoặc đợi mail mới)

### "SEND_MODE=true nhưng vẫn về draft"

Đọc log error trong Cowork conversation — script `send_email.py` in stderr rõ ràng:
```
ERROR[30]: SMTP auth failed... Fallback sang create_draft.
```

Fix lỗi đó (rotate password, allowlist egress, v.v.) → run lại.

---

## Bảo mật

### Bảo mật `.env`

- `.env` đã trong `.gitignore` — không commit nhầm
- Quyền file: `chmod 600 .env` để chỉ user đọc được
- Khi share folder cho người khác: KHÔNG share `.env` của mình. Họ tự tạo từ `.env.example`

### Bảo mật App Password

- App password = full access tới account khi gửi mail (qua SMTP)
- Đặt **tên gợi nhớ** khi tạo (ví dụ: "PR Review Cowork - 2026-05") để dễ revoke
- Rotate định kỳ (3-6 tháng) hoặc ngay khi nghi ngờ bị lộ
- Revoke ngay sau khi `test_send.py` để tránh password test bị reuse

### Bảo mật OAuth (Gmail Connector)

- Cowork dùng OAuth refresh token, không lưu password của bạn
- Revoke connector tại Cowork Settings → Connectors → Disconnect Gmail
- Hoặc revoke tại Google: https://myaccount.google.com/permissions

### Audit trail

Mỗi action của agent ghi vào Cowork conversation history (Routines tab → click task → History). Log bao gồm:
- Threads search được
- Threads bị skip (lý do)
- Drafts được tạo
- Mail được send (nếu SEND_MODE)
- Errors

History server-side ở Anthropic → **đừng paste secret vào Cowork conversation** (như password).

---

## Audit log

Cowork lưu conversation của mỗi scheduled run trong **Routines tab → click task → History**.

### Click 1 run để xem

- Threads search được (URLs, IDs, subjects)
- Threads bị skip (lý do từng thread)
- Drafts được tạo (thread, verdict, violations, draft URL)
- Mail được send (thread, recipients, message ID)
- Errors (kèm stderr của scripts)
- Output dòng tóm tắt cuối: `Run: found=X, sent=Y, drafted=Z, ...`

### Format dòng log của agent

```
[ok-draft] thread <id>: drafted (verdict=fail, violations=2)
[ok-sent] thread <id>: gửi tới pr-ops@example.com, cc=4
[skip-reviewer] thread <id>: replied by senior2@example.com
[skip-existing] thread <id>: draft đã tồn tại
[fallback-draft] thread <id>: SMTP fail (exit 30: auth), tạo draft thay thế
[error] thread <id>: Bizfly fetch fail
[dang-skip] thread <id>: <subject> — placeholder
```

Không cần dashboard riêng — Cowork UI đã đủ.

---

## So với pipeline launchd local

Project này là **Path B** — phù hợp distribute cho người dùng phổ thông qua Cowork. Còn **Path A** là pipeline custom với launchd cron + Flask dashboard local cho power users.

| | Path A (launchd local) | Path B (Cowork-Lite) |
|---|---|---|
| **Trigger** | launchd `*/10 * * * *` | Cowork scheduled task `*/10` |
| **Auth Gmail** | App password + IMAP | OAuth via Cowork connector |
| **State** | SQLite mail_queue + agent_runs | Gmail drafts (single source) |
| **Idempotency** | SQL: `WHERE thread_id=?` | Gmail: `search_drafts(thread:<id>)` |
| **Audit** | DB + logs/agent.log | Cowork conversation history |
| **Dashboard** | Flask :7337 (date picker, modal) | Cowork conversation per run |
| **Review LLM** | nested `claude -p` (~37s) | inline reasoning (~5s) |
| **Deps** | flask, waitress, markitdown[all], camoufox, playwright, bs4 | chỉ markitdown |
| **Setup time** | ~1h cho dev | ~5 phút cho ai cũng được |
| **Always-on** | launchd luôn chạy bất kể UI | Cần máy + Desktop app open |
| **Distribute** | Phải clone repo + setup từng máy | Share folder zip → trust + connect Gmail |
| **Send mode toggle** | `--send` flag trong gmail_draft.py | `SEND_MODE=true` trong `.env` |

Chọn Path A khi: cần dashboard custom, nhiều mail/giờ, máy bash/launchd thuần, audit dài hạn.

Chọn Path B khi: distribute cho team không tech, không cần dashboard, OK với Cowork's always-on requirement.

Project Path A không public — chỉ Path B (folder này) là distribute-ready.

---

## License

Tự do sử dụng cho công việc cá nhân/team. Forge phù hợp với workflow của bạn. Không support warranty.

## Contributing

Issues/PRs welcome. Domain-specific (GenK.vn) có thể adapt cho các site PR khác bằng cách:
- Sửa `rules.md` cho tiêu chí mới
- Sửa pattern keyword trong `references/01-search-filter.md`
- Sửa pattern HTML extract trong `references/02-duyet-pipeline.md` Step 1
