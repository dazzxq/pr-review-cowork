# Email Reply Templates

Body của Gmail draft. Plain text UTF-8, tiếng Việt có dấu. **Tối giản, không cầu kỳ.**

## Template PASS — verdict='pass'

```
Dear team,

Nội dung bài viết đã được duyệt.

Trân trọng.
```

## Template FAIL — verdict='fail'

```
Dear team,

Bài viết chưa đạt do các điểm sau:

- #<rule_id> <rule_name>: <details>. Đề nghị: <suggestion>
- #<rule_id> <rule_name>: <details>. Đề nghị: <suggestion>

Vui lòng chỉnh sửa và gửi lại.

Trân trọng.
```

## Quy tắc render

- Mỗi vi phạm = 1 dòng (gộp `details` + `suggestion`)
- Không in `excerpt` trong reply (giữ ngắn gọn). Nếu cần dẫn nguồn thì append vào `details`
- Không có emoji
- Subject của draft: nếu original chưa có `Re:` → prepend `Re: `; có rồi → giữ nguyên (tránh `Re: Re:`)
- Không hardcode số lượng tiêu chí trong text — body PASS không nhắc "X tiêu chí", chỉ nói đã duyệt

## Addressing — Reply-All

Lấy từ headers của mail GỐC (`messages[0]`):

| Header | Mục đích |
|--------|----------|
| `Reply-To` | Nếu có → dùng làm `to` chính. Đây là email mà bên gửi muốn nhận reply. |
| `From` | Fallback nếu không có Reply-To |
| `To` (original) + `Cc` (original) | Gộp thành `cc` của draft, **trừ chính email của bạn** (tránh tự gửi cho mình) |

Pseudo-code:
```python
my_email = "<your_email>@example.com"  # email connect Gmail của bạn
reply_to = original.headers.get("Reply-To") or original.from_
draft.to   = [reply_to]
draft.cc   = [a for a in (original.to + original.cc) if a != my_email and a != reply_to]
```

Ví dụ với header thực tế:
```
From:     'Vận hành đăng tin' via GenK | Ban Biên Tập <banbientap@genk.vn>
Reply-To: Vận hành đăng tin <kpi_2@admicro.vn>
To:       dangtin@admicro.vn, genk@admicro.vn, banbientap@genk.vn
Cc:       chivulinh@admicro.vn
```

→ Draft sẽ là:
- `to`: `kpi_2@admicro.vn` (Reply-To)
- `cc`: `dangtin@admicro.vn, genk@admicro.vn, banbientap@genk.vn, chivulinh@admicro.vn` (loại self nếu có trong list)

Gọi Gmail connector:
```
create_draft(
  thread_id=<thread_id>,
  to=<reply_to>,
  cc=<cc_list joined by comma>,
  subject="Re: " + <original.subject>,
  body=<reply text>,
)
```
