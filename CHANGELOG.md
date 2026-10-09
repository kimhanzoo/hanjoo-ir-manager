## 0.6.28

- Thêm trình sửa JSON trực tiếp cho profile trong thư viện và thiết bị đã thêm. Có thể nạp file JSON đã sửa, tải bản nháp và lưu áp dụng.
- Sửa JSON thiết bị giữ nguyên ID, bộ phát/mắt thu và ID các nút còn tồn tại; thêm nút mới, dọn nút đã xóa và tải lại các entity sau khi lưu.
- Sửa profile giữ ID profile. Thiết bị đã tạo giữ bản sao riêng; cập nhật chúng bằng “Sửa / nhập JSON” trong quản lý thiết bị.
- Sửa import/export thư viện rỗng; import file nhiều profile theo giao dịch. Lỗi kiểm tra hoặc ghi ổ đĩa không để lại dữ liệu nhập/sửa dở dang.
- Bổ sung kiểm tra JSON trùng key, số không hợp lệ, mã IR, số lần phát, cấu trúc climate/fan và trạng thái climate trùng nhau.
- Tốc độ quạt mới thêm không còn bị ẩn bởi danh sách tốc độ khai báo cũ. Đồng bộ các lựa chọn climate với trạng thái được nhập.
- Hiển thị lý do import lỗi; giữ bản nháp khi lưu lỗi; ngăn lưu khi file còn đang đọc. Nội dung JSON không bị dịch khi giao diện dùng tiếng Anh.
- Bổ sung kiểm thử hồi quy JSON và giao diện; giữ các kiểm thử học lệnh, phát lại, climate và hẹn giờ.

Cập nhật add-on, khởi động add-on để cài Manager mới, sau đó khởi động lại Home Assistant và tải lại trình duyệt. Import ở trang Thư viện tạo profile mới; để sửa đúng thiết bị đang dùng, mở thiết bị → “Sửa / nhập JSON” → “Lưu thay thế”. Đổi ID lệnh có nghĩa là xóa nút cũ và tạo nút mới; giữ ID nếu muốn giữ automation.

## 0.6.27

- Sửa nhầm phiên học khi hủy rồi học lại; chờ tải lại integration sau khi tạo thiết bị.
- Lưu mã học theo giao dịch; giữ mã cũ và mã tạm nếu ghi dữ liệu thất bại.
- Tuần tự hóa phát nhiều frame, kiểm tra toàn bộ mã trước khi phát và dọn phiên học lỗi.
- Thêm “Phát thử” trước khi lưu; cảnh báo tần số mặc định và khoảng nghỉ nhiều frame đang được ước lượng.

## 0.6.26

- Sửa đồng bộ trạng thái climate từ remote, kết quả decode đến muộn và nút bật riêng.
- Hỗ trợ học swing ngang/preset và hẹn giờ bật/tắt qua Home Assistant.
