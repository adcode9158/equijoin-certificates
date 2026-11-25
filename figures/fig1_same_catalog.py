"""Figure 1: two databases with the same catalogs.

Catalog: R lists a with count 100, S lists b with count 100; each has one other key
with count 1.  (a) Private residual keys u, v: |R join S| = 0.
(b) Crossed residual keys: R's residual key is b, S's is a: |R join S| = 200.
"""
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle
import style as S

S.apply()
W, H = S.COL_W, 1.50
fig = plt.figure(figsize=(W, H))
ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, W); ax.set_ylim(0, H)
ax.set_aspect("equal"); ax.axis("off")

LIST, RES, LINK = S.ROLE["catalog"], S.ROLE["neutral"], S.ROLE["witness"]
CW, CH, DX, ROWGAP = 0.50, 0.175, 0.36, 0.235

# ---- shared catalog
hb = FancyBboxPatch((0.06, H - 0.40), W - 0.12, 0.34, boxstyle="round,pad=0,rounding_size=0.03",
                    facecolor=LIST["light"], edgecolor=LIST["dark"], lw=S.LW_THIN)
ax.add_patch(hb)
ax.text(W / 2, H - 0.155, r"Same catalog:  $R$ lists $a$ with count 100;  $S$ lists $b$ with count 100.",
        ha="center", va="center", fontsize=S.FS_TICK)
ax.text(W / 2, H - 0.305, "Each relation has one further unlisted key (dashed) with count 1.",
        ha="center", va="center", fontsize=S.FS_TICK)


def cell(x, y, key, cnt, listed):
    if listed:
        ax.add_patch(Rectangle((x - CW / 2, y - CH / 2), CW, CH, facecolor=LIST["light"],
                               edgecolor=LIST["dark"], lw=S.LW_THIN, zorder=2))
    else:
        ax.add_patch(Rectangle((x - CW / 2, y - CH / 2), CW, CH, facecolor="white",
                               edgecolor=RES["dark"], lw=S.LW_THIN + 0.1, ls=(0, (2.2, 1.3)), zorder=2))
    ax.text(x - 0.11, y, f"${key}$", ha="center", va="center", fontsize=S.FS, zorder=3)
    ax.text(x + 0.10, y, cnt, ha="center", va="center", fontsize=S.FS_TICK, zorder=3)


def panel(cx, R, Sx, links, result, title):
    top = H - 0.69
    xr, xs = cx - DX, cx + DX
    ax.text(xr, top + 0.17, "$R$", ha="center", va="center", fontsize=S.FS)
    ax.text(xs, top + 0.17, "$S$", ha="center", va="center", fontsize=S.FS)
    pos = {}
    for i, (k, c, lst) in enumerate(R):
        cell(xr, top - i * ROWGAP, k, c, lst); pos[("R", k)] = (xr + CW / 2, top - i * ROWGAP)
    for i, (k, c, lst) in enumerate(Sx):
        cell(xs, top - i * ROWGAP, k, c, lst); pos[("S", k)] = (xs - CW / 2, top - i * ROWGAP)
    for k in links:
        (x1, y1), (x2, y2) = pos[("R", k)], pos[("S", k)]
        ax.plot([x1 + 0.01, x2 - 0.01], [y1, y2], color=LINK["dark"], lw=S.LW_DATA,
                solid_capstyle="butt", zorder=1)
    ax.text(cx, top - ROWGAP - 0.25, result, ha="center", va="center", fontsize=S.FS_TICK)
    ax.text(cx, top - ROWGAP - 0.45, title, ha="center", va="center", fontsize=S.FS)


panel(0.84,
      [("a", "100", True), ("u", "1", False)],
      [("b", "100", True), ("v", "1", False)],
      [], r"|$R \bowtie S$|  =  0", "(a) Private residual keys")
panel(2.50,
      [("a", "100", True), ("b", "1", False)],
      [("b", "100", True), ("a", "1", False)],
      ["a", "b"], r"|$R \bowtie S$|  =  100 · 1 + 1 · 100  =  200", "(b) Crossed residual keys")

ax.plot([W / 2, W / 2], [H - 1.40, H - 0.47], color=S.GRID, lw=S.LW_THIN)

S.save(fig, "fig1_same_catalog")
