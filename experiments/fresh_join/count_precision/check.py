"""Enumerate both allowed worlds and disclosures and compare the inverse precision curve."""
from itertools import combinations_with_replacement
from curve import PrecisionCurve

def main():
    checked=0
    for n in range(1,6):
        for packed in combinations_with_replacement((0,1,3),n):
            weights=dict(enumerate(packed))
            masks=range(1<<n)
            mass={m:sum(w for i,w in weights.items() if m>>i&1) for m in masks}
            for real in masks:
                passed={i for i in weights if real>>i&1}
                for budget in sorted({v for v in mass.values() if v>=mass[real]}):
                    curve=PrecisionCurve(weights,passed,budget)
                    answers={}
                    for cap in range(len(passed),n+1):
                        diffs=[other^real for other in masks if other.bit_count()<=cap and mass[other]>budget]
                        answers[cap]=min(s.bit_count() for s in masks if all(s&diff for diff in diffs))
                        assert curve.minimum(cap)==answers[cap]
                        checked+=1
                    for k in range(n+1):
                        expected=max((cap for cap,c in answers.items() if c<=k),default=None)
                        assert curve.largest_cap(k)==expected
    print('Independent feasible-world and disclosure checks:',checked)
if __name__=='__main__':
    main()

