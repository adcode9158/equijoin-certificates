"""Worst-case cardinality from per-relation named frequencies and capped tails."""
from collections import Counter
from itertools import product
from math import prod
import heapq
from fractions import Fraction

import numpy as np
from scipy.optimize import linprog
from scipy.sparse import csc_matrix


def summary(counts, k):
    pairs = sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))
    tail = pairs[k:]
    return dict(pairs[:k]), (sum(c for _, c in tail), len(tail), tail[0][1] if tail else 0)


def levels(tail):
    mass, distinct, cap = tail
    if not distinct:
        if mass:
            raise ValueError("nonempty mass on empty support")
        return {}
    if not (0 < distinct <= mass <= distinct * cap):
        raise ValueError("infeasible tail")
    if cap == 1:
        return {1: distinct}
    full, rem = divmod(mass - distinct, cap - 1)
    counts = Counter({cap: full, 1: distinct - full - bool(rem)})
    if rem:
        counts[rem + 1] += 1
    return dict(+counts)


def pair_runs(left, right):
    """Sum of rankwise products between descending run-length vectors."""
    a, b = (iter(sorted(x.items(), reverse=True)) for x in (left, right))
    va, na = next(a, (0, 0))
    vb, nb = next(b, (0, 0))
    total = 0
    while na and nb:
        take = min(na, nb)
        total += take * va * vb
        na -= take
        nb -= take
        if not na:
            va, na = next(a, (0, 0))
        if not nb:
            vb, nb = next(b, (0, 0))
    return total


def allocate(values, pool):
    pool = Counter(pool)
    score = 0
    donors = iter(sorted(pool, reverse=True))
    donor = next(donors, None)
    for v in sorted(values, reverse=True):
        if donor is None:
            break
        score += v * donor
        pool[donor] -= 1
        if not pool[donor]:
            del pool[donor]
            donor = next(donors, None)
    return score, pool


def binary(heavy, tails):
    a, b = heavy
    shared = sum(a[x] * b[x] for x in a.keys() & b.keys())
    score_a, left_b = allocate((a[x] for x in a.keys() - b.keys()), levels(tails[1]))
    score_b, left_a = allocate((b[x] for x in b.keys() - a.keys()), levels(tails[0]))
    return shared + score_a + score_b + pair_runs(left_a, left_b)


def packing(heavy, tails, record=False):
    supplies = []
    tokens = []
    description = []
    for tail in tails:
        tokens.append([])
        for value, count in levels(tail).items():
            tokens[-1].append((value, len(supplies)))
            supplies.append(count)
    constant, columns = 0, []
    for key in [*sorted(set().union(*heavy)), None]:
        # None denotes a fresh key. SQL nulls are excluded before summarization.
        fixed = [h.get(key) for h in heavy]
        if all(v is not None for v in fixed):
            constant += prod(fixed)
            continue
        choices = [tokens[i] for i,v in enumerate(fixed) if v is None]
        if any(not options for options in choices):
            continue
        name_rows = ()
        if key is not None:
            name_rows = (len(supplies),)
            supplies.append(1)
        base = prod(v for v in fixed if v is not None)
        for assignment in product(*choices):
            resources = name_rows + tuple(row for _,row in assignment)
            columns.append((base * prod(val for val,_ in assignment), resources))
            if record:
                description.append((key,assignment))
    if record:
        return constant,supplies,columns,description
    return constant, supplies, columns


def solve_pack(supplies, columns, node_limit, record=False):
    """LP prices suggest certificates. All upper/lower values are checked in integers."""
    if not columns:
        result=dict(lower=0, upper=0, nodes=0)
        if record:
            result.update(prices=[0]*len(supplies),chosen=[])
        return result
    values = [v for v,_ in columns]
    ix = [(row,j) for j,(_,rows) in enumerate(columns) for row in rows]
    rr, cc = zip(*ix)
    matrix = csc_matrix((np.ones(len(rr)), (rr,cc)), shape=(len(supplies),len(columns)))
    ub = tuple(min(supplies[i] for i in rows) for _,rows in columns)
    lo = (0,)*len(ub)
    # A scale change does not affect the optimizer; it can affect numerical precision.
    scale = max(1, max(values) // 1000000)
    objective = -np.array([v / scale for v in values])
    denom = 1 << 28
    visits = 0
    best = 0
    best_choices = [0]*len(columns)
    root_prices = []
    # Keep a proof object only for an unbranched root. Separate branch prices
    # would be needed to certify a general search tree outside this process.
    if record and node_limit != 1:
        raise ValueError("root certificate export requires node_limit=1")
    def relax(lower, upper):
        nonlocal visits, best, best_choices, root_prices
        visits += 1
        slack = supplies.copy()
        base = sum(v*n for v,n in zip(values,lower))
        for n,(_,rows) in zip(lower,columns):
            if n:
                for row in rows:
                    slack[row] -= n
        if min(slack) < 0:
            return None
        room = [min(b-a, min(slack[i] for i in rows)) for a,b,(_,rows) in zip(lower,upper,columns)]
        lp = None
        if max(slack)<=10**18 and max(room)<=10**18:
            lp = linprog(objective, A_ub=matrix, b_ub=slack, bounds=list(zip([0]*len(room),room)), method="highs")
        if lp is not None and lp.success:
            raw = lp.x
            prices = [max(0,round(Fraction.from_float(-float(y))*scale*denom)) for y in lp.ineqlin.marginals]
        else:
            raw = np.zeros(len(room))
            prices = [0]*len(slack)
        if record and visits==1:
            root_prices = prices
        cost = sum(s*y for s,y in zip(slack,prices))
        for (value,rows),cap in zip(columns,room):
            cost += cap * max(0, value*denom - sum(prices[row] for row in rows))
        bound = base + cost//denom
        left = slack.copy()
        rem = room.copy()
        score = base
        order = sorted(range(len(room)),key=lambda j: values[j],reverse=True)
        for from_lp in (True,False):
            for j in order:
                if not rem[j]:
                    continue
                value,rows = columns[j]
                n = min(rem[j], min(left[i] for i in rows))
                if from_lp:
                    n = min(n,int(max(0,raw[j])+1e-8))
                rem[j] -= n
                score += n*value
                for i in rows:
                    left[i] -= n
        if score>=best:
            best=score
            if record:
                best_choices=[a+b-c for a,b,c in zip(lower,room,rem)]
        assert score <= bound
        if bound <= best:
            return None
        candidates = [j for j in order if room[j] and abs(raw[j]-round(raw[j]))>1e-7]
        if candidates:
            j = max(candidates,key=lambda k: min(raw[k]%1,1-raw[k]%1))
            split = lower[j]+max(0,min(room[j]-1,int(raw[j])))
        else:
            j = next((k for k in order if room[k]),None)
            if j is None:
                return None
            split = lower[j]+room[j]//2
        return (-bound, visits, lower, upper, j, split)
    root = relax(lo,ub)
    queue = [root] if root else []
    while queue and -queue[0][0]>best and visits+2<=node_limit:
        _,_,lower,upper,j,split = heapq.heappop(queue)
        l, u = list(lower),list(upper)
        l[j], u[j] = split+1,split
        for a,b in ((lower,tuple(u)),(tuple(l),upper)):
            node = relax(a,b)
            if node:
                heapq.heappush(queue,node)
    result=dict(lower=best,upper=max(best,-queue[0][0] if queue else best),nodes=visits)
    if record:
        result.update(chosen=best_choices,prices=root_prices)
    return result


def bounds(heavy, tails, node_limit=127):
    if len(heavy)!=len(tails) or len(heavy)<2:
        raise ValueError("expected at least two matching relation descriptions")
    if any(None in h or any(v<=0 for v in h.values()) for h in heavy):
        raise ValueError("expected non-null keys with positive frequencies")
    if len(heavy)==2 and all(not h or not t[1] or min(h.values())>=min(t[2],t[0]-t[1]+1) for h,t in zip(heavy,tails)):
        exact = binary(heavy,tails)
        return dict(lower=exact,upper=exact,nodes=0,columns=0)
    constant, supplies, columns = packing(heavy,tails)
    result = solve_pack(supplies,columns,node_limit)
    for key in ('lower','upper'):
        result[key] += constant
    return dict(result,columns=len(columns))
