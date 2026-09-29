"""Passenger ownership scoping (PRD section 2.1)."""
from flask import g

import db
from errors import ApiError

STAFF_ROLES = ("TerminalAdmin", "SalesAssociate", "StockController", "CustomsAuditor")
ALL_ROLES = STAFF_ROLES + ("Passenger",)
LEDGER_ROLES = ("TerminalAdmin", "StockController", "CustomsAuditor")
AUDIT_ROLES = ("TerminalAdmin", "StockController", "CustomsAuditor")


def is_passenger():
    return getattr(g, "role", None) == "Passenger"


def ensure_owner(itinerary_id):
    if is_passenger() and g.user_id != itinerary_id:
        raise ApiError("ERR_NOT_ITINERARY_OWNER")


def sale_itinerary_id(sale):
    return sale["itinerary_id"]


def line_itinerary_id(line):
    sale = db.sales.get(line["sale_id"])
    return sale["itinerary_id"] if sale else None


def bag_itinerary_id(bag):
    sale = db.sales.get(bag["sale_id"])
    return sale["itinerary_id"] if sale else None


def owned_predicate(resolver):
    """List filter that keeps only records tracing back to the caller's itinerary."""
    if not is_passenger():
        return None
    owner = g.user_id

    def predicate(record):
        return resolver(record) == owner

    return predicate
