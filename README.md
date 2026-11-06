# UAS Supply Chain Resilience Planner

**Recommendation (baseline: 50 → 500 units/month over 12 months):** Qualify second sources for the graphite anode material (PWR-001B) and the GaN power FETs in the ESC (PRP-002A) first. Each avoids roughly 25–33 units of expected shortfall for about $50–70k, which makes them the best value per dollar among the actions tested. Together with a 6-week buffer on the flight controller, the top-5 bundle lifts the simulated fill rate from **86.6% to 91.3%** for about **$450k**.

> The BOM is **illustrative**: a generic Group 2 small UAS assembled from public information. It does not represent any real product or company data. Material concentration figures are approximate and cited to public sources (USGS, IEA, SIA). Disruption parameters are explicit, documented assumptions.

![Dashboard](docs/simulation.png)

## What it does

| Module | Question it answers | Method |
|---|---|---|
| `src/bom.py` | How many of each part go into one system? | Multi-level BOM explosion (extended quantity), validation (single root, no cycles, no orphans) |
| `src/demand.py` | How many do we need each month, and when must we order? | S-curve production ramp → time-phased gross requirements → lead-time offset (MRP); safety stock under demand **and** lead-time uncertainty |
| `src/risk.py` | Which parts are most likely to cause trouble, and why? | 4-factor score: HHI material concentration, geopolitical exposure, P95 lead time, single-source flag |
| `src/simulate.py` | How many systems will we actually ship? What fixes help most? | Monte Carlo (2,000 runs) of supplier outages that propagate up the tree, shipment slips and supplier catch-up; mitigations ranked by shortfall avoided per $ with paired 95% CIs (common random numbers) |
| `app.py` | Interactive what-if | Streamlit dashboard: change the ramp, service level, risk weights, buffer size |

## Key formulas

- **Extended quantity:** `ext(part) = Π qty_per_parent` along the path to the root
- **Safety stock:** `SS = z · sqrt(L·σd² + d²·σL²)`
- **HHI:** `Σ sᵢ²` over producing countries (1 = single country)
- **Risk score:** `Σ wₖ · fₖ`, with each factor scaled to [0, 1]
- **Slip probability:** `P(LT > μ + 1 month) = 1 − Φ(4.33 / σ_LT)`

## Run it

```bash
pip install -r requirements.txt
python run_analysis.py      # prints results, writes CSVs to outputs/
streamlit run app.py        # dashboard
pytest -q                   # tests
```

## Assumptions and limitations

- Monthly time buckets; no MOQ, lot sizing or supplier capacity caps (yet)
- Disruption rates are mapped from risk factors by assumption, not fitted to historical data
- Outages at different parts are independent. A real export-control shock would hit every part using that material at once (see roadmap)
- Mitigation costs are rough estimates (qualification ≈ $50k + 3% price premium; inventory carrying cost 25%/yr)

## Roadmap
- Correlated shocks by material/country (one event hits all gallium parts)
- MOQ and lot sizing; supplier capacity limits
- Optimization: choose the mitigation set that maximizes fill rate under a budget (knapsack / MILP)
- Live feeds: export-control and sanctions list changes as risk signals
