"""In-memory data store. Starts empty on every boot; no seeding ever."""
from datetime import datetime, timezone, timedelta

# Logical clock: starts at exactly 2026-09-01T00:00:00Z, never falls back to wall time.
clock = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

# Platform surge multiplier (default 1.0 = no surge).
surge_multiplier = 1.0

merchants = {}
stores = {}
policies = {}
overrides = {}
quotes = {}
orders = {}
couriers = {}
batches = {}
dispositions = {}
claims = {}
reports = {}
credits = {}
tracking_events = {}


def now():
    return clock


def set_clock(dt):
    global clock
    clock = dt


def set_surge(m):
    global surge_multiplier
    surge_multiplier = m
