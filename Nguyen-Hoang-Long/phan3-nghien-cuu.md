# Phần 3 — Đề B: giới hạn bot trên shared hosting

**Khuyến nghị:** kết hợp L4 ở biên mạng để giảm flood và L7 tại điểm kết thúc TLS để kiểm soát HTTP theo tenant. Với bot crawl làm PHP/DB chậm, chọn L7 làm lớp điều khiển chính; L4 bảo vệ bổ sung. Đánh giá dưới đây dựa trên tài liệu chính thức, không có benchmark tự thực hiện.

| Tiêu chí | nftables L4 | Nginx limit_req L7 |
|---|---|---|
| Đối tượng đếm | Packet, byte, kết nối; không tương đương số HTTP request | Request theo key cấu hình, ví dụ tenant + IP |
| Ngữ cảnh | IP, port, trạng thái kết nối; không đọc được URI/Host trong HTTPS thông thường | URI, virtual host, IP thực sau TLS termination |
| Cơ chế | Token bucket; dynamic set/meter cho từng nguồn [1][2] | Leaky bucket, rate/burst; có delay hoặc nodelay [3] |
| HTTP/2, keep-alive | Ít kết nối vẫn có thể chứa nhiều request | Giới hạn request, phù hợp crawl trên kết nối tái sử dụng |
| Chi phí/ảnh hưởng | Lọc sớm ở kernel, nhưng conntrack/set cũng dùng tài nguyên | Đã chịu chi phí TCP/TLS; có thể chặn trước upstream PHP |
| Phản hồi | Drop/reject kết nối; khách không nhận được lý do HTTP rõ ràng | Cấu hình HTTP 429, đo được số request bị giới hạn |
| Rủi ro | NAT/LB làm nhiều khách chung IP; rule không có meter có thể thành giới hạn chung | Sai real-IP gom toàn bộ khách vào IP LB; threshold quá thấp chặn người thật |

**Triển khai đề xuất.** Đặt nftables ở điểm còn nhìn thấy nguồn thật; không áp per-client L4 tại backend nếu nguồn đều là LB. Dùng meter riêng cho IPv4/IPv6, timeout và giới hạn kích thước set; giữ đường quản trị và health-check. Không thể bảo vệ đường uplink đã bão hòa chỉ bằng firewall trên máy đích: khi đó cần nhà mạng/upstream scrubbing.

Tại Nginx/LB kết thúc TLS, key kết hợp tenant được xác định từ cấu hình virtual host và IP client đáng tin cậy. Chỉ trust đúng proxy với `set_real_ip_from`; không trust 0.0.0.0/0 hay header do client gửi trực tiếp [4]. Tách giới hạn theo tenant và endpoint tốn tài nguyên; tránh một zone chung làm khách này ảnh hưởng khách khác. Nginx hỗ trợ áp đồng thời nhiều limit_req; chú ý quy tắc kế thừa khi cấu hình location [3].

Ngưỡng lab ban đầu có thể là 5 request/giây/IP/tenant, burst=10 và trả 429; đây là giả định để hiệu chỉnh, **không phải benchmark hay ngưỡng production đã chứng minh**. Chạy dry-run trước, đo 429 dự kiến, 5xx, P95, CPU, queue PHP và ảnh hưởng NAT; sau đó rollout canary một tenant, tăng dần và chuẩn bị rollback. Không miễn trừ bot chỉ dựa User-Agent. Trong log bài 1, IP nổi bật tạo 1.259 request sau khi disk đã đầy: rate-limit có thể giảm tải, không sửa được nguyên nhân ENOSPC.

**Đánh đổi:** L4 không phân biệt được các request tốn tài nguyên trong HTTPS; L7 cung cấp ngữ cảnh tốt hơn nhưng phải trả chi phí xử lý đầu vào. Cần bổ sung cache có kiểm soát (không cache dữ liệu cá nhân), quota tài nguyên tenant, rotation và cảnh báo disk. Theo dõi limiter log để tránh chính log giới hạn tạo áp lực đĩa.

**Nguồn chính thức, truy cập 29/10/2026:**

1. Netfilter, nftables manual — limit/token bucket: https://www.netfilter.org/projects/nftables/manpage.html
2. nftables wiki, Meters — stateful rate limit theo nguồn: https://wiki.nftables.org/wiki-nftables/index.php/Meters
3. Nginx, ngx_http_limit_req_module — rate/burst, dry-run, inheritance và status: https://nginx.org/en/docs/http/ngx_http_limit_req_module.html
4. Nginx, ngx_http_realip_module — trusted proxy: https://nginx.org/en/docs/http/ngx_http_realip_module.html
