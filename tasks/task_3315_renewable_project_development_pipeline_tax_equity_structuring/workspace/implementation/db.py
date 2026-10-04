"""In-memory data store. Starts empty on every boot; no seeding."""
import uuid

# Stores keyed by id
projects = {}
site_control_instruments = {}
interconnection_requests = {}
interconnection_studies = {}
offtake_agreements = {}
supply_agreements = {}
procurement_orders = {}
construction_milestones = {}
tax_credit_qualifications = {}
tax_equity_partnerships = {}
partnership_ledger_entries = {}
debt_facilities = {}


def new_id():
    return str(uuid.uuid4())


# Logical clock (epoch seconds float). Default: 2026-09-01T00:00:00Z.
_logical_clock = [1788220800.0]


def clock_now():
    return _logical_clock[0]


def clock_set(ts):
    _logical_clock[0] = float(ts)
