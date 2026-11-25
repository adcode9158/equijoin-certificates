"""Exact maximization of a product minus separable integer prices."""
from decimal import Decimal, localcontext, ROUND_HALF_EVEN
from fractions import Fraction
from functools import lru_cache
from math import prod


@lru_cache(maxsize=32768)
def log_coordinate(value, shift):
    # Decimal.ln is correctly rounded. Use more than enough decimal digits
    # to keep |coordinate - 2**shift * ln(value)| below one unit.
    with localcontext() as ctx:
        ctx.prec = len(str(1 << shift)) + len(str(value.bit_length())) + 12
        return int((Decimal(value).ln() * (1 << shift)).to_integral_value(rounding=ROUND_HALF_EVEN))


def chain(families, shift):
    """Vertices of the lower boundary of a sum of planar convex hulls."""
    hulls = []
    events = []
    for i, family in enumerate(families):
        hull = []
        for value, price, row in family:  # strictly increasing positive values
            p = (log_coordinate(value, shift), price, value, row)
            while len(hull) >= 2:
                a,b = hull[-2:]
                if (b[1]-a[1])*(p[0]-b[0]) < (p[1]-b[1])*(b[0]-a[0]):
                    break
                hull.pop()
            hull.append(p)
        hulls.append(hull)
        for a,b in zip(hull,hull[1:]):
            events.append((Fraction(b[1]-a[1],b[0]-a[0]), i, b))
    current=[h[0] for h in hulls]
    def entry():
        return prod(p[2] for p in current),sum(p[1] for p in current),tuple(p[3] for p in current)
    result=[entry()]
    for _,i,b in sorted(events):
        current[i]=b
        result.append(entry())
    return result
