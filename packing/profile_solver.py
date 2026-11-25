"""Attainable profile worlds and integer dual certificates on STATS full queries."""
from collections import Counter, defaultdict
from fractions import Fraction
from math import prod
import numpy as np
from scipy.optimize import linprog
from scipy.sparse import csc_matrix
from bounds import summary, allocate, pair_runs
from combined import histogram
from compressed_degree import decode, ends
from baselines import run_upper
from pricing import chain

DENOM=1<<18
SLOTS=13

def stable_catalog(counts):
    base,_=summary(counts,12)
    outside=[v for k,v in counts.items() if k not in base]
    cut=max(outside,default=0)
    h={k:v for k,v in base.items() if v>cut}
    levels=Counter(v for k,v in counts.items() if k not in h)
    return h, encode_runs(levels)

def encode_runs(freq):
    n=sum(freq.values())
    groups=sorted(freq.items(),reverse=True)
    if n<=SLOTS:
        return -n,groups
    it=iter(groups)
    v,count=next(it)
    pos=0
    bins=[]
    for end in ends(n,SLOTS):
        cap=v
        mass=0
        while pos<end:
            take=min(count,end-pos)
            mass+=take*v
            pos+=take
            count-=take
            if not count: v,count=next(it,(0,0))
        bins.append((cap,mass))
    candidate=n,bins
    if len(groups)<=SLOTS and histogram(decode(candidate,SLOTS))!=freq:
        return -n,groups
    return candidate

def make_problem(catalogs):
    heads,profiles=zip(*catalogs)
    levels=[histogram(decode(p,SLOTS)) for p in profiles]
    # Applying strict cutoff and the stable adaptive codec to the canonical
    # profile reproduces the catalog, independently of its assigned labels.
    for h,level,profile in zip(heads,levels,profiles):
        whole=level+Counter(h.values())
        count=0
        cut=0
        for v in sorted(whole,reverse=True):
            count+=whole[v]
            if count>12: cut=v;break
        assert all(x>cut for x in h.values()) and max(level,default=0)<=cut
        assert encode_runs(level)==profile
    resources=[]
    rowinfo=[]
    families=[]
    for i,level in enumerate(levels):
        family=[]
        for v,n in sorted(level.items()):
            family.append((v,len(resources)))
            resources.append(n); rowinfo.append((i,v))
        families.append(family)
    nameinfo=[]
    fixed=0
    for x in sorted(set().union(*heads)):
        missing=tuple(i for i,h in enumerate(heads) if x not in h)
        weight=prod(h[x] for h in heads if x in h)
        if not missing: fixed+=weight
        elif all(families[i] for i in missing):
            nameinfo.append((x,missing,weight))
    return heads,levels,families,resources,rowinfo,nameinfo,fixed

def inner(problem,rounds=60,integer_polish=False):
    heads,levels,families,supply,rowinfo,names,fixed=problem
    r=len(heads)
    allmask=tuple(range(r))
    groups=defaultdict(list)
    for j,(key,mask,w) in enumerate(names): groups[mask].append((j,w))
    if all(families): groups[allmask].append((-1,1))
    if r==2:
        s0,p1=allocate((heads[0][x] for x in heads[0].keys()-heads[1].keys()), levels[1])
        s1,p0=allocate((heads[1][x] for x in heads[1].keys()-heads[0].keys()), levels[0])
        value=fixed+s0+s1+pair_runs(p0,p1)
        return dict(lower=value,upper=value,rounds=0,columns=0,implicit=0)
    if not groups: return dict(lower=fixed,upper=fixed,rounds=0,columns=0,implicit=0)
    implicit=sum(len(n)*prod(len(families[i]) for i in mask) for mask,n in groups.items())
    price_rows=len(supply)
    capacity=list(supply)+[1]*len(names)
    columns={}
    def add(j,w,rr):
        key=(j,rr)
        if key not in columns:
            lid=rr+((price_rows+j,) if j>=0 else ())
            columns[key]=(w*prod(rowinfo[z][1] for z in rr),lid)
    def align(mask):
        # Canonical rank coupling gives a feasible seed for the restricted LP.
        fs=[iter(reversed(families[i])) for i in mask]
        current=[next(z) for z in fs]
        count=[supply[row] for _,row in current]
        while True:
            yield tuple(row for _,row in current)
            take=min(count)
            for j in range(len(fs)):
                count[j]-=take
                if not count[j]:
                    v=next(fs[j],None)
                    if v is None:return
                    current[j]=v; count[j]=supply[v[1]]
    for mask,keys in groups.items():
        for rr in align(mask):
            for j,w in keys:add(j,w,rr)
    maxval=prod(max([*h.values(),*l.keys()],default=1) for h,l in zip(heads,levels))
    scale=max(1,maxval//1000000)
    shift=(32*r*DENOM*maxval).bit_length()
    best=-1; upper=None
    primal=[]; dual=None
    for step in range(rounds):
        data=list(columns.values()); values=[v for v,rr in data]
        indices=[(i,j) for j,(_,rr) in enumerate(data) for i in rr]
        rr,cc=zip(*indices)
        A=csc_matrix((np.ones(len(rr)),(rr,cc)),shape=(len(capacity),len(data)))
        lp=linprog(-np.array(values,dtype=float)/scale,A_ub=A,b_ub=capacity,bounds=(0,None),method='highs')
        if not lp.success: raise RuntimeError(lp.message)
        prices=[max(0,round(Fraction.from_float(-float(v))*scale*DENOM)) for v in lp.ineqlin.marginals]
        remain=capacity.copy()
        lower=0
        chosen={}
        for j in np.argsort(-lp.x):
            n=int(lp.x[j]+1e-7)
            if not n:break
            c,ids=data[j]
            n=min(n,*(remain[i] for i in ids))
            lower+=n*c
            for i in ids:remain[i]-=n
            if n:chosen[j]=n
        # Multiply aligned remaining anonymous profiles. This extension realizes
        # the selected profits and then places noncontributing leftovers privately.
        tails=[]
        for f in families:
            end=0; runs=[]
            for v,i in reversed(f):
                if remain[i]:
                    end+=remain[i];runs.append((end,v))
            tails.append(runs)
        lower+=run_upper(*tails)
        if lower>best:
            best=lower
            keys=list(columns)
            primal=[[keys[j][0],list(keys[j][1]),n] for j,n in chosen.items()]
        total=sum(n*y for n,y in zip(supply,prices))
        allowances=[0]*(len(names)+1)
        before=len(columns)
        for mask,keys in groups.items():
            pts=chain([[(v,prices[z],z) for v,z in families[i]] for i in mask],shift)
            for j,w in keys:
                z=prices[price_rows+j] if j>=0 else 0
                top=max(w*DENOM*p-cost for p,cost,_ in pts)
                allowances[j]=max(0,top)
                if j>=0:total+=max(0,top)
                elif top>0:total+=top*min(sum(levels[i].values()) for i in mask)
                if top>z:
                    # Add all violated exposed vertices, avoiding a separate
                    # column for combinations outside the price oracle's chain.
                    for p,cost,ids in pts:
                        if w*DENOM*p-cost>z:add(j,w,ids)
        bound=total//DENOM
        if upper is None or bound<upper:
            upper=bound
            dual=[prices[:price_rows],allowances]
        assert upper>=best,(step,upper,best)
        if upper==best or before==len(columns): break
    if integer_polish and best<upper:
        # This integer solve supplies a candidate only. Check the allocation
        # and its profit independently of both solver status and objective.
        from scipy.optimize import Bounds, LinearConstraint, milp
        data=list(columns.values())
        entries=[(i,j) for j,(_,rows) in enumerate(data) for i in rows]
        rid,cid=zip(*entries)
        matrix=csc_matrix((np.ones(len(entries)),(rid,cid)),shape=(len(capacity),len(data)))
        candidate=milp(-np.array([v/scale for v,_ in data]), integrality=np.ones(len(data)),
            bounds=Bounds(0,np.inf), constraints=LinearConstraint(matrix,0,capacity),
            options={'time_limit':15,'mip_rel_gap':0.0})
        if candidate.x is not None:
            remain=capacity.copy()
            value=0
            trial=[]
            for ((j,rows),(profit,uses),x) in zip(columns,data,candidate.x):
                amount=max(0,min(round(x),*(remain[i] for i in uses)))
                if amount:
                    trial.append([j,list(rows),amount])
                    value+=profit*amount
                    for i in uses:remain[i]-=amount
            tails=[]
            for family in families:
                end=0
                runs=[]
                for v,i in reversed(family):
                    if remain[i]:
                        end+=remain[i]
                        runs.append((end,v))
                tails.append(runs)
            value+=run_upper(*tails)
            if value>best:
                best,primal=value,trial
            assert upper>=best
    return dict(lower=best+fixed,upper=upper+fixed,rounds=step+1,columns=len(columns),implicit=implicit,
                proof=[primal,dual])
