"""Live risk signal: adjust the chance of a country escalation shock.

The base model assumes a constant 2%/month chance of a China escalation shock.
In reality the risk moves with policy deadlines and the news. This module turns
three inputs into a single multiplier on that probability:

1. Policy calendar (data/policy_calendar.csv) - works offline, every row cited.
   A SUSPENDED control that is due to lapse within `window_days` and that covers
   a material in our bill of materials raises the multiplier:
       calendar = 1 + 0.5 x (number of such upcoming lapses)

2. News volume (optional, needs internet) - GDELT's free news API. For each exposed
   material we compare the last 30 days of articles matching
   "China export control <material>" with the average 30-day volume over the
   prior 180 days:
       ratio = recent / baseline
       news  = 1 + 0.25 x clip(average ratio - 1, 0, 4)

3. External override (optional) - data/external_signal.json written by another
   system (e.g. the Sentinel open-source intelligence pipeline):
       {"CHN": {"multiplier": 1.8, "source": "sentinel", "asof": "2026-11-05"}}
   If present it replaces the news component.

multiplier = min(cap, calendar x news_or_external)      (cap = 3 by default)

These coefficients are simple, documented choices, not fitted values: the point
is that the plan reacts to a dated, checkable signal instead of a fixed number.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd

DATA = Path(__file__).resolve().parent.parent / "data"
GDELT = "https://api.gdeltproject.org/api/v2/doc/doc?query={q}&mode=timelinevolraw&format=json&timespan={span}"
MATERIAL_TERMS = {
    "gallium": "gallium", "germanium": "germanium", "graphite": "graphite", "lithium": "lithium",
    "ndfeb_magnets": "rare earth magnet", "advanced_logic": "advanced chips", "mature_logic": "legacy chips",
}


# ---- 1. policy calendar ------------------------------------------------------
def load_calendar(path: Path = DATA / "policy_calendar.csv") -> pd.DataFrame:
    cal = pd.read_csv(path, dtype=str, keep_default_na=False)
    cal["announced"] = pd.to_datetime(cal["announced"]).dt.date
    cal["suspended_until"] = pd.to_datetime(cal["suspended_until"].replace("", None)).dt.date
    return cal


def upcoming_lapses(cal: pd.DataFrame, exposed_materials: set[str], asof: date,
                    window_days: int = 90) -> pd.DataFrame:
    """Suspended controls that lapse within the window and touch an exposed material."""
    end = asof + timedelta(days=window_days)
    rows = cal[(cal["status"] == "suspended") & cal["suspended_until"].notna()].copy()
    rows = rows[(rows["suspended_until"] >= asof) & (rows["suspended_until"] <= end)]
    rows["exposed_materials"] = rows["materials"].map(
        lambda m: ";".join(sorted(set(m.split(";")) & exposed_materials)) if m != "*" else "all")
    rows = rows[rows["exposed_materials"] != ""]
    rows["days_until_lapse"] = rows["suspended_until"].map(lambda d: (d - asof).days)
    return rows[["event_id", "country", "suspended_until", "days_until_lapse", "exposed_materials",
                 "description", "source_url"]]


# ---- 2. news volume ----------------------------------------------------------
def _get_json(url: str, timeout: float) -> dict:
    req = Request(url, headers={"User-Agent": "supply-chain-resilience/1.0"})
    with urlopen(req, timeout=timeout) as resp:      # noqa: S310 (fixed https host)
        return json.loads(resp.read().decode("utf-8"))


def parse_gdelt_timeline(payload: dict, recent_days: int = 30) -> tuple[float, float]:
    """Return (recent 30-day article count, average 30-day count over the prior period)."""
    series = (payload.get("timeline") or [{}])[0].get("data", [])
    if not series:
        return 0.0, 0.0
    df = pd.DataFrame(series)
    df["date"] = pd.to_datetime(df["date"].str[:8], format="%Y%m%d")
    df = df.groupby("date")["value"].sum().sort_index()
    cutoff = df.index.max() - pd.Timedelta(days=recent_days)
    recent = float(df[df.index > cutoff].sum())
    prior = df[df.index <= cutoff]
    prior_days = max((prior.index.max() - prior.index.min()).days + 1, 1) if len(prior) else 0
    baseline = float(prior.sum()) / prior_days * recent_days if prior_days else 0.0
    return recent, baseline


def news_ratios(materials: list[str], timeout: float = 8.0, fetch=_get_json) -> pd.DataFrame:
    """Recent-vs-baseline news volume per material. Network errors are returned, not raised."""
    rows = []
    for m in materials:
        q = quote(f'"export control" China {MATERIAL_TERMS.get(m, m)}')
        try:
            recent, base = parse_gdelt_timeline(fetch(GDELT.format(q=q, span="210d"), timeout))
            ratio = recent / base if base > 0 else (np.nan if recent == 0 else 4.0)
            rows.append({"material": m, "recent_30d": recent, "baseline_30d": base, "ratio": ratio, "error": ""})
        except Exception as e:  # offline, blocked, rate-limited, bad payload
            rows.append({"material": m, "recent_30d": np.nan, "baseline_30d": np.nan, "ratio": np.nan,
                         "error": type(e).__name__})
    return pd.DataFrame(rows)


# ---- 3. external override ----------------------------------------------------
def load_external(path: Path = DATA / "external_signal.json") -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text())


# ---- combine -----------------------------------------------------------------
def escalation_signal(exposed_materials: set[str], base_p: dict[str, float], asof: date | None = None,
                      use_news: bool = True, window_days: int = 90, cap: float = 3.0,
                      fetch=_get_json, external_path: Path = DATA / "external_signal.json") -> dict:
    asof = asof or date.today()
    cal = load_calendar()
    lapses = upcoming_lapses(cal, exposed_materials, asof, window_days)
    external = load_external(external_path)
    news = news_ratios(sorted(exposed_materials & set(MATERIAL_TERMS)), fetch=fetch) if use_news else pd.DataFrame()

    out = {"asof": asof.isoformat(), "lapses": lapses, "news": news, "countries": {}}
    for c, p in base_p.items():
        cal_mult = 1 + 0.5 * int((lapses["country"] == c).sum())
        if c in external:
            other_mult, source = float(external[c]["multiplier"]), f"external ({external[c].get('source', 'file')})"
        elif use_news and len(news) and news["ratio"].notna().any():
            avg = float(news["ratio"].dropna().mean())
            other_mult, source = 1 + 0.25 * float(np.clip(avg - 1, 0, 4)), "news (GDELT)"
        else:
            other_mult, source = 1.0, "none (offline or disabled)"
        mult = float(min(cap, cal_mult * other_mult))
        out["countries"][c] = {"base_p_month": p, "calendar_multiplier": cal_mult, "other_multiplier": other_mult,
                               "other_source": source, "multiplier": mult, "adjusted_p_month": p * mult}
    return out


def write_external(country: str, multiplier: float, source: str, path: Path = DATA / "external_signal.json") -> None:
    """Helper for other systems (e.g. Sentinel) to publish a multiplier."""
    data = load_external(path)
    data[country] = {"multiplier": float(multiplier), "source": source, "asof": datetime.utcnow().date().isoformat()}
    path.write_text(json.dumps(data, indent=2))
