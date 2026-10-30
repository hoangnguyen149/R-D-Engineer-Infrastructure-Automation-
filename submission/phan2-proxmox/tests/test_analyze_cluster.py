"""Unit tests for analyze_cluster.py (standard library only).

Run:  python3 -m unittest discover -s tests -v      (from phan2-proxmox/)

Fixtures below are SYNTHETIC. Only RealSnapshotTest reads the real snapshot.
"""
import io
import json
import os
import random
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import analyze_cluster as ac  # noqa: E402

GIB = 1024 ** 3


def node(name, cores=10, mem_gib=100, status="online"):
    return {"node": name, "status": status, "cpu_cores": cores, "mem_total": mem_gib * GIB}


def vm(vmid, on, vcpus=2, cpu=0.5, mem_max_gib=10, mem_used_gib=5, status="running"):
    return {"vmid": vmid, "name": "vm%s" % vmid, "node": on, "status": status, "vcpus": vcpus,
            "cpu_usage": cpu, "mem_max": mem_max_gib * GIB, "mem_used": mem_used_gib * GIB}


def load_cluster(nodes, vms, strict=False):
    diag = ac.Diagnostics()
    with redirect_stderr(io.StringIO()):
        cluster = ac.validate_cluster({"cluster": "t", "nodes": nodes, "vms": vms}, diag, strict)
    return cluster, diag


def analyse(nodes, vms, **kw):
    cluster, diag = load_cluster(nodes, vms)
    return cluster, ac.build_result(cluster, ac.Thresholds(**kw), diag)


def health_of(res, name):
    return next(n for n in res["nodes"] if n["node"] == name)["health"]


class MetricsTest(unittest.TestCase):
    def test_cpu_cores_and_percent(self):
        # 4 vCPU @ 50% = 2 cores ; 2 vCPU @ 100% = 2 cores ; 10 cores total -> 40%
        cluster, _ = load_cluster([node("a")], [vm(1, "a", 4, 0.5), vm(2, "a", 2, 1.0)])
        m = ac.node_metrics(cluster.nodes["a"], ac.compute_loads(cluster)["a"])
        self.assertAlmostEqual(m["cpu_cores_used"], 4.0)
        self.assertAlmostEqual(m["cpu_pct"], 40.0)

    def test_ram_percent_uses_mem_used_not_mem_max(self):
        cluster, _ = load_cluster([node("a", mem_gib=100)],
                                  [vm(1, "a", mem_max_gib=40, mem_used_gib=10), vm(2, "a", mem_max_gib=40, mem_used_gib=20)])
        m = ac.node_metrics(cluster.nodes["a"], ac.compute_loads(cluster)["a"])
        self.assertAlmostEqual(m["ram_pct"], 30.0)
        self.assertAlmostEqual(m["mem_alloc_pct"], 80.0)

    def test_overcommit_counts_running_only(self):
        cluster, _ = load_cluster([node("a", cores=8)],
                                  [vm(1, "a", 8), vm(2, "a", 8), vm(3, "a", 16, status="stopped", cpu=0, mem_used_gib=0)])
        m = ac.node_metrics(cluster.nodes["a"], ac.compute_loads(cluster)["a"])
        self.assertAlmostEqual(m["overcommit"], 2.0)

    def test_stopped_vm_does_not_load_node(self):
        cluster, _ = load_cluster([node("a")], [vm(1, "a", 8, 1.0, status="stopped")])
        m = ac.node_metrics(cluster.nodes["a"], ac.compute_loads(cluster)["a"])
        self.assertEqual(m["cpu_pct"], 0.0)
        self.assertEqual(m["vcpu_allocated"], 0.0)


class ClassificationTest(unittest.TestCase):
    TH = ac.Thresholds()

    def _health(self, cpu_cores_used, cores=100):
        # one VM with cores_used = vcpus*cpu on a `cores`-core node
        cluster, _ = load_cluster([node("a", cores=cores)], [vm(1, "a", vcpus=cpu_cores_used, cpu=1.0, mem_used_gib=1)])
        return ac.classify(cluster.nodes["a"], ac.compute_loads(cluster)["a"], self.TH)[0]

    def test_boundary_equal_threshold_is_not_overloaded(self):
        self.assertEqual(self._health(80), ac.HEALTH_WARNING)      # exactly 80% -> '>' is strict

    def test_just_above_threshold_is_overloaded(self):
        cluster, _ = load_cluster([node("a", cores=1000)], [vm(1, "a", vcpus=801, cpu=1.0, mem_used_gib=1)])
        self.assertEqual(ac.classify(cluster.nodes["a"], ac.compute_loads(cluster)["a"], self.TH)[0], ac.HEALTH_OVERLOADED)

    def test_warning_boundary_is_inclusive(self):
        self.assertEqual(self._health(72), ac.HEALTH_WARNING)      # 0.9 * 80
        self.assertEqual(self._health(71), ac.HEALTH_NORMAL)

    def test_overcommit_threshold(self):
        cluster, _ = load_cluster([node("a", cores=10)], [vm(1, "a", vcpus=41, cpu=0.0, mem_used_gib=1)])
        self.assertEqual(ac.classify(cluster.nodes["a"], ac.compute_loads(cluster)["a"], self.TH)[0], ac.HEALTH_OVERLOADED)

    def test_ram_threshold(self):
        cluster, _ = load_cluster([node("a", mem_gib=100)], [vm(1, "a", mem_max_gib=90, mem_used_gib=86, cpu=0.0)])
        self.assertEqual(ac.classify(cluster.nodes["a"], ac.compute_loads(cluster)["a"], self.TH)[0], ac.HEALTH_OVERLOADED)

    def test_offline_and_unknown(self):
        cluster, _ = load_cluster([node("a", status="offline"), node("b", status="maintenance")], [])
        loads = ac.compute_loads(cluster)
        self.assertEqual(ac.classify(cluster.nodes["a"], loads["a"], self.TH)[0], ac.HEALTH_OFFLINE)
        self.assertEqual(ac.classify(cluster.nodes["b"], loads["b"], self.TH)[0], ac.HEALTH_UNKNOWN)

    def test_custom_threshold_changes_classification(self):
        cluster, _ = load_cluster([node("a")], [vm(1, "a", 4, 1.0, mem_used_gib=1)])  # 40% cpu
        low = ac.Thresholds(cpu=30)
        self.assertEqual(ac.classify(cluster.nodes["a"], ac.compute_loads(cluster)["a"], low)[0], ac.HEALTH_OVERLOADED)


class PlannerTest(unittest.TestCase):
    def hot_cold(self, **vm_kw):
        nodes = [node("hot", cores=10), node("cold", cores=10)]
        vms = [vm(1, "hot", 4, 1.0, 10, 10), vm(2, "hot", 4, 1.0, 10, 10), vm(3, "cold", 1, 0.1, 5, 1)]
        return nodes, vms

    def test_simple_plan_moves_vm_to_cold_node(self):
        _, res = analyse(*self.hot_cold())          # hot: 8/10 cores = 80% -> not >80, so push it over
        nodes = [node("hot", cores=10), node("cold", cores=10)]
        vms = [vm(1, "hot", 5, 1.0, 10, 10), vm(2, "hot", 4, 1.0, 10, 10), vm(3, "cold", 1, 0.1, 5, 1)]
        _, res = analyse(nodes, vms)                # 9/10 = 90%
        plan = res["migration_plan"]
        self.assertEqual(plan["status"], ac.PLAN_FOUND)
        self.assertEqual({(m["from"], m["to"]) for m in plan["migrations"]}, {("hot", "cold")})

    def test_no_action_when_nothing_overloaded(self):
        _, res = analyse(*self.hot_cold())
        self.assertEqual(res["migration_plan"]["status"], ac.NO_ACTION)
        self.assertEqual(res["migration_plan"]["migrations"], [])

    def _hot(self, extra_nodes, extra_vms=()):
        nodes = [node("hot", cores=10)] + extra_nodes
        vms = [vm(1, "hot", 9, 1.0, 10, 10)] + list(extra_vms)
        return analyse(nodes, vms)[1]

    def test_never_migrates_to_offline_node(self):
        res = self._hot([node("off", cores=100, status="offline")])
        self.assertEqual(res["migration_plan"]["status"], ac.NO_FEASIBLE)

    def test_never_migrates_stopped_vm(self):
        nodes = [node("hot", cores=10), node("cold", cores=10)]
        vms = [vm(1, "hot", 9, 1.0, 10, 10), vm(2, "hot", 8, 0, 80, 0, status="stopped")]
        res = analyse(nodes, vms)[1]
        moved = [m["vmid"] for m in res["migration_plan"]["migrations"]]
        self.assertNotIn(2, moved)

    def test_destination_must_not_become_warning(self):
        # moving vm1 (9 cores) onto a node with 10 cores would give 90% -> overloaded
        res = self._hot([node("small", cores=10)])
        self.assertEqual(res["migration_plan"]["status"], ac.NO_FEASIBLE)

    def test_memory_allocation_limit_blocks_destination(self):
        nodes = [node("hot", cores=10, mem_gib=100), node("cold", cores=100, mem_gib=100)]
        vms = [vm(1, "hot", 9, 1.0, 60, 10), vm(2, "cold", 1, 0.1, 50, 1)]    # alloc cold would be 110%
        res = analyse(nodes, vms)[1]
        self.assertEqual(res["migration_plan"]["status"], ac.NO_FEASIBLE)
        res2 = analyse(nodes, vms, mem_alloc=120.0)[1]
        self.assertEqual(res2["migration_plan"]["status"], ac.PLAN_FOUND)

    def test_no_feasible_plan_reports_shortfall_and_no_migrations(self):
        nodes = [node("a", cores=10), node("b", cores=10)]
        vms = [vm(1, "a", 9, 1.0, 10, 10), vm(2, "b", 9, 1.0, 10, 10)]
        res = analyse(nodes, vms)[1]
        plan = res["migration_plan"]
        self.assertEqual(plan["status"], ac.NO_FEASIBLE)
        self.assertEqual(plan["migrations"], [])
        self.assertEqual({r["node"] for r in plan["residual_overloaded"]}, {"a", "b"})
        self.assertGreater(plan["residual_overloaded"][0]["cpu_cores_to_free"], 0)

    def test_two_step_plan_when_one_move_is_not_enough(self):
        nodes = [node("hot", cores=10), node("c1", cores=20), node("c2", cores=20)]
        vms = [vm(i, "hot", 2, 1.0, 5, 5) for i in range(1, 7)] + [vm(9, "c1", 1, 0.0, 1, 1), vm(10, "c2", 1, 0.0, 1, 1)]
        res = analyse(nodes, vms)[1]            # 12/10 cores = 120%; each VM sheds 20% -> two VMs must go (-> 80%)
        plan = res["migration_plan"]
        self.assertEqual(plan["status"], ac.PLAN_FOUND)
        self.assertEqual(len(plan["migrations"]), 2)
        self.assertEqual(len({m["vmid"] for m in plan["migrations"]}), 2)

    def test_capacity_precheck_explains_infeasibility(self):
        nodes = [node("a", cores=10), node("b", cores=10)]
        vms = [vm(1, "a", 9, 1.0, 10, 10), vm(2, "b", 9, 1.0, 10, 10)]
        res = analyse(nodes, vms)[1]
        self.assertIn("no destination", res["migration_plan"]["reason"])

    def test_search_budget_exhaustion_is_reported_not_faked(self):
        cluster, _ = load_cluster([node("hot", cores=10), node("c", cores=100)],
                                  [vm(i, "hot", 2, 1.0, 5, 5) for i in range(1, 8)])
        plan = ac.plan_migrations(cluster, ac.Thresholds(), search_budget=0)
        self.assertEqual(plan["status"], ac.NO_FEASIBLE)
        self.assertEqual(plan["migrations"], [])
        self.assertIn("budget", plan["reason"])

    def test_pinned_vms_are_not_moved(self):
        nodes = [node("hot", cores=10), node("cold", cores=10)]
        bad = vm(1, "hot", 9, 1.0, 10, 10); bad["cpu_usage"] = 95.0       # untrusted -> pinned
        res = analyse(nodes, [bad])[1]
        self.assertEqual(res["migration_plan"]["migrations"], [])

    def test_plan_is_deterministic(self):
        nodes = [node("hot", cores=20), node("c1", cores=20), node("c2", cores=20)]
        vms = [vm(i, "hot", 6, 1.0, 5, 5) for i in (1, 2, 3)]
        a = ac.render_json(analyse(nodes, vms)[1])
        b = ac.render_json(analyse(nodes, vms)[1])
        self.assertEqual(a, b)

    def test_random_clusters_satisfy_invariants(self):
        rng = random.Random(1234)
        th = ac.Thresholds()
        found = 0
        for _ in range(150):
            nodes = [node("n%d" % i, cores=rng.choice([16, 32, 64]), mem_gib=rng.choice([128, 256, 512]),
                          status=rng.choice(["online"] * 6 + ["offline"])) for i in range(rng.randint(2, 6))]
            vms = []
            for vid in range(rng.randint(5, 40)):
                n = rng.choice(nodes)["node"]
                mm = rng.choice([8, 16, 32, 64])
                vms.append(vm(vid, n, rng.choice([1, 2, 4, 8, 16]), round(rng.random(), 3), mm,
                              round(mm * rng.random(), 2), status=rng.choice(["running"] * 8 + ["stopped"])))
            cluster, res = analyse(nodes, vms)
            plan = res["migration_plan"]
            if plan["status"] != ac.PLAN_FOUND:
                self.assertEqual(plan["migrations"], [])
                continue
            found += 1
            self.assert_plan_valid(cluster, plan, th)
        self.assertGreater(found, 5, "random generator should produce some feasible plans")

    def assert_plan_valid(self, cluster, plan, th):
        placement = {v.vmid: v.node for v in cluster.vms}
        by_id = {v.vmid: v for v in cluster.vms}
        seen = set()
        for m in plan["migrations"]:
            v = by_id[m["vmid"]]
            self.assertTrue(v.running, "stopped VM migrated")
            self.assertNotIn(m["vmid"], seen, "VM moved twice")
            seen.add(m["vmid"])
            self.assertNotEqual(m["from"], m["to"])
            self.assertEqual(cluster.nodes[m["to"]].state, "online")
            self.assertEqual(placement[m["vmid"]], m["from"])
            placement[m["vmid"]] = m["to"]
        # recompute everything from scratch after applying the plan
        loads = {n: ac.NodeLoad() for n in cluster.nodes}
        for v in cluster.vms:
            if v.running:
                ac.add_vm(loads[placement[v.vmid]], v)
        for name, n in cluster.nodes.items():
            if n.state == "online":
                self.assertNotEqual(ac.classify(n, loads[name], th)[0], ac.HEALTH_OVERLOADED, name)
        for m in plan["migrations"]:   # destinations stay NORMAL w.r.t. final state of the plan's own moves
            dst = cluster.nodes[m["to"]]
            self.assertIn(ac.classify(dst, loads[m["to"]], th)[0], (ac.HEALTH_NORMAL,))


class ValidationTest(unittest.TestCase):
    def write(self, text):
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        self.addCleanup(os.remove, path)
        return path

    def run_cli(self, path, *extra):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = ac.run(["--input", path] + list(extra), stdout=out)
        return code, out.getvalue(), err.getvalue()

    def test_missing_file(self):
        code, out, err = self.run_cli("/nonexistent/file.json")
        self.assertEqual(code, ac.EXIT_INPUT_ERROR)
        self.assertEqual(out, "")
        self.assertIn("not found", err)
        self.assertNotIn("Traceback", err)

    def test_directory_as_input(self):
        code, _, err = self.run_cli(tempfile.gettempdir())
        self.assertEqual(code, ac.EXIT_INPUT_ERROR)

    def test_invalid_json(self):
        code, _, err = self.run_cli(self.write("{not json"))
        self.assertEqual(code, ac.EXIT_INPUT_ERROR)
        self.assertIn("invalid JSON", err)

    def test_empty_file(self):
        code, _, err = self.run_cli(self.write("   \n"))
        self.assertEqual(code, ac.EXIT_INPUT_ERROR)
        self.assertIn("empty", err)

    def test_nan_rejected(self):
        code, _, _ = self.run_cli(self.write('{"nodes": [], "vms": [], "x": NaN}'))
        self.assertEqual(code, ac.EXIT_INPUT_ERROR)

    def test_top_level_not_object_or_missing_keys(self):
        self.assertEqual(self.run_cli(self.write("[]"))[0], ac.EXIT_INPUT_ERROR)
        self.assertEqual(self.run_cli(self.write('{"nodes": []}'))[0], ac.EXIT_INPUT_ERROR)
        self.assertEqual(self.run_cli(self.write('{"nodes": {}, "vms": []}'))[0], ac.EXIT_INPUT_ERROR)

    def test_no_valid_node_is_fatal(self):
        code, _, err = self.run_cli(self.write('{"nodes": [{"node": "a"}], "vms": []}'))
        self.assertEqual(code, ac.EXIT_INPUT_ERROR)
        self.assertIn("missing field", err)

    def test_missing_vm_fields_skipped_with_warning(self):
        n, d = load_cluster([node("a")], [{"vmid": 1, "node": "a", "status": "running"}, vm(2, "a")])
        self.assertEqual([v.vmid for v in n.vms], [2])
        self.assertTrue(any(w["id"] == "1" for w in d.items))

    def test_invalid_numbers_and_negative_values(self):
        bad = [vm(1, "a"), vm(2, "a"), vm(3, "a"), vm(4, "a")]
        bad[0]["vcpus"] = "4"
        bad[1]["mem_max"] = -5
        bad[2]["vcpus"] = 0
        bad[3]["vcpus"] = True
        cluster, d = load_cluster([node("a")], bad)
        self.assertEqual(cluster.vms, [])
        self.assertEqual(len(d.items), 4)

    def test_cpu_usage_out_of_range_is_untrusted_not_converted(self):
        v = vm(1, "a", 4, 1.0); v["cpu_usage"] = 50.0
        cluster, d = load_cluster([node("a")], [v])
        self.assertFalse(cluster.vms[0].cpu_ok)
        self.assertIsNone(cluster.vms[0].cpu_usage)
        load = ac.compute_loads(cluster)["a"]
        self.assertEqual(load.cpu_used, 0.0)
        self.assertEqual(load.cpu_unverified, 4.0)       # worst case = all vCPUs busy
        self.assertIsNotNone(cluster.vms[0].pin_reason)

    def test_mem_used_none_and_bigger_than_max_untrusted(self):
        a, b = vm(1, "a"), vm(2, "a")
        a["mem_used"] = None
        b["mem_used"] = b["mem_max"] * 2
        cluster, _ = load_cluster([node("a")], [a, b])
        self.assertFalse(any(v.ram_ok for v in cluster.vms))
        self.assertEqual(ac.compute_loads(cluster)["a"].ram_unverified, 20 * GIB)

    def test_unknown_node_mapping_skipped(self):
        cluster, d = load_cluster([node("a")], [vm(1, "ghost")])
        self.assertEqual(cluster.vms, [])
        self.assertIn("unknown node", d.items[0]["message"])

    def test_duplicate_vmid_on_two_nodes_pinned_and_counted_on_both(self):
        cluster, d = load_cluster([node("a"), node("b")], [vm(1, "a"), vm(1, "b")])
        self.assertEqual(len(cluster.vms), 2)
        self.assertTrue(all(v.pin_reason == "duplicate vmid" for v in cluster.vms))
        loads = ac.compute_loads(cluster)
        self.assertEqual(loads["a"].running_vms, 1)
        self.assertEqual(loads["b"].running_vms, 1)

    def test_exact_duplicate_on_same_node_skipped(self):
        cluster, _ = load_cluster([node("a")], [vm(1, "a"), vm(1, "a")])
        self.assertEqual(len(cluster.vms), 1)

    def test_duplicate_node_name_keeps_first(self):
        cluster, _ = load_cluster([node("a", cores=10), node("a", cores=99)], [])
        self.assertEqual(cluster.nodes["a"].cpu_cores, 10)

    def test_zero_cores_or_ram_node_rejected(self):
        n = [node("a", cores=0), node("b"), dict(node("c"), mem_total=0)]
        cluster, d = load_cluster(n, [])
        self.assertEqual(list(cluster.nodes), ["b"])
        self.assertEqual(len(d.items), 2)

    def test_implausible_mem_total_marks_node_unknown_and_excluded(self):
        n = dict(node("a"), mem_total=262144)
        cluster, _ = load_cluster([n, node("b")], [vm(1, "a")])
        res = ac.build_result(cluster, ac.Thresholds(), ac.Diagnostics())
        self.assertEqual(health_of(res, "a"), ac.HEALTH_UNKNOWN)
        self.assertEqual(cluster.vms[0].pin_reason, "host has invalid mem_total")

    def test_dataset_without_vms_still_reports_nodes(self):
        cluster, res = analyse([node("a")], [])
        self.assertEqual(res["migration_plan"]["status"], ac.NO_ACTION)
        self.assertEqual(res["nodes"][0]["running_vms"], 0)

    def test_strict_mode_makes_bad_record_fatal(self):
        bad = vm(1, "a"); bad["cpu_usage"] = 7
        path = self.write(json.dumps({"nodes": [node("a")], "vms": [bad]}))
        self.assertEqual(self.run_cli(path, "--strict")[0], ac.EXIT_INPUT_ERROR)
        self.assertEqual(self.run_cli(path)[0], ac.EXIT_OK)

    def test_bad_cli_threshold(self):
        path = self.write(json.dumps({"nodes": [node("a")], "vms": []}))
        code, _, err = self.run_cli(path, "--cpu-threshold", "150")
        self.assertEqual(code, ac.EXIT_INPUT_ERROR)
        self.assertIn("cpu-threshold", err)


class OutputTest(unittest.TestCase):
    def setUp(self):
        self.path = tempfile.mkstemp(suffix=".json")[1]
        nodes = [node("hot", cores=10), node("cold", cores=10)]
        vms = [vm(1, "hot", 5, 1.0, 10, 10), vm(2, "hot", 4, 1.0, 10, 10)]
        bad = vm(3, "cold"); bad["cpu_usage"] = 9
        with open(self.path, "w") as fh:
            json.dump({"cluster": "t", "nodes": nodes, "vms": vms + [bad]}, fh)
        self.addCleanup(os.remove, self.path)

    def run_cli(self, *extra):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = ac.run(["--input", self.path] + list(extra), stdout=out)
        return code, out.getvalue(), err.getvalue()

    def test_json_mode_stdout_is_pure_json_and_warnings_go_to_stderr(self):
        code, out, err = self.run_cli("--format", "json")
        self.assertEqual(code, 0)
        data = json.loads(out)                                   # must parse
        self.assertEqual(data["migration_plan"]["status"], ac.PLAN_FOUND)
        self.assertIn("vm 3", err)
        self.assertEqual(len(data["warnings"]), 1)
        for key in ("cluster", "thresholds", "nodes", "overloaded_nodes", "migration_plan",
                    "nodes_after_plan", "warnings", "summary"):
            self.assertIn(key, data)

    def test_quiet_suppresses_stderr(self):
        _, _, err = self.run_cli("--format", "json", "--quiet")
        self.assertEqual(err, "")

    def test_table_mode_contains_nodes_and_plan(self):
        code, out, _ = self.run_cli("--format", "table", "--quiet")
        self.assertEqual(code, 0)
        self.assertIn("OVERLOADED", out)
        self.assertIn("PLAN_FOUND", out)
        self.assertIn("RECOMMENDATION ONLY", out)
        self.assertNotIn("\x1b[", out)                            # no colour when not a TTY

    def test_exit_code_3_when_no_feasible_plan(self):
        code, out, _ = self.run_cli("--format", "json", "--quiet", "--cpu-threshold", "20")
        self.assertEqual(code, ac.EXIT_NO_FEASIBLE)
        self.assertEqual(json.loads(out)["migration_plan"]["status"], ac.NO_FEASIBLE)


REAL = os.path.join(os.path.dirname(HERE), "cluster-pve-hcm-c3.json")


@unittest.skipUnless(os.path.exists(REAL), "real snapshot not present")
class RealSnapshotTest(unittest.TestCase):
    def test_real_snapshot_end_to_end(self):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = ac.run(["--input", REAL, "--format", "json"], stdout=out)
        self.assertEqual(code, 0)
        data = json.loads(out.getvalue())
        self.assertEqual(data["overloaded_nodes"], ["hcm-c3-n01"])
        self.assertEqual(data["migration_plan"]["status"], ac.PLAN_FOUND)
        for m in data["migration_plan"]["migrations"]:
            self.assertEqual(m["from"], "hcm-c3-n01")
            self.assertNotIn(m["to"], ("hcm-c3-n04", "hcm-c3-n06"))     # offline / invalid data
            self.assertNotIn(m["vmid"], (2001, 2067, 2073, 2065, 2199, 2390))
        after = {n["node"]: n for n in data["nodes_after_plan"]}
        self.assertNotIn(ac.HEALTH_OVERLOADED, [n["health"] for n in after.values()])
        self.assertGreaterEqual(len(data["warnings"]), 6)


if __name__ == "__main__":
    unittest.main()
