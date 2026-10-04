"""Record -> JSON rendering."""

from decimal import Decimal

from db import dec_to_json


def render(record):
    """Shallow-copy a stored record, converting Decimals for JSON."""
    if record is None:
        return None
    if isinstance(record, list):
        return [render(item) for item in record]
    out = {}
    for key, value in dict(record).items():
        out[key] = _render_value(value)
    return out


def _render_value(value):
    if isinstance(value, Decimal):
        return dec_to_json(value)
    if isinstance(value, dict):
        return {key: _render_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_render_value(item) for item in value]
    return value


def render_many(records):
    return [render(record) for record in records]


def render_payload(payload):
    """Render an arbitrary computed-read payload (Decimals -> JSON numbers)."""
    return _render_value(payload)


def sorted_by_created(records, newest_first=False):
    ordered = sorted(records, key=lambda item: (item.get("created_at") or "", item.get("id") or ""))
    if newest_first:
        ordered.reverse()
    return ordered