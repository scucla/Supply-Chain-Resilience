"""Monte Carlo disruption simulation and mitigation ranking.

Monthly time step, vectorised across simulations with NumPy.

For every purchased part (all tiers):
  * a disruption starts with probability p_month (if not already disrupted)
  * its length is Geometric with mean `mean_duration` months
  * while disrupted, only `coverage` of normal supply arrives (alternates)

Disruptions propagate UP the tree: a tier-1 part is short if it, or ANY of its
sub-tier parts, is disrupted (bottleneck = the minimum coverage on the chain).

For each direct-buy part we track inventory:
  arrivals   = planned requirement * effective coverage (+ supplier catch-up)
  slips      = with prob slip_p, this month's shipment arrives next month
  catch-up   = missed quantity is back-ordered; supplier can surge by
               `surge` x normal monthly volume once the disruption clears
Production each month = min(plan + backlog, what inventory allows).

Common random numbers: all random draws are generated once up front, so a
mitigation scenario sees exactly the same "bad luck" as the baseline. The
difference in shortfall is then due to the mitigation, not to noise.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .bom import children_map


@dataclass
class SimConfig:
    n_sims: int = 2000
    seed: int = 7
    surge: float = 0.25               # supplier catch-up capacity (x normal monthly volume)
    min_severity: float = 0.3          # outages remove 30-100% of the primary's output
    dual_source_fixed_cost: float = 50_000   # qualification, first article, audit
    dual_source_price_premium: float = 0.03  # second source usually costs a bit more
    carrying_rate: float = 0.25        # annual inventory holding cost (% of value)
    buffer_weeks: float = 6.0          # extra inventory for the "buffer" mitigation


def _descendants(kids: dict[str, list[str]], pid: str) -> list[str]:
    out, stack = [], list(kids.get(pid, []))
    while stack:
        c = stack.pop()
        out.append(c)
        stack.extend(kids.get(c, []))
    return out


class Simulator:
    def __init__(self, parts: pd.DataFrame, params: pd.DataFrame, plan: pd.Series,
                 initial_inventory: pd.Series, cfg: SimConfig | None = None):
        self.cfg = cfg or SimConfig()
        self.parts = parts.set_index("part_id")
        self.params = params.set_index("part_id").loc[self.parts.index]
        self.plan = plan.to_numpy().astype(float)
        self.ids = list(self.parts.index)
        self.idx = {p: i for i, p in enumerate(self.ids)}
        self.direct = [p for p in self.ids if self.parts.loc[p, "direct_buy"]]
        kids = children_map(parts)
        # chain[j] = indices whose disruption hits direct-buy j (itself + all sub-tier parts)
        self.chain = {j: [self.idx[j]] + [self.idx[d] for d in _descendants(kids, j) if d in self.idx]
                      for j in self.direct}
        self.init_inv = initial_inventory.reindex(self.direct).fillna(0).to_numpy()

        S, I, T = self.cfg.n_sims, len(self.ids), len(self.plan)
        rng = np.random.default_rng(self.cfg.seed)
        self.U_start = rng.random((S, I, T))
        self.U_dur = rng.random((S, I, T))
        self.U_slip = rng.random((S, len(self.direct), T))
        # Severity: share of the primary supplier's output lost, ~ Uniform(min_severity, 1)
        self.U_sev = rng.random((S, I, T))

    # ---- core ---------------------------------------------------------------
    def _disruption_coverage(self, coverage: np.ndarray) -> np.ndarray:
        """Return supply coverage in [0,1] for each sim/part/month.

        During an outage the primary still ships (1 - severity) of normal volume and
        qualified alternates can cover `coverage`; we get whichever is larger.
        """
        S, I, T = self.U_start.shape
        p = self.params["p_month"].to_numpy()
        q = 1.0 / self.params["mean_duration"].to_numpy()       # geometric success prob
        remaining = np.zeros((S, I), dtype=int)
        severity = np.zeros((S, I))
        cov = np.ones((S, I, T))
        lo = self.cfg.min_severity
        for t in range(T):
            active = remaining > 0
            starts = (~active) & (self.U_start[:, :, t] < p)
            # Geometric(q) on {1,2,...} via inverse CDF: D = ceil(ln U / ln(1-q))
            with np.errstate(divide="ignore"):
                dur = np.where(q >= 1, 1, np.ceil(np.log(self.U_dur[:, :, t]) / np.log(np.clip(1 - q, 1e-12, None))))
            dur = np.maximum(dur, 1).astype(int)
            remaining = np.where(starts, dur, remaining)
            severity = np.where(starts, lo + (1 - lo) * self.U_sev[:, :, t], severity)
            disrupted = remaining > 0
            cov[:, :, t] = np.where(disrupted, np.maximum(coverage, 1 - severity), 1.0)
            remaining = np.maximum(remaining - 1, 0)
        return cov

    def run(self, coverage_override: dict[str, float] | None = None,
            extra_inventory: dict[str, float] | None = None) -> dict:
        coverage = self.params["coverage"].copy()
        for pid, c in (coverage_override or {}).items():
            coverage[pid] = c
        cov = self._disruption_coverage(coverage.to_numpy())

        S, T, J = self.cfg.n_sims, len(self.plan), len(self.direct)
        ext = self.parts.loc[self.direct, "extended_qty"].to_numpy()
        slip_p = self.params.loc[self.direct, "slip_p"].to_numpy()
        inv = np.tile(self.init_inv, (S, 1)).astype(float)
        for pid, extra in (extra_inventory or {}).items():
            inv[:, self.direct.index(pid)] += extra

        backorder = np.zeros((S, J))       # supplier owes us this
        in_transit = np.zeros((S, J))      # slipped shipments arriving next month
        backlog = np.zeros(S)              # systems we owe the customer
        built = np.zeros((S, T))
        binding = np.zeros((S, T), dtype=int) - 1  # which part limited production

        for t in range(T):
            req = ext * self.plan[t]
            eff = np.stack([cov[:, self.chain[j], t].min(axis=1) for j in self.direct], axis=1)
            ship = req * eff
            backorder += req - ship
            # catch-up only when the chain is healthy
            healthy = eff >= 1.0
            catch = np.where(healthy, np.minimum(backorder, self.cfg.surge * req), 0.0)
            backorder -= catch
            ship += catch
            slipped = self.U_slip[:, :, t] < slip_p
            arriving = np.where(slipped, 0.0, ship) + in_transit
            in_transit = np.where(slipped, ship, 0.0)
            inv += arriving

            target = self.plan[t] + backlog
            feasible_by_part = np.floor(inv / ext)
            feasible = feasible_by_part.min(axis=1)
            b = np.minimum(target, feasible)
            short = b < target
            binding[:, t] = np.where(short, feasible_by_part.argmin(axis=1), -1)
            inv -= b[:, None] * ext
            backlog = target - b
            built[:, t] = b

        shortfall = backlog  # unbuilt systems at end of horizon
        return {"built": built, "shortfall": shortfall, "binding": binding}

    # ---- summaries ----------------------------------------------------------
    def summarize(self, res: dict) -> dict:
        sf = res["shortfall"]
        planned = self.plan.sum()
        return {
            "planned_units": planned,
            "expected_shortfall": float(sf.mean()),
            "p_any_shortfall": float((sf > 0).mean()),
            "shortfall_p95": float(np.percentile(sf, 95)),
            "fill_rate": float(1 - sf.mean() / planned),
        }

    def binding_attribution(self, res: dict) -> pd.DataFrame:
        """How often each direct-buy part was THE constraint in a short month."""
        b = res["binding"]
        counts = np.bincount(b[b >= 0].ravel(), minlength=len(self.direct))
        share = counts / max(counts.sum(), 1)
        return pd.DataFrame({"part_id": self.direct, "constraint_share": share}) \
            .sort_values("constraint_share", ascending=False).reset_index(drop=True)

    def monthly_bands(self, res: dict) -> pd.DataFrame:
        built = res["built"]
        return pd.DataFrame({
            "month": np.arange(1, len(self.plan) + 1),
            "plan": self.plan,
            "p05": np.percentile(built, 5, axis=0),
            "p50": np.percentile(built, 50, axis=0),
            "mean": built.mean(axis=0),
            "p95": np.percentile(built, 95, axis=0),
        })

    # ---- mitigations --------------------------------------------------------
    def evaluate_mitigations(self, scored: pd.DataFrame, top_k: int = 10) -> pd.DataFrame:
        cfg = self.cfg
        base_sf = self.run()["shortfall"]
        horizon_units = self.plan.sum()
        months = len(self.plan)
        rows = []
        candidates = scored.head(top_k)["part_id"].tolist()
        buffered: set[str] = set()

        for pid in candidates:
            part = self.parts.loc[pid]
            spend = part["extended_qty"] * horizon_units * part["unit_cost_usd"]
            # 1) Qualify an additional source (works at any tier)
            n_alt = part["alt_suppliers_qualified"] + 1
            new_cov = 0.5 if n_alt == 1 else 0.8
            if new_cov > self.params.loc[pid, "coverage"]:
                sf = self.run(coverage_override={pid: new_cov})["shortfall"]
                cost = cfg.dual_source_fixed_cost + cfg.dual_source_price_premium * spend
                rows.append(self._row(pid, "Qualify additional source", base_sf, sf, cost,
                                      spec=("coverage", pid, new_cov)))

            # 2) Strategic buffer: extra weeks of inventory on the direct-buy part
            #    that this part rolls up into (buffering the tier-1 protects against tier-2 outages)
            target = pid if pid in self.direct else self._direct_ancestor(pid)
            if target is not None and target not in buffered:
                buffered.add(target)
                tp = self.parts.loc[target]
                monthly = tp["extended_qty"] * self.plan.mean()
                extra_units = np.ceil(monthly * cfg.buffer_weeks / (52 / 12))
                sf = self.run(extra_inventory={target: extra_units})["shortfall"]
                cost = extra_units * tp["unit_cost_usd"] * cfg.carrying_rate * months / 12
                label = f"+{cfg.buffer_weeks:g} wks buffer on {target}"
                rows.append(self._row(pid, label, base_sf, sf, cost, inventory_cash=extra_units * tp["unit_cost_usd"],
                                      spec=("inventory", target, extra_units)))

        out = pd.DataFrame(rows)
        if out.empty:
            return out
        out["units_avoided_per_100k"] = out["shortfall_avoided"] / (out["cost_usd"] / 100_000)
        return out.sort_values("units_avoided_per_100k", ascending=False).reset_index(drop=True)

    def _direct_ancestor(self, pid: str) -> str | None:
        parent = dict(zip(self.parts.index, self.parts["parent_id"]))
        cur = parent.get(pid, "")
        while cur and cur not in self.direct:
            cur = parent.get(cur, "")
        return cur or None

    @staticmethod
    def _row(pid, action, base_sf, sf, cost, inventory_cash=0.0, spec=None):
        # Paired difference (same random draws) -> much tighter standard error than two independent runs
        diff = base_sf - sf
        se = diff.std(ddof=1) / np.sqrt(len(diff))
        return {"risk_part": pid, "action": action, "baseline_E_shortfall": base_sf.mean(),
                "new_E_shortfall": sf.mean(), "shortfall_avoided": diff.mean(),
                "ci95_low": diff.mean() - 1.96 * se, "ci95_high": diff.mean() + 1.96 * se,
                "cost_usd": cost, "inventory_cash_tied_up_usd": inventory_cash, "_spec": spec}

    def evaluate_portfolio(self, mitigations: pd.DataFrame, n: int) -> dict:
        """Apply the top-n ranked actions together. Benefits are NOT additive
        (fixing one bottleneck exposes the next), so we re-simulate the bundle."""
        cov, inv = {}, {}
        for spec in mitigations.head(n)["_spec"]:
            kind, pid, val = spec
            if kind == "coverage":
                cov[pid] = max(cov.get(pid, 0.0), val)
            else:
                inv[pid] = inv.get(pid, 0.0) + val
        res = self.summarize(self.run(coverage_override=cov, extra_inventory=inv))
        res["cost_usd"] = float(mitigations.head(n)["cost_usd"].sum())
        res["actions"] = mitigations.head(n)["action"].tolist()
        return res
