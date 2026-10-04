"""In-memory data store and logical clock.

Storage is process-local only: plain dicts keyed by entity id. No disk
persistence of any kind. The store starts empty on every boot.
"""
from datetime import datetime, timezone, timedelta
import threading

DEFAULT_CLOCK = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

_lock = threading.RLock()

# Monotonic insertion sequence: breaks "first-created" ties when the logical
# clock stamps two entities with the same timestamp.
_seq = 0


def next_seq():
    global _seq
    with _lock:
        _seq += 1
        return _seq

# Logical clock (datetime, tz-aware UTC). Never falls back to wall-clock.
_current_utc = DEFAULT_CLOCK


def now():
    with _lock:
        return _current_utc


def set_now(dt):
    global _current_utc
    with _lock:
        _current_utc = dt


def fmt(dt):
    """Format a datetime as ISO 8601 UTC with three fractional digits (Z)."""
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{dt.microsecond // 1000:03d}Z"


# Entity tables: id -> dict
payer_clients = {}
repricing_policies = {}
providers = {}
network_agreements = {}
medicare_fee_schedule = {}
ucr_rates = {}
claims = {}
claim_lines = {}
repricing_determinations = {}
negotiation_cases = {}
settlement_agreements = {}
open_negotiations = {}
idr_submissions = {}
provider_appeals = {}
claim_feed_batches = {}
fee_invoices = {}
transparency_reports = {}
