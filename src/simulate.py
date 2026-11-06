"""Monte Carlo disruption simulation and mitigation ranking.

Monthly time step, vectorised across simulations with NumPy.

Two kinds of disruption
-----------------------
1. Part-level (idiosyncratic) outages - a fire, a quality escape, a supplier
   going under. Independent across parts.
     * starts with probability p_month (if not already disrupted)
     * length ~ Geometric with mean `mean_duration` months
     * severity ~ Uniform(min_severity, 1) of the primary's output lost
     * qualified alternates can cover `coverage` of demand

2. Country escalation shocks (CORRELATED) - e.g. a Chinese export ban. One
   event hits, at the same time:
     * every part whose supplier is in that country (alternates CAN help), and
     * every part whose key material comes from that country, in proportion
       to the country's share of world supply. Alternates CANNOT help here,
       because a second supplier still needs the same material. Only buffer
       inventory or a qualified non-country material source protects.

Disruptions propagate UP the tree: a tier-1 part is short if it, or ANY of its
sub-tier parts, is short (bottleneck = minimum coverage on the chain).

For each direct-buy part we track inventory:
  arrivals   = planned requirement * effective coverage (+ supplier catch-up)
  slips      = with prob slip_p, this month's shipment arrives next month
  catch-up   = missed quantity is back-ordered; supplier can surge by
               `surge` x normal monthly volume once the chain is healthy
Production each month = min(plan + backlog, what inventory allows).

Common random numbers: all random draws are generated once up front, so every
scenario sees exactly the same "bad luck" as the baseline. Differences in
shortfall are then due to the scenario, not to sampling noise.

Scenarios
---------
A scenario is a list of action specs (tuples):
  ("coverage", part_id, new_coverage)       qualify more sources for a part
  ("inventory", part_id, extra_units)       hold extra stock of a direct-buy part
  ("material", part_id, country)            qualify a material source outside `country`
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .bom import children_map

Spec = tuple  # (kind, part_id, value)


@dataclass
class SimConfig:
    n_sims: int = 2000
    seed: int = 7
    surge: float = 0.25                # supplier catch-up capacity (x normal monthly volume)
    min_severity: float = 0.3          # part outages remove 30-100% of the primary's output
    # Country escalation shocks (correlated). See docs/SOURCES.md for the calibration.
    # Russia is a country of concern but has negligible exposure in this bill of materials
    escalation_p_month: dict = field(default_factory=lambda: {"CHN": 0.02})
    escalation_mean_months: float = 4.0
    escalation_min_severity: float = 0.3
    correlated: bool = True            # turn off to reproduce the independent-outage model
    # Mitigation costs (assumptions)
    dual_source_fixed_cost: float = 50_000     # qualification, first article, audit
    dual_source_price_premium: float = 0.03    # second source usually costs a bit more
    material_source_fixed_cost: float = 75_000  # qualify a non-country material chain with the supplier
    material_source_price_premium: float = 0.10  # non-Chinese material typically costs more
    carrying_rate: float = 0.25        # annual inventory holding cost (% of value)
    buffer_weeks: float = 6.0          # extra inventory for the "buffer" mitigation
    # Profit per system not delivered within the plan (0 = don't value in dollars). Systems short at the
    # end of the horizon are LATE, not necessarily lost, so this is "profit at risk", an upper bound.
    margin_per_unit: float = 0.0


def _descendants(kids: dict[str, list[str]], pid: str) -> list[str]:
    out, stack = [], list(kids.get(pid, []))
    while stack:
        c = stack.pop()
        out.append(c)
        stack.extend(kids.get(c, []))
    return out


def _geometric(u: np.ndarray, mean: np.ndarray | float) -> np.ndarray:
    """Geometric(q=1/mean) on {1,2,...} via inverse CDF: D = ceil(ln U / ln(1-q))."""
    q = 1.0 / np.asarray(mean, dtype=float)
    with np.errstate(divide="ignore"):
        d = np.where(q >= 1, 1, np.ceil(np.log(u) / np.log(np.clip(1 - q, 1e-12, None))))
    return np.maximum(d, 1).astype(int)


class Simulator:
    def __init__(self, parts: pd.DataFrame, params: pd.DataFrame, plan: pd.Series,
                 initial_inventory: pd.Series, cfg: SimConfig | None = None,
                 lots: pd.Series | None = None):
        self.cfg = cfg or SimConfig()
        self.parts = parts.set_index("part_id")
        self.params = params.set_index("part_id").loc[self.parts.index]
        self.plan = plan.to_numpy().astype(float)
        self.ids = list(self.parts.index)
        self.idx = {p: i for i, p in enumerate(self.ids)}
        self.direct = [p for p in self.ids if self.parts.loc[p, "direct_buy"]]
        self.didx = {p: j for j, p in enumerate(self.direct)}
        kids = children_map(parts)
        # chain[j] = indices whose disruption hits direct-buy j (itself + all sub-tier parts)
        self.chain = {j: [self.idx[j]] + [self.idx[d] for d in _descendants(kids, j) if d in self.idx]
                      for j in self.direct}
        self.init_inv = initial_inventory.reindex(self.direct).fillna(0).to_numpy()
        # Optional lot size (units) per direct-buy part; deliveries are rounded up to whole lots
        self.lots = None if lots is None else lots.reindex(self.direct).fillna(1).clip(lower=1).to_numpy()
        self.countries = [c for c in self.cfg.escalation_p_month if f"matshare_{c}" in self.params.columns]

        S, I, T, C = self.cfg.n_sims, len(self.ids), len(self.plan), len(self.countries)
        rng = np.random.default_rng(self.cfg.seed)
        self.U_start = rng.random((S, I, T))
        self.U_dur = rng.random((S, I, T))
        self.U_sev = rng.random((S, I, T))
        self.U_slip = rng.random((S, len(self.direct), T))
        self.U_esc_start = rng.random((S, max(C, 1), T))
        self.U_esc_dur = rng.random((S, max(C, 1), T))
        self.U_esc_sev = rng.random((S, max(C, 1), T))
        self._esc_cache = None

    # ---- disruption processes ----------------------------------------------
    def _part_outages(self) -> np.ndarray:
        """Severity of part-level outage in effect (0 if none): shape (S, I, T)."""
        S, I, T = self.U_start.shape
        p = self.params["p_month"].to_numpy()
        mean = self.params["mean_duration"].to_numpy()
        lo = self.cfg.min_severity
        remaining = np.zeros((S, I), dtype=int)
        sev_now = np.zeros((S, I))
        out = np.zeros((S, I, T))
        for t in range(T):
            starts = (remaining == 0) & (self.U_start[:, :, t] < p)
            remaining = np.where(starts, _geometric(self.U_dur[:, :, t], mean), remaining)
            sev_now = np.where(starts, lo + (1 - lo) * self.U_sev[:, :, t], sev_now)
            out[:, :, t] = np.where(remaining > 0, sev_now, 0.0)
            remaining = np.maximum(remaining - 1, 0)
        return out

    def _escalations(self) -> np.ndarray:
        """Severity of each country's escalation shock in effect: shape (S, C, T). Cached."""
        if self._esc_cache is not None:
            return self._esc_cache
        S, T, C = self.cfg.n_sims, len(self.plan), len(self.countries)
        out = np.zeros((S, max(C, 1), T))
        if self.cfg.correlated and C:
            p = np.array([self.cfg.escalation_p_month[c] for c in self.countries])
            lo = self.cfg.escalation_min_severity
            remaining = np.zeros((S, C), dtype=int)
            sev_now = np.zeros((S, C))
            for t in range(T):
                starts = (remaining == 0) & (self.U_esc_start[:, :C, t] < p)
                remaining = np.where(starts, _geometric(self.U_esc_dur[:, :C, t], self.cfg.escalation_mean_months),
                                     remaining)
                sev_now = np.where(starts, lo + (1 - lo) * self.U_esc_sev[:, :C, t], sev_now)
                out[:, :C, t] = np.where(remaining > 0, sev_now, 0.0)
                remaining = np.maximum(remaining - 1, 0)
        self._esc_cache = out
        return out

    def _coverage(self, coverage: np.ndarray, matshare: np.ndarray, direct: np.ndarray) -> np.ndarray:
        """Supply coverage in [0,1] for each sim/part/month.

        coverage : (I,)   share alternates can cover
        matshare : (I, C) share of the part's key material from each country
        direct   : (I, C) 1 if the part's supplier is in that country
        """
        sev = self._part_outages()                                   # (S, I, T)
        cov = np.where(sev > 0, np.maximum(coverage[None, :, None], 1 - sev), 1.0)
        if self.cfg.correlated and self.countries:
            esc = self._escalations()[:, :len(self.countries), :]    # (S, C, T)
            # Direct loss: primary supplier in the shocked country; alternates can help
            direct_loss = np.einsum("ic,sct->sit", direct, esc)
            cov = np.minimum(cov, np.where(direct_loss > 0, np.maximum(coverage[None, :, None], 1 - direct_loss), 1.0))
            # Material loss: country's share of world material supply x severity; alternates can't help
            mat_loss = np.clip(np.einsum("ic,sct->sit", matshare, esc), 0, 1)
            cov = np.minimum(cov, 1 - mat_loss)
        return cov

    # ---- main loop ----------------------------------------------------------
    def run(self, scenario: list[Spec] | None = None) -> dict:
        coverage = self.params["coverage"].to_numpy().copy()
        matshare = np.stack([self.params[f"matshare_{c}"].to_numpy() for c in self.countries], axis=1) \
            if self.countries else np.zeros((len(self.ids), 0))
        direct = np.stack([self.params[f"direct_{c}"].to_numpy() for c in self.countries], axis=1) \
            if self.countries else np.zeros((len(self.ids), 0))
        extra = np.zeros(len(self.direct))
        for kind, pid, val in scenario or []:
            i = self.idx[pid]
            if kind == "coverage":
                coverage[i] = max(coverage[i], val)
            elif kind == "inventory":
                extra[self.didx[pid]] += val
            elif kind == "material":
                matshare[i, self.countries.index(val)] = 0.0
            else:
                raise ValueError(f"Unknown action {kind}")
        cov = self._coverage(coverage, matshare, direct)

        S, T, J = self.cfg.n_sims, len(self.plan), len(self.direct)
        ext = self.parts.loc[self.direct, "extended_qty"].to_numpy()
        slip_p = self.params.loc[self.direct, "slip_p"].to_numpy()
        inv = np.tile(self.init_inv + extra, (S, 1)).astype(float)

        backorder = np.zeros((S, J))       # supplier owes us this
        in_transit = np.zeros((S, J))      # slipped shipments arriving next month
        backlog = np.zeros(S)              # systems we owe the customer
        built = np.zeros((S, T))
        binding = np.zeros((S, T), dtype=int) - 1  # which part limited production
        lot_carry = np.zeros(J)            # units received above need because of lot rounding

        for t in range(T):
            req = ext * self.plan[t]
            if self.lots is not None:      # order in whole lots; the excess carries forward as stock
                need = np.maximum(req - lot_carry, 0)
                ordered = np.ceil(need / self.lots) * self.lots
                lot_carry = lot_carry + ordered - req
                req = ordered
            eff = np.stack([cov[:, self.chain[j], t].min(axis=1) for j in self.direct], axis=1)
            ship = req * eff
            backorder += req - ship
            healthy = eff >= 1.0           # catch-up only when the whole chain is healthy
            catch = np.where(healthy, np.minimum(backorder, self.cfg.surge * ext * self.plan[t]), 0.0)
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
            binding[:, t] = np.where(b < target, feasible_by_part.argmin(axis=1), -1)
            inv -= b[:, None] * ext
            backlog = target - b
            built[:, t] = b

        return {"built": built, "shortfall": backlog, "binding": binding}

    # ---- summaries ----------------------------------------------------------
    def summarize(self, res: dict) -> dict:
        sf = res["shortfall"]
        planned = self.plan.sum()
        out = {
            "planned_units": planned,
            "expected_shortfall": float(sf.mean()),
            "p_any_shortfall": float((sf > 0).mean()),
            "shortfall_p95": float(np.percentile(sf, 95)),
            "fill_rate": float(1 - sf.mean() / planned),
        }
        if self.cfg.margin_per_unit:
            out["expected_profit_at_risk_usd"] = out["expected_shortfall"] * self.cfg.margin_per_unit
            out["profit_at_risk_p95_usd"] = out["shortfall_p95"] * self.cfg.margin_per_unit
        return out

    def binding_attribution(self, res: dict) -> pd.DataFrame:
        """How often each direct-buy part was THE constraint in a short month."""
        b = res["binding"]
        counts = np.bincount(b[b >= 0].ravel(), minlength=len(self.direct))
        share = counts / max(counts.sum(), 1)
        return pd.DataFrame({"part_id": self.direct, "constraint_share": share}) \
            .sort_values("constraint_share", ascending=False).reset_index(drop=True)

    def monthly_bands(self, res: dict) -> pd.DataFrame:
        built = res["built"]
        cum = built.cumsum(axis=1)
        q = lambda a, p: np.percentile(a, p, axis=0)  # noqa: E731
        return pd.DataFrame({
            "month": np.arange(1, len(self.plan) + 1),
            "plan": self.plan,
            "p05": q(built, 5), "p50": q(built, 50), "mean": built.mean(axis=0), "p95": q(built, 95),
            # cumulative systems delivered vs. cumulative plan
            "cum_plan": self.plan.cumsum(),
            "cum_p05": q(cum, 5), "cum_p25": q(cum, 25), "cum_p50": q(cum, 50), "cum_p75": q(cum, 75),
            "cum_p95": q(cum, 95), "cum_mean": cum.mean(axis=0),
        })

    # ---- mitigations --------------------------------------------------------
    def candidate_actions(self, scored: pd.DataFrame, top_k: int = 10) -> list[dict]:
        """Generate candidate actions with costs. Each candidate carries a list of specs.

        Single-part actions for the top-k riskiest parts, plus one assembly-level
        "remove <country> exposure" bundle per direct-buy assembly. The bundles matter
        because a correlated shock hits every exposed part in an assembly at once:
        fixing one of them leaves the assembly just as short.
        """
        cfg = self.cfg
        out, buffered = [], set()
        for pid in scored.head(top_k)["part_id"]:
            # 1) Qualify an additional supplier for the part (works at any tier)
            a = self._dual_source(pid)
            if a:
                out.append(a)
            # 2) Qualify a material source outside a country -- only meaningful when the
            #    supplier itself is NOT in that country (otherwise the direct loss dominates)
            for c in self.countries:
                if self.params.loc[pid, f"matshare_{c}"] >= 0.25 and not self.params.loc[pid, f"direct_{c}"]:
                    out.append(self._material(pid, c))
            # 3) Strategic buffer on the direct-buy part this rolls up into
            target = pid if pid in self.didx else self._direct_ancestor(pid)
            if target is not None and target not in buffered:
                buffered.add(target)
                out.append(self._buffer(target, pid))
        # 4) Assembly-level bundles: remove all exposure to a country inside one direct-buy chain
        for c in self.countries:
            for j in self.direct:
                members = [self.ids[i] for i in self.chain[j]]
                acts = []
                for pid in members:
                    if self.params.loc[pid, f"direct_{c}"]:
                        a = self._dual_source(pid, label_country=c)
                        if a:
                            acts.append(a)
                    if self.params.loc[pid, f"matshare_{c}"] >= 0.25:
                        acts.append(self._material(pid, c))
                if len(acts) >= 2:
                    out.append({"risk_part": j, "action": f"Remove {c} exposure from {j} chain ({len(acts)} actions)",
                                "cost_usd": sum(a["cost_usd"] for a in acts), "inventory_cash_tied_up_usd": 0.0,
                                "_specs": [sp for a in acts for sp in a["_specs"]]})
        return out

    def _spend(self, pid: str) -> float:
        part = self.parts.loc[pid]
        return part["extended_qty"] * self.plan.sum() * part["unit_cost_usd"]

    def _dual_source(self, pid: str, label_country: str | None = None) -> dict | None:
        n_alt = self.parts.loc[pid, "alt_suppliers_qualified"] + 1
        new_cov = 0.5 if n_alt == 1 else 0.8
        if new_cov <= self.params.loc[pid, "coverage"]:
            return None
        label = f"Qualify non-{label_country} supplier" if label_country else "Qualify additional supplier"
        return {"risk_part": pid, "action": label,
                "cost_usd": self.cfg.dual_source_fixed_cost + self.cfg.dual_source_price_premium * self._spend(pid),
                "inventory_cash_tied_up_usd": 0.0, "_specs": [("coverage", pid, new_cov)]}

    def _material(self, pid: str, c: str) -> dict:
        return {"risk_part": pid, "action": f"Qualify non-{c} material source",
                "cost_usd": self.cfg.material_source_fixed_cost + self.cfg.material_source_price_premium * self._spend(pid),
                "inventory_cash_tied_up_usd": 0.0, "_specs": [("material", pid, c)]}

    def _buffer(self, target: str, risk_part: str) -> dict:
        tp = self.parts.loc[target]
        extra_units = float(np.ceil(tp["extended_qty"] * self.plan.mean() * self.cfg.buffer_weeks / (52 / 12)))
        return {"risk_part": risk_part, "action": f"+{self.cfg.buffer_weeks:g} wks buffer on {target}",
                "cost_usd": extra_units * tp["unit_cost_usd"] * self.cfg.carrying_rate * len(self.plan) / 12,
                "inventory_cash_tied_up_usd": extra_units * tp["unit_cost_usd"],
                "_specs": [("inventory", target, extra_units)]}

    def evaluate_mitigations(self, scored: pd.DataFrame, top_k: int = 10) -> pd.DataFrame:
        base_sf = self.run()["shortfall"]
        shocked = self.shock_mask()
        rows = []
        for cand in self.candidate_actions(scored, top_k):
            sf = self.run(cand["_specs"])["shortfall"]
            row = {**cand, **self._paired(base_sf, sf)}
            # Tail view: benefit in the futures where each country escalates
            for c, mask in shocked.items():
                row[f"avoided_if_{c}_shock"] = float((base_sf[mask] - sf[mask]).mean()) if mask.any() else 0.0
            rows.append(row)
        out = pd.DataFrame(rows)
        if out.empty:
            return out
        out["units_avoided_per_100k"] = out["shortfall_avoided"] / (out["cost_usd"] / 100_000)
        if self.cfg.margin_per_unit:
            out["profit_protected_usd"] = out["shortfall_avoided"] * self.cfg.margin_per_unit
            out["net_benefit_usd"] = out["profit_protected_usd"] - out["cost_usd"]
            out["return_on_cost"] = out["profit_protected_usd"] / out["cost_usd"]
        cols = ["risk_part", "action", "baseline_E_shortfall", "new_E_shortfall", "shortfall_avoided", "ci95_low",
                "ci95_high", "cost_usd", "units_avoided_per_100k"]
        rest = [c for c in out.columns if c not in cols]
        return out[cols + rest].sort_values("units_avoided_per_100k", ascending=False).reset_index(drop=True)

    def shock_mask(self) -> dict[str, np.ndarray]:
        """For each country: boolean (S,) - did an escalation shock occur in that simulated future?"""
        esc = self._escalations()
        return {c: esc[:, k, :].max(axis=1) > 0 for k, c in enumerate(self.countries)}

    def conditional_summary(self, res: dict) -> pd.DataFrame:
        """Expected shortfall with vs. without each country's escalation."""
        sf, rows = res["shortfall"], []
        for c, mask in self.shock_mask().items():
            rows.append({"country": c, "p_shock_in_horizon": mask.mean(),
                         "E_shortfall_if_shock": sf[mask].mean() if mask.any() else np.nan,
                         "E_shortfall_if_no_shock": sf[~mask].mean() if (~mask).any() else np.nan})
        return pd.DataFrame(rows)

    def _direct_ancestor(self, pid: str) -> str | None:
        parent = dict(zip(self.parts.index, self.parts["parent_id"]))
        cur = parent.get(pid, "")
        while cur and cur not in self.didx:
            cur = parent.get(cur, "")
        return cur or None

    @staticmethod
    def _paired(base_sf: np.ndarray, sf: np.ndarray) -> dict:
        # Paired difference (same random draws) -> much tighter standard error than two independent runs
        diff = base_sf - sf
        se = diff.std(ddof=1) / np.sqrt(len(diff))
        return {"baseline_E_shortfall": base_sf.mean(), "new_E_shortfall": sf.mean(),
                "shortfall_avoided": diff.mean(), "ci95_low": diff.mean() - 1.96 * se,
                "ci95_high": diff.mean() + 1.96 * se}

    def evaluate_portfolio(self, mitigations: pd.DataFrame, n: int) -> dict:
        """Apply the top-n ranked actions together. Benefits are NOT additive
        (fixing one bottleneck exposes the next), so we re-simulate the bundle."""
        top = mitigations.head(n)
        res = self.summarize(self.run([sp for specs in top["_specs"] for sp in specs]))
        res["cost_usd"] = float(top["cost_usd"].sum())
        res["actions"] = top["action"].tolist()
        return res
