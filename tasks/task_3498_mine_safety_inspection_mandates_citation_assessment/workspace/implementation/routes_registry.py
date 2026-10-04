"""Operator, Mine, and Inspector registry endpoints (PRD section 3.1)."""
from flask import Blueprint

import store
from constants import BUSINESS_READ_ROLES, CERTIFICATIONS, MINE_TYPES, ROLE_MSHA_ADMIN
from envelope import list_response, ok_object
from errors import ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE
from serialize import inspector as ser_inspector, mine as ser_mine, operator as ser_operator
from validate import ensure_empty_body, get_or_404, parse_body, require_roles

bp = Blueprint("registry", __name__, url_prefix="/msha")


# --- Operator ---
@bp.route("/operators", methods=["POST"])
def create_operator():
    require_roles(ROLE_MSHA_ADMIN)
    body = parse_body({
        "legal_name": ("str", True),
        "annual_tonnage_tons": ("int", True, 0),
        "home_district": ("str", True),
    })
    entity = store.new_entity(store.operators, {
        "legal_name": body["legal_name"],
        "annual_tonnage_tons": body["annual_tonnage_tons"],
        "home_district": body["home_district"],
    })
    return ok_object(ser_operator(entity), 201)


@bp.route("/operators/<operatorId>", methods=["GET"])
def get_operator(operatorId):
    require_roles(*BUSINESS_READ_ROLES)
    return ok_object(ser_operator(get_or_404(store.operators, operatorId, "operator")))


@bp.route("/operators/<operatorId>/mines", methods=["GET"])
def list_operator_mines(operatorId):
    require_roles(*BUSINESS_READ_ROLES)
    get_or_404(store.operators, operatorId, "operator")
    items = [m for m in store.mines.values() if m["operator_id"] == operatorId]
    return list_response(items, ser_mine)


# --- Mine ---
@bp.route("/mines", methods=["POST"])
def create_mine():
    require_roles(ROLE_MSHA_ADMIN)
    body = parse_body({
        "operator_id": ("str", True),
        "mine_name": ("str", True),
        "mine_type": ("enum", True, MINE_TYPES),
        "activation_date": ("date", True),
    })
    get_or_404(store.operators, body["operator_id"], "operator")
    entity = store.new_entity(store.mines, {
        "operator_id": body["operator_id"],
        "mine_name": body["mine_name"],
        "mine_type": body["mine_type"],
        "activation_date": body["activation_date"],
        "status": "ACTIVE",
        "production_status": "NORMAL",
        "pov_status": "NONE",
    })
    return ok_object(ser_mine(entity), 201)


@bp.route("/mines/<mineId>", methods=["GET"])
def get_mine(mineId):
    require_roles(*BUSINESS_READ_ROLES)
    return ok_object(ser_mine(get_or_404(store.mines, mineId, "mine")))


@bp.route("/mines/<mineId>/idle", methods=["POST"])
def idle_mine(mineId):
    require_roles(ROLE_MSHA_ADMIN)
    ensure_empty_body()
    mine = get_or_404(store.mines, mineId, "mine")
    if mine["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, "only an ACTIVE mine can be idled")
    mine["status"] = "IDLED"
    store.touch(mine)
    return ok_object(ser_mine(mine))


@bp.route("/mines/<mineId>/reactivate", methods=["POST"])
def reactivate_mine(mineId):
    require_roles(ROLE_MSHA_ADMIN)
    ensure_empty_body()
    mine = get_or_404(store.mines, mineId, "mine")
    if mine["status"] != "IDLED":
        raise ApiError(ERR_INVALID_STATE, "only an IDLED mine can be reactivated")
    mine["status"] = "ACTIVE"
    store.touch(mine)
    return ok_object(ser_mine(mine))


# --- Inspector ---
@bp.route("/inspectors", methods=["POST"])
def create_inspector():
    require_roles(ROLE_MSHA_ADMIN)
    body = parse_body({
        "full_name": ("str", True),
        "badge_number": ("str", True),
        "district_code": ("str", True),
        "certification": ("enum", True, CERTIFICATIONS),
        "conflicted_operator_ids": ("str_list", False),
    })
    badge = body["badge_number"]
    if any(other["badge_number"] == badge for other in store.inspectors.values()):
        raise ApiError(ERR_INVALID_REQUEST, "badge_number must be unique across inspectors")
    entity = store.new_entity(store.inspectors, {
        "full_name": body["full_name"],
        "badge_number": badge,
        "district_code": body["district_code"],
        "certification": body["certification"],
        "conflicted_operator_ids": body["conflicted_operator_ids"] or [],
    })
    return ok_object(ser_inspector(entity), 201)


@bp.route("/inspectors/<inspectorId>", methods=["GET"])
def get_inspector(inspectorId):
    require_roles(*BUSINESS_READ_ROLES)
    return ok_object(ser_inspector(get_or_404(store.inspectors, inspectorId, "inspector")))
