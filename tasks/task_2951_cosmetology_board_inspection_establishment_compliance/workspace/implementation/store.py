"""In-memory data store, logical clock and identity/timestamp minting.

Nothing is seeded here.  Every collection starts empty on every boot and all
state vanishes when the process exits.
"""
import itertools
import random
import string
import threading
import uuid
from datetime import datetime, timezone

LOCK = threading.RLock()

# ---------------------------------------------------------------- collections
establishments = {}
practitioners = {}
schools = {}
training_records = {}
workstations = {}
booth_rentals = {}
inspections = {}
violation_codes = {}
violation_findings = {}
citations = {}
hearings = {}
sanitation_logs = {}
infection_incidents = {}
ledger_entries = {}

COLLECTIONS = {
    "Establishment": establishments,
    "Practitioner": practitioners,
    "School": schools,
    "TrainingRecord": training_records,
    "Workstation": workstations,
    "BoothRental": booth_rentals,
    "Inspection": inspections,
    "ViolationCode": violation_codes,
    "ViolationFinding": violation_findings,
    "Citation": citations,
    "Hearing": hearings,
    "SanitationLog": sanitation_logs,
    "InfectionIncident": infection_incidents,
    "LedgerEntry": ledger_entries,
}

_seq = itertools.count(1)

# ------------------------------------------------------------- logical clock
CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = {"now": CLOCK_START}

# citation numbering
_citation_seq = itertools.count(1)


def now_utc():
    """Current value of the logical clock (never wall time)."""
    return _clock["now"]


def set_clock(value):
    _clock["now"] = value


def next_seq():
    return next(_seq)


def new_id():
    return str(uuid.uuid4())


def next_citation_number():
    return "CIT-%06d" % next(_citation_seq)


_ALNUM = string.ascii_uppercase + string.digits


def new_request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def iso(dt):
    """Render an aware datetime as an ISO-8601 UTC instant with 3 fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"


def record_stamp():
    """Stamp for created_at/updated_at, taken from the logical clock.

    PRD 2.4: "the server does not read wall-clock time"; the logical clock is
    therefore the only time source in the system, and its startup value is
    exactly 2026-08-01T00:00:00Z.  Rows recorded inside one clock tick share a
    stamp, so every ordering that names created_at breaks ties on the insertion
    sequence `_seq` to stay total.
    """
    return now_utc()


def bump(row):
    """Refresh updated_at and increment version by exactly 1."""
    if "version" in row:
        row["version"] = row["version"] + 1
    if "updated_at" in row:
        row["updated_at"] = record_stamp()
    return row


def make_row(with_common=True):
    row = {"id": new_id(), "created_at": record_stamp(), "_seq": next_seq()}
    if with_common:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    return row


def values(coll):
    return list(coll.values())
