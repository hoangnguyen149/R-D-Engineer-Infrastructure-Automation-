# Nhật ký làm bài

**Họ tên:** Nguyễn Hoàng Long.
**Nhận đề lúc:** [11:41 Thứ Năm, 29/10/2026]
**Nộp bài lúc:** [20:41 Thứ Sáu, 30/10/2026]
**Tổng thời gian làm thật:** [Khoảng thời gian được ghi nhận ngày 29/10/2026, từ 18:26:55 đến 20:41:55 và ngày 30/10/2026, từ 19:26:55 đến 20:41:55, khoảng 5 giờ (các phiên kéo dài khoảng 7 giờ nếu tính cả thời gian nghỉ giữa chừng)]

## Các phiên làm việc

| Công việc | Nội dung và ghi chú chính |
|---|---|
| Đọc đề và dữ liệu | Giải nén `RnD-Test-Vietnix.zip`; đọc đề, mẫu nhật ký, snapshot hệ thống và cấu hình backup/logrotate. |
| Phần 1 — Điều tra sự cố | Đọc 5 nguồn log, thống kê LB bằng Python, đối chiếu số dòng và viết `phan1-postmortem.md`. Bot xuất hiện sau khi lỗi bắt đầu 8 phút nên chưa đủ cơ sở xem là nguyên nhân khởi phát. Còn một điểm chưa giải thích được, chưa nêu chi tiết trong nội dung cung cấp. |
| Phần 2 — Tool Proxmox | Viết `analyze_cluster.py`, test và README; xử lý dữ liệu bất thường. Sửa fixture sai; tối ưu tìm kiếm migration bằng ghi nhớ trạng thái, giới hạn tìm kiếm và kiểm tra tổng sức chứa, giảm thời gian test từ khoảng 25 giây xuống 1 giây. |
| Phần 3 — Nghiên cứu đề B | Thử cấu hình Nginx/nftables. Đổi `return 200` sang phục vụ file tĩnh để kiểm tra `limit_req`; chạy `apt-get update` để xử lý lỗi cài đặt 404. |
| Phần 4 — Rà soát cuối | Đọc lại toàn bộ bài, kiểm tra logic, sửa lỗi nhỏ, chạy lại kiểm thử và đóng gói bài nộp. |

## Giả định đã đặt ra

- Snapshot và log là dữ liệu phục vụ bài test. Phạm vi thực hiện là phân tích offline; chưa có quyền hoặc kênh kết nối production.
- Thời gian sự cố được diễn giải theo múi giờ UTC+7 và năm 2026 như đề bài. Do thiếu cấu hình log của load balancer, chưa khẳng định timestamp biểu thị thời điểm bắt đầu hay kết thúc request.
- Tải CPU được quy đổi theo vCPU × fraction; RAM được tính bằng byte. Các ngưỡng CPU 80%, RAM 85% và hệ số overcommit 4 là chính sách minh họa, cần xác nhận trước khi áp dụng thực tế.
- Chính sách trước bản sửa 03/11/2026: dữ liệu đầu vào có lỗi thì chặn việc sinh kế hoạch. Tool Test2 hiện lập đề xuất trên bản ghi hợp lệ, giữ cảnh báo và không dùng node thiếu dữ liệu/sai capacity làm đích; xem phiên sửa bên dưới. Bản dữ liệu lab chỉ sửa theo giả định được ghi rõ trong JSON, không được xem là dữ liệu production đã xác minh.
- `mem_max` được sử dụng để kiểm tra dung lượng bộ nhớ cần có trên node đích khi nhận VM. Snapshot chưa phản ánh đầy đủ bộ nhớ dành cho host, storage, network và các ràng buộc HA.
- Kế hoạch di chuyển VM là đầu ra đề xuất để rà soát, không phải bằng chứng đã thực hiện migration thành công.

## Câu hỏi đã gửi cho người ra đề

Các điểm cần xác nhận trước khi triển khai thực tế:

| Nội dung cần xác nhận | Mục đích |
|---|---|
| Giá trị RAM thực tế của node `n06` | Xác định đúng dung lượng và khả năng tiếp nhận VM. |
| Giá trị CPU của `VM2065`, `VM2067`, `VM2073` | Kiểm tra đơn vị, miền giá trị và tính chính xác của dữ liệu tải CPU. |
| Node thực sự sở hữu `VM2001` | Làm rõ quan hệ VM–node, tránh lập kế hoạch từ dữ liệu không nhất quán. |
| Giá trị `mem_used` của `VM2199` | Xác định mức sử dụng RAM hợp lệ. |
| Thông tin node `n07` và quan hệ với `VM2390` | Kiểm tra tính đầy đủ và hợp lệ của tham chiếu node. |
| Cấu hình timestamp và đơn vị thời gian trong log LB | Diễn giải đúng timeline và số liệu độ trễ. |
| Chính sách tài nguyên, storage, network và HA | Xác định điều kiện migration và các ngưỡng vận hành được chấp nhận. |

## Dùng AI và công cụ

| Hạng mục | Công cụ và mục đích | Kiểm tra được ghi nhận |
|---|---|---|
| Phân tích sự cố | ChatGPT, Python, shell: thống kê log, xây timeline, giả thuyết và báo cáo. | Đối chiếu dòng log; đếm 1.544 lỗi 504, 1.231 lỗi 502 và 1.259 request của IP bot. Sửa “hơn 40 lần” thành “40 lần”. |
| Tool Proxmox | ChatGPT và Python: viết validator, thuật toán migration, CLI và README. | Chạy snapshot; đối chiếu CPU 85,9% → 74,9%, RAM 93,0% → 81,7%; kiểm tra JSON, lỗi đầu vào (exit 2) và `NO_FEASIBLE_PLAN` (exit 3). |
| Kiểm thử tool | ChatGPT và `unittest`: tạo test và kiểm tra bất biến. | 49 unit test đạt; kiểm tra trên 150 cluster ngẫu nhiên; sửa fixture sai và chạy lại trong khoảng 1 giây. |
| Nginx/nftables | ChatGPT và tài liệu chính thức: nghiên cứu, thử cấu hình. | `nginx -t` đạt; 60 request cho 24 mã 200 và 36 mã 429; dry-run ghi 36 `REJECTED_DRY_RUN`. `nft -c -f` đạt, chưa nạp luật thật. |
| Hiệu đính và đóng gói | ChatGPT, Python/ZIP: chuẩn hóa Markdown, ghép và đóng gói bài. | Đọc lại nội dung, sửa lỗi nhỏ và kiểm tra bản giải nén; có log kiểm tra đi kèm. |

## Phần chưa xong hoặc chưa hài lòng

- Bốn phần bài làm offline đã có sản phẩm. Chưa xác nhận production khỏe vì thiếu kết nối và telemetry sau khắc phục.
- Chưa thực hiện live migration; kế hoạch di chuyển VM cần được rà soát với dữ liệu và điều kiện hạ tầng thực tế.
- Tool greedy không đảm bảo tối ưu toàn cục; nếu unresolved không kết luận vô nghiệm. Cần tối ưu thuật toán nếu cluster rất lớn và có nhiều ràng buộc.
- Chưa benchmark L4/L7, chưa chạy Nginx/MySQL thật trong lab vì runtime không có các dịch vụ đó; nghiên cứu dựa trên tài liệu chính thức.
- Dữ liệu snapshot chưa đủ để đánh giá toàn diện host overhead, storage, network và HA.
- Giờ nhận/nộp email và các phiên cá nhân là thông tin ứng viên cần bổ sung trung thực, không thể suy ra từ ZIP.

## Nếu làm lại, sẽ làm khác điều gì?

- xác định quy tắc chất lượng dữ liệu ngay từ đầu, bao gồm đơn vị đo, miền giá trị hợp lệ, tính duy nhất của VM và quan hệ VM–node. Điều này giúp phát hiện dữ liệu không nhất quán trước khi xây dựng kế hoạch migration.
- lưu bằng chứng/thống ghi thời gian từng phiên và lưu script, lệnh chạy, đầu ra kiểm thử ngay trong quá trình thực hiện để các kết luận có thể tái lập và đối chiếu.
- dựng lab Nginx, PHP-FPM và MySQL để kiểm tra các giả thuyết sự cố, quy trình phục hồi và rollback. Với migration, tôi sẽ bổ sung kiểm tra tài nguyên, storage, network và HA trước khi cân nhắc tự động thực thi.
- trực tiếp chạy lại các bước kiểm chứng quan trọng, ghi nhận kết quả thực tế và rà soát toàn bộ bài nộp để bảo đảm có thể giải thích từng kết luận, giả định và giới hạn.

## Phiên cập nhật tool Test2 theo góp ý RnD — 03/11/2026 (UTC+7)

- Phạm vi: `Nguyen-Hoang-Long/phan2-tool/cluster_balance.py` trong repo `hoangnguyen149/R-D-Engineer-Infrastructure-Automation-`. Dùng mã nguồn Phần 2 trong `NguyenHoangLong-Phan2-only.zip` người dùng cung cấp làm cơ sở; đối chiếu với bản trên GitHub. Tool Test1 trong `submission/phan2-proxmox/analyze_cluster.py` và ZIP bài nộp lịch sử được giữ nguyên.
- Công cụ: Codex và Python 3.12.14. Không đo đầy đủ thời lượng phiên, không gán thành thời gian tự làm của ứng viên. Các mốc nhận/nộp và nội dung nhật ký phiên trước được giữ nguyên.
- Bỏ điều kiện chặn toàn bộ planner khi có warning; VM lỗi/trùng vẫn bị loại, cảnh báo được giữ nguyên, không đoán lại số liệu. Node sai capacity/status hoặc thiếu bản ghi không được nhận VM. Bước đi từ nguồn thiếu dữ liệu được gắn `source_load_is_lower_bound=true`; giữ `complete=false` sau mô phỏng.
- Dữ liệu gốc: đề xuất VM2018 n01→n03, đủ 8 cảnh báo, `partial_plan_with_excluded_records`, exit 4, `resource_plan_complete=false`, `production_ready=false`. CPU/RAM n01 còn 77,69%/84,57% theo cận dưới; n03 sau nhận là 42,90%/52,02% trong mô hình. Chưa chứng minh cluster thật hết quá tải.
- Kiểm tra: 34 unit/integration test, CLI gốc/lab ở JSON/bảng (exit 4/0), JSON lỗi và mã thoát 0/2/3/4; bảo toàn tổng tài nguyên hợp lệ, không chọn node thiếu dữ liệu/sai capacity, giữ dấu cận dưới, phân biệt số bản ghi bị loại với số cảnh báo. `kiem_tra.py` còn xác minh 4.718 request LB, 2.775 lỗi và các tài liệu của gói đầy đủ.
- Cập nhật README, output mẫu, hướng dẫn kiểm tra và SHA256SUMS cho bản hiện tại. Không thay đổi JSON input, log sự cố, Test1, hay file ZIP bài nộp gốc; không truy cập production, thực hiện migration hoặc gửi email.
