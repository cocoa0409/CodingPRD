# =============================================================================
# In-memory data store + logical clock
# =============================================================================
import uuid
import threading

_LOCK = threading.RLock()

# Logical clock: startup default is exactly 2026-09-01T00:00:00Z and never
# falls back to wall-clock.
_CLOCK = {"current_utc": "2026-09-01T00:00:00Z"}

# Entity tables: id -> row (dict). The store starts empty on every boot.
cardholders = {}
devices = {}
issuers = {}
issuer_agreements = {}
merchant_programs = {}
card_accounts = {}
card_artifacts = {}
provisioning_sessions = {}
payment_tokens = {}
authorizations = {}
disputes = {}
transit_operators = {}
merchant_card_programs = {}
transit_allowlist = {}
token_events = {}

# Per-agreement fee ledger (accrual variant): agreement_id -> fee_cents
fee_ledgers = {}

# Monotonic sequence for deterministic created-order sorting when many rows
# share one logical-clock timestamp (the clock only moves when tests set it).
_seq = {"n": 0}


def next_seq():
    _seq["n"] += 1
    return _seq["n"]


def lock():
    return _LOCK


def new_id():
    return str(uuid.uuid4())


def get_clock():
    return _CLOCK["current_utc"]


def set_clock(value):
    _CLOCK["current_utc"] = value


def touch(row):
    """Refresh updated_at and bump version on a mutated row (no-op for rows
    without common fields: TransitAllowlist, TokenEvent)."""
    if "version" in row:
        row["version"] += 1
    if "updated_at" in row:
        row["updated_at"] = get_clock()
    row["_seq"] = next_seq()
