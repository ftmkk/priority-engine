"""Shared look and helpers for the notebook series.

One import gives every notebook the same palette, the same figure defaults and
the same small set of drawing primitives, so the series reads as one document
rather than six. Nothing here is specific to a single notebook.
"""
import os
import warnings
from pathlib import Path

import matplotlib
import matplotlib.gridspec as gridspec
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

# ---------------------------------------------------------------- paths & data

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CHARTS = ROOT / "charts"
ARTIFACTS = ROOT / "artifacts"
CHARTS.mkdir(exist_ok=True)

TARGET = "Completed Purchase"

# Matches src/priority_engine/ingest.py, so notebook frames can be fed straight
# into features.build() without a second naming convention.
# docker-compose publishes Postgres on 5433 of the host; inside the compose
# network it is postgres:5432. Editors that auto-load .env (VS Code does, for
# every kernel it starts) hand us the compose hostname on the laptop, where it
# does not resolve, so trust the inherited host only if it actually resolves.
# Must run before importing anything that builds the engine.
def _reachable(host):
    import socket
    try:
        socket.getaddrinfo(host, None)
        return True
    except OSError:
        return False


if not _reachable(os.environ.get("POSTGRES_HOST", "localhost")):
    os.environ["POSTGRES_HOST"] = "localhost"
    os.environ["POSTGRES_PORT"] = "5433"
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5433")
os.environ.setdefault("POSTGRES_PASSWORD", "priority_local_pw")

from sys import path as _path
_path.insert(0, str(ROOT / "src"))
from priority_engine.ingest import COLUMNS  # noqa: E402

# ------------------------------------------------------------------- palette

INK = "#1f2430"      # primary text and structural lines
MUTED = "#8a8f98"    # secondary text, neutral events
GRID = "#d8dbe0"
BLUE = "#2f6fb2"     # the path under discussion
TEAL = "#1d9e75"     # positive outcome / converted
CORAL = "#d85a30"    # negative outcome / extrapolated regime
AMBER = "#ba7517"    # warning, censored region
SURFACE = "#f4f5f7"  # shaded bands

plt.rcParams.update({
    "figure.dpi": 120,
    "figure.autolayout": True,
    "savefig.bbox": "tight",
    "font.size": 9.5,
    "axes.titlesize": 10.5,
    "axes.titleweight": "regular",
    "axes.titlelocation": "left",
    "axes.labelsize": 9,
    "axes.labelcolor": INK,
    "axes.edgecolor": GRID,
    "axes.grid": True,
    "axes.axisbelow": True,
    "grid.color": GRID,
    "grid.alpha": 0.7,
    "grid.linewidth": 0.6,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "text.color": INK,
    "xtick.color": MUTED,
    "ytick.color": MUTED,
    "xtick.labelsize": 8.5,
    "ytick.labelsize": 8.5,
    "legend.frameon": False,
    "legend.fontsize": 8.5,
})

# dataset_map() places its panels by hand; the inline backend still tries
# tight_layout on display and warns. The layout is intentional, so drop the warning.
warnings.filterwarnings("ignore", message=".*not compatible with tight_layout.*")

pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 60)


def save(fig, name):
    """Write a figure into ../charts and return it so the cell still displays."""
    fig.savefig(CHARTS / f"{name}.png")
    return fig


# ---------------------------------------------------------------------- data

# (column, family, kind) — mirrors api.PROFILE_COLUMNS, which is what the
# dashboard groups by. Imported as data rather than from api.py so a notebook
# does not need the web stack installed.
PROFILE = [
    ("product_type",              "context",   "categorical"),
    ("channel",                   "context",   "categorical"),
    ("device",                    "context",   "categorical"),
    ("payment_type",              "context",   "categorical"),
    ("insurance_company",         "context",   "categorical"),
    ("partner",                   "context",   "categorical"),
    ("city",                      "context",   "categorical"),
    ("price",                     "offer",     "numeric"),
    ("discount_percent",          "offer",     "numeric"),
    ("expected_margin",           "offer",     "numeric"),
    ("days_to_policy_expiry",     "clock",     "numeric"),
    ("minutes_since_abandonment", "clock",     "numeric"),
    ("days_since_last_visit",     "clock",     "numeric"),
    ("sessions_last_7d",          "behaviour", "discrete"),
    ("offer_views_last_7d",       "behaviour", "discrete"),
    ("price_comparisons_last_7d", "behaviour", "discrete"),
    ("visited_offer_page",        "behaviour", "flag"),
    ("has_previous_purchase",     "behaviour", "flag"),
    ("incoming_call_last_24h",    "behaviour", "flag"),
    ("completed_purchase",        "outcome",   "flag"),
]

FAMILIES = ["context", "offer", "clock", "behaviour", "outcome"]


def cols_of(*, family=None, kind=None, drop_target=True):
    """Column names from PROFILE, filtered by family and/or kind."""
    fam = [family] if isinstance(family, str) else family
    knd = [kind] if isinstance(kind, str) else kind
    return [c for c, f, k in PROFILE
            if (fam is None or f in fam) and (knd is None or k in knd)
            and not (drop_target and c == "completed_purchase")]


def sql(query, **params):
    """Run SQL against the pipeline's Postgres and return a DataFrame."""
    from priority_engine.db import query as _q
    return _q(query, **params)


def leads_db(view="pe.v_leads_curated"):
    """The deduplicated lead table, straight from the database."""
    df = sql(f"SELECT * FROM {view}")
    for c in ("price", "discount_percent", "expected_margin", "days_since_last_visit"):
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def load_leads(snake=False):
    """The raw CSV. `snake=True` renames to the pipeline's column names."""
    df = pd.read_csv(DATA / "leads.csv")
    df["Created At"] = pd.to_datetime(df["Created At"])
    if snake:
        df = df.rename(columns=COLUMNS)
    return df


def curated(df):
    """Same dedup rule as pe.v_leads_curated: one row per lead, the latest.

    Accepts either naming convention, so it works on load_leads(snake=True) too.
    """
    ts, key = ("Created At", "Lead ID") if "Created At" in df else ("created_at", "lead_id")
    return (df.sort_values(ts)
              .drop_duplicates(key, keep="last")
              .reset_index(drop=True))


def target_of(df):
    """The label column under whichever naming convention the frame uses."""
    return TARGET if TARGET in df else "completed_purchase"


def rate_table(df, col, bins=None, min_n=100):
    """Conversion rate by value or by quantile bin, with counts and lift."""
    y = target_of(df)
    key = pd.qcut(df[col], bins, duplicates="drop") if bins else df[col]
    g = df.groupby(key, observed=True)[y].agg(n="count", rate="mean")
    g["lift"] = g["rate"] / df[y].mean()
    return g[g["n"] >= min_n]


# ------------------------------------------------------------- drawing bits

def bars(ax, labels, values, color=BLUE, base=None, fmt="{:.1f}%"):
    """Horizontal-label bar chart with optional base-rate reference line."""
    x = np.arange(len(labels))
    ax.bar(x, values, color=color, width=0.62)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=8)
    if base is not None:
        ax.axhline(base, ls="--", lw=1, color=CORAL)
        ax.text(len(labels) - 0.5, base, " base rate", va="center",
                fontsize=8, color=CORAL)
    for xi, v in zip(x, values):
        ax.text(xi, v, fmt.format(v), ha="center", va="bottom",
                fontsize=8, color=INK)
    ax.margins(y=0.18)
    return ax


def timeline(ax, y, events, spans=(), color=MUTED, label=None, lw=1.2):
    """One event row on a shared time axis.

    events: (x, text) or (x, text, colour) — a dot with the text above it.
    spans:  (x0, x1, text) — a measured interval drawn under the row.
    """
    ax.annotate("", xy=(1.0, y), xytext=(0.0, y),
                arrowprops=dict(arrowstyle="-|>", color=INK, lw=lw,
                                shrinkA=0, shrinkB=0))
    for ev in events:
        x, text = ev[0], ev[1]
        c = ev[2] if len(ev) > 2 else color
        ax.plot([x], [y], "o", ms=6.5, color=c, zorder=3,
                markeredgecolor="white", markeredgewidth=1.1)
        ax.annotate(text, (x, y), xytext=(0, 9), textcoords="offset points",
                    ha="center", va="bottom", fontsize=8.5, color=INK)
    # y grows downward (timeline_canvas inverts the axis), so a span sits at y+.
    for x0, x1, text in spans:
        if x1 > x0:
            ax.annotate("", xy=(x1, y + 0.18), xytext=(x0, y + 0.18),
                        arrowprops=dict(arrowstyle="<|-|>", color=color, lw=1))
        ax.annotate(text, ((x0 + x1) / 2, y + 0.18), xytext=(0, -11),
                    textcoords="offset points", ha="center", va="top",
                    fontsize=8, color=color)
    if label:
        ax.annotate(label, (0.0, y), xytext=(0, 30), textcoords="offset points",
                    ha="left", va="bottom", fontsize=9.5, color=INK, weight="medium")
    return ax


def timeline_canvas(rows, height_per_row=1.15, width=9.2):
    """Blank axes sized for `rows` timeline rows, no ticks, no frame."""
    fig, ax = plt.subplots(figsize=(width, height_per_row * rows))
    ax.set_xlim(-0.03, 1.06)
    ax.set_ylim(rows - 0.45, -0.75)
    ax.axis("off")
    ax.grid(False)
    return fig, ax

# ------------------------------------------------------------------- the map

# Teal is reserved for the target ("bought") everywhere in the series, so the
# behaviour family uses pink instead — otherwise a behaviour row would read as
# an outcome.
FAM_COLOR = {"context": "#7f77dd", "offer": "#ba7517", "clock": "#2f6fb2",
             "behaviour": "#c4487d"}


def _assoc(df, a, b, ordered):
    """Association in [-1, 1] for any pair of columns, plus whether it is signed.

    No single coefficient is honest across both kinds of column, so the measure
    follows the pair: Spearman rho when both sides are ordered (signed),
    Cramer's V when both are nominal, and the correlation ratio eta when the
    pair is mixed. Unsigned measures are returned as magnitudes.
    """
    if a == b:
        return 1.0, True
    if a in ordered and b in ordered:
        x = pd.to_numeric(df[a], errors="coerce")
        y = pd.to_numeric(df[b], errors="coerce")
        ok = x.notna() & y.notna()
        return float(stats.spearmanr(x[ok], y[ok]).statistic), True
    if a not in ordered and b not in ordered:
        t = pd.crosstab(df[a].fillna("?"), df[b].fillna("?"))
        chi2 = stats.chi2_contingency(t.to_numpy())[0]
        d = t.to_numpy().sum() * min(t.shape[0] - 1, t.shape[1] - 1)
        return (float(np.sqrt(chi2 / d)) if d else 0.0), False
    num, cat = (a, b) if a in ordered else (b, a)
    x = pd.to_numeric(df[num], errors="coerce")
    ok = x.notna()
    x, g = x[ok], df[cat].fillna("?")[ok]
    total = ((x - x.mean()) ** 2).sum()
    if total == 0:
        return 0.0, False
    means, sizes = x.groupby(g).mean(), x.groupby(g).size()
    return float(np.sqrt((sizes * (means - x.mean()) ** 2).sum() / total)), False


def _separation(df, col, target, ordered):
    """How far the column separates the two outcome groups.

    KS for an ordered column — the largest gap between the buyer and non-buyer
    CDFs — and Cramer's V for a nominal one. Deliberately not a point-biserial
    r: a column can shift its whole distribution between the groups and still
    score near zero on that.
    """
    if col in ordered:
        v = pd.to_numeric(df[col], errors="coerce")
        a, b = v[df[target] == 1].dropna(), v[df[target] == 0].dropna()
        return float(stats.ks_2samp(a, b).statistic)
    t = pd.crosstab(df[col].fillna("?"), df[target])
    chi2 = stats.chi2_contingency(t.to_numpy())[0]
    return float(np.sqrt(chi2 / t.to_numpy().sum()))


def dataset_map(df, target="completed_purchase", annotate_above=0.25):
    """One figure for the whole dataset, grouped by column family.

    Per column: its distribution split by outcome, and the share of values
    missing. Every pair: association. Every column: separation from the target.

    Returns (fig, info) where info carries the same numbers as DataFrames, so
    findings can be read off the map rather than recomputed differently.
    """
    feats = [(c, f, k) for c, f, k in PROFILE if c != target]
    fam = {c: f for c, f, _ in feats}
    kind = {c: k for c, _, k in feats}
    ordered = {c for c, _, k in feats if k in ("numeric", "discrete", "flag")}

    # Families keep their order; inside a family the strongest separator from
    # the target comes first, so every panel reads top-down by usefulness.
    strength = {c: _separation(df, c, target, ordered) for c, _, _ in feats}
    cols = [c for f in FAMILIES for c in
            sorted([c for c, ff, _ in feats if ff == f],
                   key=lambda c: -strength[c])]
    n = len(cols)

    M = np.zeros((n, n))
    signed = np.zeros((n, n), dtype=bool)
    for i, a in enumerate(cols):
        for j, b in enumerate(cols):
            M[i, j], signed[i, j] = _assoc(df, a, b, ordered)
    sep = np.array([strength[c] for c in cols])
    miss = (df[cols].isna().mean() * 100).to_dict()

    prev = plt.rcParams["figure.autolayout"]
    plt.rcParams["figure.autolayout"] = False
    fig = plt.figure(figsize=(9.8, 8.4))
    fig.set_layout_engine("none")   # the panel positions below are deliberate
    gs = gridspec.GridSpec(1, 2, figure=fig, width_ratios=[1, 0.028], wspace=0.04,
                           left=0.265, right=0.93, top=0.875, bottom=0.215)

    # Both axes read in the same order, so the diagonal runs from the top-left
    # corner; only the lower triangle is drawn, since the upper one repeats it.
    keep = np.tril(np.ones((n, n), dtype=bool))

    axm = fig.add_subplot(gs[0, 0])
    cmap = plt.get_cmap("Purples").copy()
    cmap.set_bad("white")
    im = axm.imshow(np.ma.masked_where(~keep, np.abs(M)), cmap=cmap,
                    vmin=0, vmax=1)
    axm.set_xticks(range(n)); axm.set_yticks(range(n))
    axm.set_xticklabels(cols, rotation=55, ha="right", fontsize=7.5)
    axm.set_yticklabels(cols, fontsize=7.5)
    for t, c in zip(axm.get_xticklabels(), cols):
        t.set_color(FAM_COLOR[fam[c]])
    for t, c in zip(axm.get_yticklabels(), cols):
        t.set_color(FAM_COLOR[fam[c]])
    axm.grid(False)
    for i in range(n):
        for j in range(n):
            if not keep[i, j] or i == j or abs(M[i, j]) < annotate_above:
                continue
            sign = "\u2212" if signed[i, j] and M[i, j] < 0 else ""
            axm.annotate(f"{sign}{abs(M[i, j]):.2f}".replace("0.", "."), (j, i),
                         ha="center", va="center", fontsize=6.4,
                         color="white" if abs(M[i, j]) > 0.55 else INK)

    starts, seen = [], None
    for idx, c in enumerate(cols):
        if fam[c] != seen:
            starts.append(idx); seen = fam[c]
    for b in starts[1:]:
        axm.axhline(b - 0.5, color=INK, lw=1.1)
        axm.axvline(b - 0.5, color=INK, lw=1.1)
    for lo, hi in zip(starts, starts[1:] + [n]):
        f = fam[cols[lo]]
        axm.annotate(f, xy=(0, 0), xycoords="axes fraction",
                     xytext=(-0.305, 1 - (lo + hi) / 2 / n),
                     textcoords="axes fraction", rotation=90, ha="center",
                     va="center", fontsize=9, color=FAM_COLOR[f])

    cax = fig.add_subplot(gs[0, 1])
    fig.colorbar(im, cax=cax)
    cax.tick_params(labelsize=7)
    cax.set_ylabel("association strength", fontsize=7.5)

    fig.text(0.02, 0.955, "How the columns relate to each other",
             fontsize=13, color=INK)
    fig.text(0.02, 0.925,
             "every pair, lower triangle only   ·   inside each family the "
             "strongest separator from the target comes first",
             fontsize=8.5, color=MUTED)
    x = 0.02
    for f, colour in FAM_COLOR.items():
        fig.text(x, 0.898, f, fontsize=8.5, color=colour)
        x += 0.009 * len(f) + 0.024
    fig.text(0.02, 0.045,
             "|Spearman rho| within ordered columns (a minus sign is shown where "
             "negative), Cramer's V within categorical,", fontsize=7.5, color=MUTED)
    fig.text(0.02, 0.022, "correlation ratio eta across a mixed pair",
             fontsize=7.5, color=MUTED)
    plt.rcParams["figure.autolayout"] = prev

    info = {
        "assoc": pd.DataFrame(M, index=cols, columns=cols),
        "signed": pd.DataFrame(signed, index=cols, columns=cols),
        "separation": pd.Series(sep, index=cols).sort_values(ascending=False),
        "missing": pd.Series(miss).loc[lambda s: s > 0].sort_values(ascending=False),
        "family": pd.Series(fam),
    }
    return fig, info


def _bare(ax):
    ax.set_xticks([]); ax.set_yticks([]); ax.grid(False)
    for sp in ax.spines.values():
        sp.set_visible(False)
    return ax


def pairs_above(info, threshold=0.25):
    """Every off-diagonal pair in the map above `threshold`, strongest first."""
    A = info["assoc"].abs()
    keep = np.triu(np.ones(A.shape, dtype=bool), k=1)
    out = A.where(keep).stack().sort_values(ascending=False)
    return out[out >= threshold]

def _family_order(df, target="completed_purchase"):
    """Columns grouped by family, strongest separator from the target first."""
    feats = [(c, f, k) for c, f, k in PROFILE if c != target]
    ordered = {c for c, _, k in feats if k in ("numeric", "discrete", "flag")}
    strength = {c: _separation(df, c, target, ordered) for c, _, _ in feats}
    fam = {c: f for c, f, _ in feats}
    kind = {c: k for c, _, k in feats}
    cols = [c for f in FAMILIES for c in
            sorted([c for c, ff, _ in feats if ff == f], key=lambda c: -strength[c])]
    return cols, fam, kind, ordered, strength


def distribution_grid(df, target="completed_purchase", ncols=4):
    """One readable panel per column: its distribution split by the outcome.

    Grouped by family, strongest separator first, same order as the matrix.
    Densities rather than counts, so a 9% class is still visible next to a 91%
    one — the two curves are shape comparisons, not volume comparisons.
    """
    cols, fam, kind, ordered, strength = _family_order(df, target)
    miss = df[cols].isna().mean() * 100
    nrows = int(np.ceil(len(cols) / ncols))

    # The header is its own gridspec row rather than a reserved margin, so no
    # layout engine can reclaim it and park the title on top of a panel.
    fig = plt.figure(figsize=(12.4, 0.95 + 2.15 * nrows), layout="constrained")
    gs = gridspec.GridSpec(nrows + 1, ncols, figure=fig,
                           height_ratios=[0.40] + [1] * nrows)

    axh = fig.add_subplot(gs[0, :])
    axh.axis("off"); axh.grid(False)
    axh.text(0, 0.72, "Every column, split by outcome", fontsize=13, color=INK,
             va="center")
    axh.text(0, 0.18,
             "grouped by family, strongest separator first; the number after each "
             "name is its separation from the target; where a column has holes, the "
             "missing rows sit at the left of its panel", fontsize=8.5, color=MUTED,
             va="center")

    buyer, other = df[target] == 1, df[target] == 0

    def missing_bars(ax, c, top, at, width, to_scale=False):
        """The missing rows as two bars inside the panel, left of the data.

        Split by outcome like the rest of the panel, labelled with the overall
        share, and fenced off with a dotted rule so they are never read as part
        of the distribution. On a categorical panel the y axis already is "% of
        group", so the bars are drawn to scale; on a density panel there is no
        shared scale, so they are sized to fit and the label carries the number.
        """
        gone = [df.loc[other, c].isna().mean() * 100,
                df.loc[buyer, c].isna().mean() * 100]
        scale = 1.0 if to_scale else top / (max(gone) * 1.7)
        ax.bar([at - width * 0.55], [gone[0] * scale], width=width, color=GRID,
               zorder=2)
        ax.bar([at + width * 0.55], [gone[1] * scale], width=width, color=TEAL,
               zorder=2)
        ax.annotate(f"{df[c].isna().mean() * 100:.1f}%",
                    (at, max(gone) * scale), xytext=(0, 2),
                    textcoords="offset points", ha="center", va="bottom",
                    fontsize=6.2, color=AMBER)
        ax.annotate("missing", (at, 0), xytext=(0, -9), textcoords="offset points",
                    ha="center", va="top", fontsize=6.8, color=AMBER)
        ax.axvline(at + width * 1.35, ls=":", lw=0.8, color=AMBER, zorder=1)

    axes = []
    for i, c in enumerate(cols):
        ax = fig.add_subplot(gs[1 + i // ncols, i % ncols])
        if c in ordered and kind[c] != "flag":
            v = pd.to_numeric(df[c], errors="coerce")
            bins = np.histogram_bin_edges(v.dropna(), bins=26)
            h_other, _, _ = ax.hist(v[other].dropna(), bins=bins, density=True,
                                    color=GRID, label="did not buy")
            h_buyer, _, _ = ax.hist(v[buyer].dropna(), bins=bins, density=True,
                                    histtype="step", lw=1.6, color=TEAL,
                                    label="bought")
            ax.set_yticks([])
            if miss[c] > 0:
                span = bins[-1] - bins[0]
                bw = span * 0.055
                missing_bars(ax, c, max(h_other.max(), h_buyer.max()),
                             bins[0] - span * 0.135, bw)
                ax.set_xlim(bins[0] - span * 0.21, bins[-1] + span * 0.02)
        else:
            levels = list(df[c].value_counts().head(6).index)

            def share(mask, levels=levels):
                return (df.loc[mask, c].value_counts(normalize=True)
                          .reindex(levels).fillna(0).to_numpy() * 100)

            x = np.arange(len(levels))
            vals_other, vals_buyer = share(other), share(buyer)
            ax.bar(x - 0.2, vals_other, width=0.4, color=GRID, label="did not buy")
            ax.bar(x + 0.2, vals_buyer, width=0.4, color=TEAL, label="bought")
            ax.set_xticks(x)
            ax.set_xticklabels([str(l)[:9] for l in levels], fontsize=6.8,
                               rotation=24, ha="right")
            ax.set_ylabel("% of group", fontsize=7)
            if miss[c] > 0:
                missing_bars(ax, c, max(vals_other.max(), vals_buyer.max()),
                             -1.3, 0.4, to_scale=True)
                ax.set_xlim(-1.95, len(levels) - 0.45)
        ax.tick_params(labelsize=7.5)
        ax.set_title(f"{c}   {strength[c]:.3f}", fontsize=8.5,
                     color=FAM_COLOR[fam[c]], loc="left")
        axes.append(ax)

    handles, labels = axes[0].get_legend_handles_labels()
    axh.legend(handles, labels, loc="upper right", ncol=2,
               bbox_to_anchor=(1.0, 1.35), fontsize=8.5)
    return fig


def target_correlation(df, target="completed_purchase"):
    """Association with the outcome for every column, strongest first.

    Ordered columns get a KS statistic and a direction from the sign of their
    Spearman rho against the outcome; categorical ones get Cramer's V, which has
    no direction. Both live in [0, 1] and neither is fooled by the 9% base rate.
    """
    cols, fam, kind, ordered, strength = _family_order(df, target)
    rank = sorted(cols, key=lambda c: strength[c])

    rows = []
    for c in rank:
        if c in ordered:
            v = pd.to_numeric(df[c], errors="coerce")
            ok = v.notna()
            rho = stats.spearmanr(v[ok], df[target][ok]).statistic
            lo, hi = v.quantile(0.2), v.quantile(0.8)
            rate_lo = df.loc[ok & (v <= lo), target].mean()
            rate_hi = df.loc[ok & (v >= hi), target].mean()
            rows.append((c, strength[c], "KS", rho, rate_lo, rate_hi))
        else:
            g = df.groupby(df[c].fillna("?"))[target].agg(["size", "mean"])
            g = g[g["size"] >= 200]
            rows.append((c, strength[c], "V", np.nan,
                         g["mean"].min(), g["mean"].max()))

    base = df[target].mean()
    fig = plt.figure(figsize=(12.4, 6.4), layout="constrained")
    gs = gridspec.GridSpec(2, 2, figure=fig, height_ratios=[0.15, 1],
                           width_ratios=[1.35, 1])
    axh = fig.add_subplot(gs[0, :])
    axh.axis("off"); axh.grid(False)
    axh.text(0, 0.75, "How each column relates to the outcome", fontsize=13,
             color=INK, va="center")
    axh.text(0, 0.05,
             "left: strength, sorted   ·   right: the same column as a conversion "
             "spread, so the strength has a unit", fontsize=8.5, color=MUTED,
             va="center")
    ax = fig.add_subplot(gs[1, 0])
    ax2 = fig.add_subplot(gs[1, 1])

    y = np.arange(len(rows))
    ax.barh(y, [r[1] for r in rows],
            color=[FAM_COLOR[fam[r[0]]] for r in rows], height=0.66)
    ax.set_yticks(y); ax.set_yticklabels([r[0] for r in rows], fontsize=8)
    for t, r in zip(ax.get_yticklabels(), rows):
        t.set_color(FAM_COLOR[fam[r[0]]])
    for i, r in enumerate(rows):
        mark = "" if np.isnan(r[3]) else ("  up" if r[3] > 0 else "  down")
        ax.annotate(f"{r[1]:.3f}{mark}", (r[1], i), xytext=(4, 0),
                    textcoords="offset points", va="center", fontsize=7.5)
    ax.set_xlim(0, max(r[1] for r in rows) * 1.42)
    ax.set_xlabel("KS for ordered columns, Cramer's V for categorical", fontsize=8)
    ax.grid(axis="y", visible=False)

    # the same columns as conversion rates, so the strength has a business unit
    ax2.axvline(base * 100, ls="--", lw=1, color=CORAL)
    ax2.annotate(f"base rate {base:.1%}", (base * 100, len(rows) - 0.2),
                 xytext=(4, 0), textcoords="offset points", fontsize=7.5, color=CORAL)
    for i, r in enumerate(rows):
        lo, hi = sorted([r[4] * 100, r[5] * 100])
        ax2.plot([lo, hi], [i, i], color=FAM_COLOR[fam[r[0]]], lw=1.4, zorder=2)
        ax2.plot([lo], [i], "o", ms=4.5, color=GRID, zorder=3,
                 markeredgecolor=FAM_COLOR[fam[r[0]]], markeredgewidth=1.1)
        ax2.plot([hi], [i], "o", ms=4.5, color=FAM_COLOR[fam[r[0]]], zorder=3)
        ax2.annotate(f"{hi:.1f}%", (hi, i), xytext=(5, 0), textcoords="offset points",
                     va="center", fontsize=7.5)
    ax2.set_yticks(y); ax2.set_yticklabels([])
    ax2.set_xlim(0, max(max(r[4], r[5]) for r in rows) * 100 * 1.22)
    ax2.set_xlabel("conversion % across the column's own range\n"
                   "(ordered: bottom vs top quintile; categorical: worst vs best level)",
                   fontsize=8)
    ax2.grid(axis="y", visible=False)

    return fig, pd.DataFrame(rows, columns=["column", "strength", "measure",
                                            "rho_with_target", "rate_low", "rate_high"])

def column_sheet(df, target="completed_purchase"):
    """Every column as one row: shape, holes, signal, and what it is worth.

    Five slim panels per row instead of five separate figures — the sparkline
    keeps its own x scale (shapes are not comparable across columns anyway),
    while missing share, separation and conversion spread share one scale each,
    so those three columns can be compared straight down the page.
    """
    cols, fam, kind, ordered, strength = _family_order(df, target)
    n = len(cols)
    buyer, other = df[target] == 1, df[target] == 0
    base = df[target].mean() * 100
    miss = (df[cols].isna().mean() * 100)

    spread, direction = {}, {}
    for c in cols:
        if c in ordered:
            v = pd.to_numeric(df[c], errors="coerce")
            ok = v.notna()
            rho = stats.spearmanr(v[ok], df[target][ok]).statistic
            lo, hi = v.quantile(0.2), v.quantile(0.8)
            spread[c] = (df.loc[ok & (v <= lo), target].mean() * 100,
                         df.loc[ok & (v >= hi), target].mean() * 100)
            direction[c] = "up" if rho > 0 else "down"
        else:
            g = df.groupby(df[c])[target].agg(["size", "mean"])
            g = g[g["size"] >= 200]
            spread[c] = (g["mean"].min() * 100, g["mean"].max() * 100)
            direction[c] = ""

    fig = plt.figure(figsize=(11.6, 0.80 + 0.46 * n), layout="constrained")
    gs = gridspec.GridSpec(2, 4, figure=fig, height_ratios=[0.46 * 1.7, 0.46 * n],
                           width_ratios=[0.92, 0.30, 0.90, 1.00], wspace=0.04)

    axh = fig.add_subplot(gs[0, :]); axh.axis("off"); axh.grid(False)
    axh.text(0, 0.74, "Every column at a glance", fontsize=13, color=INK, va="center")
    axh.text(0, 0.24, "grouped by family, strongest separator from the target first",
             fontsize=8.5, color=MUTED, va="center")
    x = 0.60
    for f, colour in FAM_COLOR.items():
        axh.text(x, 0.74, f, fontsize=8.5, color=colour, va="center",
                 transform=axh.transAxes)
        x += 0.013 * len(f) + 0.035
    axh.add_patch(plt.Rectangle((0.60, 0.12), 0.022, 0.20, color=GRID,
                                transform=axh.transAxes, clip_on=False))
    axh.text(0.628, 0.22, "lead volume", fontsize=8, color=MUTED, va="center")
    # a patch, not a plotted line: a Line2D here would feed the header axes'
    # data limits and blow up the figure's tight bounding box
    axh.add_patch(plt.Rectangle((0.715, 0.205), 0.022, 0.03, color=TEAL,
                                transform=axh.transAxes, clip_on=False))
    axh.text(0.743, 0.22, "conversion", fontsize=8, color=MUTED, va="center")

    def tall(cell, xlim, xlabel):
        ax = fig.add_subplot(cell)
        ax.set_ylim(n - 0.5, -0.5)
        ax.set_yticks([]); ax.set_xlim(*xlim)
        ax.set_xlabel(xlabel, fontsize=7.5)
        ax.grid(axis="y", visible=False)
        ax.tick_params(labelsize=7)
        # a hairline under every row and a firmer one between families, drawn in
        # all four lanes so one row can be followed across the whole sheet
        for i in range(n):
            ax.axhline(i + 0.5, color=GRID, lw=0.4, alpha=0.55, zorder=0)
        for b in starts[1:]:
            ax.axhline(b - 0.5, color=MUTED, lw=0.9, alpha=0.7, zorder=1)
        return ax

    starts, seen = [], None
    for idx, c in enumerate(cols):
        if fam[c] != seen:
            starts.append(idx); seen = fam[c]

    # --- column 1: the distributions, drawn as bands inside ONE axes.
    # Each row gets its own x normalisation (shapes are not comparable across
    # columns anyway) but shares the y grid with the three columns to its right,
    # so a row lines up across the whole sheet.
    axd = tall(gs[1, 0], (0, 1),
               "grey: where the leads are   ·   teal: conversion, dotted = base rate")
    axd.set_yticks(range(n))
    axd.set_yticklabels(cols, fontsize=8)
    for t, c in zip(axd.get_yticklabels(), cols):
        t.set_color(FAM_COLOR[fam[c]])
    axd.set_xticks([])
    BAND, FOOT = 0.66, 0.30

    # Two overlapping densities cannot show a three-point difference in a lane
    # this thin, so each row carries the shape AND the outcome instead: a grey
    # backdrop for where the leads are, and a teal line for how well each slice
    # of the column converts, against a dotted base rate. A row where the teal
    # line climbs is a column that separates buyers; a flat line is one that
    # does not.
    name_rows = []
    for i, c in enumerate(cols):
        floor = i + FOOT
        if c in ordered and kind[c] != "flag":
            v = pd.to_numeric(df[c], errors="coerce")
            vd = v.dropna()
            # an integer count over a short range has fewer distinct values than
            # bins: 18 bins over 0..12 leaves some holding no integer at all, and
            # those empty bins later become NaN and break the line into pieces.
            # One bin per value instead, so every bin can be occupied.
            whole = (vd % 1 == 0).all() and vd.nunique() <= 18
            edges = (np.arange(vd.min() - 0.5, vd.max() + 1.5)
                     if whole else np.histogram_bin_edges(vd, bins=18))
            counts, _ = np.histogram(vd, bins=edges)
            idx = np.clip(np.searchsorted(edges, v, side="right") - 1, 0, len(edges) - 2)
            rate = (df.assign(_b=idx).groupby("_b")[target].mean()
                      .reindex(range(len(edges) - 1)))
            rate[counts < 50] = np.nan
            xs = np.linspace(0.015, 0.985, len(counts))
            lo, hi = np.nanmin(v), np.nanmax(v)
            fmt = (lambda x: f"{x:,.0f}") if abs(hi) >= 1000 else (lambda x: f"{x:g}")
            left, right = fmt(lo), fmt(hi)
            names = None
        else:
            levels = list(df[c].value_counts().head(6).index)
            # a flag has no "most common first" reading worth keeping: read it
            # left to right as 0 then 1, the same way every other flag row reads
            if set(levels) <= {0, 1, True, False}:
                levels = sorted(levels)
            counts = df[c].value_counts().reindex(levels).to_numpy()
            rate = (df[df[c].isin(levels)].groupby(c)[target].mean()
                      .reindex(levels))
            rate[counts < 50] = np.nan
            xs = np.linspace(0.015, 0.985, len(levels))
            left, right = "", ""
            # an ordered column labels its two ends; a categorical one has no
            # ends, so the strip under the band names the levels instead, in the
            # same order the bands are drawn — most common first
            names = [str(l) for l in levels]
            rest = df[c].nunique() - len(levels)

        # grey backdrop: where the leads are
        share = counts / counts.max() if counts.max() else counts
        axd.fill_between(xs, floor, floor - share * BAND * 0.92, step="mid",
                         color=GRID, zorder=2)

        # teal line: how that slice converts, scaled to the row's own top rate
        top = np.nanmax(rate.to_numpy()) if np.isfinite(rate.to_numpy()).any() else 0
        if top > 0:
            ys = floor - rate.to_numpy() / top * BAND * 0.92
            axd.plot(xs, ys, color=TEAL, lw=1.2, zorder=4)
            y_base = floor - base / 100 / top * BAND * 0.92
            axd.plot([0.015, 0.985], [y_base, y_base], ls=":", lw=0.7,
                     color=CORAL, zorder=3)
            axd.annotate(f"{top * 100:.0f}%", (0.985, floor - BAND * 0.92),
                         xytext=(-1, 0), textcoords="offset points", fontsize=5.2,
                         color=TEAL, ha="right", va="center")
        if names:
            # the lane is narrow, so each name gets an equal share of it and is
            # cut to fit; the outer two align inward so nothing spills off-axes
            width = int(np.clip(70 / len(names) - 1.5, 6, 18))
            cut = lambda t, w: t if len(t) <= w else t[:w - 1] + "\u2026"
            row_texts = []
            for j, (xv, nm) in enumerate(zip(xs, names)):
                last = j == len(names) - 1
                ha = "left" if j == 0 else "right" if last else "center"
                if last and rest:
                    # levels past the sixth are not drawn; say how many, in the
                    # space the last name would otherwise have used
                    tail = f" +{rest} more"
                    if len(nm) + len(tail) > width + 2:
                        tail = f" +{rest}"
                    nm = cut(nm, width + 2 - len(tail)) + tail
                row_texts.append(
                    axd.annotate(nm if last and rest else cut(nm, width),
                                 (xv, floor), xytext=(0, 1),
                                 textcoords="offset points", fontsize=5.4,
                                 color=MUTED, ha=ha, va="top"))
            name_rows.append(row_texts)
        if left:
            axd.annotate(left, (0.015, floor), xytext=(0, 1),
                         textcoords="offset points", fontsize=5.4, color=MUTED,
                         ha="left", va="top")
        if right:
            axd.annotate(right, (0.985, floor), xytext=(0, 1),
                         textcoords="offset points", fontsize=5.4, color=MUTED,
                         ha="right", va="top")

    # --- column 2: share missing, split by outcome like everything else
    miss_o = {c: df.loc[other, c].isna().mean() * 100 for c in cols}
    miss_b = {c: df.loc[buyer, c].isna().mean() * 100 for c in cols}
    axm = tall(gs[1, 1], (0, max(max(miss_o.values()), max(miss_b.values())) * 2.3),
               "%\nmissing")
    axm.barh([i - 0.17 for i in range(n)], [miss_o[c] for c in cols],
             color=GRID, height=0.30)
    axm.barh([i + 0.17 for i in range(n)], [miss_b[c] for c in cols],
             color=TEAL, height=0.30)
    for i, c in enumerate(cols):
        if miss[c] > 0:
            axm.annotate(f"{miss_o[c]:.1f} / {miss_b[c]:.1f}",
                         (max(miss_o[c], miss_b[c]), i), xytext=(3, 0),
                         textcoords="offset points", va="center", fontsize=6,
                         color=AMBER)
    axm.set_xticks([])

    # --- column 3: separation from the target
    axs = tall(gs[1, 2], (0, max(strength.values()) * 1.5),
               "separation from the target\nKS, or Cramer's V")
    axs.barh(range(n), [strength[c] for c in cols],
             color=[FAM_COLOR[fam[c]] for c in cols], height=0.55)
    for i, c in enumerate(cols):
        d = f"  {direction[c]}" if direction[c] else ""
        axs.annotate(f"{strength[c]:.3f}{d}", (strength[c], i), xytext=(3, 0),
                     textcoords="offset points", va="center", fontsize=6.2)

    # --- column 4: the same column as a conversion spread
    hi_max = max(max(v) for v in spread.values())
    axc = tall(gs[1, 3], (0, hi_max * 1.28),
               "conversion % over the column's range\nquintiles, or worst vs best level")
    axc.axvline(base, ls="--", lw=1, color=CORAL)
    axc.annotate(f"base {base:.1f}%", (base, -0.45), xytext=(3, 0),
                 textcoords="offset points", fontsize=6.2, color=CORAL, va="center")
    for i, c in enumerate(cols):
        lo, hi = sorted(spread[c])
        col = FAM_COLOR[fam[c]]
        axc.plot([lo, hi], [i, i], color=col, lw=1.3, zorder=2)
        axc.plot([lo], [i], "o", ms=3.6, color="white", markeredgecolor=col,
                 markeredgewidth=1.1, zorder=3)
        axc.plot([hi], [i], "o", ms=3.6, color=col, zorder=3)
        axc.annotate(f"{hi:.1f}", (hi, i), xytext=(4, 0), textcoords="offset points",
                     va="center", fontsize=6.2)

    # A character budget cannot know the real width of a name, so let the figure
    # settle once and then shrink any row whose level names still touch.
    if name_rows:
        fig.canvas.draw()
        rend = fig.canvas.get_renderer()
        for row_texts in name_rows:
            size = 5.4
            while size > 4.2:
                box = [t.get_window_extent(rend) for t in row_texts]
                if all(a.x1 + 2 <= b.x0 for a, b in zip(box, box[1:])):
                    break
                size -= 0.3
                for t in row_texts:
                    t.set_fontsize(size)
    return fig


# ----------------------------------------------------------- distribution shift

# The conventional PSI reading, kept here so every chart and every sentence in
# the notebooks uses the same words for the same numbers.
PSI_BANDS = [(0.10, "stable"), (0.25, "moderate"), (np.inf, "significant")]


def psi_band(value):
    """The conventional name for a PSI value: stable / moderate / significant."""
    return next(name for edge, name in PSI_BANDS if value < edge)


def shift_split(df, holdout_days=None, time_col="created_at"):
    """Split the frame the way training does: everything old, then the newest days.

    Defaults to `train.holdout_days` from the project config, so a shift measured
    here is a shift across exactly the boundary the model is validated on.
    """
    if holdout_days is None:
        from priority_engine.config import CFG
        holdout_days = CFG["train"]["holdout_days"]
    cutoff = df[time_col].max() - pd.Timedelta(days=holdout_days)
    return df[df[time_col] < cutoff], df[df[time_col] >= cutoff], cutoff


def _shift_keys(ref_s, cur_s, ordered, q=10):
    """Put both periods into one shared set of bins, defined by the reference.

    Quantile edges for an ordered column (equal-mass bins in the reference, so
    a moved distribution shows up as unequal mass in the current one), levels
    for a categorical. Missing is a bin of its own rather than a dropped row —
    a column that starts arriving empty has shifted, and dropping the NaNs
    would hide exactly that.
    """
    if ordered:
        v = pd.to_numeric(ref_s, errors="coerce")
        edges = np.unique(np.nanquantile(v.dropna(), np.linspace(0, 1, q + 1)))
        if len(edges) >= 3:            # enough distinct values to cut
            edges[0], edges[-1] = -np.inf, np.inf
            cut = lambda s: pd.cut(pd.to_numeric(s, errors="coerce"), edges)
            ka, kb = cut(ref_s).astype(object), cut(cur_s).astype(object)
        else:                          # a flag or a near-constant: use the values
            ka, kb = ref_s.astype(object), cur_s.astype(object)
    else:
        ka, kb = ref_s.astype(object), cur_s.astype(object)
    ka = pd.Series(np.where(pd.isna(ka), "(missing)", ka), index=ref_s.index)
    kb = pd.Series(np.where(pd.isna(kb), "(missing)", kb), index=cur_s.index)
    keys = sorted(set(ka) | set(kb), key=str)
    return keys, ka, kb


def _psi(p, q, eps=1e-6):
    """Population Stability Index between two binned distributions."""
    a, b = np.clip(p, eps, None), np.clip(q, eps, None)
    return float(((b - a) * np.log(b / a)).sum())


def _shift_null(p_pooled, n_ref, n_cur, draws=400, seed=0, raw=False):
    """How large a shift two samples of these sizes show with no shift at all.

    PSI has no fixed scale: it grows with the number of bins and shrinks with
    sample size, so 0.002 means nothing until you know what zero looks like
    here. Both periods are re-drawn from the pooled distribution, which is the
    null hypothesis "same population, different sample", and the spread of the
    result is the floor an observed value has to clear before it is a shift.
    """
    rng = np.random.default_rng(seed)
    a = rng.multinomial(n_ref, p_pooled, size=draws) / n_ref
    b = rng.multinomial(n_cur, p_pooled, size=draws) / n_cur
    eps = 1e-6
    ac, bc = np.clip(a, eps, None), np.clip(b, eps, None)
    psi = ((bc - ac) * np.log(bc / ac)).sum(axis=1)
    if raw:
        return psi
    tvd = 0.5 * np.abs(a - b).sum(axis=1) * 100
    return (float(np.percentile(psi, 50)), float(np.percentile(psi, 95)),
            float(np.percentile(tvd, 95)))


def shift_table(df, target="completed_purchase", holdout_days=None, q=10,
                draws=400, seed=0, min_n=200):
    """How far every column moved between the training period and the holdout.

    Four numbers per column, each answering a different question:

    - `psi` / `null_p95` — did the distribution move more than sampling noise?
    - `moved_pct` — the same shift in plain terms: the share of holdout leads
      that would have to change bin for the two periods to match.
    - `mix_pp` / `rate_pp` — of the change in conversion between the periods,
      how much comes from the column's mix moving, and how much from the
      conversion rate inside its bins moving. They sum to the same total for
      every column; only the split differs.
    - `lift_corr` / `lift_gap` — whether the column's bins keep their order,
      and how far the worst of them moves, once the level change is divided
      out. Stable lift means the ranking survives even if the probabilities do
      not.
    """
    ref, cur, cutoff = shift_split(df, holdout_days)
    feats = [(c, f, k) for c, f, k in PROFILE if c != target]
    ordered = {c for c, _, k in feats if k in ("numeric", "discrete", "flag")}
    base_r, base_c = ref[target].mean(), cur[target].mean()

    rows, detail = [], {}
    for i, (c, fam, kind) in enumerate(feats):
        keys, ka, kb = _shift_keys(ref[c], cur[c], c in ordered, q)
        n_a = ka.value_counts().reindex(keys).fillna(0)
        n_b = kb.value_counts().reindex(keys).fillna(0)
        p_a, p_b = n_a / n_a.sum(), n_b / n_b.sum()
        r_a = ref.groupby(ka, observed=True)[target].mean().reindex(keys)
        r_b = cur.groupby(kb, observed=True)[target].mean().reindex(keys)

        pooled = ((n_a + n_b) / (n_a.sum() + n_b.sum())).to_numpy()
        null50, null95, null_moved = _shift_null(pooled, len(ref), len(cur),
                                                 draws, seed + i)

        # Mix vs rate: the change in the overall conversion rate splits exactly
        # into "different leads arrived" and "the same leads converted worse".
        mix = float(((p_b - p_a) * r_a.fillna(base_r)).sum())
        rate = float((p_b * (r_b.fillna(base_r) - r_a.fillna(base_r))).sum())

        solid = (n_a >= min_n) & (n_b >= min_n)
        lift_a, lift_b = (r_a / base_r)[solid], (r_b / base_c)[solid]
        corr = (float(np.corrcoef(lift_a, lift_b)[0, 1]) if solid.sum() >= 3
                else np.nan)
        gap = float((lift_b - lift_a).abs().max()) if solid.any() else np.nan

        rows.append((c, fam, kind, _psi(p_a, p_b), null50, null95,
                     float(0.5 * np.abs(p_a - p_b).sum() * 100), null_moved,
                     mix * 100, rate * 100, corr, gap, len(keys)))
        detail[c] = pd.DataFrame({"n_ref": n_a, "n_cur": n_b, "p_ref": p_a,
                                  "p_cur": p_b, "rate_ref": r_a, "rate_cur": r_b,
                                  "lift_ref": r_a / base_r, "lift_cur": r_b / base_c})

    out = pd.DataFrame(rows, columns=["column", "family", "kind", "psi", "null_p50",
                                      "null_p95", "moved_pct",
                                      "null_moved_pct", "mix_pp", "rate_pp",
                                      "lift_corr", "lift_gap",
                                      "bins"]).set_index("column")
    out["vs_noise"] = out["psi"] / out["null_p95"]
    out["band"] = out["psi"].map(psi_band)
    out.attrs.update(cutoff=cutoff, n_ref=len(ref), n_cur=len(cur),
                     base_ref=base_r, base_cur=base_c, detail=detail)
    return out.sort_values("psi", ascending=False)


def shift_over_time(df, target="completed_purchase", freq="MS", min_n=500,
                    draws=300, seed=0):
    """Every column, month by month: did the leads arriving change shape?

    One reference period — the first month — and every later month compared
    back to it, column by column. The number reported is deliberately not PSI:
    it is the **share of that month's leads that would have to move to another
    bin** for the month to look like the reference. That needs no bands and no
    convention to read, and it is on the same scale for a categorical column
    and a numeric one.

    Even that number is never zero, because two samples of a few thousand leads
    disagree by chance. So each month also carries its own floor — the same
    comparison run on two samples drawn from one unchanged population — and a
    cell only counts as a shift when it clears its floor.
    """
    feats = [(c, f, k) for c, f, k in PROFILE if c != target]
    ordered = {c for c, _, k in feats if k in ("numeric", "discrete", "flag")}

    blocks = [(stamp, b) for stamp, b in df.set_index("created_at").resample(freq)
              if len(b) >= min_n]
    stamps = [s for s, _ in blocks]
    ref_stamp, ref = stamps[0], blocks[0][1]

    moved, floor, conv = {}, {}, {}
    for i, (stamp, block) in enumerate(blocks):
        conv[stamp] = (block[target].mean(), len(block))
        if stamp == ref_stamp:
            continue
        for j, (c, _, _) in enumerate(feats):
            keys, ka, kb = _shift_keys(ref[c], block[c], c in ordered)
            n_a = ka.value_counts().reindex(keys).fillna(0)
            n_b = kb.value_counts().reindex(keys).fillna(0)
            p_a, p_b = n_a / n_a.sum(), n_b / n_b.sum()
            moved[(c, stamp)] = float(0.5 * np.abs(p_a - p_b).sum() * 100)
            pooled = ((n_a + n_b) / (n_a.sum() + n_b.sum())).to_numpy()
            floor[(c, stamp)] = _shift_null(pooled, len(ref), len(block), draws,
                                            seed + i * 100 + j)[2]

    cols = [c for c, _, _ in feats]
    later = stamps[1:]
    M = pd.DataFrame([[moved[(c, s)] for s in later] for c in cols],
                     index=cols, columns=later)
    F = pd.DataFrame([[floor[(c, s)] for s in later] for c in cols],
                     index=cols, columns=later)
    rate = pd.DataFrame(conv, index=["rate", "n"]).T

    # ---------------------------------------------------------------- drawing
    order, fam, _, _, _ = _family_order(df, target)
    M, F = M.loc[order], F.loc[order]
    n, m = M.shape
    label = lambda s: f"{s:%b}"

    fig = plt.figure(figsize=(2.6 + 1.05 * m, 1.4 + 0.30 * n), layout="constrained")
    gs = gridspec.GridSpec(2, 1, figure=fig, height_ratios=[1.5, 0.30 * n])

    ax1 = fig.add_subplot(gs[0])
    ax1.plot(range(len(stamps)), rate["rate"] * 100, "o-", color=BLUE, lw=1.7, ms=5)
    for x, s in enumerate(stamps):
        ax1.annotate(f"{rate.loc[s, 'rate'] * 100:.1f}%", (x, rate.loc[s, "rate"] * 100),
                     xytext=(0, 7), textcoords="offset points", fontsize=8,
                     color=INK, ha="center")
    ax1.set_xlim(-0.5, m + 0.5)
    ax1.set_xticks([])
    ax1.set_ylabel("conversion %")
    ax1.set_title("The outcome changed in August")
    ax1.margins(y=0.32)

    ax2 = fig.add_subplot(gs[1])
    ax2.set_title("The arriving leads did not \u2014 every column, month by month")
    ax2.grid(False)
    ax2.set_xlim(-0.5, m + 0.5); ax2.set_ylim(n - 0.5, -0.5)
    for sp in ax2.spines.values():
        sp.set_visible(False)
    ax2.set_yticks(range(n)); ax2.set_yticklabels(order, fontsize=8)
    for tick, c in zip(ax2.get_yticklabels(), order):
        tick.set_color(FAM_COLOR[fam[c]])
    ax2.set_xticks(range(len(stamps)))
    ax2.set_xticklabels([f"{label(stamps[0])}\nreference"] +
                        [label(s) for s in later], fontsize=8.5)
    ax2.tick_params(length=0)

    # Colour is the value divided by its own floor, not the raw percentage: a
    # 2.5% move on a wide categorical column and a 1.0% move on a flag are the
    # same finding once each is read against what chance produces for it. 1.0
    # is the floor, so everything below it is one pale ramp and only a cell
    # that clears it takes colour.
    R = (M / F).to_numpy()
    cmap = matplotlib.colors.LinearSegmentedColormap.from_list(
        "shift", [(0.0, SURFACE), (0.62, "#f0e3d0"), (1.0, AMBER)])
    norm = matplotlib.colors.Normalize(0, 1.6)

    for i, c in enumerate(order):
        ax2.add_patch(plt.Rectangle((-0.42, i - 0.40), 0.84, 0.80, color="#eceef1"))
        for x, s_ in enumerate(later, start=1):
            v, r = M.loc[c, s_], R[i, x - 1]
            ax2.add_patch(plt.Rectangle((x - 0.42, i - 0.40), 0.84, 0.80,
                                        color=cmap(norm(r))))
            ax2.annotate(f"{v:.1f}", (x, i), fontsize=7.4, ha="center", va="center",
                         color="white" if r > 1.25 else (INK if r > 1 else MUTED))

    cb = fig.colorbar(matplotlib.cm.ScalarMappable(norm=norm, cmap=cmap), ax=ax2,
                      fraction=0.022, pad=0.012, aspect=34, ticks=[0, 0.5, 1.0, 1.5])
    cb.set_label("shift \u00f7 its own noise floor", fontsize=7.5, color=MUTED)
    cb.ax.set_yticklabels(["0", "\u00bd", "the floor", "1\u00bd\u00d7"], fontsize=7)
    cb.ax.tick_params(length=0, colors=MUTED)
    cb.outline.set_visible(False)

    fl_lo, fl_hi = F.to_numpy().min(), F.to_numpy().max()
    ax2.set_xlabel("% of that month's leads that would have to change bin to match "
                   f"{label(ref_stamp)}\n"
                   f"chance alone produces {fl_lo:.1f}\u2013{fl_hi:.1f}% \u00b7 "
                   "a cell only takes colour once it clears its own floor",
                   fontsize=8, color=MUTED)
    return fig, pd.concat({"moved_pct": M, "noise_floor": F}, axis=1)


def lift_stability(df, target="completed_purchase", holdout_days=None,
                   min_n=200, table=None):
    """Whether the drop is a level change or a change in what predicts.

    Every bin of every column is a point, once in absolute conversion and once
    in lift over its own period's base rate. Points on the diagonal in the
    right-hand panel mean the column still separates the same way — the model
    would rank these leads in the same order — even though the left-hand panel
    shows every one of them converting less.
    """
    t = shift_table(df, target, holdout_days) if table is None else table
    detail, fam = t.attrs["detail"], t["family"]
    ratio = t.attrs["base_cur"] / t.attrs["base_ref"]

    pts = []
    for c, d in detail.items():
        keep = (d["n_ref"] >= min_n) & (d["n_cur"] >= min_n)
        for _, r in d[keep].iterrows():
            # How far this bin's lift moved, in standard errors. If the lift is
            # genuinely unchanged and the scatter is only sampling noise, these
            # z-scores have a spread of 1 and almost none clear 2.
            se = np.hypot(
                np.sqrt(r["rate_cur"] * (1 - r["rate_cur"]) / r["n_cur"]) / t.attrs["base_cur"],
                np.sqrt(r["rate_ref"] * (1 - r["rate_ref"]) / r["n_ref"]) / t.attrs["base_ref"])
            pts.append((c, fam[c], r["n_cur"], r["rate_ref"] * 100,
                        r["rate_cur"] * 100, r["lift_ref"], r["lift_cur"],
                        (r["lift_cur"] - r["lift_ref"]) / se))
    P = pd.DataFrame(pts, columns=["column", "family", "n", "rate_ref", "rate_cur",
                                   "lift_ref", "lift_cur", "z"])
    size = 6 + 26 * (P["n"] / P["n"].max())
    colour = [FAM_COLOR[f] for f in P["family"]]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(9.6, 4.4))

    hi = max(P["rate_ref"].max(), P["rate_cur"].max()) * 1.12
    ax1.plot([0, hi], [0, hi], color=MUTED, lw=1, ls="--")
    ax1.plot([0, hi], [0, hi * ratio], color=CORAL, lw=1.2)
    ax1.scatter(P["rate_ref"], P["rate_cur"], s=size, c=colour, alpha=0.8,
                linewidths=0)
    ax1.annotate(f"×{ratio:.2f} — every bin, the same factor", (hi, hi * ratio),
                 xytext=(-4, -12), textcoords="offset points", fontsize=8,
                 color=CORAL, ha="right")
    ax1.annotate("no change", (hi, hi), xytext=(-4, -10),
                 textcoords="offset points", fontsize=8, color=MUTED, ha="right")
    ax1.set_xlim(0, hi); ax1.set_ylim(0, hi)
    ax1.set_xlabel("conversion % in the training period")
    ax1.set_ylabel("conversion % in the holdout")
    ax1.set_title("Absolute rates: all of them fell")

    lo = min(P["lift_ref"].min(), P["lift_cur"].min()) * 0.9
    hi2 = max(P["lift_ref"].max(), P["lift_cur"].max()) * 1.06
    ax2.plot([lo, hi2], [lo, hi2], color=MUTED, lw=1, ls="--")
    ax2.axhline(1, color=GRID, lw=0.8); ax2.axvline(1, color=GRID, lw=0.8)
    ax2.scatter(P["lift_ref"], P["lift_cur"], s=size, c=colour, alpha=0.8,
                linewidths=0)
    r = np.corrcoef(P["lift_ref"], P["lift_cur"])[0, 1]
    loud = int((P["z"].abs() > 2).sum())
    ax2.annotate(f"r = {r:.3f}", (0.03, 0.93), xycoords="axes fraction",
                 fontsize=9, color=INK)
    ax2.annotate(f"the spread around the diagonal is {P['z'].std():.2f} standard "
                 f"errors\n{loud} of {len(P)} bins clear two, "
                 f"{0.045 * len(P):.0f} expected by chance",
                 (0.03, 0.80), xycoords="axes fraction", fontsize=8, color=MUTED)
    ax2.set_xlim(lo, hi2); ax2.set_ylim(lo, hi2)
    ax2.set_xlabel("lift over the base rate, training period")
    ax2.set_ylabel("lift over the base rate, holdout")
    ax2.set_title("Relative to each period's base: unchanged")

    fig.suptitle("Every bin of every column, before and after the break",
                 x=0.005, ha="left", fontsize=12)
    fig.text(0.005, 0.012, f"one point per bin with at least {min_n} leads on "
             "each side, sized by holdout volume", fontsize=8, color=MUTED)
    x = 0.49
    for f, colour in FAM_COLOR.items():
        fig.text(x, 0.012, f, fontsize=8, color=colour)
        x += 0.0075 * len(f) + 0.020
    return fig, P
