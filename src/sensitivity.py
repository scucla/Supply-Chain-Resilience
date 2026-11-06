"""One-at-a-time sensitivity analysis.

Each assumption is moved to a LOW and a HIGH value while everything else stays
at base. For each case we record the baseline fill rate (how fragile the plan
looks) and the top-3 recommended actions (does the advice change?).

Common random numbers: every case uses the same seed, so differences come from
the assumption, not from sampling noise.
"""
from __future__ import annotations

import copy
from dataclasses import replace

import pandas as pd

from .pipeline import Inputs, run
from .simulate import SimConfig

# (label, low, high, how to apply) - each apply(inputs, value) returns modified Inputs
CASES = [
    ("Part outage frequency (x0.5 / x1.5)", 0.5, 1.5,
     lambda i, v: replace(i, param_scale={**i.param_scale, "p_month": v})),
    ("Part outage length (x0.5 / x1.5)", 0.5, 1.5,
     lambda i, v: replace(i, param_scale={**i.param_scale, "mean_duration": v})),
    ("China escalation chance per month (1% / 3%)", 0.01, 0.03,
     lambda i, v: replace(i, sim=replace(i.sim, escalation_p_month={"CHN": v}))),
    ("China escalation length (2 / 6 months)", 2.0, 6.0,
     lambda i, v: replace(i, sim=replace(i.sim, escalation_mean_months=v))),
    ("Outage severity floor (15% / 45%)", 0.15, 0.45,
     lambda i, v: replace(i, sim=replace(i.sim, min_severity=v, escalation_min_severity=v))),
    ("Supplier catch-up capacity (12.5% / 37.5%)", 0.125, 0.375,
     lambda i, v: replace(i, sim=replace(i.sim, surge=v))),
    ("China geopolitical score (0.70 / 1.00)", 0.70, 1.00,
     lambda i, v: replace(i, country_risk_overrides={**i.country_risk_overrides, "CHN": v})),
    ("Germanium share from China (60% / 94%)", 0.60, 0.94,
     lambda i, v: replace(i, material_overrides={**i.material_overrides,
                                                 "germanium": {"CHN": v, "OTHER": round(1 - v, 4)}})),
    ("Forecast error (10% / 30%)", 0.10, 0.30,
     lambda i, v: replace(i, demand_cv=v)),
    ("Final production rate (250 / 750 per month)", 250, 750,
     lambda i, v: replace(i, end_rate=int(v))),
]


def _top3(r: dict) -> list[str]:
    m = r["mitigations"]
    return [f"{a} | {p}" for a, p in zip(m["action"].head(3), m["risk_part"].head(3))]


def run_sensitivity(base: Inputs | None = None, n_sims: int = 2000) -> tuple[pd.DataFrame, list[str]]:
    base = base or Inputs(sim=SimConfig(n_sims=n_sims))
    r0 = run(copy.deepcopy(base))
    base_fill, base_top = r0["sim_summary"]["fill_rate"], _top3(r0)
    rows = []
    for label, lo, hi, apply in CASES:
        row = {"assumption": label, "base_fill_rate": base_fill}
        for side, v in (("low", lo), ("high", hi)):
            r = run(apply(copy.deepcopy(base), v))
            top = _top3(r)
            row[f"fill_rate_{side}"] = r["sim_summary"]["fill_rate"]
            row[f"top3_same_set_{side}"] = set(top) == set(base_top)
            row[f"top3_overlap_{side}"] = len(set(top) & set(base_top))
            row[f"top1_{side}"] = top[0]
        row["swing"] = abs(row["fill_rate_high"] - row["fill_rate_low"])
        rows.append(row)
    out = pd.DataFrame(rows).sort_values("swing", ascending=False).reset_index(drop=True)
    return out, base_top
