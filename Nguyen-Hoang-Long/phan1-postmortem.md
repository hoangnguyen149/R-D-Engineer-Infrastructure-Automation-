# Phần 1 — Postmortem web-hcm-07

Tác giả: Nguyễn Hoàng Long. Múi giờ UTC+7. Phân tích offline, chưa thực thi trên production.

**Executive Summary.** Ngày 20/10/2026, node hosting web-hcm-07 gặp 502/504 diện rộng; LB ghi lỗi đầu tiên lúc 01:33:05 và vẫn còn lỗi lúc 02:25:01. Trong bộ log có 2.775/4.718 request lỗi, thuộc 5 hostname; khoảng 40 website là phạm vi tiềm năng theo đề. Nguyên nhân gốc là cấu hình logrotate sai `dailly`, làm log tích tụ; backup ghi cùng root là tác nhân đẩy disk tới 100%. Hệ quả là MySQL không ghi được binlog, PHP bị nghẽn và Nginx không phục vụ được upstream; chưa có dữ liệu xác nhận khôi phục.

**Timeline.** 13/10 17:42 sửa cấu hình logrotate; 14–20/10 logrotate skip Nginx. Disk tăng từ 57% ngày 14 lên 82% ngày 19 và 87% ngày 20 lúc 00:30. Backup bắt đầu 01:00:02, thất bại 01:32:57–58; Nginx ENOSPC 01:32:59, MySQL disk full 01:33:04, PHP session ENOSPC 01:33:06 và max_children=50 lúc 01:34:02. On-call vào máy 02:21:11; snapshot 02:23 xác nhận root 100%.

**Nguyên nhân và bằng chứng.** syslog ghi `unknown option 'dailly'` và `skipping`, trùng cấu hình trong snapshot. du-var ghi access.log 37G, backup 19G + 16G. backup-sites.sh tạo bản mới trong /var/backups trước khi xóa bản hôm qua, không preflight dung lượng. df ghi `/dev/sda2 118G 118G 0 100% /`. MySQL ghi `Disk is full writing './binlog.000187'`; PHP chạm 50 worker; Nginx ghi timeout và errno 11 tới socket PHP. Dòng thời gian và snapshot phù hợp chuỗi disk full → backend kẹt → 502/504; thiếu processlist chi tiết nên không khẳng định toàn bộ 49 process chờ cùng nguyên nhân.

**Giả thuyết loại trừ.** RAM available ~22GB và CPU idle 94,9% không hỗ trợ RAM/CPU cạn ở snapshot. Socket PHP còn LISTEN nên không phải socket mất. IP bot nổi bật chỉ xuất hiện từ 01:41:03, sau lỗi đầu, có thể làm nặng thêm nhưng không là trigger trong dữ liệu. Không có bằng chứng MySQL crash hoặc dữ liệu bị hỏng; cần kiểm tra bổ sung, không tuyên bố tuyệt đối.

**Khắc phục đề xuất, chưa thực thi.** Thu thập `df -hT`, `df -i`, `lsof +L1`, processlist; tạm dừng đúng lịch backup và giảm tải phù hợp tại LB. Mở rộng filesystem hoặc archive nguyên vẹn bản backup dở sang volume khác đã xác minh, đối chiếu byte/hash trước khi bỏ bản trùng cục bộ; giữ bản backup thành công, /home và /var/lib/mysql. Sửa `dailly` thành `daily`, chạy `logrotate --debug /etc/logrotate.conf`, rotate khi đủ chỗ; xác nhận reopen và archive log đã đóng. Theo dõi MySQL retry, chỉ reload PHP nếu vẫn kẹt sau khi DB khỏe; kiểm tra website qua LB. Không có timestamp khôi phục nên không tính MTTR.

**Phòng ngừa.** Validation cấu hình trong CI; cảnh báo disk theo byte/%/dự báo; logrotate có maxsize và lịch kiểm tra phù hợp; backup tách filesystem, lock, preflight, partial-file lifecycle và restore test. Giám sát queue PHP, DB waiting, tỷ lệ 5xx và agent mất dữ liệu từ bên ngoài node. Giao Operations xử lý rotation, Infrastructure xử lý capacity và Monitoring kiểm chứng alert/escalation.


**Bằng chứng và runbook chi tiết:** [Phụ lục](phu-luc/huong-dan-su-co-web-hcm-07.md), có trích log theo số dòng, lệnh từng bước và thống kê từng phút. [Dữ liệu gốc](phu-luc/du-lieu-su-co/) và [script tái lập](phu-luc/thong_ke_lb.py) đi kèm.
