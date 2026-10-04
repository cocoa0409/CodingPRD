"""Farm pricing contracts (PRD 3.1, 2.4).

POST /farm-network/farms/{id}/contracts   (NetworkManager, 201; OCC-guarded)
GET  /farm-network/farms/{id}/contracts   (NetworkManager, PlatformAdmin, 200)
"""
from flask import Blueprint, request

import domain
import store
from auth import authenticate, authorize
from clock import now
from errors import ApiError
from responses import ok, ok_list
from serialize import contract_out
from validation import get_body, f_int, f_date, pagination

bp = Blueprint("contracts", __name__, url_prefix="/farm-network")


@bp.route("/farms/<fid>/contracts", methods=["POST"])
def create_contract(fid):
    uid, role = authenticate()
    authorize(role, ("NetworkManager",))
    farm = domain.get_farm_or_404(fid)
    data = get_body()
    base = f_int(data, "commodity_base_cents_per_dozen", minimum=0)
    premium = f_int(data, "premium_cents_per_dozen", minimum=0)
    start_raw, start = f_date(data, "start_date")
    end_raw, end = f_date(data, "end_date")
    if start > end:
        raise ApiError("ERR_INVALID_REQUEST", 400, "start_date must be on or before end_date")
    expected = f_int(data, "expected_farm_version")
    # State legality (priority 7): mutations on a REMOVED farm are terminal.
    if farm["status"] == "REMOVED":
        raise ApiError("ERR_FARM_TERMINAL", 409, "farm is REMOVED")
    # Optimistic concurrency (priority 8): the only OCC check in the system.
    if expected != farm["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_farm_version does not match the farm's current version")
    ts = now()
    # A new contract supersedes the farm's currently ACTIVE one (single farm
    # version increment covers creation + supersede, PRD 3.1).
    for c in store.contracts.values():
        if c["farm_id"] == farm["id"] and c["status"] == "ACTIVE":
            c["status"] = "SUPERSEDED"
            c["version"] += 1
            c["updated_at"] = ts
    contract = {
        "id": domain.new_id(),
        "farm_id": farm["id"],
        "commodity_base_cents_per_dozen": base,
        "premium_cents_per_dozen": premium,
        "start_date": start_raw,
        "end_date": end_raw,
        "status": "ACTIVE",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_start": start,
        "_end": end,
        "_seq": store.next_seq(),
    }
    store.contracts[contract["id"]] = contract
    farm["version"] += 1
    farm["updated_at"] = ts
    return ok(contract_out(contract), 201)


@bp.route("/farms/<fid>/contracts", methods=["GET"])
def list_contracts(fid):
    uid, role = authenticate()
    authorize(role, ("NetworkManager", "PlatformAdmin"))
    farm = domain.get_farm_or_404(fid)
    limit, offset = pagination()
    status = request.args.get("status")
    rows = [c for c in store.contracts.values() if c["farm_id"] == farm["id"]]
    if status is not None:
        rows = [c for c in rows if c["status"] == status]
    page, total = domain.sorted_page(rows, limit, offset)
    return ok_list([contract_out(c) for c in page], limit, offset, total)
