# Bài test R&D Engineer — Nguyễn Hoàng Long

Hoàn thiện 4 phần của đề dựa trên dữ liệu được cung cấp. **Đây là bài làm offline có kiểm thử, không phải biên bản đã phục hồi máy chủ hoặc đã migrate VM thật.** Không truy cập production, không thay đổi dữ liệu khách hàng, không gửi email/nộp bài thay ứng viên.

## Nội dung

| Phần | Tài liệu | Trạng thái |
|---|---|---|
| 1 | [Postmortem](phan1-postmortem.md) | Kết luận có bằng chứng; timeline, giả thuyết, phương án xử lý/phòng ngừa |
| 2 | [Tool Proxmox](phan2-tool/README.md) | Python, CLI bảng/JSON, validation, kế hoạch trên dữ liệu hợp lệ, test tự động |
| 3 | [Nghiên cứu đề B](phan3-nghien-cuu.md) | So sánh nftables L4 và Nginx L7, khuyến nghị và nguồn chính thức |
| 4 | [Nhật ký](phan4-nhat-ky.md) | Ghi rõ AI/công cụ, công việc đã kiểm chứng và giới hạn |
| Phụ lục | [Runbook chi tiết](phu-luc/huong-dan-su-co-web-hcm-07.md) | Lệnh xử lý từng bước, toàn bộ thống kê và bằng chứng |
| Phụ lục | [Script thống kê](phu-luc/thong_ke_lb.py) | Tái lập số request/lỗi/P95 từ log gốc |

## Kiểm tra toàn bộ

Yêu cầu Python 3.10 trở lên. Đã chạy bằng Python 3.12.14. Không cần quyền root hoặc thư viện ngoài.

```bash
python3 kiem_tra.py
```

Trên Windows dùng `py -3 kiem_tra.py` nếu Python Launcher đã được cài. Chạy trong thư mục giải nén; script dùng đường dẫn tương đối với chính nó nên cũng gọi được từ thư mục khác. Script chỉ ghi lại output kiểm thử/thống kê trong gói bài làm.

Kết quả mong đợi: test pass; JSON/bảng gốc trả exit 2 do dữ liệu bất thường; JSON/bảng lab trả exit 0; tổng LB 4.718 request, 2.775 lỗi; đủ tài liệu yêu cầu. `exit 2` ở snapshot gốc được kiểm tra như hành vi mong đợi, không bỏ qua lỗi.

## Kết quả chính và giả định

- Sự cố web-hcm-07: disk đầy do logrotate sai `dailly` + backup trên root. RAM vẫn còn ~22GiB available. Lỗi LB đầu tiên 01:33:05, cuối mẫu 02:25:01; chưa biết kết thúc incident.
- Tỷ lệ lỗi 58,82% toàn mẫu, 88,04% từ 01:33; 5 hostname được quan sát có lỗi, khoảng 40 site là phạm vi node theo đề.
- Snapshot Proxmox có 8 cảnh báo liên quan capacity, CPU ngoài miền, duplicate, null và orphan node. Không thể chứng nhận kế hoạch thật từ dữ liệu này. Tool không tự đổi đơn vị hoặc chọn bản trùng.
- Lab công khai giả định để kiểm chứng thuật toán; VM2008 n01→n02 giúp tất cả node online dưới ngưỡng mô hình CPU80%/RAM85%/overcommit4. Đây không phải khuyến nghị thực thi trên cluster thật.
- Thời gian log sự cố hiểu là UTC+7; syslog không ghi năm nên lấy 2026 theo đề. LB rt được coi là thời gian request do LB ghi, không suy ra CPU hay thời gian backend riêng.

## Điều kiện để xác nhận production bình thường

Cần kết nối quản trị được cấp quyền tới web-hcm-07/LB và telemetry mới; phương án archive/volume đã xác minh; danh sách site và đường kiểm thử được phép. Sau thực hiện phải có df/DB/FPM/LB trước-sau, không còn ENOSPC, kiểm thử đọc/ghi được phép và tỷ lệ lỗi về baseline ổn định 15–30 phút. Chưa có các bằng chứng đó trong đề nên không ghi khôi phục 100% hay MTTR giả.

Đối với Proxmox, xác minh từng field bất thường từ API/inventory rồi xuất snapshot mới; kiểm tra storage, network, CPU compatibility, HA/affinity, locks và headroom khi live migrate. Tool không có chức năng thực thi migration.

## Trước khi gửi nhà tuyển dụng

Ứng viên đọc và tự chạy `kiem_tra.py`, hiểu các giả định và cảnh báo. Nhật ký giữ nguyên việc đã dùng ChatGPT; bổ sung đúng giờ nhận email, phiên làm việc riêng và thời điểm nộp nếu có. Không bịa thời gian hoặc ghi đã test production. Đề cho phép AI nhưng yêu cầu minh bạch. Gói này chưa được gửi tới nhà tuyển dụng.
