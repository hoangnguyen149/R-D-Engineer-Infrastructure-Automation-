# Postmortem: 502/504 hàng loạt trên `web-hcm-07` ngày 20/10/2026

Quy ước: **[F]** = sự kiện quan sát được từ dữ liệu; **[I]** = suy luận; **[U]** = chưa biết / chưa đủ dữ liệu. Bằng chứng ghi dạng `file:dòng` (đường dẫn tính từ `phan1-su-co/`). Giờ theo +07.

## 1. Tóm tắt sự cố

Từ **01:33** ngày 20/10, các website trên `web-hcm-07` trả 502/504 hàng loạt (2.775/4.718 request trong log LB, 58,8%; tới khoảng 01:40–01:50 là 93%). Phạm vi ảnh hưởng là mọi site chạy PHP trên máy, trong khi file tĩnh vẫn trả 200. **Nguyên nhân gốc:** phân vùng `/` đầy 100%. Từ 14/10, logrotate của nginx bị lỗi cú pháp (`dailly`) nên `access.log` không còn được xoay vòng và phình tới 37G. Cron backup 01:00 ghi thêm ~16G vào cùng phân vùng và làm đầy nốt chỗ trống. MySQL bị treo khi ghi binlog, các worker PHP-FPM bị giữ lại chờ DB cho tới khi hết `pm.max_children`, nginx không còn worker để giao việc. Đây không phải sự cố CPU, RAM hay bot, và không cần reboot.

## 2. Timeline

| Thời điểm | Sự kiện | Bằng chứng |
|---|---|---|
| 12/10 | Baseline khỏe: `/` 55%, backup 17,0G chạy 01:00–01:40 | `syslog:4`, `syslog:9` |
| 13/10 00:00 | logrotate chạy bình thường, không lỗi | `syslog:22-23` |
| **13/10 17:42** | User `hieunv` sửa `/etc/logrotate.d/nginx` bằng vim, 17:44 reload nginx | `syslog:37-38` |
| **14/10 00:00** | Lần đầu logrotate báo lỗi, bỏ qua toàn bộ `/var/log/nginx/*.log`; lặp lại mỗi đêm tới 20/10 | `syslog:43-44`, `snapshot/logrotate-nginx.conf:3` |
| 14–20/10 | Disk tăng đều ~5%/ngày: 57% → 62 → 67 → 72 → 77 → **82 (WARN)** → **87 (WARN)** | `syslog:48,71,89,109,129,149,169` |
| 20/10 00:30 | `disk-check.sh` ghi `WARN / usage 87%` vào syslog, không thấy cảnh báo nào được gửi đi | `syslog:169` |
| 20/10 01:00 | Cron backup bắt đầu ghi `/var/backups/sites-20261020.tar.gz` | `syslog:170-171` |
| 01:00–01:32 | LB vẫn bình thường: toàn 2xx, `rt` tối đa 0,349s | `lb/access-lb-hcm-01.log` (tính trên các dòng 1–1565) |
| **01:32:57** | `tar` ngừng vì hết chỗ ghi; backup lỗi, file dở 16G bị bỏ lại | `syslog:173-175`, `snapshot/du-var.txt:18` |
| 01:32:59 – 01:33:01 | nginx không ghi được body tạm và `access.log` | `nginx/error.log:2-3` |
| **01:33:04** | MySQL: `Disk is full writing './binlog.000187' ... Waiting for someone to free space` | `mysql/error.log:2`, `syslog:176` |
| 01:33:05 | Request 504 đầu tiên tại LB (`rt=60.587`) | `lb/access-lb-hcm-01.log:1569` |
| 01:33:06 | PHP: `session_start() ... No space left on device` | `php/php8.1-fpm.log:2` |
| 01:33:16 | nginx: `connect() to unix:/run/php/php8.1-fpm.sock failed (11: Resource temporarily unavailable)` | `nginx/error.log:4` |
| 01:34:02 | `server reached pm.max_children setting (50)`, xuất hiện 40 lần tới 01:58 | `php/php8.1-fpm.log:3` |
| 01:34:40 | Zabbix: `vfs.fs.size[/,pfree] became not supported: Cannot write to log file` | `syslog:177` |
| 01:41:03 | IP `45.135.232.17` (UA AhrefsBot) bắt đầu crawl `/tin-tuc/page/849/`, toàn nhận 5xx | `lb/access-lb-hcm-01.log:1863` |
| 02:21 / 02:23 | On-call vào máy; snapshot: `/` 100%, avail 0 | `syslog:183`, `snapshot/df-h.txt:6` |

## 3. Nguyên nhân gốc và chuỗi hệ quả

`Sửa config sai (13/10) → access.log không xoay → đĩa đầy dần → backup ghi nốt chỗ cuối → ENOSPC → MySQL treo → PHP-FPM cạn worker → nginx 502/504 → khách thấy lỗi`

1. **Khởi phát [F]:** `/etc/logrotate.d/nginx` dòng 3 là `dailly`; syslog báo `unknown option 'dailly' -- ignoring line` và `found error in /var/log/nginx/*.log , skipping` (`syslog:43-44`). Lần đổi file duy nhất trong log là ở `syslog:37`, và đêm 13/10 chưa có lỗi (`syslog:22-23`). **[I]** lần sửa này đưa ra lỗi gõ sai; lỗi cũng làm `error.log` không được xoay.
2. **Tích lũy [F]:** `access.log` 37G, lần xoay cuối là `access.log.1` ngày 13/10 (`snapshot/du-var.txt:10-12`); `/var/log` chiếm 38G. **[I]** ~37G trong ~6,1 ngày ≈ 6 GB/ngày, khớp mức tăng 5%/ngày của đĩa 118G (≈5,9 GB/ngày); trước 13/10 đĩa chỉ tăng ~1%/ngày (`syslog:4,25,48`).
3. **Điểm đứt [F]:** backup `tar` ghi tới 16G thì ENOSPC (`snapshot/du-var.txt:18`, `syslog:173`). Script chỉ xóa bản cũ khi bản mới thành công và không kiểm tra dung lượng trống (`snapshot/backup-sites.sh:8,11`), nên lúc chạy phải giữ cùng lúc hai bản ~19G trên cùng phân vùng với `/home` và log. **[I]** lúc 00:30 còn ~15G trống (118G × 13%), thấp hơn 19G backup cần, nên lỗi này chắc chắn xảy ra.
4. **Làm treo DB [F]:** MySQL kẹt ở `binlog.000187` và thử lại mỗi 60 giây (`mysql/error.log:2-7`); lúc 02:23 vẫn còn 49 tiến trình `Waiting for` (`snapshot/ss-summary.txt:13-14`). **[I]** mọi truy vấn ghi (WordPress ghi option/session liên tục) bị chặn chờ binlog; `mysqli_real_connect(): Error while reading greeting packet` xuất hiện từ `php/php8.1-fpm.log:4`.
5. **Cạn worker [F]:** PHP không ghi được session (`php:2`), `pm.max_children (50)` bị chạm (`php:3`) và socket trả `Resource temporarily unavailable` (`nginx/error.log:4`).
6. **Triệu chứng HTTP [F]:** trong log LB có 1.231 lần 502 với `rt` ≤ 0,01s (khớp `connect()` bị từ chối ngay) và 1.544 lần 504 với `rt` 60,0–61,0s (khớp `upstream timed out`, `nginx/error.log:5`). **[I]** 60s là mặc định `fastcgi_read_timeout` của nginx, nhưng file cấu hình nginx/php-fpm không có trong snapshot **[U]**. File tĩnh vẫn được phục vụ: 207/363 response 2xx sau 01:34 là `banner.jpg`, nên nginx vẫn sống.
7. **Giám sát mù [F]:** `disk-check.sh` chỉ ghi WARN vào syslog (82% rồi 87%), còn Zabbix mất item đĩa đúng lúc đĩa đầy (`syslog:149,169,177`). **[U]** nội dung `disk-check.sh` và trigger Zabbix không có trong snapshot.

**Điểm chưa giải thích [U]:** dòng 504 đầu tiên ở LB (`rt=60.587`, 01:33:05) nếu tính thời điểm bắt đầu request thì trước giờ `tar` báo lỗi (01:32:57) khoảng 1 phút. Có thể do định nghĩa mốc thời gian của LB hoặc lệch đồng hồ; chênh lệch này không làm đổi kết luận.

## 4. Giả thuyết đã xét

| Giả thuyết | Kết luận | Bằng chứng |
|---|---|---|
| CPU/load cao | **Loại trừ** | load 1,84; CPU idle 94,9%, wa 0,6% (`snapshot/uptime-top.txt:2,7`) |
| Thiếu RAM / OOM | **Loại trừ** | available 22.053 MiB, swap dùng 12 MiB (`snapshot/free-m.txt:3-4`); không có OOM trong `syslog` hay `dmesg-tail.txt` (`free` 611 MiB chỉ là page cache) |
| nginx chết / restart | **Loại trừ** | không có restart trong syslog; nginx vẫn ghi lỗi và phục vụ file tĩnh |
| Bot AhrefsBot (`45.135.232.17`) gây quá tải | **Loại trừ là nguyên nhân gốc, có thể làm nặng thêm** | lưu lượng ổn định ~350 req/10 phút tới 01:32; IP này mới xuất hiện lúc 01:41:03, sau khi lỗi bắt đầu 8 phút (`lb:1863`); 1.259 request của nó đều là 5xx (45% tổng 5xx). Cùng IP bị UFW chặn khi dò cổng 3306 (`syslog:179`) |
| Backup làm chậm site (I/O, CPU) | **Loại trừ** | trong 01:00–01:32 `rt` tối đa 0,349s; backup chỉ là điểm kích hoạt khi hết chỗ |
| Load balancer lỗi | **Loại trừ ở mức khá chắc** | trước 01:33 bình thường; lỗi khớp từng dòng với log nginx/php/mysql của máy. Chỉ có upstream `web-hcm-07` trong log **[U]** |
| `wp-cron` site42 | **Loại trừ** | lần chạy cuối 19/10 19:59, không chạy trong khung sự cố (`syslog:163`) |
| MySQL hết `max_connections` | **Not confirmed** | `mysql/error.log` không có lỗi "Too many connections"; `max_connections` không có trong snapshot |
| Hết inode | **Not confirmed** | không có `df -i`; lỗi là `errno 28` do hết block |
| Hết file descriptor | **Not confirmed** | không có "too many open files"; `ss -s` chỉ có 2.391 socket, estab 412 (`snapshot/ss-summary.txt:2-3`) |

## 5. Khắc phục tức thời (02:23)

Không đụng `/home`, `/var/lib/mysql` hay `/var/lib/php/sessions`. Không restart MySQL; không reboot. Mọi bước ghi lại vào ticket.

**Bước 0: kiểm tra chỉ đọc.**
```bash
df -h /; df -i /
ls -lh /var/backups/ /var/log/nginx/
pgrep -af 'backup-sites|tar -czf'       # đảm bảo không còn tar đang chạy
mysqladmin processlist | grep -c 'Waiting for'
```

**Bước 1: lấy lại ~16G bằng cách xóa file backup dở** (`/var/backups/sites-20261020.tar.gz` là file sinh tự động, lỗi theo `syslog:173-175`, không phải dữ liệu khách). Giữ bản tốt `sites-20261019.tar.gz`.
```bash
lsof /var/backups/sites-20261020.tar.gz   # không có tiến trình nào đang mở
rm -- /var/backups/sites-20261020.tar.gz
df -h /                                    # kỳ vọng còn trống ~16G
```
*Tác động:* chỉ mất bản backup hỏng. *Rollback:* không cần; chạy lại backup sau khi dung lượng ổn.

**Bước 2: sửa logrotate và xoay log nginx.**
```bash
cp -a /etc/logrotate.d/nginx /root/nginx.logrotate.bak
sed -i 's/^\tdailly$/\tdaily/' /etc/logrotate.d/nginx
logrotate -d /etc/logrotate.d/nginx        # dry-run, phải không còn error
logrotate -f /etc/logrotate.d/nginx        # nginx reopen log qua postrotate, không downtime
ionice -c3 nice -n19 gzip -1 /var/log/nginx/access.log.1   # ~37G text, kỳ vọng còn vài GB
df -h /
```
*Lưu ý:* nén thay vì xóa, vì access log là dữ liệu có giá trị tra cứu. Sau đó đẩy bản `.gz` sang log tập trung. *Rollback:* `cp -a /root/nginx.logrotate.bak /etc/logrotate.d/nginx`.

**Bước 3: để MySQL tự phục hồi.** MySQL thử lại mỗi 60s (`mysql/error.log:2`), không cần restart. Theo dõi:
```bash
journalctl -u mysql -f      # hoặc tail -f /var/log/mysql/error.log
watch -n5 'mysqladmin processlist | grep -c "Waiting for"'
```
Nếu sau 5 phút vẫn kẹt: **escalate cho DBA**; không `PURGE BINARY LOGS` hay thao tác dữ liệu khi chưa có xác nhận (binlog có thể phục vụ replication/PITR).

**Bước 4: PHP-FPM.** Worker sẽ tự nhả khi DB phản hồi. Chỉ khi sau MySQL hồi phục ~2 phút mà log vẫn báo `max_children` thì reload mềm:
```bash
php-fpm8.1 -t && systemctl reload php8.1-fpm
```

**Bước 5: xác minh.**
```bash
for h in site42.vn tintuc24h.net shop.anhduongfood.vn; do
  curl -s -o /dev/null -w "$h %{http_code} %{time_total}s\n" -H "Host: $h" http://127.0.0.1/
done
tail -f /var/log/nginx/error.log            # không còn dòng mới
df -h /                                      # mục tiêu < 70%
```
Đối chiếu tỷ lệ 5xx trên LB về mức nền (~0 so với 4–7 request 404 mỗi 10 phút lúc bình thường). *Tùy chọn sau hồi phục:* chặn `45.135.232.17` ở LB hoặc `ufw deny from 45.135.232.17` (đã thấy IP này dò cổng, `syslog:179`). Ngoài ra chạy lại backup bằng tay sau khi đủ chỗ trống.

## 6. Phòng ngừa

Các ngưỡng dưới đây là **giá trị khởi điểm**, cần hiệu chỉnh theo baseline.

| Lớp | Đề xuất | Căn cứ |
|---|---|---|
| Change management | Lint/validate trước khi áp config (`logrotate -d`, `nginx -t`), quản lý `/etc` bằng Git/Ansible và có review | lỗi gõ sai tồn tại 6 ngày |
| Giám sát logrotate | Alert khi syslog có `logrotate.*error`; alert nếu `access.log` lớn hơn 2G hoặc mtime lần xoay > 36h | `syslog:43-44` lặp mỗi đêm |
| Cảnh báo đĩa | Gửi cảnh báo thật (Alertmanager/Zabbix) khi `/` > 70% (warning), > 80% (critical); thêm `predict_linear(node_filesystem_avail_bytes{mountpoint="/"}[6h], 24*3600) < 0` | dữ liệu 72% (17/10) cho thấy cảnh báo 70% đã báo sớm ~3 ngày |
| Cảnh báo Zabbix | Trigger "item unsupported" và "no data"; ship log về hệ thống tập trung | `syslog:177` |
| Backup | Sang volume/ổ riêng hoặc đẩy ra ngoài máy; kiểm tra dung lượng trống ≥ 1,3× bản trước; ghi file `.tmp` rồi `mv` khi thành công; dùng `trap` dọn file dở; `ionice`/`nice`; thêm backup DB riêng | `backup-sites.sh:8,11` |
| Cấu hình | `logrotate` thêm `maxsize 1G`; tách `/var/log`, `/var/backups`, `/var/lib/mysql` thành phân vùng riêng; giữ ~5% reserved blocks; đặt một file ballast 2–5G để xóa nhanh khi đầy đĩa | nhiều dịch vụ dùng chung `/` |
| MySQL | Đặt `binlog_expire_logs_seconds`, theo dõi dung lượng datadir | `mysql/error.log:2` |
| PHP-FPM/nginx | Bật `pm.status_path`, alert khi `listen queue` > 0 kéo dài và khi log có `max_children`; đặt `request_terminate_timeout` cho khớp `fastcgi_read_timeout`. **Không chỉ nâng `max_children`** vì chỉ làm nhiều worker kẹt hơn | `php:3` |
| Alert tầng HTTP | Cảnh báo khi tỷ lệ 5xx trên LB > 5% trong 2 phút | sự cố kéo dài ~50 phút trước khi on-call vào |
| Bot | Rate-limit tại Nginx/nftables (xem `phan3-nghien-cuu.md`) | IP crawl sâu `/tin-tuc/page/849/` |
| Vận hành | Runbook "disk full" và diễn tập định kỳ; rà soát các `*.sh` cron có ghi vào `/` | |
