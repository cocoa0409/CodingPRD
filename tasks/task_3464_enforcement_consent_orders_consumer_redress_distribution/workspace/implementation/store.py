"""In-memory data store, logical clock, and the automatic lifecycle sweep.

Storage is dicts keyed by id; the store starts EMPTY on every boot (no seeding).
The logical clock starts at exactly 2026-09-01T00:00:00Z and moves only via
POST /_clock/set_current_utc.
"""
import threading
import uuid

from timeutil import parse_iso, fmt_iso, seconds

INITIAL_CLOCK_RAW = "2026-09-01T00:00:00Z"


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.seq = 0
        self.clock_raw = INITIAL_CLOCK_RAW
        self.clock_dt = parse_iso(INITIAL_CLOCK_RAW)
        self.subject_companies = {}
        self.investigations = {}
        self.cids = {}
        self.consent_orders = {}
        self.comment_periods = {}
        self.compliance_reports = {}
        self.violation_penalties = {}
        self.judgments = {}
        self.redress_funds = {}
        self.claimants = {}
        self.claims = {}
        self.refund_checks = {}


db = Store()


def new_id():
    return str(uuid.uuid4())


def now_dt():
    return db.clock_dt


def now_str():
    return fmt_iso(db.clock_dt)


def next_seq():
    db.seq += 1
    return db.seq


def stamp_new(entity):
    """Attach the common system fields to a freshly created entity."""
    ts = now_str()
    entity["id"] = new_id()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    entity["_seq"] = next_seq()
    return entity


def touch(entity):
    """Every mutation — direct or cascaded — bumps version and updated_at (PRD §2.10)."""
    entity["version"] = int(entity.get("version", 1)) + 1
    entity["updated_at"] = now_str()


def public(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def sweep():
    """Automatic transitions fired on every clock advance (PRD §2.5):
    1. OPEN comment periods close at/after closes_at (boundary inclusive).
    2. ISSUED refund checks go STALE at/after stale_after (boundary inclusive).
    3. IN_MONITORING orders EXPIRE only strictly past monitoring_ends_at.
    """
    now = seconds(db.clock_dt)
    for period in list(db.comment_periods.values()):
        if period["status"] == "OPEN" and seconds(parse_iso(period["closes_at"])) <= now:
            period["status"] = "CLOSED"
            touch(period)
    for check in list(db.refund_checks.values()):
        if check["status"] == "ISSUED" and seconds(parse_iso(check["stale_after"])) <= now:
            check["status"] = "STALE"
            touch(check)
    for order in list(db.consent_orders.values()):
        if (order["status"] == "IN_MONITORING" and order.get("monitoring_ends_at")
                and now > seconds(parse_iso(order["monitoring_ends_at"]))):
            order["status"] = "EXPIRED"
            touch(order)
