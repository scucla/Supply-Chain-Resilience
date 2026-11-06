"""Load, validate and explode a multi-level bill of materials (BOM).

Key idea: each row stores `qty_per_parent` (how many of this part go into ONE of
its parent). The *extended* quantity is how many go into ONE finished system,
found by multiplying quantities along the path from the part up to the root.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def load_data(data_dir: Path = DATA_DIR) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    bom = pd.read_csv(data_dir / "bom.csv", dtype={"parent_id": "string", "key_material": "string"})
    materials = pd.read_csv(data_dir / "material_sources.csv")
    countries = pd.read_csv(data_dir / "country_risk.csv")
    bom["parent_id"] = bom["parent_id"].fillna("")
    bom["key_material"] = bom["key_material"].fillna("")
    validate_bom(bom, countries)
    return bom, materials, countries


def validate_bom(bom: pd.DataFrame, countries: pd.DataFrame) -> None:
    """Fail fast on the mistakes that silently break MRP math."""
    ids = set(bom["part_id"])
    if len(ids) != len(bom):
        raise ValueError("Duplicate part_id values in BOM")
    roots = bom[bom["parent_id"] == ""]
    if len(roots) != 1:
        raise ValueError(f"BOM must have exactly one root, found {len(roots)}")
    orphans = set(bom.loc[bom["parent_id"] != "", "parent_id"]) - ids
    if orphans:
        raise ValueError(f"Parents not found in BOM: {orphans}")
    unknown = set(bom["supplier_country"]) - set(countries["country"])
    if unknown:
        raise ValueError(f"Countries missing from country_risk.csv: {unknown}")
    # Cycle check: walking up from any node must reach the root.
    parent = dict(zip(bom["part_id"], bom["parent_id"]))
    for pid in ids:
        seen, cur = set(), pid
        while cur:
            if cur in seen:
                raise ValueError(f"Cycle detected at {pid}")
            seen.add(cur)
            cur = parent[cur]


def explode(bom: pd.DataFrame) -> pd.DataFrame:
    """Add `extended_qty` (units per finished system) and `level` (depth in tree)."""
    parent = dict(zip(bom["part_id"], bom["parent_id"]))
    qty = dict(zip(bom["part_id"], bom["qty_per_parent"]))

    ext, level = {}, {}
    for pid in bom["part_id"]:
        q, depth, cur = 1.0, 0, pid
        while cur:
            q *= qty[cur]
            cur = parent[cur]
            depth += 1
        ext[pid], level[pid] = q, depth - 1

    out = bom.copy()
    out["extended_qty"] = out["part_id"].map(ext)
    out["level"] = out["part_id"].map(level)
    # Direct buys = parts we purchase ourselves (parent is something we make).
    make_ids = set(out.loc[out["make_buy"] == "make", "part_id"])
    out["direct_buy"] = (out["make_buy"] == "buy") & out["parent_id"].isin(make_ids)
    return out


def purchased_parts(exploded: pd.DataFrame) -> pd.DataFrame:
    return exploded[exploded["make_buy"] == "buy"].copy()


def children_map(exploded: pd.DataFrame) -> dict[str, list[str]]:
    kids: dict[str, list[str]] = {}
    for pid, par in zip(exploded["part_id"], exploded["parent_id"]):
        if par:
            kids.setdefault(par, []).append(pid)
    return kids
