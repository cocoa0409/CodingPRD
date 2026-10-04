"""CoordinationRequest endpoints: reads and neighbor respond (PRD §3.5)."""
from flask import Blueprint, request

from auth import authenticate, check_office_scope, require_role
from constants import COORDINATION_OUTCOMES
from db import STORE, now
from errors import api_error
from serialize import serialize
from util import envelope, get_body, list_response, touch

bp = Blueprint("coordinations", __name__, url_prefix="/alerts")

FORECASTING = ["Forecaster", "MeteorologistInCharge"]
ANY_ROLE = ["PlatformAdmin", "Forecaster", "MeteorologistInCharge", "VerificationAnalyst", "EmergencyManager"]


def _get_coord_or_404(coord_id):
    coord = STORE["coordinations"].get(coord_id)
    if coord is None:
        raise api_error(
            "ERR_COORDINATION_REQUEST_NOT_FOUND", "CoordinationRequest %s does not exist." % coord_id
        )
    return coord


@bp.get("/coordination-requests/<coord_id>")
def get_coordination(coord_id):
    role, _uid, _fc = authenticate()
    require_role(role, ANY_ROLE)
    return envelope(serialize(_get_coord_or_404(coord_id)), "object", 200)


@bp.get("/coordination-requests")
def list_coordinations():
    role, _uid, _fc = authenticate()
    require_role(role, ANY_ROLE)
    rows = list(STORE["coordinations"].values())
    for field in ("product_id", "from_office_id", "to_office_id", "status"):
        value = request.args.get(field)
        if value is not None:
            rows = [c for c in rows if c.get(field) == value]
    return list_response(rows, serialize)


@bp.post("/coordination-requests/<coord_id>/respond")
def respond_coordination(coord_id):
    role, _uid, forecaster = authenticate()
    require_role(role, FORECASTING)
    body = get_body()
    # tier 4: schema
    outcome = body.get("outcome")
    if outcome not in COORDINATION_OUTCOMES:
        raise api_error(
            "ERR_INVALID_REQUEST", "outcome must be one of %s" % COORDINATION_OUTCOMES
        )
    # tier 5: path existence
    coord = _get_coord_or_404(coord_id)
    # tier 3: office scope — the request's target office
    check_office_scope(forecaster, coord["to_office_id"])
    # tier 7: state
    if coord["status"] != "REQUESTED":
        raise api_error(
            "ERR_INVALID_COORDINATION_STATE", "CoordinationRequest is no longer REQUESTED."
        )
    stamp = now()
    coord["responded_at"] = stamp
    if outcome == "ACKNOWLEDGED":
        coord["status"] = "ACKNOWLEDGED"
        touch(coord)
        return envelope(serialize(coord), "object", 200)
    # DECLINED: respond, revert the linked product PENDING_COORDINATION -> DRAFT,
    # and (caused by the reversion) cancel still-REQUESTED sibling requests
    coord["status"] = "DECLINED"
    touch(coord)
    product = STORE["products"].get(coord["product_id"])
    if product is not None and product["status"] == "PENDING_COORDINATION":
        product["status"] = "DRAFT"
        touch(product)
        for sibling in STORE["coordinations"].values():
            if (
                sibling["product_id"] == product["id"]
                and sibling["id"] != coord["id"]
                and sibling["status"] == "REQUESTED"
            ):
                sibling["status"] = "CANCELLED"
                touch(sibling)
    return envelope(serialize(coord), "object", 200)
