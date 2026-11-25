"""Figure 4: pricing six configurations; the lower hull and the best-profit vertex.

Input 1 offers degrees (1, 2, 4) at prices (0, 1, 9); input 2 offers (1, 3) at (0, 2).
A configuration (v1, v2) sits at (v1*v2, p1(v1)+p2(v2)) and earns v1*v2 - price.
"""
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.ticker import FixedLocator, NullLocator
import style as S

S.apply()
d1 = {1: 0, 2: 1, 4: 9}
d2 = {1: 0, 3: 2}
cfg = [(a, b, a * b, d1[a] + d2[b]) for a in d1 for b in d2]

# lower convex hull in (log product, price)
pts = sorted({(np.log(p), c, a, b) for a, b, p, c in cfg})
hull = []
for P in pts:
    while len(hull) >= 2:
        (x1, y1, *_), (x2, y2, *_) = hull[-2], hull[-1]
        if (x2 - x1) * (P[1] - y1) - (y2 - y1) * (P[0] - x1) <= 0:
            hull.pop()
        else:
            break
    hull.append(P)
hull_set = {(h[2], h[3]) for h in hull}
best = max(cfg, key=lambda t: t[2] - t[3])

fig, ax = plt.subplots(figsize=(S.COL_W, 1.8)); S.tight(fig)
ax.set_xscale("log")

# iso-profit curve through the best vertex: price = product - profit*
xs = np.geomspace(3.6, 14, 100)
prof = best[2] - best[3]
ax.plot(xs, xs - prof, ls=(0, (1, 1.6)), lw=S.LW_THIN + 0.1, color=S.ROLE["witness"]["dark"], zorder=1)
ax.text(14.6, 0.9, f"price = product \u2212 {prof}", fontsize=S.FS_TICK,
        color=S.INK2, ha="right", va="center")

hx = [np.exp(h[0]) for h in hull]; hy = [h[1] for h in hull]
ax.plot(hx, hy, color=S.ROLE["certified"]["dark"], lw=S.LW_DATA, zorder=2)

h_hull = h_oth = None
for a, b, p, c in cfg:
    on = (a, b) in hull_set
    is_best = (a, b) == best[:2]
    if is_best:
        hb = ax.scatter(p, c, s=34, marker="o", facecolor=S.ROLE["witness"]["dark"],
                        edgecolor="white", linewidth=0.5, zorder=5)
    elif on:
        h_hull = ax.scatter(p, c, s=20, marker="o", facecolor=S.ROLE["certified"]["dark"],
                            edgecolor="white", linewidth=0.4, zorder=4)
    else:
        h_oth = ax.scatter(p, c, s=18, marker="o", facecolor="white",
                           edgecolor=S.ROLE["neutral"]["dark"], linewidth=0.7, zorder=4)
    off = {(1, 1): (1, 5, "center", "bottom"), (2, 1): (0, 5, "center", "bottom"),
           (1, 3): (0, 5, "center", "bottom"), (4, 1): (5, 0, "left", "center"),
           (2, 3): (6, -1, "left", "top"), (4, 3): (-5, 0, "right", "center")}[(a, b)]
    ax.annotate(f"({a}, {b})", (p, c), xytext=off[:2], textcoords="offset points",
                ha=off[2], va=off[3], fontsize=S.FS_TICK - 0.5, color=S.INK2)

ax.annotate(f"Best profit {best[2]} \u2212 {best[3]} = {prof}", (best[2], best[3]),
            xytext=(1.9, 6.2), textcoords="data", ha="center", va="center",
            fontsize=S.FS_TICK, color=S.INK,
            arrowprops=dict(arrowstyle="-|>", lw=S.LW_THIN, color=S.INK2,
                            shrinkA=2, shrinkB=4, mutation_scale=6))

ticks = [1, 2, 3, 4, 6, 12]
ax.xaxis.set_major_locator(FixedLocator(ticks))
ax.xaxis.set_minor_locator(NullLocator())
ax.set_xticklabels([str(t) for t in ticks])
ax.set_xlim(0.88, 15)
ax.set_ylim(-0.9, 12.2)
ax.yaxis.set_major_locator(FixedLocator([0, 3, 6, 9, 12]))
ax.set_xlabel("Degree product $v_1 v_2$ (log scale)")
ax.set_ylabel("Sum of prices")

ax.legend([h_hull, hb, h_oth], ["Lower-hull vertex", "Maximum profit", "Off-hull configuration"],
          loc="upper left", handletextpad=0.2, borderaxespad=0.2)

S.save(fig, "fig4_pricing_hull")
