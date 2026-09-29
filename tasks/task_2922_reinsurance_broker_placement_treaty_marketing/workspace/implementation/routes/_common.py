"""Shared role sets and list helpers for the route modules (PRD section 4)."""
from flask import request

import db
import response
import validate
from middleware import (
    BROKER_ACCOUNTANT,
    BROKER_ACTUARY,
    BROKER_PLACEMENT_LEAD,
    CEDENT_UNDERWRITER,
    COMPLIANCE_OFFICER,
    PLATFORM_ADMIN,
    REINSURER_UNDERWRITER,
)

BROKER_SIDE = (
    PLATFORM_ADMIN,
    BROKER_PLACEMENT_LEAD,
    BROKER_ACTUARY,
    BROKER_ACCOUNTANT,
    COMPLIANCE_OFFICER,
)
CEDENT_READ = BROKER_SIDE + (CEDENT_UNDERWRITER,)
REINSURER_READ = BROKER_SIDE + (REINSURER_UNDERWRITER,)
EVERY_ROLE = BROKER_SIDE + (CEDENT_UNDERWRITER, REINSURER_UNDERWRITER)
LEDGER_READ = (
    PLATFORM_ADMIN,
    BROKER_PLACEMENT_LEAD,
    BROKER_ACCOUNTANT,
    COMPLIANCE_OFFICER,
)


def paged(rows, serializer):
    limit, offset = validate.pagination()
    return response.list_response([serializer(r) for r in rows], limit, offset)


def filter_eq(rows, field, value):
    if value is None:
        return rows
    return [r for r in rows if r.get(field) == value]


def q(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


def ordered_filtered(collection, filters):
    rows = db.ordered(collection)
    for field, value in filters:
        rows = filter_eq(rows, field, value)
    return rows
