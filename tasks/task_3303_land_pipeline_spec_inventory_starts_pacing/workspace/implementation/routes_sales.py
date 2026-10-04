"""Routes: sales contracts."""

from flask import Blueprint

from db import db, iso3
from errors import ApiError
from helpers import (
    auth, require_role, body, idem_begin, require_fields,
    fresh_row, touch, get_or_404, clock,
)
from response import success_obj
import services as svc

bp = Blueprint("sales", __name__)


def _terminate_side_effects(contract, home):
    """Home returns to UNSOLD; posture recompute happens implicitly via
    computed reads; incentive auto-activation is status-derived."""
    prior_posture = svc.posture_of(home["community_id"])[4]
    home["sales_status"] = "UNSOLD"
    touch(home)
    new_posture = svc.posture_of(home["community_id"])[4]
    if new_posture == "OVERHELD" and prior_posture != "OVERHELD":
        # Flagged incentives become ACTIVE (status is clock-derived), so the
        # only concrete work is recomputing applicable home prices.
        svc.refresh_community_home_pricing(home["community_id"])


@bp.post("/sales-contracts")
def create_sales_contract():
    role, _ = auth()
    ctx = idem_begin()
    require_role(role, ["SALES_AGENT"])
    b = body()
    require_fields(b, [
        ("home_id", "string", None, False),
        ("buyer_name", "string", None, False),
        ("contract_price_cents", "integer", None, False),
    ])
    home = get_or_404(db.homes, b["home_id"])
    if home["sales_status"] != "UNSOLD":
        raise ApiError("ERR_HOME_NOT_UNSOLD", 409, "Home is not UNSOLD")
    row = fresh_row()
    row.update({
        "home_id": home["id"],
        "buyer_name": b["buyer_name"],
        "contract_price_cents": b["contract_price_cents"],
        "state": "PENDING",
        "approved_at": None,
        "closed_at": None,
        "renegotiation_count": 0,
    })
    db.sales_contracts[row["id"]] = row
    home["sales_status"] = "RESERVED"
    touch(home)
    return success_obj(svc.ser_sales_contract(row), status=201)


@bp.get("/sales-contracts/<sid>")
def get_sales_contract(sid):
    auth()
    sc = get_or_404(db.sales_contracts, sid)
    return success_obj(svc.ser_sales_contract(sc))


@bp.post("/sales-contracts/<sid>/approve")
def approve_sales_contract(sid):
    role, _ = auth()
    ctx = idem_begin()
    sc = get_or_404(db.sales_contracts, sid)
    require_role(role, ["COMMUNITY_MANAGER"])
    body()
    if sc["state"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "Contract is not PENDING")
    home = db.homes[sc["home_id"]]
    # Refresh pricing so the floor is evaluated at approval time.
    home.update(svc.compute_home_pricing(home))
    if sc["contract_price_cents"] < home["net_effective_price_cents"]:
        raise ApiError(
            "ERR_PRICE_BELOW_NET_FLOOR", 422,
            "contract_price_cents is below the home's net effective price",
        )
    sc["state"] = "APPROVED"
    sc["approved_at"] = iso3(clock())
    touch(sc)
    home["sales_status"] = "SOLD"
    touch(home)
    return success_obj(svc.ser_sales_contract(sc))


@bp.post("/sales-contracts/<sid>/renegotiate")
def renegotiate_sales_contract(sid):
    role, _ = auth()
    ctx = idem_begin()
    sc = get_or_404(db.sales_contracts, sid)
    require_role(role, ["SALES_AGENT"])
    b = body()
    require_fields(b, [("contract_price_cents", "integer", None, False)])
    if sc["state"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", 409, "Contract is not APPROVED")
    sc["state"] = "PENDING"
    sc["contract_price_cents"] = b["contract_price_cents"]
    sc["renegotiation_count"] = sc.get("renegotiation_count", 0) + 1
    touch(sc)
    home = db.homes[sc["home_id"]]
    home["sales_status"] = "RESERVED"
    touch(home)
    return success_obj(svc.ser_sales_contract(sc))


@bp.post("/sales-contracts/<sid>/close")
def close_sales_contract(sid):
    role, _ = auth()
    ctx = idem_begin()
    sc = get_or_404(db.sales_contracts, sid)
    require_role(role, ["COMMUNITY_MANAGER"])
    body()
    if sc["state"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", 409, "Contract is not APPROVED")
    home = db.homes[sc["home_id"]]
    if home["build_stage"] != "COMPLETE":
        raise ApiError("ERR_HOME_NOT_COMPLETE", 409, "Home build_stage is not COMPLETE")
    sc["state"] = "CLOSED"
    sc["closed_at"] = iso3(clock())
    touch(sc)
    home["sales_status"] = "CLOSED_SALE"
    home["build_stage"] = "CLOSED"
    home.update(svc.compute_home_pricing(home))
    touch(home)
    return success_obj(svc.ser_sales_contract(sc))


@bp.post("/sales-contracts/<sid>/terminate")
def terminate_sales_contract(sid):
    role, _ = auth()
    ctx = idem_begin()
    sc = get_or_404(db.sales_contracts, sid)
    require_role(role, ["SALES_AGENT"])
    body()
    if sc["state"] in ("CLOSED", "TERMINATED"):
        raise ApiError(
            "ERR_SALES_CONTRACT_NOT_TERMINABLE", 409,
            "Contract cannot be terminated from state " + sc["state"],
        )
    if sc["state"] not in ("PENDING", "APPROVED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Contract cannot be terminated")
    sc["state"] = "TERMINATED"
    touch(sc)
    home = db.homes[sc["home_id"]]
    _terminate_side_effects(sc, home)
    return success_obj(svc.ser_sales_contract(sc))
