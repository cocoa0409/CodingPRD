"""Output projection.

Stored records keep native datetimes so temporal arithmetic stays exact; the
wire format renders every datetime as an ISO 8601 UTC instant with three
fractional digits (PRD §2.2 / §2.6).
"""

from datetime import datetime

from clock import fmt_dt


def render(record):
    """Project one stored record onto the wire shape."""
    if record is None:
        return None
    out = {}
    for key, value in record.items():
        if isinstance(value, datetime):
            out[key] = fmt_dt(value)
        else:
            out[key] = value
    return out


def render_list(records):
    return [render(record) for record in records]