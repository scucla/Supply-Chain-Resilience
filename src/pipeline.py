"""One function that wires every module together (used by the CLI and the app)."""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from . import bom as bom_mod
from . import demand, risk
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


def run(inp: Inputs | None = None, with_mitigations: bool = True) -> dict:
    inp = inp or Inputs()
    raw, materials, countries = bom_mod.load_data()
    exploded = bom_mod.explode(raw)
    parts = bom_mod.purchased_parts(exploded)

    plan = demand.production_plan(inp.start_rate, inp.end_rate, inp.months, inp.ramp_shape)
    reqs = demand.gross_requirements(parts, plan)
    ss = demand.safety_stock(parts, plan, inp.service_level, inp.demand_cv)
    orders = demand.order_schedule(parts, plan)
    spend = demand.spend_by_part(parts, plan)

    scored = risk.score_parts(parts, materials, countries, inp.weights)
    scored = scored.merge(spend.rename("horizon_spend_usd"), left_on="part_id", right_index=True)
    params = risk.disruption_params(scored, materials, countries)

    init_inv = ss.set_index("part_id")["safety_stock_units"]
    sim = Simulator(parts, params, plan, init_inv, inp.sim)
    base = sim.run()

    out = {
        "exploded": exploded, "parts": parts, "plan": plan, "requirements": reqs,
        "safety_stock": ss, "orders": orders, "scored": scored, "params": params,
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
