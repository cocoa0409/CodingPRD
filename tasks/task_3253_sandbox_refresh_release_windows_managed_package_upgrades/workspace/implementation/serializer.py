"""Response serialisation.

All datetimes leave as ISO 8601 UTC with three fractional digits (PRD §2.11).
Rows are stored with datetime objects for the fields that participate in
arithmetic and with strings for plain recorded timestamps; both are normalised
here.  Internal bookkeeping keys (the minting sequence, the clock-dependent
projection caches and the diagnostic ``supersedes_job_id`` pointer) are dropped
from every response body.
"""

import clock

DATETIME_FIELDS = (
    "created_at",
    "updated_at",
    "last_refresh_at",
    "next_refresh_at",
    "installed_at",
    "refreshed_at",
    "validated_at",
    "approved_at",
    "archived_at",
    "closed_at",
)

INTERNAL_FIELDS = (
    "_seq",
    "_total_cache",
    "_layer_total_cache",
)


def serialize(row):
    if row is None:
        return None
    out = {}
    for key, value in row.items():
        if key in INTERNAL_FIELDS:
            continue
        if key in DATETIME_FIELDS:
            out[key] = clock.iso(value) if value is not None else None
        else:
            out[key] = value
    return out


def serialize_all(rows):
    return [serialize(row) for row in rows]