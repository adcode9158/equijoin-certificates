"""Exact minimum fitting certificate with one known filtered cardinality.

Each key has an upper count for the table with the total, its observed actual
count, and lists of partner (upper, actual). O(K) here denotes unit disclosures,
never measured wall time. This transparent DP is used on finite instances.
"""
from fractions import Fraction
from math import prod


def options(designated_cap, designated_value, partners):
    weight = prod(c for c,a in partners)
    ranks = [weight]
    unknown = sorted(((Fraction(a,c),c,a) for c,a in partners if c), key=lambda p:p[0])
    for _,cap,actual in unknown:
        weight = weight // cap * actual
        ranks.append(weight)
    return designated_cap, designated_value, ranks


def minimum_one_total(keys, budget):
    prepared = [options(c,a,p) for c,a,p in keys]
    total = sum(a for c,a,p in keys)
    truth = sum(a*prod(v for c,v in p) for c,a,p in keys)
    assert truth <= budget
    best = sum(len(p)+1 for c,a,p in keys)
    thresholds = {0} | {w for c,a,ranks in prepared for w in ranks}
    for t in thresholds:
        initial = t*total + sum(c*max(ranks[0]-t,0) for c,a,ranks in prepared)
        needed = initial-budget
        if needed<=0:
            return 0
        # best is a feasible cost already. Search only for a strict improvement.
        dp = [0]
        for c,a,ranks in prepared:
            old = c*max(ranks[0]-t,0)
            improvements = [0]*(len(ranks)+1)
            for j,w in enumerate(ranks):
                improvements[j] = max(improvements[j],old - c*max(w-t,0))
                improvements[j+1] = max(improvements[j+1],old - a*(w-t))
            updated=[0]*min(best,len(dp)+len(improvements)-1)
            for i,s in enumerate(dp):
                for j,gain in enumerate(improvements[:best-i]):
                    updated[i+j]=max(updated[i+j],s+gain)
            dp=updated
        for k,achieved in enumerate(dp):
            if achieved>=needed:
                best=k
                break
    return best

