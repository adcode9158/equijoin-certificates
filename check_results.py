"""Recompute the manuscript's headline counts from the included recorded rows."""
import csv
import json
from collections import Counter
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parent


def records(path):
    with (ROOT / path).open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def catalog_results():
    cases = records("evidence/all-cases.csv")
    assert len({r["case_id"] for r in cases}) == len(cases) == 1605
    bounds = [(int(r["original_lower"]), int(r["original_upper"])) for r in cases]
    assert all(0 < lo <= hi for lo, hi in bounds)
    closed = sum(lo == hi for lo, hi in bounds)
    gap_percent = 100 * max((hi - lo) / lo for lo, hi in bounds)
    full = [r for r in cases if r["full_lines"]]
    fit = [r for r in full if int(r["actual"]) <= 10_000_000]
    certified = [r for r in fit if int(r["original_upper"]) <= 10_000_000]
    excluded = {r["case_id"] for r in fit if int(r["original_lower"]) > 10_000_000}
    assert (closed, len(full), len(fit), len(certified), len(excluded)) == (1599, 86, 59, 18, 41)
    assert gap_percent < 0.0044
    hard = records("evidence/hard-41-certified.csv")
    assert len(hard) == 41 and {r["case_id"] for r in hard} == excluded
    assert sum(int(r["compressed_upper"]) <= 10_000_000 for r in hard) == 5
    assert sum(int(r["exact_degree_floor"]) > 10_000_000 for r in hard) == 36
    print(f"STATS: {closed}/{len(cases)} closed, maximum relative gap {gap_percent:.8f}%.")
    print(f"Full queries: {len(certified)}/{len(fit)} certified; {len(excluded)} over-budget witnesses.")
    releases = [r for r in records("evidence/published-estimates.csv") if r["first"] == "1"]
    assert len(releases) == len(full)
    print("Matched full queries: median ratio / below witness / below observed (one-row tolerance)")
    for method in ("profile", "safebound", "lpbound", "corr_exact", "corr_lowrank15000", "corr_sketch512"):
        ratio = median(float(r[method]) / int(r["truth"]) for r in releases)
        below = [sum(float(r[method]) + 1 < int(r[key]) for r in releases)
                 for key in ("profile_witness", "truth")]
        print(f"  {method}: {ratio:.2f} / {below[0]} / {below[1]}")


def template_results():
    decisions = records("heldout-results/decisions.csv")
    sizes = records("heldout-results/serialized-bytes.csv")
    methods = ("single_column", "four_equal_groups", "four_area_plus_equality", "nonnull_first_then_equality")
    for dataset, year, budget in [("STATS-CEB", "", 10_000_000), ("Lahman", "2024", 1_000_000),
                                  ("Lahman", "2025", 1_000_000)]:
        cohort = [r for r in decisions if (r["dataset"], r["snapshot"]) == (dataset, year)]
        banks = [r for r in sizes if (r["dataset"], r["snapshot"]) == (dataset, year)]
        assert len({r["case_id"] for r in cohort}) == len(cohort)
        fitting = sum(int(r["actual"]) <= budget for r in cohort)
        assert fitting == (1391 if dataset == "STATS-CEB" else 231)
        for method in methods:
            if not cohort[0][method]:
                continue
            admitted = [r for r in cohort if r[method] == "1"]
            assert all(int(r["actual"]) <= budget for r in admitted)
            byte_counts = [int(r[method]) for r in banks]
            assert max(byte_counts) <= 16144
            summary = f"{len(admitted)}/{fitting}, {median(byte_counts):g} median bytes"
            if dataset == "STATS-CEB":
                summary += f", {sum(r['full'] == '1' for r in admitted)}/59 full"
            print(f"{dataset} {year} {method}: {summary}")


def stream_results():
    blocks = records("evidence/paired-blocks.csv")
    audits = json.loads((ROOT / "evidence/cohort-verification.json").read_text())
    for stream, audit in audits.items():
        arrivals = [r for r in records(f"evidence/{stream}/by-arrival.csv") if r["phase"] == "test"]
        assert len(arrivals) == audit["test"] and audit["identical_compiled_bytes"]
        assert audit["same_signature_in_all_12_arms"] and audit["tie_does_not_straddle_split"]
        timing = [r for r in blocks if r["stream"] == stream]
        budget, = {int(r["budget_rows"]) for r in timing}
        for r in arrivals:
            assert (r["single_route"], r["single_admit"]) == (r["pair_route"], r["pair_admit"])
            if r["truth_status"] == "invalid":
                assert r["single_route"] == "invalid" and r["single_admit"] == ""
            else:
                count = int(r.get("exact_rows", r.get("original_rows_or_capped_witness")))
                assert (r["single_admit"] == "True") == (count <= budget)
        paths = Counter(r["single_route"] for r in arrivals)
        by_arm = {s: {int(r["block"]): float(r["charged_ms"]) for r in timing if r["arm"] == s}
                  for s in ("single", "pair")}
        assert by_arm["single"].keys() == by_arm["pair"].keys() == set(range(1, 7))
        for r in timing:
            assert int(r["heldout_fallbacks"]) == paths["exact"]
            assert int(r["heldout_false_admits"]) == int(r["heldout_unchecked_admits"]) == 0
            assert int(r["hard_limit_bytes"]) == 256 * 2**20
            assert int(r["refresh_events"]) == 0 and float(r["refresh_ms"]) == 0
        delta = median(by_arm["single"][i] - by_arm["pair"][i] for i in by_arm["single"])
        costs = [median(x.values()) for x in by_arm.values()]
        print(f"{stream}: {len(arrivals)} held out, {paths['exact']} fallbacks per policy, "
              f"{paths['invalid']} invalid; {costs[0]:.1f}/{costs[1]:.1f} ms, paired saving {delta:.2f} ms.")


if __name__ == "__main__":
    catalog_results()
    template_results()
    stream_results()
