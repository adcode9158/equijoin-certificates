"""Figure 2: unit residual supplies at three inputs.

Edge x joins inputs 1-3, y joins 1-2, z joins 2-3; each key is listed at frequency 2
by the remaining input, so a fully chosen edge earns 2 rows.
(a) Integer packing: edges pairwise share a vertex, so only one fits -> 2 rows.
(b) Linear relaxation: each edge at 1/2 spends exactly one unit per input -> 3 rows.
"""
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.patches import Circle
import style as S

S.apply()
W, H = S.COL_W, 1.27
fig = plt.figure(figsize=(W, H))
ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, W); ax.set_ylim(0, H)
ax.set_aspect("equal"); ax.axis("off")

R = 0.085                       # node radius (inches)
TRI = {1: (0.0, 0.43), 2: (-0.42, -0.13), 3: (0.42, -0.13)}
EDGES = {"x": (1, 3), "y": (1, 2), "z": (2, 3)}
LABEL_OFF = {"x": (0.10, 0.05), "y": (-0.10, 0.05), "z": (0.0, -0.075)}


def seg(p, q, r=R + 0.012):
    p, q = np.array(p), np.array(q)
    u = (q - p) / np.linalg.norm(q - p)
    return p + r * u, q - r * u


def panel(cx, cy, chosen, used, title, result):
    pos = {k: (cx + v[0], cy + v[1]) for k, v in TRI.items()}
    for name, (i, j) in EDGES.items():
        a, b = seg(pos[i], pos[j])
        w = chosen.get(name, 0)
        if w == 1:
            ax.plot(*zip(a, b), color=S.ROLE["certified"]["dark"], lw=2.0, solid_capstyle="butt", zorder=2)
        elif w == 0.5:
            ax.plot(*zip(a, b), color=S.ROLE["fractional"]["dark"], lw=1.2, zorder=2)
        else:
            ax.plot(*zip(a, b), color="#B5B5B5", lw=S.LW_THIN, ls=(0, (3, 2)), zorder=1)
        mx, my = (pos[i][0] + pos[j][0]) / 2, (pos[i][1] + pos[j][1]) / 2
        ox, oy = LABEL_OFF[name]
        txt = f"${name}$" + (" = \u00bd" if w == 0.5 else "")
        ha = {"x": "left", "y": "right", "z": "center"}[name] if w == 0.5 else "center"
        if w == 0.5 and name != "z":
            ox = ox - (0.05 if name == "x" else -0.05)
        ax.text(mx + ox, my + oy, txt, ha=ha, va="center", fontsize=S.FS,
                color=S.INK if w else S.INK2)
    for k, (x, y) in pos.items():
        fc = used.get(k, "white")
        ax.add_patch(Circle((x, y), R, facecolor=fc, edgecolor=S.INK, lw=S.LW_THIN + 0.1, zorder=3))
        ax.text(x, y, str(k), ha="center", va="center", fontsize=S.FS_TICK, zorder=4)
    ax.text(cx, cy - 0.40, result, ha="center", va="center", fontsize=S.FS_TICK, color=S.INK)
    ax.text(cx, cy - 0.60, title, ha="center", va="center", fontsize=S.FS, color=S.INK)


T, L = S.ROLE["certified"]["light"], S.ROLE["fractional"]["light"]
panel(0.84, 0.67, {"x": 1}, {1: T, 3: T},
      "(a) Integer packing", "one edge  ×  2 rows  =  2 rows")
panel(2.50, 0.67, {"x": 0.5, "y": 0.5, "z": 0.5}, {1: L, 2: L, 3: L},
      "(b) Linear relaxation", "3 edges  \u00d7  \u00bd  \u00d7  2 rows  =  3 rows")

# divider between panels
ax.plot([W / 2, W / 2], [0.03, H - 0.05], color=S.GRID, lw=S.LW_THIN)

S.save(fig, "fig2_packing_vs_lp")
