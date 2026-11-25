"""Directly enumerate all bounded-cardinality memberships and proving subsets."""
from itertools import product,combinations_with_replacement
from rounding import minima


def main():
    checked=0
    for n in range(1,6):
        for seq in combinations_with_replacement((0,1,3),n):
            weights=dict(enumerate(seq))
            worlds=list(range(1<<n))
            mass=[sum(w for i,w in weights.items() if mask>>i&1) for mask in worlds]
            for true in worlds:
                passed={i for i in weights if true>>i&1}
                caps=list(range(len(passed),n+1))
                for budget in sorted({v for v in mass if v>=mass[true]}):
                    computed=minima(weights,passed,caps,budget)
                    for cap,answer in zip(caps,computed):
                        opposite=[mask^true for mask in worlds if mask.bit_count()<=cap and mass[mask]>budget]
                        best=min(p.bit_count() for p in worlds if all(p&d for d in opposite))
                        assert answer==best
                        checked+=1
    print('Upper-cardinality instance/cap/budget triples checked:',checked)

if __name__=='__main__':
    main()

