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


def chart(fig):
    """Render with our own Plotly template (theme=None stops Streamlit restyling) and no toolbar clutter."""
    st.plotly_chart(fig, width="stretch", theme=None,
                    config={"displayModeBar": False, "displaylogo": False, "responsive": True})
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
                chart(px.line(hist, x="date", y=["calendar_multiplier", "news_and_rules_multiplier",
                                                           "total_multiplier"], markers=True,
                                        title="China shock-probability multiplier"))

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
    risk_by_part = scored.set_index("part_id")["risk_score"]
    kids = {}
    for pid_, par_ in zip(ex["part_id"], ex["parent_id"]):
        kids.setdefault(par_, []).append(pid_)

    def chain(pid_):
        out_, stack_ = [pid_], list(kids.get(pid_, []))
        while stack_:
            c_ = stack_.pop(); out_.append(c_); stack_ += kids.get(c_, [])
        return out_

    tm = ex[ex["direct_buy"]].copy()
    tm["cost_per_system"] = tm["extended_qty"] * tm["unit_cost_usd"]
    tm["assembly"] = tm["parent_id"].map(ex.set_index("part_id")["part_name"]).str.replace(" assembly", "")
    tm["chain_risk"] = tm["part_id"].map(lambda p_: max(risk_by_part.get(c_, 0) for c_ in chain(p_)))
    tm["riskiest"] = tm["part_id"].map(lambda p_: names.get(max(chain(p_), key=lambda c_: risk_by_part.get(c_, 0)), ""))
    ui.section("Where the money and the risk sit",
               "Purchased parts, grouped by assembly",
               "Box size is cost per system. Color runs from beige (low risk) to deep orange (high risk) and shows the "
               "highest risk score anywhere in that part's supply chain, "
               "including sub-tier parts the supplier buys, so a U.S.-made speed controller still shows the risk of the "
               "Chinese gallium transistors inside it.")
    def risk_color(v):
        stops = [(0.0, (236, 232, 223)), (0.45, (232, 183, 150)), (1.0, (194, 65, 12))]
        for (a, ca), (b_, cb) in zip(stops, stops[1:]):
            if v <= b_:
                t = (v - a) / (b_ - a)
                return "rgb(%d,%d,%d)" % tuple(round(x + (y - x) * t) for x, y in zip(ca, cb))
        return "rgb(194,65,12)"

    asm = tm.groupby("assembly")["cost_per_system"].sum()
    ids = ["root"] + [f"a:{a}" for a in asm.index] + list(tm["part_id"])
    labels = ["Drone"] + list(asm.index) + list(tm["part_name"])
    parents = [""] + ["root"] * len(asm) + [f"a:{a}" for a in tm["assembly"]]
    values = [asm.sum()] + list(asm.values) + list(tm["cost_per_system"])
    colors = ["#FFFFFF"] + ["#F6F5F1"] * len(asm) + [risk_color(v) for v in tm["chain_risk"]]
    text = [""] + [f"${v:,.0f} per system" for v in asm.values] + [
        f"${c:,.0f} · risk {r_:.2f}" for c, r_ in zip(tm["cost_per_system"], tm["chain_risk"])]
    hover = [""] + [""] * len(asm) + [f"Riskiest input: {x}<br>Supplier country: {y}"
                                      for x, y in zip(tm["riskiest"], tm["supplier_country"])]
    fig = go.Figure(go.Treemap(
        ids=ids, labels=labels, parents=parents, values=values, branchvalues="total", text=text,
        customdata=hover, marker=dict(colors=colors, line=dict(color="#FFFFFF", width=3)),
        texttemplate="<b>%{label}</b><br>%{text}", textposition="top left",
        textfont=dict(family="Inter, sans-serif", size=13, color=ui.TEXT),
        hovertemplate="<b>%{label}</b><br>%{text}<br>%{customdata}<extra></extra>",
        tiling=dict(pad=4, packing="squarify"), pathbar=dict(visible=False), maxdepth=3, root=dict(color="#FFFFFF")))
    fig.update_layout(height=620, margin=dict(l=0, r=0, t=0, b=0), uniformtext=dict(minsize=10.5, mode="hide"))
    chart(fig)
    with st.expander("Full bill of materials (all tiers)"):
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
    chart(px.bar(r["plan"].reset_index(), x="month", y="units", title="Production plan: systems per month")
                    .update_layout(xaxis=dict(title="Month", dtick=1), yaxis_title="Systems")
                    .update_traces(marker_color=ui.BLUE))
    req = r["requirements"]
    tier2 = r["parts"].query("not direct_buy")["part_id"]
    ui.section("Sub-tier forecast", "What to tell tier-1 suppliers",
               "Monthly need for parts inside supplier products. Sharing this lets suppliers order in time.")
    sub = req.loc[req.index.isin(tier2)].astype(int)
    sub.columns = [f"M{c}" for c in sub.columns]
    sub.insert(0, "Name", sub.index.map(names))
    sub.index.name = "Part"
    st.dataframe(sub, width="stretch")
    ui.section("Lot sizing", "Economic order quantity vs. supplier minimum",
               "The lot is the larger of the economic order quantity and the supplier's minimum. Lots smaller than a "
               "month's need mean several deliveries a month.")
    st.latex(r"Q^{*} = \sqrt{\dfrac{2\,D\,S}{H}} \qquad \text{lot} = \max\left(Q^{*},\ \text{MOQ}\right)")
    st.caption("D = annual demand · S = cost per purchase order ($400) · H = holding cost per unit per year "
               "(25% of unit cost) · MOQ = supplier minimum order quantity")
    lots = r["lots"].merge(r["parts"][["part_id", "part_name", "direct_buy"]])
    st.dataframe(lots[lots["direct_buy"]].drop(columns="direct_buy"), width="stretch", hide_index=True, column_config={
        "part_id": "Part", "part_name": "Name", "annual_demand": NUM("Annual demand", "%.0f"), "moq": NUM("Minimum", "%.0f"),
        "eoq": NUM("Economic qty", "%.0f"), "lot_size": NUM("Lot", "%.0f"), "binding": "Set by",
        "months_of_supply_per_lot": NUM("Months / lot", "%.2f"), "annual_cost_monthly_ordering": USD("Cost, monthly orders"),
        "annual_cost_with_lot": USD("Cost, with lot"), "annual_savings_vs_monthly_ordering": USD("Annual savings")})
    ui.section("Safety stock", "Buffer for demand and lead-time uncertainty",
               "Demand during the lead time varies for two reasons: demand itself, and the lead time. Safety stock "
               "covers both at a 95% cycle service level.")
    st.latex(r"SS = z\,\sqrt{\,L\,\sigma_d^{2} + d^{2}\,\sigma_L^{2}\,}")
    st.caption("z = 1.645 for 95% · d, σd = average and spread of monthly demand · L, σL = average and spread of "
               "lead time in months")
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
    chart(px.bar(long, x="contribution", y="part", color="factor", orientation="h", height=660,
                 title="Top 20 risk scores, split by factor", labels={"factor": "", "part": "", "contribution": ""})
          .update_yaxes(categoryorder="total ascending", title=None)
          .update_layout(legend_title_text="", xaxis_title="Risk score (sum of weighted factors)",
                         margin=dict(l=8, r=24, t=72, b=56)))
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
    ui.section("Materials", "How concentrated is world supply?",
               "Concentration is the Herfindahl-Hirschman index: the sum of squared country shares. 1 means one country.")
    st.latex(r"\text{HHI} = \sum_{c} s_c^{2}")
    st.dataframe(r["materials"], hide_index=True, width="stretch", column_config={
        "material": "Material", "top_country": "Top producer",
        "hhi": CC.ProgressColumn("Concentration", min_value=0, max_value=1, format="%.2f"),
        "material_geo_risk": NUM("Geo risk", "%.2f"), "top_share": PCT("Top share")})

# ---------------- simulation ----------------
with tabs[4]:
    ui.band("small_uas.jpg", "Simulation", f"{n_sims:,} simulated futures",
            "Part outages plus correlated country shocks, propagated up the tree month by month.", _credit("small_uas.jpg"))
    b = r["bands"]
    ui.section("Deliveries", "Cumulative systems delivered against plan",
               "Each shaded range covers that share of the simulated futures. Most futures track the plan; "
               "the gap opens after month 6, when volume is high and a single outage costs the most.")
    last = b.iloc[-1]
    fig = go.Figure([
        go.Scatter(x=b["month"], y=b["cum_p95"], mode="lines", line=dict(width=0), showlegend=False, hoverinfo="skip"),
        go.Scatter(x=b["month"], y=b["cum_p05"], mode="lines", fill="tonexty", fillcolor="rgba(107,140,174,0.18)",
                   line=dict(width=0), name="90% of futures", hoverinfo="skip"),
        go.Scatter(x=b["month"], y=b["cum_p75"], mode="lines", line=dict(width=0), showlegend=False, hoverinfo="skip"),
        go.Scatter(x=b["month"], y=b["cum_p25"], mode="lines", fill="tonexty", fillcolor="rgba(31,58,95,0.22)",
                   line=dict(width=0), name="Middle 50%", hoverinfo="skip"),
        go.Scatter(x=b["month"], y=b["cum_plan"], mode="lines", name="Plan", line=dict(color=ui.TEXT, width=2, dash="dot"),
                   hovertemplate="Month %{x}<br>Plan %{y:,.0f}<extra></extra>"),
        go.Scatter(x=b["month"], y=b["cum_mean"], mode="lines", name="Average future", line=dict(color=ui.ACCENT, width=3),
                   hovertemplate="Month %{x}<br>Average %{y:,.0f}<extra></extra>"),
    ])
    for y_, label_, color_ in [(last["cum_plan"], f"Plan {last['cum_plan']:,.0f}", ui.TEXT),
                               (last["cum_mean"], f"Average {last['cum_mean']:,.0f}", ui.ACCENT),
                               (last["cum_p05"], f"Worst 5%: {last['cum_p05']:,.0f}", ui.MUTED)]:
        fig.add_annotation(x=last["month"], y=y_, text=f"<b>{label_}</b>", showarrow=False, xanchor="left", xshift=10,
                           font=dict(family="JetBrains Mono, ui-monospace, monospace", size=12, color=color_))
    fig.update_layout(height=480, margin=dict(r=150), xaxis=dict(title="Month", dtick=1, range=[0.8, last["month"] + 0.2]),
                      yaxis=dict(title="Systems delivered (cumulative)", tickformat=","), hovermode="x unified")
    chart(fig)
    if "CHN" in cond.index:
        ui.kpis([("Chance of a China shock", f"{p_shock:.0%}", f"within {months} months", False),
                 ("Shortfall if it happens", f"{cond.loc['CHN', 'E_shortfall_if_shock']:,.0f}", "systems, average", True),
                 ("Shortfall if it doesn't", f"{cond.loc['CHN', 'E_shortfall_if_no_shock']:,.0f}", "systems, average", False),
                 ("Multiplier", f"{cond.loc['CHN', 'E_shortfall_if_shock'] / max(cond.loc['CHN', 'E_shortfall_if_no_shock'], 1):.1f}×",
                  "a second supplier can't offset a material cutoff", False)])
    c1, c2 = st.columns(2)
    with c1:
        sf = r["shortfall_dist"]
        chart(px.histogram(sf, nbins=40, title="How many systems end up short")
                        .update_traces(marker_color=ui.STEEL, marker_line=dict(color=ui.PANEL, width=1))
                        .add_vline(x=sf.mean(), line=dict(color=ui.ACCENT, width=2),
                                   annotation_text=f"average {sf.mean():,.0f}", annotation_font_color=ui.ACCENT)
                        .update_layout(showlegend=False, xaxis_title="Systems short at month 12",
                                       yaxis_title="Simulated futures", height=400))
    with c2:
        attr = r["attribution"].assign(part_name=lambda d: d["part_id"].map(names))
        chart(px.bar(attr.head(8), x="constraint_share", y="part_name", orientation="h", text="constraint_share",
                               title="Which part stopped the line")
                        .update_traces(marker_color=ui.BLUE, texttemplate="%{text:.0%}", textposition="outside",
                                       textfont=dict(family="JetBrains Mono, ui-monospace, monospace", size=11, color=ui.MUTED), cliponaxis=False)
                        .update_layout(xaxis_tickformat=".0%", xaxis_title="Share of short months", yaxis_title=None,
                                       height=400)
                        .update_yaxes(categoryorder="total ascending"))
    with st.expander("Simulation parameters by part"):
        st.dataframe(r["params"], hide_index=True, width="stretch")

# ---------------- actions ----------------
with tabs[5]:
    if m.empty:
        st.info("No mitigations evaluated.")
    else:
        show = m.drop(columns="_specs").assign(part_name=lambda d: d["risk_part"].map(names).fillna(d["risk_part"]))
        kind = lambda a: ("Second supplier" if a.startswith("Qualify") and "material" not in a else    # noqa: E731
                          "Non-China material" if "material" in a else "Buffer stock" if "buffer" in a else "Assembly bundle")
        show["type"] = show["action"].map(kind)
        show["per100k"] = show["shortfall_avoided"] / show["cost_usd"] * 1e5
        top = show[show["shortfall_avoided"] > 0.5].sort_values("per100k", ascending=False).head(12).iloc[::-1]
        short = {"Second supplier": "Second supplier", "Buffer stock": "6-week buffer",
                 "Non-China material": "Non-China material", "Assembly bundle": "De-risk whole assembly"}
        top["label"] = [f"{short[t]} · {n}" for t, n in zip(top["type"], top["part_name"])]
        top["label"] = top["label"].where(~top["label"].duplicated(), top["label"] + " ")
        palette = {"Second supplier": ui.BLUE, "Buffer stock": ui.ACCENT, "Assembly bundle": ui.STEEL,
                   "Non-China material": ui.GREEN}
        ui.section("Mitigations", "The twelve best actions per dollar",
                   "Systems saved over the 12-month plan, with 95% confidence intervals from paired simulations. "
                   "Cost and return on cost on the right.")
        fig = go.Figure()
        for t_, g_ in top.groupby("type", sort=False):
            fig.add_trace(go.Scatter(
                x=g_["shortfall_avoided"], y=g_["label"], mode="markers", name=t_,
                marker=dict(size=13, color=palette[t_], line=dict(color="white", width=1.5)),
                error_x=dict(type="data", symmetric=False, array=g_["ci95_high"] - g_["shortfall_avoided"],
                             arrayminus=g_["shortfall_avoided"] - g_["ci95_low"], color=palette[t_], thickness=2, width=0),
                customdata=g_[["cost_usd", "action", "ci95_low", "ci95_high"]],
                hovertemplate="<b>%{y}</b><br>%{customdata[1]}<br>Saves %{x:.1f} systems (%{customdata[2]:.0f}–"
                              "%{customdata[3]:.0f})<br>Cost $%{customdata[0]:,.0f}<extra></extra>"))
        xmax = float(top["ci95_high"].max()) * 1.08
        for _, row_ in top.iterrows():
            ret_ = f" · {row_['return_on_cost']:.1f}×" if "return_on_cost" in row_ else ""
            fig.add_annotation(x=1.0, xref="paper", y=row_["label"], text=f"${row_['cost_usd'] / 1e3:,.0f}K{ret_}",
                               showarrow=False, xanchor="left", xshift=12,
                               font=dict(family="JetBrains Mono, ui-monospace, monospace", size=11.5, color=ui.MUTED))
        fig.update_layout(height=150 + 40 * len(top), margin=dict(l=8, r=150, t=70, b=70),
                          xaxis=dict(title="Systems saved", range=[0, xmax], side="top"),
                          yaxis=dict(title=None, tickfont=dict(family="Inter", size=13, color=ui.TEXT),
                                     categoryorder="array", categoryarray=top["label"].tolist()),
                          legend=dict(y=-0.04, yanchor="top", x=0), hovermode="closest")
        fig.add_annotation(x=1.0, xref="paper", y=1.0, yref="paper", yshift=26, text="COST · RETURN", showarrow=False,
                           xanchor="left", xshift=12, font=dict(family="JetBrains Mono, ui-monospace, monospace", size=10, color=ui.MUTED))
        chart(fig)
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
                       line=dict(color=ui.ACCENT, width=3), marker=dict(size=8),
                       text=g["action"] + " · " + g["risk_part"], hovertemplate="%{text}<br>$%{x:,.0f} → %{y:.1%}"),
            go.Scatter(x=n["cumulative_cost_usd"], y=n["fill_rate"], mode="lines+markers", name="Naive ranking",
                       line=dict(dash="dot", color=ui.GRAY), marker=dict(size=6),
                       text=n["action"] + " · " + n["risk_part"], hovertemplate="%{text}<br>$%{x:,.0f} → %{y:.1%}"),
        ])
        fig.update_layout(title="Efficient frontier", xaxis_title="Cumulative cost ($)", yaxis_title="On-time delivery",
                          yaxis_tickformat=".1%", height=460)
        chart(fig)
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
                   name="Low value", marker_color=ui.STEEL, hovertemplate="%{y}<br>%{x:.1f} pts"),
            go.Bar(y=sens["assumption"], x=(sens["fill_rate_high"] - base) * 100, base=base * 100, orientation="h",
                   name="High value", marker_color=ui.ACCENT, hovertemplate="%{y}<br>%{x:.1f} pts"),
        ])
        fig.add_vline(x=base * 100, line_color=ui.TEXT, line_width=1)
        fig.update_layout(barmode="overlay", height=480, title=f"On-time delivery under each assumption (base {base:.1%})",
                          xaxis_title="On-time delivery (%)", yaxis_title=None)
        chart(fig)

ui.footer()
