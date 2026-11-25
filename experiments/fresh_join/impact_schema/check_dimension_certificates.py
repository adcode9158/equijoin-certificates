"""Enumerate fixed-size memberships and independently find minimum proving subsets."""
from itertools import combinations_with_replacement

from dimension_certificates import high_weight_first, minimum_certificate


def main():
    checked=0
    for n in range(1,7):
        for weights in combinations_with_replacement((0,1,3),n):
            maps=dict(enumerate(weights))
            universe=range(1<<n)
            values=[sum(w for i,w in enumerate(weights) if mask>>i&1) for mask in universe]
            for actual,truth in enumerate(values):
                passed={i for i in maps if actual>>i&1}
                worlds=[w for w in universe if w.bit_count()==len(passed)]
                # Every nontrivial decision on these integer outcomes changes
                # at some observed value. Include negative instances for the policy.
                for budget in sorted({values[w] for w in worlds}):
                    _,decision=high_weight_first(maps,len(passed),passed.__contains__,budget)
                    assert decision==(truth<=budget)
                    invalid=[w^actual for w in worlds if (values[w]<=budget)!=decision]
                    brute=min(m.bit_count() for m in universe if all(m&delta for delta in invalid))
                    cert=(minimum_certificate(maps,passed,budget) if decision else
                          minimum_certificate(maps,maps.keys()-passed,sum(weights)-budget-1))
                    assert len(cert)==brute
                    checked+=1
    print('Instance/budget decisions and minimum certificates checked:',checked)


if __name__=='__main__':
    main()
