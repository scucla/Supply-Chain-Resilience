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

3. Daily refresh (optional) - scripts/refresh_signal.py, run every day by a GitHub
   Actions job, combines news volume with United States export-control rule-making
   (Federal Register, Bureau of Industry and Security) and writes
   data/external_signal.json plus a row in data/signal_history.csv:
       {"CHN": {"multiplier": 1.3, "source": "daily refresh", "asof": "2026-11-05"}}
   If the file is fresh (under 14 days old) it replaces the live news component.
   Any other system can publish a multiplier the same way (write_external).

multiplier = min(cap, calendar x news_or_external)      (cap = 3 by default)

These coefficients are simple, documented choices, not fitted values: the point
is that the plan reacts to a dated, checkable signal instead of a fixed number.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd

DATA = Path(__file__).resolve().parent.parent / "data"
FEDREG = ("https://www.federalregister.gov/api/v1/documents.json?per_page=200&order=newest"
          "&conditions%5Bagencies%5D%5B%5D=industry-and-security-bureau"
          "&conditions%5Bpublication_date%5D%5Bgte%5D={since}"
          "&fields%5B%5D=title&fields%5B%5D=publication_date&fields%5B%5D=html_url&fields%5B%5D=type"
          "&fields%5B%5D=abstract")
FEDREG_TERMS = ("china", "chinese", "semiconductor", "entity list", "advanced computing", "integrated circuit",
                "critical mineral", "gallium", "germanium", "rare earth", "graphite", "hong kong", "macau")
STALE_DAYS = 14
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
        fresh = c in external and (asof - date.fromisoformat(external[c].get("asof", "1970-01-01"))).days <= STALE_DAYS
        if fresh:
            other_mult = float(external[c]["multiplier"])
            source = f"{external[c].get('source', 'file')}, {external[c].get('asof')}"
        elif use_news and len(news) and news["ratio"].notna().any():
            avg = float(news["ratio"].dropna().mean())
            other_mult, source = 1 + 0.25 * float(np.clip(avg - 1, 0, 4)), "news (GDELT)"
        else:
            other_mult, source = 1.0, "none (offline or disabled)"
        mult = float(min(cap, cal_mult * other_mult))
        out["countries"][c] = {"base_p_month": p, "calendar_multiplier": cal_mult, "other_multiplier": other_mult,
                               "other_source": source, "multiplier": mult, "adjusted_p_month": p * mult}
    return out


def write_external(country: str, multiplier: float, source: str, path: Path = DATA / "external_signal.json",
                   asof: date | None = None) -> None:
    """Publish a multiplier (used by the daily refresh; any other system can call it too)."""
    data = load_external(path)
    data[country] = {"multiplier": float(multiplier), "source": source,
                     "asof": (asof or datetime.now(timezone.utc).date()).isoformat()}
    path.write_text(json.dumps(data, indent=2))



# ---- United States rule-making (Federal Register) ---------------------------
def parse_fedreg(payload: dict, asof: date, recent_days: int = 30) -> tuple[pd.DataFrame, float, float]:
    """China/chip-related Bureau of Industry and Security documents: (table, recent count, baseline per 30 days)."""
    docs = pd.DataFrame(payload.get("results") or [])
    if docs.empty:
        return docs, 0.0, 0.0
    text = (docs["title"].fillna("") + " " + docs.get("abstract", pd.Series("", index=docs.index)).fillna("")).str.lower()
    docs = docs[text.str.contains("|".join(FEDREG_TERMS), regex=True)].copy()
    docs["publication_date"] = pd.to_datetime(docs["publication_date"]).dt.date
    cutoff = asof - timedelta(days=recent_days)
    recent = float((docs["publication_date"] > cutoff).sum())
    prior = docs[docs["publication_date"] <= cutoff]
    span = (cutoff - min(prior["publication_date"].min(), cutoff - timedelta(days=180))).days if len(prior) else 180
    baseline = len(prior) / max(span, 1) * recent_days
    return docs, recent, baseline


def refresh(asof: date | None = None, fetch=_get_json, materials: set[str] | None = None,
            out_json: Path = DATA / "external_signal.json", history: Path = DATA / "signal_history.csv") -> dict:
    """Daily job: combine news and rule-making into one multiplier and record it.

    other = 1 + 0.25 x clip(news ratio - 1, 0, 4) + 0.25 x clip(rule-making ratio - 1, 0, 4), capped at 2.5
    (calendar effects are added later by escalation_signal, so they are not double counted here).
    """
    asof = asof or date.today()
    materials = materials or {"gallium", "germanium", "graphite", "lithium", "ndfeb_magnets", "advanced_logic"}
    news = news_ratios(sorted(materials), fetch=fetch)
    news_ratio = float(news["ratio"].dropna().mean()) if news["ratio"].notna().any() else np.nan
    try:
        docs, fr_recent, fr_base = parse_fedreg(fetch(FEDREG.format(since=(asof - timedelta(days=210)).isoformat()),
                                                      10.0), asof)
        fr_ratio = fr_recent / fr_base if fr_base > 0 else (1.0 if fr_recent == 0 else 4.0)
        fr_error = ""
    except Exception as e:
        docs, fr_recent, fr_base, fr_ratio, fr_error = pd.DataFrame(), np.nan, np.nan, np.nan, type(e).__name__

    parts = [0.25 * float(np.clip(x - 1, 0, 4)) for x in (news_ratio, fr_ratio) if not np.isnan(x)]
    ok = bool(parts)
    other = float(min(2.5, 1 + sum(parts))) if ok else 1.0
    cal = escalation_signal(materials, {"CHN": 0.02}, asof=asof, use_news=False,
                            external_path=Path("/nonexistent"))["countries"]["CHN"]
    row = {"date": asof.isoformat(), "news_ratio": news_ratio, "rulemaking_recent_30d": fr_recent,
           "rulemaking_baseline_30d": fr_base, "rulemaking_ratio": fr_ratio, "news_and_rules_multiplier": other,
           "calendar_multiplier": cal["calendar_multiplier"],
           "total_multiplier": min(3.0, other * cal["calendar_multiplier"]),
           "adjusted_p_month": 0.02 * min(3.0, other * cal["calendar_multiplier"]),
           "errors": ";".join(sorted(set(news["error"].replace("", np.nan).dropna()) | ({fr_error} - {""})))}
    if ok:  # never overwrite a good signal with a failed fetch
        write_external("CHN", other, "daily refresh (news + Federal Register)", path=out_json, asof=asof)
    hist = pd.read_csv(history) if history.exists() else pd.DataFrame()
    hist = pd.concat([hist[hist.get("date", pd.Series(dtype=str)) != row["date"]] if len(hist) else hist,
                      pd.DataFrame([row])], ignore_index=True)
    hist.to_csv(history, index=False)
    return {"row": row, "news": news, "rules": docs}
