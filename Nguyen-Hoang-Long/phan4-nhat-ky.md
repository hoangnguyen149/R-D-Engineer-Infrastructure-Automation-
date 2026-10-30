# Nhật ký làm bài

**Họ tên:** Nguyễn Hoàng Long.
**Nhận đề lúc:** Không có timestamp email gốc trong dữ liệu cung cấp; ứng viên bổ sung từ email, không suy đoán.
**Nộp bài lúc:** Chưa gửi bài cho nhà tuyển dụng.
**Tổng thời gian làm thật:** Chưa biết tổng thời gian ứng viên đã làm. Phiên hoàn thiện có hỗ trợ AI ngày 29/10/2026 được ghi theo dấu thời gian công cụ ở dưới; không tính đây là thời gian tự làm của ứng viên.

## Các phiên làm việc

| Thời điểm UTC+7 | Thời lượng | Làm phần nào | Ghi chú |
|---|---|---|---|
| Phiên trước trong cuộc hội thoại, 29/10/2026 | Không có phép đo đầy đủ | Phần 1 | Đọc ZIP/log, thống kê 4.718 request, tạo báo cáo chi tiết; không truy cập production |
| 29/10/2026, mốc đo công cụ 13:26:55 | Đến mốc hoàn tất kiểm tra ở cuối file | Hoàn thiện các phần 1–4 | Xây tool, test, nghiên cứu tài liệu chính thức, tái lập thống kê và đóng gói |

## Giả định đã đặt ra

- Snapshot/log là dữ liệu bài test, chưa có quyền/kênh kết nối production.
- Timestamps sự cố là UTC+7, năm 2026 theo đề; thiếu cấu hình LB nên không khẳng định timestamp là bắt đầu request.
- Tải CPU theo vCPU × fraction, RAM dùng byte; ngưỡng CPU80%/RAM85%/overcommit4 là chính sách minh họa.
- Dữ liệu gốc có lỗi thì chặn kế hoạch tự động. Lab sửa theo giả định ghi ngay trong JSON, không coi đó là dữ liệu đã xác minh.
- `mem_max` dùng để kiểm tra dung lượng nhận VM; snapshot không có host overhead, storage/network hay ràng buộc HA.

## Câu hỏi đã gửi cho người ra đề

Chưa gửi câu hỏi/email nào. Những điểm cần xác nhận nếu triển khai: giá trị thật của RAM n06, CPU của VM2065/2067/2073, node sở hữu VM2001, mem_used VM2199 và node n07/VM2390.

## Dùng AI và công cụ

| Bước | Công cụ | Dùng để làm gì | Kiểm chứng thực tế trong phiên AI |
|---|---|---|---|
| Điều tra | ChatGPT + đọc log bằng shell/Python | Xây timeline, giả thuyết, runbook | Đối chiếu ENOSPC, dailly, backup; phân biệt dấu hiệu với kết luận |
| Thống kê | Python standard library | Parse LB, count status/hostname/phút/P95 | Không bỏ dòng lỗi parse; đối chiếu tổng và lỗi giữa các nhóm |
| Tool | ChatGPT + Python | Viết validator, planner, CLI | Unit/integration test, output gốc và lab, bảo toàn tài nguyên và kiểm tra từng đích |
| Nghiên cứu | Tra cứu web chính thức | Đối chiếu Nginx, nftables, Proxmox | Nguồn URL trong tài liệu; không dùng benchmark tưởng tượng |
| Đóng gói | Python/ZIP | Bài nộp và tái kiểm tra từ bản giải nén | Có log kiểm tra đi kèm |

Ứng viên chưa cung cấp bằng chứng tự chạy lại; cột kiểm chứng trên mô tả việc công cụ đã làm trong phiên AI, không gán thành việc ứng viên đã tự thực hiện.

## Phần chưa xong hoặc chưa hài lòng

- Bốn phần bài làm offline đã có sản phẩm. Chưa xác nhận production khỏe vì thiếu kết nối và telemetry sau khắc phục; không chạy live migration.
- Tool greedy không đảm bảo tối ưu toàn cục; nếu unresolved không kết luận vô nghiệm. Cần tối ưu thuật toán nếu cluster rất lớn.
- Chưa benchmark L4/L7, chưa chạy Nginx/MySQL thật trong lab vì runtime không có các dịch vụ đó; nghiên cứu dựa trên tài liệu chính thức.
- Giờ nhận/nộp email và các phiên cá nhân là thông tin ứng viên cần bổ sung trung thực, không thể suy ra từ ZIP.

## Nếu làm lại, sẽ làm khác điều gì?

Xác định data-quality contract trước khi lập kế hoạch migrate; lưu bằng chứng/thống kê bằng script ngay từ đầu; dựng lab dịch vụ thật để kiểm tra rollback và phục hồi, rồi bổ sung kiểm thử tài nguyên/network/HA trước khi xem xét tự động thực thi.

**Mốc hoàn tất kiểm tra offline:** 2026-10-29T13:35:55+07:00. Khoảng đo từ 13:26:55 chỉ phản ánh phiên công cụ, không bao gồm toàn bộ phiên trước hoặc thời gian ứng viên tự làm.
