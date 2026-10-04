"""List-query helpers: pagination (PRD §2.3) and deterministic ordering (PRD §2.4)."""

from clock import parse_iso
from errors import invalid_request


def pagination(args):
    """Read the offset-based pagination pair from the query string.

    `limit` defaults to 10 and must lie in [1, 100]; `offset` defaults to 0.
    A value outside the band is a malformed request.
    """
    limit = _int_arg(args, "limit", 10)
    offset = _int_arg(args, "offset", 0)
    if limit < 1 or limit > 100:
        raise invalid_request("limit must be between 1 and 100 inclusive.")
    if offset < 0:
        raise invalid_request("offset must be >= 0.")
    return limit, offset


def _int_arg(args, name, default):
    raw = args.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise invalid_request("Query parameter %s must be an integer." % name)


def bool_arg(args, name, default=None):
    raw = args.get(name)
    if raw is None or raw == "":
        return default
    lowered = raw.strip().lower()
    if lowered in ("true", "1", "yes"):
        return True
    if lowered in ("false", "0", "no"):
        return False
    raise invalid_request("Query parameter %s must be a boolean." % name)


def filter_arg(args, name, allowed=None):
    raw = args.get(name)
    if raw is None or raw == "":
        return None
    raw = raw.strip()
    if allowed is not None and raw not in allowed:
        raise invalid_request(
            "Query parameter %s must be one of: %s." % (name, ", ".join(sorted(allowed)))
        )
    return raw


def sort_rows(rows, key_name):
    """Sort by an instant ascending.

    A collection is ordered by created_at ascending.  The tie-break is the
    server-side creation sequence, never the id, so rows minted inside the same
    instant still order deterministically.
    """
    return sorted(rows, key=lambda row: (_instant(row.get(key_name)), row.get("_seq", 0)))


def _instant(value):
    if value is None:
        return 0.0
    parsed = parse_iso(value)
    if parsed is None:
        return 0.0
    return parsed.timestamp()


def paginate(rows, limit, offset):
    return rows[offset:offset + limit]