"""State registrations (PRD 3.9): the state layer on the federal approval."""
from datetime import timedelta

from flask import Blueprint, request

import clock
import constants
from auth import require_auth, require_role
from db import new_row, store, touch
from envelope import ok, ok_list
from errors import err
from services.calcs import renewal_fee_cents
from validate import (
    as_enum,
    as_int,
    as_list,
    as_str,
    paginate,
    parse_body,
    reject_unknown,
)

bp = Blueprint("state_registrations", __name__)

NON_TERMINAL_REG_STATUSES = ("SUBMITTED", "GRANTED", "LAPSED")


def get_registration_or_404(registration_id):
    reg = store["state_registrations"].get(registration_id)
    if reg is None:
        err(
            "ERR_STATE_REGISTRATION_NOT_FOUND",
            "State registration %s does not exist." % registration_id,
        )
    return reg


@bp.post("/state-registrations")
def create_state_registration():
    caller = require_auth()
    require_role(caller, [constants.ROLE_REGISTRANT_REPRESENTATIVE])
    data = parse_body()
    reject_unknown(data, ["product_id", "state_code"])
    product_id = as_str(data, "product_id", required=True)
    state_code = as_str(data, "state_code", required=True)
    # Stage 3: state registration is offered in exactly four states.
    if state_code not in constants.STATE_BASE_FEE_CENTS:
        err("ERR_INVALID_REQUEST", "state_code must be one of CA, TX, IA, FL.")

    product = store["products"].get(product_id)
    if product is None:
        err("ERR_PRODUCT_NOT_FOUND", "Product %s does not exist." % product_id)
    if product["registrant_ref"] != caller["user_id"]:
        err("ERR_NOT_RESOURCE_OWNER", "The product belongs to another registrant.")
    if product["status"] != "REGISTERED":
        err("ERR_PRODUCT_NOT_REGISTERED", "The product must be REGISTERED at filing.")

    for reg in store["state_registrations"].values():
        if (
            reg["product_id"] == product_id
            and reg["state_code"] == state_code
            and reg["status"] in NON_TERMINAL_REG_STATUSES
        ):
            err(
                "ERR_DUPLICATE_STATE_REGISTRATION",
                "A non-terminal registration already exists for this product and state.",
            )

    row = new_row()
    row.update(
        {
            "product_id": product_id,
            "registrant_ref": caller["user_id"],
            "state_code": state_code,
            "status": "SUBMITTED",
            "additional_restrictions": [],
            "annual_fee_cents": None,
            "submitted_at": clock.now(),
            "granted_at": None,
            "renewal_due_at": None,
            "last_renewal_at": None,
            "renewal_count": 0,
        }
    )
    store["state_registrations"][row["id"]] = row
    return ok(row, status=201)


@bp.get("/state-registrations")
def list_state_registrations():
    require_auth()
    rows = list(store["state_registrations"].values())
    for key in ("product_id", "state_code", "status"):
        value = request.args.get(key)
        if value is not None:
            rows = [r for r in rows if r.get(key) == value]
    page, limit, offset, total = paginate(rows)
    return ok_list(page, limit, offset, total)


@bp.get("/state-registrations/<registration_id>")
def get_state_registration(registration_id):
    require_auth()
    return ok(get_registration_or_404(registration_id))


@bp.post("/state-registrations/<registration_id>/review-decisions")
def decide_state_registration(registration_id):
    caller = require_auth()
    require_role(caller, [constants.ROLE_STATE_LEAD_AGENCY])
    data = parse_body()
    reject_unknown(data, ["decision", "additional_restrictions"])
    decision = as_enum(data, "decision", ["GRANT", "DENY"], required=True)
    additional_restrictions = as_list(data, "additional_restrictions", required=False)
    if additional_restrictions is not None:
        for item in additional_restrictions:
            if not isinstance(item, str):
                err(
                    "ERR_INVALID_REQUEST",
                    "additional_restrictions must be an array of strings.",
                )

    reg = get_registration_or_404(registration_id)
    if reg["status"] != "SUBMITTED":
        err("ERR_STATE_REG_NOT_DECIDABLE", "The registration is not SUBMITTED.")

    if decision == "DENY":
        reg["status"] = "DENIED"
        touch(reg)
        return ok(reg)

    # GRANT: re-check the product is REGISTERED at decision time.
    product = store["products"][reg["product_id"]]
    if product["status"] != "REGISTERED":
        err(
            "ERR_PRODUCT_NOT_REGISTERED",
            "The product must be REGISTERED at decision time.",
        )
    # Stage 8: RESTRICTED_USE requires a valid certification in that state.
    if product["classification"] == "RESTRICTED_USE":
        now = clock.now()
        valid = any(
            c["state_code"] == reg["state_code"]
            and c["status"] == "ACTIVE"
            and c["certified_until"] >= now
            for c in store["certifications"].values()
        )
        if not valid:
            err(
                "ERR_NO_VALID_APPLICATOR_CERTIFICATION",
                "No ACTIVE applicator certification in %s covers this grant." % reg["state_code"],
            )

    now = clock.now()
    fee = constants.STATE_BASE_FEE_CENTS[reg["state_code"]]
    if product["classification"] == "RESTRICTED_USE":
        fee += constants.RUP_SURCHARGE_CENTS
    reg["status"] = "GRANTED"
    reg["granted_at"] = now
    reg["renewal_due_at"] = now + timedelta(days=constants.RENEWAL_PERIOD_DAYS)
    reg["annual_fee_cents"] = fee
    reg["additional_restrictions"] = additional_restrictions or []
    touch(reg)
    return ok(reg)


@bp.post("/state-registrations/<registration_id>/revoke")
def revoke_state_registration(registration_id):
    caller = require_auth()
    require_role(caller, [constants.ROLE_STATE_LEAD_AGENCY])
    data = parse_body()
    reject_unknown(data, ["reason"])
    if "reason" in data and data["reason"] is not None:
        as_str(data, "reason")

    reg = get_registration_or_404(registration_id)
    if reg["status"] not in ("GRANTED", "LAPSED"):
        err(
            "ERR_STATE_REG_NOT_DECIDABLE",
            "Only a GRANTED or LAPSED registration can be revoked.",
        )
    reg["status"] = "REVOKED"
    if data.get("reason") is not None:
        reg["reason"] = data["reason"]
    touch(reg)
    return ok(reg)


@bp.post("/state-registrations/<registration_id>/renew")
def renew_state_registration(registration_id):
    caller = require_auth()
    require_role(caller, [constants.ROLE_REGISTRANT_REPRESENTATIVE])
    data = parse_body()
    reject_unknown(data, ["payment_cents"])
    payment = as_int(data, "payment_cents", required=False)

    reg = get_registration_or_404(registration_id)
    product = store["products"][reg["product_id"]]
    if product["registrant_ref"] != caller["user_id"]:
        err("ERR_NOT_RESOURCE_OWNER", "The registration belongs to another registrant.")

    if reg["status"] not in ("GRANTED", "LAPSED"):
        err(
            "ERR_STATE_REG_NOT_DECIDABLE",
            "Only a GRANTED or LAPSED registration can be renewed.",
        )
    if product["status"] == "CANCELLED":
        err("ERR_PRODUCT_TERMINAL", "The product is CANCELLED.")
    if product["status"] not in ("REGISTERED", "UNDER_REVIEW"):
        err(
            "ERR_PRODUCT_NOT_REGISTERED",
            "The product must be REGISTERED or UNDER_REVIEW to renew.",
        )

    # Stage 12: fiscal exactness, computed BEFORE the anniversary moves.
    now = clock.now()
    fee_due = renewal_fee_cents(reg, now)
    if payment != fee_due:
        err(
            "ERR_INCORRECT_FEE_PAYMENT",
            "payment_cents must equal the computed renewal fee of %d." % fee_due,
        )

    # Only after the fee is fixed does the anniversary move: +365 days from
    # the previous renewal_due_at, never from the payment date.
    reg["renewal_due_at"] = reg["renewal_due_at"] + timedelta(
        days=constants.RENEWAL_PERIOD_DAYS
    )
    reg["last_renewal_at"] = now
    reg["renewal_count"] += 1
    reg["status"] = "GRANTED"
    touch(reg)
    return ok(reg)
