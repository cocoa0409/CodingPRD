"""Lookup and list-filter helpers shared by the route modules."""

from flask import request

from errors import fail
from store import by_created_at, db

NOT_FOUND = {
    "designs": "ERR_DESIGN_NOT_FOUND",
    "orders": "ERR_ORDER_NOT_FOUND",
    "work_orders": "ERR_WORK_ORDER_NOT_FOUND",
    "stator_builds": "ERR_SUBASSEMBLY_NOT_FOUND",
    "rotor_builds": "ERR_SUBASSEMBLY_NOT_FOUND",
    "assembly_records": "ERR_ASSEMBLY_RECORD_NOT_FOUND",
    "performance_tests": "ERR_PERFORMANCE_TEST_NOT_FOUND",
    "nameplates": "ERR_NAMEPLATE_NOT_FOUND",
    "warranty_claims": "ERR_WARRANTY_CLAIM_NOT_FOUND",
    "distributors": "ERR_DISTRIBUTOR_NOT_FOUND",
    "ovens": "ERR_OVEN_NOT_FOUND",
    "test_cells": "ERR_TEST_CELL_NOT_FOUND",
    "standards": "ERR_STANDARD_NOT_FOUND",
}


def table(name):
    return getattr(db, name)


def load(name, row_id):
    """Resolve an identifier or reject with the error naming the kind of
    resource that was missing (PRD 2.6)."""
    row = table(name).get(row_id) if isinstance(row_id, str) else None
    if row is None:
        fail(NOT_FOUND[name])
    return row


def rows(name):
    return by_created_at(list(table(name).values()))


def eq_filter(collection, field, arg=None):
    value = request.args.get(arg or field)
    if value is None:
        return collection
    return [r for r in collection if r.get(field) == value]


def bool_filter(collection, field, arg=None):
    value = request.args.get(arg or field)
    if value is None:
        return collection
    if value.lower() in ("true", "1"):
        wanted = True
    elif value.lower() in ("false", "0"):
        wanted = False
    else:
        fail("ERR_INVALID_REQUEST", "Filter '%s' must be a boolean." % (arg or field))
    return [r for r in collection if bool(r.get(field)) is wanted]


def int_filter(collection, field, arg=None):
    value = request.args.get(arg or field)
    if value is None:
        return collection
    try:
        wanted = int(value)
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", "Filter '%s' must be an integer." % (arg or field))
    return [r for r in collection if r.get(field) == wanted]
