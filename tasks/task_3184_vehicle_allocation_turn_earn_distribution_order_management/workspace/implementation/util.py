"""Shared entity helpers: timestamps, ISO weeks, sweeps, validation utils."""
import re
import uuid
from datetime import datetime, timedelta, timezone

from db import get_store, now_iso
from errors import validation

UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
WEEK_RE = re.compile(r"^(\d{4})-W(\d{2})$")
REGION_CODE_RE = re.compile(r"^[A-Z0-9-]{2,20}$")


def new_id() -> str:
    return str(uuid.uuid4())


def parse_dt(value):
    """Parse an ISO 8601 timestamp into an aware datetime."""
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        raise ValueError("not a timestamp")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def fmt_dt(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def now_dt() -> datetime:
    return parse_dt(now_iso())


def current_iso_week() -> str:
    iso = now_dt().isocalendar()
    return f"{iso[0]:04d}-W{iso[1]:02d}"


def week_monday(week_str: str) -> datetime:
    m = WEEK_RE.match(week_str or "")
    if not m:
        raise ValueError("bad ISO week")
    year, week = int(m.group(1)), int(m.group(2))
    return datetime.strptime(f"{year}-W{week:02d}-1", "%G-W%V-%u").replace(tzinfo=timezone.utc)


def current_week_monday() -> datetime:
    return week_monday(current_iso_week())


def new_entity(fields: dict) -> dict:
    """Attach the common fields (PRD §2.4)."""
    now = now_iso()
    fields.update({
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    })
    return fields


def bump(entity: dict) -> None:
    """Version bump + updated_at refresh (PRD §2.4)."""
    entity["version"] += 1
    entity["updated_at"] = now_iso()


def touch(entity: dict) -> None:
    entity["updated_at"] = now_iso()


# ---------------------------------------------------------------------------
# Field validation helpers (ERR_VALIDATION)
# ---------------------------------------------------------------------------

def req_field(body: dict, name: str):
    value = body.get(name)
    if value is None:
        raise validation(f"missing required field: {name}")
    return value


def req_str(body: dict, name: str) -> str:
    value = req_field(body, name)
    if not isinstance(value, str) or not value:
        raise validation(f"field {name} must be a non-empty string")
    return value


def opt_str(body: dict, name: str):
    value = body.get(name)
    if value is not None and not isinstance(value, str):
        raise validation(f"field {name} must be a string")
    return value


def req_bool(body: dict, name: str) -> bool:
    value = req_field(body, name)
    if not isinstance(value, bool):
        raise validation(f"field {name} must be a boolean")
    return value


def opt_bool(body: dict, name: str, default: bool) -> bool:
    value = body.get(name)
    if value is None:
        return default
    if not isinstance(value, bool):
        raise validation(f"field {name} must be a boolean")
    return value


def req_int(body: dict, name: str, minimum=None, maximum=None) -> int:
    value = req_field(body, name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise validation(f"field {name} must be an integer")
    if minimum is not None and value < minimum:
        raise validation(f"field {name} below minimum {minimum}")
    if maximum is not None and value > maximum:
        raise validation(f"field {name} above maximum {maximum}")
    return value


def opt_int(body: dict, name: str, default=None, minimum=None, maximum=None):
    value = body.get(name)
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise validation(f"field {name} must be an integer")
    if minimum is not None and value < minimum:
        raise validation(f"field {name} below minimum {minimum}")
    if maximum is not None and value > maximum:
        raise validation(f"field {name} above maximum {maximum}")
    return value


def req_enum(body: dict, name: str, allowed) -> str:
    value = req_str(body, name)
    if value not in allowed:
        raise validation(f"field {name} must be one of {sorted(allowed)}")
    return value


def req_ts(body: dict, name: str) -> str:
    value = req_str(body, name)
    try:
        parse_dt(value)
    except (ValueError, TypeError):
        raise validation(f"field {name} must be an ISO 8601 timestamp")
    return value


def opt_ts(body: dict, name: str):
    value = body.get(name)
    if value is None:
        return None
    return req_ts(body, name)


def req_week(body: dict, name: str) -> str:
    value = req_str(body, name)
    if not WEEK_RE.match(value):
        raise validation(f"field {name} must be an ISO week YYYY-Www")
    try:
        week_monday(value)
    except ValueError:
        raise validation(f"field {name} must be a valid ISO week")
    return value


# ---------------------------------------------------------------------------
# Lazy sweeps (PRD §2.9): evaluated on read against the logical clock.
# ---------------------------------------------------------------------------

def sweep_restriction(restriction: dict) -> None:
    if restriction["status"] == "ACTIVE":
        eff_to = restriction.get("effective_to")
        if eff_to is not None and now_dt() >= parse_dt(eff_to):
            restriction["status"] = "EXPIRED"
            bump(restriction)


def sweep_all_restrictions() -> None:
    for r in get_store("commodity_restrictions").values():
        sweep_restriction(r)


def sweep_trade(trade: dict) -> None:
    if trade["state"] in ("PROPOSED", "COUNTERED", "ACCEPTED"):
        if now_dt() >= parse_dt(trade["expires_at"]):
            trade["state"] = "EXPIRED"
            bump(trade)


def sweep_all_trades() -> None:
    for t in get_store("dealer_trades").values():
        sweep_trade(t)
