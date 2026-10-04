"""In-memory store and the logical clock. Empty on every boot; no seeding."""
from datetime import datetime, timezone

from constants import CLOCK_DEFAULT_ISO


def _parse_default(iso):
    return datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


# The single logical clock; never wall-clock.
_now = _parse_default(CLOCK_DEFAULT_ISO)

# Insertion-order tiebreaker for created_at sorting.
_seq = 0

# Flat collections keyed by id.
gpas = {}          # GroupPricingAgreement
clinics = {}       # Clinic
agreements = {}    # PlacementAgreement
analyzers = {}     # Analyzer
orders = {}        # ReagentOrder
periods = {}       # CommitmentPeriod
test_orders = {}   # LabTestOrder
results = {}       # LabResult (keyed by id; 1:1 with test_order_id)
cases = {}         # ServiceCase


def now():
    return _now


def set_now(dt):
    global _now
    _now = dt


def next_seq():
    global _seq
    _seq += 1
    return _seq
