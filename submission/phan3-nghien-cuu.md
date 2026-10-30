# Phần 3 (Đề B): chặn/rate-limit bot crawl, nftables (L4) so với Nginx `limit_req` (L7)

## 1. So sánh

| Tiêu chí | L4: nftables | L7: Nginx `limit_req` |
|---|---|---|
| Thấy gì | IP, cổng, trạng thái TCP/conntrack; **không** thấy Host/URI/User-Agent | Host, URI, header, cookie, vhost; mọi biến của nginx dùng làm key |
| Cơ chế | meter/set động: `update @set { ip saddr limit rate ... }`, có `timeout`; `ct count` đếm kết nối đang mở [1] | leaky bucket theo key, có `burst`/`nodelay`/`delay` [2] |
| Chi phí | xử lý trong kernel, trước khi tới nginx (chưa có benchmark lab, xem mục 4) | sau khi nhận kết nối và parse HTTP; mỗi trạng thái 64 hoặc 128 byte, 1 MB giữ ~8 nghìn trạng thái 128 byte, hết chỗ thì xóa trạng thái dùng lâu nhất [2] |
| Chặn bot crawl | tốt với flood, quét cổng, mở nhiều kết nối; **không** phân biệt trang nặng hay nhẹ | tốt với crawl sâu trang động (như `/tin-tuc/page/849/`), tách theo vhost/đường dẫn/UA |
| Shared hosting nhiều site | một luật cho cả máy, khó công bằng giữa các khách | key `$server_name` chặn "hàng xóm ồn" riêng từng vhost [2] |
| IP thật sau LB/CDN | thấy IP của LB nếu LB là proxy; chỉ dùng được đặt **trên chính LB/edge** | `set_real_ip_from` (chỉ tin LB) + `real_ip_header X-Forwarded-For`/`proxy_protocol` + `real_ip_recursive` [3] |
| Dương tính giả | cao hơn với NAT/văn phòng/CGNAT vì chặn cả IP, mất cả mọi site | thấp hơn nếu key chọn tốt, trả 429 có thể phục hồi ngay; vẫn dính NAT khi key là IP |
| Vận hành | luật toàn cục, đổi cần quyền root, dễ tự khóa mình | thử an toàn bằng `limit_req_dry_run` (1.17.1+) và biến `$limit_req_status` [2] |

## 2. Khuyến nghị: phòng thủ nhiều lớp

`Internet → LB/edge (nftables L4) → Nginx L7 trên web node → PHP-FPM → MySQL`

- **Lớp L4 trên LB/edge (thô, rộng):** chỉ chặn hành vi rõ ràng là tấn công: tốc độ mở kết nối mới theo IP, quá nhiều kết nối đồng thời, IP lên danh sách chặn có `timeout` tự hết hạn, có allowlist cho IP nội bộ/giám sát. Ngưỡng cao, mục tiêu là bảo vệ hạ tầng chứ không phải điều tiết crawler.
- **Lớp L7 trên web node (mịn, theo ngữ cảnh):** đây là lớp xử lý bot crawl. Giới hạn mỗi IP, gom nhóm crawler đã biết (qua UA) vào một bucket/vhost, và chặn tổng theo vhost. Lý do: điểm nghẽn trong sự cố `web-hcm-07` là PHP-FPM (`pm.max_children=50`), và chặn ở nginx giúp request không bao giờ chạm tới PHP-FPM.
- **Bắt buộc:** nginx phải khôi phục IP thật từ LB, nếu không mọi request trông như đến từ một IP (IP của LB) và `perip` sẽ chặn nhầm cả site. Chỉ liệt kê IP của LB trong `set_real_ip_from`.
- **Triển khai theo pha:** `limit_req_dry_run on` ít nhất 1 tuần, đọc `$limit_req_status` trong access log, hiệu chỉnh rồi mới bật thật với `limit_req_status 429`. Verify Googlebot/Bingbot bằng reverse DNS rồi đưa vào allowlist (UA là thứ giả được: trong log sự cố IP `45.135.232.17` mang UA AhrefsBot nhưng cũng bị UFW chặn khi dò cổng 3306, `phan1-su-co/syslog:179`).

Cấu hình minh họa Nginx (`nginx -t` báo hợp lệ trên nginx 1.24.0):

```nginx
# /etc/nginx/conf.d/ratelimit.conf  (context: http)

# 1) Chỉ tin X-Forwarded-For khi request đến từ LB (IP LB: ví dụ, thay bằng IP thật)
set_real_ip_from  10.20.1.0/24;
real_ip_header    X-Forwarded-For;
real_ip_recursive on;

# 2) Crawler đã biết (theo User-Agent) dùng CHUNG một bucket cho mỗi vhost;
#    khách thường có key rỗng nên không bị đếm (xem tài liệu limit_req_zone).
#    User-Agent giả mạo được: chỉ là lớp giảm tải, không phải xác thực bot.
map $http_user_agent $crawler_key {
    default "";
    ~*(ahrefsbot|semrushbot|mj12bot|dotbot|petalbot|bytespider) $server_name;
}

# 3) Ba vùng nhớ (giá trị khởi điểm, cần hiệu chỉnh theo traffic baseline)
limit_req_zone $binary_remote_addr zone=perip:20m    rate=10r/s;   # mỗi IP
limit_req_zone $crawler_key        zone=crawler:1m   rate=1r/s;    # cả nhóm bot trên 1 vhost
limit_req_zone $server_name        zone=pervhost:1m  rate=100r/s;  # chặn "hàng xóm ồn" giữa các site

limit_req_status    429;
limit_req_log_level warn;
limit_req_dry_run   on;     # tuần đầu: chỉ ghi nhận ($limit_req_status = *_DRY_RUN), đổi thành off khi đã hiệu chỉnh

log_format rl '$remote_addr $host "$request" $status $limit_req_status rt=$request_time';

server {
    listen 80 default_server;
    server_name _;
    access_log /var/log/nginx/access.log rl;
    limit_req zone=perip    burst=20 nodelay;
    limit_req zone=crawler  burst=5;
    limit_req zone=pervhost burst=200 nodelay;
    # location / { ... fastcgi_pass ... }
}
```

Cấu hình minh họa nftables cho LB/edge (`nft -c -f` báo hợp lệ trên nftables 1.0.9; cú pháp theo [1]):

```
table inet bot_guard {
    set allow4   { type ipv4_addr; flags interval; elements = { 10.0.0.0/8 } }
    set blocked4 { type ipv4_addr; flags timeout; timeout 10m; size 65536; }
    set meter4   { type ipv4_addr; flags dynamic, timeout; timeout 1m; size 65536; }
    set conn4    { type ipv4_addr; flags dynamic; size 65536; }

    chain input {
        type filter hook input priority filter; policy accept;
        ip saddr @allow4 accept
        ip saddr @blocked4 counter drop
        tcp dport { 80, 443 } ct state new update @meter4 { ip saddr limit rate over 60/second burst 120 packets } add @blocked4 { ip saddr } counter drop
        tcp dport { 80, 443 } ct state new add @conn4 { ip saddr ct count over 200 } counter drop
    }
}
```

## 3. Đánh đổi và rủi ro

- **Ngưỡng chỉ là giá trị khởi điểm.** Không có traffic baseline thì chưa thể khẳng định phù hợp production; sai ngưỡng sẽ chặn khách thật, đặc biệt khi nhiều người dùng chung một IP NAT.
- **UA giả mạo được:** `$crawler_key` chỉ giảm tải từ crawler "lịch sự"; bot ác ý đổi UA sẽ lọt qua và chỉ bị `perip` giữ lại.
- **`burst` không `nodelay` làm trễ request** (không bị từ chối): kiểm tra thực tế ở mục 4 cho thấy mỗi request crawler bị giữ ~1 giây, nên chiếm một kết nối nginx trong lúc chờ.
- **L4 có thể tự khóa mình:** chặn IP của LB hay giám sát sẽ làm sập mọi site; luôn có allowlist, `timeout` ngắn, và `nft -c` trước khi nạp.
- **Giới hạn bộ nhớ:** `perip:20m` giữ cỡ 160 nghìn IP (8 nghìn trạng thái/MB [2]); tấn công từ nhiều IP hơn sẽ đẩy trạng thái cũ ra, nên cần thêm lớp L4 và cache trang động.

## 4. Kiểm chứng đã làm và chưa làm

Đã chạy trên lab của mình (nginx 1.24.0, Ubuntu 24.04, sandbox, **không phải máy chủ hosting thật**): 60 request liên tiếp từ một IP → 24 trả 200, 36 trả 429; với UA AhrefsBot 15 request → tất cả 200 nhưng bị `DELAYED` (~1 s mỗi request); với `limit_req_dry_run on` → 60 request đều 200, trong đó 36 ghi `REJECTED_DRY_RUN`. Lưu ý một lỗi dễ gặp khi tự test: `return 200` được xử lý ở pha rewrite, **trước** `limit_req`, nên không bị giới hạn (lần test đầu của mình đã dính lỗi này). Nftables chỉ mới kiểm tra cú pháp (`nft -c`), **chưa** nạp luật hay thử tải thật. **Chưa có benchmark** về CPU/độ trễ của hai lớp, nên bài không đưa con số hiệu năng nào.

## Tài liệu tham khảo (đã mở và đọc ngày 29/10/2026)

1. nftables wiki, *Meters*: https://wiki.nftables.org/wiki-nftables/index.php/Meters (mục chính: https://wiki.nftables.org/)
2. nginx, *ngx_http_limit_req_module*: https://nginx.org/en/docs/http/ngx_http_limit_req_module.html
3. nginx, *ngx_http_realip_module*: https://nginx.org/en/docs/http/ngx_http_realip_module.html
