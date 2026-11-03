import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cluster_balance import GIB, analyze, loads, validate, DEFAULT

TOOL=Path(__file__).resolve().parents[1]/'cluster_balance.py'
ORIGINAL=Path(__file__).resolve().parents[1]/'examples/original.json'


def node(name='a', cores=10, ram=100, status='online'):
    return dict(node=name, cpu_cores=cores, mem_total=ram*GIB, status=status)


def vm(vid=1, name='a', cpu=1, used=10, maximum=20, vcpus=2, status='running'):
    return dict(vmid=vid, node=name, cpu_usage=cpu, mem_used=used*GIB,
                mem_max=maximum*GIB, vcpus=vcpus, status=status)


def fixture():
    return dict(nodes=[node(), node('b')], vms=[vm()])


class PlannerTests(unittest.TestCase):
    def test_cpu_formula(self):
        d=fixture(); d['vms'][0].update(vcpus=4,cpu_usage=.5)
        r=analyze(d)['before']['a']; self.assertEqual(r['cpu_cores_used'],2)
        self.assertEqual(r['ratios']['cpu'],.2)

    def test_stopped_excluded_running_overcommit(self):
        d=fixture(); d['vms'].append(vm(2,cpu=0,used=0,vcpus=64,status='stopped'))
        r=analyze(d)['before']['a']; self.assertEqual(r['running_vcpus'],2)
        self.assertEqual(r['configured_vcpus_all_valid_records'],66)

    def test_exact_threshold_not_overloaded(self):
        d=fixture(); d['vms']=[vm(vcpus=8,used=85,maximum=85)]
        self.assertEqual(analyze(d)['plan'],[])
        self.assertEqual(analyze(d)['before']['a']['assessment'],'within_thresholds')

    def test_ram_migration_and_conservation(self):
        d=fixture(); d['vms']=[vm(1,used=50,maximum=50),vm(2,used=40,maximum=40)]
        original=copy.deepcopy(d); r=analyze(d)
        self.assertEqual(d,original); self.assertTrue(r['resource_plan_complete'])
        self.assertEqual(len(r['plan']),1)
        self.assertEqual(sum(x['ram_bytes_used'] for x in r['before'].values()),sum(x['ram_bytes_used'] for x in r['after'].values()))
        for x in r['after'].values(): self.assertFalse(x['overloaded_dimensions'])

    def test_cpu_migration(self):
        d=fixture(); d['vms']=[vm(1,vcpus=5),vm(2,vcpus=5)]
        self.assertEqual(analyze(d)['plan_status'],'balanced')
        self.assertEqual(len(analyze(d)['plan']),1)

    def test_overcommit_migration(self):
        d=fixture(); d['vms']=[vm(1,cpu=.01,vcpus=25),vm(2,cpu=.01,vcpus=25)]
        self.assertEqual(analyze(d)['before']['a']['overloaded_dimensions'],['overcommit'])
        self.assertTrue(analyze(d)['resource_plan_complete'])

    def test_offline_target_never_used(self):
        d=fixture(); d['nodes'][1]['status']='offline'; d['vms']=[vm(1,vcpus=9)]
        r=analyze(d); self.assertEqual(r['plan_status'],'unresolved'); self.assertEqual(r['plan'],[])

    def test_no_capacity_does_not_claim_success(self):
        d=fixture(); d['vms']=[vm(1,vcpus=9),vm(2,'b',vcpus=8)]
        self.assertFalse(analyze(d)['resource_plan_complete'])

    def test_transient_mem_max_headroom(self):
        d=fixture(); d['vms']=[vm(1,vcpus=9,used=10,maximum=90)]
        self.assertEqual(analyze(d)['plan_status'],'unresolved')

    def test_duplicate_all_excluded(self):
        d=fixture(); d['vms'].append(vm(1,'b')); r=analyze(d)
        self.assertEqual(r['plan_status'],'partial_plan_with_excluded_records'); self.assertFalse(r['resource_plan_complete'])
        self.assertEqual(len(r['warnings']),2)
        self.assertEqual(sum(x['running_vms'] for x in r['before'].values()),0)
        self.assertFalse(r['before']['a']['complete']); self.assertFalse(r['before']['b']['complete'])

    def test_invalid_fields(self):
        for field,value in [('cpu_usage',31),('cpu_usage',float('nan')),('mem_used',None),('mem_used',-1),('vcpus',True),('node','absent'),('vmid',[]),('status','paused'),('mem_max',1)]:
            with self.subTest(field=field,value=value):
                d=fixture(); d['vms'][0][field]=value
                r=analyze(d)   # bad record is excluded + warned, cluster is NOT blocked
                self.assertEqual(r['plan_status'],'partial_plan_with_excluded_records')
                self.assertTrue(r['warnings']); self.assertEqual(r['plan'],[])
                self.assertEqual(sum(x['running_vms'] for x in r['before'].values()),0)

    def test_invalid_nodes(self):
        for field,value in [('mem_total',262144),('cpu_cores',0),('status',[])]:
            d=fixture(); d['nodes'][0][field]=value
            r=analyze(d)
            self.assertEqual(r['plan_status'],'partial_plan_with_excluded_records'); self.assertTrue(r['warnings'])
            self.assertIsNone(r['before']['a']['ratios'])  # N/A, never guessed

    def test_missing_field(self):
        d=fixture(); del d['vms'][0]['mem_used']; self.assertTrue(analyze(d)['warnings'])

    def test_running_on_offline_is_excluded_and_warned(self):
        d=fixture(); d['nodes'][0]['status']='offline'; self.assertTrue(analyze(d)['warnings'])

    def test_bad_root(self):
        for d in [None,[],{},dict(nodes=[],vms=[])]:
            with self.assertRaises(ValueError): analyze(d)

    def test_threshold_validation(self):
        with self.assertRaises(ValueError): analyze(fixture(),dict(cpu=2,ram=.8,overcommit=4))

    def test_deterministic(self):
        d=fixture(); d['vms']=[vm(1,vcpus=5),vm(2,vcpus=5)]
        self.assertEqual(analyze(d),analyze(d))

    def test_original_anomalies(self):
        r=analyze(json.loads(ORIGINAL.read_text()))
        self.assertEqual(r['plan_status'],'partial_plan_with_excluded_records')
        self.assertEqual(len(r['warnings']),8)
        text=json.dumps(r['warnings'])
        for value in ['2001','2067','2073','2065','2199','2390','hcm-c3-n06']: self.assertIn(value,text)

    def test_original_still_proposes_migration(self):
        """Regression: original file used to return blocked_invalid_data and an empty plan."""
        r=analyze(json.loads(ORIGINAL.read_text()))
        self.assertNotEqual(r['plan_status'],'blocked_invalid_data')
        self.assertGreaterEqual(len(r['plan']),1)
        self.assertEqual(r['before']['hcm-c3-n01']['assessment'],'overloaded_lower_bound')
        for m in r['plan']:
            self.assertEqual(m['from'],'hcm-c3-n01')
            self.assertEqual(m['to'],'hcm-c3-n03')            # only clean, online, valid target
            self.assertTrue(m['source_load_is_lower_bound'])
            self.assertNotIn(m['vmid'],{2001,2067,2073,2065,2199,2390})  # excluded records never migrated
        self.assertFalse(r['resource_plan_complete']); self.assertFalse(r['production_ready'])
        self.assertFalse(r['after']['hcm-c3-n03']['overloaded_dimensions'])

    def test_tainted_node_never_a_target(self):
        d=dict(nodes=[node('a'),node('b'),node('c')],
               vms=[vm(1,'a',vcpus=5),vm(2,'a',vcpus=5),vm(3,'b'),vm(4,'b',used=-1)])  # b lost VM4
        r=analyze(d)
        self.assertTrue(r['plan']); self.assertTrue(all(m['to']=='c' for m in r['plan']))

    def test_only_tainted_targets_gives_unresolved_not_unsafe_move(self):
        d=dict(nodes=[node('a'),node('b')],vms=[vm(1,'a',vcpus=5),vm(2,'a',vcpus=5),vm(3,'b',used=-1)])
        r=analyze(d)
        self.assertEqual(r['plan'],[]); self.assertEqual(r['plan_status'],'unresolved_with_excluded_records')
        self.assertTrue(r['warnings'])

    def test_tainted_source_can_still_shed_load(self):
        d=dict(nodes=[node('a'),node('b')],vms=[vm(1,'a',vcpus=5),vm(2,'a',vcpus=5),vm(3,'a',used=-1)])
        r=analyze(d)
        self.assertEqual(len(r['plan']),1); self.assertTrue(r['plan'][0]['source_load_is_lower_bound'])
        self.assertEqual(r['plan'][0]['to'],'b')
        self.assertNotEqual(r['plan_status'],'balanced')

    def test_invalid_vm_removed_from_plan_but_warning_kept(self):
        d=dict(nodes=[node('a'),node('b')],vms=[vm(1,'a',vcpus=5),vm(2,'a',vcpus=5),vm(9,'zzz')])
        r=analyze(d)
        self.assertEqual(len(r['plan']),1); self.assertNotEqual(r['plan'][0]['vmid'],9)
        self.assertIn('unknown or invalid node reference',json.dumps(r['warnings']))
        self.assertEqual(r['excluded_records'],1)

    def test_clean_data_still_reports_balanced(self):
        d=fixture(); d['vms']=[vm(1,vcpus=5),vm(2,vcpus=5)]
        r=analyze(d); self.assertEqual(r['plan_status'],'balanced')
        self.assertEqual(r['warnings'],[]); self.assertTrue(r['resource_plan_complete'])

    def test_blocked_only_when_nothing_usable(self):
        d=fixture()
        for n in d['nodes']: n['mem_total']=1024
        r=analyze(d)
        self.assertEqual(r['plan_status'],'blocked_invalid_data'); self.assertEqual(r['plan'],[])
        self.assertTrue(r['warnings'])

    def test_invalid_capacity_never_a_target(self):
        for field,value in [('mem_total',262144),('mem_total',None),('cpu_cores',0),('status',[])]:
            with self.subTest(field=field,value=value):
                d=dict(nodes=[node('a'),node('b'),node('c')],
                       vms=[vm(1,'a',vcpus=5),vm(2,'a',vcpus=5)])
                d['nodes'][1][field]=value
                r=analyze(d)
                self.assertEqual([m['to'] for m in r['plan']],['c'])
                self.assertFalse(r['resource_plan_complete'])

    def test_original_projection_preserves_lower_bounds_and_resources(self):
        d=json.loads(ORIGINAL.read_text()); original=copy.deepcopy(d); r=analyze(d)
        self.assertEqual(d,original)
        nodes,work,tainted,_=validate(d)
        initial=loads(nodes,work,tainted,DEFAULT)
        for m in r['plan']:
            v=next(v for v in work if v['vmid']==m['vmid'])
            self.assertEqual(v['node'],m['from'])
            self.assertTrue(nodes[m['to']]['valid'])
            self.assertNotIn(m['to'],tainted)
            before=loads(nodes,work,tainted,DEFAULT)
            self.assertLessEqual(before[m['to']]['ram_bytes_used']+v['mem_max'],nodes[m['to']]['mem_total']*.85)
            v['node']=m['to']; after=loads(nodes,work,tainted,DEFAULT)
            self.assertEqual(m['target_after'],after[m['to']])
            self.assertTrue(after[m['to']]['complete'])
            self.assertFalse(after[m['to']]['overloaded_dimensions'])
        final=loads(nodes,work,tainted,DEFAULT)
        self.assertEqual(final,r['after'])
        self.assertFalse(final['hcm-c3-n01']['complete'])
        self.assertEqual(final['hcm-c3-n01']['assessment'],'unknown')
        self.assertFalse(final['hcm-c3-n02']['complete'])
        self.assertIsNone(final['hcm-c3-n06']['ratios'])
        for field in ['cpu_cores_used','ram_bytes_used','running_vcpus']:
            self.assertAlmostEqual(sum(x[field] for x in initial.values()),sum(x[field] for x in final.values()))

    def test_multiple_warnings_count_one_excluded_record(self):
        d=fixture(); d['vms'][0].update(cpu_usage=31,mem_used=-1)
        r=analyze(d)
        self.assertEqual(len(r['warnings']),2)
        self.assertEqual(r['excluded_records'],1)
        self.assertEqual(sum(x['running_vms'] for x in r['before'].values()),0)

    def test_cli_exit_status_contract(self):
        unresolved=dict(nodes=[node('a'),node('b')],
                        vms=[vm(1,'a',vcpus=5),vm(2,'a',vcpus=5),vm(3,'b',used=-1)])
        clean_unresolved=fixture(); clean_unresolved['nodes'][1]['status']='offline'
        clean_unresolved['vms']=[vm(1,vcpus=9)]
        blocked=fixture()
        for n in blocked['nodes']: n['mem_total']=1024
        warning_no_moves=fixture(); warning_no_moves['vms'][0]['cpu_usage']=31
        for d,code,status in [(fixture(),0,'balanced'),(blocked,2,'blocked_invalid_data'),
                              (clean_unresolved,3,'unresolved'),(unresolved,3,'unresolved_with_excluded_records'),
                              (warning_no_moves,4,'partial_plan_with_excluded_records')]:
            with self.subTest(status=status), tempfile.TemporaryDirectory() as tmp:
                p=Path(tmp)/'input.json'; p.write_text(json.dumps(d))
                result=subprocess.run([sys.executable,str(TOOL),str(p),'--format','json'],capture_output=True,text=True)
                self.assertEqual(result.returncode,code)
                self.assertEqual(json.loads(result.stdout)['plan_status'],status)

    def test_cli_original_exit_and_json(self):
        result=subprocess.run([sys.executable,str(TOOL),str(ORIGINAL),'--format','json'],capture_output=True,text=True)
        self.assertEqual(result.returncode,4)
        report=json.loads(result.stdout)
        self.assertGreaterEqual(len(report['plan']),1)
        self.assertEqual(result.stderr.count('WARNING'),8)
        self.assertNotIn('Traceback',result.stderr)

    def test_cli_original_table_shows_move_and_warning_count(self):
        result=subprocess.run([sys.executable,str(TOOL),str(ORIGINAL)],capture_output=True,text=True)
        self.assertEqual(result.returncode,4)
        self.assertEqual(len(result.stderr.splitlines()),8)
        self.assertIn('MOVE VM',result.stdout); self.assertIn('EXCLUDED RECORDS: 8',result.stdout)
        self.assertIn('[source load is a lower bound]',result.stdout)

    def test_cli_invalid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'bad.json';p.write_text('{bad')
            result=subprocess.run([sys.executable,str(Path(__file__).resolve().parents[1]/'cluster_balance.py'),str(p),'--format','json'],capture_output=True,text=True)
            self.assertEqual(result.returncode,2);self.assertEqual(json.loads(result.stdout)['plan_status'],'input_error')
            self.assertNotIn('Traceback',result.stderr)

    def test_cli_missing_file(self):
        result=subprocess.run([sys.executable,str(Path(__file__).resolve().parents[1]/'cluster_balance.py'),'/nonexistent-incident-input','--format','json'],capture_output=True,text=True)
        self.assertEqual(result.returncode,2);json.loads(result.stdout)

    def test_each_step_safe_in_lab(self):
        p=Path(__file__).resolve().parents[1]/'examples/lab-assumptions.json'
        d=json.loads(p.read_text());r=analyze(d); self.assertTrue(r['resource_plan_complete'])
        nodes,work,_,_=validate(d)
        initial=loads(nodes,work,set(),DEFAULT)
        for m in r['plan']:
            v=next(v for v in work if v['vmid']==m['vmid'])
            self.assertEqual(v['node'],m['from']); self.assertEqual(nodes[m['to']]['status'],'online')
            before=loads(nodes,work,set(),DEFAULT)
            self.assertLessEqual(before[m['to']]['ram_bytes_used']+v['mem_max'],nodes[m['to']]['mem_total']*.85)
            v['node']=m['to'];after=loads(nodes,work,set(),DEFAULT)
            self.assertFalse(after[m['to']]['overloaded_dimensions'])
        final=loads(nodes,work,set(),DEFAULT)
        for field in ['cpu_cores_used','ram_bytes_used','running_vcpus']:
            self.assertAlmostEqual(sum(x[field] for x in initial.values()),sum(x[field] for x in final.values()))
        for x in final.values(): self.assertFalse(x['overloaded_dimensions'])


if __name__=='__main__': unittest.main()
