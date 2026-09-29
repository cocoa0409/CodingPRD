"""Bakery department endpoints (PRD 3.1)."""

from flask import Blueprint, request

import serializers
from errors import ApiError
from guards import ANY_ROLE, as_bool, as_decimal, as_string, authenticate, body, find_department
from response import created, listing, mark_new, ok, parse_pagination
from store import by_seq, db, new_entity
from util import q2, q4

bp = Blueprint("departments", __name__)


@bp.post("/bakery/departments")
def create_department():
    authenticate(("RegionalAdmin",))
    payload = body()
    name = as_string(payload, "name", min_len=1, max_len=120)
    store_number = as_string(payload, "store_number", min_len=1, max_len=10)
    shrink_budget_pct = as_decimal(payload, "shrink_budget_pct", minimum=0, maximum="0.5000", exclusive_min=True)
    labor_rate = as_decimal(payload, "labor_rate_cents_per_minute", minimum=0, exclusive_min=True)
    freight = as_decimal(payload, "freight_surcharge_pct", required=False, minimum=0, maximum="0.5000",
                         default=q4("0.05"))
    donation = as_bool(payload, "donation_partner_enabled", default=True)

    for existing in db.departments.values():
        if existing["store_number"] == store_number:
            raise ApiError("ERR_DUPLICATE_SKU", "store_number already exists.")

    row = new_entity(
        name=name,
        store_number=store_number,
        shrink_budget_pct=q4(shrink_budget_pct),
        labor_rate_cents_per_minute=q2(labor_rate),
        freight_surcharge_pct=q4(freight),
        donation_partner_enabled=donation,
        open_purchase_commitment_cents=0,
    )
    db.departments[row["id"]] = row
    mark_new(row)
    return created(serializers.department(row))


@bp.get("/bakery/departments/<departmentId>")
def read_department(departmentId):
    authenticate(ANY_ROLE)
    row = find_department(departmentId)
    return ok(serializers.department(row))


@bp.get("/bakery/departments")
def list_departments():
    authenticate(ANY_ROLE)
    limit, offset = parse_pagination(request.args)
    store_number = request.args.get("store_number")
    rows = [
        row
        for row in db.departments.values()
        if store_number in (None, "") or row["store_number"] == store_number
    ]
    return listing([serializers.department(row) for row in by_seq(rows)], limit, offset)
