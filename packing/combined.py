"""Combine key identity and residual shape in one 51-word summary."""
from math import prod
from collections import Counter
from bounds import summary,bounds,allocate,pair_runs
from compressed_degree import encode,decode
from baselines import run_upper

def prefix(heads,tail):
    """Prepend descending named frequencies to a residual envelope."""
    out=[]
    for j,value in enumerate(sorted(heads,reverse=True),1):
        out.append((j,value))
    return out+[(end+len(out),value) for end,value in tail]

def make_catalog(counts):
    head,_=summary(counts,12)
    return head,encode((v for x,v in counts.items() if x not in head),13)

def histogram(runs):
    result=Counter()
    pos=0
    for end,frequency in runs:
        result[frequency]+=end-pos
        pos=end
    return result

def combined(catalogs):
    heads,profiles=zip(*catalogs)
    tails=[decode(p,13) for p in profiles]
    caps=[t[0][1] if t else 0 for t in tails]
    triples=[]
    for runs,cap in zip(tails,caps):
        n=m=0
        for end,v in runs:
            m+=(end-n)*v
            n=end
        triples.append((m,n,cap))
    name_bounds=bounds(heads,triples,node_limit=1)
    common=set.intersection(*(set(h) for h in heads))
    fixed=sum(prod(h[x] for h in heads) for x in common)
    others=[{x:v for x,v in h.items() if x not in common} for h in heads]
    ranked=fixed+run_upper(*(prefix(h.values(),t) for h,t in zip(others,tails)))
    core=fixed+run_upper(*(prefix([u]*len(h),t) for h,u,t in zip(others,caps,tails)))
    clipped=core
    groups={}
    for x in set().union(*others):
        missing=tuple(i for i,h in enumerate(others) if x not in h)
        known=[i for i,h in enumerate(others) if x in h]
        excess=prod(others[i][x] for i in known)-prod(caps[i] for i in known)
        clipped+=excess*prod(caps[i] for i in missing)
        groups.setdefault(missing,[]).append(excess)
    grouped=core+sum(run_upper(prefix(weights,[]),*(tails[i] for i in mask))
                     for mask,weights in groups.items())
    upper=min(name_bounds['upper'],ranked,grouped)
    if len(heads)==2:
        s0,tail1=allocate(others[0].values(),histogram(tails[1]))
        s1,tail0=allocate(others[1].values(),histogram(tails[0]))
        upper=fixed+s0+s1+pair_runs(tail0,tail1)
    return dict(named=name_bounds['upper'],ranked=ranked,clipped=clipped,
                grouped=grouped,combined=upper)
