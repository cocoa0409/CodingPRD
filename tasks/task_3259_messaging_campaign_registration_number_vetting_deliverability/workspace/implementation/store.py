"""Shared mutable in-memory state for the Messaging Deliverability API.

The store starts empty on every boot. No seeding is performed anywhere.
"""

ACCOUNTS = {}
BRANDS = {}
CAMPAIGNS = {}
NUMBERS = {}
CONSENTS = {}
MESSAGES = {}
FEEDBACK = {}
CHARGES = {}
SNAPSHOTS = {}
OPSRUNS = {}

# Logical clock (ISO 8601 UTC string with three fractional digits, trailing Z).
# Startup default is exactly 2026-09-01T00:00:00Z per PRD section 2.5.
CLOCK = {"current_utc": "2026-09-01T00:00:00.000Z"}


def now_iso():
    return CLOCK["current_utc"]
