"""JSON-safe rendering of stored records.

Records are written with plain ints / strings, but rate fields may still hold a
Decimal after an update, so every response is passed through `clean()` before
it leaves the process.  This module also installs a Flask JSON provider that
knows how to render Decimal, so no response can ever carry a non-JSON value.
"""
from decimal import Decimal

from flask.json.provider import DefaultJSONProvider

from store import public


class DecimalJSONProvider(DefaultJSONProvider):
    """Renders Decimal as an int when integral, else as a float."""

    @staticmethod
    def default(obj):
        if isinstance(obj, Decimal):
            if obj == obj.to_integral_value():
                return int(obj)
            return float(obj)
        return DefaultJSONProvider.default(obj)


def clean(value):
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    return value


def render(record):
    """A record ready for the response envelope."""
    return clean(public(record))