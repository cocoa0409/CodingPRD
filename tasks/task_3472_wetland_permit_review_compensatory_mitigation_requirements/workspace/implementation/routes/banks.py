"""MitigationBank and CreditTransaction endpoints (PRD §3.6)."""

from decimal import Decimal

from flask import Blueprint

import calculations as calc
from db import STORE, bump, new_entity
from errors import api_err
from helpers import (RESOURCE_TYPES, get_body, req_enum, req_number,
                     req_str, req_str_list)
from middleware import check_ownership, require_roles
from response import apply_filters, list_response, success_obj
from serialization import bank_out, credit_txn_out

bp = Blueprint("banks", __name__)

ALL_ROLES = ("SystemAdmin", "Applicant", "Reviewer", "DistrictEngineer",
             "AgencyReviewer", "EnforcementOfficer")


def _get_bank_or_404(bank_id):
    bank = STORE["banks"].get(bank_id)
    if bank is None:
        raise api_err("ERR_BANK_NOT_FOUND",
                      "No MitigationBank with id %s" % bank_id)
    return bank


def _decimal_map(body, name, positive=False, non_negative=False):
    """Validate a {resource_type: number} map; values coerced to Decimal."""
    raw = body.get(name)
    if not isinstance(raw, dict):
        raise api_err("ERR_INVALID_REQUEST",
                      "Field %s must be an object keyed by resource type"
                      % name)
    result = {}
    for key, value in raw.items():
        if key not in RESOURCE_TYPES:
            raise api_err("ERR_INVALID_REQUEST",
                          "Field %s has an unknown resource type %s"
                          % (name, key))
        if isinstance(value, bool) \
                or not isinstance(value, (int, float)):
            raise api_err("ERR_INVALID_REQUEST",
                          "Field %s values must be numbers" % name)
        dec = Decimal(str(value))
        if positive and not dec > 0:
            raise api_err("ERR_INVALID_REQUEST",
                          "Field %s values must be > 0" % name)
        if non_negative and not dec >= 0:
            raise api_err("ERR_INVALID_REQUEST",
                          "Field %s values must be >= 0" % name)
        result[key] = dec
    return result


@bp.post("/wetland-permits/mitigation-banks")
def create_bank():
    require_roles(["SystemAdmin"])
    body = get_body()
    bank_name = req_str(body, "bank_name")
    sponsor_name = req_str(body, "sponsor_name")
    state_code = req_str(body, "state_code")
    watersheds = req_str_list(body, "service_area_watersheds", non_empty=True)
    credit_capacity = _decimal_map(body, "credit_capacity", non_negative=True)
    base_price = _decimal_map(body, "base_price_per_credit", positive=True)
    # Every type with positive capacity must carry a strictly positive price.
    for rtype, capacity in credit_capacity.items():
        if capacity > 0 and base_price.get(rtype, Decimal("0")) <= 0:
            raise api_err("ERR_INVALID_REQUEST",
                          "base_price_per_credit must be > 0 for every "
                          "resource type with capacity")
    bank = new_entity({
        "bank_name": bank_name,
        "sponsor_name": sponsor_name,
        "state_code": state_code,
        "service_area_watersheds": watersheds,
        "credit_capacity": credit_capacity,
        "base_price_per_credit": base_price,
        # Inventory maps and revenue are computed on read from the bank's
        # transactions (calculations.bank_inventory).
        "status": "PENDING_APPROVAL",
    })
    STORE["banks"][bank["id"]] = bank
    return success_obj(bank_out(bank), 201)


@bp.get("/wetland-permits/mitigation-banks")
def list_banks():
    require_roles(list(ALL_ROLES))

    def watershed_match(bank, raw):
        return raw in bank["service_area_watersheds"]

    banks = apply_filters(STORE["banks"].values(), {
        "status": "status",
        "watershed_code": watershed_match,
    })
    return list_response(banks, bank_out)


@bp.get("/wetland-permits/mitigation-banks/<id>")
def get_bank(id):
    require_roles(list(ALL_ROLES))
    return success_obj(bank_out(_get_bank_or_404(id)))


@bp.post("/wetland-permits/mitigation-banks/<id>/approve")
def approve_bank(id):
    require_roles(["DistrictEngineer"])
    bank = _get_bank_or_404(id)
    if bank["status"] not in ("PENDING_APPROVAL", "SUSPENDED"):
        raise api_err("ERR_BANK_NOT_OPERATIONAL",
                      "approve requires a PENDING_APPROVAL or SUSPENDED bank")
    bank["status"] = "OPERATIONAL"
    bump(bank)
    return success_obj(bank_out(bank))


@bp.post("/wetland-permits/mitigation-banks/<id>/suspend")
def suspend_bank(id):
    require_roles(["DistrictEngineer"])
    bank = _get_bank_or_404(id)
    if bank["status"] != "OPERATIONAL":
        raise api_err("ERR_BANK_NOT_OPERATIONAL",
                      "suspend requires an OPERATIONAL bank")
    bank["status"] = "SUSPENDED"
    bump(bank)
    return success_obj(bank_out(bank))


# ---------------------------------------------------------------------------
# Credit transactions
# ---------------------------------------------------------------------------

def _get_txn_or_404(txn_id):
    txn = STORE["credit_txns"].get(txn_id)
    if txn is None:
        raise api_err("ERR_CREDIT_TXN_NOT_FOUND",
                      "No CreditTransaction with id %s" % txn_id)
    return txn


def _txn_owner_applicant_id(txn):
    plan = STORE["plans"].get(txn["plan_id"])
    app = STORE["applications"].get(plan["application_id"]) if plan else None
    return app["applicant_id"] if app else None


@bp.post("/wetland-permits/credit-transactions")
def create_credit_txn():
    user_id, role = require_roles(["Applicant"])
    body = get_body()
    # Tier 5: body FK existence. plan_id is resolved first because the
    # ownership check (tier 4) needs the plan's application's applicant.
    plan_id = body.get("plan_id")
    plan = None
    if plan_id is not None and isinstance(plan_id, str):
        plan = STORE["plans"].get(plan_id)
        if plan is None:
            raise api_err("ERR_PLAN_NOT_FOUND",
                          "No MitigationPlan with id %s" % plan_id)
    if plan is not None:
        app = STORE["applications"].get(plan["application_id"])
        check_ownership(user_id, role,
                        app["applicant_id"] if app else None)
    bank_id = body.get("bank_id")
    bank = None
    if bank_id is not None and isinstance(bank_id, str):
        bank = STORE["banks"].get(bank_id)
        if bank is None:
            raise api_err("ERR_BANK_NOT_FOUND",
                          "No MitigationBank with id %s" % bank_id)
    # Tier 6: shape.
    if not isinstance(plan_id, str):
        raise api_err("ERR_INVALID_REQUEST", "Field plan_id is required")
    if not isinstance(bank_id, str):
        raise api_err("ERR_INVALID_REQUEST", "Field bank_id is required")
    resource_type = req_enum(body, "resource_type", RESOURCE_TYPES)
    if resource_type not in plan["required_credits_by_type"]:
        raise api_err("ERR_INVALID_REQUEST",
                      "resource_type must be a key of the plan's "
                      "required_credits_by_type")
    credits = req_number(body, "credits", minimum=Decimal("0"),
                         min_exclusive=True)
    # Tier 7: plan APPROVED, then bank OPERATIONAL.
    if plan["status"] != "APPROVED":
        raise api_err("ERR_PLAN_INVALID_STATE",
                      "Credit reservations require an APPROVED plan")
    if bank["status"] != "OPERATIONAL":
        raise api_err("ERR_BANK_NOT_OPERATIONAL",
                      "Credit reservations require an OPERATIONAL bank")
    # Priority 25: in-state service — bank state_code must equal the state
    # code of the site on the plan's application.
    app = STORE["applications"].get(plan["application_id"])
    site = STORE["sites"].get(app["site_id"]) if app else None
    if site is None or bank["state_code"] != site["state_code"]:
        raise api_err("ERR_OUT_OF_SERVICE_AREA",
                      "The bank's state_code differs from the site's "
                      "state_code")
    # Priority 27: sufficient available inventory (exact equality allowed).
    _, _, available, _ = calc.bank_inventory(bank)
    if available.get(resource_type, Decimal("0")) < credits:
        raise api_err("ERR_INSUFFICIENT_CREDIT_INVENTORY",
                      "The bank's available credits for %s are below the "
                      "requested amount" % resource_type)
    txn = new_entity({
        "bank_id": bank["id"],
        "plan_id": plan["id"],
        "resource_type": resource_type,
        "credits": credits,
        "price_per_credit_dollars": None,
        "total_price_dollars": None,
        "status": "RESERVED",
    })
    STORE["credit_txns"][txn["id"]] = txn
    return success_obj(credit_txn_out(txn), 201)


@bp.get("/wetland-permits/credit-transactions")
def list_credit_txns():
    require_roles(list(ALL_ROLES))
    items = apply_filters(STORE["credit_txns"].values(), {
        "bank_id": "bank_id",
        "plan_id": "plan_id",
        "resource_type": "resource_type",
        "status": "status",
    })
    return list_response(items, credit_txn_out)


@bp.get("/wetland-permits/credit-transactions/<id>")
def get_credit_txn(id):
    require_roles(list(ALL_ROLES))
    return success_obj(credit_txn_out(_get_txn_or_404(id)))


@bp.post("/wetland-permits/credit-transactions/<id>/purchase")
def purchase_credit_txn(id):
    user_id, role = require_roles(["Applicant"])
    txn = _get_txn_or_404(id)
    check_ownership(user_id, role, _txn_owner_applicant_id(txn))
    get_body()
    if txn["status"] != "RESERVED":
        raise api_err("ERR_CREDIT_TXN_INVALID_STATE",
                      "Only a RESERVED transaction can be purchased")
    bank = STORE["banks"].get(txn["bank_id"])
    unit, total = calc.purchase_pricing(bank, txn["resource_type"],
                                        txn["credits"])
    txn["price_per_credit_dollars"] = unit
    txn["total_price_dollars"] = total
    txn["status"] = "PURCHASED"
    bump(txn)
    return success_obj(credit_txn_out(txn))


@bp.post("/wetland-permits/credit-transactions/<id>/release")
def release_credit_txn(id):
    user_id, role = require_roles(["Applicant"])
    txn = _get_txn_or_404(id)
    check_ownership(user_id, role, _txn_owner_applicant_id(txn))
    get_body()
    if txn["status"] != "RESERVED":
        raise api_err("ERR_CREDIT_TXN_INVALID_STATE",
                      "Only a RESERVED transaction can be released")
    txn["status"] = "RELEASED"
    bump(txn)
    return success_obj(credit_txn_out(txn))
