"""Driver identities and master driver records (PRD section 3.3), including
the OCC-guarded record claim (PRD section 2.7)."""
from flask import Blueprint, request

import serialize
import state
import store
import validation as v
from errors import err
from response import ok, ok_list

bp = Blueprint("drivers", __name__, url_prefix="/driver-exchange")

LAWFUL_STATUS_BASES = {"US_CITIZEN", "PERMANENT_RESIDENT", "TEMPORARY_STATUS"}


@bp.post("/drivers")
def create_driver():
    """Register a shared driver identity; the registrar's own jurisdiction
    must exist."""
    user_id, role = v.auth_context()
    v.require_role(role, {"JurisdictionRegistrar"})
    data = v.body()
    full_name = v.req_string(data, "full_name")
    dob = v.req_date(data, "date_of_birth")
    ssn_hash = v.req_string(data, "ssn_last4_hash")
    basis = v.req_enum(data, "lawful_status_basis", LAWFUL_STATUS_BASES)
    v.registrar_jurisdiction(user_id)
    driver = {
        "id": store.new_id(),
        "full_name": full_name,
        "date_of_birth": dob.isoformat(),
        "ssn_last4_hash": ssn_hash,
        "lawful_status_basis": basis,
    }
    store.stamp(driver)
    store.db.drivers[driver["id"]] = driver
    return ok(serialize.driver(driver), 201)


@bp.get("/drivers/<did>")
def get_driver(did):
    _, role = v.auth_context()
    v.require_role(role, v.ALL_ROLES)
    driver = store.db.drivers.get(did)
    if driver is None:
        raise err("ERR_DRIVER_NOT_FOUND", "no driver with id %s" % did)
    return ok(serialize.driver(driver))


@bp.post("/driver-records")
def create_driver_record():
    """Claim the master record for a driver into the caller's jurisdiction.
    Ladder: shape -> driver existence -> caller jurisdiction existence -> OCC
    -> jurisdiction ACTIVE -> POINTER_NETWORK certified -> one-driver-one-
    record."""
    user_id, role = v.auth_context()
    v.require_role(role, {"JurisdictionRegistrar"})
    data = v.body()
    driver_id = v.req_string(data, "driver_id")
    expected_version = v.req_int(data, "expected_driver_version")
    driver = store.db.drivers.get(driver_id)
    if driver is None:
        raise err("ERR_DRIVER_NOT_FOUND", "no driver with id %s" % driver_id)
    jurisdiction = v.registrar_jurisdiction(user_id)
    if expected_version != driver["version"]:
        raise err("ERR_STALE_VERSION",
                  "expected_driver_version does not match the driver identity version")
    if jurisdiction["membership_status"] != "ACTIVE":
        raise err("ERR_JURISDICTION_NOT_ACTIVE",
                  "a record claim requires an ACTIVE jurisdiction")
    if not state.has_certified_participation(user_id, "POINTER_NETWORK"):
        raise err("ERR_PARTICIPATION_NOT_CERTIFIED",
                  "a record claim requires a CERTIFIED POINTER_NETWORK participation")
    if state.active_record_for_driver(driver_id) is not None:
        raise err("ERR_RECORD_ALREADY_HELD",
                  "the driver already has an ACTIVE record")
    record = {
        "id": store.new_id(),
        "driver_id": driver_id,
        "holding_jurisdiction_id": user_id,
        "status": "ACTIVE",
        "points_total": 0,
        "abstract_points_total": 0,
    }
    store.stamp(record)
    store.db.records[record["id"]] = record
    store.touch(driver)  # a successful claim advances the driver version by 1
    return ok(serialize.record(record), 201)


def _record_or_404(rid):
    record = store.db.records.get(rid)
    if record is None:
        raise err("ERR_RECORD_NOT_FOUND", "no driver record with id %s" % rid)
    return record


@bp.get("/driver-records/<rid>")
def get_driver_record(rid):
    _, role = v.auth_context()
    v.require_role(role, v.ALL_ROLES)
    return ok(serialize.record(_record_or_404(rid)))


@bp.get("/driver-records")
def list_driver_records():
    _, role = v.auth_context()
    v.require_role(role, v.ALL_ROLES)
    driver_id = request.args.get("driver_id")
    holding = request.args.get("holding_jurisdiction_id")
    items = list(store.db.records.values())
    if driver_id is not None:
        items = [r for r in items if r["driver_id"] == driver_id]
    if holding is not None:
        items = [r for r in items if r["holding_jurisdiction_id"] == holding]
    page, limit, offset, total = v.paginate(store.sorted_by_created(items))
    return ok_list([serialize.record(r) for r in page], limit, offset, total)


@bp.get("/driver-records/<rid>/convictions")
def list_record_convictions(rid):
    _, role = v.auth_context()
    v.require_role(role, v.ALL_ROLES)
    _record_or_404(rid)
    items = [c for c in store.db.convictions.values() if c["record_id"] == rid]
    page, limit, offset, total = v.paginate(store.sorted_by_created(items))
    return ok_list([serialize.conviction(c) for c in page], limit, offset, total)


@bp.get("/driver-records/<rid>/disqualifications")
def list_record_disqualifications(rid):
    """Derived statuses are evaluated at read time (PRD section 2.4)."""
    _, role = v.auth_context()
    v.require_role(role, v.ALL_ROLES)
    _record_or_404(rid)
    items = [d for d in store.db.disqualifications.values() if d["record_id"] == rid]
    page, limit, offset, total = v.paginate(store.sorted_by_created(items))
    return ok_list([serialize.disqualification(d) for d in page], limit, offset, total)
