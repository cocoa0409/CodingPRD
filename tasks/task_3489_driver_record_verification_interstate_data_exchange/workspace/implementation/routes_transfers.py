"""Interstate license transfer protocol (PRD section 3.6)."""
from flask import Blueprint, request

import serialize
import state
import store
import validation as v
from errors import err
from response import ok, ok_list

bp = Blueprint("license_transfers", __name__, url_prefix="/driver-exchange")

IN_FLIGHT = {"INITIATED", "SURRENDER_RECORDED", "CONTESTED"}


@bp.post("/license-transfers")
def initiate_transfer():
    """Initiate a transfer into the caller's jurisdiction: the second
    OCC-guarded write of PRD section 2.7. The prior license must be ACTIVE
    and belong to the driver; at most one transfer per driver may be in
    flight."""
    user_id, role = v.auth_context()
    v.require_role(role, {"JurisdictionRegistrar"})
    data = v.body()
    driver_id = v.req_string(data, "driver_id")
    prior_license_id = v.req_string(data, "prior_license_id")
    expected_version = v.req_int(data, "expected_driver_version")
    driver = store.db.drivers.get(driver_id)
    if driver is None:
        raise err("ERR_DRIVER_NOT_FOUND", "no driver with id %s" % driver_id)
    prior_license = store.db.licenses.get(prior_license_id)
    if prior_license is None:
        raise err("ERR_LICENSE_NOT_FOUND", "no license with id %s" % prior_license_id)
    jurisdiction = v.registrar_jurisdiction(user_id)
    if prior_license["driver_id"] != driver_id:
        raise err("ERR_INVALID_REQUEST",
                  "the prior license does not belong to the driver")
    if expected_version != driver["version"]:
        raise err("ERR_STALE_VERSION",
                  "expected_driver_version does not match the driver identity version")
    if jurisdiction["membership_status"] != "ACTIVE":
        raise err("ERR_JURISDICTION_NOT_ACTIVE",
                  "transfer initiation requires an ACTIVE jurisdiction")
    if not state.has_certified_participation(user_id, "POINTER_NETWORK"):
        raise err("ERR_PARTICIPATION_NOT_CERTIFIED",
                  "transfer initiation requires a CERTIFIED POINTER_NETWORK participation")
    if prior_license["status"] != "ACTIVE":
        raise err("ERR_LICENSE_NOT_ACTIVE", "the prior license must be ACTIVE")
    for t in store.db.license_transfers.values():
        if t["driver_id"] == driver_id and t["status"] in IN_FLIGHT:
            raise err("ERR_TRANSFER_ALREADY_IN_FLIGHT",
                      "the driver already has an in-flight transfer")
    transfer = {
        "id": store.new_id(),
        "driver_id": driver_id,
        "from_jurisdiction_id": prior_license["issuing_jurisdiction_id"],
        "to_jurisdiction_id": user_id,
        "prior_license_id": prior_license_id,
        "new_license_id": None,
        "status": "INITIATED",
        "contest_reason": None,
    }
    store.stamp(transfer)
    store.db.license_transfers[transfer["id"]] = transfer
    store.touch(driver)  # a successful initiation advances the driver version by 1
    return ok(serialize.license_transfer(transfer), 201)


def _transfer_or_404(tid):
    transfer = store.db.license_transfers.get(tid)
    if transfer is None:
        raise err("ERR_TRANSFER_NOT_FOUND", "no license transfer with id %s" % tid)
    return transfer


@bp.get("/license-transfers/<tid>")
def get_transfer(tid):
    _, role = v.auth_context()
    v.require_role(role, v.ALL_ROLES)
    return ok(serialize.license_transfer(_transfer_or_404(tid)))


@bp.get("/license-transfers")
def list_transfers():
    _, role = v.auth_context()
    v.require_role(role, v.ALL_ROLES)
    items = list(store.db.license_transfers.values())
    for param in ("driver_id", "from_jurisdiction_id", "to_jurisdiction_id",
                  "prior_license_id", "new_license_id"):
        value = request.args.get(param)
        if value is not None:
            items = [t for t in items if t[param] == value]
    page, limit, offset, total = v.paginate(store.sorted_by_created(items))
    return ok_list([serialize.license_transfer(t) for t in page], limit, offset, total)


@bp.post("/license-transfers/<tid>/record-surrender")
def record_surrender(tid):
    """From-jurisdiction registrar records surrender: INITIATED or CONTESTED
    -> SURRENDER_RECORDED; the prior license goes ACTIVE -> SURRENDERED and
    any contest_reason is cleared."""
    user_id, role = v.auth_context()
    v.require_role(role, {"JurisdictionRegistrar"})
    transfer = _transfer_or_404(tid)
    if transfer["from_jurisdiction_id"] != user_id:
        raise err("ERR_JURISDICTION_OWNERSHIP_MISMATCH",
                  "only the from-jurisdiction registrar may record surrender")
    if transfer["status"] not in ("INITIATED", "CONTESTED"):
        raise err("ERR_INVALID_STATE",
                  "surrender can be recorded only from INITIATED or CONTESTED")
    prior_license = store.db.licenses.get(transfer["prior_license_id"])
    if prior_license is not None and prior_license["status"] == "ACTIVE":
        prior_license["status"] = "SURRENDERED"
        store.touch(prior_license)
    transfer["contest_reason"] = None
    transfer["status"] = "SURRENDER_RECORDED"
    store.touch(transfer)
    return ok(serialize.license_transfer(transfer))


@bp.post("/license-transfers/<tid>/contest")
def contest_transfer(tid):
    """To-jurisdiction registrar contests a recorded surrender:
    SURRENDER_RECORDED -> CONTESTED; the contest reason is recorded and the
    prior license walks back SURRENDERED -> ACTIVE as compensation."""
    user_id, role = v.auth_context()
    v.require_role(role, {"JurisdictionRegistrar"})
    transfer = _transfer_or_404(tid)
    if transfer["to_jurisdiction_id"] != user_id:
        raise err("ERR_JURISDICTION_OWNERSHIP_MISMATCH",
                  "only the to-jurisdiction registrar may contest")
    data = v.body()
    reason = v.req_string(data, "reason")
    if transfer["status"] != "SURRENDER_RECORDED":
        raise err("ERR_INVALID_STATE", "contest requires SURRENDER_RECORDED")
    prior_license = store.db.licenses.get(transfer["prior_license_id"])
    if prior_license is not None and prior_license["status"] == "SURRENDERED":
        prior_license["status"] = "ACTIVE"
        store.touch(prior_license)
    transfer["contest_reason"] = reason
    transfer["status"] = "CONTESTED"
    store.touch(transfer)
    return ok(serialize.license_transfer(transfer))


@bp.post("/license-transfers/<tid>/complete")
def complete_transfer(tid):
    """To-jurisdiction registrar completes the move. Rung-6 sub-order:
    receiving jurisdiction ACTIVE, then POINTER_NETWORK certified, then the
    transfer/license arcs; then the rung-7 disqualification gate. The cascade
    retires the old record and creates the replacement record and a
    PENDING_VERIFICATION license in the receiving jurisdiction."""
    user_id, role = v.auth_context()
    v.require_role(role, {"JurisdictionRegistrar"})
    transfer = _transfer_or_404(tid)
    if transfer["to_jurisdiction_id"] != user_id:
        raise err("ERR_JURISDICTION_OWNERSHIP_MISMATCH",
                  "only the to-jurisdiction registrar may complete the transfer")
    to_jurisdiction = store.db.jurisdictions.get(transfer["to_jurisdiction_id"])
    if to_jurisdiction is None or to_jurisdiction["membership_status"] != "ACTIVE":
        raise err("ERR_JURISDICTION_NOT_ACTIVE",
                  "the receiving jurisdiction must be ACTIVE")
    if not state.has_certified_participation(transfer["to_jurisdiction_id"],
                                             "POINTER_NETWORK"):
        raise err("ERR_PARTICIPATION_NOT_CERTIFIED",
                  "the receiving jurisdiction must hold a CERTIFIED POINTER_NETWORK participation")
    if transfer["status"] != "SURRENDER_RECORDED":
        raise err("ERR_INVALID_STATE", "completion requires SURRENDER_RECORDED")
    prior_license = store.db.licenses.get(transfer["prior_license_id"])
    if prior_license is None or prior_license["status"] != "SURRENDERED":
        raise err("ERR_INVALID_STATE", "the prior license must be SURRENDERED")
    old_record = store.db.records.get(prior_license["record_id"])
    if old_record is not None and state.active_disqualifications(old_record["id"]):
        raise err("ERR_ACTIVE_DISQUALIFICATION",
                  "an ACTIVE disqualification blocks transfer completion")
    old_record["status"] = "TRANSFERRED_OUT"
    store.touch(old_record)
    new_record = {
        "id": store.new_id(),
        "driver_id": transfer["driver_id"],
        "holding_jurisdiction_id": transfer["to_jurisdiction_id"],
        "status": "ACTIVE",
        "points_total": 0,
        "abstract_points_total": 0,
    }
    store.stamp(new_record)
    store.db.records[new_record["id"]] = new_record
    new_license = {
        "id": store.new_id(),
        "driver_id": transfer["driver_id"],
        "issuing_jurisdiction_id": transfer["to_jurisdiction_id"],
        "record_id": new_record["id"],
        "license_class": prior_license["license_class"],
        "status": "PENDING_VERIFICATION",
        "ssn_check_status": "PENDING",
        "lawful_status_check_status": "PENDING",
    }
    store.stamp(new_license)
    store.db.licenses[new_license["id"]] = new_license
    transfer["new_license_id"] = new_license["id"]
    transfer["status"] = "COMPLETED"
    store.touch(transfer)
    return ok(serialize.license_transfer(transfer))
