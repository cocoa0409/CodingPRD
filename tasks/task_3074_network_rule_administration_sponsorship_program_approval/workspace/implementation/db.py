"""In-memory data store. Everything resets on process restart (per-test-server isolation)."""

from datetime import datetime, timezone

# Logical clock: starts at exactly 2026-09-01T00:00:00Z
_logical_clock = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

# Stores: dict id -> record dict
members = {}
participants = {}
merchants = {}
bin_ranges = {}
programs = {}
certification_tests = {}
rules = {}
violations = {}
disputes = {}
evidence = {}
interchange_rates = {}
fraud_cases = {}
remediation_plans = {}
fraud_cycles = {}
settlement_windows = {}
settlement_lines = {}


def get_clock():
    return _logical_clock


def set_clock(dt):
    global _logical_clock
    _logical_clock = dt
