# Data sources and assumptions

Every number in `data/` (including `policy_calendar.csv`) is either **cited** (with a link in the CSV) or **assumed** (labeled `Assumption` or `ASSUMED`). This page summarizes both so a reviewer can check them quickly. Shares were last checked on **5 November 2026**.

## Material production shares (`data/material_sources.csv`)

| Material | China share | Basis | Source |
|---|---|---|---|
| Gallium | 98.9% | 2024 primary low-purity production (839 of 848 tonnes) | [USGS Mineral Commodity Summaries 2026: Gallium](https://pubs.usgs.gov/periodicals/mcs2026/mcs2026-gallium.pdf) |
| Rare-earth (NdFeB) magnets | 94% | 2024 sintered permanent magnet production | [International Energy Agency](https://www.iea.org/data-and-statistics/charts/china-s-share-in-rare-earth-magnet-production-2024) |
| Battery-grade graphite | 94% | 2025 refining | International Energy Agency Global Critical Minerals Outlook 2026, via [Bank of Finland BOFIT](https://www.bofit.fi/en/monitoring/weekly/2026/vw202632_2/) |
| Refined lithium | 74% | 2025 refining | Same as above |
| Refined copper | 47% | 2025 refining | Same as above |
| Aluminum | ~60% | 2024 smelter production | USGS Mineral Commodity Summaries 2025, via [Nasdaq](https://www.nasdaq.com/articles/top-10-aluminum-producing-countries) |
| Germanium | 60% (range 60–94%) | Refined production; USGS publishes no country table | Project Blue, via [Compound Semiconductor](https://compoundsemiconductor.net/article/122926/China_suspends_US_export_ban_on_Ga_and_Ge_and_Sb) |
| Carbon fiber | ~46% | China 2023 capacity ÷ 2024 global installed capacity | [Yicai Global](https://yicaiglobal.com/star50news/2024_04_116678981368770199555) and industry capacity reports |
| Advanced chips (16 nm and below) | 9% (Taiwan 66%) | 2024 foundry capacity | [TrendForce, May 2024](https://www.trendforce.com/news/2024/05/14/insights-trendforce-foundry-capacity-market-share-of-advanced-process-to-decline-in-taiwan-korea-until-2027-while-us-on-the-rise/) |
| Mature chips (28 nm and above) | ~33% | 2024 foundry capacity | TrendForce; Moody's via [SemiMedia](https://www.semimedia.cc/asia-controls-75-of-global-chip-capacity-set-to-keep-lead-in-next-five-years/) |

**Known weaknesses**
- **Germanium** has no reliable public country data. The model uses the low end (60%) and the sensitivity analysis tests the high end.
- **Carbon fiber** commodity shares overstate risk for aerospace-grade fiber, where Chinese suppliers are generally not qualified for defense programs.
- **The magnet split outside China** (Japan 4%, other 2%) is assumed.
- Where no country breakdown exists, the remainder is grouped as `OTHER`. Because `OTHER` is excluded from the concentration index, that index is a **lower bound**.

## Policy timeline that drives the China risk score

| Date | Event | Status on 5 Nov 2026 |
|---|---|---|
| Aug 2023 | China requires export licenses for gallium and germanium | In force |
| Dec 2024 | China bans gallium, germanium and antimony exports to the United States | **Suspended until 27 Nov 2026** |
| Apr 2025 | Licensing on seven medium/heavy rare earths (incl. dysprosium, terbium) | In force |
| Oct 2025 | Wider package: more rare earths, magnets made abroad with Chinese inputs, lithium batteries, **graphite anode material** | **Suspended until 10 Nov 2026** |
| Sep 2026 | China says the broader United States–China arrangement runs to 10 Jan 2027, but no amended legal notice covers the two dates above | As of late Oct, no published extension |
| Ongoing | Ban on Chinese dual-use exports to **United States military end users** | In force (never suspended) |

Sources: [CNBC](https://www.cnbc.com/2025/11/09/china-suspends-ban-on-exports-of-gallium-germanium-antimony-to-us.html), [Fastmarkets](https://www.fastmarkets.com/insights/china-suspends-export-prohibition-on-superhard-materials-us/), [Technology.org](https://www.technology.org/2026/10/19/china-rare-earth-export-pause-november-10/), [Carra Globe](https://carraglobe.com/china-rare-earth-export-controls-2026/), [InvestorNews](https://investornews.com/critical-minerals-rare-earths/chinas-november-27-gallium-deadline-leaves-america-exposed/).

## United States drone-component rule

Section 848 of the fiscal-year-2020 National Defense Authorization Act bars the Defense Department from buying drones that are made in China or that use **flight controllers, radios, data transmission devices, cameras, or gimbals** made in China ([statute text](https://www.wifcon.com/dodauth20/dod20_848.htm)). The `ndaa_848_category` column in `bom.csv` marks those components, and `risk.compliance_review()` flags any Chinese-origin part inside one. These are **flags for review, not legal conclusions.**

## Country risk scores (`data/country_risk.csv`)

These are **judgment calls** on a 0–1 scale, with the reasoning written next to each score in the CSV. They are not fitted to data. The sensitivity analysis shows how much the recommendations depend on them.

## Model parameters that are assumptions

| Parameter | Value | Where | Basis |
|---|---|---|---|
| Part-level outage probability per month | 0.2% + 0.8% × geopolitical + 0.5% × concentration | `risk.disruption_params` | Judgment; top sensitivity |
| Average part outage length | 1 + 3 × concentration months | same | Judgment; top sensitivity |
| Part outage severity | Uniform(30%, 100%) of output lost | `SimConfig.min_severity` | Judgment |
| China escalation shock probability | 2% per month (about 22% per year) | `SimConfig.escalation_p_month` | China announced roughly five rounds of controls touching these materials between Jul 2023 and Oct 2025 (about 0.2 per month). Most were licensing that slowed rather than stopped supply, so we assume about 1 in 10 effectively cuts supply to a given buyer |
| Escalation length / severity | Geometric, average 4 months / Uniform(30%, 100%) | `SimConfig` | Judgment; tested 2–6 months in the sensitivity analysis |
| Backup coverage | 0 / 50% / 80% for 0 / 1 / 2+ alternates | `risk.disruption_params` | Judgment |
| Supplier catch-up capacity | 25% of monthly volume | `SimConfig.surge` | Judgment |
| Second-supplier qualification | $50,000 + 3% price premium | `SimConfig` | Rough industry estimate |
| Non-China material qualification | $75,000 + 10% price premium | `SimConfig` | Rough estimate; non-Chinese material typically costs more |
| Inventory carrying cost | 25% per year | `SimConfig.carrying_rate` | Common textbook range 20–30% |
| Cost per purchase order | $400 | `Inputs.order_cost` | Admin, receiving inspection, fixed freight |
| Forecast error | 20% | `Inputs.demand_cv` | Judgment |
| Sale price / assembly cost per system | $80,000 / $15,000 | `Inputs` | Illustrative; profit = price − purchased parts − assembly |
| Live-signal coefficients | +0.5 per upcoming lapse; +0.25 per unit of news ratio above 1; cap 3× | `signals.py` | Simple, documented choices, not fitted |

The bill of materials itself (parts, costs, lead times, suppliers) is **illustrative** and does not represent any real product.
