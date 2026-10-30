# Nhật ký làm bài

**Họ tên:** [BẠN ĐIỀN]
**Nhận đề lúc:** [BẠN ĐIỀN: giờ nhận email, dd/mm/yyyy]
**Nộp bài lúc:** [BẠN ĐIỀN]
**Tổng thời gian làm thật (ước tính):** [BẠN ĐIỀN]

> **Lưu ý về độ tin cậy của nhật ký này:** bản nháp được AI (Claude) soạn trong cùng phiên làm việc đã sinh ra phần lớn bài làm. AI chỉ quan sát được những gì diễn ra trong phiên chat/sandbox, **không biết** giờ bắt đầu/kết thúc thật, thời gian bạn tự đọc, chạy lại hay sửa ngoài phiên. Mọi ô đánh dấu **[BẠN ĐIỀN]** phải do chính bạn điền theo thực tế; nếu bạn chưa tự kiểm chứng một bước nào thì phải ghi đúng là chưa kiểm chứng, không ghi như đã làm.

## Các phiên làm việc

| Thời điểm | Thời lượng | Làm phần nào | Ghi chú (kẹt ở đâu, đã thử gì) |
|---|---|---|---|
| [BẠN ĐIỀN] | [BẠN ĐIỀN] | Đọc đề, giải nén `RnD-Test-Vietnix.zip`, đọc snapshot Phần 1 | Đọc `DE-BAI.md`, `MAU-NHAT-KY.md`, `df-h`, `du-var`, `free`, `top`, `ss`, `backup-sites.sh`, `logrotate-nginx.conf` |
| [BẠN ĐIỀN] | [BẠN ĐIỀN] | Phần 1: điều tra sự cố, viết `phan1-postmortem.md` | Đọc 5 nguồn log; thống kê log LB bằng script Python; đối chiếu số dòng. Kẹt: giả thuyết bot (IP `45.135.232.17`, UA AhrefsBot) có vẻ là thủ phạm nhưng đối chiếu thời gian cho thấy nó chỉ xuất hiện sau khi lỗi bắt đầu 8 phút. Còn một điểm không giải thích được (xem mục "Phần chưa xong") |
| [BẠN ĐIỀN] | [BẠN ĐIỀN] | Phần 2: tool Proxmox (`analyze_cluster.py`, test, README) | Dữ liệu có 5 loại bất thường cài sẵn (xem Giả định). Lỗi gặp: một test viết sai fixture (kế hoạch 2 bước thực ra chỉ cần 1 bước); bộ test chạy ~25 giây vì tìm kiếm migration nở theo cấp số nhân khi không có phương án, sửa bằng ghi nhớ trạng thái, ngân sách tìm kiếm và kiểm tra tổng sức chứa (còn ~1 giây) |
| [BẠN ĐIỀN] | [BẠN ĐIỀN] | Phần 3 (đề B): nghiên cứu và thử cấu hình | Đọc tài liệu nginx/nftables. Lỗi gặp: lần test đầu `limit_req` không có tác dụng vì dùng `return 200` (chạy ở pha rewrite, trước `limit_req`); đổi sang trả file tĩnh thì mới chặn được. `apt-get install` lần đầu lỗi 404 cho tới khi chạy `apt-get update` |
| [BẠN ĐIỀN] | [BẠN ĐIỀN] | Phần 4 và rà soát cuối | [BẠN ĐIỀN: bạn đã tự đọc lại, chạy lại gì] |

## Giả định đã đặt ra

- **Phần 1:** đề nói lỗi từ "khoảng 01:00" nhưng log cho thấy LB vẫn bình thường tới 01:32 và 5xx đầu tiên lúc 01:33:05. Mình lấy 01:33 làm mốc bắt đầu, còn 01:00 là lúc backup bắt đầu chứ không phải lúc lỗi bắt đầu. Các file cấu hình nginx/php-fpm, `disk-check.sh` và trigger Zabbix **không có** trong snapshot, nên mọi nhận định về `fastcgi_read_timeout`, cơ chế gửi cảnh báo đều ghi là suy luận hoặc chưa biết.
- **Phần 1:** `error.log` của nginx trong snapshot là bản rút gọn (670 dòng) trong khi `du` ghi 641 MB; mình không suy ra số lượng lỗi thật từ file này.
- **Phần 2:** ngưỡng 80% CPU / 85% RAM / 4:1 overcommit lấy từ đề xuất làm giá trị khởi điểm, không phải ngưỡng chính thức. Quy tắc dữ liệu bẩn do mình chọn: `cpu_usage` ngoài [0,1] không tự đổi đơn vị (nghi là %); `mem_total=262144` của `n06` nghi là MiB nhưng không tự sửa; `vmid` 2001 trùng trên n01 và n02 thì tính tải ở cả hai node và ghim VM; VM 2390 trỏ node không tồn tại thì bỏ. Node nhận phải còn trạng thái NORMAL và tổng `mem_max` ≤ 100% RAM.
- **Phần 3:** chọn đề B vì sát với chính sự cố ở Phần 1. Không có số liệu traffic thật nên mọi ngưỡng chỉ là giá trị khởi điểm.

## Câu hỏi đã gửi cho người ra đề

- [BẠN ĐIỀN: nếu bạn có gửi câu hỏi nào thì ghi; bản AI không gửi câu hỏi nào]

## Dùng AI và công cụ

| Bước | Công cụ | Dùng để làm gì | Bạn đã kiểm tra, sửa lại gì |
|---|---|---|---|
| Đọc và phân tích log Phần 1 | Claude (AI), Python, `grep`/`awk` trong sandbox | AI đọc log, thống kê LB (tỷ lệ 2xx/5xx, rt, IP/UA), hình thành giả thuyết và chuỗi nguyên nhân, soạn báo cáo | Số dòng trích dẫn lấy bằng `grep -n`/`cat -n` rồi đối chiếu lại (ví dụ `syslog:43-44`, `lb:1569`, `nginx/error.log:4`); số liệu 1.544 lần 504, 1.231 lần 502 và 1.259 request của IP bot đếm bằng script. Sửa 1 chỗ ghi "hơn 40 lần" thành "40 lần" sau khi đếm lại. Câu lệnh khắc phục **chưa chạy trên máy thật**; **[BẠN ĐIỀN: bạn đã tự đối chiếu/chạy thử thế nào]** |
| Phần 2: thiết kế thuật toán và viết code | Claude (AI) | Viết `analyze_cluster.py`, thuật toán tìm kiếm migration, README | Chạy tool trên snapshot thật; tự tính tay lại tải `hcm-c3-n01` và node nhận `n03` bằng script riêng (khớp: CPU 85,9%→74,9%, RAM 93,0%→81,7%); chạy với `--cpu-threshold 30` để ép trường hợp `NO_FEASIBLE_PLAN` (exit 3); kiểm tra `json.tool` trên stdout JSON; thử file không tồn tại và JSON hỏng (exit 2, không traceback) |
| Phần 2: unit test | Claude (AI) | Sinh 49 unit test (fixture tổng hợp) và test bất biến trên 150 cluster ngẫu nhiên | Chạy `python3 -m unittest discover -s tests`: 49 test, OK. Một test ban đầu FAIL do AI viết sai fixture, đã sửa fixture (không sửa để ép test pass); kết quả chạy lại OK trong ~1 giây |
| Phần 3: nghiên cứu | Claude (AI), web search/fetch | Đọc tài liệu chính thức của nginx và nftables | Đã mở các URL tài liệu chính thức nginx (limit_req, realip) và nftables wiki (Meters) và đối chiếu từng con số (16 nghìn trạng thái 64 byte/MB, mặc định 503, `dry_run` từ 1.17.1, `ct count` chỉ dùng với `add`). Cài nginx 1.24.0 và nftables 1.0.9 trong sandbox: `nginx -t` OK, thử tải thực tế (24 trả 200 và 36 trả 429 trên 60 request; chế độ dry-run ghi 36 `REJECTED_DRY_RUN`), `nft -c -f` OK (chưa nạp luật thật) |
| Hiệu đính Markdown, ghép bài | Claude (AI) | Định dạng, rút gọn | Đọc lại; **[BẠN ĐIỀN: bạn đã tự đọc lại toàn bộ chưa]** |

Phân biệt: những gì ghi là "đã chạy/đã đếm" ở trên là kết quả do lệnh thật trả về trong phiên; những nhận định nguyên nhân (mục "Inference" trong postmortem), mức ngưỡng và khuyến nghị kiến trúc là **ý kiến của AI**, chưa được kiểm chứng trên hệ thống thật.

## Phần chưa xong hoặc chưa hài lòng

- **Postmortem:** dòng 504 đầu tiên ở LB (`rt=60.587` lúc 01:33:05) nếu tính từ lúc bắt đầu request thì sớm hơn thời điểm `tar` báo lỗi khoảng 1 phút; mình chưa giải thích được (do định nghĩa mốc giờ của LB hay lệch đồng hồ). Báo cáo dài hơn mức 1–2 trang A4 do nhiều bảng bằng chứng, cần rút gọn nếu muốn bám sát đề.
- **Khắc phục tức thời:** chưa thể thử trên máy thật; chưa xét kỹ khả năng access log đang có file mở bị xóa (`lsof +L1`) khiến dung lượng không nhả.
- **Tool Proxmox:** heuristic không đảm bảo tối ưu toàn cục; chưa kiểm tra affinity, I/O, HA; chưa chạy trên Python 3.8–3.11 (chỉ 3.12.3); chưa có bước chuyển đổi trực tiếp từ output `pvesh`.
- **Phần 3:** chưa có benchmark nào, luật nftables mới chỉ kiểm tra cú pháp. Bản nháp dài hơn "một trang A4" vì kèm cấu hình.
- **Nhật ký:** các thông tin thời gian và việc tự kiểm chứng của chính bạn phải được điền thủ công.

## Nếu làm lại, bạn sẽ làm khác điều gì?

- Tự đọc log trước, rồi mới dùng AI đối chiếu, thay vì để AI dẫn dắt giả thuyết; ghi giờ bắt đầu/kết thúc từng phiên ngay khi làm.
- Xin người ra đề file cấu hình nginx/php-fpm và `disk-check.sh` để loại bỏ các điểm "chưa biết".
- Chạy thử thuật toán migration sớm với dữ liệu bẩn và cluster ngẫu nhiên để phát hiện vấn đề hiệu năng sớm hơn, thay vì phát hiện ở bước chạy test.
