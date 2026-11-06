"""Sensitivity analysis: tornado chart + recommendation-stability table.

    python run_sensitivity.py      (about 40 seconds)
"""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from src.sensitivity import run_sensitivity

ROOT = Path(__file__).parent


def main() -> None:
    t, base_top = run_sensitivity()
    (ROOT / "outputs").mkdir(exist_ok=True)
    t.to_csv(ROOT / "docs" / "sensitivity.csv", index=False)   # committed so the dashboard can show it
    pd.set_option("display.width", 200, "display.max_colwidth", 60)
    print("Base-case top 3:", *base_top, sep="\n  ")
    print(t[["assumption", "fill_rate_low", "fill_rate_high", "swing", "top3_overlap_low", "top3_overlap_high"]]
          .round(3).to_string(index=False))
    for _, row in t.iterrows():
        for side in ("low", "high"):
            if row[f"top3_overlap_{side}"] < 3:
                print(f"  changed top-3 at {side}: {row['assumption']}  (new #1: {row[f'top1_{side}']})")
    same1 = sum((t[f"top1_{s}"] == base_top[0]).sum() for s in ("low", "high"))
    same3 = sum(t[f"top3_same_set_{s}"].sum() for s in ("low", "high"))
    print(f"\n#1 recommendation unchanged in {same1}/{2 * len(t)} cases; top-3 set unchanged in {same3}/{2 * len(t)}")
    _tornado(t, ROOT / "docs" / "tornado.png")


def _tornado(t: pd.DataFrame, path: Path) -> None:
    t = t.iloc[::-1]
    base = t["base_fill_rate"].iloc[0] * 100
    fig, ax = plt.subplots(figsize=(9, 4.8))
    y = range(len(t))
    lo, hi = t["fill_rate_low"] * 100 - base, t["fill_rate_high"] * 100 - base
    ax.barh(y, lo, left=base, color="#4C78A8", label="Low value of assumption")
    ax.barh(y, hi, left=base, color="#F58518", label="High value of assumption")
    for i, (_, r) in enumerate(t.iterrows()):
        stable = r["top3_same_set_low"] and r["top3_same_set_high"]
        ax.text(max(base + lo.iloc[i], base + hi.iloc[i]) + 0.15, i, "top-3 unchanged" if stable else "top-3: 2 of 3 kept",
                va="center", fontsize=7.5, color="#444" if stable else "#B22222")
    ax.axvline(base, color="black", lw=0.8)
    ax.set_yticks(list(y), t["assumption"], fontsize=8.5)
    ax.set_xlabel("Expected fill rate (%)")
    ax.set_title(f"Sensitivity of fill rate to each assumption (base {base:.1f}%)")
    ax.legend(fontsize=8, loc="lower left")
    ax.spines[["top", "right"]].set_visible(False)
    ax.set_xlim(min(base + lo.min(), base + hi.min()) - 0.5, max(base + lo.max(), base + hi.max()) + 2.5)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


if __name__ == "__main__":
    main()
