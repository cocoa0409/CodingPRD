"""Patron endpoints (PRD 3.1)."""
from flask import Blueprint

from db import base_row, db, touch
from middleware import (ACCOUNTANT, ACQUISITIONS, ADMIN, ILL_STAFF, PATRON, auth,
                        get_patron, own_patron_id)
from response import ok_row
from routes.common import filter_eq, list_response
from services import derive
from validate import (body, opt_enum, opt_int, opt_str, q_str, q_enum, req_enum,
                      req_str, bad)

bp = Blueprint("patrons", __name__)

PATRON_TYPES = ("FACULTY", "GRAD", "UNDERGRAD", "STAFF")
PATRON_STATUSES = ("ACTIVE", "BLOCKED", "WITHDRAWN")
INFRACTION_KINDS = ("LOST", "DAMAGED", "LATE_RETURN", "UNCLAIMED", "UNPAID_CHARGE")


@bp.route("/ill/patrons", methods=["POST"])
def create_patron():
    auth(ADMIN, ILL_STAFF)
    data = body()
    external_id = req_str(data, "external_id", 1, 32)
    full_name = req_str(data, "full_name")
    email = req_str(data, "email")
    patron_type = req_enum(data, "patron_type", PATRON_TYPES)
    department = req_str(data, "department")
    max_open_requests = opt_int(data, "max_open_requests", 5, 1)
    max_concurrent_loans = opt_int(data, "max_concurrent_loans", 3, 1)
    unpaid_cap = opt_int(data, "unpaid_balance_cap_cents", 5000, 0)
    for existing in db.patrons.values():
        if existing["external_id"] == external_id:
            bad("Field 'external_id' must be unique across all patron rows.")
    row = base_row()
    row.update({
        "external_id": external_id,
        "full_name": full_name,
        "email": email,
        "patron_type": patron_type,
        "department": department,
        "status": "ACTIVE",
        "max_open_requests": max_open_requests,
        "max_concurrent_loans": max_concurrent_loans,
        "unpaid_balance_cap_cents": unpaid_cap,
        "historical_lost_count": 0,
        "historical_damaged_count": 0,
        "historical_late_return_count": 0,
        "historical_unclaimed_count": 0,
        "historical_unpaid_cents": 0,
        "lost_count": 0,
        "damaged_count": 0,
        "late_return_count": 0,
        "unclaimed_count": 0,
        "unpaid_balance_cents": 0,
        "pending_charge_cents": 0,
        "open_request_count": 0,
        "provisional_risk_score": 0,
        "final_risk_score": 0,
    })
    db.patrons[row["id"]] = row
    return ok_row(row, 201)


@bp.route("/ill/patrons/<patron_id>", methods=["PATCH"])
def patch_patron(patron_id):
    auth(ADMIN)
    patron = get_patron(patron_id)
    data = body()
    status = opt_enum(data, "status", PATRON_STATUSES)
    email = opt_str(data, "email", None, 1)
    max_open_requests = opt_int(data, "max_open_requests", None, 1)
    max_concurrent_loans = opt_int(data, "max_concurrent_loans", None, 1)
    unpaid_cap = opt_int(data, "unpaid_balance_cap_cents", None, 0)
    if status is not None:
        patron["status"] = status
    if email is not None:
        patron["email"] = email
    if max_open_requests is not None:
        patron["max_open_requests"] = max_open_requests
    if max_concurrent_loans is not None:
        patron["max_concurrent_loans"] = max_concurrent_loans
    if unpaid_cap is not None:
        patron["unpaid_balance_cap_cents"] = unpaid_cap
    derive.recompute_patron(
        patron, ("provisional_risk_score", "final_risk_score"), defer_touch=True)
    touch(patron)
    return ok_row(patron)


@bp.route("/ill/patrons/<patron_id>/infraction-records", methods=["POST"])
def add_infraction(patron_id):
    auth(ADMIN)
    patron = get_patron(patron_id)
    data = body()
    kind = req_enum(data, "kind", INFRACTION_KINDS)
    count = opt_int(data, "count", 1, 0)
    if kind == "UNPAID_CHARGE":
        unpaid = opt_int(data, "unpaid_amount_cents", None, 0)
        if unpaid is None:
            bad("Field 'unpaid_amount_cents' is required for an UNPAID_CHARGE record.")
        patron["historical_unpaid_cents"] += unpaid
    else:
        opt_int(data, "unpaid_amount_cents", None, 0)
        if kind == "LOST":
            patron["historical_lost_count"] += count
        elif kind == "DAMAGED":
            patron["historical_damaged_count"] += count
        elif kind == "LATE_RETURN":
            patron["historical_late_return_count"] += count
        elif kind == "UNCLAIMED":
            patron["historical_unclaimed_count"] += count
    derive.recompute_patron(patron, derive.PATRON_ALL_KEYS, defer_touch=True)
    touch(patron)
    return ok_row(patron)


@bp.route("/ill/patrons/<patron_id>", methods=["GET"])
def get_one_patron(patron_id):
    user_id, role = auth(PATRON, ILL_STAFF, ACQUISITIONS, ACCOUNTANT, ADMIN)
    own_patron_id(patron_id, user_id, role)
    patron = get_patron(patron_id)
    return ok_row(patron)


@bp.route("/ill/patrons", methods=["GET"])
def list_patrons():
    auth(ILL_STAFF, ADMIN)
    rows = list(db.patrons.values())
    rows = filter_eq(rows, "status", q_enum("status", PATRON_STATUSES))
    rows = filter_eq(rows, "external_id", q_str("external_id"))
    return list_response(rows)
