# Bước 2b — ĐĂNG Pipeline (Placeholder)

Workflow ĐĂNG **chưa được triển khai**. Hiện tại chỉ ghi nhận log:

```
log: [dang-skip] thread <id>: <subject> — placeholder, không xử lý
```

Tăng counter `DANG += 1`. Đi thread tiếp.

Không cần extract field, không tạo draft, không fetch gì cả.

## Khi nào triển khai full?

Khi owner xác định flow cho ĐĂNG (kiểm tra link bài đã publish, so với bài DUYỆT đã duyệt trước, v.v.). File này sẽ được rewrite khi đó.
