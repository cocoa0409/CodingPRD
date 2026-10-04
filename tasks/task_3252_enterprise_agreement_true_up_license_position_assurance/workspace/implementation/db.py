"""In-memory data store and logical clock. Starts completely empty."""
import datetime
import uuid

# Logical clock: fixed startup default, never wall-clock before first set.
DEFAULT_CLOCK = datetime.datetime(2026, 9, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)
_clock = DEFAULT_CLOCK


def get_clock():
    return _clock


def set_clock(to_iso8601):
    global _clock
    s = to_iso8601.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    _clock = dt.astimezone(datetime.timezone.utc)
    return _clock


def now_iso():
    """ISO 8601 UTC with three fractional digits, e.g. 2026-09-01T00:00:00.000Z"""
    dt = _clock.astimezone(datetime.timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % ms


def today():
    return _clock.astimezone(datetime.timezone.utc).date()


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + uuid.uuid4().hex[:24]


def parse_date(s):
    if not isinstance(s, str):
        raise ValueError("not a date string")
    return datetime.date.fromisoformat(s.strip()[:10])


# ------------------------- stores (keyed by id) -------------------------
organizations = {}
agreements = {}
products = {}
anniversaries = {}
entitlements = {}
deployments = {}
snapshots = {}
trueup_reports = {}
trueup_lines = {}
benefit_grants = {}
redemptions = {}
step_ups = {}
commitments = {}
consumption_events = {}
hosting_auths = {}
assessments = {}
