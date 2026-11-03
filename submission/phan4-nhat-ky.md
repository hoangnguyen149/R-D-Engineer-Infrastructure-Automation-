# Nhật ký làm bài

**Họ tên:** [Nguyễn Hoàng Long]
**Nhận đề lúc:** [11:41 Thứ Năm, 29/10/2026]
**Nộp bài lúc:** [20:41 Thứ Sáu, 30/10/2026]
**Tổng thời gian làm thật (ước tính):** [Khoảng thời gian được ghi nhận ngày 29/10/2026, từ 18:26:55 đến 20:41:55 và ngày 30/10/2026, từ 19:26:55 đến 20:41:55, khoảng 5 giờ (các phiên kéo dài khoảng 7 giờ nếu tính cả thời gian nghỉ giữa chừng)]

## Các phiên làm việc

| Công việc | Nội dung và ghi chú chính |
|---|---|
| Đọc đề và dữ liệu | Giải nén `RnD-Test-Vietnix.zip`; đọc đề, mẫu nhật ký, snapshot hệ thống và cấu hình backup/logrotate. |
| Phần 1 — Điều tra sự cố | Đọc 5 nguồn log, thống kê LB bằng Python, đối chiếu số dòng và viết `phan1-postmortem.md`. Bot xuất hiện sau khi lỗi bắt đầu 8 phút nên chưa đủ cơ sở xem là nguyên nhân khởi phát. Còn một điểm chưa giải thích được, chưa nêu chi tiết trong nội dung cung cấp. |
| Phần 2 — Tool Proxmox | Viết `analyze_cluster.py`, test và README; xử lý dữ liệu bất thường. Sửa fixture sai; tối ưu tìm kiếm migration bằng ghi nhớ trạng thái, giới hạn tìm kiếm và kiểm tra tổng sức chứa, giảm thời gian test từ khoảng 25 giây xuống 1 giây. |
| Phần 3 — Nghiên cứu đề B | Thử cấu hình Nginx/nftables. Đổi `return 200` sang phục vụ file tĩnh để kiểm tra `limit_req`; chạy `apt-get update` để xử lý lỗi cài đặt 404. |
| Phần 4 — Rà soát cuối | Đọc lại toàn bộ bài, kiểm tra logic, sửa lỗi nhỏ, chạy lại kiểm thử và đóng gói bài nộp. |

## Giả định đã đặt ra

- **Phần 1:** đề nói lỗi từ "khoảng 01:00" nhưng log cho thấy LB vẫn bình thường tới 01:32 và 5xx đầu tiên lúc 01:33:05. Mốc bắt đầu lỗi lấy là 01:33, còn 01:00 là lúc backup bắt đầu chứ không phải lúc lỗi bắt đầu. Các file cấu hình nginx/php-fpm, disk-check.sh và trigger Zabbix không có trong snapshot, nên mọi nhận định về fastcgi_read_timeout, cơ chế gửi cảnh báo đều ghi là suy luận hoặc chưa biết.
- **Phần 1:** `error.log` của nginx trong snapshot là bản rút gọn (670 dòng) trong khi `du` ghi 641 MB; mình không suy ra số lượng lỗi thật từ file này.
- **Phần 2:** ngưỡng 80% CPU / 85% RAM / 4:1 overcommit lấy từ đề xuất làm giá trị khởi điểm, không phải ngưỡng chính thức. Quy tắc dữ liệu bẩn do mình chọn: `cpu_usage` ngoài [0,1] không tự đổi đơn vị (nghi là %); `mem_total=262144` của `n06` nghi là MiB nhưng không tự sửa; `vmid` 2001 trùng trên n01 và n02 thì tính tải ở cả hai node và ghim VM; VM 2390 trỏ node không tồn tại thì bỏ. Node nhận phải còn trạng thái NORMAL và tổng `mem_max` ≤ 100% RAM.
- **Phần 3:** chọn đề B vì sát với chính sự cố ở Phần 1. Không có số liệu traffic thật nên mọi ngưỡng chỉ là giá trị khởi điểm.

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
| Phân tích sự cố | Claude, Python, shell: thống kê log, xây timeline, giả thuyết và báo cáo. | Đối chiếu dòng log; đếm 1.544 lỗi 504, 1.231 lỗi 502 và 1.259 request của IP bot. Sửa “hơn 40 lần” thành “40 lần”. |
| Tool Proxmox | Claude và Python: viết validator, thuật toán migration, CLI và README. | Chạy snapshot; đối chiếu CPU 85,9% → 74,9%, RAM 93,0% → 81,7%; kiểm tra JSON, lỗi đầu vào (exit 2) và `NO_FEASIBLE_PLAN` (exit 3). |
| Kiểm thử tool | Claude và `unittest`: tạo test và kiểm tra bất biến. | 49 unit test đạt; kiểm tra trên 150 cluster ngẫu nhiên; sửa fixture sai và chạy lại trong khoảng 1 giây. |
| Nginx/nftables | Claude và tài liệu chính thức: nghiên cứu, thử cấu hình. | `nginx -t` đạt; 60 request cho 24 mã 200 và 36 mã 429; dry-run ghi 36 `REJECTED_DRY_RUN`. `nft -c -f` đạt, chưa nạp luật thật. |
| Hiệu đính và đóng gói | Claude, Python/ZIP: chuẩn hóa Markdown, ghép và đóng gói bài. | Đọc lại nội dung, sửa lỗi nhỏ và kiểm tra bản giải nén; có log kiểm tra đi kèm. |

## Phần chưa xong hoặc chưa hài lòng

- **Postmortem:** dòng 504 đầu tiên ở LB (`rt=60.587` lúc 01:33:05) nếu tính từ lúc bắt đầu request thì sớm hơn thời điểm `tar` báo lỗi khoảng 1 phút; mình chưa giải thích được (do định nghĩa mốc giờ của LB hay lệch đồng hồ). Báo cáo dài hơn mức 1–2 trang A4 do nhiều bảng bằng chứng, cần rút gọn nếu muốn bám sát đề.
- **Khắc phục tức thời:** chưa thể thử trên máy thật; chưa xét kỹ khả năng access log đang có file mở bị xóa (`lsof +L1`) khiến dung lượng không nhả.
- **Tool Proxmox:** heuristic không đảm bảo tối ưu toàn cục; chưa kiểm tra affinity, I/O, HA; chưa chạy trên Python 3.8–3.11 (chỉ 3.12.3); chưa có bước chuyển đổi trực tiếp từ output `pvesh`.
- **Phần 3:** chưa có benchmark nào, luật nftables mới chỉ kiểm tra cú pháp. Bản nháp dài hơn "một trang A4" vì kèm cấu hình.
- **Nhật ký:** các thông tin thời gian và việc tự kiểm chứng của chính bạn phải được điền thủ công.

## Nếu làm lại, bạn sẽ làm khác điều gì?

- Tự đọc log trước, rồi mới dùng AI đối chiếu; ghi giờ bắt đầu/kết thúc từng phiên ngay khi làm.
- Xin người ra đề file cấu hình nginx/php-fpm và `disk-check.sh` để loại bỏ các điểm "chưa biết".
- Chạy thử thuật toán migration sớm với dữ liệu bẩn và cluster ngẫu nhiên để phát hiện vấn đề hiệu năng sớm hơn, thay vì phát hiện ở bước chạy test.
