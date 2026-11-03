# Tool phân tích tải Proxmox — Python standard library

Python >=3.10, không cần pip/dependency ngoài. Tool chỉ đọc JSON và đưa đề xuất, không gọi API/SSH, không tự migrate.

## Chạy

Từ thư mục `phan2-tool/`:

```bash
python3 cluster_balance.py examples/original.json
python3 cluster_balance.py examples/original.json --format json > original-report.json
python3 cluster_balance.py examples/lab-assumptions.json --format json > lab-report.json
python3 -m unittest discover -s tests -v
```

Lệnh trên dữ liệu gốc trả exit **4 có chủ đích** (có đề xuất nhưng một phần bản ghi bị loại), không phải crash. Warnings đi stderr; stdout JSON parse được. `--format table` là mặc định. Đọc mã thoát ngay sau lệnh cần kiểm tra (`echo $?` trong Bash). Có thể đổi ngưỡng:

```bash
python3 cluster_balance.py examples/lab-assumptions.json --cpu-threshold 0.8 --ram-threshold 0.85 --overcommit-threshold 4
```

| Exit | Ý nghĩa |
|---|---|
| 0 | Dữ liệu sạch hoàn toàn và đã có phương án cân bằng theo mô hình tài nguyên (`balanced`) |
| 2 | Lỗi đọc file/JSON/schema gốc, hoặc không còn node online hợp lệ nào để đánh giá (`input_error`, `blocked_invalid_data`) |
| 3 | Heuristic chưa tìm được phương án cân bằng (`unresolved`, `unresolved_with_excluded_records`), kể cả khi có một phần bước |
| 4 | Phần dữ liệu hợp lệ không còn quá tải nhưng còn cảnh báo (`partial_plan_with_excluded_records`); chưa chứng nhận toàn cluster. `plan` có thể rỗng nếu không cần/còn VM hợp lệ để di chuyển |

## Công thức và chính sách

- CPU core thực dùng = tổng `vcpus × cpu_usage` của VM running. CPU% = core thực dùng/core vật lý ×100.
- RAM thực dùng = tổng mem_used của VM running; RAM% = RAM thực dùng/mem_total ×100. GiB = byte/2^30.
- Overcommit đang hoạt động = tổng vCPU running/core vật lý. Báo thêm `configured_vcpus_all_valid_records` bao gồm VM stopped để lập kế hoạch bật máy; không tính stopped vào tải đang chạy.
- Quá tải khi CPU>80%, RAM>85% hoặc overcommit>4. Bằng đúng ngưỡng không coi là quá tải. Đây là ngưỡng do ứng viên lựa chọn, không mặc định Proxmox.
- mem_total <1GiB bị đánh dấu đáng ngờ theo sanity policy; không đoán đơn vị. CPU ngoài [0,1], NaN, boolean thay số, thiếu field, RAM âm/null/>mem_max, duplicate ID, node không tồn tại, running trên offline đều là lỗi dữ liệu.
- Mọi bản sao VM trùng bị loại khỏi phép cộng, không chọn bừa bản đầu. Tổng node bị thiếu bản ghi là lower bound, không được ghi là khỏe. Node có capacity sai hiển thị N/A cho tỷ lệ.
- **Bản ghi lỗi chỉ bị loại khỏi kế hoạch, không chặn cả cluster.** Mỗi lý do lỗi được giữ trong stderr và `warnings[]`; một bản ghi có thể có nhiều cảnh báo. `excluded_records` đếm số bản ghi node/VM lỗi riêng biệt. Các VM/node hợp lệ vẫn được đưa vào tính toán và đề xuất migrate. Tool không tự sửa số liệu (không đổi % thành fraction, không đoán đơn vị, không chọn bản trùng).
- **Node thiếu bản ghi (tainted) hoặc có capacity/status sai không bao giờ làm node đích.** Node nguồn còn capacity/status hợp lệ vẫn có thể giảm tải bằng cách chuyển VM hợp lệ; bước chuyển được gắn `source_load_is_lower_bound=true`. Node sai capacity không đánh giá được quá tải nên không tự suy ra bước chuyển từ node đó. Tải nguồn thiếu dữ liệu vẫn chỉ là cận dưới sau mô phỏng, không chứng nhận đã hết quá tải hay migration an toàn trên hạ tầng thật.
- Khi có bản ghi bị loại, trạng thái không bao giờ là `balanced` mà là `partial_plan_with_excluded_records` (hoặc `unresolved_with_excluded_records`) và `resource_plan_complete=false`. `blocked_invalid_data` chỉ còn dùng khi không có node online hợp lệ nào để đánh giá.

## Thuật toán

Greedy xác định, mỗi lượt thử VM running chưa di chuyển từ node quá tải sang node online khác. Đích phải không vượt cả ba ngưỡng sau chuyển, và RAM đang dùng tại đích + **mem_max của VM đến** phải nằm trong ngân sách RAM 85% ở thời điểm nhận. Chọn bước giảm tổng phần vượt ngưỡng nhiều nhất; hòa thì chọn mem_max nhỏ hơn, VMID nhỏ hơn, tên đích. Cập nhật tải sau mỗi bước. Mỗi VM chỉ chuyển một lần, số vòng bị chặn bởi số VM.

Nếu còn quá tải mà không có bước hợp lệ, xuất `unresolved`, giữ danh sách bước từng phần để người đọc kiểm tra nhưng `resource_plan_complete=false`; không tuyên bố bài toán vô nghiệm toàn cục. Greedy không bảo đảm số lượt tối thiểu, không tìm mọi chuỗi di chuyển trung gian. Cách tính hiện tại phù hợp snapshot nhỏ; một lần thử tính lại tải nên không tối ưu cho hàng chục nghìn VM.

`resource_plan_complete=true` chỉ bảo đảm bất biến CPU/RAM/overcommit của mô hình snapshot, không phải an toàn production. Chưa có host overhead, dự báo tải, dirty-page rate, storage/IOPS/network, HA/affinity, CPU model, passthrough hoặc lock. Dự phòng 20% CPU/15% RAM không thay thế đo overhead thực. Trước live migration cần snapshot mới, quorum/storage/network/CPU tương thích và kiểm tra từng bước; `production_ready` luôn false.

## Kết quả dữ liệu gốc

Có 6 node, gồm n04 offline, và 66 VMID duy nhất trong 67 bản ghi; số bản ghi không được dùng thay số VM chạy.

Các lỗi cụ thể (8 cảnh báo): n06 mem_total=262144 byte; VM 2067/2073/2065 cpu_usage=31/98/20.8; VM 2001 trùng ở n01/n02 (cả hai bản bị loại); VM 2199 thiếu mem_used; VM 2390 trỏ n07 không có trong nodes. Không tự sửa % thành fraction hoặc đoán n06 là 256GiB. Tổng CPU/RAM hợp lệ của n01 là 81,37%/88,34%, vượt ngưỡng dù chưa cộng VM2001, nên đây là lower bound của mức quá tải.

Trước đây tool chặn toàn bộ (`blocked_invalid_data`, plan rỗng). Hiện tool loại 7 bản ghi VM lỗi và loại node n06 khỏi đích, giữ nguyên 8 cảnh báo và đề xuất: **chuyển VM 2018 từ hcm-c3-n01 sang hcm-c3-n03** (exit 4). Chỉ n03 đủ điều kiện làm node đích: n02 và n05 thiếu bản ghi, n06 sai capacity, n04 offline. Sau bước chuyển, n01 còn 77,69% CPU / 84,57% RAM trên dữ liệu hợp lệ, nhưng vì thiếu VM 2001 nên vẫn ghi `unknown`, cần sửa dữ liệu và xuất snapshot mới để xác nhận. n03 sau khi nhận: 42,90% CPU / 52,02% RAM, dưới ngưỡng mô hình.

Xem `examples/original-output.txt`, `original-output.json`, `original-warnings.txt` — output thực tế đã chạy. JSON gốc được giữ nguyên byte tại `examples/original.json`.

## Lab minh họa — KHÔNG dùng làm dữ liệu production

`examples/lab-assumptions.json` ghi công khai các giả định: n06=256GiB; VM2001 thuộc n01; ba CPU >1 là % và chia 100; VM2199 mem_used=mem_max theo dự phòng; bỏ VM2390 khỏi lab cô lập. Đây là dữ liệu giả định để chứng minh thuật toán, không phải kết quả điều tra đã xác minh.

Kết quả: chuyển VM2008 n01 → n02. CPU n01 giảm từ 85,92% xuống 74,89%, RAM từ 93,00% xuống 81,72%. CPU n02 lên 50,11%, RAM lên 66,28%. Các node online còn lại vẫn dưới ngưỡng. File output ghi đầy đủ kế hoạch và trạng thái trước/sau.

## Kiểm thử

34 test kiểm chứng công thức, stopped VM, ranh giới ngưỡng, CPU/RAM/overcommit overload, loại bản ghi lỗi nhưng vẫn lập kế hoạch, node thiếu dữ liệu không làm đích, node nguồn thiếu dữ liệu vẫn chuyển được, offline target, thiếu capacity, mem_max lúc nhận, bảo toàn tổng tài nguyên hợp lệ và ngưỡng đích sau từng bước. Có test hồi quy trên file gốc của đề (phải có ít nhất một bước migrate từ n01 sang n03, đủ 8 cảnh báo, exit 4), giữ nhãn cận dưới sau mô phỏng, đếm bản ghi khác với số cảnh báo, và CLI integration test cho JSON hỏng, đường dẫn không tồn tại, exit 0/2/3/4. Kết quả chạy ở `examples/test-results.txt`.

Nguồn kiểm tra điều kiện hạ tầng: Proxmox official requirements https://proxmox.com/en/products/proxmox-virtual-environment/requirements ; không suy luận điều kiện migrate chỉ từ RAM còn trống.
