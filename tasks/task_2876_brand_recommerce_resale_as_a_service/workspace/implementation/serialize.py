"""Row-to-JSON projection.  Internal bookkeeping keys are never exposed."""

from datetime import datetime

import store
from store import fmt_ts


def aged_days(unit):
    listed_at = unit.get("listed_at")
    if listed_at is None:
        return 0
    elapsed = int((store.now() - listed_at).total_seconds())
    if elapsed <= 0:
        return 0
    return elapsed // 86400


def out(row):
    if row is None:
        return None
    data = {}
    for key, value in row.items():
        if key.startswith("_"):
            continue
        data[key] = fmt_ts(value) if isinstance(value, datetime) else value
    if row.get("_kind") == "resale_units":
        data["aged_days"] = aged_days(row)
    return data


def out_list(rows):
    return [out(row) for row in rows]
