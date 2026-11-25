"""Check the manuscript's decision-tree, corpus, transfer and live grant results."""
import csv
import json
import sys
from pathlib import Path

EVIDENCE = Path(__file__).resolve().parent / "evidence" / "discovery"
sys.path.insert(0, str(EVIDENCE))
from pivotal import test


def rows(filename):
    with (EVIDENCE / filename).open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def discovery():
    assert test() == 4530
    data = rows("online-budget.csv")
    cohort = [r for r in data if r["db"] not in ("financial", "formula_1") and int(r["offline_at_m"]) > 0]
    outcomes = ("offline_combined", "actual_descending_combined", "worst_combined")
    assert (len(cohort), *(sum(int(r[col]) <= 64 for r in cohort) for col in outcomes)) == (45, 36, 27, 24)
    other = [r for r in cohort if r["db"] != "codebase_community"]
    assert (len(other), sum(int(r["offline_combined"]) <= 64 for r in other),
            sum(int(r["worst_combined"]) <= 64 for r in other)) == (22, 18, 14)
    badge = next(r for r in cohort if r["db"] == "codebase_community" and r["question_id"] == "551")
    assert tuple(map(int, (badge[f] for f in ("observed", "offline_at_m", "offline_at_m1",
                                               "worst_at_m", "worst_at_m1")))) == (95, 1, 2874, 18, 5727)
    independent = json.loads((EVIDENCE / "online_cap_two.json").read_text())["q552"]
    assert (independent["cap_one_worst"], independent["cap_two_worst"]) == (18, 5727)
    spider = next(r for r in rows("spider-summary.csv")
                  if r["budget"] == "100" and r["parser"] == "with_sql_equality")
    assert tuple(int(spider[k]) for k in ("cases", "fitting", "exact_positive", "extra_increases")) == (18,17,0,0)


def physical():
    measurements = rows("live_streams.csv")
    attempts = rows("live_attempts.csv")
    saving = []
    for cohort, high in (("A", 12), ("B", 13)):
        first = rows("first-grants.csv" if cohort == "A" else "replication-grants.csv")
        for turn in ("0", "1"):
            frozen = {r["method"]: r for r in first if r["round"] == turn}
            cert, native = frozen["certificate_cold"], frozen["native_matched"]
            assert int(cert["high_grants"]) == int(native["high_grants"]) == high
            assert int(cert["spill_or_failure"]) == (5 if cohort=="A" else 4)
            assert int(native["spill_or_failure"]) == 6
            assert (float(cert["total_ms"]) <= float(native["total_ms"])) == (cohort == "A")
            assert float(cert["preflight_ms"]) < float(frozen["group_sql"]["preflight_ms"])
            streams = {r["policy"]: r for r in measurements if r["cohort"] == cohort and r["round"] == turn}
            cert, native = streams["certificate"], streams["native"]
            assert int(cert["successes"]) == int(native["successes"]) == 32
            assert int(cert["initial_high"]) == int(native["initial_high"]) == high
            assert (int(cert["attempts"]), int(native["attempts"])) == (32, 32 if cohort == "A" else 34)
            sub = [r for r in attempts if r["cohort"] == cohort and r["round"] == turn]
            completed = {p : {(r["case"], r["rows"], r["checksum"]) for r in sub
                               if r["status"] == "completed" and r["policy"] == p} for p in streams}
            assert len(completed["certificate"]) == 32 and completed["certificate"] == completed["native"]
            saving.append(100 * (1 - float(cert["wall_ms"]) / float(native["wall_ms"])))
    assert (round(min(saving), 1), round(max(saving), 1)) == (4.3, 7.2)
    assert all(int(r["failures"]) == 0 for r in rows("approximate-grants.csv")
               if r["placement"] == "matched" and r["method"] == "head_ratio")
    bird = { (r["layout"],r["policy"]):r for r in rows("bird-timing.csv")
             if r["cohort"] == "primary" and r["budget"] == "100"}
    assert all(int(r["cases"]) == 105 for r in bird.values())
    assert [round(float(bird[layout, method]["median_ms"]), 2) for layout in ("released", "cover")
            for method in ("native_cap", "challenger")] == [51.18, 84.45, 10.55, 15.94]


if __name__ == "__main__":
    discovery()
    physical()
    print("Verified 4,530 decision trees, BIRD and Spider counts, native timings, and matched DuckDB completions.")
