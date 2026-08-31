"""Bilateral prorate agreements and their sector rate cards (PRD section 3.2)."""

from flask import Blueprint

from calculations import factors_of_agreement
from errors import ApiError
from responses import ok, ok_list
from store import db, must_find, new_row, serialize, touch
import validation as V

bp = Blueprint("agreements", __name__)


@bp.route("/interline/prorate-agreements", methods=["POST"])
def create_agreement():
    user_id, role = V.require([V.ROLE_ACCOUNTANT])
    data = V.body()
    issuing_id = V.req_str(data, "issuing_carrier_id")
    partner_id = V.req_str(data, "partner_carrier_id")
    agreement_type = V.req_enum(data, "agreement_type", V.AGREEMENT_TYPES)
    settlement_currency = V.req_enum(data, "settlement_currency", V.CURRENCIES)
    eff_from_raw, eff_from = V.req_date(data, "effective_from")
    eff_to_raw, eff_to = V.req_date(data, "effective_to")
    if eff_to < eff_from:
        V.bad("effective_to must be on or after effective_from.")

    issuing = must_find("carrier", issuing_id)
    partner = must_find("carrier", partner_id)

    V.require_ownership(user_id, role, issuing["id"])

    if issuing["status"] != "ACTIVE":
        raise ApiError("ERR_CARRIER_SUSPENDED")

    agreement = new_row({
        "issuing_carrier_id": issuing["id"],
        "partner_carrier_id": partner["id"],
        "agreement_type": agreement_type,
        "settlement_currency": settlement_currency,
        "effective_from": eff_from_raw,
        "effective_to": eff_to_raw,
        "status": "DRAFT",
        "suspension_reason": "NONE",
        "factor_count": 0,
    })
    agreement["_effective_from"] = eff_from
    agreement["_effective_to"] = eff_to
    db.agreements[agreement["id"]] = agreement
    return ok(serialize(agreement), 201)


@bp.route("/interline/prorate-agreements/<agreement_id>", methods=["GET"])
def get_agreement(agreement_id):
    V.require(V.ALL_ROLES)
    agreement = must_find("agreement", agreement_id)
    return ok(serialize(agreement))


@bp.route("/interline/prorate-agreements", methods=["GET"])
def list_agreements():
    V.require(V.ALL_ROLES)
    limit, offset = V.pagination()
    issuing_id = V.filter_str("issuing_carrier_id")
    partner_id = V.filter_str("partner_carrier_id")
    status = V.filter_enum("status", V.AGREEMENT_STATUSES)
    rows = list(db.agreements.values())
    if issuing_id is not None:
        rows = [r for r in rows if r["issuing_carrier_id"] == issuing_id]
    if partner_id is not None:
        rows = [r for r in rows if r["partner_carrier_id"] == partner_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    window, total = V.listing(rows, limit, offset)
    return ok_list(window, limit, offset, total)


@bp.route("/interline/prorate-agreements/<agreement_id>/factors",
          methods=["POST"])
def create_factor(agreement_id):
    user_id, role = V.require([V.ROLE_ACCOUNTANT])
    data = V.body()
    origin = V.req_str(data, "origin")
    destination = V.req_str(data, "destination")
    class_of_service = V.req_enum(data, "class_of_service", V.CLASSES)
    factor_bp = V.opt_int(data, "factor_bp", minimum=1, maximum=100000)
    flat_amount = V.opt_int(data, "flat_amount_minor", minimum=1)
    percent_bp = V.opt_int(data, "percent_bp", minimum=1, maximum=10000)

    agreement = must_find("agreement", agreement_id)

    V.require_ownership(user_id, role, agreement["issuing_carrier_id"])

    if agreement["status"] != "DRAFT":
        raise ApiError("ERR_AGREEMENT_STATE_INVALID")

    for existing in factors_of_agreement(agreement["id"]):
        if (existing["origin"] == origin
                and existing["destination"] == destination
                and existing["class_of_service"] == class_of_service):
            raise ApiError("ERR_DUPLICATE_FACTOR_SECTOR")

    supplied = [name for name, value in (("factor_bp", factor_bp),
                                         ("flat_amount_minor", flat_amount),
                                         ("percent_bp", percent_bp))
                if value is not None]
    expected = {"STRAIGHT_RATE": "factor_bp",
                "SPA_FLAT": "flat_amount_minor",
                "SPA_PERCENT": "percent_bp"}[agreement["agreement_type"]]
    if supplied != [expected]:
        raise ApiError("ERR_FACTOR_FIELD_MISMATCH")

    specificity = (1 if origin != "*" else 0) + (1 if destination != "*" else 0)
    factor = new_row({
        "agreement_id": agreement["id"],
        "origin": origin,
        "destination": destination,
        "class_of_service": class_of_service,
        "factor_bp": factor_bp,
        "flat_amount_minor": flat_amount,
        "percent_bp": percent_bp,
        "specificity_score": specificity,
    })
    db.factors[factor["id"]] = factor
    agreement["factor_count"] += 1
    touch(agreement)
    return ok(serialize(factor), 201)


@bp.route("/interline/prorate-agreements/<agreement_id>/factors",
          methods=["GET"])
def list_factors(agreement_id):
    V.require(V.ALL_ROLES)
    limit, offset = V.pagination()
    agreement = must_find("agreement", agreement_id)
    rows = [f for f in db.factors.values()
            if f["agreement_id"] == agreement["id"]]
    window, total = V.listing(rows, limit, offset)
    return ok_list(window, limit, offset, total)


@bp.route("/interline/prorate-agreements/<agreement_id>/activate",
          methods=["POST"])
def activate_agreement(agreement_id):
    V.require([V.ROLE_OPERATOR])
    V.body()
    agreement = must_find("agreement", agreement_id)

    if agreement["status"] not in ("DRAFT", "SUSPENDED"):
        raise ApiError("ERR_AGREEMENT_STATE_INVALID")

    issuing = db.carriers.get(agreement["issuing_carrier_id"])
    partner = db.carriers.get(agreement["partner_carrier_id"])
    if issuing is None or issuing["status"] != "ACTIVE":
        raise ApiError("ERR_CARRIER_SUSPENDED")
    if partner is None or partner["status"] != "ACTIVE":
        raise ApiError("ERR_CARRIER_SUSPENDED")

    # Closed-closed interval rule.
    for other in db.agreements.values():
        if other["id"] == agreement["id"]:
            continue
        if other["status"] not in ("ACTIVE", "SUSPENDED"):
            continue
        if (other["issuing_carrier_id"] != agreement["issuing_carrier_id"]
                or other["partner_carrier_id"] != agreement["partner_carrier_id"]):
            continue
        if (agreement["_effective_from"] <= other["_effective_to"]
                and other["_effective_from"] <= agreement["_effective_to"]):
            raise ApiError("ERR_AGREEMENT_PERIOD_OVERLAP")

    agreement["status"] = "ACTIVE"
    agreement["suspension_reason"] = "NONE"
    touch(agreement)
    return ok(serialize(agreement))


@bp.route("/interline/prorate-agreements/<agreement_id>/suspend",
          methods=["POST"])
def suspend_agreement(agreement_id):
    V.require([V.ROLE_OPERATOR])
    V.body()
    agreement = must_find("agreement", agreement_id)
    if agreement["status"] != "ACTIVE":
        raise ApiError("ERR_AGREEMENT_STATE_INVALID")
    agreement["status"] = "SUSPENDED"
    agreement["suspension_reason"] = "OPERATOR_SUSPENDED"
    touch(agreement)
    return ok(serialize(agreement))
