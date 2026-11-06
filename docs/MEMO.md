# Memo: Supply resilience for a small-drone production ramp

**Date:** 5 November 2026  **Scope:** illustrative 45-part bill of materials for a generic small drone, ramping from 50 to 500 systems a month over 12 months (3,300 total). Not based on any real product. Material shares and policy dates are cited in [SOURCES.md](SOURCES.md). Outage rates and costs are documented assumptions.

## Bottom line

At current risk levels the ramp delivers about **90.6%** of planned systems on time, roughly 310 short. In the worst 5% of simulated futures, about **1,420** are short. **Fund three supplier qualifications now (about $196,000):** graphite anode material, gallium nitride power transistors, and rare-earth magnets. That lifts on-time delivery to **92.4%**, and each returns **8–13×** its cost in profit at risk. With **$500,000**, add a second radio-frequency chip supplier, 6 weeks of speed-controller buffer stock, and a second radio processor supplier, reaching **93.6%**.

## Why now

Two Chinese export-control suspensions covering this parts list lapse this month: the October 2025 package on rare earths, battery materials and **graphite anode material** on **10 November**, and the ban on **gallium and germanium** exports to the United States on **27 November**. As of late October, neither had a published legal extension. Treating those deadlines as live risk doubles the modeled chance of a China supply shock. The probability of one within a year rises from 22% to 39%, and expected on-time delivery falls to **88.0%**. When a China shock happens, expected shortfall is **2.5× higher** (589 vs. 233 systems).

## How the analysis works

1. **Plan.** Explode the bill of materials into parts per drone. Turn the ramp into monthly part needs and order dates. Size safety stock for both demand and lead-time uncertainty. Order in economic or minimum lot sizes.
2. **Score.** Rate each part on material concentration (Herfindahl-Hirschman Index), geopolitical exposure, 95th-percentile lead time, and number of backup suppliers.
3. **Simulate.** Run 2,000 futures with part-level outages plus **correlated country shocks**. A single China export-control event hits every China-sourced part *and* every part using a China-concentrated material at the same time. Rank actions by shortfall avoided per dollar, with paired 95% confidence intervals. Choose funding sets with a greedy optimizer that re-simulates after every pick.

## Recommended actions

| Priority | Action | Cost | Systems saved (95% CI) | Profit protected |
|---|---|---|---|---|
| 1 | Second supplier: graphite anode material (battery) | $52k | 21 (16–25) | $0.67M |
| 2 | Second supplier: gallium nitride transistors (speed controller) | $71k | 19 (15–24) | $0.63M |
| 3 | Second supplier: rare-earth magnets (motors) | $72k | 17 (13–22) | $0.56M |
| 4 | Second supplier: radio-frequency front-end chip | $63k | 12 (9–16) | $0.40M |
| 5 | 6 weeks of buffer stock: electronic speed controller | $118k | 25 (21–28) | $0.80M |

Profit protected assumes $32,700 profit per system (illustrative $80,000 price). Systems short at month 12 are late rather than necessarily lost, so treat it as an upper bound.

**If you're planning for the bad case, the order changes.** A second supplier can't fix a cutoff of the *material*: both suppliers still need Chinese gallium or graphite. When a China shock occurs, the most valuable actions are **6 weeks of battery-pack buffer stock** (41 systems saved, $314k) and **6 weeks of speed-controller buffer stock** (35 saved). Fixing one part in an assembly also does nothing if a sibling part shares the same exposure. Battery-pack de-risking only works if both the graphite and the lithium cells move off Chinese material.

**Diminishing returns.** The first ~$375k raises on-time delivery from 90.6% to 93.4%, and the next ~$770k adds only 2.4 points more. Funding actions in their stand-alone ranking order eventually spends **$266k on an assembly bundle that adds nothing**, because earlier picks already covered it. Re-simulating after each pick avoids that.

## How much to trust it

- **The #1 recommendation was the same in all 20 sensitivity cases. The top-3 set was identical in 16.** Each of 10 assumptions was moved to a low and a high value ([tornado chart](tornado.png)).
- **The biggest uncertainty is how long and how often part outages last.** Together they swing on-time delivery from 86% to 95%. Validating them against real supplier on-time and quality history is the first thing to do with company data.
- **Compliance:** one part needs review. A Chinese germanium lens sits inside the gimbal, a "critical component" under section 848 of the fiscal-year-2020 defense authorization act. Three other China-sourced parts (magnets, gallium nitride transistors, graphite) sit outside covered components and are on watch. These are flags, not legal conclusions.
- **Lead times:** 15 of 38 purchased parts take more than 13 weeks. Five take more than 20 weeks (FPGA, artificial-intelligence processor, radio processor, GNSS receiver, gimbal), so the first quarter's orders for those need to be placed before the ramp starts.

## Limitations

The bill of materials, costs, lead times and outage rates are illustrative. Country risk scores are judgment calls with written rationale. The model uses monthly time steps and doesn't model supplier capacity caps. The live-signal multiplier applies for the whole horizon even though deadlines are one-time events. The greedy optimizer is a heuristic, not a proven optimum.

## Next steps with real data

1. Replace the illustrative bill of materials and lead times with a real export from the company's planning system.
2. Fit outage frequency and length to supplier delivery and quality history (the top sensitivity).
3. Re-run the optimizer against the actual mitigation budget, and refresh the live signal weekly.
