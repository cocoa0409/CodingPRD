"""In-memory data store. Fresh on every process boot — no seeding."""

# Entity collections keyed by id
studios = {}
seasons = {}
titles = {}
talents = {}
deals = {}
castings = {}
locations = {}
production_slots = {}
program_blocks = {}
air_slots = {}
sponsorships = {}
streaming_windows = {}
licenses = {}

# Logical clock — ISO string, always starts at the pinned default
_logical_clock = "2026-09-01T00:00:00Z"


def get_clock():
    return _logical_clock


def set_clock(value):
    global _logical_clock
    _logical_clock = value
