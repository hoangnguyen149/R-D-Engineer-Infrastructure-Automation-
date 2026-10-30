# Điều tra và xử lý sự cố web-hcm-07

Nguồn: RnD-Test-Vietnix.zip, toàn bộ thư mục phan1-su-co. Phạm vi: Phần 1 của đề; không phải lời giải phần Proxmox và nghiên cứu. Thời gian sự kiện: UTC+7. Đây là phân tích dữ liệu tĩnh và runbook đề xuất, chưa thực thi trên máy chủ thật. Các thống kê là số đếm trong bộ dữ liệu được cung cấp, không ngoại suy toàn bộ traffic production.

## 1. Kết luận chính

Đây là sự cố cạn dung lượng phân vùng gốc, không phải tràn RAM. Cấu hình logrotate Nginx có lỗi `dailly`, khiến nhóm log Nginx bị bỏ qua từ 14/10 đến 20/10. Access log tăng lên 37G; lúc 00:30 ngày 20/10 phân vùng đã dùng 87%. Backup chạy 01:00, tạo thêm file 16G trước khi thất bại, làm dung lượng trống về 0. MySQL không ghi được binlog, PHP không ghi được session và pool bão hòa, Nginx gặp lỗi ghi file tạm, lỗi kết nối upstream và timeout.

Khoảng 40 website nằm trên node theo mô tả đề; access log chỉ chứng minh 5 hostname có lỗi. Có 2.775 request 502/504 trong 4.718 request được cung cấp (58,82%). Từ 01:33 đến cuối log, tỷ lệ lỗi là 88,04%. Không có bằng chứng về thời điểm phục hồi hoặc số giao dịch mất; không được ghi “đã khắc phục hoàn toàn” hay MTTR chính xác.

## 2. Timeline và bằng chứng

| Thời điểm | Sự kiện | Nguồn và ý nghĩa |
|---|---|---|
| 12–13/10, 00:00 | Không thấy lỗi logrotate; disk 55–56% lúc 00:30 | syslog, mốc nền |
| 13/10 17:42:30 | `COMMAND=/usr/bin/vim /etc/logrotate.d/nginx` | Thay đổi cấu hình có liên quan; chưa có diff để quy kết chính xác ai đưa lỗi vào |
| 13/10 17:44:02 | `COMMAND=/usr/bin/systemctl reload nginx` | Reload Nginx không kiểm tra cú pháp logrotate |
| 14/10 00:00:02 | `unknown option 'dailly' -- ignoring line`; `found error in /var/log/nginx/*.log , skipping` | Bằng chứng trực tiếp rotation bị bỏ qua |
| 14–20/10 | Lặp lại lỗi mỗi ngày, tổng 7 lần chạy | Trạng thái `Deactivated successfully` không đủ chứng minh từng stanza thành công |
| 14–18/10 00:30 | Disk 57%, 62%, 67%, 72%, 77% | Dung lượng tăng khoảng 5 điểm phần trăm/ngày |
| 19/10 00:30:02 | `WARN / usage 82%` | Đã có dấu hiệu cảnh báo, chưa có bằng chứng cảnh báo được gửi/ack |
| 19/10 01:42:11 | `backup done size=19.1G` | Bản backup thành công gần nhất theo log; vẫn cần kiểm tra khả năng phục hồi |
| 20/10 00:30:02 | `WARN / usage 87%` | Chỉ còn xấp xỉ 15,3G nếu lấy 118G × 13%; số làm tròn, không phải byte chính xác |
| 20/10 01:00:02 | `start backup /home -> /var/backups/sites-20261020.tar.gz` | Ghi backup mới lên cùng phân vùng, giữ backup cũ đến khi thành công |
| 01:32:57–58 | `Wrote only 4096 of 10240 bytes`; `ERROR backup failed exit=2, keep old backups` | Backup mới thất bại, để lại 16G |
| 01:32:59 | Nginx `pwrite()` file body lỗi `(28: No space left on device)` | Dịch vụ bắt đầu không ghi được dữ liệu tạm |
| 01:33:01 | Nginx không ghi được `access.log`, errno 28 | Dùng access log LB để đo ảnh hưởng, không dựa vào access log cục bộ bị ngừng ghi |
| 01:33:04 | MySQL `Disk is full writing './binlog.000187'` | Chờ giải phóng dung lượng, retry 60 giây |
| 01:33:05 | LB ghi 504 đầu tiên | Mốc đầu tiên quan sát trong access log; chưa xác định thời điểm bắt đầu request vì thiếu cấu hình timestamp LB |
| 01:33:06 | PHP `session_start()` lỗi hết chỗ | Session cũng chịu ảnh hưởng trực tiếp |
| 01:33:16 | Nginx connect socket PHP lỗi errno 11 | Upstream không tiếp nhận kịp; không phải bằng chứng socket bị xóa |
| 01:34:02 | `server reached pm.max_children setting (50)` | Worker pool bão hòa |
| 01:34:40 | Zabbix item không supported do `Cannot write to log file` | Giám sát cục bộ cũng bị ảnh hưởng |
| 01:41:03–01:56:40 | 1.259 request từ 45.135.232.17 tới tintuc24h.net | Đợt truy cập sau khi sự cố đã phát sinh; có thể làm trầm trọng thêm |
| 02:21:11 | On-call SSH thành công | Muộn hơn lỗi LB đầu tiên 48 phút 06 giây; đây không phải MTTD |
| 02:23:41–53 | Snapshot: disk 100%, RAM available 22.053 MiB, CPU idle 94,9% | Xác nhận nút thắt dung lượng |
| 02:25:01 | LB vẫn ghi 502 | Khoảng quan sát từ lỗi đầu đến lỗi cuối là 51 phút 56 giây, chưa phải thời gian downtime hoàn chỉnh |

## 3. Chuỗi nguyên nhân

1. **Lỗi cấu hình:** `snapshot/logrotate-nginx.conf` chứa `dailly` thay vì `daily`. Syslog chứng minh lỗi và skip, không chỉ suy đoán từ chính tả.
2. **Tích tụ log:** `snapshot/du-var.txt`: `/var/log` 38G, riêng access.log 37G; file xoay gần nhất có timestamp 13/10. Dữ liệu hỗ trợ rotation không hoạt động nhiều ngày. Không có access log trước sự cố để khẳng định nguyên nhân traffic tạo toàn bộ 37G.
3. **Trigger backup:** script đặt `DEST=/var/backups`, tạo file mới trước rồi mới xóa bản hôm qua nếu thành công. Đây là cách giữ backup cũ có ích, nhưng thiếu kiểm tra dung lượng cao điểm và thiếu tách phân vùng. Tại thời điểm chạy cần chứa đồng thời backup cũ + mới + tăng trưởng log/dữ liệu + dự phòng.
4. **Cạn dung lượng:** `df-h.txt`: `/dev/sda2 118G 118G 0 100% /`. Backup thất bại để lại bản dở 16G và bản 19G hôm trước.
5. **MySQL và PHP bị chặn:** binlog không ghi được; snapshot đếm 49 process có chuỗi `Waiting for`, nhưng không chứa chi tiết state nên không được nói cả 49 đều chờ binlog. PHP lỗi DB greeting, hết chỗ lưu session, chạm 50 worker.
6. **Nginx trả lỗi:** timeout đọc upstream phù hợp 504; lỗi connect socket errno 11 phù hợp 502. Snapshot socket `LISTEN 511 511` hỗ trợ queue bão hòa. Không ánh xạ từng dòng error log với từng request LB khi không có request ID chung.
7. **Yếu tố kéo dài:** backup dở không được xử lý, rotation vẫn sai, không thấy hành động với cảnh báo disk, giám sát cục bộ bị hỏng khi disk đầy.

## 4. Giả thuyết và mức độ loại trừ

| Giả thuyết | Đánh giá có căn cứ |
|---|---|
| Hết RAM/OOM | Không được hỗ trợ ở snapshot: available 22.053/31.994 MiB ≈ 68,9%, swap 12 MiB. `free` 611 MiB không có nghĩa RAM cạn. Dmesg chỉ là tail nên không chứng minh lịch sử không từng có OOM. |
| CPU quá tải | Idle 94,9%, iowait 0,6%, load 1,84/2,10/1,97. Không có số core để kết luận chỉ từ load. Snapshot không mô tả mọi thời điểm trước đó. |
| Bot/DDoS là trigger | Đợt IP nổi bật xuất hiện 01:41:03, sau lỗi 01:33:05. Không giải thích lỗi logrotate và tăng disk nhiều ngày. User-Agent AhrefsBot tự khai báo, không chứng minh bot thật. |
| PHP-FPM bị tắt/socket mất | Socket LISTEN và process còn tồn tại; có bằng chứng pool/queue bão hòa. |
| MySQL crash/corrupt | mysqld còn chạy, log ghi chờ dung lượng. Không có bằng chứng corruption trong tập dữ liệu, nhưng chưa kiểm chứng tính toàn vẹn dữ liệu. |
| Tấn công port 3306 | UFW đã BLOCK lúc 01:51:10, sau sự cố. Không đồng nghĩa đã xâm nhập; cùng IP với HTTP không đủ chứng minh quan hệ nhân quả. |
| Inode/quota | Chưa có `df -i`/quota để loại trừ hoàn toàn, nhưng block capacity đầy đã được chứng minh. |
| DNS warning 14/10 | Có warning reverse DNS, chưa có chuỗi bằng chứng nối với disk full ngày 20/10. |

## 5. Runbook khôi phục tại thời điểm 02:23

Các lệnh dưới đây dành cho kỹ sư có quyền quản trị trên đúng máy. Chạy từng bước, kiểm tra kết quả trước khi tiếp tục; không dán toàn bộ thành một script. Không chạy lệnh cleanup trên `/home`, `/var/lib/mysql`, source code, session của khách hoặc các bản backup tốt. Không chạy `rm -rf`, `RESET MASTER`, purge binlog tùy tiện, hay tăng max_children để che triệu chứng.

### Bước 1 — Xác nhận và giữ bằng chứng

```bash
hostname -f
date -Is
df -hT /
df -i /
findmnt -T /var/backups
findmnt -T /var/log/nginx
free -m
uptime
systemctl --no-pager status nginx php8.1-fpm mysql
ss -xlp
sudo lsof +L1
sudo mysql -e 'SHOW FULL PROCESSLIST;'
```

`lsof +L1` tìm file đã xóa nhưng process còn mở; xóa tên file chưa chắc giải phóng dung lượng. Nếu `lsof` chưa cài, không cài thêm khi disk đầy; dùng `/proc/<pid>/fd` hoặc công cụ hiện có. Dùng xác thực MySQL đã cấu hình, không truyền mật khẩu rõ trên command line.

Chụp output về máy quản trị hoặc volume khác đã xác minh, không ghi dump lớn vào `/`. Có thể giữ bản cấu hình rất nhỏ ở `/run` nếu cần, nhưng `/run` là tạm và không thay thế lưu chứng cứ lâu dài. Thu thập log tập trung, checksum file đề và đánh số dòng cho báo cáo.

### Bước 2 — Ngăn phát sinh thêm tải ghi

```bash
sudo crontab -l
sudo rg -n 'backup-sites' /etc/crontab /etc/cron.d
ps -eo pid,ppid,lstart,args --forest
```

Tạm vô hiệu hóa đúng lịch backup-sites sau khi lưu cấu hình; không dừng toàn bộ cron. Theo log, backup đã thất bại nên không mặc định còn tiến trình để kill. Nếu xác minh có job vẫn chạy, dừng qua unit/job chính xác hoặc SIGTERM vào PID đã đối chiếu; không dùng `pkill tar` diện rộng.

Nếu có node thay thế và dữ liệu/session đồng bộ, drain node lỗi qua LB theo quy trình. Nếu không có, không tự chuyển traffic sang máy chưa sẵn sàng. Có thể giảm lưu lượng crawl tại LB/WAF theo IP + hostname sau kiểm tra; tránh chặn IP LB trên backend hoặc chặn toàn bộ website chỉ vì User-Agent.

### Bước 3 — Tạo dung lượng mà vẫn giữ dữ liệu

Ưu tiên mở rộng volume hoặc chuyển bản backup dở sang volume độc lập đã có. Không có thông tin LVM/filesystem nên không đưa lệnh resize áp dụng mù quáng. Kiểm tra `lsblk -f`, `findmnt /` rồi dùng quy trình mở rộng phù hợp loại filesystem.

Ví dụ **chỉ khi** `/mnt/incident-archive` là volume khác, đã mount, đủ dung lượng, và không có process còn ghi file backup:

```bash
findmnt -T /mnt/incident-archive
df -h /mnt/incident-archive
sudo lsof /var/backups/sites-20261020.tar.gz
sudo install -d -m 0700 /mnt/incident-archive/web-hcm-07-20261020
sudo cp --preserve=all -- /var/backups/sites-20261020.tar.gz \
  /mnt/incident-archive/web-hcm-07-20261020/
sudo cmp -- /var/backups/sites-20261020.tar.gz \
  /mnt/incident-archive/web-hcm-07-20261020/sites-20261020.tar.gz
```

Chỉ nếu copy và cmp đều thành công, lưu hash/biên bản và đã xác nhận đây là artifact dở của job thất bại, bỏ bản cục bộ trùng để thu hồi chỗ:

```bash
sudo rm -- /var/backups/sites-20261020.tar.gz
df -h /
```

Bản dở vẫn được giữ nguyên trên volume archive; không xóa bản 19/10. Dung lượng dự kiến thu hồi khoảng 16G, cần xác nhận bằng `df` thực tế. Nếu chính sách cấm cả việc di dời bản backup dở, dùng mở rộng volume. Nếu chưa có nơi lưu, không tự giả định đường dẫn `/mnt` là ổ khác và không tự xóa backup. Copy 16G có thể mất thời gian; chọn phương án theo hạ tầng sẵn có.

### Bước 4 — Xử lý log 37G và sửa logrotate

Sau khi có khoảng trống, lưu bản cấu hình gốc, sửa đúng `dailly` thành `daily`, chạy dry-run:

```bash
sudo cp -a /etc/logrotate.d/nginx /mnt/incident-archive/web-hcm-07-20261020/nginx-logrotate.before
sudoedit /etc/logrotate.d/nginx
sudo logrotate --debug /etc/logrotate.conf
sudo nginx -t
```

Đọc toàn bộ lỗi của dry-run, không chỉ nhìn status systemd. `nginx -t` kiểm tra Nginx, không thay thế kiểm tra logrotate. Sau khi hết lỗi cấu hình và đủ dung lượng cho việc nén/rotation, có thể dùng:

```bash
sudo logrotate --verbose --force /etc/logrotate.d/nginx
sudo lsof +L1
df -h /
```

Rotation có `delaycompress`: file vừa xoay còn nguyên kích thước. Rename trên cùng filesystem không trả lại 37G. Xác minh Nginx đã reopen, không còn giữ file xoay, rồi archive file xoay thực tế sang volume khác, kiểm tra byte/hash trước khi bỏ bản cục bộ. Nếu reopen qua hook không hoạt động, dùng `sudo nginx -s reopen` với đúng instance/config; kiểm tra log và file descriptor. Không copy/truncate active log tùy tiện: có rủi ro mất bằng chứng và log phát sinh trong lúc copy. Không nén file 37G trên phân vùng gần đầy mà chưa tính headroom.

### Bước 5 — Để MySQL hồi phục, kiểm tra trước khi restart

```bash
sudo mysqladmin ping
sudo mysql -e 'SELECT NOW(); SHOW FULL PROCESSLIST;'
sudo journalctl -u mysql --since '5 minutes ago' --no-pager
sudo journalctl -u php8.1-fpm --since '5 minutes ago' --no-pager
ss -xlp
```

MySQL log nói retry 60 giây; theo dõi qua ít nhất 1–2 chu kỳ sau khi có dung lượng. `ping` và `SELECT` chỉ chứng minh liveness/đọc, không chứng minh write đã khỏe. Kiểm tra binlog có tiến triển và request ghi qua tài khoản/tenant thử nghiệm được phép; không tạo/xóa bảng trong database khách để test. Nếu chưa có môi trường thử ghi, ghi rõ giới hạn xác minh.

Nếu MySQL còn kẹt, điều tra processlist/locks/error log, không restart mặc định. Sau khi DB ổn, nếu PHP còn worker treo, kiểm tra cấu hình rồi reload:

```bash
sudo php-fpm8.1 -t
sudo systemctl reload php8.1-fpm
```

Chỉ restart PHP nếu reload không giải quyết và đã tính ảnh hưởng request đang chạy. Không restart cả ba dịch vụ khi disk còn 100%.

### Bước 6 — Xác minh qua LB và theo dõi

Kiểm tra cả 5 hostname trong mẫu và danh sách khoảng 40 website từ inventory. Kiểm tra static, trang động có DB, session/đăng nhập bằng tài khoản test. Dùng URL thật đã xác minh DNS/TLS, ví dụ:

```bash
curl --silent --show-error --output /dev/null \
  --write-out 'HTTP=%{http_code} total=%{time_total}\n' \
  https://site42.vn/
```

Không dùng 200 đơn lẻ để đóng incident. Tiêu chí đề xuất: disk thoát critical và còn đủ dự phòng; không phát sinh ENOSPC; queue PHP giảm; MySQL hết trạng thái chờ bất thường; LB 502/504 về baseline ổn định 15–30 phút; giám sát có dữ liệu trở lại. Ghi thời gian từng thao tác, trước/sau, kết quả và người thực hiện. Nếu cấu hình mới lỗi, rollback bản đã biết tốt (hoặc bản gốc đã sửa typo), không phục hồi nguyên lỗi `dailly`.

## 6. Phòng ngừa và tiêu chí nghiệm thu

| Ưu tiên | Việc cần làm | Người phụ trách đề xuất | Kiểm chứng |
|---|---|---|---|
| P0 | Sửa typo, kiểm tra mọi stanza, chạy thử rotation | Operations | Dry-run sạch; file được xoay; Nginx ghi file mới |
| P0 | Tách backup khỏi root hoặc bảo đảm peak capacity | Infrastructure | Job đủ chỗ cho backup mới + tăng trưởng + reserve |
| P0 | Alert disk theo % và byte, theo dõi từ bên ngoài node | Monitoring | Thử cảnh báo/ack/escalation, kể cả khi agent mất dữ liệu |
| P1 | Version control + review cấu hình + validation trước rollout | Platform | Thay đổi sai bị CI chặn |
| P1 | `daily` + `maxsize` và chạy logrotate thường xuyên hơn | Operations | Thử vượt ngưỡng và chứng minh thực sự xoay |
| P1 | Backup `.partial`, lock chống chồng job, verify rồi promote, retention | Backup owner | Job thiếu chỗ fail sớm; giữ bản tốt; phục hồi thử thành công |
| P1 | Rate limit L7 theo tenant/IP, giới hạn trusted proxy | Web platform | Không gom mọi khách vào IP LB; đo false positive |
| P1 | FPM pool theo tenant, slowlog, queue alert | Hosting | Một tenant chậm không chiếm toàn bộ pool |
| P2 | Tách filesystem/quota cho log, backup, DB và tenant | Infrastructure | Bài test fill log không làm root/DB hết chỗ |

Ngưỡng gợi ý, cần điều chỉnh theo baseline: disk warning 75%, critical 85%, emergency 90%; dự báo hết chỗ trong 24 giờ; 5xx >5%/5 phút với điều kiện số request tối thiểu; PHP active >80% max_children hoặc queue tăng kéo dài. Giữ khoảng trống lớn hơn kích thước backup dự kiến cộng tăng trưởng trong thời gian chạy và dự phòng; không chỉ dùng ngưỡng phần trăm cố định. Tại 87%/118G, còn ~15,3G, thấp hơn backup gần nhất 19,1G ngay cả chưa cộng dự phòng.

`maxsize` không tự tạo daemon theo dõi: chỉ được đánh giá khi logrotate chạy. `rotate 14` là 14 bản, không nhất thiết 14 ngày nếu xoay nhiều lần/ngày. Không thể suy ra chỉ cần tăng timeout hoặc max_children là hết lỗi.

## 7. Thống kê đầy đủ và phương pháp

Parse tất cả 4.718 dòng LB; đều upstream web-hcm-07. Không có dòng bị bỏ qua trong lần phân tích. Tỷ lệ lỗi = (502+504)/tổng request của nhóm. P95 dùng nearest-rank: phần tử ceil(0,95×N) trong dãy `rt` tăng dần, đơn vị giây. Timestamp dùng nguyên giá trị log UTC+7; chưa biết LB ghi thời điểm bắt đầu hay kết thúc request. `rt` không đồng nghĩa thời gian xử lý riêng của backend. Không cộng số dòng error log vào request lỗi LB: chúng là những phép đo khác nhau.

### Tổng HTTP status

| Status | Số request | Tỷ lệ |
|---|---:|---:|
| 200 | 1914 | 40.57% |
| 404 | 29 | 0.61% |
| 502 | 1231 | 26.09% |
| 504 | 1544 | 32.73% |

### Theo giai đoạn

| Nhóm | Request | 502/504 | Tỷ lệ lỗi | rt trung bình (s) | P95 (s) |
|---|---:|---:|---:|---:|---:|
| 00:50:00–01:00:00 | 352 | 0 | 0.00% | 0.186 | 0.333 |
| 01:00:00–01:33:00 | 1214 | 0 | 0.00% | 0.182 | 0.332 |
| 01:33:00–02:26:00 | 3152 | 2775 | 88.04% | 29.799 | 60.797 |

### Theo hostname — toàn bộ cửa sổ

| Nhóm | Request | 502/504 | Tỷ lệ lỗi | rt trung bình (s) | P95 (s) |
|---|---:|---:|---:|---:|---:|
| noithatmoc.com | 660 | 318 | 48.18% | 16.416 | 60.787 |
| phongkhamanbinh.vn | 689 | 282 | 40.93% | 15.840 | 60.759 |
| shop.anhduongfood.vn | 688 | 279 | 40.55% | 15.907 | 60.793 |
| site42.vn | 667 | 302 | 45.28% | 17.640 | 60.820 |
| tintuc24h.net | 2014 | 1594 | 79.15% | 24.705 | 60.463 |

### Theo từng phút — phút 02:25 chỉ có một bản ghi

| Nhóm | Request | 502/504 | Tỷ lệ lỗi | rt trung bình (s) | P95 (s) |
|---|---:|---:|---:|---:|---:|
| 00:50 | 34 | 0 | 0.00% | 0.202 | 0.327 |
| 00:51 | 37 | 0 | 0.00% | 0.177 | 0.336 |
| 00:52 | 41 | 0 | 0.00% | 0.207 | 0.345 |
| 00:53 | 32 | 0 | 0.00% | 0.185 | 0.342 |
| 00:54 | 40 | 0 | 0.00% | 0.214 | 0.326 |
| 00:55 | 29 | 0 | 0.00% | 0.134 | 0.319 |
| 00:56 | 38 | 0 | 0.00% | 0.159 | 0.322 |
| 00:57 | 38 | 0 | 0.00% | 0.192 | 0.333 |
| 00:58 | 36 | 0 | 0.00% | 0.177 | 0.327 |
| 00:59 | 27 | 0 | 0.00% | 0.211 | 0.330 |
| 01:00 | 43 | 0 | 0.00% | 0.185 | 0.321 |
| 01:01 | 28 | 0 | 0.00% | 0.188 | 0.312 |
| 01:02 | 47 | 0 | 0.00% | 0.191 | 0.307 |
| 01:03 | 36 | 0 | 0.00% | 0.164 | 0.338 |
| 01:04 | 33 | 0 | 0.00% | 0.185 | 0.340 |
| 01:05 | 39 | 0 | 0.00% | 0.208 | 0.311 |
| 01:06 | 26 | 0 | 0.00% | 0.161 | 0.341 |
| 01:07 | 26 | 0 | 0.00% | 0.216 | 0.323 |
| 01:08 | 32 | 0 | 0.00% | 0.161 | 0.313 |
| 01:09 | 35 | 0 | 0.00% | 0.165 | 0.339 |
| 01:10 | 32 | 0 | 0.00% | 0.157 | 0.315 |
| 01:11 | 38 | 0 | 0.00% | 0.191 | 0.341 |
| 01:12 | 34 | 0 | 0.00% | 0.181 | 0.339 |
| 01:13 | 39 | 0 | 0.00% | 0.186 | 0.341 |
| 01:14 | 54 | 0 | 0.00% | 0.203 | 0.337 |
| 01:15 | 40 | 0 | 0.00% | 0.160 | 0.286 |
| 01:16 | 32 | 0 | 0.00% | 0.171 | 0.338 |
| 01:17 | 25 | 0 | 0.00% | 0.185 | 0.343 |
| 01:18 | 40 | 0 | 0.00% | 0.178 | 0.311 |
| 01:19 | 40 | 0 | 0.00% | 0.170 | 0.302 |
| 01:20 | 43 | 0 | 0.00% | 0.196 | 0.340 |
| 01:21 | 44 | 0 | 0.00% | 0.173 | 0.331 |
| 01:22 | 33 | 0 | 0.00% | 0.207 | 0.332 |
| 01:23 | 34 | 0 | 0.00% | 0.177 | 0.332 |
| 01:24 | 51 | 0 | 0.00% | 0.158 | 0.314 |
| 01:25 | 44 | 0 | 0.00% | 0.192 | 0.329 |
| 01:26 | 34 | 0 | 0.00% | 0.188 | 0.330 |
| 01:27 | 48 | 0 | 0.00% | 0.187 | 0.337 |
| 01:28 | 30 | 0 | 0.00% | 0.190 | 0.328 |
| 01:29 | 28 | 0 | 0.00% | 0.161 | 0.322 |
| 01:30 | 35 | 0 | 0.00% | 0.190 | 0.310 |
| 01:31 | 37 | 0 | 0.00% | 0.186 | 0.346 |
| 01:32 | 34 | 0 | 0.00% | 0.184 | 0.338 |
| 01:33 | 36 | 26 | 72.22% | 27.136 | 60.755 |
| 01:34 | 47 | 43 | 91.49% | 37.538 | 60.725 |
| 01:35 | 31 | 27 | 87.10% | 35.682 | 60.927 |
| 01:36 | 34 | 27 | 79.41% | 37.425 | 60.958 |
| 01:37 | 40 | 33 | 82.50% | 39.607 | 60.892 |
| 01:38 | 48 | 41 | 85.42% | 35.461 | 60.866 |
| 01:39 | 31 | 27 | 87.10% | 25.691 | 60.901 |
| 01:40 | 26 | 20 | 76.92% | 37.638 | 60.940 |
| 01:41 | 103 | 97 | 94.17% | 24.663 | 60.483 |
| 01:42 | 117 | 108 | 92.31% | 25.892 | 60.619 |
| 01:43 | 118 | 112 | 94.92% | 26.604 | 60.198 |
| 01:44 | 118 | 107 | 90.68% | 28.635 | 60.544 |
| 01:45 | 135 | 126 | 93.33% | 33.191 | 60.530 |
| 01:46 | 130 | 124 | 95.38% | 27.911 | 60.632 |
| 01:47 | 110 | 107 | 97.27% | 32.863 | 60.694 |
| 01:48 | 122 | 110 | 90.16% | 25.852 | 60.306 |
| 01:49 | 121 | 114 | 94.21% | 36.392 | 60.639 |
| 01:50 | 127 | 117 | 92.13% | 31.045 | 60.543 |
| 01:51 | 120 | 110 | 91.67% | 29.772 | 60.716 |
| 01:52 | 108 | 99 | 91.67% | 30.820 | 60.708 |
| 01:53 | 111 | 99 | 89.19% | 24.723 | 60.441 |
| 01:54 | 106 | 99 | 93.40% | 23.832 | 60.304 |
| 01:55 | 115 | 108 | 93.91% | 31.542 | 60.684 |
| 01:56 | 87 | 83 | 95.40% | 33.906 | 60.699 |
| 01:57 | 36 | 30 | 83.33% | 22.119 | 60.892 |
| 01:58 | 35 | 27 | 77.14% | 33.954 | 60.840 |
| 01:59 | 34 | 28 | 82.35% | 30.888 | 60.903 |
| 02:00 | 33 | 27 | 81.82% | 32.120 | 60.875 |
| 02:01 | 41 | 32 | 78.05% | 32.912 | 60.850 |
| 02:02 | 39 | 31 | 79.49% | 31.525 | 60.980 |
| 02:03 | 45 | 37 | 82.22% | 35.095 | 60.856 |
| 02:04 | 37 | 28 | 75.68% | 25.240 | 60.928 |
| 02:05 | 33 | 26 | 78.79% | 25.798 | 60.934 |
| 02:06 | 42 | 34 | 80.95% | 27.592 | 60.820 |
| 02:07 | 42 | 33 | 78.57% | 29.131 | 60.749 |
| 02:08 | 37 | 30 | 81.08% | 38.118 | 60.893 |
| 02:09 | 32 | 23 | 71.88% | 19.229 | 60.844 |
| 02:10 | 44 | 35 | 79.55% | 26.862 | 60.893 |
| 02:11 | 35 | 31 | 88.57% | 33.061 | 60.880 |
| 02:12 | 27 | 22 | 81.48% | 27.459 | 60.900 |
| 02:13 | 39 | 32 | 82.05% | 37.421 | 60.879 |
| 02:14 | 31 | 23 | 74.19% | 23.902 | 60.863 |
| 02:15 | 32 | 27 | 84.38% | 34.143 | 60.794 |
| 02:16 | 41 | 34 | 82.93% | 33.018 | 60.891 |
| 02:17 | 32 | 28 | 87.50% | 30.440 | 60.891 |
| 02:18 | 37 | 34 | 91.89% | 32.888 | 60.950 |
| 02:19 | 46 | 37 | 80.43% | 21.565 | 60.821 |
| 02:20 | 33 | 26 | 78.79% | 29.574 | 60.818 |
| 02:21 | 31 | 22 | 70.97% | 26.425 | 60.839 |
| 02:22 | 27 | 20 | 74.07% | 31.613 | 60.853 |
| 02:23 | 39 | 30 | 76.92% | 20.729 | 60.639 |
| 02:24 | 30 | 23 | 76.67% | 29.066 | 60.952 |
| 02:25 | 1 | 1 | 100.00% | 0.005 | 0.005 |

### Tài nguyên và sự kiện dịch vụ

| Chỉ số | Giá trị |
|---|---|
| Root | 118G/118G, available 0 |
| /var | 87G; các thư mục con không cộng thêm lần nữa |
| /var/log | 38G, gồm Nginx access 37G và error 641M |
| /var/backups | 35G, gồm bản cũ 19G và bản dở 16G |
| /var/lib | 14G, bao gồm MySQL 12G |
| /home | 21G |
| RAM | Total 31.994 MiB, available 22.053 MiB |
| CPU | Idle 94,9%, iowait 0,6% |
| PHP socket | LISTEN, queue 511/511 |
| DB process chứa Waiting for | 49, thiếu state chi tiết |
| Logrotate | 7 lần skip Nginx; mỗi lần có 2 dòng lỗi |
| MySQL disk full | 6 bản ghi trong mysql/error.log, phản chiếu trong syslog; không tính thành 12 sự kiện độc lập |
| Nginx error log | 670 dòng: 371 timeout, 296 EAGAIN, 2 ENOSPC, 1 warning buffering |
| PHP log | 55 dòng: 40 max_children, 7 DB greeting, 6 slow, 1 session ENOSPC, 1 NOTICE |

### Phân tích traffic nổi bật

IP 45.135.232.17 tạo 1.259 request (26,69% mẫu), toàn bộ tới tintuc24h.net, trong 01:41:03–01:56:40: 636 lỗi 502 và 623 lỗi 504. User-Agent tự khai AhrefsBot. Không xác minh danh tính bot từ User-Agent.

Nếu bỏ IP này, vẫn còn 1.516 lỗi/3.459 request = 43,83% toàn cửa sổ; riêng giai đoạn từ 01:33 còn 1.516/1.893 = 80,08%. Do vậy sự cố không được giải thích bằng riêng đợt bot. Mức request/phút tăng rõ trong 01:41–01:56, nhưng trước đó lỗi đã xuất hiện. Các tỷ lệ này mô tả log mẫu, không chứng minh cường độ DDoS trên toàn mạng.

## 8. Mẫu postmortem rút gọn để tách thành phan1-postmortem.md

**Executive Summary.** Ngày 20/10/2026, node hosting web-hcm-07 gặp 502/504 diện rộng; LB ghi lỗi đầu tiên lúc 01:33:05 và vẫn còn lỗi lúc 02:25:01. Trong bộ log có 2.775/4.718 request lỗi, thuộc 5 hostname; khoảng 40 website là phạm vi tiềm năng theo đề. Nguyên nhân gốc là cấu hình logrotate sai `dailly`, làm log tích tụ; backup ghi cùng root là tác nhân đẩy disk tới 100%. Hệ quả là MySQL không ghi được binlog, PHP bị nghẽn và Nginx không phục vụ được upstream; chưa có dữ liệu xác nhận khôi phục.

**Timeline.** 13/10 17:42 sửa cấu hình logrotate; 14–20/10 logrotate skip Nginx. Disk tăng từ 57% ngày 14 lên 82% ngày 19 và 87% ngày 20 lúc 00:30. Backup bắt đầu 01:00:02, thất bại 01:32:57–58; Nginx ENOSPC 01:32:59, MySQL disk full 01:33:04, PHP session ENOSPC 01:33:06 và max_children=50 lúc 01:34:02. On-call vào máy 02:21:11; snapshot 02:23 xác nhận root 100%.

**Nguyên nhân và bằng chứng.** syslog ghi `unknown option 'dailly'` và `skipping`, trùng cấu hình trong snapshot. du-var ghi access.log 37G, backup 19G + 16G. backup-sites.sh tạo bản mới trong /var/backups trước khi xóa bản hôm qua, không preflight dung lượng. df ghi `/dev/sda2 118G 118G 0 100% /`. MySQL ghi `Disk is full writing './binlog.000187'`; PHP chạm 50 worker; Nginx ghi timeout và errno 11 tới socket PHP. Dòng thời gian và snapshot phù hợp chuỗi disk full → backend kẹt → 502/504; thiếu processlist chi tiết nên không khẳng định toàn bộ 49 process chờ cùng nguyên nhân.

**Giả thuyết loại trừ.** RAM available ~22GB và CPU idle 94,9% không hỗ trợ RAM/CPU cạn ở snapshot. Socket PHP còn LISTEN nên không phải socket mất. IP bot nổi bật chỉ xuất hiện từ 01:41:03, sau lỗi đầu, có thể làm nặng thêm nhưng không là trigger trong dữ liệu. Không có bằng chứng MySQL crash hoặc dữ liệu bị hỏng; cần kiểm tra bổ sung, không tuyên bố tuyệt đối.

**Khắc phục đề xuất, chưa thực thi.** Thu thập `df -hT`, `df -i`, `lsof +L1`, processlist; tạm dừng đúng lịch backup và giảm tải phù hợp tại LB. Mở rộng filesystem hoặc archive nguyên vẹn bản backup dở sang volume khác đã xác minh, đối chiếu byte/hash trước khi bỏ bản trùng cục bộ; giữ bản backup thành công, /home và /var/lib/mysql. Sửa `dailly` thành `daily`, chạy `logrotate --debug /etc/logrotate.conf`, rotate khi đủ chỗ; xác nhận reopen và archive log đã đóng. Theo dõi MySQL retry, chỉ reload PHP nếu vẫn kẹt sau khi DB khỏe; kiểm tra website qua LB. Không có timestamp khôi phục nên không tính MTTR.

**Phòng ngừa.** Validation cấu hình trong CI; cảnh báo disk theo byte/%/dự báo; logrotate có maxsize và lịch kiểm tra phù hợp; backup tách filesystem, lock, preflight, partial-file lifecycle và restore test. Giám sát queue PHP, DB waiting, tỷ lệ 5xx và agent mất dữ liệu từ bên ngoài node. Giao Operations xử lý rotation, Infrastructure xử lý capacity và Monitoring kiểm chứng alert/escalation.

## 9. Kiểm chứng và nhật ký trung thực

Đã đọc toàn bộ log trong gói và dùng Python đếm access log, tổng HTTP status, nhóm hostname/phút, nearest-rank P95; đối chiếu tổng nhóm đều bằng 4.718. Phân tích có hỗ trợ AI (ChatGPT). Chưa kết nối production, chưa chạy recovery command, chưa benchmark, chưa xác minh backup restore. Người nộp bài cần tự ghi giờ bắt đầu/kết thúc thực tế, thao tác đã tự kiểm chứng và vấn đề còn mở; không biến timeline incident thành nhật ký thời gian làm bài.

Các dữ liệu cần bổ sung khi làm thật: cấu hình timestamp LB, đầy đủ processlist/locks, df -i, lịch sử alert/ack, inventory 40 site, dung lượng byte chính xác, diff cấu hình, backup validation và log sau phục hồi. Các timestamp metadata/size giữa các snapshot có độ làm tròn hoặc chênh lệch (ví dụ backup 19/10 có mtime 01:41 trong ls nhưng syslog done 01:42:11); không dùng chúng để tính tốc độ byte chính xác.

## 10. Tài liệu kỹ thuật đối chiếu

- Nginx, Controlling nginx: https://nginx.org/en/docs/control.html — reopen log với USR1 sau rotation.
- MySQL 8.0, How MySQL Handles a Full Disk: https://dev.mysql.com/doc/refman/8.0/en/full-disk.html — xử lý disk-full; đối chiếu với retry được ghi trực tiếp trong log của đề.
- logrotate upstream manual: https://github.com/logrotate/logrotate/blob/main/logrotate.8.in — debug, daily, maxsize, rotate và hành vi copytruncate.

## 11. Trích xuất bằng chứng có số dòng

Số dòng tính từ 1 trong file gốc của gói ZIP. Đây là các trích đoạn để tra cứu, không phải toàn bộ log.

### syslog

```text
37: Oct 13 17:42:30 web-hcm-07 sudo:   hieunv : TTY=pts/0 ; PWD=/home/hieunv ; USER=root ; COMMAND=/usr/bin/vim /etc/logrotate.d/nginx
43: Oct 14 00:00:02 web-hcm-07 logrotate[5199]: error: /etc/logrotate.d/nginx:3 unknown option 'dailly' -- ignoring line
67: Oct 15 00:00:02 web-hcm-07 logrotate[7122]: error: /etc/logrotate.d/nginx:3 unknown option 'dailly' -- ignoring line
85: Oct 16 00:00:02 web-hcm-07 logrotate[8536]: error: /etc/logrotate.d/nginx:3 unknown option 'dailly' -- ignoring line
105: Oct 17 00:00:02 web-hcm-07 logrotate[10880]: error: /etc/logrotate.d/nginx:3 unknown option 'dailly' -- ignoring line
125: Oct 18 00:00:02 web-hcm-07 logrotate[12924]: error: /etc/logrotate.d/nginx:3 unknown option 'dailly' -- ignoring line
145: Oct 19 00:00:02 web-hcm-07 logrotate[14251]: error: /etc/logrotate.d/nginx:3 unknown option 'dailly' -- ignoring line
149: Oct 19 00:30:02 web-hcm-07 disk-check: WARN / usage 82%
165: Oct 20 00:00:02 web-hcm-07 logrotate[16013]: error: /etc/logrotate.d/nginx:3 unknown option 'dailly' -- ignoring line
169: Oct 20 00:30:02 web-hcm-07 disk-check: WARN / usage 87%
173: Oct 20 01:32:57 web-hcm-07 backup-sites: tar: /var/backups/sites-20261020.tar.gz: Wrote only 4096 of 10240 bytes
175: Oct 20 01:32:58 web-hcm-07 backup-sites: ERROR backup failed exit=2, keep old backups
177: Oct 20 01:34:40 web-hcm-07 zabbix_agentd[731]: item [vfs.fs.size[/,pfree]] became not supported: Cannot write to log file
183: Oct 20 02:21:11 web-hcm-07 sshd[17146]: Accepted publickey for oncall from 10.20.1.22 port 40118 ssh2: ED25519 SHA256:Lx0c...
```

### nginx/error.log

```text
2: 2026/10/20 01:32:59 [crit] 2104#0: *5532190 pwrite() "/var/lib/nginx/body/0000183421" failed (28: No space left on device), client: 113.161.40.12, server: shop.anhduongfood.vn, request: "POST /wp-admin/admin-ajax.php HTTP/1.1", host: "shop.anhduongfood.vn"
3: 2026/10/20 01:33:01 [alert] 2112#0: 2104#0: *5532201 write() to "/var/log/nginx/access.log" failed (28: No space left on device) while logging request
4: 2026/10/20 01:33:16 [error] 2105#0: *5209440 connect() to unix:/run/php/php8.1-fpm.sock failed (11: Resource temporarily unavailable) while connecting to upstream, client: 14.218.58.164, server: site42.vn, request: "GET /tin-tuc/ HTTP/1.1", upstream: "fastcgi://unix:/run/php/php8.1-fpm.sock:", host: "site42.vn"
5: 2026/10/20 01:33:59 [error] 2110#0: *7422208 upstream timed out (110: Connection timed out) while reading response header from upstream, client: 171.146.250.51, server: shop.anhduongfood.vn, request: "GET / HTTP/1.1", upstream: "fastcgi://unix:/run/php/php8.1-fpm.sock:", host: "shop.anhduongfood.vn"
```

### mysql/error.log

```text
2: 2026-10-20T01:33:04.118842+07:00 14 [ERROR] [MY-000035] [Server] Disk is full writing './binlog.000187' (OS errno 28 - No space left on device). Waiting for someone to free space... Retry in 60 secs. Further messages will be issued every 10 minutes.
```

### php/php8.1-fpm.log

```text
2: [20-Oct-2026 01:33:06] WARNING: [pool www] child 90311 said into stderr: "PHP Warning:  session_start(): open(/var/lib/php/sessions/sess_9f2c1d, O_RDWR) failed: No space left on device (28) in /home/site42/public_html/wp-includes/class-wp-session.php on line 112"
3: [20-Oct-2026 01:34:02] WARNING: [pool www] server reached pm.max_children setting (50), consider raising it
```

### snapshot/df-h.txt

```text
6: /dev/sda2       118G  118G     0 100% /
```

### snapshot/free-m.txt

```text
3: Mem:           31994        9182         611         402       22201       22053
```
