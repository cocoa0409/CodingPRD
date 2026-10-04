import threading
from datetime import datetime, timezone

_lock = threading.Lock()

STORES = {
    "laboratories": {},
    "inspector_profiles": {},
    "enrollments": {},
    "sections": {},
    "checklist_editions": {},
    "pt_subscriptions": {},
    "pt_shipments": {},
    "pt_results": {},
    "pt_investigations": {},
    "inspection_cycles": {},
    "team_assignments": {},
    "inspection_findings": {},
    "personnel_records": {},
    "competency_assessments": {},
    "method_validations": {},
}

# Logical clock: starts exactly at 2026-09-01T00:00:00Z; never falls back
# to wall-clock time.
CLOCK = {"now": datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)}

# Sequence counter used to break ties between resources created at the
# same logical instant, keeping created_at ordering deterministic.
SEQ = {"n": 0}


def lock():
    return _lock


def next_seq():
    SEQ["n"] += 1
    return SEQ["n"]


def now():
    return CLOCK["now"]
