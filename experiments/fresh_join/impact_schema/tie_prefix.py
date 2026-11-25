"""Conservative free-prefix and exact single-swap checks for ascending-ID tie breaking."""
import argparse
import csv
import json
import zipfile
from math import prod
from pathlib import Path

from dimension_certificates import BUDGET, minimum_certificate
from permutation_witness import load


def first_swap(weights, passed, slack, masks, visible, earliest):
    donors = sorted((weights[x],x) for x in passed)
    recipients = sorted(((w,x) for x,w in weights.items()
                         if x not in passed and w-donors[0][0]>slack),reverse=True)
    for w_t,t in recipients:
        for w_s,s in donors:
            gain = w_t - w_s
            if gain<=slack:
                break
            if (masks[s]^masks[t]) & visible[min(s,t)]:
                continue
            # Independently reconstruct each first-24 list after its exchange.
            for j,top25 in enumerate(earliest):
                changed = set(top25)
                if bool(masks[s]&(1<<j)) != bool(masks[t]&(1<<j)):
                    old,new=(s,t) if masks[s]&(1<<j) else (t,s)
                    changed.discard(old)
                    changed.add(new)
                assert sorted(changed)[:24]==top25[:24]
            return s,t,gain
    return None


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("paper",type=Path)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    cases,base,meta=load(args.paper)
    dim=base["users","Id"]
    with zipfile.ZipFile(args.paper/"supplement.zip") as src:
        with src.open("validation-data/inputs/filtered-key-frequencies.jsonl") as f:
            user_filters=[r for r in map(json.loads,f) if r["table"]=="users"]
    masks={x:0 for x in dim}
    earliest=[]; cutoffs=[]
    for j,r in enumerate(user_filters):
        pairs = r["key_frequency_pairs"]
        assert r["column"]=="Id" and len(pairs)>24 and all(v==1 for _,v in pairs)
        keys=sorted(x for x,_ in pairs)
        earliest.append(keys[:25]); cutoffs.append(keys[23])
        for x in keys: masks[x]|=1<<j
    cutoff=max(cutoffs)
    fixed_ids={x for x in dim if x<=cutoff}
    visible={x:sum(1<<j for j,L in enumerate(cutoffs) if L>=x) for x in dim}
    rows=[]
    for case in cases:
        actual=case["observed_cardinality"]
        if actual>BUDGET: continue
        ids=case["input_ids"]
        dims=[i for i in ids if meta[i][0]==("users","Id") and meta[i][1]!="TRUE"]
        if not dims: continue
        d=dims[0]; passed=set(meta[d][2])
        others=[meta[i][2] for i in ids if i!=d]
        weights={x:prod(m.get(x,0) for m in others) for x in dim}
        assert sum(weights[x] for x in passed)==actual
        unprobed=sum(sorted(weights.values(),reverse=True)[:len(passed)])
        fixed=sum(weights[x] for x in passed&fixed_ids)
        unknown={x:v for x,v in weights.items() if x>cutoff}
        tail=passed-fixed_ids
        upper=fixed+sum(sorted(unknown.values(),reverse=True)[:len(tail)])
        min_reads=len(minimum_certificate(unknown,tail,BUDGET-fixed))
        donor=min((weights[x] for x in tail),default=0)
        target=max((w for x,w in unknown.items() if x not in tail),default=0)
        suffix_swap=bool(tail and len(tail)<len(unknown) and target-donor>BUDGET-actual)
        direct=first_swap(weights,passed,BUDGET-actual,masks,visible,earliest)
        assert not suffix_swap or direct
        rows.append((case["case_id"],actual,unprobed,cutoff,len(fixed_ids),upper,min_reads,
                     int(suffix_swap),int(bool(direct)),*(direct[:2] if direct else ("","")),
                     actual+direct[2] if direct else ""))
    header=("case_id","observed","strict_unprobed_max","last_disclosed_id","free_users","suffix_upper",
            "suffix_min_certificate","suffix_one_swap","all_top24_one_swap","pass_donor","fail_receiver","after_swap")
    with args.output.open("w",newline="") as f:
        w=csv.writer(f);w.writerow(header);w.writerows(rows)
    hard=[v for v in rows if v[2]>BUDGET]
    print("all user filters",len(user_filters),"max24",cutoff,"frozen",len(fixed_ids),"of",len(dim))
    print("original dimension ambiguous",len(hard),"suffix ambiguous",sum(r[5]>BUDGET for r in hard),
          "suffix single swap",sum(r[7] for r in hard),"global top24 single swap",sum(r[8] for r in hard))
    print("example",next(r for r in rows if r[0]=="query-0084"))


if __name__=="__main__":
    main()
