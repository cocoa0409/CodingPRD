"""In-memory data store and logical clock. State lives only in process memory;
start.sh re-invocation wipes everything (per-test-server isolation)."""
from datetime import datetime, timezone

# Logical clock: mandatory startup default per scaffold.
START_CLOCK = datetime(2026, 9, 1, tzinfo=timezone.utc)

current_clock = START_CLOCK


def now():
    return current_clock


def set_clock(dt):
    global current_clock
    current_clock = dt


# Entity stores: dict keyed by id. All start empty; nothing is seeded.
patrons = {}
credentials = {}
libraries = {}
works = {}
batches = {}
items = {}
loans = {}
waitlist_entries = {}
crawl_jobs = {}
captures = {}
directives = {}
rights_requests = {}
grants = {}
budget_lines = {}
