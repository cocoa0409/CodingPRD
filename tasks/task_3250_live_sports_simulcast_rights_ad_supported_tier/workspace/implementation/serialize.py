"""Serialize stored entities (datetimes -> ISO strings) to wire format."""
import clock

_DT_FIELDS = {
    "term_start", "term_end", "scheduled_start", "scheduled_end", "live_start",
    "effective_start", "effective_end", "issued_at", "expires_at",
    "hold_expires_at", "confirmed_at", "flight_start", "flight_end",
    "served_at", "active_from", "available_from", "redeemed_at",
}

# Server-minted instants are emitted in the same whole-second ISO 8601 UTC
# form clients supply; three-fractional-digit formatting applies to the
# envelope's api_request_timestamp and entity created_at/updated_at.


def serialize(entity):
    out = {}
    for k, v in entity.items():
        if k in _DT_FIELDS and v is not None and not isinstance(v, str):
            # Entity data timestamps echo the whole-second ISO 8601 UTC form
            # used by clients and the logical clock; the three-fractional-digit
            # format (PRD §2.2/§2.4) applies to the meta envelope and
            # created_at/updated_at, which are not in _DT_FIELDS.
            out[k] = clock.iso_echo(v)
        else:
            out[k] = v
    return out


def serialize_list(entities):
    return [serialize(e) for e in entities]


def paginate(items, args):
    """Apply limit/offset with defaults; returns (page_items, limit, offset, total)."""
    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    total = len(items)
    return items[offset:offset + limit], limit, offset, total


def by_created(entities):
    return sorted(entities, key=lambda e: (e.get("created_at") or "", e.get("id") or ""))
