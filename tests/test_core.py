import numpy as np
import pandas as pd
import pytest

from src import bom, demand, risk
from src.pipeline import Inputs, run
from src.simulate import SimConfig, Simulator


@pytest.fixture(scope="module")
def data():
    raw, mats, ctry = bom.load_data()
    ex = bom.explode(raw)
    return ex, bom.purchased_parts(ex), mats, ctry


def test_extended_qty_multiplies_down_the_tree(data):
    ex, *_ = data
    q = ex.set_index("part_id")["extended_qty"]
    assert q["PRP-001"] == 4            # 4 motors per drone
    assert q["PRP-001A"] == 4           # 1 magnet set per motor
    assert q["PRP-002A"] == 24          # 6 FETs x 4 ESCs
    assert q["PWR-001B"] == 24          # 1 anode per cell x 12 cells x 2 packs


def test_cycle_is_rejected(data):
    ex, _, _, ctry = data
    bad = ex[bom.load_data()[0].columns].copy()
    bad.loc[bad["part_id"] == "ASM-AIR", "parent_id"] = "AIR-001"
    with pytest.raises(ValueError):
        bom.validate_bom(bad, ctry)


def test_hhi_bounds(data):
    _, _, mats, ctry = data
    mm = risk.material_metrics(mats, ctry).set_index("material")
    assert ((mm["hhi"] >= 0) & (mm["hhi"] <= 1)).all()
    g = mats[(mats["material"] == "gallium") & (mats["country"] != "OTHER")]["share"]
    assert mm.loc["gallium", "hhi"] == pytest.approx((g ** 2).sum())


def test_safety_stock_zero_when_no_uncertainty(data):
    _, parts, *_ = data
    p = parts.assign(lead_time_sd_wks=0.0)
    ss = demand.safety_stock(p, demand.production_plan(100, 100, 6), demand_cv=0.0)
    assert (ss["safety_stock_units"] == 0).all()


def test_no_risk_means_no_shortfall(data):
    _, parts, mats, ctry = data
    plan = demand.production_plan(50, 500, 12)
    scored = risk.score_parts(parts, mats, ctry)
    params = risk.disruption_params(scored).assign(p_month=0.0, slip_p=0.0)
    sim = Simulator(parts, params, plan, pd.Series(dtype=float), SimConfig(n_sims=200))
    assert sim.summarize(sim.run())["expected_shortfall"] == 0


def test_more_coverage_never_hurts():
    r = run(Inputs(sim=SimConfig(n_sims=300)), with_mitigations=True)
    assert (r["mitigations"]["shortfall_avoided"] >= -1e-9).all()


def test_alternates_do_not_protect_against_material_shock(data):
    """A country shock on a part's key material can't be fixed by adding suppliers."""
    _, parts, mats, ctry = data
    plan = demand.production_plan(100, 100, 12)
    scored = risk.score_parts(parts, mats, ctry)
    params = risk.disruption_params(scored, mats, ctry).assign(p_month=0.0, slip_p=0.0)
    cfg = SimConfig(n_sims=300, escalation_p_month={"CHN": 0.3})
    sim = Simulator(parts, params, plan, pd.Series(dtype=float), cfg)
    base = sim.run()["shortfall"].mean()
    assert base > 0                                            # China shocks alone cause shortfall
    # Give every China-supplied part 100% backup coverage: material losses remain
    fix_suppliers = [("coverage", p, 1.0) for p in params.loc[params["direct_CHN"] == 1, "part_id"]]
    assert sim.run(fix_suppliers)["shortfall"].mean() > 0
    # Also remove all China material exposure: shortfall disappears
    fix_all = fix_suppliers + [("material", p, "CHN") for p in params.loc[params["matshare_CHN"] > 0, "part_id"]]
    assert sim.run(fix_all)["shortfall"].mean() == 0


def test_independent_mode_ignores_country_shocks(data):
    _, parts, mats, ctry = data
    plan = demand.production_plan(100, 100, 12)
    params = risk.disruption_params(risk.score_parts(parts, mats, ctry), mats, ctry).assign(p_month=0.0, slip_p=0.0)
    sim = Simulator(parts, params, plan, pd.Series(dtype=float),
                    SimConfig(n_sims=200, correlated=False, escalation_p_month={"CHN": 0.5}))
    assert sim.run()["shortfall"].mean() == 0


def test_eoq_formula_and_moq_floor(data):
    _, parts, *_ = data
    plan = demand.production_plan(100, 100, 12)            # flat: annual demand = 1200 x extended qty
    lots = demand.lot_sizing(parts, plan, order_cost=400, carrying_rate=0.25).set_index("part_id")
    p = parts.set_index("part_id").loc["AVI-002"]             # 1 per system
    expected = np.sqrt(2 * 1200 * 400 / (p["unit_cost_usd"] * 0.25))
    assert lots.loc["AVI-002", "eoq"] == pytest.approx(expected)
    assert (lots["lot_size"] >= lots["moq"]).all()
    assert (lots["lot_size"] >= np.floor(lots["eoq"])).all()


def test_lot_rounding_in_order_schedule(data):
    _, parts, *_ = data
    plan = demand.production_plan(10, 10, 6)
    one = parts[parts["part_id"] == "AIR-001"]               # 1 per system -> 10/month
    sched = demand.order_schedule(one, plan, pd.Series({"AIR-001": 25}))
    assert (sched["qty"] % 25 == 0).all()                    # whole lots only
    assert sched["qty"].sum() >= 60                          # covers total need
    assert sched["qty"].sum() - 60 < 25                      # never more than one lot of excess


def test_dollar_valuation_is_consistent():
    r = run(Inputs(sim=SimConfig(n_sims=300)))
    ue, S, m = r["unit_economics"], r["sim_summary"], r["mitigations"]
    assert ue["margin_per_unit_usd"] == pytest.approx(ue["unit_price_usd"] - ue["material_cost_usd"]
                                                      - ue["conversion_cost_usd"])
    assert S["expected_profit_at_risk_usd"] == pytest.approx(S["expected_shortfall"] * ue["margin_per_unit_usd"])
    assert np.allclose(m["net_benefit_usd"], m["shortfall_avoided"] * ue["margin_per_unit_usd"] - m["cost_usd"])


def test_greedy_respects_budget_and_improves():
    from src import optimize
    r = run(Inputs(sim=SimConfig(n_sims=300)))
    sim = r["simulator"]
    cands = sim.candidate_actions(r["scored"], 6)
    path = optimize.greedy(sim, cands, budget=200_000, max_steps=6)
    assert path["cumulative_cost_usd"].iloc[-1] <= 200_000
    assert (path["expected_shortfall"].diff().dropna() <= 1e-9).all()   # each step helps (mean objective)


def test_cvar_is_at_least_mean():
    from src.optimize import risk_metric
    x = np.random.default_rng(0).exponential(10, 1000)
    assert risk_metric(x, "cvar") >= risk_metric(x, "mean")


def test_sensitivity_hooks_change_inputs():
    from dataclasses import replace
    base = Inputs(sim=SimConfig(n_sims=200))
    r0 = run(base, with_mitigations=False)
    r1 = run(replace(base, param_scale={"p_month": 3.0}), with_mitigations=False)
    assert r1["sim_summary"]["fill_rate"] < r0["sim_summary"]["fill_rate"]
    r2 = run(replace(base, material_overrides={"germanium": {"CHN": 0.94, "OTHER": 0.06}}), with_mitigations=False)
    hhi = r2["materials"].set_index("material").loc["germanium", "hhi"]
    assert hhi == pytest.approx(0.94 ** 2)


# ---- live signal -------------------------------------------------------------
def _fake_gdelt(daily_old, daily_new, days_old=180, days_new=30):
    from datetime import date, timedelta
    start = date(2026, 4, 1)
    data = [{"date": (start + timedelta(days=i)).strftime("%Y%m%dT000000Z"),
             "value": daily_old if i < days_old else daily_new} for i in range(days_old + days_new)]
    return {"timeline": [{"series": "Article Count", "data": data}]}


def test_gdelt_parser_ratio():
    from src.signals import parse_gdelt_timeline
    recent, base = parse_gdelt_timeline(_fake_gdelt(2, 6))
    assert recent == pytest.approx(180)          # 30 days x 6
    assert base == pytest.approx(60)             # 30 days x 2
    assert recent / base == pytest.approx(3.0)


def test_calendar_and_news_multiplier(tmp_path):
    from datetime import date
    from src import signals
    exposed = {"gallium", "graphite"}
    fake = lambda url, timeout: _fake_gdelt(2, 6)           # news volume tripled
    out = signals.escalation_signal(exposed, {"CHN": 0.02}, asof=date(2026, 11, 5), fetch=fake,
                                    external_path=tmp_path / "none.json")
    c = out["countries"]["CHN"]
    assert c["calendar_multiplier"] == 2.0                 # Nov 10 and Nov 27 lapses both within 90 days
    assert c["other_multiplier"] == pytest.approx(1.5)     # 1 + 0.25 x (3 - 1)
    assert c["multiplier"] == pytest.approx(3.0)           # capped at 3
    # After both deadlines pass, the calendar adds nothing
    later = signals.escalation_signal(exposed, {"CHN": 0.02}, asof=date(2027, 3, 1), use_news=False,
                                      external_path=tmp_path / "none.json")
    assert later["countries"]["CHN"]["multiplier"] == 1.0


def test_offline_and_external_override(tmp_path):
    from datetime import date
    from src import signals
    def offline(url, timeout):
        raise OSError("no network")
    out = signals.escalation_signal({"gallium"}, {"CHN": 0.02}, asof=date(2027, 3, 1), fetch=offline,
                                    external_path=tmp_path / "none.json")
    assert out["countries"]["CHN"]["multiplier"] == 1.0    # fails safe
    ext = tmp_path / "external_signal.json"
    signals.write_external("CHN", 1.8, "sentinel", path=ext)
    out = signals.escalation_signal({"gallium"}, {"CHN": 0.02}, asof=date(2027, 3, 1), fetch=offline,
                                    external_path=ext)
    assert out["countries"]["CHN"]["multiplier"] == pytest.approx(1.8)
    assert "sentinel" in out["countries"]["CHN"]["other_source"]
