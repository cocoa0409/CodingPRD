"""In-memory data store. Empty on every boot; no seeding."""
import uuid

db = {
    "offices": {},
    "fee_schedules": {},
    "agents": {},
    "fee_assignments": {},
    "offers": {},
    "transactions": {},
    "cdas": {},
    "closing_lines": {},
    "invoices": {},
    "invoice_lines": {},
    "entries": {},
    "referrals": {},
    "reports": {},
}

_seq = [0]


def next_seq():
    _seq[0] += 1
    return _seq[0]


def new_id():
    return str(uuid.uuid4())
