"""Logical clock, territories, and the wholesaler registry (§2.5, §3.1)."""

from flask import Blueprint, request

import cascades
import clock
import db
from auth import ALL_ROLES, ROLE_BREWER_ADMIN, require_roles
from envelope import created, ok, paginate
from errors import ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from validate import field, get_body, validate_body

bp = Blueprint("core", __name__)

SUPPLIER_TYPES = ("CRAFT", "IMPORT", "DOMESTIC_PREMIUM")
WHOLESALER_TIERS = ("GOLD", "SILVER", "BRONZE")


@bp.route("/_clock/set_current_utc", methods=["POST"])
@require_roles(ROLE_BREWER_ADMIN)
def set_current_utc(user_id, caller_role):
    data, _ = validate_body(get_body(), {"to_iso8601": field("datetime", required=True)})
    new_clock = clock.parse_iso(data["to_iso8601"])
    clock.set_now(new_clock)
    sweeps = cascades.run_clock_sweeps(new_clock)
    payload = {"current_utc": clock.format_iso(new_clock)}
    payload.update(sweeps)
    return ok(payload)


@bp.route("/territories", methods=["POST"])
@require_roles(ROLE_BREWER_ADMIN)
def create_territory(user_id, caller_role):
    data, _ = validate_body(get_body(), {
        "name": field("string", required=True),
        "state_code": field("string", required=True),
    })
    territory = db.stamped()
    territory.update({
        "name": data["name"],
        "state_code": data["state_code"],
        "status": "VACANT",
        "incumbent_wholesaler_id": None,
    })
    db.territories[territory["id"]] = territory
    return created(territory)


@bp.route("/territories/<tid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_territory(tid, user_id, caller_role):
    territory = db.territories.get(tid)
    if territory is None:
        raise ApiError(ERR_NOT_FOUND, "Territory not found", 404)
    return ok(territory)


@bp.route("/territories/<tid>/agreements", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_territory_agreements(tid, user_id, caller_role):
    if tid not in db.territories:
        raise ApiError(ERR_NOT_FOUND, "Territory not found", 404)
    rows = [a for a in db.agreements.values() if a["territory_id"] == tid]
    return paginate(rows, status_filter=request.args.get("status"))


def _check_supplier_book(entries):
    for entry in entries:
        if not isinstance(entry, dict):
            raise ApiError(ERR_INVALID_REQUEST,
                           "supplier_book entries must be objects", 400)
        if not isinstance(entry.get("supplier_name"), str):
            raise ApiError(ERR_INVALID_REQUEST,
                           "supplier_book entries require a supplier_name", 400)
        if entry.get("supplier_type") not in SUPPLIER_TYPES:
            raise ApiError(ERR_INVALID_REQUEST,
                           "supplier_type must be CRAFT, IMPORT or DOMESTIC_PREMIUM",
                           400)
        added_at = entry.get("added_at")
        if added_at is not None and not isinstance(added_at, str):
            raise ApiError(ERR_INVALID_REQUEST,
                           "supplier_book added_at must be a string", 400)


@bp.route("/wholesalers", methods=["POST"])
@require_roles(ROLE_BREWER_ADMIN)
def create_wholesaler(user_id, caller_role):
    data, _ = validate_body(get_body(), {
        "legal_name": field("string", required=True),
        "home_state": field("string", required=True),
        "license_number": field("string", required=True),
        "tier": field("enum", required=True, enum=WHOLESALER_TIERS),
        "holds_retail_interest": field("boolean", default=False),
        "financial_capacity_score": field("integer", required=True),
        "warehouse_capacity_score": field("integer", required=True),
        "market_coverage_score": field("integer", required=True),
        "supplier_book": field("array", default=[]),
    })
    _check_supplier_book(data["supplier_book"])
    wholesaler = db.stamped()
    wholesaler.update({
        "legal_name": data["legal_name"],
        "home_state": data["home_state"],
        "license_number": data["license_number"],
        "tier": data["tier"],
        "holds_retail_interest": data["holds_retail_interest"],
        "financial_capacity_score": data["financial_capacity_score"],
        "warehouse_capacity_score": data["warehouse_capacity_score"],
        "market_coverage_score": data["market_coverage_score"],
        "supplier_book": data["supplier_book"],
        "status": "APPLICANT",
        "suspended_account_count": 0,
    })
    db.wholesalers[wholesaler["id"]] = wholesaler
    return created(wholesaler)


@bp.route("/wholesalers/<wid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_wholesaler(wid, user_id, caller_role):
    wholesaler = db.wholesalers.get(wid)
    if wholesaler is None:
        raise ApiError(ERR_NOT_FOUND, "Wholesaler not found", 404)
    return ok(wholesaler)


@bp.route("/wholesalers/<wid>/agreements", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_wholesaler_agreements(wid, user_id, caller_role):
    if wid not in db.wholesalers:
        raise ApiError(ERR_NOT_FOUND, "Wholesaler not found", 404)
    rows = [a for a in db.agreements.values() if a["wholesaler_id"] == wid]
    return paginate(rows, status_filter=request.args.get("status"))


@bp.route("/wholesalers/<wid>/retail-accounts", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_wholesaler_accounts(wid, user_id, caller_role):
    if wid not in db.wholesalers:
        raise ApiError(ERR_NOT_FOUND, "Wholesaler not found", 404)
    rows = [a for a in db.accounts.values() if a["serving_wholesaler_id"] == wid]
    return paginate(rows, status_filter=request.args.get("status"))


@bp.route("/wholesalers/<wid>/performance-reviews", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_wholesaler_reviews(wid, user_id, caller_role):
    if wid not in db.wholesalers:
        raise ApiError(ERR_NOT_FOUND, "Wholesaler not found", 404)
    rows = [r for r in db.reviews.values() if r["wholesaler_id"] == wid]
    return paginate(rows, status_filter=request.args.get("status"))
