"""Imminent-danger order endpoints (PRD section 3.5)."""
from flask import Blueprint, g, request

import clock
import services_ido
import store
from constants import BUSINESS_READ_ROLES, ROLE_DISTRICT_MANAGER, ROLE_INSPECTOR
from envelope import list_response, ok_object
from errors import (
    ApiError,
    ERR_INSPECTOR_MISMATCH,
    ERR_INVALID_STATE,
    ERR_MINE_NOT_ACTIVE,
    ERR_SOD_VERIFY_SELF,
)
from serialize import imminent_danger_order as ser_ido
from validate import ensure_empty_body, get_or_404, parse_body, require_roles

bp = Blueprint("idos", __name__, url_prefix="/msha")


@bp.route("/imminent-danger-orders", methods=["POST"])
def create_ido():
    require_roles(ROLE_INSPECTOR)
    body = parse_body({
        "mine_id": ("str", True),
        "hazard_description": ("str", True),
        "inspection_id": ("str", False),
    })
    mine = get_or_404(store.mines, body["mine_id"], "mine")
    inspection = None
    if body["inspection_id"] is not None:
        inspection = get_or_404(store.inspections, body["inspection_id"], "inspection")
    # Tier 6: the inspection named on a manual IDO must belong to the caller.
    if inspection is not None and inspection["inspector_id"] != g.uid:
        raise ApiError(
            ERR_INSPECTOR_MISMATCH,
            "the named inspection is not assigned to the acting inspector",
        )
    # Tier 7 state preconditions.
    if mine["status"] != "ACTIVE":
        raise ApiError(ERR_MINE_NOT_ACTIVE, "an IDLED mine cannot accept a new imminent-danger order")
    if inspection is not None and (
        inspection["status"] != "IN_PROGRESS" or inspection["mine_id"] != mine["id"]
    ):
        raise ApiError(
            ERR_INVALID_STATE,
            "the named inspection must be IN_PROGRESS at this mine",
        )
    # Tier 10: one-active-order rule with closed-interval occupation.
    services_ido.assert_issuable(mine["id"], clock.now())
    order = services_ido.create_ido(
        mine,
        body["hazard_description"],
        inspection["id"] if inspection is not None else None,
        g.uid,
    )
    return ok_object(ser_ido(order), 201)


@bp.route("/imminent-danger-orders/<orderId>", methods=["GET"])
def get_ido(orderId):
    require_roles(*BUSINESS_READ_ROLES)
    return ok_object(ser_ido(get_or_404(store.idos, orderId, "imminent-danger order")))


@bp.route("/imminent-danger-orders", methods=["GET"])
def list_idos():
    require_roles(*BUSINESS_READ_ROLES)
    items = list(store.idos.values())
    for param in ("mine_id", "inspection_id", "issued_by_inspector_id", "verified_by_inspector_id", "status"):
        value = request.args.get(param)
        if value is not None:
            items = [o for o in items if o.get(param) is not None and o[param] == value]
    return list_response(items, ser_ido)


@bp.route("/imminent-danger-orders/<orderId>/confirm-withdrawal", methods=["POST"])
def confirm_withdrawal(orderId):
    require_roles(ROLE_INSPECTOR)
    body = parse_body({"miners_withdrawn_count": ("int", True, 0)})
    order = get_or_404(store.idos, orderId, "imminent-danger order")
    if order["status"] != "ISSUED":
        raise ApiError(ERR_INVALID_STATE, "withdrawal confirmation requires ISSUED status")
    order["miners_withdrawn_count"] = body["miners_withdrawn_count"]
    order["withdrawal_confirmed_at"] = clock.now()
    order["status"] = "WITHDRAWAL_CONFIRMED"
    store.touch(order)
    return ok_object(ser_ido(order))


@bp.route("/imminent-danger-orders/<orderId>/verify-abatement", methods=["POST"])
def verify_ido_abatement(orderId):
    require_roles(ROLE_INSPECTOR)
    parse_body({"abatement_note": ("str", True)})
    order = get_or_404(store.idos, orderId, "imminent-danger order")
    # Segregation of duties (tier 6) precedes the state check (tier 7).
    if g.uid == order["issued_by_inspector_id"]:
        raise ApiError(
            ERR_SOD_VERIFY_SELF,
            "the issuing inspector cannot verify abatement of this order",
        )
    if order["status"] != "WITHDRAWAL_CONFIRMED":
        raise ApiError(ERR_INVALID_STATE, "abatement verification requires WITHDRAWAL_CONFIRMED status")
    order["abatement_verified_at"] = clock.now()
    order["verified_by_inspector_id"] = g.uid
    order["status"] = "ABATEMENT_VERIFIED"
    store.touch(order)
    return ok_object(ser_ido(order))


@bp.route("/imminent-danger-orders/<orderId>/terminate", methods=["POST"])
def terminate_ido(orderId):
    require_roles(ROLE_DISTRICT_MANAGER)
    ensure_empty_body()
    order = get_or_404(store.idos, orderId, "imminent-danger order")
    if order["status"] != "ABATEMENT_VERIFIED":
        raise ApiError(ERR_INVALID_STATE, "termination requires ABATEMENT_VERIFIED status")
    order["status"] = "TERMINATED"
    order["terminated_at"] = clock.now()
    store.touch(order)
    services_ido.terminate_cascade(order)
    return ok_object(ser_ido(order))
