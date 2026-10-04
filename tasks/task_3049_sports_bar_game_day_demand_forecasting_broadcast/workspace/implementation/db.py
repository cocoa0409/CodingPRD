"""In-memory store and logical clock. Store starts empty on every boot."""
from datetime import datetime, timezone

# Entity stores, keyed by id
venues = {}
events = {}
licenses = {}
zones = {}
screen_assignments = {}
guests = {}
waitlist_entries = {}
checks = {}
order_lines = {}
promo_rules = {}
staffing_plans = {}
shifts = {}
trivia_sessions = {}
trivia_entries = {}
fantasy_contests = {}
fantasy_entries = {}
ppv_events = {}

# Logical clock: starts at 2026-09-01T00:00:00Z; never falls back to wall clock.
_current_utc = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


def now():
    return _current_utc


def set_now(dt):
    global _current_utc
    _current_utc = dt
    return _current_utc
