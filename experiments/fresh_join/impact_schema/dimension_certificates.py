"""Minimum membership certificates when fact-side fanouts are known exactly."""
import csv
import sys
from bisect import bisect_left, bisect_right
from itertools import accumulate
from math import prod
from pathlib import Path

from permutation_witness import load


BUDGET = 10_000_000


def bounds(unknown, remaining, fixed):
    ranked = sorted(unknown, reverse=True)
    return fixed+sum(ranked[len(ranked)-remaining:]), fixed+sum(ranked[:remaining])


def minimum_certificate(weights, passed, budget):
    """Return a minimum subset of labels proving that the weighted sum fits."""
    actual = sum(weights[x] for x in passed)
    assert actual <= budget
    yes = sorted(weights[x] for x in passed)
    no = sorted(w for x,w in weights.items() if x not in passed)
    yes_sum = list(accumulate(yes,initial=0))
    no_sum = list(accumulate(no,initial=0))
    best = None
    for t in sorted(set(weights.values())|{0}):
        # This dual expression is the unprobed upper bound at threshold t.
        a,b = bisect_right(yes,t),bisect_right(no,t)
        bound = (len(yes)*t + yes_sum[-1]-yes_sum[a]-(len(yes)-a)*t
                 + no_sum[-1]-no_sum[b]-(len(no)-b)*t)
        required = bound-budget
        if required<=0:
            return set()

        def savings(g):
            # Each observed pass below t saves t-w; each fail above t saves w-t.
            i,j = bisect_right(yes,t-g),bisect_left(no,t+g)
            return i+len(no)-j, i*t-yes_sum[i]+no_sum[-1]-no_sum[j]-(len(no)-j)*t

        low,high = 1, max(t, (no[-1] if no else 0)-t)+1
        while low+1<high:
            mid = (low+high)//2
            if savings(mid)[1]>=required:
                low=mid
            else:
                high=mid
        n,saved = savings(low+1)
        count = n+(required-saved+low-1)//low
        if best is None or count<best[0]:
            best = count,t

    count,t = best
    def benefit(key):
        return max(0, t-weights[key] if key in passed else weights[key]-t)
    chosen = set(sorted(weights,key=lambda x:(-benefit(x),x))[:count])
    fixed = sum(weights[x] for x in chosen & passed)
    _,worst = bounds((w for x,w in weights.items() if x not in chosen),len(passed-chosen),fixed)
    assert worst<=budget
    return chosen


def high_weight_first(weights, m, lookup, budget):
    """Uses only the membership bits acquired so far, known weights and m."""
    keys = sorted(weights,key=lambda x:(-weights[x],x))
    prefix = list(accumulate((weights[x] for x in keys),initial=0))
    fixed = 0
    for i in range(len(keys)+1):
        lo = fixed+prefix[-1]-prefix[len(keys)-m]
        hi = fixed+prefix[i+m]-prefix[i]
        if hi<=budget or lo>budget:
            return i, hi<=budget
        if lookup(keys[i]):
            m-=1
            fixed+=weights[keys[i]]


def main(root,output):
    cases,base,meta = load(root)
    dim = base['users','Id']
    assert all(v==1 for v in dim.values())
    with output.open('w',newline='') as stream:
        writer=csv.writer(stream)
        writer.writerow(['case_id','observed','passing_users','unprobed_max','min_yes_certificate',
                         'min_no_certificate','adaptive_descending_probes'])
        for case in cases:
            ids=case['input_ids']
            dims=[i for i in ids if meta[i][0]==('users','Id') and meta[i][1]!='TRUE']
            if not dims:
                continue
            assert len(dims)==1
            dim_id=dims[0]
            passed=set(meta[dim_id][2])
            assert len(passed)>24 and all(c==1 for c in meta[dim_id][2].values())
            others=[meta[i][2] for i in ids if i!=dim_id]
            weights={x:prod(m.get(x,0) for m in others) for x in dim}
            actual=sum(weights[x] for x in passed)
            assert actual==case['observed_cardinality']
            floor,upper=bounds(weights.values(),len(passed),0)
            n,admit=high_weight_first(weights,len(passed),passed.__contains__,BUDGET)
            assert admit==(actual<=BUDGET) and floor<=actual<=upper
            yes=no=None
            if admit:
                yes=len(minimum_certificate(weights,passed,BUDGET))
                assert yes<=n
            else:
                no=len(minimum_certificate(weights,weights.keys()-passed,sum(weights.values())-BUDGET-1))
                assert no<=n
            writer.writerow([case['case_id'],actual,len(passed),upper,yes,no,n])


if __name__=='__main__':
    main(Path(sys.argv[1]),Path(sys.argv[2]))
