# Proxmox Cluster Load Analyzer

Tool Python 3 (chỉ dùng standard library) đọc snapshot JSON của một cluster Proxmox VE, tính tải từng node, đánh dấu node quá tải và **đề xuất** (không thực thi) kế hoạch live-migrate VM để cân bằng tải.

## Yêu cầu và cài đặt

- Python 3 (mã viết tương thích 3.8+, nhưng chỉ được chạy thử trên Python 3.12.3). Không cần cài thêm package.
- Không cần cài đặt: chạy trực tiếp `analyze_cluster.py`.

```bash
cd phan2-proxmox
python3 analyze_cluster.py --input cluster-pve-hcm-c3.json --format table
python3 analyze_cluster.py --input cluster-pve-hcm-c3.json --format json | jq .migration_plan
python3 analyze_cluster.py -i cluster-pve-hcm-c3.json -f json --cpu-threshold 75 --ram-threshold 80 --overcommit-threshold 3
```

| Option | Mặc định | Ý nghĩa |
|---|---|---|
| `--input/-i` | (bắt buộc) | file JSON snapshot |
| `--format/-f` | `table` | `table` (đọc trên terminal) hoặc `json` (cho script) |
| `--cpu-threshold` | 80 | % CPU thực dùng / số core vật lý |
| `--ram-threshold` | 85 | % RAM thực dùng (`mem_used`) / `mem_total` |
| `--overcommit-threshold` | 4 | vCPU cấp phát / core vật lý (4 nghĩa là 4:1) |
| `--warn-ratio` | 0.9 | WARNING khi chỉ số ≥ 90% ngưỡng |
| `--mem-alloc-limit` | 100 | node nhận: tổng `mem_max` sau khi nhận ≤ n% `mem_total` |
| `--max-migrations`, `--beam` | 6, 8 | giới hạn tìm kiếm của planner |
| `--strict` | tắt | bản ghi lỗi trở thành lỗi dừng (exit 2) thay vì bị cách ly |
| `--quiet/-q`, `--no-color` | | tắt warning trên stderr / tắt màu |

Exit code: `0` thành công (có hoặc không có kế hoạch), `2` lỗi input hoặc tham số, `3` `NO_FEASIBLE_PLAN` (có node quá tải mà không có kế hoạch an toàn), `4` lỗi nội bộ. Stdout chỉ chứa kết quả; cảnh báo và lỗi nằm ở stderr, nên ở chế độ JSON có thể pipe thẳng sang `jq` hoặc script khác.

## Công thức (chỉ tính VM `running`)

| Chỉ số | Công thức |
|---|---|
| CPU thực dùng (core) | `Σ vcpus × cpu_usage` |
| CPU % | `core thực dùng / cpu_cores × 100` |
| RAM % | `Σ mem_used / mem_total × 100` |
| Overcommit vCPU | `Σ vcpus / cpu_cores` |
| RAM cấp phát % | `Σ mem_max / mem_total × 100` (chỉ dùng làm ràng buộc an toàn cho node nhận) |

Đơn vị hiển thị: GiB = 1024³ byte. Đây là mô hình ước tính cộng dồn từ VM; **chưa** gồm overhead của hypervisor và tiến trình trên host (snapshot không có số liệu host để đối chiếu). VM `stopped` không tính vào tải, nhưng được báo riêng số lượng và số vCPU cấp phát.

## Ngưỡng và giả định

Các ngưỡng là **giả định vận hành** để phân tích, không phải mặc định của Proxmox; hiệu chỉnh theo baseline của từng cluster.

- **OVERLOADED:** một trong ba chỉ số **lớn hơn hẳn** ngưỡng (`>`, so sánh nghiêm ngặt: đúng 80,0% chưa phải quá tải).
- **WARNING:** chưa quá tải nhưng một chỉ số `≥ 0,9 × ngưỡng`.
- **NORMAL / OFFLINE / UNKNOWN:** bình thường / node `offline` / node không đủ dữ liệu tin cậy.
- Node nhận VM phải còn **NORMAL sau khi nhận** (không bị đẩy vào vùng WARNING) và `Σ mem_max ≤ --mem-alloc-limit`, để RAM không cạn khi guest tăng dùng; node nguồn chỉ cần xuống ≤ ngưỡng.

## Thuật toán migration

1. Chỉ VM `running`, dữ liệu tin cậy và không bị "ghim" mới được chuyển (VM `stopped` không bao giờ).
2. Node nhận phải `online`, dữ liệu hợp lệ, đang NORMAL, khác node nguồn. Không chuyển tới node offline hoặc UNKNOWN.
3. Mỗi bước tính lại tải node nguồn và node nhận, kiểm tra CPU, RAM thực dùng, overcommit, RAM cấp phát. Mỗi VM chỉ chuyển một lần; vì node nhận luôn NORMAL nên không thể trở thành node nguồn, nghĩa là không có vòng lặp.
4. Tìm kiếm **iterative deepening** (1, 2, … tối đa `--max-migrations`) bằng DFS với **beam** `--beam`, có ghi nhớ trạng thái đã thất bại và ngân sách số lần mở rộng. Ứng viên được xếp theo: mức quá tải còn lại của nguồn, rồi dung lượng RAM phải chuyển (`mem_used`, nhỏ trước), rồi áp lực lên node nhận, rồi `vmid` để kết quả xác định (deterministic).
5. Đây là **heuristic**: tìm kế hoạch ít migration nhất *trong giới hạn tìm kiếm*, không chứng minh tối ưu toàn cục và có thể bỏ sót phương án ngoài beam.
6. Nếu không có kế hoạch an toàn thì trả `NO_FEASIBLE_PLAN`, không tạo kế hoạch giả, kèm lượng cần giải phóng ở từng node quá tải và headroom còn lại của các node nhận. Nếu hết ngân sách tìm kiếm thì lý do ghi rõ đó là giới hạn của heuristic, không phải chứng minh bất khả thi.

Tool chỉ **đề xuất**. Snapshot không có shared storage, CPU compatibility, network, chính sách HA, passthrough, băng thông migration. Mỗi kế hoạch kèm danh sách preflight check (7 mục) cần xác nhận trước khi chạy `qm migrate` thật.

## Xử lý dữ liệu lỗi

Mặc định bản ghi lỗi **không làm crash tool**: bản ghi bị cách ly, in cảnh báo (`WARNING: [vm 2067] ...` ở stderr, đồng thời trong mảng `warnings` của JSON), và không bao giờ dùng như dữ liệu đã xác thực.

| Lỗi | Xử lý |
|---|---|
| File không tồn tại / không đọc được / thư mục / rỗng / JSON hỏng / `NaN` / thiếu `nodes`,`vms` | thông báo lỗi ngắn, exit 2, không traceback |
| Node thiếu trường, `cpu_cores`/`mem_total` ≤ 0, trùng tên | bỏ bản ghi (giữ bản đầu) |
| `mem_total` < 1 GiB (nghi sai đơn vị) | node = UNKNOWN, loại khỏi việc chuyển đến/đi |
| VM thiếu trường, `vcpus`/`mem_max` không hợp lệ hoặc âm, trỏ tới node không có | bỏ bản ghi, cảnh báo (tải của nó **không** được tính ở đâu) |
| `cpu_usage` ngoài [0,1] hoặc `mem_used` không hợp lệ (null, âm, > `mem_max`) | không tự đổi đơn vị; phần CPU/RAM đó bị coi là chưa xác thực: không đưa vào số liệu tin cậy, nhưng khi kiểm tra node nhận thì tính ở **trường hợp xấu nhất** (cpu = vcpus, ram = `mem_max`); VM bị ghim |
| `vmid` trùng trên hai node | tải tính trên cả hai node (an toàn), VM bị ghim |
| `status` lạ | node → UNKNOWN; VM không tính tải, không chuyển |

## Kết quả chạy thật trên `cluster-pve-hcm-c3.json`

```text
Cluster pve-hcm-c3 | snapshot 2026-10-27T09:00:00+07:00 | nodes=6 vms=66 (running 63)
Thresholds: CPU>80%  RAM>85%  vCPU overcommit>4:1  (WARNING from 90% of threshold)  [assumptions]

+------------+---------+----------------+-------+--------------------+-------+------+------------+------------+
| Node       | State   | CPU cores used |  CPU% | RAM used/total GiB |  RAM% | vCPU | Overcommit | Health     |
+------------+---------+----------------+-------+--------------------+-------+------+------------+------------+
| hcm-c3-n01 | online  |        55.0/64 | 85.9% |            476/512 | 93.0% |  110 |     1.72:1 | OVERLOADED |
| hcm-c3-n02 | online  |        23.9/64 | 37.3% |            306/512 | 59.7% |   92 |     1.44:1 | NORMAL*    |
| hcm-c3-n03 | online  |        18.2/48 | 38.0% |            180/384 | 47.0% |   80 |     1.67:1 | NORMAL     |
| hcm-c3-n04 | offline |         0.0/48 |  0.0% |              0/384 |  0.0% |    0 |     0.00:1 | OFFLINE    |
| hcm-c3-n05 | online  |        50.5/64 | 78.9% |            368/512 | 71.9% |   72 |     1.12:1 | WARNING*   |
| hcm-c3-n06 | online  |         9.6/32 | 30.0% |              133/? |   n/a |   94 |     2.94:1 | UNKNOWN    |
+------------+---------+----------------+-------+--------------------+-------+------+------------+------------+
* = node hosts running VMs with unverified metrics (see warnings); WARNING/NORMAL use trusted data only
  - hcm-c3-n01: cpu 85.9 > 80.0; ram 93.0 > 85.0
  - hcm-c3-n06: mem_total invalid, RAM utilisation cannot be computed

Migration plan: PLAN_FOUND - plan clears all overloaded nodes using 1 migration(s)
+------+------------+------------+------------+------+---------+------------+------------+------------+------------+
| VMID | Name       | From       | To         | vCPU | RAM GiB |   Src CPU% |   Src RAM% |   Dst CPU% |   Dst RAM% |
+------+------------+------------+------------+------+---------+------------+------------+------------+------------+
| 2008 | db-ent-415 | hcm-c3-n01 | hcm-c3-n03 | 8    |    57.7 | 85.9->74.9 | 93.0->81.7 | 38.0->52.7 | 47.0->62.0 |
+------+------------+------------+------------+------+---------+------------+------------+------------+------------+
RECOMMENDATION ONLY - nothing was migrated. Run preflight checks first:
  [ ] Shared storage (or storage migration plan) reachable from the destination node
  [ ] CPU model/flags compatible between source and destination (or a generic CPU type is set)
  [ ] Same bridges/VLANs/firewall rules available on the destination
  [ ] No local disks, PCI/USB passthrough or other migration blockers on the VM
  [ ] HA group/affinity/anti-affinity rules allow the move
  [ ] Migration network bandwidth/latency acceptable for the mem_used to transfer; schedule outside peak
  [ ] Destination metrics re-checked live immediately before migrating (this plan uses a stale snapshot)

Data-quality warnings (7, also on stderr):
  ! [node hcm-c3-n06] mem_total=262144 bytes (< 1 GiB) is implausible - probably a unit error (MiB instead of bytes?). RAM metrics unknown; node excluded from migration
  ! [vm 2067] cpu_usage=31.0 outside [0,1] (looks like a percentage, not a 0..1 ratio; NOT auto-converted); CPU treated as unverified (worst case = all vCPUs busy)
  ! [vm 2073] cpu_usage=98.0 outside [0,1] (looks like a percentage, not a 0..1 ratio; NOT auto-converted); CPU treated as unverified (worst case = all vCPUs busy)
  ! [vm 2065] cpu_usage=20.8 outside [0,1] (looks like a percentage, not a 0..1 ratio; NOT auto-converted); CPU treated as unverified (worst case = all vCPUs busy)
  ! [vm 2199] mem_used=None invalid (must be 0..mem_max); RAM treated as unverified (worst case = mem_max)
  ! [vm 2390] unknown node mapping 'hcm-c3-n07'; skipped (its load is NOT included anywhere)
  ! [vm 2001] duplicate vmid on different nodes (hcm-c3-n01, hcm-c3-n02); load counted on each claimed node, VM pinned (never migrated) until the inventory is fixed
```

Phần cảnh báo (7 dòng) in thêm ở stderr. Chạy `-q` ở trên để ẩn. Các điểm bất thường phát hiện trong snapshot: node `n06` có `mem_total=262144` (nghi tính theo MiB), VM 2067/2073/2065 có `cpu_usage` 31.0/98.0/20.8 (nghi là %), VM 2199 có `mem_used=null`, VM 2390 trỏ tới node `hcm-c3-n07` không tồn tại, vmid 2001 xuất hiện trên cả `n01` và `n02`.

**Đối chiếu thủ công cho `hcm-c3-n01`:** Σ(vcpus × cpu_usage) = 54,99 core → 85,9% của 64 core; Σ mem_used = 476,2 GiB → 93,0% của 512 GiB; Σ vcpus = 110 → overcommit 1,72. Sau khi chuyển VM 2008: CPU 74,9%, RAM 81,7% (cả hai ≤ ngưỡng). Node nhận `n03`: CPU 52,7%, RAM 62,0%, RAM cấp phát 85,2%, overcommit 1,83 (tự tính lại ngoài tool, khớp kết quả).

**Độ nhạy với dữ liệu bẩn:** nếu loại hẳn bản ghi trùng vmid 2001 khỏi `n01`, node này vẫn quá tải (CPU ≈ 81,4%, RAM ≈ 88,3%), nên kết luận "n01 quá tải" không phụ thuộc vào dữ liệu nghi ngờ đó. `n02` chứa 3 VM CPU chưa xác thực; với trường hợp xấu nhất (mọi vCPU bận 100%) CPU của nó chỉ ≈ 53.0%, vẫn là NORMAL.

Khi không có kế hoạch an toàn (ví dụ giả lập `--cpu-threshold 30`, exit code 3):

```text
Migration plan: NO_FEASIBLE_PLAN - no feasible plan: no destination node is NORMAL (online, valid data, below the warning level)
  Needs more capacity: hcm-c3-n01 must free 35.79 cores / 40.96 GiB RAM / 0.0 vCPU
  Needs more capacity: hcm-c3-n02 must free 4.69 cores / 0.0 GiB RAM / 0.0 vCPU
  Needs more capacity: hcm-c3-n03 must free 3.84 cores / 0.0 GiB RAM / 0.0 vCPU
  Needs more capacity: hcm-c3-n05 must free 31.31 cores / 0.0 GiB RAM / 0.0 vCPU
```

### JSON mẫu (trích từ lần chạy thật, rút gọn mảng dài)

```json
{
  "cluster": {
    "name": "pve-hcm-c3",
    "collected_at": "2026-10-27T09:00:00+07:00",
    "source": "export từ /cluster/resources (đã rút gọn)",
    "nodes_total": 6,
    "vms_total": 66,
    "vms_running": 63
  },
  "thresholds": {
    "cpu_pct": 80.0,
    "ram_pct": 85.0,
    "vcpu_overcommit": 4.0,
    "warn_ratio": 0.9,
    "dest_mem_alloc_pct": 100.0,
    "max_migrations": 6,
    "beam": 8,
    "overloaded_when": "value > threshold (strict)",
    "warning_when": "value >= warn_ratio * threshold",
    "assumption": "operational assumptions, not official Proxmox limits"
  },
  "nodes": [
    {
      "node": "hcm-c3-n01",
      "state": "online",
      "health": "OVERLOADED",
      "cpu_cores_used": 54.99,
      "cpu_pct": 85.9,
      "cpu_pct_worst_case": 85.9,
      "ram_used_gib": 476.2,
      "ram_pct": 93.0,
      "vcpu_allocated": 110.0,
      "vcpu_overcommit": 1.72,
      "unverified_vms": []
    },
    {
      "node": "hcm-c3-n02",
      "state": "online",
      "health": "NORMAL",
      "cpu_cores_used": 23.89,
      "cpu_pct": 37.3,
      "cpu_pct_worst_case": 53.0,
      "ram_used_gib": 305.5,
      "ram_pct": 59.7,
      "vcpu_allocated": 92.0,
      "vcpu_overcommit": 1.44,
      "unverified_vms": [
        2067,
        2073,
        2065
      ]
    }
  ],
  "overloaded_nodes": [
    "hcm-c3-n01"
  ],
  "migration_plan": {
    "status": "PLAN_FOUND",
    "reason": "plan clears all overloaded nodes using 1 migration(s)",
    "recommendation_only": true,
    "migrations": [
      {
        "vmid": 2008,
        "name": "db-ent-415",
        "from": "hcm-c3-n01",
        "to": "hcm-c3-n03",
        "vcpus": 8,
        "cpu_cores_used": 7.064,
        "mem_used_gib": 57.74,
        "mem_max_gib": 68.0,
        "source": {
          "before": {
            "cpu_pct": 85.9,
            "ram_pct": 93.0,
            "overcommit": 1.72
          },
          "after": {
            "cpu_pct": 74.9,
            "ram_pct": 81.7,
            "overcommit": 1.59
          }
        },
        "destination": {
          "before": {
            "cpu_pct": 38.0,
            "ram_pct": 47.0,
            "overcommit": 1.67
          },
          "after": {
            "cpu_pct": 52.7,
            "ram_pct": 62.0,
            "overcommit": 1.83
          }
        },
        "preflight_required": true
      }
    ],
    "algorithm": "iterative-deepening beam-limited DFS; heuristic, not proven globally optimal",
    "preflight_checks": "[... 7 items ...]"
  },
  "warnings": [
    {
      "scope": "node",
      "id": "hcm-c3-n06",
      "message": "mem_total=262144 bytes (< 1 GiB) is implausible - probably a unit error (MiB instead of bytes?). RAM metrics unknown; node excluded from migration"
    },
    "... (7 total)"
  ],
  "summary": {
    "overloaded": 1,
    "migrations_proposed": 1,
    "plan_status": "PLAN_FOUND",
    "warnings": 7
  }
}
```

## Kiểm thử

```bash
cd phan2-proxmox
python3 -m unittest discover -s tests -v
```

Kết quả lần chạy cuối: `Ran 49 tests in 1.135s`, `OK`. Bộ test (49 test) gồm: công thức CPU/RAM/overcommit, ranh giới ngưỡng (`>` và `≥`), phân loại, điều kiện chuyển VM (stopped, offline, cùng node, ghim), kiểm tra sức chứa node nhận, `NO_FEASIBLE_PLAN`, kế hoạch 2 bước, hết ngân sách tìm kiếm, JSON hỏng/thiếu trường/giá trị sai/trùng ID, JSON hợp lệ trên stdout (cảnh báo ở stderr), tính xác định, và một bài **kiểm tra bất biến trên 150 cluster ngẫu nhiên** (VM chỉ chuyển một lần, không chuyển VM stopped, không đến node offline, tính lại từ đầu sau kế hoạch thì không node nào quá tải và node nhận vẫn NORMAL). Fixture trong test là **dữ liệu tổng hợp**; chỉ `RealSnapshotTest` đọc snapshot thật.

## Giới hạn và lưu ý khi dùng thật

- Đây là snapshot tĩnh, `cpu_usage` là một thời điểm chứ không phải trung bình; nên dùng số liệu trung bình 15–60 phút để tránh chuyển VM theo đỉnh tức thời.
- Không có số liệu I/O, mạng, chính sách HA, CPU model, shared storage; đề xuất chưa thể coi là chắc chắn thực thi được.
- Không xét affinity giữa các VM (ví dụ hai node của cùng một cluster ứng dụng không nên nằm chung host).
- Mô hình cộng VM bỏ qua overhead hypervisor, ZFS ARC/Ceph trên host, và RAM cho chính migration.
- Triển khai thật: chạy định kỳ bằng cron/systemd timer với dữ liệu xuất từ `pvesh get /cluster/resources --output-format json` (cần một bước chuẩn hóa schema `node`/`vms`), đẩy JSON tới hệ thống cảnh báo; việc migrate nên do người vận hành duyệt hoặc workflow có kiểm tra preflight, không tự động.
