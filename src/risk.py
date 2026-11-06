"""Part-level supply risk scoring.

Four factors, each scaled to [0, 1]:

  concentration : Herfindahl-Hirschman Index (HHI) of the key material's
                  producing countries.  HHI = sum(s_c^2).  1.0 = one country.
  geopolitical  : 50/50 blend of supplier-country risk and the share-weighted
                  risk of the countries producing the key material.
  lead_time     : 95th-percentile lead time (mu + 1.645 sigma) / cap.
  single_source : 1.0 if no qualified alternate, 0.5 if one, 0 if two or more.

Composite = weighted sum, weights normalised to sum to 1.
"""
from __future__ import annotations

from statistics import NormalDist

import numpy as np
import pandas as pd

DEFAULT_WEIGHTS = {"concentration": 0.30, "geopolitical": 0.30, "lead_time": 0.20, "single_source": 0.20}
LEAD_TIME_CAP_WKS = 40.0


def material_metrics(materials: pd.DataFrame, countries: pd.DataFrame) -> pd.DataFrame:
    """HHI and share-weighted geo risk per material.

    'OTHER' is a bucket of many small producers, so it is excluded from the HHI
    sum (treating it as perfectly fragmented). That makes HHI a lower bound.
    """
    risk = dict(zip(countries["country"], countries["geo_risk"]))
    rows = []
    for mat, g in materials.groupby("material"):
        named = g[g["country"] != "OTHER"]
        hhi = float((named["share"] ** 2).sum())
        geo = float((g["share"] * g["country"].map(risk)).sum() / g["share"].sum())
        top = (named if len(named) else g).sort_values("share", ascending=False).iloc[0]
        rows.append({"material": mat, "hhi": hhi, "material_geo_risk": geo,
                     "top_country": top["country"], "top_share": top["share"]})
    return pd.DataFrame(rows)


def score_parts(parts: pd.DataFrame, materials: pd.DataFrame, countries: pd.DataFrame,
                weights: dict[str, float] | None = None) -> pd.DataFrame:
    w = {**DEFAULT_WEIGHTS, **(weights or {})}
    total = sum(w.values()) or 1.0
    w = {k: v / total for k, v in w.items()}

    mm = material_metrics(materials, countries).set_index("material")
    c_risk = dict(zip(countries["country"], countries["geo_risk"]))
    concern = dict(zip(countries["country"], countries["country_of_concern"]))

    df = parts.copy()
    has_mat = df["key_material"] != ""
    df["hhi"] = df["key_material"].map(mm["hhi"]).where(has_mat, 0.0).astype(float)
    df["material_top_country"] = df["key_material"].map(mm["top_country"]).where(has_mat, "")
    supplier_geo = df["supplier_country"].map(c_risk).astype(float)
    mat_geo = df["key_material"].map(mm["material_geo_risk"]).astype(float)

    df["f_concentration"] = df["hhi"]
    df["f_geopolitical"] = np.where(has_mat, 0.5 * supplier_geo + 0.5 * mat_geo, supplier_geo)
    lt_p95 = df["lead_time_wks"] + 1.645 * df["lead_time_sd_wks"]
    df["f_lead_time"] = np.clip(lt_p95 / LEAD_TIME_CAP_WKS, 0, 1)
    df["f_single_source"] = df["alt_suppliers_qualified"].map(lambda n: 1.0 if n == 0 else 0.5 if n == 1 else 0.0)

    df["risk_score"] = (w["concentration"] * df["f_concentration"] + w["geopolitical"] * df["f_geopolitical"]
                        + w["lead_time"] * df["f_lead_time"] + w["single_source"] * df["f_single_source"])
    df["compliance_flag"] = df["supplier_country"].map(concern).astype(bool)
    df["risk_tier"] = pd.cut(df["risk_score"], bins=[-0.01, 0.30, 0.50, 1.01], labels=["Low", "Medium", "High"])
    df["top_driver"] = df[["f_concentration", "f_geopolitical", "f_lead_time", "f_single_source"]].idxmax(axis=1) \
        .str.replace("f_", "", regex=False)
    return df.sort_values("risk_score", ascending=False).reset_index(drop=True)


def disruption_params(scored: pd.DataFrame, materials: pd.DataFrame | None = None,
                      countries: pd.DataFrame | None = None) -> pd.DataFrame:
    """Translate risk factors into simulation parameters (explicit assumptions).

    p_month       : monthly probability a PART-LEVEL outage starts = 0.2% + 0.8%*geo + 0.5%*HHI
                    (idiosyncratic: fires, quality escapes, supplier failure). Country-wide
                    export-control shocks are modeled separately and are correlated across parts.
    mean_duration : mean disruption length in months = 1 + 3*HHI
                    (concentrated materials have nowhere else to go, so outages last longer)
    coverage      : fraction of supply alternates can cover during an outage
    slip_p        : chance a shipment is > 1 month late, assuming LT ~ Normal(mu, sigma):
                    P(LT > mu + 4.33 wks) = 1 - Phi(4.33 / sigma)
    """
    out = scored[["part_id"]].copy()
    out["p_month"] = 0.002 + 0.008 * scored["f_geopolitical"] + 0.005 * scored["hhi"]
    out["mean_duration"] = 1 + 3 * scored["hhi"]
    out["coverage"] = scored["alt_suppliers_qualified"].map(lambda n: 0.0 if n == 0 else 0.5 if n == 1 else 0.8)
    sd = scored["lead_time_sd_wks"].clip(lower=1e-6).to_numpy()
    out["slip_p"] = 1 - np.vectorize(NormalDist().cdf)((52 / 12) / sd)
    # Exposure to each country of concern, for correlated escalation shocks
    if materials is not None and countries is not None:
        for c in countries.loc[countries["country_of_concern"] == 1, "country"]:
            share = materials[materials["country"] == c].set_index("material")["share"]
            out[f"matshare_{c}"] = scored["key_material"].map(share).fillna(0.0).to_numpy()
            out[f"direct_{c}"] = (scored["supplier_country"] == c).astype(float).to_numpy()
    return out


def compliance_review(exploded: pd.DataFrame, countries: pd.DataFrame) -> pd.DataFrame:
    """Flag country-of-concern parts that sit inside a 'critical component' named in
    section 848 of the fiscal-year-2020 National Defense Authorization Act (flight
    controllers, radios, data transmission devices, cameras, gimbals).

    Section 848 bars the Defense Department from buying drones whose critical
    components are MANUFACTURED in China. A Chinese sub-part inside a United
    States-made component is not automatically covered, so these are flags for
    legal review, not verdicts.
    """
    concern = set(countries.loc[countries["country_of_concern"] == 1, "country"])
    parent = dict(zip(exploded["part_id"], exploded["parent_id"]))
    cat = dict(zip(exploded["part_id"], exploded.get("ndaa_848_category", pd.Series(dtype=str)).fillna("")))
    rows = []
    for _, p in exploded.iterrows():
        if p["supplier_country"] not in concern:
            continue
        cur, chain = p["part_id"], []
        while cur:
            if cat.get(cur):
                chain.append((cur, cat[cur]))
            cur = parent.get(cur, "")
        for comp, c in chain:
            level = "HIGH: component itself made in a covered country" if comp == p["part_id"] \
                else "REVIEW: covered-country sub-part inside a critical component"
            rows.append({"part_id": p["part_id"], "part_name": p["part_name"], "supplier_country": p["supplier_country"],
                         "inside_component": comp, "section_848_category": c, "finding": level})
        if not chain:
            rows.append({"part_id": p["part_id"], "part_name": p["part_name"], "supplier_country": p["supplier_country"],
                         "inside_component": "", "section_848_category": "",
                         "finding": "WATCH: covered-country source outside section 848 critical components"})
    return pd.DataFrame(rows)
