"""Figure 5: observed vs compatible witness join size for the 86 full queries."""
import csv
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.ticker import FixedLocator, NullFormatter

import style as S

S.apply()
HERE = Path(__file__).resolve().parent
BUDGET = 10_000_000
points = {key: [] for key in ("certified", "fits_witness_over_budget", "observed_over_budget")}
with (HERE.parent / "evidence" / "all-cases.csv").open(newline="", encoding="utf-8") as source:
    for row in csv.DictReader(source):
        if not row["full_lines"]:
            continue
        actual, lower, upper = (int(row[field]) for field in ("actual", "original_lower", "original_upper"))
        assert 0 < actual <= lower <= upper
        if upper <= BUDGET:
            category = "certified"
        elif actual <= BUDGET:
            assert lower > BUDGET
            category = "fits_witness_over_budget"
        else:
            category = "observed_over_budget"
        points[category].append((actual, lower))
assert [len(group) for group in points.values()] == [18, 41, 27]

CATS = [  # drawn back-to-front; legend order = reading order
    ("observed_over_budget",     "Observed over budget",      "s", S.ROLE["neutral"]),
    ("fits_witness_over_budget", "Fits, witness > budget", "^", S.ROLE["witness"]),
    ("certified",                "Certified",                 "o", S.ROLE["certified"]),
]
fig, ax = plt.subplots(figsize=(S.COL_W, 2.2))
S.tight(fig)
XL, YL = (10**2, 10**10.6), (10**4.2, 10**12.8)
assert all(XL[0] < x < XL[1] and YL[0] < y < YL[1] for group in points.values() for x, y in group)
ax.set(xscale="log", yscale="log")

# reference geometry
ax.plot(XL, XL, ls=(0, (1, 1.6)), lw=S.LW_THIN, color=S.REF, zorder=1)
ax.text(10**5.35, 10**4.62, r"$y = x$", fontsize=S.FS_TICK, color=S.INK2, ha="left", va="center")
ax.axvline(BUDGET, ls=(0, (4, 2)), lw=S.LW_THIN + 0.1, color=S.REF, zorder=1)
ax.axhline(BUDGET, ls=(0, (4, 2)), lw=S.LW_THIN + 0.1, color=S.REF, zorder=1)
ax.text(10**2.08, BUDGET * 10**0.2, "Budget", fontsize=S.FS_TICK, color=S.INK2,
        ha="left", va="bottom")

handles = {}
for key, label, mk, col in CATS:
    observed, witness = zip(*points[key])
    n = len(observed)
    if mk == "s":   # open marker: neutral class recedes
        h = ax.scatter(observed, witness, s=13, marker=mk, facecolor="white",
                       edgecolor=col["dark"], linewidth=0.7, zorder=3)
    else:
        h = ax.scatter(observed, witness, s=17 if mk == "^" else 15, marker=mk,
                       facecolor=col["dark"], edgecolor="white", linewidth=0.35, zorder=4)
    handles[key] = (h, f"{label} ({n})")

ax.set_xlim(*XL)
ax.set_ylim(*YL)
ax.tick_params(labelsize=7.4)
for axis, major, minor in (
    (ax.xaxis, (3, 5, 7, 9), range(2, 11)),
    (ax.yaxis, (5, 7, 9, 11), range(5, 13)),
):
    axis.set_major_locator(FixedLocator([10**k for k in major]))
    axis.set_minor_locator(FixedLocator([10**k for k in minor]))
    axis.set_minor_formatter(NullFormatter())
ax.grid(False, axis="x")
ax.grid(True, axis="y", which="major")
ax.set_xlabel("Observed join size (rows)")
ax.set_ylabel("Compatible witness size (rows)")

order = ["certified", "fits_witness_over_budget", "observed_over_budget"]
ax.legend([handles[k][0] for k in order], [handles[k][1] for k in order],
          loc="lower right", bbox_to_anchor=(1.0, 0.095), handletextpad=0.25,
          borderaxespad=0.15, markerscale=1.0)

S.save(fig, "admission-witnesses")
