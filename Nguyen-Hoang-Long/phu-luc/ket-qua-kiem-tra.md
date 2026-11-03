# Kết quả kiểm tra bàn giao

## Kiểm tra lịch sử — 29/10/2026

Thời điểm UTC+7: 2026-10-29T13:35:55+07:00
Python: 3.12.14

Đã tạo ZIP, giải nén vào thư mục tạm độc lập và chạy `kiem_tra.py` từ ngoài thư mục project. Exit code = 0.

```text
PASS: unit/integration tests
PASS: original CLI JSON/table and expected exit 2
PASS: lab-assumptions CLI JSON/table and expected exit 0
PASS: LB totals, first/last errors and group conservation
PASS: all required deliverables present
OFFLINE CHECKS PASSED. Production recovery/migration NOT executed or certified.
```

- 21 unittest/integration test thành công; log chi tiết tại phan2-tool/examples/test-results.txt.
- Dữ liệu sự cố và JSON Proxmox gốc khớp byte với file đính kèm.
- Archive CRC hợp lệ; không đóng gói cache Python.
- Không có thao tác SSH, recovery production, live migration hoặc gửi bài/email.
- Snapshot gốc bị chặn với 8 cảnh báo; lab có 1 bước migrate dự kiến, mọi node online dưới ngưỡng.
- Các kiểm tra này không thay thế kiểm thử dịch vụ thật hoặc xác nhận production bình thường.

## Kiểm tra bản sửa Test2 theo góp ý RnD — 03/11/2026 (UTC+7)

Python 3.12.14; không cần thư viện ngoài. Chạy `python3 kiem_tra.py` tại thư mục `Nguyen-Hoang-Long/`, exit 0:

```text
PASS: unit/integration tests
PASS: original CLI JSON/table and expected exit 4
PASS: lab-assumptions CLI JSON/table and expected exit 0
PASS: LB totals, first/last errors and group conservation
PASS: all required deliverables present
OFFLINE CHECKS PASSED. Production recovery/migration NOT executed or certified.
```

- 34 unit/integration test đạt; log mới tại `phan2-tool/examples/test-results.txt`.
- Snapshot gốc: VM2018 n01→n03, 8 cảnh báo, `partial_plan_with_excluded_records`, exit 4. n06 và các node thiếu dữ liệu không được làm đích. n01 sau mô phỏng vẫn `complete=false`, assessment `unknown`, `resource_plan_complete=false`.
- Lab: VM2008 n01→n02, exit 0. Kiểm tra dự trữ RAM theo `mem_max` và giới hạn CPU/RAM/overcommit sau từng bước.
- Tái lập đúng 4.718 request, 2.775 lỗi LB. Không thay đổi input JSON/log, Test1 hoặc ZIP bài nộp lịch sử.
- SHA256SUMS được cập nhật cho các tệp hiện tại. Các kết quả chỉ phản ánh kiểm chứng offline, chưa thực hiện migration hay xác nhận production.
