"""Reaggregate matched physical effects, including the cost of each routing procedure."""
import csv
import sys
from collections import Counter
from math import ceil
from pathlib import Path
from statistics import median

HERE=Path(__file__).resolve().parent / ('replication' if '--replicate' in sys.argv else '')
def data(name):
    with (HERE/name).open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def main():
    decision=data('decisions.csv')
    measure={(r['case'],int(r['round']),int(r['memory_mib'])):r for r in data('measurements.csv')}
    startup={(int(r['round']),r['method']):float(r['extra_ms']) for r in data('preflight.csv')}
    methods={'always_low':(None,0),'always_high':(None,1),'native_threshold':('native_ms','native_high'),
             'native_matched':('native_ms','matched_native_high'),'certificate_resident':('certificate_ms','certificate_high'),
             'certificate_cold':('certificate_ms','certificate_high'),'group_sql':('sql_ms','certificate_high'),
             'natural_cold':('natural_ms','certificate_high'),'memo_cold':('memo_ms','certificate_high'),
             'indexed_cold':('indexed_ms','certificate_high')}
    result=[]
    for rnd in (0,1):
        for name,(cost,col) in methods.items():
            rows=[]
            for q in decision:
                if int(q['round'])!=rnd:continue
                mem=128 if (col if cost is None else int(q[col])) else 32
                m=measure[q['case'],rnd,mem]
                overhead=float(q[cost]) if cost else 0
                if not rows and name.endswith('_cold'):
                    overhead+=startup[rnd,name.split('_')[0]]
                rows.append(dict(high=mem==128,risk=int(m['risk']),failure=m['status']!='completed',temp=int(m['profiler_total_spill_bytes'] or 0),
                                 wall=float(m['elapsed_ms'])+overhead,overhead=overhead))
            lat=sorted(r['wall'] for r in rows)
            result.append(dict(round=rnd,method=name,high_grants=sum(r['high'] for r in rows),max_grant_mib_sum=32*len(rows)+96*sum(r['high'] for r in rows),
                          spill_or_failure=sum(r['risk'] for r in rows),failed=sum(r['failure'] for r in rows),total_spill_bytes=sum(r['temp'] for r in rows),
                          preflight_ms=round(sum(r['overhead'] for r in rows),3),total_ms=round(sum(lat),3),p95_ms=round(lat[ceil(.95*len(lat))-1],3)))
    with (HERE/'comparison.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(result[0]));w.writeheader();w.writerows(result)
    for r in result:print(*r.values())
if __name__=='__main__':main()

