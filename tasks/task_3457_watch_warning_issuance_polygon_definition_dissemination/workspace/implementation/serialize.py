"""Entity serialization: drops internal `_`-prefixed fields, renders
datetimes as ISO 8601 UTC with three fractional digits, and injects the
computed `window_end` on products."""
from datetime import datetime
from decimal import Decimal

from calculations import window_end
from util import fmt_dt


def _ser_value(value):
    if isinstance(value, datetime):
        return fmt_dt(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, list):
        return [_ser_value(v) for v in value]
    if isinstance(value, dict):
        return {k: _ser_value(v) for k, v in value.items()}
    return value


def serialize(entity):
    out = {}
    for key, value in entity.items():
        if key.startswith("_"):
            continue
        out[key] = _ser_value(value)
    return out


def serialize_product(product):
    out = serialize(product)
    out["window_end"] = fmt_dt(window_end(product))
    return out
