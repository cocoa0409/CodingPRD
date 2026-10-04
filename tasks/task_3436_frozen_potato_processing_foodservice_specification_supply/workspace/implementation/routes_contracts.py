"""Crop contract endpoints: creation, amendment cycle, shortfall, settlement.

Validation precedence follows PRD section 2.10: shape (4) -> existence (5) ->
state (6) -> structural / delivery-window overlap (8) -> OCC (12).
"""

import domain
from db import store
from errors import ApiError
from flask import Blueprint, request
from middleware import ANY_ROLES, require_roles
from response import list_response, sort_default, success_object
from util import body_json, req_dt, req_enum, req_int, req_number, req_str, round_half_up
from constants import VARIETIES

bp = Blueprint("contracts", __name__)

_BLOCKING_STATUSES = ("DRAFT", "ACTIVE", "AMENDMENT_PENDING")


def _overlaps_sibling(grower_id, variety, start, end, exclude_id=None):
    """delivery_window_overlap: half-open [start, end); adjacency allowed;
    only non-terminal siblings of the same grower+variety block."""
    for other in store.contracts.values():
        if other["id"] == exclude_id:
            continue
        if other["grower_id"] != grower_id or other["variety"] != variety:
            continue
        if other["status"] not in _BLOCKING_STATUSES:
            continue
        if other["delivery_window_start"] < end and start < other["delivery_window_end"]:
            return True
    return False


def _read_terms(body, prefix=""):
    acres = req_number(body, "contracted_acres")
    if acres <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "Field 'contracted_acres': must be > 0", 400)
    yld = req_number(body, "expected_yield_cwt_per_acre")
    if yld <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "Field 'expected_yield_cwt_per_acre': must be > 0", 400)
    base = req_int(body, "base_price_per_cwt_cents")
    if base <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "Field 'base_price_per_cwt_cents': must be > 0", 400)
    start = req_dt(body, "delivery_window_start")
    end = req_dt(body, "delivery_window_end")
    if not end > start:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "Field 'delivery_window_end': must be strictly after delivery_window_start",
            400,
        )
    return acres, yld, base, start, end


@bp.route("/potato-ops/crop-contracts", methods=["POST"])
@require_roles("GrowerRelationsManager")
def create_contract():
    body = body_json()
    grower_id = req_str(body, "grower_id")
    variety = req_enum(body, "variety", VARIETIES)
    acres, yld, base, start, end = _read_terms(body)
    domain.get_grower_or_404(grower_id)
    if _overlaps_sibling(grower_id, variety, start, end):
        raise ApiError(
            "ERR_DELIVERY_WINDOW_OVERLAP",
            "Delivery window overlaps a sibling non-terminal contract of the same grower and variety",
            409,
        )
    c = domain.new_entity()
    c.update({
        "grower_id": grower_id,
        "variety": variety,
        "contracted_acres": acres,
        "expected_yield_cwt_per_acre": yld,
        "contracted_volume_cwt": round_half_up(acres * yld, 1),
        "base_price_per_cwt_cents": base,
        "delivery_window_start": start,
        "delivery_window_end": end,
        "pending_amendment": None,
        "settlement_amount_cents": None,
        "status": "DRAFT",
    })
    store.contracts[c["id"]] = c
    return success_object(domain.contract_view(c), 201)


@bp.route("/potato-ops/crop-contracts", methods=["GET"])
@require_roles(*ANY_ROLES)
def list_contracts():
    items = list(store.contracts.values())
    grower_id = request.args.get("grower_id")
    status = request.args.get("status")
    variety = request.args.get("variety")
    if grower_id is not None:
        items = [c for c in items if c["grower_id"] == grower_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    if variety is not None:
        items = [c for c in items if c["variety"] == variety]
    return list_response(sort_default(items), domain.contract_view)


@bp.route("/potato-ops/crop-contracts/<cid>", methods=["GET"])
@require_roles(*ANY_ROLES)
def get_contract(cid):
    return success_object(domain.contract_view(domain.get_contract_or_404(cid)), 200)


@bp.route("/potato-ops/crop-contracts/<cid>/activate", methods=["POST"])
@require_roles("GrowerRelationsManager")
def activate_contract(cid):
    c = domain.get_contract_or_404(cid)
    if c["status"] != "DRAFT":
        raise ApiError("ERR_CONTRACT_NOT_DRAFT", "activate requires the contract in DRAFT", 409)
    domain.get_grower_or_404(c["grower_id"])
    c["status"] = "ACTIVE"
    domain.touch(c)
    return success_object(domain.contract_view(c), 200)


@bp.route("/potato-ops/crop-contracts/<cid>/propose-amendment", methods=["POST"])
@require_roles("GrowerRelationsManager")
def propose_amendment(cid):
    body = body_json()
    acres, yld, base, start, end = _read_terms(body)
    c = domain.get_contract_or_404(cid)
    if c["status"] != "ACTIVE":
        raise ApiError(
            "ERR_CONTRACT_NOT_ACTIVE", "propose-amendment requires the contract ACTIVE", 409
        )
    c["pending_amendment"] = {
        "contracted_acres": acres,
        "expected_yield_cwt_per_acre": yld,
        "base_price_per_cwt_cents": base,
        "delivery_window_start": start,
        "delivery_window_end": end,
    }
    c["status"] = "AMENDMENT_PENDING"
    domain.touch(c)
    return success_object(domain.contract_view(c), 200)


@bp.route("/potato-ops/crop-contracts/<cid>/accept-amendment", methods=["POST"])
@require_roles("GrowerRelationsManager")
def accept_amendment(cid):
    body = body_json()
    expected = req_int(body, "expected_crop_contract_version")
    c = domain.get_contract_or_404(cid)
    if c["status"] != "AMENDMENT_PENDING":
        raise ApiError(
            "ERR_CONTRACT_NOT_IN_AMENDMENT",
            "accept-amendment requires the contract in AMENDMENT_PENDING",
            409,
        )
    pa = c["pending_amendment"]
    if _overlaps_sibling(
        c["grower_id"], c["variety"], pa["delivery_window_start"], pa["delivery_window_end"],
        exclude_id=c["id"],
    ):
        raise ApiError(
            "ERR_DELIVERY_WINDOW_OVERLAP",
            "Amended delivery window overlaps a sibling non-terminal contract of the same grower and variety",
            409,
        )
    if expected != c["version"]:
        raise ApiError(
            "ERR_STALE_VERSION",
            "expected_crop_contract_version does not match the contract's current version",
            412,
        )
    c["contracted_acres"] = pa["contracted_acres"]
    c["expected_yield_cwt_per_acre"] = pa["expected_yield_cwt_per_acre"]
    c["base_price_per_cwt_cents"] = pa["base_price_per_cwt_cents"]
    c["delivery_window_start"] = pa["delivery_window_start"]
    c["delivery_window_end"] = pa["delivery_window_end"]
    c["contracted_volume_cwt"] = round_half_up(
        pa["contracted_acres"] * pa["expected_yield_cwt_per_acre"], 1
    )
    c["pending_amendment"] = None
    c["status"] = "ACTIVE"
    domain.touch(c)
    return success_object(domain.contract_view(c), 200)


@bp.route("/potato-ops/crop-contracts/<cid>/declare-shortfall", methods=["POST"])
@require_roles("GrowerRelationsManager")
def declare_shortfall(cid):
    c = domain.get_contract_or_404(cid)
    if c["status"] != "ACTIVE":
        raise ApiError(
            "ERR_CONTRACT_NOT_ACTIVE", "declare-shortfall requires the contract ACTIVE", 409
        )
    c["status"] = "SHORTFALL_DECLARED"
    domain.settle_contract(c)
    domain.touch(c)
    return success_object(domain.contract_view(c), 200)
