"""Serialization of stored rows into JSON-safe response objects.

Stored rows hold real `datetime` objects and `Decimal` values; responses must
carry ISO 8601 UTC strings with three fractional digits (PRD.md 2.5) and plain
JSON numbers.  Internal bookkeeping keys (leading underscore) are never
exposed.
"""

from datetime import datetime
from decimal import Decimal

from response import _render_ts


def scalar(value):
    if isinstance(value, datetime):
        return _render_ts(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: scalar(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, (list, tuple)):
        return [scalar(v) for v in value]
    return value


def serialize(record):
    if record is None:
        return None
    return {k: scalar(v) for k, v in record.items() if not k.startswith("_")}


def serialize_many(rows):
    return [serialize(r) for r in rows]


def datetimes(record, *names):
    """Convenience accessor used by the calculation layer."""
    return tuple(record.get(n) for n in names)