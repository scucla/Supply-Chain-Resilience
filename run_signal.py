"""Print the live risk signal, or publish a multiplier for the model to use.

    python run_signal.py                         # show today's signal (calendar + news)
    python run_signal.py --asof 2026-11-05       # as of a given date
    python run_signal.py --publish CHN 1.8 --source sentinel
                                                 # write data/external_signal.json (how Sentinel plugs in)
"""
import argparse
from datetime import date

from src import signals

EXPOSED = {"gallium", "germanium", "graphite", "lithium", "ndfeb_magnets", "advanced_logic", "mature_logic",
           "copper", "aluminum", "carbon_fiber"}

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--asof", type=date.fromisoformat, default=None)
    ap.add_argument("--no-news", action="store_true")
    ap.add_argument("--publish", nargs=2, metavar=("COUNTRY", "MULTIPLIER"))
    ap.add_argument("--source", default="manual")
    a = ap.parse_args()
    if a.publish:
        signals.write_external(a.publish[0], float(a.publish[1]), a.source)
        print(f"Wrote data/external_signal.json: {a.publish[0]} x{float(a.publish[1])} ({a.source})")
    s = signals.escalation_signal(EXPOSED, {"CHN": 0.02}, asof=a.asof, use_news=not a.no_news)
    print(f"As of {s['asof']}")
    print(s["lapses"].drop(columns=["description", "source_url"]).to_string(index=False) or "No lapses in window")
    if len(s["news"]):
        print(s["news"].round(2).to_string(index=False))
    for c, v in s["countries"].items():
        print(f"{c}: {v['base_p_month']:.1%}/month x {v['multiplier']:.2f} = {v['adjusted_p_month']:.1%}/month "
              f"(calendar x{v['calendar_multiplier']}, {v['other_source']} x{v['other_multiplier']:.2f})")
