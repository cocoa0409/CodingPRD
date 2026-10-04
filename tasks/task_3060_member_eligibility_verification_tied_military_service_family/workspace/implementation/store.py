import threading
from datetime import datetime, timezone

LOCK = threading.RLock()

_eligible_tables = [
    "eligibility_cases", "service_records", "evidence_docs", "members",
    "households", "addresses", "deployment_orders", "protection_claims",
    "product_offerings", "entitlements", "survivor_cases",
]

# tables: name -> { id -> row-dict }
T = {name: {} for name in _eligible_tables}
# per-table creation order (ids), used for created_at-asc stable sort
SEQ = {name: [] for name in _eligible_tables}

# logical clock: exact string -> "2026-09-01T00:00:00Z" before any call
LOGICAL_CLOCK = "2026-09-01T00:00:00Z"

# member number counter (first member -> 1)
MEMBER_NUMBER_COUNTER = [0]


def now_iso_ms():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def clock_date_str():
    return LOGICAL_CLOCK[:10]


def clock_now_dt():
    s = LOGICAL_CLOCK
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def clock_today_date():
    return clock_now_dt().date()


def insert_row(table, row):
    T[table][row["id"]] = row
    SEQ[table].append(row["id"])
    return row


def next_member_number():
    MEMBER_NUMBER_COUNTER[0] += 1
    return "%010d" % MEMBER_NUMBER_COUNTER[0]
