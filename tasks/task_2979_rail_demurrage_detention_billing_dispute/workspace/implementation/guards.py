"""Ladder bands 6 and 7 of PRD §2.8: path existence and body-reference
existence, plus the ownership chain of §2.1.

There is exactly one not-found code per addressable entity, and body references
are resolved in the order they are declared for the operation.
"""

from errors import fail
from store import db

# collection attribute -> the entity's own 404 code
_NOT_FOUND = {
    "customers": "ERR_CUSTOMER_NOT_FOUND",
    "tariffs": "ERR_TARIFF_RULE_SET_NOT_FOUND",
    "facilities": "ERR_FACILITY_NOT_FOUND",
    "rail_cars": "ERR_RAIL_CAR_NOT_FOUND",
    "cycles": "ERR_PLACEMENT_CYCLE_NOT_FOUND",
    "charges": "ERR_DEMURRAGE_CHARGE_NOT_FOUND",
    "invoices": "ERR_INVOICE_NOT_FOUND",
    "claims": "ERR_BUNCHING_CLAIM_NOT_FOUND",
    "disputes": "ERR_DEMURRAGE_DISPUTE_NOT_FOUND",
    "agreements": "ERR_AVERAGE_AGREEMENT_NOT_FOUND",
    "complaints": "ERR_REGULATORY_COMPLAINT_NOT_FOUND",
}


def lookup(collection, identifier):
    """Resolve an identifier to a live row or raise the collection's own 404."""
    rows = getattr(db, collection)
    row = rows.get(identifier) if isinstance(identifier, str) else None
    if row is None:
        fail(_NOT_FOUND[collection], "No such resource: %s." % identifier)
    return row


def customer(identifier):
    return lookup("customers", identifier)


def tariff(identifier):
    return lookup("tariffs", identifier)


def facility(identifier):
    return lookup("facilities", identifier)


def rail_car(identifier):
    return lookup("rail_cars", identifier)


def cycle(identifier):
    return lookup("cycles", identifier)


def charge(identifier):
    return lookup("charges", identifier)


def invoice(identifier):
    return lookup("invoices", identifier)


def claim(identifier):
    return lookup("claims", identifier)


def dispute(identifier):
    return lookup("disputes", identifier)


def agreement(identifier):
    return lookup("agreements", identifier)


def complaint(identifier):
    return lookup("complaints", identifier)


# --------------------------------------------------------------------------
# the ownership chain of PRD §2.1
# --------------------------------------------------------------------------

def owner_of_cycle(row):
    return row["customer_id"]


def owner_of_charge(row):
    parent = db.cycles.get(row["placement_cycle_id"])
    return None if parent is None else parent["customer_id"]


def owner_of_dispute(row):
    return row["customer_id"]


def owner_of_evidence(row):
    parent = db.disputes.get(row["demurrage_dispute_id"])
    return None if parent is None else parent["customer_id"]


def owner_of_complaint(row):
    parent = db.disputes.get(row["demurrage_dispute_id"])
    return None if parent is None else parent["customer_id"]
