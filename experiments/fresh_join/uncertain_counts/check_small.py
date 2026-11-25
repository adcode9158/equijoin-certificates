"""Independent finite-world checks for both information regimes and hardness."""
from itertools import product, combinations_with_replacement
from math import lcm, prod
from random import Random

from box_certificates import oracle
from one_total import minimum_one_total


def brute(labels, worlds, truth, budget):
    opposite=[sum((a!=b)<<i for i,(a,b) in enumerate(zip(labels,w)))
              for w,value in worlds if (value<=budget)!=(truth<=budget)]
    return min(mask.bit_count() for mask in range(1<<len(labels)) if all(mask&diff for diff in opposite))


def test_boxes_and_one_total():
    g=Random(1403)
    checks=with_total=0
    for _ in range(115):
        n,arity=g.choice(((2,2),(2,3),(3,2)))
        cap=tuple(g.randint(1,2) for i in range(n*arity))
        tuples=list(product(*(range(c+1) for c in cap)))
        worlds=[(r,sum(prod(r[j:j+arity]) for j in range(0,len(r),arity))) for r in tuples]
        for labels,truth in g.sample(worlds, min(6,len(worlds))):
            max_result=sum(prod(cap[j:j+arity]) for j in range(0,len(cap),arity))
            for budget in {truth, max(0,truth-1), g.randrange(max_result+1)}:
                caps=[cap[j:j+arity] for j in range(0,len(cap),arity)]
                actual=[labels[j:j+arity] for j in range(0,len(cap),arity)]
                opt=oracle(caps,actual,list(range(arity)),budget)
                assert opt==brute(labels,worlds,truth,budget)
                checks+=1
                if truth<=budget:
                    m=sum(labels[::arity])
                    consistent=[(w,v) for w,v in worlds if sum(w[::arity])==m]
                    prepared=[(c[0],a[0],list(zip(c[1:],a[1:]))) for c,a in zip(caps,actual)]
                    best=minimum_one_total(prepared,budget)
                    assert best==brute(labels,consistent,truth,budget)
                    with_total+=1
    return checks,with_total


def test_hardness():
    count=0
    for n in range(1,5):
        for caps in combinations_with_replacement(range(1,5),n):
            scale=lcm(*caps)
            degree=[scale//a for a in caps]
            subsets={sum(c for c,b in zip(caps,flags) if b) for flags in product((0,1),repeat=n)}
            groups={}
            for r in product(*(range(c+1) for c in caps)):
                groups.setdefault(sum(r),[]).append(r)
            for total in range(1,sum(caps)):
                feasible=groups[total]
                maximum=max(sum(w*x*y for w,x,y in zip(degree,a,b)) for a in feasible for b in feasible)
                observed=sum(w*x*y for w,x,y in zip(degree,feasible[0],feasible[-1]))
                assert observed<scale*total
                assert (maximum==scale*total)==(total in subsets)
                count+=1
    return count


if __name__=="__main__":
    print("Independent finite box / one-total decisions",test_boxes_and_one_total())
    print("Finite instances of the two-total reduction",test_hardness())

