"""Figure 3: block decoding moves one tuple from rank 5 to rank 4.

Observed residual degrees (4, 4, 4, 3, 2); blocks are ranks {1,2} and {3,4,5}.
Recorded (maximum, sum): (4, 8) and (4, 9). Decoding gives (4, 4, 4, 4, 1).
Each column is drawn as stacked unit cells, one per tuple.
"""
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, FancyArrowPatch
from matplotlib.ticker import FixedLocator
import style as S

S.apply()
OBS = [4, 4, 4, 3, 2]
DEC = [4, 4, 4, 4, 1]
BLOCKS = [(1, 2), (3, 5)]
TOP = 5.85
GAP = 0.10                      # white gap between cells (data units)
CELL = S.ROLE["neutral"]["light"]
MOVE = S.ROLE["witness"]
BAND = [S.ROLE["catalog"]["light"], "#F1F3DC"]   # block 1 pink, block 2 pale lime tint


def records(seq):
    return [(max(seq[a - 1:b]), sum(seq[a - 1:b])) for a, b in BLOCKS]


def draw(ax, seq, moved_from=None, moved_to=None, ghost=None):
    for (a, b), fc, (mx, sm) in zip(BLOCKS, BAND, records(seq)):
        ax.add_patch(Rectangle((a - 0.5, 0), b - a + 1, TOP, facecolor=fc, edgecolor="none", zorder=0))
        ax.text((a + b) / 2, 5.45, f"Block {1 if a == 1 else 2}", ha="center", va="center",
                fontsize=S.FS_TICK, color=S.INK2)
        ax.text((a + b) / 2, 4.62, f"({mx}, {sm})", ha="center", va="center",
                fontsize=S.FS_TICK, color=S.INK)
    for r, d in enumerate(seq, start=1):
        for lvl in range(d):
            fc, ec, ls = CELL, S.ROLE["neutral"]["dark"], "-"
            if moved_from == (r, lvl + 1):
                fc, ec = MOVE["light"], MOVE["dark"]
            if moved_to == (r, lvl + 1):
                fc, ec = MOVE["dark"], MOVE["dark"]
            ax.add_patch(Rectangle((r - 0.5 + GAP, lvl + GAP / 2), 1 - 2 * GAP, 1 - GAP,
                                   facecolor=fc, edgecolor=ec, lw=S.LW_THIN, ls=ls, zorder=2))
    if ghost:
        r, lvl = ghost
        ax.add_patch(Rectangle((r - 0.5 + GAP, lvl - 1 + GAP / 2), 1 - 2 * GAP, 1 - GAP,
                               facecolor="none", edgecolor=MOVE["dark"], lw=S.LW_THIN + 0.1,
                               ls=(0, (2, 1.5)), zorder=2))
    ax.set_xlim(0.5, 5.5); ax.set_ylim(0, TOP)
    ax.xaxis.set_major_locator(FixedLocator(range(1, 6)))
    ax.yaxis.set_major_locator(FixedLocator(range(0, 5)))
    ax.grid(False)
    ax.tick_params(axis="x", length=0, pad=2.5)
    for sp in ("left", "bottom"):
        ax.spines[sp].set_linewidth(S.LW_AXIS)
    ax.spines["left"].set_bounds(0, 4)
    ax.set_xlabel("Residual rank")


fig, (a1, a2) = plt.subplots(1, 2, figsize=(S.COL_W, 1.62), sharey=True,
                             gridspec_kw=dict(wspace=0.12))
S.tight(fig)
draw(a1, OBS, moved_from=(5, 2))
draw(a2, DEC, moved_to=(4, 4), ghost=(5, 2))
a1.set_ylabel("Degree")
a2.tick_params(axis="y", labelleft=False)

arrow = FancyArrowPatch((5.0, 1.55), (4.42, 3.45), connectionstyle="arc3,rad=0.35",
                        arrowstyle="-|>", mutation_scale=6, lw=S.LW_THIN + 0.1,
                        color=MOVE["dark"], zorder=4)
a2.add_patch(arrow)

a1.text(0.32, 4.62, "(max, sum)", ha="right", va="center", fontsize=S.FS_TICK, color=S.INK2)
S.panel_label(a1, "(a) Observed: 3 levels", y=-0.30)
S.panel_label(a2, "(b) Decoded: 2 levels", y=-0.30)

S.save(fig, "fig3_block_decoding")
