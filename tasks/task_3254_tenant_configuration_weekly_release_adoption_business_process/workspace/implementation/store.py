"""In-memory data store and logical clock for the tenant-config platform."""
import threading
from datetime import datetime, timezone

LOCK = threading.RLock()

# Logical clock: fixed startup default 2026-09-01T00:00:00Z (never wall-clock).
CLOCK_DEFAULT = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


def _fresh_state():
    return {
        "clock": CLOCK_DEFAULT,
        # Platform-wide current shared code version label.
        "code_version": "v1",
        # entity stores: id -> dict
        "tenants": {},
        "organization_units": {},
        "workers": {},
        "security_groups": {},
        "memberships": {},
        "definitions": {},
        "steps": {},
        "instances": {},
        "step_events": {},
        "release_trains": {},
        "feature_adoptions": {},
        "connectors": {},
        "runs": {},
        "refresh_jobs": {},
        "notifications": {},
    }


STATE = _fresh_state()


def reset_state():
    global STATE
    with LOCK:
        STATE = _fresh_state()
