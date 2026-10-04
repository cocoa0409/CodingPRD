import os

STORES = [
    "agencies", "policies", "plans", "officers", "devices", "recordings",
    "cases", "links", "redaction_jobs", "share_grants", "legal_holds",
    "audit_log", "custody_events",
]

db = {}

_CLOCK_DEFAULT = "2026-09-01T00:00:00Z"


def reset():
    for name in STORES:
        db[name] = {}
    db["_clock"] = _CLOCK_DEFAULT


reset()


def collection(name):
    return db[name]


def get_clock():
    return db["_clock"]


def set_clock(value):
    db["_clock"] = value


def use_wallclock():
    return os.environ.get("PRD_BENCH_WALLCLOCK", "").lower() in ("1", "true", "yes")
