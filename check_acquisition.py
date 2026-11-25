"""Reaggregate the certificate and degree-cap experiments reported in the manuscript."""
import csv
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parent / "evidence" / "acquisition"

def rows(name):
    with (ROOT / name).open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

def main():
    fits = [r for r in rows("bird.csv") if r["budget"] == "100" and r["fits"] == "1"
            and r["dataset"] not in ("formula_1","financial")]
    hard = [r for r in fits if int(r["previous_rich_min"]) > 0]
    other = [r for r in hard if r["dataset"] != "codebase_community"]
    assert (len(fits),len(hard),len(other)) == (80,45,22)
    assert median(int(r["minimum"]) for r in hard) == 486
    assert median(int(r["minimum"]) for r in other) == 272.5
    assert median(int(r["previous_rich_min"]) for r in other) == 1.5
    table = [r for r in rows("rounding.csv") if int(r["exact"]) > 0
             and r["dataset"] not in ("formula_1","financial")]
    fields = ["exact","one_extra","ten_extra","no_count"]
    assert [median(int(r[k]) for r in table) for k in fields] == [1,35,1174.5,17715]
    table = [r for r in table if r["dataset"] != "codebase_community"]
    assert [median(int(r[k]) for r in table) for k in fields] == [1,3,4,9.5]
    costs = [r for r in rows("dimension-certs.csv") if r["min_yes_certificate"] and int(r["min_yes_certificate"])]
    assert len(costs) == 30
    assert sum(int(r["min_yes_certificate"]) for r in costs) == 1604
    assert sum(int(r["adaptive_descending_probes"]) for r in costs) == 1648
    assert sum(r["min_yes_certificate"] == r["adaptive_descending_probes"] for r in costs) == 23
    swaps = rows("dimension-swaps.csv")
    assert len(swaps) == 30 and sum(r["min_disjoint_swaps"] == "1" for r in swaps) == 25
    ties = rows("tie-prefix.csv")
    q84 = next(r for r in ties if r["case_id"] == "query-0084")
    assert (q84["pass_donor"],q84["fail_receiver"],q84["after_swap"],
            q84["suffix_min_certificate"]) == ("742","919","71106139578","346")
    p = rows("precision.csv")
    stats = [r for r in p if r["source"] == "STATS" and int(r["exact"]) > 0]
    assert sum(int(r["none"])-int(r["exact"]) for r in stats) == 1
    benchmark = [r for r in p if r["source"] not in ("STATS","formula_1","financial") and int(r["exact"]) > 0]
    assert len(benchmark) == 45
    assert sum(r["combined"] == r["exact"] for r in benchmark) == 38
    for group, expected in ((benchmark,(63357,805)),
                            ([r for r in benchmark if r["source"]!="codebase_community"],(745,287))):
        assert (sum(int(r["combined"]) for r in group),sum(int(r["exact"]) for r in group))==expected
    print("Verified the BIRD precision table, matched cohorts, STATS witnesses and histogram outcomes.")

if __name__ == "__main__":
    main()
