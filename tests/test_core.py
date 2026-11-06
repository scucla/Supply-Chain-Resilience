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
