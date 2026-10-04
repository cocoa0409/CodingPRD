"""Entity serialisation.

Internal bookkeeping keys start with an underscore and are stripped from every
response body.  Datetime values are rendered as ISO 8601 UTC with exactly three
fractional digits (PRD §2.7).
"""

from datetime import datetime

from core import fmt


def _clean(value):
    if isinstance(value, datetime):
        return fmt(value)
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if isinstance(value, set):
        return sorted(_clean(v) for v in value)
    return value


def serialize(entity):
    if entity is None:
        return None
    out = {}
    for key, value in entity.items():
        if key.startswith("_"):
            continue
        if value is None and key in ("updated_at", "version"):
            continue
        out[key] = _clean(value)
    return out


def serialize_many(entities):
    return [serialize(e) for e in entities]