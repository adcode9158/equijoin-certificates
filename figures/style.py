"""Shared style for all figures: one palette, one type scale, one line-weight scale.

Every figure imports this module so typography, legends and colors stay identical.
Liberation Serif is metric-compatible with Times New Roman (identical advance widths);
PDFs embed it as TrueType (Type 42). If Times New Roman is installed, it is used instead.
"""
from pathlib import Path
import matplotlib as mpl
import matplotlib.font_manager as fm

# ---------------------------------------------------------------- palette
# Light tints = the requested pastel palette (fills, bands).
# Dark tones = the same hues at lower lightness, for strokes, markers and
# text-adjacent marks that must stay readable at column width.
PINK     = dict(light="#FDDED7", dark="#B86A5B")
PEACH    = dict(light="#F5BE8F", dark="#BF6F2E")
TEAL     = dict(light="#C1E0DB", dark="#3F8077")
LIME     = dict(light="#CCD376", dark="#848B2C")
LAVENDER = dict(light="#A28CC2", dark="#6A5799")
SLATE    = dict(light="#8498AB", dark="#5D7085")

# Semantic roles: the same meaning gets the same color in every figure.
ROLE = {
    "certified":  TEAL,      # within budget / integer optimum / lower hull
    "witness":    PEACH,     # attained maximum / compatible witness above budget
    "neutral":    SLATE,     # observed, over budget, non-hull candidates
    "fractional": LAVENDER,  # LP relaxation
    "catalog":    PINK,      # recorded catalog / relation R
    "secondary":  LIME,      # second block / relation S accents
}

INK      = "#222222"   # primary text and axes
INK2     = "#555555"   # secondary text
GRID     = "#E3E3E3"   # subtle gray grid
REF      = "#7A7A7A"   # reference lines (budget, y = x)

# ---------------------------------------------------------------- geometry
COL_W = 241.14 / 72   # acmart sigconf / PVLDB \columnwidth (241.14 pt), inches
TXT_W = 7.0     # full text width, inches

FS      = 8.0   # base font size (axis labels, panel labels)
FS_TICK = 7.0   # tick labels, legend, annotations
LW_AXIS = 0.5
LW_DATA = 0.9
LW_THIN = 0.5


def _font_family():
    names = {f.name for f in fm.fontManager.ttflist}
    for cand in ("Times New Roman", "Liberation Serif", "TeX Gyre Termes"):
        if cand in names:
            return cand
    return "serif"


FONT = _font_family()


def apply():
    mpl.rcParams.update({
        "font.family": FONT,
        "font.size": FS,
        "mathtext.fontset": "custom",
        "mathtext.rm": FONT,
        "mathtext.it": f"{FONT}:italic",
        "mathtext.bf": f"{FONT}:bold",
        "axes.labelsize": FS,
        "axes.titlesize": FS,
        "xtick.labelsize": FS_TICK,
        "ytick.labelsize": FS_TICK,
        "legend.fontsize": FS_TICK,
        "axes.linewidth": LW_AXIS,
        "axes.edgecolor": INK,
        "axes.labelcolor": INK,
        "axes.labelpad": 2.5,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.axisbelow": True,
        "axes.grid": True,
        "grid.color": GRID,
        "grid.linewidth": 0.4,
        "grid.linestyle": "-",
        "xtick.color": INK, "ytick.color": INK,
        "xtick.major.width": LW_AXIS, "ytick.major.width": LW_AXIS,
        "xtick.minor.width": 0.35, "ytick.minor.width": 0.35,
        "xtick.major.size": 2.5, "ytick.major.size": 2.5,
        "xtick.minor.size": 1.5, "ytick.minor.size": 1.5,
        "xtick.major.pad": 2, "ytick.major.pad": 2,
        "xtick.direction": "out", "ytick.direction": "out",
        "lines.linewidth": LW_DATA,
        "patch.linewidth": LW_THIN,
        "legend.frameon": False,
        "legend.handlelength": 1.2,
        "legend.handletextpad": 0.4,
        "legend.borderaxespad": 0.3,
        "legend.labelspacing": 0.3,
        "legend.columnspacing": 1.0,
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "savefig.facecolor": "white",
        "pdf.fonttype": 42,          # embed TrueType, no Type 3 fonts
        "ps.fonttype": 42,
        "svg.fonttype": "none",      # keep text editable in SVG
        "savefig.bbox": None,        # exact figure size: every figure is 241 pt wide
    })


def panel_label(ax, text, y=-0.30, **kw):
    """Sub-figure label centred under a panel, e.g. '(a) Integer packing'."""
    ax.text(0.5, y, text, transform=ax.transAxes, ha="center", va="top",
            fontsize=FS, color=INK, **kw)


def save(fig, name):
    output = Path(__file__).resolve().with_name(f"{name}.pdf")
    fig.savefig(output, metadata={"Title": name, "CreationDate": None})


def tight(fig):
    """Fit labels inside the fixed figure size (no cropping, so width stays 241 pt)."""
    fig.set_layout_engine("constrained")
    fig.get_layout_engine().set(w_pad=0.012, h_pad=0.012, wspace=0.03, hspace=0.0)
