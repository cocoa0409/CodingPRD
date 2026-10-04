"""Vehicle titles and interstate re-titling with brand-washing prevention
(PRD section 3.7)."""
from flask import Blueprint, request

import calc
import serialize
import state
import store
import validation as v
from errors import err
from response import ok, ok_list

bp = Blueprint("titles", __name__, url_prefix="/driver-exchange")


@bp.post("/vehicle-titles")
def create_vehicle_title():
    """Title a vehicle in the caller's ACTIVE, TITLE_NETWORK-certified
    jurisdiction. At most one ACTIVE title exists per VIN across the
    exchange."""
    user_id, role = v.auth_context()
    v.require_role(role, {"JurisdictionRegistrar"})
    data = v.body()
    vin = v.req_string(data, "vin")
    if len(vin) != 17:
        raise err("ERR_INVALID_REQUEST", "vin must be exactly 17 characters")
    brands = v.req_brand_list(data, "brands", required=False)
    jurisdiction = v.registrar_jurisdiction(user_id)
    if jurisdiction["membership_status"] != "ACTIVE":
        raise err("ERR_JURISDICTION_NOT_ACTIVE", "titling requires an ACTIVE jurisdiction")
    if not state.has_certified_participation(user_id, "TITLE_NETWORK"):
        raise err("ERR_PARTICIPATION_NOT_CERTIFIED",
                  "titling requires a CERTIFIED TITLE_NETWORK participation")
    for t in store.db.vehicle_titles.values():
        if t["vin"] == vin and t["status"] == "ACTIVE":
            raise err("ERR_VIN_ALREADY_TITLED",
                      "an ACTIVE title with this VIN already exists")
    title = {
        "id": store.new_id(),
        "vin": vin,
        "holding_jurisdiction_id": user_id,
        "brands": brands,
        "status": "ACTIVE",
        "washing_alert": False,
    }
    store.stamp(title)
    store.db.vehicle_titles[title["id"]] = title
    return ok(serialize.vehicle_title(title), 201)


@bp.post("/title-transfers")
def create_title_transfer():
    """Request re-titling of an out-of-state vehicle. The brand-washing check
    runs synchronously: a non-superset disclosure is rejected with
    ERR_BRAND_DISCLOSURE_MISMATCH and permanently sets the source title's
    washing_alert; no transfer is persisted. On success the transfer is
    created VERIFIED with carried_brands the sorted union."""
    user_id, role = v.auth_context()
    v.require_role(role, {"JurisdictionRegistrar"})
    data = v.body()
    vehicle_title_id = v.req_string(data, "vehicle_title_id")
    disclosed = v.req_brand_list(data, "disclosed_brands", required=True)
    title = store.db.vehicle_titles.get(vehicle_title_id)
    if title is None:
        raise err("ERR_TITLE_NOT_FOUND", "no vehicle title with id %s" % vehicle_title_id)
    jurisdiction = v.registrar_jurisdiction(user_id)
    if jurisdiction["membership_status"] != "ACTIVE":
        raise err("ERR_JURISDICTION_NOT_ACTIVE",
                  "re-titling requires an ACTIVE jurisdiction")
    if not state.has_certified_participation(user_id, "TITLE_NETWORK"):
        raise err("ERR_PARTICIPATION_NOT_CERTIFIED",
                  "re-titling requires a CERTIFIED TITLE_NETWORK participation")
    carried = calc.carried_brands(title["brands"], disclosed)
    if carried is None:
        title["washing_alert"] = True
        store.touch(title)
        raise err("ERR_BRAND_DISCLOSURE_MISMATCH",
                  "disclosed_brands must be a superset of the source title's brands")
    if user_id == title["holding_jurisdiction_id"]:
        raise err("ERR_SAME_JURISDICTION_TRANSFER",
                  "the receiving jurisdiction must differ from the source title's "
                  "holding jurisdiction")
    transfer = {
        "id": store.new_id(),
        "vehicle_title_id": vehicle_title_id,
        "to_jurisdiction_id": user_id,
        "disclosed_brands": disclosed,
        "carried_brands": carried,
        "new_title_id": None,
        "status": "VERIFIED",
    }
    store.stamp(transfer)
    store.db.title_transfers[transfer["id"]] = transfer
    return ok(serialize.title_transfer(transfer), 201)


def _title_transfer_or_404(tid):
    transfer = store.db.title_transfers.get(tid)
    if transfer is None:
        raise err("ERR_TITLE_TRANSFER_NOT_FOUND", "no title transfer with id %s" % tid)
    return transfer


@bp.get("/title-transfers/<tid>")
def get_title_transfer(tid):
    _, role = v.auth_context()
    v.require_role(role, v.ALL_ROLES)
    return ok(serialize.title_transfer(_title_transfer_or_404(tid)))


@bp.get("/title-transfers")
def list_title_transfers():
    _, role = v.auth_context()
    v.require_role(role, v.ALL_ROLES)
    items = list(store.db.title_transfers.values())
    for param in ("vehicle_title_id", "to_jurisdiction_id"):
        value = request.args.get(param)
        if value is not None:
            items = [t for t in items if t[param] == value]
    page, limit, offset, total = v.paginate(store.sorted_by_created(items))
    return ok_list([serialize.title_transfer(t) for t in page], limit, offset, total)


@bp.post("/title-transfers/<tid>/complete")
def complete_title_transfer(tid):
    """Complete the re-titling: the source title goes ACTIVE -> EXPORTED and
    a new ACTIVE title carrying carried_brands is created in the receiving
    jurisdiction."""
    user_id, role = v.auth_context()
    v.require_role(role, {"JurisdictionRegistrar"})
    transfer = _title_transfer_or_404(tid)
    if transfer["to_jurisdiction_id"] != user_id:
        raise err("ERR_JURISDICTION_OWNERSHIP_MISMATCH",
                  "only the receiving jurisdiction's registrar may complete")
    if transfer["status"] != "VERIFIED":
        raise err("ERR_INVALID_STATE", "completion requires VERIFIED")
    source = store.db.vehicle_titles.get(transfer["vehicle_title_id"])
    if source is None or source["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "the source title must be ACTIVE")
    source["status"] = "EXPORTED"
    store.touch(source)
    new_title = {
        "id": store.new_id(),
        "vin": source["vin"],
        "holding_jurisdiction_id": transfer["to_jurisdiction_id"],
        "brands": list(transfer["carried_brands"]),
        "status": "ACTIVE",
        "washing_alert": False,
    }
    store.stamp(new_title)
    store.db.vehicle_titles[new_title["id"]] = new_title
    transfer["new_title_id"] = new_title["id"]
    transfer["status"] = "COMPLETED"
    store.touch(transfer)
    return ok(serialize.title_transfer(transfer))
