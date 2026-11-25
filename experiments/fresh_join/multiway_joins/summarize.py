"""Reduce the full rotation log to per-stream times and certificate outcomes."""
import csv
from collections import defaultdict
from pathlib import Path
from statistics import median

here=Path(__file__).resolve().parent
groups=defaultdict(lambda:defaultdict(list))
with (here/'timing.csv').open() as src:
    for row in csv.DictReader(src):
        groups[row['cohort'],row['policy']][int(row['round'])].append(row)
with (here/'summary.csv').open('w',newline='') as out:
    writer=csv.writer(out)
    writer.writerow(['cohort','policy','cases','rounds','median_ms','min_ms','max_ms',
                     'prefix_admissions','prefix_rejections','shape_builds'])
    for (cohort,policy),data in sorted(groups.items()):
        ref=data[0]
        assert len(data)==8 and all([r['case_id'] for r in v]==[r['case_id'] for r in ref] for v in data.values())
        times=[sum(int(r['ns']) for r in v)/1e6 for v in data.values()]
        early=[r for r in ref if r['fallback']=='0' and policy not in ('scan_exact','indexed_keys','memo_capped')]
        writer.writerow([cohort,policy,len(ref),len(times),median(times),min(times),max(times),
                         sum(int(r['truth'])<=10**7 for r in early),sum(int(r['truth'])>10**7 for r in early),
                         sum(int(r['shape_build']) for r in ref)])

