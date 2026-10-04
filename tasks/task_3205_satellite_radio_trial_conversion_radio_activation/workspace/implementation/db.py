"""In-memory store. Empty at boot; tests construct all state via API."""
import threading

# Global logical clock (seconds since epoch as float). Default: 2026-09-01T00:00:00Z.
EPOCH_DEFAULT = 1788220800.0  # 2026-09-01T00:00:00Z

lock = threading.RLock()

now_seconds = EPOCH_DEFAULT

automakers = {}
dealers = {}
customers = {}
vehicles = {}
radios = {}
package_tiers = {}
plans = {}
subscriptions = {}
campaigns = {}
offer_steps = {}
redemptions = {}
signal_commands = {}
ledger_entries = {}
disclosures = {}


def set_now(ts):
    global now_seconds
    now_seconds = ts


def get_now():
    return now_seconds


_seq = 0


def next_seq():
    """Monotone insertion sequence for FIFO tie-breaks among records created
    within the same logical instant."""
    global _seq
    _seq += 1
    return _seq
