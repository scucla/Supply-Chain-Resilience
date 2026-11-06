"""CLI: run the full analysis and write CSVs to outputs/.

    python run_analysis.py
"""
from pathlib import Path

import pandas as pd

from src.pipeline import Inputs, run

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

    r["scored"].to_csv(OUT / "risk_scores.csv", index=False)
    r["orders"].to_csv(OUT / "order_schedule.csv", index=False)
    r["safety_stock"].to_csv(OUT / "safety_stock.csv", index=False)
    r["lots"].to_csv(OUT / "lot_sizing.csv", index=False)
    m.drop(columns="_specs").to_csv(OUT / "mitigations.csv", index=False)
    r["requirements"].to_csv(OUT / "gross_requirements.csv")
    print(f"\nCSVs written to {OUT}/")


if __name__ == "__main__":
    main()
