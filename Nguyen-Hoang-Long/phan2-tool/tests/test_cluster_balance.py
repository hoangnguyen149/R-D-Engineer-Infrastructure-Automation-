import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cluster_balance import GIB, analyze, loads, validate, DEFAULT


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
        self.assertEqual(r['plan_status'],'blocked_invalid_data')
        self.assertEqual(sum(x['running_vms'] for x in r['before'].values()),0)
        self.assertFalse(r['before']['a']['complete']); self.assertFalse(r['before']['b']['complete'])

    def test_invalid_fields(self):
        for field,value in [('cpu_usage',31),('cpu_usage',float('nan')),('mem_used',None),('mem_used',-1),('vcpus',True),('node','absent'),('vmid',[]),('status','paused'),('mem_max',1)]:
            with self.subTest(field=field,value=value):
                d=fixture(); d['vms'][0][field]=value
                self.assertEqual(analyze(d)['plan_status'],'blocked_invalid_data')

    def test_invalid_nodes(self):
        for field,value in [('mem_total',262144),('cpu_cores',0),('status',[])]:
            d=fixture(); d['nodes'][0][field]=value
            self.assertEqual(analyze(d)['plan_status'],'blocked_invalid_data')

    def test_missing_field(self):
        d=fixture(); del d['vms'][0]['mem_used']; self.assertTrue(analyze(d)['warnings'])

    def test_running_on_offline_blocks(self):
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
        p=Path(__file__).resolve().parents[1]/'examples/original.json'
        r=analyze(json.loads(p.read_text())); self.assertEqual(r['plan_status'],'blocked_invalid_data')
        text=json.dumps(r['warnings'])
        for value in ['2001','2067','2073','2065','2199','2390','hcm-c3-n06']: self.assertIn(value,text)

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
