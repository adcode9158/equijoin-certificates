"""Partitioned degree-envelope and full anonymous-degree bounds for bag joins."""

from collections.abc import Mapping, Sequence
from functools import lru_cache
from math import prod


Bucket = tuple[int, int, int]  # number of rows, distinct keys, maximum frequency
MASK64 = (1 << 64) - 1


def hash_summary(counts: Mapping[int, int], buckets: int, seed: int = 0) -> tuple[Bucket, ...]:
    """Build a 3*buckets-word synopsis; the common bucket count and seed are public."""
    if buckets < 1:
        raise ValueError("positive bucket count required")
    stats = [[0, 0, 0] for _ in range(buckets)]
    for key, frequency in counts.items():
        if frequency <= 0:
            raise ValueError("frequency maps must contain only positive multiplicities")
        # SplitMix64 on the normalized integer key. Hash collisions preserve safety.
        mix = (int(key) + seed + 0x9e3779b97f4a7c15) & MASK64
        mix = ((mix ^ (mix >> 30)) * 0xbf58476d1ce4e5b9) & MASK64
        mix = ((mix ^ (mix >> 27)) * 0x94d049bb133111eb) & MASK64
        bucket = stats[(mix ^ (mix >> 31)) % buckets]
        frequency = int(frequency)
        bucket[0] += frequency
        bucket[1] += 1
        bucket[2] = max(bucket[2], frequency)
    return tuple(tuple(bucket) for bucket in stats)


def concentrated_runs(rows: int, distinct: int, maximum: int) -> list[tuple[int, int]]:
    """(exclusive rank end, frequency) runs of the prefix-maximal integer sequence."""
    if distinct == 0:
        if rows or maximum:
            raise ValueError("invalid empty bucket")
        return []
    if not (1 <= maximum <= rows - distinct + 1 and rows <= distinct * maximum):
        raise ValueError("inconsistent bucket counts")
    if maximum == 1:
        return [(distinct, 1)]
    full, remainder = divmod(rows - distinct, maximum - 1)
    runs = [(full, maximum)]
    if remainder:
        runs.append((full + 1, 1 + remainder))
    if full + bool(remainder) < distinct:
        runs.append((distinct, 1))
    return runs


def run_upper(*runs: Sequence[tuple[int, int]]) -> int:
    """Integral of the pointwise product of nonincreasing step functions on ranks."""
    if not runs:
        raise ValueError("supply one or more sequences")
    if any(not seq for seq in runs):
        return 0
    cursors = [0] * len(runs)
    previous = 0
    result = 0
    while True:
        current = [seq[i] for i, seq in zip(cursors, runs)]
        end = min(endpoint for endpoint, _ in current)
        result += (end - previous) * prod(value for _, value in current)
        previous = end
        for j, (endpoint, _) in enumerate(current):
            if endpoint == end:
                cursors[j] += 1
                if cursors[j] == len(runs[j]):
                    return result


def hash_upper(*summaries: Sequence[Bucket]) -> int:
    if not summaries or any(len(s) != len(summaries[0]) for s in summaries):
        raise ValueError("supply one or more aligned summaries")
    return sum(run_upper(*(concentrated_runs(*bucket) for bucket in group))
               for group in zip(*summaries))


def degree_upper(*counts: Mapping[int, int]) -> int:
    """Unbudgeted anonymous degree-sequence comparator."""
    if not counts:
        raise ValueError("supply one or more relations")
    degrees = [sorted(map(int, c.values()), reverse=True) for c in counts]
    return sum(prod(values) for values in zip(*degrees))


def cautious_binary(left: Mapping[int, int], right: Mapping[int, int],
                    left_rows: int, right_rows: int) -> int:
    """PostBOUND BTW 2023, Algorithm 1, for a binary unfiltered bag join.

    Inputs are named top-k counts and total row counts. Fallback frequencies
    are the last reported frequencies. Memoization removes repeated permutations
    of the same prefix set. The number of subsets can still be exponential.
    """
    if not left_rows or not right_rows:
        return 0
    if not left or not right:
        raise ValueError("PostBOUND needs a nonempty top list for each nonempty relation")
    cap_l, cap_r = min(left.values()), min(right.values())
    keys = sorted(left.keys() | right.keys())
    pairs = sorted(((left.get(x, cap_l), right.get(x, cap_r)) for x in keys),
                   key=lambda pair: pair[0] * pair[1], reverse=True)

    @lru_cache(maxsize=None)
    def search(mask, rows_l, rows_r):
        if not rows_l or not rows_r:
            return 0
        if not mask:
            return min(rows_l * min(rows_r, cap_r), rows_r * min(rows_l, cap_l))
        # Search the largest local contributions first. A UES cutoff safely
        # prunes the remaining permutations if a branch already attains it.
        max_l, max_r = cap_l, cap_r
        indices = mask
        while indices:
            bit = indices & -indices
            a, b = pairs[bit.bit_length() - 1]
            max_l, max_r = max(max_l, a), max(max_r, b)
            indices ^= bit
        cutoff = min(rows_l * min(rows_r, max_r), rows_r * min(rows_l, max_l))
        remaining = mask
        best = 0
        while remaining:
            bit = remaining & -remaining
            a, b = pairs[bit.bit_length() - 1]
            u, v = min(a, rows_l), min(b, rows_r)
            best = max(best, u * v + search(mask ^ bit, rows_l - u, rows_r - v))
            if best == cutoff:
                break
            remaining ^= bit
        return best

    return search((1 << len(keys)) - 1, left_rows, right_rows)
