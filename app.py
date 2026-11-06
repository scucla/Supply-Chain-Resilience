"""Streamlit dashboard.   Run:  streamlit run app.py"""
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from src.pipeline import Inputs, run
from src.simulate import SimConfig

st.set_page_config(page_title="UAS Supply Chain Resilience", layout="wide")
st.title("UAS Supply Chain Resilience Planner")
st.caption("Illustrative BOM for a generic Group 2 sUAS. Not based on any real product. All data public or assumed.")

# ---------------- sidebar ----------------
with st.sidebar:
    st.header("Production ramp")
    start = st.number_input("Month-1 rate (units)", 10, 2000, 50, 10)
    end = st.number_input("Final rate (units)", 10, 5000, 500, 50)
    months = st.slider("Horizon (months)", 6, 24, 12)
    shape = st.radio("Ramp shape", ["s-curve", "linear"], horizontal=True)
    st.header("Inventory policy")
    sl = st.slider("Cycle service level", 0.80, 0.995, 0.95, 0.005)
    cv = st.slider("Forecast error (CV)", 0.05, 0.50, 0.20, 0.05)
    st.header("Risk weights")
    w = {k: st.slider(k, 0.0, 1.0, v, 0.05) for k, v in
         {"concentration": 0.30, "geopolitical": 0.30, "lead_time": 0.20, "single_source": 0.20}.items()}
    st.header("Simulation")
    n_sims = st.select_slider("Simulations", [500, 1000, 2000, 5000], 2000)
    surge = st.slider("Supplier catch-up capacity", 0.0, 1.0, 0.25, 0.05)
    buffer_wks = st.slider("Buffer mitigation (weeks)", 2.0, 12.0, 6.0, 1.0)


@st.cache_resource(show_spinner="Running Monte Carlo...")
def cached_run(start, end, months, shape, sl, cv, w_items, n_sims, surge, buffer_wks):
    cfg = SimConfig(n_sims=n_sims, surge=surge, buffer_weeks=buffer_wks)
    return run(Inputs(start, end, months, shape, sl, cv, dict(w_items), cfg))


r = cached_run(start, end, months, shape, sl, cv, tuple(w.items()), n_sims, surge, buffer_wks)
S, scored, m = r["sim_summary"], r["scored"], r["mitigations"]
names = r["parts"].set_index("part_id")["part_name"]

tabs = st.tabs(["Summary", "BOM", "Demand plan", "Risk", "Simulation", "Mitigations"])

# ---------------- summary ----------------
with tabs[0]:
    c = st.columns(4)
    c[0].metric("Planned units", f"{S['planned_units']:,.0f}")
    c[1].metric("Expected fill rate", f"{S['fill_rate']:.1%}")
    c[2].metric("P(any shortfall)", f"{S['p_any_shortfall']:.0%}")
    c[3].metric("Shortfall P95 (units)", f"{S['shortfall_p95']:,.0f}")
    if not m.empty:
        top = m.iloc[0]
        best = r["portfolios"][-1]
        st.subheader("Recommendation")
        st.markdown(
            f"- **Highest-value action:** {top['action']} for **{top['risk_part']}** "
            f"({names[top['risk_part']]}). Avoids ~{top['shortfall_avoided']:.0f} units of shortfall "
            f"(95% CI {top['ci95_low']:.0f} to {top['ci95_high']:.0f}) for ~${top['cost_usd']:,.0f}.\n"
            f"- **Top-{best['n']} bundle:** fill rate {S['fill_rate']:.1%} → {best['fill_rate']:.1%} "
            f"for ~${best['cost_usd']:,.0f}.\n"
            f"- **Compliance:** {int(scored['compliance_flag'].sum())} parts are sourced from a country of concern; "
            f"{int(r['compliance']['finding'].str.startswith('REVIEW').sum())} sit inside a section 848 critical component. "
            "See the Risk tab."
        )

# ---------------- BOM ----------------
with tabs[1]:
    ex = r["exploded"].copy()
    ex["value_per_unit"] = ex["extended_qty"] * ex["unit_cost_usd"]
    ex.loc[ex["value_per_unit"] == 0, "value_per_unit"] = 1  # make-nodes need a size; plotly sums children
    fig = px.sunburst(ex, ids="part_id", parents="parent_id", names="part_name", values="value_per_unit",
                      color="tier", branchvalues="remainder", title="BOM structure (sized by cost per system)")
    fig.update_layout(height=650)
    st.plotly_chart(fig, width="stretch")
    st.dataframe(ex.drop(columns="value_per_unit"), width="stretch", hide_index=True)

# ---------------- demand ----------------
with tabs[2]:
    st.plotly_chart(px.bar(r["plan"].reset_index(), x="month", y="units", title="Production plan"),
                    width="stretch")
    req = r["requirements"]
    tier2 = r["parts"].query("not direct_buy")["part_id"]
    st.subheader("Gross requirements: sub-tier forecast to share with tier-1 suppliers")
    st.dataframe(req.loc[req.index.isin(tier2)].astype(int), width="stretch")
    st.subheader("Order-now list (lead time longer than time until need)")
    late = r["orders"].query("status != 'planned'").groupby("part_id")["qty"].sum().sort_values(ascending=False)
    st.dataframe(late.rename("qty_already_late").to_frame().join(names), width="stretch")
    st.subheader("Safety stock: SS = z·√(L·σd² + d²·σL²)")
    st.dataframe(r["safety_stock"].round(1), width="stretch", hide_index=True)

# ---------------- risk ----------------
with tabs[3]:
    f = scored.head(20).copy()
    wn = {k: v / sum(w.values()) for k, v in w.items()} if sum(w.values()) else w
    long = pd.DataFrame({
        "part": f["part_id"].tolist() * 4,
        "factor": sum([[k] * len(f) for k in wn], []),
        "contribution": sum([(wn[k] * f[f"f_{k}"]).tolist() for k in wn], []),
    })
    st.plotly_chart(px.bar(long, x="contribution", y="part", color="factor", orientation="h",
                           title="Top 20 risk scores, by factor", height=600)
                    .update_yaxes(categoryorder="total ascending"), width="stretch")
    sc = scored.assign(spend=scored["horizon_spend_usd"].clip(lower=1))
    st.plotly_chart(px.scatter(sc, x="risk_score", y="extended_qty", color="supplier_country", size="unit_cost_usd",
                               hover_name="part_name", log_y=True, title="Risk vs. volume per system"),
                    width="stretch")
    st.dataframe(scored[["part_id", "part_name", "tier", "supplier", "supplier_country", "key_material", "hhi",
                         "f_concentration", "f_geopolitical", "f_lead_time", "f_single_source", "risk_score",
                         "risk_tier", "top_driver", "compliance_flag"]].round(3), width="stretch", hide_index=True)
    st.subheader("Compliance review: covered-country parts (section 848, fiscal-year-2020 defense authorization act)")
    st.caption("Flags for legal review, not legal conclusions.")
    st.dataframe(r["compliance"], width="stretch", hide_index=True)
    st.subheader("Material concentration (HHI)")
    st.dataframe(r["materials"].round(3), hide_index=True)

# ---------------- simulation ----------------
with tabs[4]:
    b = r["bands"]
    fig = go.Figure([
        go.Scatter(x=b["month"], y=b["p95"], line=dict(width=0), showlegend=False),
        go.Scatter(x=b["month"], y=b["p05"], fill="tonexty", line=dict(width=0), name="5–95% band"),
        go.Scatter(x=b["month"], y=b["p50"], name="Median built"),
        go.Scatter(x=b["month"], y=b["plan"], name="Plan", line=dict(dash="dash")),
    ])
    fig.update_layout(title="Units built per month across simulations", xaxis_title="month")
    st.plotly_chart(fig, width="stretch")
    st.subheader("Correlated shocks: what a country escalation does")
    st.caption("One escalation event hits every part sourced from that country AND every part whose key material it "
               "produces, at the same time. A second supplier does not help with the material loss.")
    st.dataframe(r["conditional"].round(3), hide_index=True)
    st.plotly_chart(px.histogram(r["shortfall_dist"], nbins=60, title="Distribution of end-of-horizon shortfall")
                    .update_layout(showlegend=False, xaxis_title="units short"), width="stretch")
    attr = r["attribution"].assign(part_name=lambda d: d["part_id"].map(names))
    st.plotly_chart(px.bar(attr.head(10), x="constraint_share", y="part_name", orientation="h",
                           title="Which direct-buy part was the binding constraint")
                    .update_yaxes(categoryorder="total ascending"), width="stretch")
    st.dataframe(r["params"].round(4), hide_index=True)

# ---------------- mitigations ----------------
with tabs[5]:
    if m.empty:
        st.info("No mitigations evaluated.")
    else:
        show = m.drop(columns="_specs").assign(part_name=lambda d: d["risk_part"].map(names))
        st.plotly_chart(px.scatter(show, x="cost_usd", y="shortfall_avoided", color="action", hover_name="part_name",
                                   error_y=show["ci95_high"] - show["shortfall_avoided"],
                                   title="Cost vs. shortfall avoided (with 95% CI)"), width="stretch")
        st.dataframe(show.round(1), width="stretch", hide_index=True)
        if "avoided_if_CHN_shock" in show:
            st.subheader("Ranked for the bad case: benefit if China escalates")
            st.caption("Average-case and tail-case rankings differ. Buffers and assembly-wide de-risking matter most "
                       "when a correlated shock hits.")
            st.dataframe(show.sort_values("avoided_if_CHN_shock", ascending=False)
                         [["risk_part", "part_name", "action", "shortfall_avoided", "avoided_if_CHN_shock", "cost_usd"]]
                         .head(10).round(1), width="stretch", hide_index=True)
        st.subheader("Bundles (re-simulated together, since benefits are not additive)")
        st.dataframe(pd.DataFrame(r["portfolios"]).drop(columns="actions").round(3), hide_index=True)
