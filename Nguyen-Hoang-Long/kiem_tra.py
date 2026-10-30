#!/usr/bin/env python3
"""One-command offline verification; never contacts or modifies production."""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parent

def run():
    tool=ROOT/'phan2-tool'
    tests=subprocess.run([sys.executable,'-m','unittest','discover','-s',str(tool/'tests'),'-v'],capture_output=True,text=True)
    (tool/'examples/test-results.txt').write_text(tests.stdout+tests.stderr)
    if tests.returncode: raise RuntimeError(tests.stdout+tests.stderr)
    print('PASS: unit/integration tests')
    for name,expected in [('original',2),('lab-assumptions',0)]:
        for fmt,ext in [('json','json'),('table','txt')]:
            result=subprocess.run([sys.executable,str(tool/'cluster_balance.py'),str(tool/'examples'/f'{name}.json'),'--format',fmt],capture_output=True,text=True)
            if result.returncode!=expected:raise RuntimeError(result.stderr+result.stdout)
            (tool/'examples'/f'{name}-output.{ext}').write_text(result.stdout)
            (tool/'examples'/f'{name}-warnings.txt').write_text(result.stderr)
            if fmt=='json':
                report=json.loads(result.stdout)
                if name=='original':
                    assert report['plan']==[] and report['plan_status']=='blocked_invalid_data'
                    assert len(report['warnings'])==8
                else:
                    assert report['resource_plan_complete']
                    assert all(not n['overloaded_dimensions'] for n in report['after'].values())
                assert not report['production_ready']
        print(f'PASS: {name} CLI JSON/table and expected exit {expected}')
    result=subprocess.run([sys.executable,str(ROOT/'phu-luc/thong_ke_lb.py'),str(ROOT/'phu-luc/du-lieu-su-co/lb/access-lb-hcm-01.log')],capture_output=True,text=True,check=True)
    report=json.loads(result.stdout)
    assert report['total']['requests']==4718 and report['total']['errors']==2775
    assert report['first_error']['time']=='01:33:05'
    assert report['last_error']['time']=='02:25:01'
    assert sum(r['requests'] for r in report['minutes'].values())==4718
    assert sum(r['errors'] for r in report['groups']['host'].values())==2775
    (ROOT/'phu-luc/thong-ke-lb.json').write_text(result.stdout)
    print('PASS: LB totals, first/last errors and group conservation')
    for name in ['README.md','phan1-postmortem.md','phan3-nghien-cuu.md','phan4-nhat-ky.md','phan2-tool/README.md']:
        assert (ROOT/name).stat().st_size>100
    print('PASS: all required deliverables present')
    print('OFFLINE CHECKS PASSED. Production recovery/migration NOT executed or certified.')

if __name__=='__main__':run()
