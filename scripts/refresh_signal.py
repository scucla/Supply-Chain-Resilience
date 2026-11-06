"""Daily risk-signal refresh. Run by .github/workflows/refresh-signal.yml (or by hand).

    python scripts/refresh_signal.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.signals import refresh  # noqa: E402

if __name__ == "__main__":
    out = refresh(pause=6.0)   # GDELT allows one request every 5 seconds
    row = out["row"]
    print(f"{row['date']}: news ratio {row['news_ratio']:.2f}, rule-making ratio {row['rulemaking_ratio']:.2f} "
          f"({row['rulemaking_recent_30d']:.0f} China/chip rules in 30 days), calendar x{row['calendar_multiplier']}, "
          f"total x{row['total_multiplier']:.2f} -> {row['adjusted_p_month']:.1%}/month"
          + (f"  [errors: {row['errors']}]" if row["errors"] else ""))
    print(out["news"].to_string(index=False))
    if len(out["rules"]):
        print(out["rules"][["publication_date", "title"]].head(10).to_string(index=False))
