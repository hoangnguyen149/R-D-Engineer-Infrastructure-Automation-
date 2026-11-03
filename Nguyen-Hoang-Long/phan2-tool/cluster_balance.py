#!/usr/bin/env python3
"""Offline resource planner. Invalid records are excluded and reported; no Proxmox credentials or mutations."""
import argparse
import copy
import json
import math
import sys
from collections import Counter
from pathlib import Path

GIB = 1024 ** 3
DEFAULT = {'cpu': .80, 'ram': .85, 'overcommit': 4.0}


def number(v, minimum=0, maximum=None, integer=False):
    try:
        return (type(v) in (int, float) and math.isfinite(v) and v >= minimum
                and (maximum is None or v <= maximum)
                and (not integer or type(v) is int))
    except OverflowError:
        return False


def validate(data):
    """Invalid VM records are excluded; affected totals explicitly incomplete."""
    warnings, nodes, vms, tainted = [], {}, [], set()
    def warn(where, message):
        warnings.append({'record': where, 'message': message})
    if not isinstance(data, dict) or not isinstance(data.get('nodes'), list) or not isinstance(data.get('vms'), list):
        raise ValueError('root must be an object with nodes[] and vms[]')
    if not data['nodes']:
        raise ValueError('nodes[] must not be empty')
    node_ids = Counter(n.get('node') for n in data['nodes'] if isinstance(n, dict) and isinstance(n.get('node'), str))
    for i, n in enumerate(data['nodes']):
        where = f'nodes[{i}]'
        if not isinstance(n, dict):
            warn(where, 'record must be object'); continue
        name = n.get('node')
        if not isinstance(name, str) or not name or node_ids[name] != 1:
            warn(where, 'missing or duplicate node name'); continue
        reasons = []
        if n.get('status') not in ('online', 'offline'): reasons.append('status must be online/offline')
        if not number(n.get('cpu_cores'), 1, integer=True): reasons.append('cpu_cores must be positive integer')
        if not number(n.get('mem_total'), GIB, integer=True): reasons.append('mem_total must be integer bytes >= 1 GiB (sanity policy)')
        nodes[name] = dict(n, status=n.get('status') if isinstance(n.get('status'), str) else 'invalid', valid=not reasons)
        for reason in reasons: warn(f'{where} {name}', reason)
    ids = Counter(v.get('vmid') for v in data['vms'] if isinstance(v, dict) and type(v.get('vmid')) is int)
    for i, v in enumerate(data['vms']):
        where = f'vms[{i}]'
        if not isinstance(v, dict):
            warn(where, 'record must be object'); continue
        reasons = []
        vid, name = v.get('vmid'), v.get('node')
        if type(vid) is not int or vid <= 0: reasons.append('vmid must be positive integer')
        elif ids[vid] != 1: reasons.append('duplicate vmid: all copies excluded, no guessed owner')
        if not isinstance(name, str) or name not in nodes: reasons.append('unknown or invalid node reference')
        if v.get('status') not in ('running', 'stopped'): reasons.append('unsupported/missing VM status')
        if not number(v.get('vcpus'), 1, integer=True): reasons.append('vcpus must be positive integer')
        if not number(v.get('cpu_usage'), 0, 1): reasons.append('cpu_usage must be finite fraction in [0,1]')
        if not number(v.get('mem_max'), 1, integer=True): reasons.append('mem_max must be positive integer bytes')
        if not number(v.get('mem_used'), 0, integer=True): reasons.append('mem_used must be nonnegative integer bytes')
        elif number(v.get('mem_max'), 1) and v['mem_used'] > v['mem_max']: reasons.append('mem_used exceeds mem_max')
        if v.get('status') == 'stopped' and (v.get('mem_used') != 0 or v.get('cpu_usage') != 0): reasons.append('stopped VM has nonzero usage')
        if isinstance(name, str) and name in nodes and nodes[name].get('status') == 'offline' and v.get('status') == 'running':
            reasons.append('running VM reported on offline node')
        if reasons:
            if isinstance(name, str): tainted.add(name)
            for reason in reasons: warn(f'{where} vmid={vid} node={name}', reason)
        else:
            vms.append(copy.deepcopy(v))
    return nodes, vms, tainted, warnings


def loads(nodes, vms, tainted, limits):
    result = {}
    for name, n in sorted(nodes.items()):
        running = [v for v in vms if v['node'] == name and v['status'] == 'running']
        cpu = sum(v['vcpus'] * v['cpu_usage'] for v in running)
        ram = sum(v['mem_used'] for v in running)
        vc = sum(v['vcpus'] for v in running)
        totalvc = sum(v['vcpus'] for v in vms if v['node'] == name)
        ratios = {'cpu': cpu/n['cpu_cores'], 'ram': ram/n['mem_total'], 'overcommit': vc/n['cpu_cores']} if n['valid'] else None
        exceed = [k for k in limits if ratios and ratios[k] > limits[k] + 1e-12]
        complete = n['valid'] and name not in tainted
        result[name] = {'status': n['status'], 'complete': complete, 'running_vms': len(running),
                        'cpu_cores_used': cpu, 'ram_bytes_used': ram, 'running_vcpus': vc,
                        'configured_vcpus_all_valid_records': totalvc, 'ratios': ratios,
                        'overloaded_dimensions': exceed,
                        'assessment': ('offline' if n['status'] == 'offline' else
                                       'overloaded' if exceed and complete else
                                       'overloaded_lower_bound' if exceed else
                                       'unknown' if not complete else 'within_thresholds')}
    return result


def excess(state, limits):
    return sum(max(0, v['ratios'][k]/limits[k]-1) for v in state.values()
               if v['status'] == 'online' and v['ratios'] for k in limits)


def plan(nodes, vms, limits, tainted=frozenset()):
    """Deterministic greedy search, each move lowers excess; never certifies failure.

    `vms` holds only valid records. A node in `tainted` lost at least one record, so its
    real load is unknown (the computed value is a lower bound): it may give VMs away but
    never receives one, because "target stays below threshold" cannot be guaranteed.
    """
    work = copy.deepcopy(vms)
    moves, moved = [], set()
    for _ in range(len(vms)):
        current = loads(nodes, work, tainted, limits)
        score = excess(current, limits)
        if score <= 1e-12:
            return moves, current, 'balanced'
        candidates = []
        for v in sorted(work, key=lambda v: v['vmid']):
            src = v['node']
            if v['status'] != 'running' or v['vmid'] in moved or not current[src]['overloaded_dimensions']:
                continue
            for dst, node in sorted(nodes.items()):
                if dst == src or node['status'] != 'online': continue
                if not node['valid'] or dst in tainted: continue  # unknown/invalid target capacity
                # Reserve full incoming guest allocation while source remains present.
                if current[dst]['ram_bytes_used'] + v['mem_max'] > node['mem_total'] * limits['ram']:
                    continue
                v['node'] = dst
                after = loads(nodes, work, tainted, limits)
                v['node'] = src
                newscore = excess(after, limits)
                if not after[dst]['overloaded_dimensions'] and newscore < score-1e-12:
                    candidates.append((newscore, v['mem_max'], v['vmid'], dst, src, after))
        if not candidates:
            return moves, current, 'unresolved'
        _, _, vid, dst, src, after = min(candidates, key=lambda x: x[:4])
        vm = next(v for v in work if v['vmid'] == vid)
        vm['node'] = dst
        moved.add(vid)
        moves.append({'vmid': vid, 'from': src, 'to': dst,
                      'incoming_ram_reservation_bytes': vm['mem_max'],
                      'source_load_is_lower_bound': src in tainted,
                      'target_after': after[dst]})
    final = loads(nodes, work, tainted, limits)
    return moves, final, 'balanced' if excess(final, limits) <= 1e-12 else 'unresolved'


def analyze(data, limits=None):
    limits = dict(DEFAULT if limits is None else limits)
    if set(limits) != set(DEFAULT) or any(not number(v, 1e-9) for v in limits.values()) or limits['cpu'] > 1 or limits['ram'] > 1:
        raise ValueError('CPU/RAM thresholds must be (0,1]; overcommit > 0')
    nodes, vms, tainted, warnings = validate(data)
    before = loads(nodes, vms, tainted, limits)
    report = {'cluster': data.get('cluster'), 'collected_at': data.get('collected_at'),
              'thresholds': limits, 'warnings': warnings,
              'excluded_records': len({w['record'] for w in warnings}),
              'before': before, 'plan': [], 'after': before, 'plan_status': 'blocked_invalid_data',
              'resource_plan_complete': False, 'production_ready': False,
              'notes': ['Read-only snapshot estimate, excludes host overhead and future load.',
                        'Verify fresh telemetry, storage, CPU compatibility, network, HA/affinity, locks and migration overhead before execution.']}
    # Only block when nothing can be evaluated at all (no valid online node).
    if any(n['valid'] and n['status'] == 'online' for n in nodes.values()):
        moves, after, status = plan(nodes, vms, limits, tainted)
        if warnings:
            # Never claim "balanced" while records are missing: loads of affected nodes are lower bounds.
            status = 'partial_plan_with_excluded_records' if status == 'balanced' else 'unresolved_with_excluded_records'
            report['notes'].append('Invalid records were excluded and are listed in warnings. Nodes with excluded records '
                                   'show LOWER-BOUND load and are never used as migration targets; re-check them after fixing the data.')
        report.update(plan=moves, after=after, plan_status=status,
                      resource_plan_complete=status == 'balanced')
    return report


def table(report):
    lines = [f"Cluster: {report.get('cluster')} | Plan: {report['plan_status']}",
             'Metrics: valid records only; incomplete totals are LOWER BOUNDS, not healthy.',
             f"{'Node':18} {'State':8} {'CPU cores':>10} {'CPU %':>8} {'RAM GiB':>10} {'RAM %':>8} {'vCPU/core':>10} Assessment"]
    for name, r in report['before'].items():
        ratios = r['ratios']
        nums = (f"{ratios['cpu']*100:8.2f} {r['ram_bytes_used']/GIB:10.2f} {ratios['ram']*100:8.2f} {ratios['overcommit']:10.2f}" if ratios else f"{'N/A':>8} {r['ram_bytes_used']/GIB:10.2f} {'N/A':>8} {'N/A':>10}")
        lines.append(f"{name:18} {r['status']:8} {r['cpu_cores_used']:10.3f} {nums} {r['assessment']}")
    if report.get('warnings'):
        lines.append(f"EXCLUDED RECORDS: {report['excluded_records']} (details in warnings/stderr). Nodes marked unknown/lower_bound lack data and are never migration targets.")
    for m in report['plan']:
        flag = ' [source load is a lower bound]' if m.get('source_load_is_lower_bound') else ''
        lines.append(f"MOVE VM {m['vmid']}: {m['from']} -> {m['to']}{flag}")
    if report['plan']:
        lines.append('AFTER (projected): node CPU% RAM% vCPU/core')
        for name, r in report['after'].items():
            q = r['ratios']
            if q:
                lines.append(f"{name}: {q['cpu']*100:.2f}% {q['ram']*100:.2f}% {q['overcommit']:.2f} ({r['assessment']})")
    lines.append('Production ready: false (resource suggestion only; no migration executed)')
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--format', choices=['table', 'json'], default='table')
    parser.add_argument('--cpu-threshold', type=float, default=.8)
    parser.add_argument('--ram-threshold', type=float, default=.85)
    parser.add_argument('--overcommit-threshold', type=float, default=4)
    args = parser.parse_args(argv)
    try:
        data = json.loads(args.input.read_text(encoding='utf-8'), parse_constant=lambda v: (_ for _ in ()).throw(ValueError(f'invalid JSON constant {v}')))
        report = analyze(data, {'cpu': args.cpu_threshold, 'ram': args.ram_threshold, 'overcommit': args.overcommit_threshold})
    except (OSError, UnicodeError, ValueError, RecursionError) as exc:
        error = {'plan_status': 'input_error', 'error': str(exc), 'plan': [], 'resource_plan_complete': False, 'production_ready': False}
        print(json.dumps(error, ensure_ascii=False) if args.format == 'json' else f"ERROR: {exc}")
        print(f'ERROR: {exc}', file=sys.stderr)
        return 2
    for w in report['warnings']: print(f"WARNING {w['record']}: {w['message']}", file=sys.stderr)
    print(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) if args.format == 'json' else table(report))
    status = report['plan_status']
    if status == 'blocked_invalid_data': return 2
    if status == 'balanced': return 0
    if status == 'partial_plan_with_excluded_records': return 4
    return 3


if __name__ == '__main__':
    sys.exit(main())
