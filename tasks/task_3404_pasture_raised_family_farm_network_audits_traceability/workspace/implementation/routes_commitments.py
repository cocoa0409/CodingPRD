"""Weekly supply commitments (PRD 3.7, 2.1).

POST /farm-network/commitments        (NetworkManager, 201)
GET  /farm-network/commitments        (NM, PA, RetailerBuyer scoped, 200)
GET  /farm-network/commitments/{id}   (NM, PA, RetailerBuyer scoped, 200)
"""
from flask import Blueprint, request

import domain
import store
from auth import authenticate, authorize
from clock import now
from errors import ApiError
from responses import ok, ok_list
from serialize import commitment_out
from validation import MISSING, get_body, f_int, f_date, pagination

bp = Blueprint("commitments", __name__, url_prefix="/farm-network")


@bp.route("/commitments", methods=["POST"])
def create_commitment():
    uid, role = authenticate()
    authorize(role, ("NetworkManager",))
    data = get_body()
    # Body references resolve first (priority 5), retailer then farm.
    retailer_id = data.get("retailer_id", MISSING)
    if retailer_id is MISSING:
        raise ApiError("ERR_INVALID_REQUEST", 400, "missing required field: retailer_id")
    retailer = store.retailers.get(retailer_id) if isinstance(retailer_id, str) else None
    if retailer is None:
        raise ApiError("ERR_RETAILER_NOT_FOUND", 404, "retailer not found")
    farm_id = data.get("farm_id", MISSING)
    if farm_id is MISSING:
        raise ApiError("ERR_INVALID_REQUEST", 400, "missing required field: farm_id")
    farm = store.farms.get(farm_id) if isinstance(farm_id, str) else None
    if farm is None:
        raise ApiError("ERR_FARM_NOT_FOUND", 404, "farm not found")
    # Well-formed body (priority 6).
    week_raw, week = f_date(data, "week_start")
    committed = f_int(data, "committed_dozens", minimum=1)
    # State legality (priority 7).
    if farm["status"] != "ACTIVE":
        raise ApiError("ERR_FARM_NOT_ACTIVE", 409, "farm is not ACTIVE")
    # Certification gate (priority 9).
    if domain.derive_certification_status(farm) != "CERTIFIED":
        raise ApiError("ERR_CERTIFICATION_NOT_CURRENT", 422,
                       "farm certification must be CERTIFIED to create a commitment")
    # Referential (priority 10): a contract of any status covering the week,
    # then an existing forecast for (farm, week_start).
    if domain.find_covering_contract(farm["id"], week, require_active=False) is None:
        raise ApiError("ERR_CONTRACT_REQUIRED", 422,
                       "no contract covers the committed week")
    forecast = None
    for f in store.forecasts.values():
        if f["farm_id"] == farm["id"] and f["week_start"] == week_raw:
            forecast = f
            break
    if forecast is None:
        raise ApiError("ERR_FORECAST_REQUIRED", 422,
                       "no production forecast exists for this farm and week")
    # Capacity (priority 13): cumulative cap, inclusive at equality.
    cap = domain.commitment_cap(forecast["conservative_dozens"])
    total = sum(cm["committed_dozens"] for cm in store.commitments.values()
                if cm["farm_id"] == farm["id"] and cm["week_start"] == week_raw
                and cm["status"] in ("ACTIVE", "FILLED", "SHORTFALL"))
    if total + committed > cap:
        raise ApiError("ERR_COMMITMENT_EXCEEDS_FORECAST", 422,
                       "cumulative committed dozens would exceed the commitment cap")
    ts = now()
    commitment = {
        "id": domain.new_id(),
        "farm_id": farm["id"],
        "retailer_id": retailer["id"],
        "week_start": week_raw,
        "committed_dozens": committed,
        "status": "ACTIVE",
        "delivered_dozens": None,
        "fill_rate": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_week_start": week,
        "_seq": store.next_seq(),
    }
    store.commitments[commitment["id"]] = commitment
    return ok(commitment_out(commitment), 201)


@bp.route("/commitments", methods=["GET"])
def list_commitments():
    uid, role = authenticate()
    authorize(role, ("NetworkManager", "PlatformAdmin", "RetailerBuyer"))
    # Retailer scoping (priority 3): a buyer must pass retailer_id equal to
    # its own account id.
    if role == "RetailerBuyer":
        rid = request.args.get("retailer_id")
        if not rid or rid != uid:
            raise ApiError("ERR_FORBIDDEN", 403,
                           "RetailerBuyer must filter by its own retailer_id")
    limit, offset = pagination()
    farm_id = request.args.get("farm_id")
    retailer_id = request.args.get("retailer_id")
    week_start = request.args.get("week_start")
    status = request.args.get("status")
    rows = list(store.commitments.values())
    if farm_id is not None:
        rows = [c for c in rows if c["farm_id"] == farm_id]
    if retailer_id is not None:
        rows = [c for c in rows if c["retailer_id"] == retailer_id]
    if week_start is not None:
        rows = [c for c in rows if c["week_start"] == week_start]
    if status is not None:
        rows = [c for c in rows if c["status"] == status]
    page, total = domain.sorted_page(rows, limit, offset)
    return ok_list([commitment_out(c) for c in page], limit, offset, total)


@bp.route("/commitments/<cid>", methods=["GET"])
def get_commitment(cid):
    uid, role = authenticate()
    authorize(role, ("NetworkManager", "PlatformAdmin", "RetailerBuyer"))
    commitment = domain.get_commitment_or_404(cid)
    if role == "RetailerBuyer" and commitment["retailer_id"] != uid:
        raise ApiError("ERR_FORBIDDEN", 403,
                       "RetailerBuyer may only read its own account's commitments")
    return ok(commitment_out(commitment))
