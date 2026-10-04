"""In-memory data store and logical clock."""
from datetime import datetime, timedelta, timezone

# Logical clock (PRD 2.4): starts exactly at 2026-09-01T00:00:00Z, never wall clock.
CLOCK = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


def now():
    return CLOCK


def set_clock(dt):
    global CLOCK
    CLOCK = dt


def new_id():
    import uuid
    return str(uuid.uuid4())


# Entity tables: dict id -> dict row.
DB = {
    "smart_accounts": {},
    "partner_orgs": {},
    "partner_delegations": {},
    "virtual_accounts": {},
    "license_pools": {},
    "devices": {},
    "assignments": {},
    "usage_reports": {},
    "compliance_events": {},
    "milestones": {},
    "service_contracts": {},
    "contract_coverages": {},
    "rma_cases": {},
    "transfer_requests": {},
}
