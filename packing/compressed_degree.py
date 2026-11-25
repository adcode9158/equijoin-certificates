"""Budget-matched anonymous degree-envelope control for the STATS-CEB cases."""
from itertools import groupby

from baselines import run_upper
from bounds import summary, bounds



def ends(ndv, slots):
    previous = 0
    for j in range(1, slots + 1):
        # The last endpoint is exact. Each bin is nonempty. The boundaries
        # depend only on the shared slot count and the stored NDV.
        end = ndv if j == slots else min(ndv - slots + j,
                                         max(previous + 1, round(ndv ** (j / slots))))
        yield end
        previous = end


def encode(frequencies, slots):
    degrees = sorted(frequencies, reverse=True)
    groups = [(value, sum(1 for _ in group)) for value, group in groupby(degrees)]
    if len(groups) <= slots:
        # Sign bit of NDV distinguishes exact run-length encoding.
        return -len(degrees), groups
    previous = 0
    bins = []
    for end in ends(len(degrees), slots):
        bins.append((degrees[previous], sum(degrees[previous:end])))
        previous = end
    return len(degrees), bins


def decode(catalog, slots):
    tag, bins = catalog
    runs = []
    pos = 0
    if tag <= 0:
        for value, count in bins:
            pos += count
            runs.append((pos, value))
        return runs
    for j, end in enumerate(ends(tag, slots)):
        cap, mass = bins[j]
        floor = bins[j + 1][0] if j + 1 < slots else 1
        if cap != floor:
            full, remainder = divmod(mass - (end - pos) * floor, cap - floor)
            if full:
                pos += full
                runs.append((pos, cap))
            if remainder:
                pos += 1
                runs.append((pos, floor + remainder))
        if end != pos:
            runs.append((end, floor))
            pos = end
    return runs
