"""FinancingDraw routes."""
from flask import Blueprint

import db
import domain
from errors import ApiError, ok
from util import (body, new_id, now_iso, paginate_args, paginate_list,
                  req_int, req_string, require_roles, touch)

bp = Blueprint("draws", __name__)


@bp.route("/performance-contracts/<contractId>/financing-facilities/<facilityId>/draws", methods=["POST"])
def create_draw(contractId, facilityId):
    require_roles("ESCOEngineer")
    _, f = domain.get_facility(contractId, facilityId)
    data = body()
    rec = {
        "id": new_id(),
        "facility_id": f["id"],
        "amount_cents": req_int(data, "amount_cents", min_v=1),
        "purpose": req_string(data, "purpose"),
        "status": "REQUESTED",
        "created_at": now_iso(),
    }
    db.draws[rec["id"]] = rec
    return ok(domain.ser_draw(rec), code=201)


@bp.route("/performance-contracts/<contractId>/financing-facilities/<facilityId>/draws", methods=["GET"])
def list_draws(contractId, facilityId):
    require_roles()
    _, f = domain.get_facility(contractId, facilityId)
    limit, offset = paginate_args()
    items = [d for d in db.draws.values() if d["facility_id"] == f["id"]]
    items.sort(key=lambda d: (d["created_at"], d["id"]))
    page, meta = paginate_list(items, limit, offset)
    return ok([domain.ser_draw(d) for d in page], response_type="array", pagination=meta)


@bp.route("/performance-contracts/<contractId>/financing-facilities/<facilityId>/draws/<drawId>/approve", methods=["POST"])
def approve_draw(contractId, facilityId, drawId):
    require_roles("LenderOfficer")
    _, f, d = domain.get_draw(contractId, facilityId, drawId)
    if d["status"] != "REQUESTED":
        raise ApiError("ERR_DRAW_NOT_REQUESTED", 409, "draw must be in REQUESTED")
    if f["status"] != "FUNDING":
        raise ApiError("ERR_FACILITY_NOT_FUNDING", 409, "facility must be in FUNDING")
    pending = sum(x["amount_cents"] for x in db.draws.values()
                  if x["facility_id"] == f["id"] and x["id"] != d["id"]
                  and x["status"] == "APPROVED")
    if d["amount_cents"] > f["principal_cents"] - f["drawn_cents"] - pending:
        raise ApiError("ERR_DRAW_EXCEEDS_AVAILABLE", 422,
                       "draw exceeds the remaining availability")
    d["status"] = "APPROVED"
    return ok(domain.ser_draw(d))


@bp.route("/performance-contracts/<contractId>/financing-facilities/<facilityId>/draws/<drawId>/release", methods=["POST"])
def release_draw(contractId, facilityId, drawId):
    require_roles("LenderOfficer")
    _, f, d = domain.get_draw(contractId, facilityId, drawId)
    if d["status"] != "APPROVED":
        raise ApiError("ERR_DRAW_NOT_APPROVED", 409, "draw must be in APPROVED")
    d["status"] = "RELEASED"
    f["drawn_cents"] += d["amount_cents"]
    touch(f)
    return ok(domain.ser_draw(d))


@bp.route("/performance-contracts/<contractId>/financing-facilities/<facilityId>/draws/<drawId>/reject", methods=["POST"])
def reject_draw(contractId, facilityId, drawId):
    require_roles("LenderOfficer")
    _, f, d = domain.get_draw(contractId, facilityId, drawId)
    if d["status"] != "REQUESTED":
        raise ApiError("ERR_DRAW_NOT_REQUESTED", 409, "draw must be in REQUESTED")
    d["status"] = "REJECTED"
    return ok(domain.ser_draw(d))
