"""Phase-1 plots.

Rules enforced here rather than per call site:

* every plot is generated from a saved aggregate table, and writes that table
  next to the figure;
* axes are labelled and the sample size is stated in the title or the caption
  line;
* rate axes are anchored at 0 (no truncated axes that exaggerate differences);
* the analysis level (trajectory vs instance) is named in the title.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

# Centralized cosmetics - do not hardcode these at call sites.
STYLE = {
    "figsize": (7.2, 4.4),
    "figsize_wide": (9.5, 4.6),
    "dpi": 160,
    "grid_alpha": 0.25,
    "bar_color": "#4C72B0",
    "bar_color_alt": "#DD8452",
    "oracle_color": "#55A868",
    "baseline_color": "#8C8C8C",
    "point_color": "#4C72B0",
    "err_color": "#333333",
    "ref_color": "#B0B0B0",
    "correct_color": "#55A868",
    "wrong_color": "#C44E52",
    "title_size": 11,
    "label_size": 10,
}


def _finish(fig: plt.Figure, ax: plt.Axes, title: str, xlabel: str, ylabel: str, caption: str) -> plt.Figure:
    ax.set_title(title, fontsize=STYLE["title_size"])
    ax.set_xlabel(xlabel, fontsize=STYLE["label_size"])
    ax.set_ylabel(ylabel, fontsize=STYLE["label_size"])
    ax.grid(alpha=STYLE["grid_alpha"], linestyle=":")
    ax.set_axisbelow(True)
    fig.text(0.01, 0.005, caption, fontsize=7.5, color="#555555", ha="left", va="bottom")
    fig.tight_layout(rect=(0, 0.035, 1, 1))
    return fig


def _save(fig: plt.Figure, table: pd.DataFrame, out_dir: Path, name: str) -> dict:
    out_dir = Path(out_dir)
    (out_dir / "figures").mkdir(parents=True, exist_ok=True)
    (out_dir / "tables").mkdir(parents=True, exist_ok=True)
    png = out_dir / "figures" / f"{name}.png"
    csv = out_dir / "tables" / f"{name}.csv"
    fig.savefig(png, dpi=STYLE["dpi"], bbox_inches="tight")
    plt.close(fig)
    table.to_csv(csv, index=False)
    return {"figure": str(png), "table": str(csv)}


def _empty(out_dir: Path, name: str, message: str) -> dict:
    fig, ax = plt.subplots(figsize=STYLE["figsize"])
    ax.text(0.5, 0.5, message, ha="center", va="center", wrap=True, fontsize=10)
    ax.set_axis_off()
    return _save(fig, pd.DataFrame([{"note": message}]), out_dir, name)


# --------------------------------------------------------------------------
# 1. Selector performance
# --------------------------------------------------------------------------


def plot_selector_performance(summary: pd.DataFrame, out_dir: Path, n_instances: int) -> dict:
    if summary is None or not len(summary):
        return _empty(out_dir, "01_selector_performance", "No selector results available")
    df = summary.dropna(subset=["point"]).sort_values("point")
    fig, ax = plt.subplots(figsize=STYLE["figsize_wide"])
    colors = [
        STYLE["oracle_color"]
        if r.get("is_upper_bound")
        else (
            STYLE["baseline_color"]
            if r["selector"] in ("first", "random_expected", "random_sampled_mean")
            else STYLE["bar_color"]
        )
        for _, r in df.iterrows()
    ]
    y = np.arange(len(df))
    lo = (df["point"] - df["ci_lo"]).clip(lower=0)
    hi = (df["ci_hi"] - df["point"]).clip(lower=0)
    ax.barh(y, df["point"], color=colors, height=0.65)
    ax.errorbar(df["point"], y, xerr=[lo, hi], fmt="none", ecolor=STYLE["err_color"], capsize=3, lw=1.2)
    ax.set_yticks(y)
    ax.set_yticklabels(df["selector"])
    ax.set_xlim(0, min(1.0, max(1e-9, df["ci_hi"].max() * 1.15)))
    return _save(
        _finish(
            fig,
            ax,
            f"Selector performance (instance level, n={n_instances} instances)",
            "Mean official reward",
            "",
            "95% percentile bootstrap CI, resampling task instances. Green = ORACLE UPPER BOUND (uses ground truth, not deployable). Grey = baselines.",
        ),
        df,
        out_dir,
        "01_selector_performance",
    )


# --------------------------------------------------------------------------
# 2. Oracle@K
# --------------------------------------------------------------------------


def plot_oracle_at_k(table: pd.DataFrame, out_dir: Path) -> dict:
    if table is None or not len(table):
        return _empty(out_dir, "02_oracle_at_k", "No oracle@K results available")
    fig, ax = plt.subplots(figsize=STYLE["figsize"])
    ax.plot(table["k"], table["oracle_all_subsets"], "o-", color=STYLE["oracle_color"], label="Oracle@K (all subsets)")
    ax.plot(
        table["k"],
        table["oracle_first_k_prefix"],
        "s--",
        color=STYLE["bar_color"],
        label="Oracle@K (first-K prefix)",
    )
    ax.set_xticks(table["k"])
    ax.set_ylim(0, 1.0)
    ax.legend(fontsize=8)
    n = int(table["n_instances"].max()) if len(table) else 0
    return _save(
        _finish(
            fig,
            ax,
            f"Oracle@K candidate-generation ceiling (instance level, n={n})",
            "K sampled trajectories",
            "Mean official reward of the best candidate",
            "UPPER BOUND ONLY: selects using ground truth. Shows whether independent sampling ever produces a correct alternative.",
        ),
        table,
        out_dir,
        "02_oracle_at_k",
    )


# --------------------------------------------------------------------------
# 3. First / plurality / oracle by task
# --------------------------------------------------------------------------


def plot_by_task(by_task: pd.DataFrame, out_dir: Path) -> dict:
    if by_task is None or not len(by_task):
        return _empty(out_dir, "03_by_task", "No per-task results available")
    cols = [c for c in ("first", "plurality", "oracle") if c in by_task.columns]
    df = by_task.sort_values("task_name")
    x = np.arange(len(df))
    width = 0.8 / max(1, len(cols))
    fig, ax = plt.subplots(figsize=STYLE["figsize_wide"])
    palette = {"first": STYLE["baseline_color"], "plurality": STYLE["bar_color"], "oracle": STYLE["oracle_color"]}
    for i, c in enumerate(cols):
        ax.bar(x + i * width - 0.4 + width / 2, df[c], width=width, label=c, color=palette.get(c, STYLE["bar_color"]))
    ax.set_xticks(x)
    ax.set_xticklabels(
        [f"{t}\n(n={int(n)})" for t, n in zip(df["task_name"], df.get("n", [0] * len(df)), strict=False)],
        rotation=35,
        ha="right",
        fontsize=7.5,
    )
    ax.set_ylim(0, 1.0)
    ax.legend(fontsize=8)
    return _save(
        _finish(
            fig,
            ax,
            "First vs plurality vs oracle, by task (instance level)",
            "",
            "Mean official reward",
            "Oracle is an upper bound (uses ground truth). Per-task n is small; treat differences as descriptive.",
        ),
        df,
        out_dir,
        "03_by_task",
    )


# --------------------------------------------------------------------------
# 4-5. Calibration
# --------------------------------------------------------------------------


def plot_reliability(reliability: pd.DataFrame, out_dir: Path, extra: dict | None = None) -> dict:
    if reliability is None or not len(reliability) or reliability["n"].sum() == 0:
        return _empty(out_dir, "04_reliability_diagram", "No valid verbalized confidence available")
    df = reliability[reliability["n"] > 0].copy()
    fig, ax = plt.subplots(figsize=STYLE["figsize"])
    ax.plot([0, 1], [0, 1], "--", color=STYLE["ref_color"], lw=1, label="perfect calibration")
    ax.plot(df["mean_confidence"], df["accuracy"], "o-", color=STYLE["point_color"], label="observed")
    for _, r in df.iterrows():
        ax.annotate(
            f"n={int(r['n'])}",
            (r["mean_confidence"], r["accuracy"]),
            textcoords="offset points",
            xytext=(4, 5),
            fontsize=7.5,
            color="#555555",
        )
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.legend(fontsize=8)
    bits = []
    if extra:
        for k in ("brier", "ece_equal_width", "auroc", "confidence_parse_rate"):
            if extra.get(k) is not None:
                bits.append(f"{k}={extra[k]:.3f}")
    n_total = int(df["n"].sum())
    return _save(
        _finish(
            fig,
            ax,
            f"Reliability of verbalized confidence (trajectory level, n={n_total})",
            "Mean stated confidence in bin",
            "Observed accuracy in bin",
            "Equal-width bins; bin counts annotated. " + ("  ".join(bits) if bits else ""),
        ),
        df,
        out_dir,
        "04_reliability_diagram",
    )


def plot_accuracy_by_confidence(reliability: pd.DataFrame, out_dir: Path) -> dict:
    if reliability is None or not len(reliability) or reliability["n"].sum() == 0:
        return _empty(out_dir, "05_accuracy_by_confidence_bin", "No valid verbalized confidence available")
    df = reliability[reliability["n"] > 0].copy()
    fig, ax = plt.subplots(figsize=STYLE["figsize"])
    labels = [f"[{r.lo:.1f},{r.hi:.1f})\nn={int(r.n)}" for r in df.itertuples()]
    ax.bar(np.arange(len(df)), df["accuracy"], color=STYLE["bar_color"])
    ax.set_xticks(np.arange(len(df)))
    ax.set_xticklabels(labels, fontsize=7.5)
    ax.set_ylim(0, 1)
    return _save(
        _finish(
            fig,
            ax,
            f"Accuracy by stated-confidence bin (trajectory level, n={int(df['n'].sum())})",
            "Stated confidence bin",
            "Mean official reward",
            "Bars show mean reward of trajectories whose stated confidence falls in the bin.",
        ),
        df,
        out_dir,
        "05_accuracy_by_confidence_bin",
    )


# --------------------------------------------------------------------------
# 6. Plurality fraction
# --------------------------------------------------------------------------


def plot_accuracy_by_plurality(instrumented: pd.DataFrame, out_dir: Path) -> dict:
    if instrumented is None or "instance_plurality_fraction" not in instrumented:
        return _empty(out_dir, "06_accuracy_by_plurality_fraction", "No consensus features available")
    sub = instrumented.dropna(subset=["instance_plurality_fraction", "reward"])
    if not len(sub):
        return _empty(out_dir, "06_accuracy_by_plurality_fraction", "No consensus features available")
    df = (
        sub.groupby("instance_plurality_fraction")
        .agg(mean_reward=("reward", "mean"), n=("reward", "size"))
        .reset_index()
        .sort_values("instance_plurality_fraction")
    )
    fig, ax = plt.subplots(figsize=STYLE["figsize"])
    ax.bar(np.arange(len(df)), df["mean_reward"], color=STYLE["bar_color"])
    ax.set_xticks(np.arange(len(df)))
    ax.set_xticklabels(
        [f"{v:.2f}\nn={int(n)}" for v, n in zip(df["instance_plurality_fraction"], df["n"], strict=True)], fontsize=8
    )
    ax.set_ylim(0, 1)
    return _save(
        _finish(
            fig,
            ax,
            f"Reward by consensus size (trajectory level, n={len(sub)})",
            "Plurality fraction of the trajectory's instance",
            "Mean official reward",
            "Higher plurality fraction = stronger agreement among the K sampled trajectories.",
        ),
        df,
        out_dir,
        "06_accuracy_by_plurality_fraction",
    )


# --------------------------------------------------------------------------
# 7-8. Behavioural signals
# --------------------------------------------------------------------------


def plot_length_vs_correct(instrumented: pd.DataFrame, out_dir: Path, length_field: str) -> dict:
    if instrumented is None or length_field not in instrumented:
        return _empty(out_dir, "07_length_vs_correctness", f"{length_field} unavailable")
    sub = instrumented.dropna(subset=[length_field, "correct"])
    if not len(sub) or sub["correct"].nunique() < 2:
        return _empty(out_dir, "07_length_vs_correctness", f"{length_field}: insufficient data or single class")
    fig, ax = plt.subplots(figsize=STYLE["figsize"])
    groups = [sub[sub["correct"] == 0][length_field], sub[sub["correct"] == 1][length_field]]
    bp = ax.boxplot(
        groups,
        tick_labels=[f"incorrect\n(n={len(groups[0])})", f"correct\n(n={len(groups[1])})"],
        patch_artist=True,
        widths=0.5,
    )
    for patch, color in zip(bp["boxes"], [STYLE["wrong_color"], STYLE["correct_color"]], strict=True):
        patch.set_facecolor(color)
        patch.set_alpha(0.65)
    for i, g in enumerate(groups, start=1):
        ax.scatter(np.random.default_rng(0).normal(i, 0.05, len(g)), g, s=9, color="#333333", alpha=0.4, zorder=3)
    ax.set_ylim(bottom=0)
    table = sub.groupby("correct")[length_field].describe().reset_index()
    return _save(
        _finish(
            fig,
            ax,
            f"Trace length vs correctness (trajectory level, n={len(sub)})",
            "",
            length_field,
            "Box = IQR, whiskers 1.5*IQR, points = individual trajectories.",
        ),
        table,
        out_dir,
        "07_length_vs_correctness",
    )


def plot_tool_failure_vs_correct(instrumented: pd.DataFrame, out_dir: Path) -> dict:
    field = "failed_tool_call_count"
    if instrumented is None or field not in instrumented:
        return _empty(out_dir, "08_tool_failure_vs_correctness", f"{field} unavailable")
    sub = instrumented.dropna(subset=[field, "reward"]).copy()
    if not len(sub):
        return _empty(out_dir, "08_tool_failure_vs_correctness", f"{field}: no data")
    sub["bucket"] = np.where(sub[field] > 0, "≥1 failed execution", "0 failed executions")
    df = sub.groupby("bucket").agg(mean_reward=("reward", "mean"), n=("reward", "size")).reset_index()
    fig, ax = plt.subplots(figsize=STYLE["figsize"])
    ax.bar(df["bucket"], df["mean_reward"], color=[STYLE["bar_color"], STYLE["bar_color_alt"]][: len(df)])
    for i, r in df.iterrows():
        ax.text(i, r["mean_reward"], f"n={int(r['n'])}", ha="center", va="bottom", fontsize=8)
    ax.set_ylim(0, 1)
    return _save(
        _finish(
            fig,
            ax,
            f"Reward by presence of a failed code execution (trajectory level, n={len(sub)})",
            "",
            "Mean official reward",
            "A 'failed execution' is a code block whose observable result was an error or a timeout.",
        ),
        df,
        out_dir,
        "08_tool_failure_vs_correctness",
    )


def plot_confidence_vs_length(instrumented: pd.DataFrame, out_dir: Path, length_field: str) -> dict:
    if instrumented is None or "final_confidence" not in instrumented or length_field not in instrumented:
        return _empty(out_dir, "09_confidence_vs_length", "confidence or length unavailable")
    sub = instrumented.dropna(subset=["final_confidence", length_field, "correct"])
    if not len(sub):
        return _empty(out_dir, "09_confidence_vs_length", "No trajectory has both confidence and length")
    fig, ax = plt.subplots(figsize=STYLE["figsize"])
    for label, color, marker in ((1, STYLE["correct_color"], "o"), (0, STYLE["wrong_color"], "x")):
        s = sub[sub["correct"] == label]
        ax.scatter(
            s[length_field],
            s["final_confidence"],
            c=color,
            marker=marker,
            s=28,
            alpha=0.75,
            label=f"{'correct' if label else 'incorrect'} (n={len(s)})",
        )
    ax.set_ylim(0, 1.02)
    ax.set_xlim(left=0)
    ax.legend(fontsize=8)
    return _save(
        _finish(
            fig,
            ax,
            f"Stated confidence vs trace length (trajectory level, n={len(sub)})",
            length_field,
            "Stated confidence (normalized to [0,1])",
            "The two signals combined by the SRLM-style selector.",
        ),
        sub[[length_field, "final_confidence", "correct", "run_id"]],
        out_dir,
        "09_confidence_vs_length",
    )


def plot_confidence_length_heatmap(
    instrumented: pd.DataFrame, out_dir: Path, length_field: str, min_cell: int = 3
) -> dict:
    """Analogue of the motivating SRLM confidence x length accuracy heatmap.

    Only drawn when every populated cell has at least ``min_cell`` observations;
    otherwise a note is emitted rather than a misleading picture.
    """
    name = "12_confidence_length_heatmap"
    if instrumented is None or "final_confidence" not in instrumented or length_field not in instrumented:
        return _empty(out_dir, name, "confidence or length unavailable")
    sub = instrumented.dropna(subset=["final_confidence", length_field, "correct"]).copy()
    if len(sub) < 4 * min_cell:
        return _empty(out_dir, name, f"Only {len(sub)} trajectories have both signals; too few for a 2x2 heatmap")
    c_med = sub["final_confidence"].median()
    l_med = sub[length_field].median()
    sub["c_bin"] = np.where(sub["final_confidence"] >= c_med, "high conf", "low conf")
    sub["l_bin"] = np.where(sub[length_field] >= l_med, "long trace", "short trace")
    grid = sub.pivot_table(index="c_bin", columns="l_bin", values="correct", aggfunc="mean")
    counts = sub.pivot_table(index="c_bin", columns="l_bin", values="correct", aggfunc="size")
    if counts.min().min() < min_cell:
        return _empty(
            out_dir,
            name,
            f"Smallest cell has {int(counts.min().min())} trajectories (< {min_cell}); heatmap suppressed",
        )

    fig, ax = plt.subplots(figsize=(5.6, 4.2))
    im = ax.imshow(grid.values, cmap="viridis", vmin=0, vmax=1)
    ax.set_xticks(range(grid.shape[1]), grid.columns)
    ax.set_yticks(range(grid.shape[0]), grid.index)
    for i in range(grid.shape[0]):
        for j in range(grid.shape[1]):
            ax.text(
                j,
                i,
                f"{grid.values[i, j]:.2f}\nn={int(counts.values[i, j])}",
                ha="center",
                va="center",
                color="white",
                fontsize=9,
            )
    fig.colorbar(im, ax=ax, label="Mean official reward")
    table = grid.reset_index().melt(id_vars="c_bin", value_name="mean_reward")
    return _save(
        _finish(
            fig,
            ax,
            f"Confidence x length accuracy (trajectory level, n={len(sub)})",
            f"{length_field} (split at median {l_med:.0f})",
            f"Stated confidence (split at median {c_med:.2f})",
            "Median splits, not fixed thresholds. Exploratory.",
        ),
        table,
        out_dir,
        name,
    )


# --------------------------------------------------------------------------
# 10-11. Perturbation and missingness
# --------------------------------------------------------------------------


def plot_prompt_perturbation(perturbation: dict, out_dir: Path) -> dict:
    name = "10_prompt_perturbation"
    if not perturbation or not perturbation.get("n_paired_instances"):
        return _empty(out_dir, name, "No paired standard/instrumented instances available")
    std = perturbation["standard_reward"]
    inst = perturbation["instrumented_t0_reward"]
    df = pd.DataFrame(
        [
            {"condition": "A: standard\n(no confidence request)", **std},
            {"condition": "B: instrumented t=0\n(confidence request)", **inst},
        ]
    )
    fig, ax = plt.subplots(figsize=STYLE["figsize"])
    x = np.arange(len(df))
    ax.bar(x, df["point"], color=[STYLE["baseline_color"], STYLE["bar_color"]], width=0.55)
    ax.errorbar(
        x,
        df["point"],
        yerr=[(df["point"] - df["ci_lo"]).clip(lower=0), (df["ci_hi"] - df["point"]).clip(lower=0)],
        fmt="none",
        ecolor=STYLE["err_color"],
        capsize=4,
    )
    ax.set_xticks(x)
    ax.set_xticklabels(df["condition"], fontsize=8.5)
    ax.set_ylim(0, 1)
    d = perturbation["reward_difference"]
    caption = (
        f"Paired over n={perturbation['n_paired_instances']} instances. "
        f"Difference (B-A) = {d['difference']:+.3f} [{d['ci_lo']:+.3f}, {d['ci_hi']:+.3f}]. "
        f"Answer-change rate = {perturbation.get('answer_change_rate', float('nan')):.2f}."
    )
    return _save(
        _finish(fig, ax, "Prompt-perturbation check (instance level)", "", "Mean official reward", caption),
        df,
        out_dir,
        name,
    )


def plot_missingness(trajectories: pd.DataFrame, out_dir: Path) -> dict:
    name = "11_missingness_and_failures"
    if trajectories is None or not len(trajectories):
        return _empty(out_dir, name, "No trajectories available")
    rows = []
    total = len(trajectories)
    rows.append({"category": "planned runs", "n": total, "fraction": 1.0})
    for label, mask in (
        ("run directory present", trajectories["run_present"] == True),  # noqa: E712
        ("completed", trajectories["completed"].fillna(False).astype(bool)),
        ("answer parsed", trajectories.get("answer_parse_status", pd.Series(dtype=str)) == "ok"),
        (
            "valid confidence",
            trajectories.get("confidence_parse_status", pd.Series(dtype=str)).isin(["ok", "multiple_blocks"]),
        ),
        (
            "token usage available",
            trajectories.get("token_usage_available", pd.Series(dtype=bool)).fillna(False).astype(bool),
        ),
    ):
        n = int(mask.sum()) if len(mask) else 0
        rows.append({"category": label, "n": n, "fraction": n / total if total else 0.0})
    df = pd.DataFrame(rows)
    fig, ax = plt.subplots(figsize=STYLE["figsize_wide"])
    ax.bar(np.arange(len(df)), df["fraction"], color=STYLE["bar_color"])
    for i, r in df.iterrows():
        ax.text(i, r["fraction"], f"{int(r['n'])}", ha="center", va="bottom", fontsize=8)
    ax.set_xticks(np.arange(len(df)))
    ax.set_xticklabels(df["category"], rotation=25, ha="right", fontsize=8)
    ax.set_ylim(0, 1.05)
    fails = trajectories["failure_class"].fillna("none").value_counts().to_dict()
    return _save(
        _finish(
            fig,
            ax,
            f"Data completeness and failures (trajectory level, n={total})",
            "",
            "Fraction of planned runs",
            f"Failure classes: {fails}",
        ),
        df,
        out_dir,
        name,
    )


def plot_signal_auroc(table: pd.DataFrame, out_dir: Path) -> dict:
    name = "13_signal_auroc"
    if table is None or "auroc" not in table:
        return _empty(out_dir, name, "No signal AUROC results available")
    df = table.dropna(subset=["auroc"]).sort_values("auroc")
    if not len(df):
        return _empty(out_dir, name, "No signal had both correctness classes present")
    fig, ax = plt.subplots(figsize=STYLE["figsize_wide"])
    y = np.arange(len(df))
    ax.barh(y, df["auroc"], color=STYLE["bar_color"], height=0.65)
    if "auroc_ci_lo" in df:
        ax.errorbar(
            df["auroc"],
            y,
            xerr=[(df["auroc"] - df["auroc_ci_lo"]).clip(lower=0), (df["auroc_ci_hi"] - df["auroc"]).clip(lower=0)],
            fmt="none",
            ecolor=STYLE["err_color"],
            capsize=3,
            lw=1.1,
        )
    ax.axvline(0.5, color=STYLE["ref_color"], ls="--", lw=1)
    ax.set_yticks(y)
    ax.set_yticklabels([f"{s} (n={int(n)})" for s, n in zip(df["signal"], df["n"], strict=True)], fontsize=8)
    ax.set_xlim(0, 1)
    return _save(
        _finish(
            fig,
            ax,
            "Trajectory-level AUROC of each signal for correctness",
            "AUROC",
            "",
            "Cluster bootstrap over task instances. Dashed line = chance. AUROC < 0.5 means the signal predicts INcorrectness.",
        ),
        df,
        out_dir,
        name,
    )


def generate_all(results: dict[str, Any], out_dir: str | Path, *, length_field: str) -> dict[str, dict]:
    """Generate the full Phase-1 figure set from saved aggregate results."""
    out_dir = Path(out_dir)
    sel = results.get("selectors") or {}
    calib = results.get("calibration") or {}
    inst = results.get("instrumented")
    figs: dict[str, dict] = {}
    n_inst = len(sel.get("per_instance", [])) if sel else 0

    figs["selector_performance"] = plot_selector_performance(sel.get("summary"), out_dir, n_inst)
    figs["oracle_at_k"] = plot_oracle_at_k(results.get("oracle_at_k"), out_dir)
    figs["by_task"] = plot_by_task(sel.get("by_task"), out_dir)
    figs["reliability"] = plot_reliability(calib.get("reliability"), out_dir, calib)
    figs["accuracy_by_confidence"] = plot_accuracy_by_confidence(calib.get("reliability"), out_dir)
    figs["accuracy_by_plurality"] = plot_accuracy_by_plurality(inst, out_dir)
    figs["length_vs_correct"] = plot_length_vs_correct(inst, out_dir, length_field)
    figs["tool_failure_vs_correct"] = plot_tool_failure_vs_correct(inst, out_dir)
    figs["confidence_vs_length"] = plot_confidence_vs_length(inst, out_dir, length_field)
    figs["prompt_perturbation"] = plot_prompt_perturbation(results.get("perturbation"), out_dir)
    figs["missingness"] = plot_missingness(results.get("trajectories"), out_dir)
    figs["confidence_length_heatmap"] = plot_confidence_length_heatmap(inst, out_dir, length_field)
    figs["signal_auroc"] = plot_signal_auroc(results.get("signal_auroc"), out_dir)
    return figs
