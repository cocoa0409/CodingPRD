"""Entity -> JSON dict. Internal keys (prefixed '_') are never serialized;
datetimes are formatted ISO 8601 UTC with three fractional digits."""

from datetime import datetime

from timeutil import fmt_dt


def serialize(row):
    out = {}
    for k, v in row.items():
        if k.startswith("_"):
            continue
        if isinstance(v, datetime):
            out[k] = fmt_dt(v)
        elif isinstance(v, list):
            out[k] = [_serialize_value(x) for x in v]
        else:
            out[k] = v
    return out


def _serialize_value(v):
    if isinstance(v, datetime):
        return fmt_dt(v)
    if isinstance(v, dict):
        return {k: _serialize_value(x) for k, x in v.items() if not k.startswith("_")}
    return v


def serialize_all(rows):
    return [serialize(r) for r in rows]
