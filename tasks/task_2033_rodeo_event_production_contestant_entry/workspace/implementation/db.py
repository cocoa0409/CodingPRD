"""In-memory data store. The store starts empty on every boot; no seeding."""
import uuid
from datetime import datetime, timezone

DB = {
    "rodeos": {},
    "rodeo_events": {},
    "performances": {},
    "contestants": {},
    "stock_contracts": {},
    "stock_animals": {},
    "judges": {},
    "judge_assignments": {},
    "entries": {},
    "draw_assignments": {},
    "run_results": {},
    "payouts": {},
    "vet_reports": {},
    "ticket_orders": {},
}

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"


def _parse(text):
    t = text.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# The logical clock (PRD 2.4): starts at exactly DEFAULT_CLOCK and only moves
# via POST /api/_clock/set_current_utc. Never falls back to wall-clock time.
CLOCK = {"raw": DEFAULT_CLOCK, "dt": _parse(DEFAULT_CLOCK)}

_SEQ = [0]


def next_seq():
    _SEQ[0] += 1
    return _SEQ[0]


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """Wall-clock UTC timestamp, ISO 8601 with three fractional digits."""
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"
