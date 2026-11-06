"""One function that wires every module together (used by the CLI and the app)."""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from . import bom as bom_mod
from . import demand, risk
from . import optimize
from .simulate import SimConfig, Simulator


@dataclass
class Inputs:
    start_rate: int = 50
    end_rate: int = 500
    months: int = 12
    ramp_shape: str = "s-curve"
    service_level: float = 0.95
    demand_cv: float = 0.20
    weights: dict = field(default_factory=lambda: dict(risk.DEFAULT_WEIGHTS))
    sim: SimConfig = field(default_factory=SimConfig)
    top_k_mitigations: int = 10
    order_cost: float = 400.0          # $ per purchase order (admin, inspection, fixed freight) - assumption
    use_lot_sizing: bool = True        # order in max(EOQ, MOQ) lots instead of exactly what is needed
    unit_price_usd: float = 80_000     # illustrative sale price per system - assumption
    conversion_cost_usd: float = 15_000  # assembly labor, test, overhead per system - assumption


def run(inp: Inputs | None = None, with_mitigations: bool = True) -> dict:
    inp = inp or Inputs()
    raw, materials, countries = bom_mod.load_data()
    exploded = bom_mod.explode(raw)
    parts = bom_mod.purchased_parts(exploded)

    plan = demand.production_plan(inp.start_rate, inp.end_rate, inp.months, inp.ramp_shape)
    reqs = demand.gross_requirements(parts, plan)
    ss = demand.safety_stock(parts, plan, inp.service_level, inp.demand_cv)
    lots = demand.lot_sizing(parts, plan, inp.order_cost, inp.sim.carrying_rate)
    lot_map = lots.set_index("part_id")["lot_size"] if inp.use_lot_sizing else None
    orders = demand.order_schedule(parts, plan, lot_map)
    spend = demand.spend_by_part(parts, plan)

    scored = risk.score_parts(parts, materials, countries, inp.weights)
    scored = scored.merge(spend.rename("horizon_spend_usd"), left_on="part_id", right_index=True)
    params = risk.disruption_params(scored, materials, countries)

    init_inv = ss.set_index("part_id")["safety_stock_units"]
    material_cost = float((parts["extended_qty"] * parts["unit_cost_usd"]).where(parts["direct_buy"], 0).sum())
    margin = inp.unit_price_usd - material_cost - inp.conversion_cost_usd
    inp.sim.margin_per_unit = max(margin, 0.0)
    sim = Simulator(parts, params, plan, init_inv, inp.sim, lots=lot_map)
    base = sim.run()

    out = {
        "exploded": exploded, "parts": parts, "plan": plan, "requirements": reqs,
        "safety_stock": ss, "orders": orders, "lots": lots, "scored": scored, "params": params,
        "unit_economics": {"unit_price_usd": inp.unit_price_usd, "material_cost_usd": material_cost,
                           "conversion_cost_usd": inp.conversion_cost_usd, "margin_per_unit_usd": margin},
        "materials": risk.material_metrics(materials, countries),
        "compliance": risk.compliance_review(exploded, countries),
        "sim_summary": sim.summarize(base), "bands": sim.monthly_bands(base),
        "attribution": sim.binding_attribution(base), "shortfall_dist": pd.Series(base["shortfall"]),
        "conditional": sim.conditional_summary(base),
    }
    if with_mitigations:
        m = sim.evaluate_mitigations(scored, inp.top_k_mitigations)
        out["mitigations"] = m
        out["portfolios"] = [{"n": n, **sim.evaluate_portfolio(m, n)} for n in (1, 3, 5) if n <= len(m)]
    out["simulator"] = sim
    return out


def budget_frontier(r: dict, objective: str = "mean", max_steps: int = 10,
                    budgets: tuple = (100_000, 250_000, 500_000, 1_000_000), top_k: int = 10) -> dict:
    """Greedy re-simulated frontier, the naive ranking for comparison, and best sets for fixed budgets."""
    sim = r["simulator"]
    cands = sim.candidate_actions(r["scored"], top_k)
    return {
        "greedy": optimize.greedy(sim, cands, objective=objective, max_steps=max_steps),
        "naive": optimize.naive_prefix(sim, r["mitigations"], objective=objective, max_steps=max_steps),
        "budgets": optimize.best_for_budgets(sim, cands, list(budgets), objective=objective),
    }
