# Bài test Kỹ thuật: R&D Engineer (Infrastructure & Automation) - Vietnix

Chào bạn,

Cảm ơn bạn đã quan tâm và ứng tuyển vào team RnD Vietnix.

Bài test dưới đây xoay quanh chính những bài toán thực tế mà team xử lý hằng ngày: điều tra sự cố hệ thống, xây dựng công cụ tự động hóa hạ tầng, và nghiên cứu giải pháp công nghệ. Mục tiêu là giúp hai bên hiểu rõ cách tư duy kỹ thuật và phong cách làm việc của nhau.

---

## Thông tin chung

- **Thời hạn:** 72 giờ tính từ lúc nhận email (thực tế bài làm mất khoảng 4 đến 6 giờ, bạn chủ động sắp xếp thời gian phù hợp).
- **Phản hồi nhận đề:** Nhờ bạn reply email trong vòng 24 giờ để xác nhận đã nhận được đề và cho team biết mốc thời gian dự kiến nộp bài.
- **Thắc mắc & Trao đổi:** Bạn cứ thoải mái trao đổi qua email bất cứ lúc nào. Trường hợp chưa kịp nhận phản hồi từ team, bạn hãy tự đưa ra giả định hợp lý, ghi chú rõ giả định đó trong bài và tiếp tục làm.
- **Sử dụng AI & Công cụ:** Thoải mái sử dụng ChatGPT, Claude, Copilot hoặc bất kỳ công cụ nào hỗ trợ công việc. Yêu cầu duy nhất là bạn ghi chép trung thực vào nhật ký (dùng ở bước nào, công cụ gì). Khi vào vòng phỏng vấn kỹ thuật, team sẽ cùng bạn trao đổi sâu về bản chất bài làm.
- **Tiêu chí đánh giá:** Team đánh giá cao sự trung thực, mạch lạc và tư duy xử lý vấn đề hơn một bài làm cố tỏ ra hoàn hảo. Nếu hết thời gian mà chưa xong hết, bạn cứ nộp những gì đã hoàn thiện, kèm ghi chú phần còn dở dang và hướng xử lý tiếp theo nếu có thêm thời gian.
- **Hình thức nộp:** Gửi link repo GitHub/GitLab (nếu để private thì invite người gửi đề) hoặc file `.zip` đính kèm, reply trực tiếp trong thread email này.
- **Email liên hệ & nộp bài:** rnd@vietnix.vn

Cấu trúc thư mục bài nộp:

```
<ho-ten>/
  README.md            # Tổng quan, hướng dẫn chạy tool, các giả định đã đặt ra
  phan1-postmortem.md  # Báo cáo điều tra sự cố
  phan2-tool/          # Mã nguồn, unit test, README riêng (nếu cần)
  phan3-nghien-cuu.md  # Bài nghiên cứu so sánh
  phan4-nhat-ky.md     # Nhật ký làm bài theo mẫu
```

---

## Phần 1: Điều tra sự cố (Thời lượng ước tính: ~1.5 giờ)

**Bối cảnh:** máy `web-hcm-07` là một node shared hosting (Nginx + PHP-FPM 8.1 + MySQL 8) chạy khoảng 40 website của khách hàng. Rạng sáng ngày **20/10/2026** (khoảng từ 01:00), hàng loạt website trên máy này bắt đầu trả về lỗi 502/504. Đến 02:21, kỹ sư on-call SSH vào kiểm tra và lưu lại một số output hiện trạng.

Dữ liệu điều tra nằm trong thư mục `phan1-su-co/`:

| File                                                       | Nội dung                                                                                                                           |
| ---------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| `syslog`                                                   | Log hệ thống từ 12/10 đến 20/10 (đã rút gọn)                                                                                       |
| `nginx/error.log`, `php/php8.1-fpm.log`, `mysql/error.log` | Log lỗi riêng của từng service (được đẩy về hệ thống log tập trung qua syslog nên vẫn lưu vết đầy đủ trong thời gian xảy ra sự cố) |
| `lb/access-lb-hcm-01.log`                                  | Access log từ load balancer đứng trước máy `web-hcm-07`, ghi nhận trong khung giờ 00:50 đến 02:25                                  |
| `snapshot/`                                                | Output các lệnh kiểm tra on-call thực hiện lúc 02:23 cùng một số file cấu hình, script lấy trực tiếp từ máy chủ                    |

**Yêu cầu:** viết báo cáo postmortem `phan1-postmortem.md` (khoảng 1 đến 2 trang A4), gồm:

1. **Tóm tắt sự cố (Executive Summary):** 3 đến 5 câu nêu vắn tắt hiện tượng, phạm vi ảnh hưởng và kết luận nguyên nhân gốc rễ.
2. **Timeline sự cố:** các mốc thời gian đáng chú ý dẫn tới sự cố (bao gồm cả các dấu hiệu hoặc thay đổi diễn ra trước đêm 20/10 nếu có liên quan).
3. **Phân tích nguyên nhân gốc & chuỗi hệ quả:** giải thích cặn kẽ vì sao máy chủ rơi vào tình trạng 502/504. Mọi kết luận bắt buộc phải đi kèm bằng chứng cụ thể (trích dẫn chính xác dòng log, output lệnh hoặc file cấu hình).
4. **Các giả thuyết đã loại trừ:** nêu các hướng nghi vấn ban đầu và lý do/bằng chứng bạn loại bỏ các giả thuyết đó.
5. **Khắc phục tức thời:** các thao tác / câu lệnh cụ thể bạn sẽ thực hiện ngay tại thời điểm 02:23 để khôi phục dịch vụ. **Lưu ý quan trọng:** đây là máy hosting của khách hàng, tuyệt đối **không xóa hoặc chỉnh sửa dữ liệu, database, source code của khách**.
6. **Phương án phòng ngừa:** đề xuất cải tiến về giám sát, cảnh báo và cấu hình để tránh sự cố tái diễn hoặc phát hiện sớm trước khi ảnh hưởng diện rộng.

---

## Phần 2: Tool phân tích tải cluster Proxmox (Thời lượng ước tính: ~2 giờ)

**Bối cảnh:** team cần một tool chạy định kỳ để giám sát tình trạng tải của cluster Proxmox VE và đưa ra gợi ý live-migrate các VM nhằm cân bằng tài nguyên giữa các node.

File `phan2-proxmox/cluster-pve-hcm-c3.json` là snapshot xuất từ cluster `pve-hcm-c3`. Ý nghĩa các trường:

| Trường                            | Ý nghĩa                                                                    |
| --------------------------------- | -------------------------------------------------------------------------- |
| `nodes[].cpu_cores`               | Số core CPU vật lý của node                                                |
| `nodes[].mem_total`               | Tổng dung lượng RAM vật lý của node (byte)                                 |
| `nodes[].status`                  | Trạng thái node (`online` / `offline`)                                     |
| `vms[].vcpus`                     | Số vCPU cấp phát cho VM                                                    |
| `vms[].cpu_usage`                 | Tỷ lệ CPU thực dùng của VM (từ `0` đến `1` tương ứng với số vCPU được cấp) |
| `vms[].mem_max`, `vms[].mem_used` | RAM cấp phát và RAM thực tế đang dùng của VM (byte)                        |
| `vms[].status`                    | Trạng thái VM (`running`, `stopped`, ...)                                  |

**Yêu cầu:** viết tool bằng **Python, Go hoặc Bash** (tự chọn), đọc file JSON trên để:

1. Thống kê và hiển thị mức tải của từng node: CPU thực dùng, RAM thực dùng, tỷ lệ overcommit vCPU so với core vật lý.
2. Nhận diện và đánh dấu các node đang rơi vào trạng thái **quá tải**.
3. Đề xuất kế hoạch migrate: chỉ rõ VM nào cần chuyển từ node nào sang node nào, đảm bảo sau khi chuyển thì không node nào bị quá tải và node nhận VM cũng không bị đẩy vào ngưỡng quá tải.
4. Hỗ trợ 2 định dạng output:
   - Dạng bảng trực quan trên terminal (cho người đọc trực tiếp).
   - Dạng JSON chuẩn (để pipe sang các tool/script tự động hóa khác).

**Tiêu chuẩn bắt buộc:**

- Kèm file `README.md`: hướng dẫn cài đặt, cách chạy, ví dụ output thực tế và các giả định/ngưỡng đánh giá bạn đã áp dụng.
- Có test tự động (unit test) cho các phần logic cốt lõi.
- Xử lý ngoại lệ an toàn: tool không crash khi gặp file JSON lỗi hoặc thiếu trường; cần log cảnh báo rõ ràng bản ghi nào bất thường.

---

## Phần 3: Nghiên cứu ngắn (Thời lượng ước tính: ~1 giờ, chọn 1 trong 2 đề)

**Đề A:** Vietnix dự kiến dựng dịch vụ Object Storage S3 quy mô nhỏ cho khách doanh nghiệp: khoảng 50 TB dữ liệu, hạ tầng ban đầu 3 đến 4 server, yêu cầu chịu lỗi tối thiểu 1 server. Hãy so sánh **MinIO** và **Ceph RGW** cho bài toán cụ thể này và đưa ra khuyến nghị lựa chọn.

**Đề B:** Một máy chủ shared hosting thường xuyên bị bot crawl dữ liệu dồn dập khiến cả hệ thống bị chậm. Hãy so sánh phương án chặn / rate-limit ở **tầng L4 (nftables)** với **tầng L7 (Nginx `limit_req` hoặc tương đương)** và đề xuất mô hình triển khai phù hợp cho hosting.

**Yêu cầu:** viết `phan3-nghien-cuu.md`, khoảng nửa đến một trang A4:

- Đưa ra tiêu chí so sánh rõ ràng, có số liệu hoặc dẫn chứng từ tài liệu chính thức (official docs, source code, benchmark uy tín).
- Đưa ra khuyến nghị chốt kèm đánh giá rủi ro kỹ thuật / đánh đổi (trade-offs).
- Khuyến khích (không bắt buộc): bổ sung kết quả benchmark từ lab cá nhân nếu có sẵn.

---

## Phần 4: Nhật ký làm bài (Bắt buộc)

Ghi chép vào file `phan4-nhat-ky.md` theo mẫu `MAU-NHAT-KY.md` đi kèm.
Bạn hãy ghi nhận chân thực: mốc thời gian làm bài, tổng thời gian thực tế, những chỗ bị vướng, các phương án đã thử, việc sử dụng AI/công cụ hỗ trợ ở bước nào và cách bạn kiểm chứng lại kết quả của AI.

---

Hy vọng bài test mang lại cho bạn những thử thách thú vị. Cần làm rõ bất kỳ điểm nào trong đề bài, bạn cứ reply email này nhé.

**Team RnD, Vietnix**
