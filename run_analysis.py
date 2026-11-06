"""CLI: run the full analysis and write CSVs to outputs/.

    python run_analysis.py
"""
from pathlib import Path

import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from src.pipeline import Inputs, budget_frontier, run

OUT = Path(__file__).parent / "outputs"


def main() -> None:
    OUT.mkdir(exist_ok=True)
    r = run(Inputs())
    pd.set_option("display.width", 160, "display.max_columns", 20)

    print("\n== Production plan (units/month) ==")
    print(r["plan"].to_frame().T.to_string())

    print("\n== Top 10 supply risks ==")
    cols = ["part_id", "part_name", "tier", "supplier_country", "key_material", "risk_score", "top_driver", "compliance_flag"]
    print(r["scored"][cols].head(10).round(3).to_string(index=False))

    print("\n== Simulation (baseline) ==")
    for k, v in r["sim_summary"].items():
        print(f"  {k:22s} {v:,.3f}")

    ue = r["unit_economics"]
    print(f"\n== Unit economics (illustrative) ==\n  price ${ue['unit_price_usd']:,.0f} - parts ${ue['material_cost_usd']:,.0f}"
          f" - assembly ${ue['conversion_cost_usd']:,.0f} = profit ${ue['margin_per_unit_usd']:,.0f} per system")

    print("\n== Correlated shocks: expected shortfall with vs. without a country escalation ==")
    print(r["conditional"].round(1).to_string(index=False))

    print("\n== Which parts actually stopped the line ==")
    attr = r["attribution"].merge(r["parts"][["part_id", "part_name"]])
    print(attr.head(8).round(3).to_string(index=False))

    print("\n== Ranked mitigations ==")
    m = r["mitigations"]
    print(m[["risk_part", "action", "shortfall_avoided", "ci95_low", "ci95_high", "cost_usd", "net_benefit_usd", "return_on_cost"]]
          .head(10).round(1).to_string(index=False))

    print("\n== Ranked for the bad case (benefit if China escalates) ==")
    print(m.sort_values("avoided_if_CHN_shock", ascending=False)[["risk_part", "action", "shortfall_avoided",
          "avoided_if_CHN_shock", "cost_usd"]].head(6).round(1).to_string(index=False))

    print("\n== Bundles (top-n actions applied together) ==")
    base_fill = r["sim_summary"]["fill_rate"]
    for pf in r["portfolios"]:
        print(f"  top {pf['n']}: fill rate {base_fill:.1%} -> {pf['fill_rate']:.1%}, "
              f"E[shortfall] {r['sim_summary']['expected_shortfall']:.0f} -> {pf['expected_shortfall']:.0f}, cost ${pf['cost_usd']:,.0f}")

    print("\n== Compliance review (section 848) ==")
    print(r["compliance"][["part_id", "supplier_country", "inside_component", "finding"]].to_string(index=False))

    print("\n== Order-now list (release month <= 0) ==")
    late = r["orders"][r["orders"]["status"] != "planned"]
    print(late.groupby("part_id")["qty"].sum().sort_values(ascending=False).head(10).to_string())

    print("\n== Budget optimizer (greedy, re-simulated each step) ==")
    fr = {obj: budget_frontier(r, obj) for obj in ("mean", "cvar")}
    g = fr["mean"]["greedy"]
    print(g[["step", "action", "risk_part", "cumulative_cost_usd", "fill_rate", "cvar90_shortfall"]]
          .round(3).to_string(index=False))
    print("\n  Best set for each budget (risk-neutral objective):")
    print(fr["mean"]["budgets"][["budget_usd", "spent_usd", "n_actions", "fill_rate", "cvar90_shortfall"]]
          .round(3).to_string(index=False))
    _plot_frontier(fr, Path(__file__).parent / "docs" / "frontier.png")
    for obj, d in fr.items():
        d["greedy"].to_csv(OUT / f"frontier_greedy_{obj}.csv", index=False)
        d["budgets"].to_csv(OUT / f"best_by_budget_{obj}.csv", index=False)
    fr["mean"]["naive"].to_csv(OUT / "frontier_naive.csv", index=False)

    r["scored"].to_csv(OUT / "risk_scores.csv", index=False)
    r["orders"].to_csv(OUT / "order_schedule.csv", index=False)
    r["safety_stock"].to_csv(OUT / "safety_stock.csv", index=False)
    r["lots"].to_csv(OUT / "lot_sizing.csv", index=False)
    m.drop(columns="_specs").to_csv(OUT / "mitigations.csv", index=False)
    r["requirements"].to_csv(OUT / "gross_requirements.csv")
    print(f"\nCSVs written to {OUT}/")


def _plot_frontier(fr: dict, path: Path) -> None:
    fig, ax = plt.subplots(1, 2, figsize=(11, 4.2))
    for obj, style in (("mean", "-o"), ("cvar", "--s")):
        g = fr[obj]["greedy"]
        ax[0].plot(g["cumulative_cost_usd"] / 1e3, g["fill_rate"] * 100, style, ms=4,
                   label=f"Greedy ({'average' if obj == 'mean' else 'worst-10%'} objective)")
        ax[1].plot(g["cumulative_cost_usd"] / 1e3, g["cvar90_shortfall"], style, ms=4)
    n = fr["mean"]["naive"]
    ax[0].plot(n["cumulative_cost_usd"] / 1e3, n["fill_rate"] * 100, ":^", ms=4, color="gray",
               label="Naive (stand-alone ranking)")
    ax[1].plot(n["cumulative_cost_usd"] / 1e3, n["cvar90_shortfall"], ":^", ms=4, color="gray")
    ax[0].set(xlabel="Mitigation budget ($ thousands)", ylabel="Expected fill rate (%)",
              title="Efficient frontier: fill rate")
    ax[1].set(xlabel="Mitigation budget ($ thousands)", ylabel="Units short, average of worst 10%",
              title="Efficient frontier: bad-case shortfall")
    ax[0].legend(fontsize=8, loc="lower right")
    for a in ax:
        a.grid(alpha=0.3)
        a.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


if __name__ == "__main__":
    main()
