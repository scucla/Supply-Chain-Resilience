"""Streamlit dashboard.   Run:  streamlit run app.py"""
import datetime as _dt
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from src import signals, ui
from src.pipeline import Inputs, budget_frontier, run
from src.simulate import SimConfig

ROOT = Path(__file__).parent
st.set_page_config(page_title="Supply Chain Resilience Planner", page_icon="◆", layout="wide",
                   initial_sidebar_state="collapsed")
ui.inject()
CC = st.column_config
PCT = lambda label: CC.NumberColumn(label, format="percent")          # noqa: E731
USD = lambda label: CC.NumberColumn(label, format="dollar")           # noqa: E731
NUM = lambda label, f="%.1f": CC.NumberColumn(label, format=f)        # noqa: E731

# ---------------- sidebar ----------------
with st.sidebar:
    st.markdown('<div class="sb-title">Scenario controls</div>', unsafe_allow_html=True)
    with st.expander("Production ramp", expanded=True):
        start = st.number_input("Month-1 rate (systems)", 10, 2000, 50, 10)
        end = st.number_input("Final rate (systems)", 10, 5000, 500, 50)
        months = st.slider("Horizon (months)", 6, 24, 12)
        shape = st.radio("Ramp shape", ["s-curve", "linear"], horizontal=True)
    with st.expander("Live risk signal", expanded=True):
        live = st.toggle("Adjust China shock risk for policy deadlines and news", value=False,
                         help="Policy calendar (offline, cited) plus a daily refresh of news volume and US export-"
                              "control rule-making, written to data/external_signal.json by a scheduled GitHub job.")
    with st.expander("Inventory policy"):
        sl = st.slider("Cycle service level", 0.80, 0.995, 0.95, 0.005)
        cv = st.slider("Forecast error", 0.05, 0.50, 0.20, 0.05)
    with st.expander("Risk weights"):
        w = {k: st.slider(k.replace("_", " ").capitalize(), 0.0, 1.0, v, 0.05) for k, v in
             {"concentration": 0.30, "geopolitical": 0.30, "lead_time": 0.20, "single_source": 0.20}.items()}
    with st.expander("Unit economics"):
        price = st.number_input("Sale price per system ($)", 10_000, 500_000, 80_000, 5_000)
        conv = st.number_input("Assembly + overhead per system ($)", 0, 200_000, 15_000, 1_000)
    with st.expander("Simulation"):
        n_sims = st.select_slider("Simulated futures", [500, 1000, 2000, 5000], 2000)
        surge = st.slider("Supplier catch-up capacity", 0.0, 1.0, 0.25, 0.05)
        buffer_wks = st.slider("Buffer mitigation (weeks)", 2.0, 12.0, 6.0, 1.0)


@st.cache_resource(show_spinner="Simulating 2,000 futures…")
def cached_run(start, end, months, shape, sl, cv, w_items, n_sims, surge, buffer_wks, price, conv, live, today):
    cfg = SimConfig(n_sims=n_sims, surge=surge, buffer_weeks=buffer_wks)
    return run(Inputs(start, end, months, shape, sl, cv, dict(w_items), cfg,
                      unit_price_usd=price, conversion_cost_usd=conv, live_signal=live, signal_asof=today))


today = _dt.date.today()
r = cached_run(start, end, months, shape, sl, cv, tuple(w.items()), n_sims, surge, buffer_wks, price, conv, live, today)
S, scored, m = r["sim_summary"], r["scored"], r["mitigations"]
names = r["parts"].set_index("part_id")["part_name"]
cond = r["conditional"].set_index("country")
p_shock = float(cond.loc["CHN", "p_shock_in_horizon"]) if "CHN" in cond.index else 0.0
credit = {k.split(" ")[0]: v for k, v in ui.credits().items()}


def _credit(file: str) -> str:
    c = credit.get(file)
    return f"Photo: {c['artist']} · public domain" if c else ""


# ---------------- hero ----------------
ui.hero(
    eyebrow="Supply chain resilience · illustrative small UAS program",
    title="See the shortage before it stops the line.",
    hint="Open the panel at top left (») to change the scenario",
    lede=f"Monte Carlo planning for a 45-part drone ramping {start} → {end} systems a month: correlated "
         f"export-control shocks, ranked fixes with confidence intervals, and a live policy signal.",
    stats=[(f"{S['fill_rate']:.1%}", "Expected on-time delivery"),
           (f"{S['shortfall_p95']:,.0f}", "Systems short · worst 5%"),
           (f"{p_shock:.0%}", f"Chance of a China shock · {months} mo"),
           (f"${S.get('expected_profit_at_risk_usd', 0) / 1e6:,.1f}M", "Expected profit at risk")],
    credit=(f"Footage: {credit['hero.mp4']['artist'].replace('Video by ', '')}, U.S. Air Force · public domain"
            if "hero.mp4" in credit else ""),
)

tabs = st.tabs(["Overview", "Bill of materials", "Demand", "Risk", "Simulation", "Actions", "Budget", "Sensitivity"])

# ---------------- overview ----------------
with tabs[0]:
    lapses = signals.upcoming_lapses(signals.load_calendar(),
                                     set(scored.loc[scored["key_material"] != "", "key_material"]), today, 120)
    if len(lapses):
        ui.section("Why now", "Export-control suspensions are about to lapse",
                   "Suspended Chinese controls covering materials in this bill of materials. As of late October no "
                   "legal extension had been published. Turn on the live risk signal in the sidebar to price them in.")
        pretty = lambda s_: ", ".join(x.replace("ndfeb_magnets", "rare-earth magnets").replace("_", " ")  # noqa: E731
                                      for x in s_.split(";"))
        ui.deadlines([(r_.suspended_until.strftime("%d %b %Y"), r_.description.split(";")[0],
                       f"{r_.days_until_lapse} days · {pretty(r_.exposed_materials)}")
                      for r_ in lapses.sort_values("suspended_until").itertuples()])
    if r.get("signal"):
        for c_, v in r["signal"]["countries"].items():
            ui.note(f"Live signal ({r['signal']['asof']}): {c_} shock probability {v['base_p_month']:.1%} → "
                    f"{v['adjusted_p_month']:.1%} per month (×{v['multiplier']:.2f}: policy calendar "
                    f"×{v['calendar_multiplier']:.1f}; {v['other_source']} ×{v['other_multiplier']:.2f}).")
        hist_path = ROOT / "data" / "signal_history.csv"
        if hist_path.exists():
            hist = pd.read_csv(hist_path)
            with st.expander(f"Daily signal history · {len(hist)} days"):
                st.plotly_chart(px.line(hist, x="date", y=["calendar_multiplier", "news_and_rules_multiplier",
                                                           "total_multiplier"], markers=True,
                                        title="CHINA SHOCK-PROBABILITY MULTIPLIER"), width="stretch")

    ui.section("Outlook", "Where the plan stands",
               "Profit at risk counts systems not delivered within the plan, so treat it as an upper bound: "
               "late systems may still ship later.")
    ue = r["unit_economics"]
    ui.kpis([
        ("Planned systems", f"{S['planned_units']:,.0f}", f"{start} → {end} per month over {months} months", False),
        ("Expected on-time delivery", f"{S['fill_rate']:.1%}", f"{S['expected_shortfall']:,.0f} systems short on average", True),
        ("Any shortfall", f"{S['p_any_shortfall']:.0%}", "share of simulated futures", False),
        ("Worst-5% shortfall", f"{S['shortfall_p95']:,.0f}", "systems not built on time", False),
        ("Profit per system", f"${ue['margin_per_unit_usd']:,.0f}", f"${ue['unit_price_usd']:,.0f} price − parts − assembly", False),
        ("Profit at risk", f"${S.get('expected_profit_at_risk_usd', 0) / 1e6:,.1f}M",
         f"${S.get('profit_at_risk_p95_usd', 0) / 1e6:,.1f}M in the worst 5%", False),
    ])

    if not m.empty:
        ui.section("Recommended actions", "Fund these first",
                   "Ranked by systems saved per dollar. Each figure is a paired comparison on the same simulated "
                   "futures, with a 95% confidence interval.")
        cards = []
        for i, a in enumerate(m.head(3).itertuples(), start=1):
            cards.append({"n": f"0{i}", "title": a.action, "part": f"{names.get(a.risk_part, a.risk_part)} · {a.risk_part}",
                          "rows": [("Cost", f"${a.cost_usd:,.0f}"),
                                   ("Systems saved", f"{a.shortfall_avoided:.0f}  ({a.ci95_low:.0f}–{a.ci95_high:.0f})"),
                                   ("If China escalates", f"{getattr(a, 'avoided_if_CHN_shock', float('nan')):.0f} saved"),
                                   ("Return on cost", f"{getattr(a, 'return_on_cost', float('nan')):.1f}×")]})
        best = r["portfolios"][-1]
        cards.append({"n": f"TOP {best['n']}", "title": "Fund the top five together", "part": "Re-simulated as a bundle",
                      "rows": [("Cost", f"${best['cost_usd']:,.0f}"),
                               ("On-time delivery", f"{S['fill_rate']:.1%} → {best['fill_rate']:.1%}"),
                               ("Worst-5% shortfall", f"{S['shortfall_p95']:,.0f} → {best['shortfall_p95']:,.0f}"),
                               ("Why bundle", "benefits overlap")]})
        ui.action_cards(cards)
        n_review = int(r["compliance"]["finding"].str.startswith("REVIEW").sum())
        ui.note(f"Compliance: {int(scored['compliance_flag'].sum())} parts come from a country of concern; {n_review} sits "
                "inside a drone critical component under section 848 of the FY2020 defense authorization act. "
                "Flags for review, not legal conclusions. Details in the Risk tab.")

# ---------------- bill of materials ----------------
with tabs[1]:
    ui.band("assembly_mq9.jpg", "Bill of materials", "45 parts, three supplier tiers",
            "Quantities multiply down the tree: 6 transistors × 4 speed controllers = 24 per drone.",
            _credit("assembly_mq9.jpg"))
    ex = r["exploded"].copy()
    ex["value_per_unit"] = ex["extended_qty"] * ex["unit_cost_usd"]
    ex.loc[ex["value_per_unit"] == 0, "value_per_unit"] = 1  # make-nodes need a size; plotly sums children
    fig = px.sunburst(ex, ids="part_id", parents="parent_id", names="part_name", values="value_per_unit",
                      color="tier", branchvalues="remainder", title="STRUCTURE · SIZED BY COST PER SYSTEM",
                      color_continuous_scale=[[0, "#1b2129"], [0.5, ui.BLUE], [1, ui.ACCENT]])
    fig.update_layout(height=640, coloraxis_showscale=False)
    st.plotly_chart(fig, width="stretch")
    bom_cols = {"part_id": "Part", "part_name": "Name", "parent_id": "Parent", "tier": "Tier", "make_buy": "Make / buy",
                "qty_per_parent": "Qty / parent", "extended_qty": "Qty / system", "unit_cost_usd": USD("Unit cost"),
                "supplier": "Supplier", "supplier_country": "Country", "alt_suppliers_qualified": "Backups",
                "lead_time_wks": "Lead time (wks)", "lead_time_sd_wks": "± wks", "moq": "Minimum order",
                "key_material": "Key material", "ndaa_848_category": "Critical component"}
    st.dataframe(ex[[c for c in bom_cols if c in ex]], width="stretch", hide_index=True, column_config=bom_cols)

# ---------------- demand ----------------
with tabs[2]:
    ui.band("assembly_line_1942.jpg", "Demand and ordering", "From a ramp to purchase orders",
            "Requirements by month, order-release dates offset by lead time, safety stock and lot sizes.",
            _credit("assembly_line_1942.jpg"))
    st.plotly_chart(px.bar(r["plan"].reset_index(), x="month", y="units", title="PRODUCTION PLAN · SYSTEMS PER MONTH")
                    .update_traces(marker_color=ui.ACCENT), width="stretch")
    req = r["requirements"]
    tier2 = r["parts"].query("not direct_buy")["part_id"]
    ui.section("Sub-tier forecast", "What to tell tier-1 suppliers",
               "Monthly need for parts inside supplier products. Sharing this lets suppliers order in time.")
    sub = req.loc[req.index.isin(tier2)].astype(int)
    sub.columns = [f"M{c}" for c in sub.columns]
    sub.insert(0, "Name", sub.index.map(names))
    st.dataframe(sub, width="stretch")
    ui.section("Lot sizing", "Economic order quantity vs. supplier minimum",
               "Q* = √(2 × annual demand × cost per order ÷ holding cost). The lot is the larger of Q* and the "
               "minimum; lots smaller than a month's need mean several deliveries a month.")
    lots = r["lots"].merge(r["parts"][["part_id", "part_name", "direct_buy"]])
    st.dataframe(lots[lots["direct_buy"]].drop(columns="direct_buy"), width="stretch", hide_index=True, column_config={
        "part_id": "Part", "part_name": "Name", "annual_demand": NUM("Annual demand", "%.0f"), "moq": NUM("Minimum", "%.0f"),
        "eoq": NUM("Economic qty", "%.0f"), "lot_size": NUM("Lot", "%.0f"), "binding": "Set by",
        "months_of_supply_per_lot": NUM("Months / lot", "%.2f"), "annual_cost_monthly_ordering": USD("Cost, monthly orders"),
        "annual_cost_with_lot": USD("Cost, with lot"), "annual_savings_vs_monthly_ordering": USD("Annual savings")})
    ui.section("Safety stock", "Buffer for demand and lead-time uncertainty", "SS = z · √(L·σd² + d²·σL²)")
    st.dataframe(r["safety_stock"], width="stretch", hide_index=True, column_config={
        "part_id": "Part", "avg_monthly_demand": NUM("Monthly demand", "%.0f"), "lead_time_months": NUM("Lead time (mo)"),
        "safety_stock_units": NUM("Safety stock", "%.0f"), "reorder_point_units": NUM("Reorder point", "%.0f"),
        "safety_stock_value_usd": USD("Value"), "z": NUM("z", "%.3f")})

# ---------------- risk ----------------
with tabs[3]:
    ui.section("Supplier risk", "Which parts are most likely to cause trouble, and why",
               "Four factors scaled 0–1: material concentration, geopolitical exposure, 95th-percentile lead time "
               "and number of backup suppliers. Weights are adjustable in the sidebar.")
    f = scored.head(20).copy()
    wn = {k: v / sum(w.values()) for k, v in w.items()} if sum(w.values()) else w
    long = pd.DataFrame({"part": [f"{p} · {names[p]}" for p in f["part_id"]] * 4,
                         "factor": sum([[k.replace("_", " ")] * len(f) for k in wn], []),
                         "contribution": sum([(wn[k] * f[f"f_{k}"]).tolist() for k in wn], [])})
    st.plotly_chart(px.bar(long, x="contribution", y="part", color="factor", orientation="h", height=640,
                           title="TOP 20 RISK SCORES · BY FACTOR").update_yaxes(categoryorder="total ascending", title=None),
                    width="stretch")
    st.dataframe(scored[["part_id", "part_name", "tier", "supplier_country", "key_material", "hhi", "risk_score",
                         "risk_tier", "top_driver", "compliance_flag"]], width="stretch", hide_index=True, column_config={
        "part_id": "Part", "part_name": "Name", "tier": "Tier", "supplier_country": "Country", "key_material": "Material",
        "hhi": NUM("Concentration", "%.2f"), "risk_score": CC.ProgressColumn("Risk score", min_value=0, max_value=1, format="%.2f"),
        "risk_tier": "Level", "top_driver": "Main driver", "compliance_flag": CC.CheckboxColumn("Country of concern")})
    ui.section("Compliance", "Covered-country parts inside drone critical components",
               "Section 848 of the FY2020 defense authorization act bars the Defense Department from buying drones whose "
               "flight controllers, radios, data links, cameras or gimbals are made in China. Flags, not legal conclusions.")
    st.dataframe(r["compliance"], width="stretch", hide_index=True, column_config={
        "part_id": "Part", "part_name": "Name", "supplier_country": "Country", "inside_component": "Inside",
        "section_848_category": "Critical component", "finding": "Finding"})
    ui.section("Materials", "How concentrated is world supply?", "Concentration = sum of squared country shares (1 = one country).")
    st.dataframe(r["materials"], hide_index=True, width="stretch", column_config={
        "material": "Material", "top_country": "Top producer",
        "hhi": CC.ProgressColumn("Concentration", min_value=0, max_value=1, format="%.2f"),
        "material_geo_risk": NUM("Geo risk", "%.2f"), "top_share": PCT("Top share")})

# ---------------- simulation ----------------
with tabs[4]:
    ui.band("small_uas.jpg", "Simulation", f"{n_sims:,} simulated futures",
            "Part outages plus correlated country shocks, propagated up the tree month by month.", _credit("small_uas.jpg"))
    b = r["bands"]
    fig = go.Figure([
        go.Scatter(x=b["month"], y=b["p95"], mode="lines", line=dict(width=0), showlegend=False, hoverinfo="skip"),
        go.Scatter(x=b["month"], y=b["p05"], mode="lines", fill="tonexty", fillcolor="rgba(110,168,254,0.16)",
                   line=dict(width=0), name="5–95% of futures"),
        go.Scatter(x=b["month"], y=b["p50"], mode="lines", name="Median built", line=dict(color=ui.BLUE, width=2.5)),
        go.Scatter(x=b["month"], y=b["plan"], mode="lines", name="Plan", line=dict(dash="dash", color=ui.ACCENT, width=2)),
    ])
    fig.update_layout(title="SYSTEMS BUILT PER MONTH", xaxis_title="Month", height=440)
    st.plotly_chart(fig, width="stretch")
    if "CHN" in cond.index:
        ui.kpis([("Chance of a China shock", f"{p_shock:.0%}", f"within {months} months", False),
                 ("Shortfall if it happens", f"{cond.loc['CHN', 'E_shortfall_if_shock']:,.0f}", "systems, average", True),
                 ("Shortfall if it doesn't", f"{cond.loc['CHN', 'E_shortfall_if_no_shock']:,.0f}", "systems, average", False),
                 ("Multiplier", f"{cond.loc['CHN', 'E_shortfall_if_shock'] / max(cond.loc['CHN', 'E_shortfall_if_no_shock'], 1):.1f}×",
                  "a second supplier can't offset a material cutoff", False)])
    c1, c2 = st.columns(2)
    with c1:
        st.plotly_chart(px.histogram(r["shortfall_dist"], nbins=50, title="DISTRIBUTION OF SHORTFALL · SYSTEMS")
                        .update_traces(marker_color=ui.BLUE).update_layout(showlegend=False, xaxis_title="Systems short",
                                                                           yaxis_title="Futures"), width="stretch")
    with c2:
        attr = r["attribution"].assign(part_name=lambda d: d["part_id"].map(names))
        st.plotly_chart(px.bar(attr.head(8), x="constraint_share", y="part_name", orientation="h",
                               title="WHICH PART STOPPED THE LINE").update_traces(marker_color=ui.ACCENT)
                        .update_layout(xaxis_tickformat=".0%", xaxis_title=None, yaxis_title=None)
                        .update_yaxes(categoryorder="total ascending"), width="stretch")
    with st.expander("Simulation parameters by part"):
        st.dataframe(r["params"], hide_index=True, width="stretch")

# ---------------- actions ----------------
with tabs[5]:
    if m.empty:
        st.info("No mitigations evaluated.")
    else:
        show = m.drop(columns="_specs").assign(part_name=lambda d: d["risk_part"].map(names).fillna(d["risk_part"]))
        ui.section("Mitigations", "Cost against systems saved",
                   "Error bars are 95% confidence intervals from paired simulations. Up and to the left is better.")
        kind = lambda a: ("Second supplier" if a.startswith("Qualify") and "material" not in a else    # noqa: E731
                          "Non-China material" if "material" in a else "Buffer stock" if "buffer" in a else "Assembly bundle")
        show["type"] = show["action"].map(kind)
        fig = px.scatter(show, x="cost_usd", y="shortfall_avoided", color="type", hover_name="part_name",
                         hover_data={"action": True, "type": False},
                         error_y=show["ci95_high"] - show["shortfall_avoided"], height=460)
        fig.update_traces(marker=dict(size=11, line=dict(width=0)))
        fig.update_layout(xaxis_title="Cost ($)", yaxis_title="Systems saved", legend_title=None, title=None)
        st.plotly_chart(fig, width="stretch")
        cols = {"risk_part": "Part", "part_name": "Name", "action": "Action", "cost_usd": USD("Cost"),
                "shortfall_avoided": NUM("Saved"), "ci95_low": NUM("CI low"), "ci95_high": NUM("CI high"),
                "avoided_if_CHN_shock": NUM("Saved if China escalates"), "return_on_cost": NUM("Return ×"),
                "net_benefit_usd": USD("Net benefit")}
        st.dataframe(show[[c for c in cols if c in show]], width="stretch", hide_index=True, column_config=cols)
        if "avoided_if_CHN_shock" in show:
            ui.section("Bad case", "Ranked for a China escalation",
                       "A second supplier still needs the same Chinese gallium or graphite. When the material is cut, "
                       "buffer stock and assembly-wide de-risking matter most.")
            st.dataframe(show.sort_values("avoided_if_CHN_shock", ascending=False)[[c for c in cols if c in show]].head(8),
                         width="stretch", hide_index=True, column_config=cols)

# ---------------- budget ----------------
with tabs[6]:
    ui.section("Budget optimizer", "What to fund with a given budget",
               "Picks one action at a time, re-simulating every remaining candidate on top of those already chosen, "
               "and takes the largest risk reduction per dollar. Re-simulating catches overlaps a one-shot ranking misses.")
    obj_label = st.radio("Optimize for", ["Average outcome", "Bad case (worst 10% of futures)"], horizontal=True)
    obj = "mean" if obj_label.startswith("Average") else "cvar"
    if st.button("Run optimizer · about 20 seconds"):
        with st.spinner("Re-simulating candidates…"):
            st.session_state["frontier"] = (obj, budget_frontier(r, obj))
    if "frontier" in st.session_state and st.session_state["frontier"][0] == obj:
        fr = st.session_state["frontier"][1]
        g, n = fr["greedy"], fr["naive"]
        fig = go.Figure([
            go.Scatter(x=g["cumulative_cost_usd"], y=g["fill_rate"], mode="lines+markers", name="Greedy, re-simulated",
                       line=dict(color=ui.ACCENT, width=2.5), marker=dict(size=8),
                       text=g["action"] + " · " + g["risk_part"], hovertemplate="%{text}<br>$%{x:,.0f} → %{y:.1%}"),
            go.Scatter(x=n["cumulative_cost_usd"], y=n["fill_rate"], mode="lines+markers", name="Naive ranking",
                       line=dict(dash="dot", color=ui.MUTED), marker=dict(size=6),
                       text=n["action"] + " · " + n["risk_part"], hovertemplate="%{text}<br>$%{x:,.0f} → %{y:.1%}"),
        ])
        fig.update_layout(title="EFFICIENT FRONTIER", xaxis_title="Cumulative cost ($)", yaxis_title="On-time delivery",
                          yaxis_tickformat=".1%", height=460)
        st.plotly_chart(fig, width="stretch")
        st.dataframe(g, width="stretch", hide_index=True, column_config={
            "step": "Step", "action": "Action", "risk_part": "Part", "cost_usd": USD("Cost"),
            "cumulative_cost_usd": USD("Cumulative"), "expected_shortfall": NUM("Avg short"),
            "cvar90_shortfall": NUM("Worst-10% short"), "fill_rate": PCT("On-time"), "profit_at_risk_usd": USD("Profit at risk"),
            "marginal_mean_reduction": NUM("Gain this step"), "marginal_cvar_reduction": NUM("Gain this step")})
        ui.section("Fixed budgets", "Best set for each budget")
        st.dataframe(fr["budgets"], width="stretch", hide_index=True, column_config={
            "budget_usd": USD("Budget"), "spent_usd": USD("Spent"), "n_actions": "Actions", "fill_rate": PCT("On-time"),
            "expected_shortfall": NUM("Avg short"), "cvar90_shortfall": NUM("Worst-10% short"), "actions": "Actions chosen"})

# ---------------- sensitivity ----------------
with tabs[7]:
    ui.section("Sensitivity", "Would the advice change if the assumptions are wrong?",
               "Each assumption moved to a low and a high value with everything else at base, on the same random draws. "
               "Precomputed at default settings by run_sensitivity.py.")
    sp = ROOT / "docs" / "sensitivity.csv"
    if sp.exists():
        sens = pd.read_csv(sp).sort_values("swing")
        base = sens["base_fill_rate"].iloc[0]
        top1 = sens["top1_low"].mode()[0]
        n_cases = 2 * len(sens)
        ui.kpis([("#1 recommendation unchanged", f"{int((sens['top1_low'] == top1).sum() + (sens['top1_high'] == top1).sum())}/{n_cases}", "cases", True),
                 ("Top-3 set unchanged", f"{int(sens['top3_same_set_low'].sum() + sens['top3_same_set_high'].sum())}/{n_cases}", "cases", False),
                 ("Biggest driver", sens.iloc[-1]["assumption"].split(" (")[0], "validate against supplier history first", False)])
        fig = go.Figure([
            go.Bar(y=sens["assumption"], x=(sens["fill_rate_low"] - base) * 100, base=base * 100, orientation="h",
                   name="Low value", marker_color=ui.BLUE, hovertemplate="%{y}<br>%{x:.1f} pts"),
            go.Bar(y=sens["assumption"], x=(sens["fill_rate_high"] - base) * 100, base=base * 100, orientation="h",
                   name="High value", marker_color=ui.ACCENT, hovertemplate="%{y}<br>%{x:.1f} pts"),
        ])
        fig.add_vline(x=base * 100, line_color="rgba(255,255,255,.5)", line_width=1)
        fig.update_layout(barmode="overlay", height=480, title=f"ON-TIME DELIVERY (%) · BASE {base:.1%}",
                          xaxis_title="On-time delivery (%)", yaxis_title=None)
        st.plotly_chart(fig, width="stretch")

ui.footer()
