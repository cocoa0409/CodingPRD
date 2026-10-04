"""In-memory data store. Fresh and empty on every process boot — no seeding."""
import threading

LOCK = threading.RLock()

manufacturers = {}
agreements = {}
vehicles = {}
price_lists = {}
price_lines = {}
price_modifications = {}
teaming = {}
teaming_scopes = {}
orders = {}
invoices = {}
disputes = {}
sales_reports = {}
audits = {}

# Logical clock (ISO-8601 UTC string, normalized to millisecond precision).
# Initialized at exactly 2026-09-01T00:00:00Z; never falls back to wall clock.
logical_clock = "2026-09-01T00:00:00.000Z"


def set_logical_clock(iso):
    global logical_clock
    logical_clock = iso
