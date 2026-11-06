"""Choose which mitigations to fund under a budget, and trace the efficient frontier.

The problem is a knapsack: pick actions x_i in {0, 1} to minimise risk subject to
sum(cost_i * x_i) <= budget. Two complications rule out the textbook solution:

1. Benefits are not additive. Fixing one bottleneck exposes the next one, and
   two fixes on the same assembly overlap. The value of a set is only known by
   simulating the set.
2. Each evaluation is a full Monte Carlo run.

So we use **greedy selection with re-simulation**: at every step, simulate each
remaining candidate added to the current set and pick the one with the largest
risk reduction per dollar that still fits the budget. Common random numbers keep
these comparisons low-noise. Greedy is not guaranteed optimal for knapsacks, but
re-simulating at each step captures the interactions that a one-shot ranking
misses, and the comparison against that naive ranking is reported.

Risk objective (pick one):
  "mean"  expected shortfall (risk-neutral)
  "cvar"  conditional value at risk: average shortfall in the worst 10% of
          futures (risk-averse; weights the correlated-shock tail)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .simulate import Simulator


def risk_metric(shortfall: np.ndarray, objective: str = "mean", alpha: float = 0.90) -> float:
    if objective == "mean":
        return float(shortfall.mean())
    if objective == "cvar":
        cutoff = np.quantile(shortfall, alpha)
        return float(shortfall[shortfall >= cutoff].mean())
    raise ValueError(objective)


def greedy(sim: Simulator, candidates: list[dict], budget: float = np.inf, objective: str = "mean",
           max_steps: int = 15, min_gain: float = 1e-9) -> pd.DataFrame:
    """Greedy re-simulated selection. Returns one row per step (the frontier)."""
    chosen: list[dict] = []
    specs: list = []
    spent = 0.0
    sf = sim.run(specs)["shortfall"]
    current = risk_metric(sf, objective)
    rows = [_frontier_row(sim, 0, "(baseline: no actions)", "", 0.0, 0.0, sf, objective)]
    remaining = list(candidates)

    for step in range(1, max_steps + 1):
        best, best_ratio, best_sf, best_val = None, 0.0, None, None
        for cand in remaining:
            if spent + cand["cost_usd"] > budget:
                continue
            trial_sf = sim.run(specs + cand["_specs"])["shortfall"]
            val = risk_metric(trial_sf, objective)
            gain = current - val
            ratio = gain / max(cand["cost_usd"], 1.0)
            if gain > min_gain and ratio > best_ratio:
                best, best_ratio, best_sf, best_val = cand, ratio, trial_sf, val
        if best is None:
            break
        chosen.append(best)
        specs += best["_specs"]
        spent += best["cost_usd"]
        remaining = [c for c in remaining if c is not best]
        rows.append(_frontier_row(sim, step, best["action"], best["risk_part"], best["cost_usd"], spent, best_sf,
                                  objective, gain=current - best_val))
        current = best_val
    return pd.DataFrame(rows)


def naive_prefix(sim: Simulator, ranked: pd.DataFrame, objective: str = "mean", max_steps: int = 15) -> pd.DataFrame:
    """Baseline for comparison: fund actions in their stand-alone ranking order."""
    specs, spent, rows = [], 0.0, []
    sf = sim.run(specs)["shortfall"]
    rows.append(_frontier_row(sim, 0, "(baseline: no actions)", "", 0.0, 0.0, sf, objective))
    for step, (_, a) in enumerate(ranked.head(max_steps).iterrows(), start=1):
        specs += a["_specs"]
        spent += a["cost_usd"]
        sf = sim.run(specs)["shortfall"]
        rows.append(_frontier_row(sim, step, a["action"], a["risk_part"], a["cost_usd"], spent, sf, objective))
    return pd.DataFrame(rows)


def best_for_budgets(sim: Simulator, candidates: list[dict], budgets: list[float],
                     objective: str = "mean") -> pd.DataFrame:
    """Run the budget-constrained greedy for several budgets; one summary row per budget."""
    rows = []
    for b in budgets:
        path = greedy(sim, candidates, budget=b, objective=objective)
        last = path.iloc[-1]
        rows.append({"budget_usd": b, "spent_usd": last["cumulative_cost_usd"], "n_actions": int(last["step"]),
                     "fill_rate": last["fill_rate"], "expected_shortfall": last["expected_shortfall"],
                     "cvar90_shortfall": last["cvar90_shortfall"],
                     "actions": " | ".join(path["action"].iloc[1:])})
    return pd.DataFrame(rows)


def _frontier_row(sim, step, action, part, cost, cum_cost, sf, objective, gain=0.0) -> dict:
    planned = sim.plan.sum()
    row = {"step": step, "action": action, "risk_part": part, "cost_usd": cost, "cumulative_cost_usd": cum_cost,
           "expected_shortfall": float(sf.mean()), "cvar90_shortfall": risk_metric(sf, "cvar"),
           "fill_rate": float(1 - sf.mean() / planned), f"marginal_{objective}_reduction": gain}
    if sim.cfg.margin_per_unit:
        row["profit_at_risk_usd"] = float(sf.mean()) * sim.cfg.margin_per_unit
    return row
