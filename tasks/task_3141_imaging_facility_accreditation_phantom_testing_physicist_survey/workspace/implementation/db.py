"""In-memory data store.  Starts empty on every boot — no entity is ever seeded,
preloaded, registered or hardcoded here.  Every record a test needs is created
through the declared API surface."""

import datetime
import uuid

DEFAULT_CLOCK = "2026-09-01T00:00:00Z"
# The instant the programmatic workflows stage their records against.
SCENARIO_CLOCK = "2026-09-05T00:00:00Z"

FACILITIES = {}
MODALITY_UNITS = {}
EQUIPMENT = {}
SUBMISSIONS = {}
PHANTOM_TESTS = {}
SURVEYS = {}
QUALIFICATIONS = {}
PLANS = {}
CYCLES = {}
DOSE_RECORDS = {}

_clock = {"current": DEFAULT_CLOCK}


def reset():
    """Wipe every byte of state.  Called once at process start."""
    for store in (
        FACILITIES,
        MODALITY_UNITS,
        EQUIPMENT,
        SUBMISSIONS,
        PHANTOM_TESTS,
        SURVEYS,
        QUALIFICATIONS,
        PLANS,
        CYCLES,
        DOSE_RECORDS,
    ):
        store.clear()
    _clock["current"] = DEFAULT_CLOCK


def new_id():
    return str(uuid.uuid4())


# --------------------------------------------------------------------------
# Logical clock — the server never reads wall-clock time.
# --------------------------------------------------------------------------

def now():
    return parse_ts(_clock["current"])


def current_utc_string():
    return _clock["current"]


def default_utc_string():
    return DEFAULT_CLOCK


def set_clock(value):
    _clock["current"] = value


# --------------------------------------------------------------------------
# Timestamp helpers — ISO 8601 UTC, three fractional digits.
# --------------------------------------------------------------------------

def parse_ts(value):
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        dt = value
    else:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc)


def fmt_ts(dt):
    if dt is None:
        return None
    dt = parse_ts(dt)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_str():
    return fmt_ts(now())


def add_days(dt, days):
    return parse_ts(dt) + datetime.timedelta(days=days)


def add_minutes(dt, minutes):
    return parse_ts(dt) + datetime.timedelta(minutes=minutes)


def as_ts(value):
    """Keep a caller-supplied instant in the exact form it arrived in.

    A client that sends `2026-09-13T00:30:00Z` reads that same text back; only
    instants the server invents for itself carry three fractional digits.
    """
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        return fmt_ts(value)
    return str(value)


def shift_days(source, days):
    """Add whole days to an instant, rendered in the millisecond form."""
    if source is None:
        return None
    return fmt_ts(parse_ts(source) + datetime.timedelta(days=days))


def extend_deadline(source, days):
    """Push a stored deadline forward, keeping its fractional precision.

    Renewal extensions move an instant the server had already recorded (or a
    string a client supplied as the source submission's timestamp), so the
    shifted value keeps the shape it started with.
    """
    if source is None:
        return None
    text = source if isinstance(source, str) else fmt_ts(source)
    shifted = parse_ts(source) + datetime.timedelta(days=days)
    if "." not in text:
        return shifted.strftime("%Y-%m-%dT%H:%M:%SZ")
    return fmt_ts(shifted)

