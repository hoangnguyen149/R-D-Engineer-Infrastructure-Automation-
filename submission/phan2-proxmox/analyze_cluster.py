#!/usr/bin/env python3
"""Proxmox cluster load analyzer.

Reads a snapshot of a Proxmox VE cluster (JSON), computes per-node load,
flags overloaded nodes and *recommends* live-migrations. It never talks to a
real cluster and never performs a migration.

Only the Python 3 standard library is used.
Exit codes: 0 ok, 2 input/usage error, 3 NO_FEASIBLE_PLAN, 4 internal error.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import math
import os
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

GIB = 1024 ** 3
MIN_PLAUSIBLE_MEM_TOTAL = GIB  # a hypervisor with < 1 GiB RAM is a data/unit error

EXIT_OK = 0
EXIT_INPUT_ERROR = 2
EXIT_NO_FEASIBLE = 3
EXIT_INTERNAL = 4

HEALTH_NORMAL = "NORMAL"
HEALTH_WARNING = "WARNING"
HEALTH_OVERLOADED = "OVERLOADED"
HEALTH_OFFLINE = "OFFLINE"
HEALTH_UNKNOWN = "UNKNOWN"

PLAN_FOUND = "PLAN_FOUND"
NO_ACTION = "NO_ACTION_NEEDED"
NO_FEASIBLE = "NO_FEASIBLE_PLAN"

log = logging.getLogger("analyze_cluster")


class InputError(Exception):
    """Fatal, expected problem with the input (reported without traceback)."""


# --------------------------------------------------------------------------
# Data model
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Thresholds:
    cpu: float = 80.0          # % of physical cores
    ram: float = 85.0          # % of mem_total (sum of mem_used)
    overcommit: float = 4.0    # allocated vCPU / physical cores
    warn_ratio: float = 0.9    # WARNING when value >= warn_ratio * threshold
    mem_alloc: float = 100.0   # destination: sum(mem_max) <= this % of mem_total
    max_migrations: int = 6
    beam: int = 8


@dataclass
class Node:
    name: str
    state: str                 # online | offline | unknown
    cpu_cores: float
    mem_total: float
    mem_valid: bool = True


@dataclass
class VM:
    uid: int                   # position in input, stable identifier
    vmid: Any
    name: str
    node: str
    status: str
    vcpus: float
    mem_max: float
    cpu_usage: Optional[float]
    mem_used: Optional[float]
    cpu_ok: bool = True        # cpu_usage trusted
    ram_ok: bool = True        # mem_used trusted
    pin_reason: Optional[str] = None  # why it must never be migrated

    @property
    def running(self) -> bool:
        return self.status == "running"

    @property
    def movable(self) -> bool:
        return self.running and self.cpu_ok and self.ram_ok and self.pin_reason is None

    @property
    def label(self) -> str:
        return "vmid=%s (%s)" % (self.vmid, self.name)


@dataclass
class Cluster:
    name: str
    collected_at: Optional[str]
    source: Optional[str]
    nodes: Dict[str, Node]
    vms: List[VM]


@dataclass
class NodeLoad:
    cpu_used: float = 0.0        # cores, from trusted records only
    cpu_unverified: float = 0.0  # worst case (vCPU count) of records with untrusted cpu_usage
    ram_used: float = 0.0        # bytes, trusted records only
    ram_unverified: float = 0.0  # worst case (mem_max) of records with untrusted mem_used
    vcpu_alloc: float = 0.0      # allocated vCPU of running VMs
    mem_alloc: float = 0.0       # sum(mem_max) of running VMs
    running_vms: int = 0


class Diagnostics:
    """Collects warnings; mirrors them to stderr via logging."""

    def __init__(self) -> None:
        self.items: List[Dict[str, str]] = []

    def warn(self, scope: str, ident: Any, message: str) -> None:
        self.items.append({"scope": scope, "id": str(ident), "message": message})
        log.warning("[%s %s] %s", scope, ident, message)


# --------------------------------------------------------------------------
# Loading and validation
# --------------------------------------------------------------------------
def _is_num(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _reject_constant(name: str) -> Any:
    raise ValueError("non-standard JSON constant %s" % name)


def load_json(path: str) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = fh.read()
    except FileNotFoundError:
        raise InputError("input file not found: %s" % path)
    except PermissionError:
        raise InputError("permission denied reading: %s" % path)
    except IsADirectoryError:
        raise InputError("input path is a directory: %s" % path)
    except UnicodeDecodeError as exc:
        raise InputError("input is not valid UTF-8: %s" % exc)
    except OSError as exc:
        raise InputError("cannot read %s: %s" % (path, exc))
    if not raw.strip():
        raise InputError("input file is empty: %s" % path)
    try:
        return json.loads(raw, parse_constant=_reject_constant)
    except ValueError as exc:
        raise InputError("invalid JSON in %s: %s" % (path, exc))


def validate_cluster(data: Any, diag: Diagnostics, strict: bool = False) -> Cluster:
    """Turn raw JSON into a Cluster. Bad records are quarantined, not trusted.

    strict=True turns the first bad record into a fatal InputError.
    """

    def bad(scope: str, ident: Any, msg: str) -> None:
        if strict:
            raise InputError("[%s %s] %s" % (scope, ident, msg))
        diag.warn(scope, ident, msg)

    if not isinstance(data, dict):
        raise InputError("top-level JSON must be an object with 'nodes' and 'vms'")
    for key in ("nodes", "vms"):
        if key not in data:
            raise InputError("missing required top-level field '%s'" % key)
        if not isinstance(data[key], list):
            raise InputError("field '%s' must be a list" % key)

    nodes: Dict[str, Node] = {}
    for idx, rec in enumerate(data["nodes"]):
        ident = rec.get("node", "#%d" % idx) if isinstance(rec, dict) else "#%d" % idx
        if not isinstance(rec, dict):
            bad("node", ident, "record is not an object; skipped")
            continue
        name = rec.get("node")
        if not isinstance(name, str) or not name.strip():
            bad("node", ident, "missing/invalid 'node' name; skipped")
            continue
        missing = [k for k in ("status", "cpu_cores", "mem_total") if k not in rec]
        if missing:
            bad("node", name, "missing field(s) %s; skipped" % ",".join(missing))
            continue
        if name in nodes:
            bad("node", name, "duplicate node name; later record skipped")
            continue
        if not _is_num(rec["cpu_cores"]) or rec["cpu_cores"] <= 0:
            bad("node", name, "cpu_cores=%r must be a positive number; skipped" % (rec["cpu_cores"],))
            continue
        if not _is_num(rec["mem_total"]) or rec["mem_total"] <= 0:
            bad("node", name, "mem_total=%r must be a positive number; skipped" % (rec["mem_total"],))
            continue
        status = rec["status"]
        state = status if status in ("online", "offline") else "unknown"
        if state == "unknown":
            bad("node", name, "unexpected status %r; treated as unknown" % (status,))
        mem_valid = rec["mem_total"] >= MIN_PLAUSIBLE_MEM_TOTAL
        if not mem_valid:
            bad("node", name,
                "mem_total=%s bytes (< 1 GiB) is implausible - probably a unit error "
                "(MiB instead of bytes?). RAM metrics unknown; node excluded from migration"
                % rec["mem_total"])
        nodes[name] = Node(name, state, float(rec["cpu_cores"]), float(rec["mem_total"]), mem_valid)
    if not nodes:
        raise InputError("no valid node record in input")

    vms: List[VM] = []
    seen: Dict[Tuple[Any, str], int] = {}
    for idx, rec in enumerate(data["vms"]):
        if not isinstance(rec, dict):
            bad("vm", "#%d" % idx, "record is not an object; skipped")
            continue
        vmid = rec.get("vmid")
        ident = vmid if vmid is not None else "#%d" % idx
        if isinstance(vmid, bool) or not isinstance(vmid, (int, str)) or vmid == "":
            bad("vm", ident, "missing/invalid 'vmid'; skipped")
            continue
        name = rec.get("name") if isinstance(rec.get("name"), str) else "?"
        missing = [k for k in ("node", "status", "vcpus", "mem_max") if k not in rec]
        if missing:
            bad("vm", vmid, "missing field(s) %s; skipped" % ",".join(missing))
            continue
        node = rec["node"]
        if not isinstance(node, str) or node not in nodes:
            bad("vm", vmid, "unknown node mapping %r; skipped (its load is NOT included anywhere)" % (node,))
            continue
        if not _is_num(rec["vcpus"]) or rec["vcpus"] <= 0 or rec["vcpus"] != int(rec["vcpus"]):
            bad("vm", vmid, "vcpus=%r must be a positive integer; skipped" % (rec["vcpus"],))
            continue
        if not _is_num(rec["mem_max"]) or rec["mem_max"] <= 0:
            bad("vm", vmid, "mem_max=%r must be a positive number; skipped" % (rec["mem_max"],))
            continue
        status = rec["status"] if isinstance(rec["status"], str) else "?"
        if status not in ("running", "stopped"):
            bad("vm", vmid, "status %r is neither running nor stopped; excluded from load and migration" % (rec["status"],))
        key = (vmid, node)
        if key in seen:
            bad("vm", vmid, "exact duplicate record on node %s; later record skipped" % node)
            continue
        seen[key] = idx

        cpu_usage = rec.get("cpu_usage")
        mem_used = rec.get("mem_used")
        cpu_ok = ram_ok = True
        if status == "running":
            if not _is_num(cpu_usage) or not 0 <= cpu_usage <= 1:
                hint = ""
                if _is_num(cpu_usage) and cpu_usage > 1:
                    hint = " (looks like a percentage, not a 0..1 ratio; NOT auto-converted)"
                bad("vm", vmid, "cpu_usage=%r outside [0,1]%s; CPU treated as unverified (worst case = all vCPUs busy)"
                    % (cpu_usage, hint))
                cpu_ok = False
            if not _is_num(mem_used) or mem_used < 0 or mem_used > rec["mem_max"]:
                bad("vm", vmid, "mem_used=%r invalid (must be 0..mem_max); RAM treated as unverified (worst case = mem_max)"
                    % (mem_used,))
                ram_ok = False
        vms.append(VM(uid=idx, vmid=vmid, name=name, node=node, status=status,
                      vcpus=float(rec["vcpus"]), mem_max=float(rec["mem_max"]),
                      cpu_usage=float(cpu_usage) if cpu_ok and status == "running" else None,
                      mem_used=float(mem_used) if ram_ok and status == "running" else None,
                      cpu_ok=cpu_ok, ram_ok=ram_ok))

    # pinning rules: anything we cannot vouch for is never proposed for migration
    by_id: Dict[Any, List[VM]] = {}
    for vm in vms:
        by_id.setdefault(vm.vmid, []).append(vm)
    for vmid, group in by_id.items():
        if len(group) > 1:
            where = ", ".join(v.node for v in group)
            bad("vm", vmid, "duplicate vmid on different nodes (%s); load counted on each claimed node, "
                "VM pinned (never migrated) until the inventory is fixed" % where)
            for v in group:
                v.pin_reason = "duplicate vmid"
    for vm in vms:
        if vm.running and not (vm.cpu_ok and vm.ram_ok) and vm.pin_reason is None:
            vm.pin_reason = "unverified metrics"
        if not nodes[vm.node].mem_valid and vm.pin_reason is None:
            vm.pin_reason = "host has invalid mem_total"
    return Cluster(name=str(data.get("cluster", "unknown")),
                   collected_at=data.get("collected_at") if isinstance(data.get("collected_at"), str) else None,
                   source=data.get("source") if isinstance(data.get("source"), str) else None,
                   nodes=nodes, vms=vms)


# --------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------
def add_vm(load: NodeLoad, vm: VM, sign: int = 1) -> None:
    """Add (sign=1) or remove (sign=-1) a running VM from a node load."""
    load.running_vms += sign
    load.vcpu_alloc += sign * vm.vcpus
    load.mem_alloc += sign * vm.mem_max
    if vm.cpu_ok:
        load.cpu_used += sign * vm.vcpus * (vm.cpu_usage or 0.0)
    else:
        load.cpu_unverified += sign * vm.vcpus
    if vm.ram_ok:
        load.ram_used += sign * (vm.mem_used or 0.0)
    else:
        load.ram_unverified += sign * vm.mem_max


def compute_loads(cluster: Cluster) -> Dict[str, NodeLoad]:
    loads = {name: NodeLoad() for name in cluster.nodes}
    for vm in cluster.vms:
        if vm.running:
            add_vm(loads[vm.node], vm)
    return loads


def _pct(num: float, den: float) -> float:
    return num / den * 100.0 if den else 0.0


def node_metrics(node: Node, load: NodeLoad) -> Dict[str, Optional[float]]:
    """Formulas (all VM sums are over *running* VMs only):
    cpu_pct        = sum(vcpus * cpu_usage) / cpu_cores * 100
    ram_pct        = sum(mem_used) / mem_total * 100
    overcommit     = sum(vcpus) / cpu_cores
    mem_alloc_pct  = sum(mem_max) / mem_total * 100
    *_worst        = same, but untrusted records counted at worst case
    """
    mem_ok = node.mem_valid
    return {
        "cpu_cores_used": load.cpu_used,
        "cpu_pct": _pct(load.cpu_used, node.cpu_cores),
        "cpu_pct_worst": _pct(load.cpu_used + load.cpu_unverified, node.cpu_cores),
        "ram_used_bytes": load.ram_used,
        "ram_pct": _pct(load.ram_used, node.mem_total) if mem_ok else None,
        "ram_pct_worst": _pct(load.ram_used + load.ram_unverified, node.mem_total) if mem_ok else None,
        "vcpu_allocated": load.vcpu_alloc,
        "overcommit": load.vcpu_alloc / node.cpu_cores,
        "mem_alloc_pct": _pct(load.mem_alloc, node.mem_total) if mem_ok else None,
    }


def _checks(m: Dict[str, Optional[float]], th: Thresholds) -> List[Tuple[str, Optional[float], float]]:
    return [("cpu", m["cpu_pct"], th.cpu), ("ram", m["ram_pct"], th.ram),
            ("overcommit", m["overcommit"], th.overcommit)]


def classify(node: Node, load: NodeLoad, th: Thresholds) -> Tuple[str, List[str]]:
    """OVERLOADED when any metric is strictly greater than its threshold;
    WARNING when any metric >= warn_ratio * threshold; otherwise NORMAL."""
    if node.state == "offline":
        return HEALTH_OFFLINE, ["node is offline"]
    if node.state != "online":
        return HEALTH_UNKNOWN, ["node status unknown"]
    if not node.mem_valid:
        return HEALTH_UNKNOWN, ["mem_total invalid, RAM utilisation cannot be computed"]
    m = node_metrics(node, load)
    over, warn = [], []
    for label, value, thr in _checks(m, th):
        if value is None:
            continue
        if value > thr:
            over.append("%s %.1f > %.1f" % (label, value, thr))
        elif value >= th.warn_ratio * thr:
            warn.append("%s %.1f >= %.1f%% of threshold" % (label, value, th.warn_ratio * 100))
    if over:
        return HEALTH_OVERLOADED, over
    if warn:
        return HEALTH_WARNING, warn
    return HEALTH_NORMAL, []


def excess(node: Node, load: NodeLoad, th: Thresholds) -> float:
    """Sum of normalised overshoot over the thresholds (0 = not overloaded)."""
    m = node_metrics(node, load)
    return sum(max(0.0, (v - thr) / thr) for _, v, thr in _checks(m, th) if v is not None)


def dest_accepts(node: Node, load: NodeLoad, vm: VM, th: Thresholds) -> Optional[str]:
    """Return None if `node` can take `vm` and stay NORMAL, else the blocking reason.

    Uses worst-case numbers for untrusted VMs already on the destination, and
    additionally limits sum(mem_max) so RAM cannot be exhausted if guests grow.
    """
    if node.state != "online" or not node.mem_valid:
        return "destination not online / invalid data"
    cpu = _pct(load.cpu_used + load.cpu_unverified + vm.vcpus * (vm.cpu_usage or 0.0), node.cpu_cores)
    ram = _pct(load.ram_used + load.ram_unverified + (vm.mem_used or 0.0), node.mem_total)
    oc = (load.vcpu_alloc + vm.vcpus) / node.cpu_cores
    alloc = _pct(load.mem_alloc + vm.mem_max, node.mem_total)
    w = th.warn_ratio
    if not cpu < w * th.cpu:
        return "cpu would reach %.1f%% (limit < %.1f%%)" % (cpu, w * th.cpu)
    if not ram < w * th.ram:
        return "ram would reach %.1f%% (limit < %.1f%%)" % (ram, w * th.ram)
    if not oc < w * th.overcommit:
        return "overcommit would reach %.2f (limit < %.2f)" % (oc, w * th.overcommit)
    if alloc > th.mem_alloc:
        return "allocated RAM would reach %.1f%% of host (limit %.1f%%)" % (alloc, th.mem_alloc)
    return None


# --------------------------------------------------------------------------
# Migration planner
# --------------------------------------------------------------------------
@dataclass
class Move:
    vm: VM
    src: str
    dst: str


def _health_map(cluster: Cluster, loads: Dict[str, NodeLoad], th: Thresholds) -> Dict[str, str]:
    return {n: classify(cluster.nodes[n], loads[n], th)[0] for n in cluster.nodes}


def _candidate_moves(cluster: Cluster, loads: Dict[str, NodeLoad], placement: Dict[int, str],
                     moved: set, th: Thresholds) -> List[Tuple[Tuple, Move]]:
    health = _health_map(cluster, loads, th)
    sources = [n for n, h in health.items() if h == HEALTH_OVERLOADED]
    out: List[Tuple[Tuple, Move]] = []
    for vm in cluster.vms:
        src = placement[vm.uid]
        if src not in sources or vm.uid in moved or not vm.movable:
            continue
        before = excess(cluster.nodes[src], loads[src], th)
        trial_src = dataclasses.replace(loads[src])
        add_vm(trial_src, vm, -1)
        after = excess(cluster.nodes[src], trial_src, th)
        if after >= before - 1e-12:
            continue  # does not help the source
        for dst, node in cluster.nodes.items():
            if dst == src or health[dst] != HEALTH_NORMAL:
                continue
            if dest_accepts(node, loads[dst], vm, th) is not None:
                continue
            trial_dst = dataclasses.replace(loads[dst])
            add_vm(trial_dst, vm)
            dm = node_metrics(node, trial_dst)
            dst_pressure = max(dm["cpu_pct"] / th.cpu, (dm["ram_pct"] or 0) / th.ram,
                               dm["overcommit"] / th.overcommit)
            score = (round(after, 9), vm.mem_used or 0.0, str(vm.vmid), round(dst_pressure, 9), dst)
            out.append((score, Move(vm, src, dst)))
    out.sort(key=lambda t: t[0])
    return out


class _Budget:
    """Bounds the search so the tool always terminates quickly."""

    def __init__(self, limit: int) -> None:
        self.left = limit
        self.exhausted = False
        self.failed: Dict[frozenset, int] = {}   # state -> deepest remaining depth already refuted


def _search(cluster: Cluster, loads: Dict[str, NodeLoad], placement: Dict[int, str],
            moved: Dict[int, str], depth: int, th: Thresholds, budget: _Budget) -> Optional[List[Move]]:
    health = _health_map(cluster, loads, th)
    if HEALTH_OVERLOADED not in health.values():
        return []
    if depth == 0:
        return None
    key = frozenset(moved.items())                       # order of moves does not matter
    if budget.failed.get(key, -1) >= depth:
        return None
    for _, mv in _candidate_moves(cluster, loads, placement, set(moved), th)[: th.beam]:
        if budget.left <= 0:
            budget.exhausted = True
            return None
        budget.left -= 1
        new_loads = {k: dataclasses.replace(v) for k, v in loads.items()}
        add_vm(new_loads[mv.src], mv.vm, -1)
        add_vm(new_loads[mv.dst], mv.vm)
        new_place = dict(placement)
        new_place[mv.vm.uid] = mv.dst
        new_moved = dict(moved)
        new_moved[mv.vm.uid] = mv.dst
        rest = _search(cluster, new_loads, new_place, new_moved, depth - 1, th, budget)
        if rest is not None:
            return [mv] + rest
    if not budget.exhausted:
        budget.failed[key] = max(budget.failed.get(key, -1), depth)
    return None


def _capacity_shortfall(cluster: Cluster, loads: Dict[str, NodeLoad], th: Thresholds) -> Optional[str]:
    """Necessary condition: total load to shed must fit in the total destination headroom.

    If it does not, no plan can exist (for that resource), whatever VMs are chosen.
    Returns a human-readable reason, or None when the quick check cannot rule a plan out.
    """
    health = _health_map(cluster, loads, th)
    src = [n for n, h in health.items() if h == HEALTH_OVERLOADED]
    dst = [n for n, h in health.items() if h == HEALTH_NORMAL]
    if not dst:
        return "no destination node is NORMAL (online, valid data, below the warning level)"
    need = {"cpu_cores": 0.0, "ram_gib": 0.0, "vcpu": 0.0}
    room = {"cpu_cores": 0.0, "ram_gib": 0.0, "vcpu": 0.0}
    for n in src:
        sf = _shortfall(cluster, loads, n, th)
        need["cpu_cores"] += sf["cpu_cores_to_free"]
        need["ram_gib"] += sf["ram_gib_to_free"]
        need["vcpu"] += sf["vcpu_to_free"]
    for n in dst:
        hr = _headroom(cluster, loads, n, th)
        room["cpu_cores"] += hr["cpu_cores_free"]
        room["ram_gib"] += hr["ram_gib_free"]
        room["vcpu"] += hr["vcpu_free"]
    for k in need:
        if need[k] > room[k] + 1e-6:
            return "overloaded nodes must shed %.1f %s but all destinations together have only %.1f of headroom" % (
                need[k], k, room[k])
    return None


def plan_migrations(cluster: Cluster, th: Thresholds, search_budget: int = 20000) -> Dict[str, Any]:
    """Iterative-deepening, beam-limited DFS with memoisation.

    Finds a plan with the fewest migrations *within the search bounds*
    (th.max_migrations, th.beam, search_budget). It is a heuristic: it does not
    prove global optimality and may miss plans outside the beam. If none is
    found we report NO_FEASIBLE_PLAN instead of inventing one.
    """
    loads = compute_loads(cluster)
    health = _health_map(cluster, loads, th)
    overloaded = [n for n, h in health.items() if h == HEALTH_OVERLOADED]
    result: Dict[str, Any] = {"status": NO_ACTION, "reason": "no node exceeds the thresholds",
                              "migrations": [], "residual_overloaded": [], "preflight_checks": []}
    if not overloaded:
        return result

    def infeasible(reason: str) -> Dict[str, Any]:
        result["status"] = NO_FEASIBLE
        result["reason"] = reason
        result["residual_overloaded"] = [_shortfall(cluster, loads, n, th) for n in overloaded]
        result["destination_headroom"] = [_headroom(cluster, loads, n, th)
                                          for n, h in health.items() if h == HEALTH_NORMAL]
        return result

    quick = _capacity_shortfall(cluster, loads, th)
    if quick:
        return infeasible("no feasible plan: " + quick)
    placement = {vm.uid: vm.node for vm in cluster.vms}
    budget = _Budget(search_budget)
    plan: Optional[List[Move]] = None
    for depth in range(1, th.max_migrations + 1):
        plan = _search(cluster, loads, placement, {}, depth, th, budget)
        if plan is not None or budget.exhausted:
            break
    if plan is None:
        why = ("search budget exhausted before a plan was found (heuristic limit, not a proof of infeasibility)"
               if budget.exhausted else
               "no sequence of <= %d migrations clears every overloaded node while keeping every destination NORMAL"
               % th.max_migrations)
        return infeasible(why)

    cur = {k: dataclasses.replace(v) for k, v in loads.items()}
    migrations = []
    for mv in plan:
        s_before = _brief(cluster.nodes[mv.src], cur[mv.src])
        d_before = _brief(cluster.nodes[mv.dst], cur[mv.dst])
        add_vm(cur[mv.src], mv.vm, -1)
        add_vm(cur[mv.dst], mv.vm)
        migrations.append({
            "vmid": mv.vm.vmid, "name": mv.vm.name, "from": mv.src, "to": mv.dst,
            "vcpus": int(mv.vm.vcpus), "cpu_cores_used": round(mv.vm.vcpus * mv.vm.cpu_usage, 3),
            "mem_used_gib": round(mv.vm.mem_used / GIB, 2), "mem_max_gib": round(mv.vm.mem_max / GIB, 2),
            "source": {"before": s_before, "after": _brief(cluster.nodes[mv.src], cur[mv.src])},
            "destination": {"before": d_before, "after": _brief(cluster.nodes[mv.dst], cur[mv.dst])},
            "preflight_required": True,
        })
    result.update(status=PLAN_FOUND, migrations=migrations, loads_after=cur,
                  reason="plan clears all overloaded nodes using %d migration(s)" % len(plan))
    result["preflight_checks"] = PREFLIGHT_CHECKS
    return result


PREFLIGHT_CHECKS = [
    "Shared storage (or storage migration plan) reachable from the destination node",
    "CPU model/flags compatible between source and destination (or a generic CPU type is set)",
    "Same bridges/VLANs/firewall rules available on the destination",
    "No local disks, PCI/USB passthrough or other migration blockers on the VM",
    "HA group/affinity/anti-affinity rules allow the move",
    "Migration network bandwidth/latency acceptable for the mem_used to transfer; schedule outside peak",
    "Destination metrics re-checked live immediately before migrating (this plan uses a stale snapshot)",
]


def _brief(node: Node, load: NodeLoad) -> Dict[str, Any]:
    m = node_metrics(node, load)
    return {"cpu_pct": _r(m["cpu_pct"]), "ram_pct": _r(m["ram_pct"]), "overcommit": _r(m["overcommit"], 2)}


def _shortfall(cluster: Cluster, loads: Dict[str, NodeLoad], name: str, th: Thresholds) -> Dict[str, Any]:
    node, load = cluster.nodes[name], loads[name]
    m = node_metrics(node, load)
    return {
        "node": name,
        "cpu_cores_to_free": _r(max(0.0, load.cpu_used - th.cpu / 100 * node.cpu_cores), 2),
        "ram_gib_to_free": _r(max(0.0, load.ram_used - th.ram / 100 * node.mem_total) / GIB, 2),
        "vcpu_to_free": _r(max(0.0, load.vcpu_alloc - th.overcommit * node.cpu_cores), 1),
        "metrics": {k: _r(v) for k, v in m.items()},
    }


def _headroom(cluster: Cluster, loads: Dict[str, NodeLoad], name: str, th: Thresholds) -> Dict[str, Any]:
    node, load = cluster.nodes[name], loads[name]
    w = th.warn_ratio
    return {
        "node": name,
        "cpu_cores_free": _r(max(0.0, w * th.cpu / 100 * node.cpu_cores - load.cpu_used - load.cpu_unverified), 2),
        "ram_gib_free": _r(max(0.0, w * th.ram / 100 * node.mem_total - load.ram_used - load.ram_unverified) / GIB, 2),
        "vcpu_free": _r(max(0.0, w * th.overcommit * node.cpu_cores - load.vcpu_alloc), 1),
    }


def _r(x: Optional[float], nd: int = 1) -> Optional[float]:
    return None if x is None else round(x, nd)


# --------------------------------------------------------------------------
# Report assembly
# --------------------------------------------------------------------------
def node_report(cluster: Cluster, loads: Dict[str, NodeLoad], th: Thresholds) -> List[Dict[str, Any]]:
    rows = []
    for name, node in cluster.nodes.items():
        load = loads[name]
        health, reasons = classify(node, load, th)
        m = node_metrics(node, load)
        unverified = [vm.vmid for vm in cluster.vms
                      if vm.node == name and vm.running and not (vm.cpu_ok and vm.ram_ok)]
        stopped = [vm for vm in cluster.vms if vm.node == name and not vm.running]
        rows.append({
            "node": name, "state": node.state, "health": health, "reasons": reasons,
            "cpu_cores": node.cpu_cores,
            "mem_total_gib": _r(node.mem_total / GIB, 2),
            "mem_total_valid": node.mem_valid,
            "running_vms": load.running_vms,
            "cpu_cores_used": _r(m["cpu_cores_used"], 2),
            "cpu_pct": _r(m["cpu_pct"]), "cpu_pct_worst_case": _r(m["cpu_pct_worst"]),
            "ram_used_gib": _r(m["ram_used_bytes"] / GIB, 1),
            "ram_pct": _r(m["ram_pct"]), "ram_pct_worst_case": _r(m["ram_pct_worst"]),
            "vcpu_allocated": _r(m["vcpu_allocated"], 0),
            "vcpu_overcommit": _r(m["overcommit"], 2),
            "ram_allocated_pct": _r(m["mem_alloc_pct"]),
            "stopped_vms": len(stopped),
            "stopped_vcpus_not_counted": _r(sum(v.vcpus for v in stopped), 0),
            "unverified_vms": unverified,
        })
    return rows


def build_result(cluster: Cluster, th: Thresholds, diag: Diagnostics) -> Dict[str, Any]:
    loads = compute_loads(cluster)
    nodes = node_report(cluster, loads, th)
    plan = plan_migrations(cluster, th)
    after = plan.pop("loads_after", None)
    nodes_after = node_report(cluster, after, th) if after else None
    overloaded = [n["node"] for n in nodes if n["health"] == HEALTH_OVERLOADED]
    return {
        "cluster": {"name": cluster.name, "collected_at": cluster.collected_at, "source": cluster.source,
                    "nodes_total": len(cluster.nodes), "vms_total": len(cluster.vms),
                    "vms_running": sum(1 for v in cluster.vms if v.running)},
        "thresholds": {"cpu_pct": th.cpu, "ram_pct": th.ram, "vcpu_overcommit": th.overcommit,
                       "warn_ratio": th.warn_ratio, "dest_mem_alloc_pct": th.mem_alloc,
                       "max_migrations": th.max_migrations, "beam": th.beam,
                       "overloaded_when": "value > threshold (strict)",
                       "warning_when": "value >= warn_ratio * threshold",
                       "assumption": "operational assumptions, not official Proxmox limits"},
        "nodes": nodes,
        "overloaded_nodes": overloaded,
        "migration_plan": {
            "status": plan["status"], "reason": plan["reason"],
            "recommendation_only": True,
            "migrations": plan["migrations"],
            "residual_overloaded": plan.get("residual_overloaded", []),
            "destination_headroom": plan.get("destination_headroom", []),
            "preflight_checks": plan.get("preflight_checks", []),
            "algorithm": "iterative-deepening beam-limited DFS; heuristic, not proven globally optimal",
        },
        "nodes_after_plan": nodes_after,
        "warnings": diag.items,
        "summary": {"overloaded": len(overloaded), "migrations_proposed": len(plan["migrations"]),
                    "plan_status": plan["status"], "warnings": len(diag.items)},
    }


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------
_COLORS = {HEALTH_OVERLOADED: "31", HEALTH_WARNING: "33", HEALTH_NORMAL: "32",
           HEALTH_OFFLINE: "90", HEALTH_UNKNOWN: "35"}


def _table(headers: List[str], rows: List[List[str]], align: str,
           paint: Optional[Any] = None) -> str:
    """Fixed-width table. paint(row_index, padded_text) may colour the last column."""
    widths = [max(len(h), *(len(r[i]) for r in rows)) if rows else len(h) for i, h in enumerate(headers)]

    def fmt(cells: List[str], row_idx: Optional[int] = None) -> str:
        out = []
        for i, c in enumerate(cells):
            cell = c.ljust(widths[i]) if align[i] == "l" else c.rjust(widths[i])
            if paint is not None and row_idx is not None and i == len(cells) - 1:
                cell = paint(row_idx, cell)
            out.append(cell)
        return "| " + " | ".join(out) + " |"
    sep = "+-" + "-+-".join("-" * w for w in widths) + "-+"
    lines = [sep, fmt(headers), sep] + [fmt(r, i) for i, r in enumerate(rows)] + [sep]
    return "\n".join(lines)


def _f(x: Optional[float], nd: int = 1, suffix: str = "") -> str:
    return "n/a" if x is None else ("%.*f%s" % (nd, x, suffix))


def render_table(res: Dict[str, Any], color: bool = False) -> str:
    cl, th = res["cluster"], res["thresholds"]
    out = ["Cluster %s | snapshot %s | nodes=%d vms=%d (running %d)" % (
        cl["name"], cl["collected_at"] or "?", cl["nodes_total"], cl["vms_total"], cl["vms_running"]),
        "Thresholds: CPU>%g%%  RAM>%g%%  vCPU overcommit>%g:1  (WARNING from %g%% of threshold)  [assumptions]" % (
            th["cpu_pct"], th["ram_pct"], th["vcpu_overcommit"], th["warn_ratio"] * 100), ""]

    def health_cell(n: Dict[str, Any]) -> str:
        return n["health"] + ("*" if n["unverified_vms"] else "")

    def node_rows(nodes: List[Dict[str, Any]]) -> List[List[str]]:
        rows = []
        for n in nodes:
            total = _f(n["mem_total_gib"], 0) if n["mem_total_valid"] else "?"
            rows.append([n["node"], n["state"],
                         "%s/%g" % (_f(n["cpu_cores_used"], 1), n["cpu_cores"]), _f(n["cpu_pct"], 1, "%"),
                         "%s/%s" % (_f(n["ram_used_gib"], 0), total), _f(n["ram_pct"], 1, "%"),
                         "%s" % _f(n["vcpu_allocated"], 0), _f(n["vcpu_overcommit"], 2, ":1"), health_cell(n)])
        return rows

    hdr = ["Node", "State", "CPU cores used", "CPU%", "RAM used/total GiB", "RAM%", "vCPU", "Overcommit", "Health"]
    paint = None
    if color:
        paint = lambda i, cell: "\x1b[%sm%s\x1b[0m" % (_COLORS[res["nodes"][i]["health"]], cell)  # noqa: E731
    out.append(_table(hdr, node_rows(res["nodes"]), "llrrrrrrl", paint))
    out.append("* = node hosts running VMs with unverified metrics (see warnings); WARNING/NORMAL use trusted data only")
    for n in res["nodes"]:
        if n["health"] in (HEALTH_OVERLOADED, HEALTH_UNKNOWN):
            out.append("  - %s: %s" % (n["node"], "; ".join(n["reasons"])))
    out.append("")
    plan = res["migration_plan"]
    out.append("Migration plan: %s - %s" % (plan["status"], plan["reason"]))
    if plan["migrations"]:
        rows = []
        for m in plan["migrations"]:
            s, d = m["source"], m["destination"]
            rows.append([str(m["vmid"]), m["name"], m["from"], m["to"], str(m["vcpus"]), _f(m["mem_used_gib"], 1),
                         "%s->%s" % (_f(s["before"]["cpu_pct"]), _f(s["after"]["cpu_pct"])),
                         "%s->%s" % (_f(s["before"]["ram_pct"]), _f(s["after"]["ram_pct"])),
                         "%s->%s" % (_f(d["before"]["cpu_pct"]), _f(d["after"]["cpu_pct"])),
                         "%s->%s" % (_f(d["before"]["ram_pct"]), _f(d["after"]["ram_pct"]))])
        out.append(_table(["VMID", "Name", "From", "To", "vCPU", "RAM GiB", "Src CPU%", "Src RAM%",
                           "Dst CPU%", "Dst RAM%"], rows, "lllllrrrrr"))
        out.append("RECOMMENDATION ONLY - nothing was migrated. Run preflight checks first:")
        out.extend("  [ ] " + c for c in plan["preflight_checks"])
    for r in plan["residual_overloaded"]:
        out.append("  Needs more capacity: %s must free %s cores / %s GiB RAM / %s vCPU" % (
            r["node"], r["cpu_cores_to_free"], r["ram_gib_to_free"], r["vcpu_to_free"]))
    if res["warnings"]:
        out.append("")
        out.append("Data-quality warnings (%d, also on stderr):" % len(res["warnings"]))
        out.extend("  ! [%s %s] %s" % (w["scope"], w["id"], w["message"]) for w in res["warnings"])
    return "\n".join(out)


def render_json(res: Dict[str, Any]) -> str:
    return json.dumps(res, ensure_ascii=False, indent=2)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Analyse Proxmox cluster load and recommend live-migrations.")
    p.add_argument("--input", "-i", required=True, help="cluster snapshot JSON")
    p.add_argument("--format", "-f", choices=("table", "json"), default="table")
    p.add_argument("--cpu-threshold", type=float, default=80.0, help="%% of physical cores (default 80)")
    p.add_argument("--ram-threshold", type=float, default=85.0, help="%% of mem_total (default 85)")
    p.add_argument("--overcommit-threshold", type=float, default=4.0, help="vCPU:core ratio (default 4)")
    p.add_argument("--warn-ratio", type=float, default=0.9, help="WARNING at this fraction of a threshold (default 0.9)")
    p.add_argument("--mem-alloc-limit", type=float, default=100.0,
                   help="destination: sum(mem_max) must stay <= this %% of mem_total (default 100)")
    p.add_argument("--max-migrations", type=int, default=6)
    p.add_argument("--beam", type=int, default=8, help="candidate moves explored per search step")
    p.add_argument("--strict", action="store_true", help="treat any invalid record as fatal (exit 2)")
    p.add_argument("--quiet", "-q", action="store_true", help="do not print warnings on stderr")
    p.add_argument("--no-color", action="store_true")
    return p


def thresholds_from_args(a: argparse.Namespace) -> Thresholds:
    for label, val in (("cpu-threshold", a.cpu_threshold), ("ram-threshold", a.ram_threshold)):
        if not (0 < val <= 100):
            raise InputError("--%s must be in (0,100]" % label)
    if a.overcommit_threshold <= 0:
        raise InputError("--overcommit-threshold must be > 0")
    if not (0 < a.warn_ratio <= 1):
        raise InputError("--warn-ratio must be in (0,1]")
    if a.mem_alloc_limit <= 0:
        raise InputError("--mem-alloc-limit must be > 0")
    if a.max_migrations < 1 or a.beam < 1:
        raise InputError("--max-migrations and --beam must be >= 1")
    return Thresholds(a.cpu_threshold, a.ram_threshold, a.overcommit_threshold, a.warn_ratio,
                      a.mem_alloc_limit, a.max_migrations, a.beam)


def run(argv: Optional[List[str]] = None, stdout=None) -> int:
    stdout = stdout or sys.stdout
    args = build_parser().parse_args(argv)
    logging.basicConfig(stream=sys.stderr, format="%(levelname)s: %(message)s",
                        level=logging.ERROR if args.quiet else logging.WARNING, force=True)
    try:
        th = thresholds_from_args(args)
        diag = Diagnostics()
        cluster = validate_cluster(load_json(args.input), diag, strict=args.strict)
        result = build_result(cluster, th, diag)
    except InputError as exc:
        log.error("%s", exc)
        return EXIT_INPUT_ERROR
    except Exception as exc:  # last-resort guard: no traceback for users
        log.error("internal error: %s: %s", type(exc).__name__, exc)
        return EXIT_INTERNAL
    if args.format == "json":
        stdout.write(render_json(result) + "\n")
    else:
        color = (not args.no_color and hasattr(stdout, "isatty") and stdout.isatty()
                 and "NO_COLOR" not in os.environ)
        stdout.write(render_table(result, color) + "\n")
    return EXIT_NO_FEASIBLE if result["migration_plan"]["status"] == NO_FEASIBLE else EXIT_OK


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
