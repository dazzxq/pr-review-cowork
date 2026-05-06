# 6 Tiêu chí duyệt bài PR GenK

## Tiêu chí 1 (rule_id=1) — Tiêu đề quá dài
Đếm số từ trong **tiêu đề bài viết** (giá trị trường "Tiêu đề bài viết" trong email DUYỆT).
- ≤ 18 từ → ✅ ĐẠT
- > 18 từ → ❌ VI PHẠM
  - `details`: "X từ, vượt Y từ so với giới hạn 18"
  - `excerpt`: tiêu đề thực tế
  - `suggestion`: gợi ý rút gọn ≤18 từ

## Tiêu chí 2 (rule_id=2) — Sapo quá dài
Sapo là **đoạn in đậm/in nghiêng đầu tiên** ngay dưới tiêu đề (trước thân bài). Nếu không có dấu hiệu format thì lấy đoạn văn đầu tiên trước heading/ảnh.
- ≤ 50 từ → ✅ ĐẠT
- > 50 từ → ❌ VI PHẠM
  - `details`: "X từ, vượt Y từ so với giới hạn 50"
  - `excerpt`: nội dung sapo
  - `suggestion`: cách rút ngắn

## Tiêu chí 3 (rule_id=3) — Khẳng định tuyệt đối
Quét toàn bài, tìm các cụm từ (không phân biệt hoa thường):
"nhất", "đầu tiên", "dẫn đầu", "số 1", "hàng đầu", "tốt nhất",
"duy nhất", "hoàn hảo", "vượt trội nhất", "không đối thủ",
"không ai sánh bằng", "tiên phong"

Lưu ý: từ "nhất" trong cụm nối/từ ghép trung tính (ví dụ "nhất là", "thống nhất", "duy nhất chỉ là phần phụ trong câu") cần đánh giá ngữ cảnh — chỉ flag khi mang nghĩa quảng cáo tuyệt đối.

- Không tìm thấy / chỉ là từ trung tính → ✅ ĐẠT
- Có khẳng định tuyệt đối → ❌ VI PHẠM
  - `details`: liệt kê cụm từ tìm thấy
  - `excerpt`: trích nguyên đoạn câu chứa từ vi phạm
  - `suggestion`: cách diễn đạt thay thế trung tính

## Tiêu chí 4 (rule_id=4) — Cảm xúc cá nhân / đánh giá chủ quan
Quét toàn bài, tìm nội dung bộc lộ cảm xúc cá nhân hoặc đánh giá chủ quan:
"tôi rất thích", "sản phẩm tuyệt vời", "đáng mua", "quá đỉnh",
"mình recommend", "cực kỳ ấn tượng", "tôi nghĩ", "theo tôi",
"chúng tôi đánh giá", "mình thấy"

- Không tìm thấy → ✅ ĐẠT
- Có cảm xúc/đánh giá chủ quan → ❌ VI PHẠM
  - `excerpt`: trích đoạn vi phạm
  - `suggestion`: viết lại trung tính, dẫn nguồn cụ thể

## Tiêu chí 5 (rule_id=5) — Số liệu thiếu nguồn
Tìm tất cả số liệu dạng %, con số thống kê, dữ liệu thị trường, kết quả nghiên cứu trong bài.
Mỗi số liệu phải có nguồn đi kèm rõ ràng (ví dụ: "theo [Tên nguồn]", "dữ liệu từ X", "khảo sát của Y").

- Tất cả số liệu có nguồn → ✅ ĐẠT
- Có ít nhất 1 số liệu không có nguồn → ❌ VI PHẠM
  - `details`: liệt kê từng số liệu không nguồn
  - `excerpt`: trích đoạn chứa số liệu
  - `suggestion`: ghi nguồn hoặc bỏ số liệu

## Tiêu chí 6 (rule_id=6) — Viết tắt thành phố Hồ Chí Minh
Tìm bất kỳ biến thể viết tắt nào của "thành phố Hồ Chí Minh":
"TP.HCM", "TPHCM", "Tp.HCM", "tp.hcm", "HCM",
"TP Hồ Chí Minh", "Sài Gòn", "SG"

Bài phải viết đầy đủ "thành phố Hồ Chí Minh".

- Không có viết tắt → ✅ ĐẠT
- Có viết tắt → ❌ VI PHẠM
  - `details`: liệt kê từng biến thể tìm thấy + vị trí (đoạn nào)
  - `excerpt`: trích đoạn vi phạm
  - `suggestion`: thay bằng "thành phố Hồ Chí Minh"
