#!/usr/bin/env python3
"""Reproduce statistics from the supplied LB log; no production operations."""
import argparse
import collections
import json
import math
import re
from pathlib import Path

PATTERN=re.compile(r'^(\S+).*\[20/Oct/2026:(\d\d:\d\d:\d\d) \+0700\] "[^"]+" (\d+) .*host="([^"]+)" upstream="([^"]+)" rt=([\d.]+)')

def stats(rows):
    times=sorted(r['rt'] for r in rows)
    counts=collections.Counter(r['status'] for r in rows)
    errors=sum(r['status'] in (502,504) for r in rows)
    return dict(requests=len(rows),status=dict(counts),errors=errors,
                error_pct=round(errors/len(rows)*100,2) if rows else None,
                mean_rt=round(sum(times)/len(times),3) if times else None,
                p95_rt=times[math.ceil(.95*len(times))-1] if times else None)

def analyze(path):
    rows=[]
    for i,line in enumerate(path.read_text().splitlines(),1):
        m=PATTERN.fullmatch(line)
        if not m:raise ValueError(f'Unparsed line {i}; refusing partial statistics')
        ip,t,status,host,upstream,rt=m.groups()
        rows.append(dict(ip=ip,time=t,status=int(status),host=host,upstream=upstream,rt=float(rt)))
    if not rows:raise ValueError('Empty log')
    groups={key:{v:stats([r for r in rows if r[key]==v]) for v in sorted(set(r[key] for r in rows))} for key in ['host','upstream']}
    minutes={t:stats([r for r in rows if r['time'].startswith(t)]) for t in sorted(set(r['time'][:5] for r in rows))}
    errors=[r for r in rows if r['status'] in (502,504)]
    return dict(total=stats(rows),first_error=min(errors,key=lambda x:x['time']) if errors else None,
                last_error=max(errors,key=lambda x:x['time']) if errors else None,groups=groups,minutes=minutes,
                since_0133=stats([r for r in rows if r['time']>='01:33:00']),
                without_highlighted_ip=stats([r for r in rows if r['ip']!='45.135.232.17']),
                highlighted_ip=stats([r for r in rows if r['ip']=='45.135.232.17']))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log',type=Path)
    args=parser.parse_args()
    print(json.dumps(analyze(args.log),indent=2,ensure_ascii=False))
