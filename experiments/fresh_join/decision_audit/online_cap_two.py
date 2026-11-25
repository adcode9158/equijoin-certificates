"""Exact deterministic worst-case point-query cost under a cap of two memberships."""
import json
import sqlite3
from functools import lru_cache
from itertools import combinations_with_replacement
from pathlib import Path

HERE = Path(__file__).resolve().parent


from badge import question_552_name

def worst_case(weights, budget):
    """Count individually over-budget keys and members of over-budget light pairs."""
    heavy = sum(w > budget for w in weights)
    light = sorted((w for w in weights if w <= budget), reverse=True)
    if len(light) < 2 or light[0] + light[1] <= budget:
        return heavy
    return heavy + sum(w + light[0] > budget for w in light)


def descending(items, budget, cap, read):
    """Call read only for individual probes. Items contain the public weights."""
    ranked = sorted(items, key=lambda it: (-it[1], it[0]))
    reads = total = 0
    for pos, (key, weight) in enumerate(ranked):
        if total > budget:
            return False, reads
        upper = total + sum(w for _, w in ranked[pos:pos+cap])
        if upper <= budget:
            return True, reads
        reads += 1
        if read(key):
            total += weight
            cap -= 1
    return total <= budget, reads


@lru_cache(None)
def minimax(n, accepting):
    """Enumerate every legal possible world and every next unit-cost probe."""
    worlds = [s for s in range(1 << n) if s.bit_count() <= 2]
    full = (1 << len(worlds)) - 1
    bit_tests = [sum(1 << j for j,s in enumerate(worlds) if s & 1 << i) for i in range(n)]

    @lru_cache(None)
    def optimal_depth(possible):
        if not possible & accepting or not possible & (full ^ accepting):
            return 0
        best = n
        for test in bit_tests:
            yes = possible & test
            if yes == possible or not yes:
                continue
            no = possible ^ yes
            cost = 1 + max(optimal_depth(yes), optimal_depth(no))
            best = min(best, cost)
        return best
    return optimal_depth(full)


def test():
    comparisons = worlds_tested = 0
    for n in range(8):
        worlds = [s for s in range(1 << n) if s.bit_count() <= 2]
        for weights in combinations_with_replacement([0, 1, 3, 6], n):
            sizes = [sum(w for i,w in enumerate(weights) if s & (1 << i)) for s in worlds]
            for budget in sorted(set(sizes)):
                accepts = sum(1 << j for j,v in enumerate(sizes) if v <= budget)
                independent = minimax(n, accepts)
                observed_max = 0
                for s, size in zip(worlds, sizes):
                    decision, reads = descending(enumerate(weights), budget, 2, lambda i: s & (1 << i))
                    assert decision == (size <= budget)
                    observed_max = max(observed_max, reads)
                    worlds_tested += 1
                assert independent == observed_max == worst_case(weights, budget)
                comparisons += 1
    return dict(weight_budget_pairs=comparisons, distinct_labeled_decision_problems=minimax.cache_info().currsize,
                descending_worlds=worlds_tested)


def bird():
    path = HERE.parents[1] / "inputs/bird/codebase_community.sqlite"
    name = question_552_name(path.parent)
    with sqlite3.connect(path.as_uri()+"?mode=ro&immutable=1", uri=True) as db:
        items = list(db.execute("""SELECT u.Id, coalesce(b.n,0) FROM users u LEFT JOIN
            (SELECT UserId, count(*) n FROM badges GROUP BY UserId) b ON b.UserId=u.Id"""))
        sql = "SELECT DisplayName = ? FROM users WHERE Id = ?"
        def point(key):
            return bool(db.execute(sql, (name,key)).fetchone()[0])
        actual = {}
        for cap in (1,2):
            result, reads = descending(items, 100, cap, point)
            assert result
            actual[cap] = reads
    ws = [w for _,w in items]
    light = sorted((w for w in ws if w <= 100), reverse=True)
    return dict(keys=len(items), heavy=sum(w > 100 for w in ws), top_light=light[:2],
                nonisolated_light=sum(w+light[0]>100 for w in light),
                cap_one_worst=sum(w > 100 for w in ws), cap_two_worst=worst_case(ws,100),
                actual_descending_sql_probes=actual)


if __name__ == "__main__":
    observations = dict(validation=test(), q552=bird())
    output = HERE / "online_cap_two.json"
    output.write_text(json.dumps(observations, indent=2)+"\n",encoding="utf-8")
    print(output.read_text())
