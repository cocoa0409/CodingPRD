"""DesignRegistration endpoints."""

from flask import Blueprint, request

import db
import errors as E
from errors import ApiError
from middleware import require_auth, require_role
from response import success
from services.helpers import (
    check_buyer_body_ownership,
    get_json_body,
    get_registration_or_404,
    mint_id,
    opt_str,
    paginate,
    pagination_params,
    req_date,
    req_int,
    req_str,
    serialize_registration,
    stamp_now,
)

bp = Blueprint("registrations", __name__)

_seq = 0


def _next_seq():
    global _seq
    _seq += 1
    return _seq


@bp.post("/design-registrations")
def create_registration():
    user_id, role = require_auth()
    require_role(user_id, role, {"SalesRep", "CustomerBuyer"})
    body = get_json_body()
    customer_id = req_str(body, "customer_id")
    part_id = req_str(body, "part_id")
    end_customer_name = req_str(body, "end_customer_name")
    registered_cost_cents = req_int(body, "registered_cost_cents")
    max_registered_qty = req_int(body, "max_registered_qty")
    valid_from = req_date(body, "valid_from")
    valid_to = req_date(body, "valid_to")

    # Ownership (priority 2) precedes FK existence (priority 3) for body customer_id.
    check_buyer_body_ownership(user_id, role, customer_id)

    if customer_id not in db.customers:
        raise ApiError(E.ERR_CUSTOMER_NOT_FOUND, 404, "Customer not found.")
    if part_id not in db.parts:
        raise ApiError(E.ERR_PART_NOT_FOUND, 404, "Part not found.")

    # Window-overlap among SUBMITTED/APPROVED for the same (customer, part);
    # CLOSED intervals — touching boundaries conflict.
    for reg in db.design_registrations.values():
        if (
            reg["customer_id"] == customer_id
            and reg["part_id"] == part_id
            and reg["status"] in ("SUBMITTED", "APPROVED")
            and valid_from <= reg["_valid_to"]
            and valid_to >= reg["_valid_from"]
        ):
            raise ApiError(
                E.ERR_REGISTRATION_WINDOW_OVERLAP,
                409,
                "Validity window overlaps an existing SUBMITTED/APPROVED registration.",
            )

    now = stamp_now()
    reg = {
        "id": mint_id(),
        "customer_id": customer_id,
        "part_id": part_id,
        "end_customer_name": end_customer_name,
        "registered_cost_cents": registered_cost_cents,
        "max_registered_qty": max_registered_qty,
        "registered_qty_remaining": 0,
        "valid_from": valid_from.isoformat(),
        "valid_to": valid_to.isoformat(),
        "_valid_from": valid_from,
        "_valid_to": valid_to,
        "status": "SUBMITTED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": _next_seq(),
    }
    db.design_registrations[reg["id"]] = reg
    return success(serialize_registration(reg), status=201)


@bp.get("/design-registrations")
def list_registrations():
    require_auth()
    limit, offset = pagination_params()
    customer_id = request.args.get("customer_id")
    part_id = request.args.get("part_id")
    status = request.args.get("status")
    items = list(db.design_registrations.values())
    if customer_id is not None:
        items = [r for r in items if r["customer_id"] == customer_id]
    if part_id is not None:
        items = [r for r in items if r["part_id"] == part_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    page, pag = paginate(items, limit, offset)
    return success(
        [serialize_registration(r) for r in page],
        status=200,
        response_type="array",
        pagination=pag,
    )


@bp.get("/design-registrations/<registrationId>")
def get_registration(registrationId):
    require_auth()
    reg = get_registration_or_404(registrationId)
    return success(serialize_registration(reg), status=200)


@bp.post("/design-registrations/<registrationId>/decision")
def decide_registration(registrationId):
    user_id, role = require_auth()
    require_role(user_id, role, {"SupplierAdmin"})
    body = get_json_body()
    decision = body.get("decision")
    if decision not in ("APPROVE", "REJECT"):
        raise ApiError(E.ERR_INVALID_REQUEST, 400, "decision must be APPROVE or REJECT.")
    reg = get_registration_or_404(registrationId)
    if reg["status"] != "SUBMITTED":
        raise ApiError(
            E.ERR_REGISTRATION_NOT_SUBMITTED,
            409,
            "Registration is not in SUBMITTED.",
        )
    if decision == "APPROVE":
        reg["status"] = "APPROVED"
        reg["registered_qty_remaining"] = reg["max_registered_qty"]
    else:
        reg["status"] = "REJECTED"
    reg["updated_at"] = stamp_now()
    reg["version"] += 1
    return success(serialize_registration(reg), status=200)
