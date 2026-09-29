"""In-memory store. Every collection starts empty on every boot; nothing is
seeded, preloaded or hardcoded here."""

import core
from errors import ApiError

guides = {}
borrowers = {}
communities = {}
units = {}
valuations = {}
loans = {}
filings = {}
policies = {}
payments = {}
cases = {}

_COLLECTIONS = (guides, borrowers, communities, units, valuations, loans,
                filings, policies, payments, cases)


def clear_all():
    for coll in _COLLECTIONS:
        coll.clear()
    core.reset_clock()


def stamp_new(record, versioned=True):
    """Attach identity and audit fields to a brand-new record."""
    record["_seq"] = core.next_seq()
    record["created_at"] = core.now()
    if versioned:
        record["updated_at"] = core.now()
        record["version"] = 1
    return record


def touch(record):
    """A mutation: refresh updated_at and increment version by exactly one."""
    if "version" in record:
        record["updated_at"] = core.now()
        record["version"] = record["version"] + 1
    return record


def ordered(records):
    """created_at ascending; ascending creation order is the only tie-break."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


def serialize(record):
    out = {}
    for key, value in record.items():
        if key.startswith("_"):
            continue
        out[key] = _convert(value)
    return out


def _convert(value):
    if hasattr(value, "utcoffset") and hasattr(value, "year"):
        return core.iso(value)
    if isinstance(value, list):
        return [_convert(v) for v in value]
    if isinstance(value, dict):
        return dict((k, _convert(v)) for k, v in value.items())
    return value


def serialize_all(records):
    return [serialize(r) for r in records]


# --------------------------------------------------------------------------
# resolution helpers — each identifier carries its own not-found code (PRD 2.6)
# --------------------------------------------------------------------------

def _lookup(coll, identifier, error_id):
    if not isinstance(identifier, str) or identifier not in coll:
        raise ApiError(error_id)
    return coll[identifier]


def get_guide(identifier):
    return _lookup(guides, identifier, "ERR_GUIDE_NOT_FOUND")


def get_borrower(identifier):
    return _lookup(borrowers, identifier, "ERR_BORROWER_NOT_FOUND")


def get_community(identifier):
    return _lookup(communities, identifier, "ERR_COMMUNITY_NOT_FOUND")


def get_unit(identifier):
    return _lookup(units, identifier, "ERR_UNIT_NOT_FOUND")


def get_valuation(identifier):
    return _lookup(valuations, identifier, "ERR_VALUATION_NOT_FOUND")


def get_loan(identifier):
    return _lookup(loans, identifier, "ERR_LOAN_NOT_FOUND")


def get_filing(identifier):
    return _lookup(filings, identifier, "ERR_FILING_NOT_FOUND")


def get_policy(identifier):
    return _lookup(policies, identifier, "ERR_POLICY_NOT_FOUND")


def get_payment(identifier):
    return _lookup(payments, identifier, "ERR_PAYMENT_NOT_FOUND")


def get_case(identifier):
    return _lookup(cases, identifier, "ERR_RECOVERY_CASE_NOT_FOUND")


# --------------------------------------------------------------------------
# relationship helpers
# --------------------------------------------------------------------------

def loans_of_unit(unit_id):
    return ordered([l for l in loans.values() if l["unit_id"] == unit_id])


def loans_of_borrower(borrower_id):
    return ordered([l for l in loans.values() if l["borrower_id"] == borrower_id])


def filings_of_loan(loan_id):
    return ordered([f for f in filings.values() if f["loan_id"] == loan_id])


def filings_of_unit(unit_id):
    return ordered([f for f in filings.values() if f["unit_id"] == unit_id])


def policies_of_loan(loan_id):
    return ordered([p for p in policies.values() if p["loan_id"] == loan_id])


def payments_of_loan(loan_id):
    return ordered([p for p in payments.values() if p["loan_id"] == loan_id])


def cases_of_loan(loan_id):
    return ordered([c for c in cases.values() if c["loan_id"] == loan_id])
