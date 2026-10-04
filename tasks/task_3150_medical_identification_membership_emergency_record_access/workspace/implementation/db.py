"""In-memory data store. Wiped clean on every process boot; never seeded."""

# Stores keyed by id
members = {}
guardian_links = {}
record_items = {}
tickets = {}
contacts = {}
directives = {}
products = {}
orders = {}
responders = {}
access_events = {}
wandering_cases = {}
reminders = {}
disputes = {}
audit_events = {}

# Logical clock (ISO 8601 string, UTC). Server startup default per PRD §2.4.
_logical_clock = {"current": "2026-09-01T00:00:00Z"}


def logical_now():
    return _logical_clock["current"]


def set_logical_now(value):
    _logical_clock["current"] = value
