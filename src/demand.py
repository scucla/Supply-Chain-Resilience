"""Time-phased demand planning (a lightweight MRP).

1. Build a production plan (units/month) from a ramp.
2. Gross requirements: plan[t] * extended_qty for every purchased part,
   including tier-2/3 parts we don't buy directly (that's the forecast we
   would share with our tier-1 supplier so *they* can order in time).
3. Offset by lead time to get order-release dates.
4. Size safety stock for demand AND lead-time uncertainty.
"""
from __future__ import annotations

import math
from statistics import NormalDist

import numpy as np
import pandas as pd

WEEKS_PER_MONTH = 52 / 12  # 4.333


def production_plan(start_rate: int, end_rate: int, months: int, shape: str = "s-curve") -> pd.Series:
    """Monthly build plan. S-curve mimics a real production ramp (slow, fast, plateau)."""
    t = np.arange(months)
    if shape == "linear" or months == 1:
        frac = t / max(months - 1, 1)
    else:
        k = 8 / months  # steepness scaled to the horizon
        raw = 1 / (1 + np.exp(-k * (t - (months - 1) / 2)))
        frac = (raw - raw[0]) / (raw[-1] - raw[0])
    plan = np.round(start_rate + (end_rate - start_rate) * frac).astype(int)
    return pd.Series(plan, index=pd.RangeIndex(1, months + 1, name="month"), name="units")


def gross_requirements(parts: pd.DataFrame, plan: pd.Series) -> pd.DataFrame:
    """Rows = parts, columns = months, values = units required that month."""
    req = np.outer(parts["extended_qty"].to_numpy(), plan.to_numpy())
    return pd.DataFrame(req, index=parts["part_id"], columns=plan.index)


def lead_time_months(lead_time_wks: pd.Series) -> pd.Series:
    return np.ceil(lead_time_wks / WEEKS_PER_MONTH).astype(int)


def safety_stock(parts: pd.DataFrame, plan: pd.Series, service_level: float = 0.95,
                 demand_cv: float = 0.20) -> pd.DataFrame:
    """SS = z * sqrt(L * sigma_d^2 + d^2 * sigma_L^2)   (all in months).

    d       : mean monthly demand for the part
    sigma_d : std dev of monthly demand (forecast error) = demand_cv * d
    L       : mean lead time (months), sigma_L: lead-time std dev (months)
    z       : standard-normal quantile for the target cycle service level
    """
    z = NormalDist().inv_cdf(service_level)
    d = parts["extended_qty"].to_numpy() * plan.mean()
    sigma_d = demand_cv * d
    L = parts["lead_time_wks"].to_numpy() / WEEKS_PER_MONTH
    sigma_L = parts["lead_time_sd_wks"].to_numpy() / WEEKS_PER_MONTH
    ss = z * np.sqrt(L * sigma_d**2 + d**2 * sigma_L**2)
    out = pd.DataFrame({
        "part_id": parts["part_id"].to_numpy(),
        "avg_monthly_demand": d,
        "lead_time_months": L,
        "safety_stock_units": np.ceil(ss),
        "reorder_point_units": np.ceil(d * L + ss),
    })
    out["safety_stock_value_usd"] = out["safety_stock_units"] * parts["unit_cost_usd"].to_numpy()
    out["z"] = z
    return out


def order_schedule(parts: pd.DataFrame, plan: pd.Series, lots: pd.Series | None = None) -> pd.DataFrame:
    """Planned order releases: need in month t -> release in month t - LT.

    If `lots` (part_id -> lot size) is given, each month's net need is rounded up to
    whole lots and any excess carries into later months (so some months need no order).
    Release months <= 0 mean the order is already late relative to month 1 of
    the plan (the order-now list).
    """
    req = gross_requirements(parts, plan)
    lt = lead_time_months(parts["lead_time_wks"]).to_numpy()
    rows = []
    for i, pid in enumerate(req.index):
        lot = float(lots.get(pid, 1)) if lots is not None else 1.0
        carry = 0.0
        for month, qty in req.loc[pid].items():
            need = max(qty - carry, 0.0)
            order = math.ceil(need / lot) * lot if need > 0 else 0.0
            carry += order - qty
            if order > 0:
                rows.append({"part_id": pid, "need_month": month, "release_month": month - lt[i],
                             "qty": int(order)})
    sched = pd.DataFrame(rows)
    sched["status"] = np.where(sched["release_month"] <= 0, "ORDER NOW / LATE", "planned")
    return sched


def spend_by_part(parts: pd.DataFrame, plan: pd.Series) -> pd.Series:
    """Spend over the horizon. Only direct buys hit our P&L (tier-2 cost is inside the tier-1 price)."""
    spend = parts["extended_qty"] * plan.sum() * parts["unit_cost_usd"]
    spend = spend.where(parts["direct_buy"], 0.0)
    return pd.Series(spend.to_numpy(), index=parts["part_id"], name="horizon_spend_usd")


def lot_sizing(parts: pd.DataFrame, plan: pd.Series, order_cost: float = 400.0,
               carrying_rate: float = 0.25) -> pd.DataFrame:
    """Economic order quantity vs. minimum order quantity, per part.

    Economic order quantity (EOQ) balances the fixed cost of placing an order
    against the cost of holding stock:

        total cost(Q) = (D / Q) * S  +  (Q / 2) * H
        d/dQ = 0  ->   Q* = sqrt(2 * D * S / H)

    D : annual demand (units)  -- annualised from the plan
    S : cost per order ($)     -- purchase-order admin, receiving inspection, fixed freight
    H : holding cost per unit per year = unit cost * carrying rate

    The supplier's minimum order quantity (MOQ) is a floor, so the lot we use is
    max(EOQ, MOQ). We compare annual ordering + holding cost against ordering
    one order per month for that month's need.
    """
    D = parts["extended_qty"].to_numpy() * plan.sum() * 12 / len(plan)
    H = parts["unit_cost_usd"].to_numpy() * carrying_rate
    with np.errstate(divide="ignore", invalid="ignore"):
        eoq = np.sqrt(2 * D * order_cost / H)
    moq = parts.get("moq", pd.Series(0, index=parts.index)).fillna(0).to_numpy().astype(float)
    lot = np.ceil(np.maximum(eoq, moq))
    monthly = D / 12

    def annual_cost(q):
        q = np.maximum(q, 1)
        return D / q * order_cost + q / 2 * H

    out = pd.DataFrame({
        "part_id": parts["part_id"].to_numpy(),
        "annual_demand": D,
        "moq": moq,
        "eoq": eoq,
        "lot_size": lot,
        "binding": np.where(moq > eoq, "MOQ", "EOQ"),
        "months_of_supply_per_lot": lot / np.maximum(monthly, 1e-9),
        "annual_cost_monthly_ordering": annual_cost(monthly),
        "annual_cost_with_lot": annual_cost(lot),
    })
    out["annual_savings_vs_monthly_ordering"] = out["annual_cost_monthly_ordering"] - out["annual_cost_with_lot"]
    return out
