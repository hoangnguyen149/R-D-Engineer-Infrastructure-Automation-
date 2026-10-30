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

Lệnh trên dữ liệu gốc trả exit **2 có chủ đích**, không phải crash. Warnings đi stderr; stdout JSON parse được. `--format table` là mặc định. Có thể đổi ngưỡng:

```bash
python3 cluster_balance.py examples/lab-assumptions.json --cpu-threshold 0.8 --ram-threshold 0.85 --overcommit-threshold 4
```

| Exit | Ý nghĩa |
|---|---|
| 0 | Dữ liệu hợp lệ và đã có phương án cân bằng theo mô hình tài nguyên |
| 2 | Lỗi đọc/JSON/schema hoặc dữ liệu bất thường; không phát kế hoạch migrate |
| 3 | Dữ liệu hợp lệ nhưng heuristic chưa tìm được phương án cân bằng |

## Công thức và chính sách

- CPU core thực dùng = tổng `vcpus × cpu_usage` của VM running. CPU% = core thực dùng/core vật lý ×100.
- RAM thực dùng = tổng mem_used của VM running; RAM% = RAM thực dùng/mem_total ×100. GiB = byte/2^30.
- Overcommit đang hoạt động = tổng vCPU running/core vật lý. Báo thêm `configured_vcpus_all_valid_records` bao gồm VM stopped để lập kế hoạch bật máy; không tính stopped vào tải đang chạy.
- Quá tải khi CPU>80%, RAM>85% hoặc overcommit>4. Bằng đúng ngưỡng không coi là quá tải. Đây là ngưỡng do ứng viên lựa chọn, không mặc định Proxmox.
- mem_total <1GiB bị đánh dấu đáng ngờ theo sanity policy; không đoán đơn vị. CPU ngoài [0,1], NaN, boolean thay số, thiếu field, RAM âm/null/>mem_max, duplicate ID, node không tồn tại, running trên offline đều là lỗi dữ liệu.
- Mọi bản sao VM trùng bị loại khỏi phép cộng, không chọn bừa bản đầu. Tổng node bị thiếu bản ghi là lower bound, không được ghi là khỏe. Node có capacity sai hiển thị N/A cho tỷ lệ.
- Bất kỳ dữ liệu bất thường nào đều chặn toàn bộ kế hoạch tự động (`blocked_invalid_data`); có thể nhìn thấy node n01 quá tải ngay cả từ lower bound. Đây là chủ đích fail-closed thay vì tạo một kế hoạch “đủ ngưỡng” trên số liệu tự sửa.

## Thuật toán

Greedy xác định, mỗi lượt thử VM running chưa di chuyển từ node quá tải sang node online khác. Đích phải không vượt cả ba ngưỡng sau chuyển, và RAM đang dùng tại đích + **mem_max của VM đến** phải nằm trong ngân sách RAM 85% ở thời điểm nhận. Chọn bước giảm tổng phần vượt ngưỡng nhiều nhất; hòa thì chọn mem_max nhỏ hơn, VMID nhỏ hơn, tên đích. Cập nhật tải sau mỗi bước. Mỗi VM chỉ chuyển một lần, số vòng bị chặn bởi số VM.

Nếu còn quá tải mà không có bước hợp lệ, xuất `unresolved`, giữ danh sách bước từng phần để người đọc kiểm tra nhưng `resource_plan_complete=false`; không tuyên bố bài toán vô nghiệm toàn cục. Greedy không bảo đảm số lượt tối thiểu, không tìm mọi chuỗi di chuyển trung gian. Cách tính hiện tại phù hợp snapshot nhỏ; một lần thử tính lại tải nên không tối ưu cho hàng chục nghìn VM.

`resource_plan_complete=true` chỉ bảo đảm bất biến CPU/RAM/overcommit của mô hình snapshot, không phải an toàn production. Chưa có host overhead, dự báo tải, dirty-page rate, storage/IOPS/network, HA/affinity, CPU model, passthrough hoặc lock. Dự phòng 20% CPU/15% RAM không thay thế đo overhead thực. Trước live migration cần snapshot mới, quorum/storage/network/CPU tương thích và kiểm tra từng bước; `production_ready` luôn false.

## Kết quả dữ liệu gốc

Có 6 node, gồm n04 offline, và 66 VMID duy nhất trong 67 bản ghi; số bản ghi không được dùng thay số VM chạy.

Các lỗi cụ thể: n06 mem_total=262144 byte; VM 2067/2073/2065 cpu_usage=31/98/20.8; VM 2001 trùng ở n01/n02; VM 2199 thiếu mem_used; VM 2390 trỏ n07 không có trong nodes. Không tự sửa % thành fraction hoặc đoán n06 là 256GiB. Tổng CPU/RAM hợp lệ của n01 đã là 81,37%/88,34%, vượt ngưỡng dù chưa cộng VM2001.

Xem `examples/original-output.txt`, `original-output.json`, `original-warnings.txt` — output thực tế đã chạy. JSON gốc được giữ nguyên byte tại `examples/original.json`.

## Lab minh họa — KHÔNG dùng làm dữ liệu production

`examples/lab-assumptions.json` ghi công khai các giả định: n06=256GiB; VM2001 thuộc n01; ba CPU >1 là % và chia 100; VM2199 mem_used=mem_max theo dự phòng; bỏ VM2390 khỏi lab cô lập. Đây là dữ liệu giả định để chứng minh thuật toán, không phải kết quả điều tra đã xác minh.

Kết quả: chuyển VM2008 n01 → n02. CPU n01 giảm từ 85,92% xuống 74,89%, RAM từ 93,00% xuống 81,72%. CPU n02 lên 50,11%, RAM lên 66,28%. Các node online còn lại vẫn dưới ngưỡng. File output ghi đầy đủ kế hoạch và trạng thái trước/sau.

## Kiểm thử

Các test kiểm chứng công thức, stopped VM, ranh giới ngưỡng, CPU/RAM/overcommit overload, fail-closed dữ liệu bẩn, offline target, thiếu capacity, mem_max lúc nhận, bảo toàn tổng tài nguyên và an toàn đích sau từng bước. Có CLI integration test cho JSON hỏng và đường dẫn không tồn tại. Kết quả chạy ở `examples/test-results.txt`.

Nguồn kiểm tra điều kiện hạ tầng: Proxmox official requirements https://proxmox.com/en/products/proxmox-virtual-environment/requirements ; không suy luận điều kiện migrate chỉ từ RAM còn trống.
