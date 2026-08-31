"""In-memory data store and the logical clock.

Nothing is seeded here: every dict starts empty on every boot and every row is
created by a client through a declared endpoint.
"""
import datetime
import threading
import uuid

LOCK = threading.RLock()

# ---------------------------------------------------------------------------
# Collections -- keyed by row id.
# ---------------------------------------------------------------------------
employers = {}
plans = {}
vendors = {}
isas = {}
participants = {}
ua_notices = {}
eligibility_determinations = {}
vendor_accounts = {}
contribution_elections = {}
remittance_batches = {}
remittance_corrections = {}
participant_requests = {}
transfer_exchange_requests = {}

ALL_COLLECTIONS = [
    employers, plans, vendors, isas, participants, ua_notices,
    eligibility_determinations, vendor_accounts, contribution_elections,
    remittance_batches, remittance_corrections, participant_requests,
    transfer_exchange_requests,
]

# ---------------------------------------------------------------------------
# Logical clock -- 2026-08-01T00:00:00Z at boot, never wall-clock time.
# ---------------------------------------------------------------------------
CLOCK_EPOCH = datetime.datetime(2026, 8, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)
_clock = {"now": CLOCK_EPOCH}


def now():
    return _clock["now"]


def set_clock(dt):
    previous = _clock["now"]
    _clock["now"] = dt
    return previous


def today():
    return _clock["now"].date()


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(datetime.timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_ts():
    return fmt_ts(_clock["now"])


def new_id():
    return str(uuid.uuid4())


def common_fields():
    ts = now_ts()
    return {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1,
            "_seq": next_seq()}


def bare_fields():
    """Common fields for an immutable row (id + created_at only)."""
    return {"id": new_id(), "created_at": now_ts(), "_seq": next_seq()}


def touch(row):
    """Record a mutation of a row: refresh updated_at and bump version by 1."""
    row["updated_at"] = now_ts()
    row["version"] = row.get("version", 1) + 1
    return row


_seq = {"n": 0}


def next_seq():
    _seq["n"] += 1
    return _seq["n"]


def reset():
    for coll in ALL_COLLECTIONS:
        coll.clear()
    _clock["now"] = CLOCK_EPOCH
    _seq["n"] = 0


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------
def rows(coll):
    return sorted(coll.values(), key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)))


def accounts_of(participant_id, status=None):
    out = []
    for va in rows(vendor_accounts):
        if va["participant_id"] != participant_id:
            continue
        if status is not None and va["status"] != status:
            continue
        out.append(va)
    return out


def elections_of(participant_id):
    return [e for e in rows(contribution_elections) if e["participant_id"] == participant_id]


def notices_of(plan_id):
    return [n for n in rows(ua_notices) if n["plan_id"] == plan_id]


def corrections_of(batch_id):
    return [c for c in rows(remittance_corrections) if c["remittance_batch_id"] == batch_id]


def isas_for(plan_id, vendor_id):
    return [a for a in rows(isas) if a["plan_id"] == plan_id and a["vendor_id"] == vendor_id]


def latest_determination(plan_id, participant_id):
    live = [d for d in rows(eligibility_determinations)
            if d["plan_id"] == plan_id and d["participant_id"] == participant_id
            and not d["superseded"]]
    return live[-1] if live else None
