"""License issuance, federal verification, and reinstatement (PRD section
3.5)."""
from flask import Blueprint, request

import serialize
import state
import store
import validation as v
from errors import err
from response import ok, ok_list

bp = Blueprint("licenses", __name__, url_prefix="/driver-exchange")

LICENSE_CLASSES = {"STANDARD", "COMMERCIAL"}
CHECK_TYPES = {"SSN": "ssn_check_status", "LAWFUL_STATUS": "lawful_status_check_status"}
CHECK_RESULTS = {"VERIFIED", "FAILED"}


@bp.post("/licenses")
def issue_license():
    """Issuance starts from the pointer: the driver must hold an ACTIVE
    record in the caller's ACTIVE, POINTER_NETWORK-certified jurisdiction;
    COMMERCIAL additionally requires no derived-ACTIVE disqualification on
    the driver's ACTIVE record."""
    user_id, role = v.auth_context()
    v.require_role(role, {"JurisdictionRegistrar"})
    data = v.body()
    driver_id = v.req_string(data, "driver_id")
    license_class = v.req_enum(data, "license_class", LICENSE_CLASSES)
    driver = store.db.drivers.get(driver_id)
    if driver is None:
        raise err("ERR_DRIVER_NOT_FOUND", "no driver with id %s" % driver_id)
    jurisdiction = v.registrar_jurisdiction(user_id)
    if jurisdiction["membership_status"] != "ACTIVE":
        raise err("ERR_JURISDICTION_NOT_ACTIVE",
                  "issuance requires an ACTIVE jurisdiction")
    if not state.has_certified_participation(user_id, "POINTER_NETWORK"):
        raise err("ERR_PARTICIPATION_NOT_CERTIFIED",
                  "issuance requires a CERTIFIED POINTER_NETWORK participation")
    active_record = state.active_record_for_driver(driver_id)
    if license_class == "COMMERCIAL" and active_record is not None:
        if state.active_disqualifications(active_record["id"]):
            raise err("ERR_ACTIVE_DISQUALIFICATION",
                      "COMMERCIAL issuance is blocked by an ACTIVE disqualification")
    if active_record is not None and active_record["holding_jurisdiction_id"] != user_id:
        raise err("ERR_RECORD_HELD_BY_OTHER_JURISDICTION",
                  "the driver's ACTIVE record is held by another jurisdiction")
    if active_record is None:
        raise err("ERR_RECORD_NOT_FOUND",
                  "the driver has no ACTIVE record held by the caller's jurisdiction")
    license_obj = {
        "id": store.new_id(),
        "driver_id": driver_id,
        "issuing_jurisdiction_id": user_id,
        "record_id": active_record["id"],
        "license_class": license_class,
        "status": "PENDING_VERIFICATION",
        "ssn_check_status": "PENDING",
        "lawful_status_check_status": "PENDING",
    }
    store.stamp(license_obj)
    store.db.licenses[license_obj["id"]] = license_obj
    return ok(serialize.license(license_obj), 201)


def _license_or_404(lid):
    license_obj = store.db.licenses.get(lid)
    if license_obj is None:
        raise err("ERR_LICENSE_NOT_FOUND", "no license with id %s" % lid)
    return license_obj


@bp.get("/licenses/<lid>")
def get_license(lid):
    _, role = v.auth_context()
    v.require_role(role, v.ALL_ROLES)
    return ok(serialize.license(_license_or_404(lid)))


@bp.get("/licenses")
def list_licenses():
    _, role = v.auth_context()
    v.require_role(role, v.ALL_ROLES)
    items = list(store.db.licenses.values())
    for param in ("driver_id", "issuing_jurisdiction_id", "record_id"):
        value = request.args.get(param)
        if value is not None:
            items = [l for l in items if l[param] == value]
    page, limit, offset, total = v.paginate(store.sorted_by_created(items))
    return ok_list([serialize.license(l) for l in page], limit, offset, total)


@bp.post("/licenses/<lid>/verification-results")
def post_verification_result(lid):
    """Federal verification callback. The second VERIFIED activates the
    license; any FAILED denies it (terminal). Posting to a decided license,
    or re-posting a decided dimension, is ERR_INVALID_STATE."""
    _, role = v.auth_context()
    v.require_role(role, {"FederalVerifier"})
    data = v.body()
    check_type = v.req_enum(data, "check_type", set(CHECK_TYPES.keys()))
    result = v.req_enum(data, "result", CHECK_RESULTS)
    license_obj = _license_or_404(lid)
    if license_obj["status"] != "PENDING_VERIFICATION":
        raise err("ERR_INVALID_STATE",
                  "the license is no longer PENDING_VERIFICATION")
    field = CHECK_TYPES[check_type]
    if license_obj[field] != "PENDING":
        raise err("ERR_INVALID_STATE",
                  "this verification dimension is already decided")
    license_obj[field] = result
    if result == "FAILED":
        license_obj["status"] = "DENIED"
    elif (license_obj["ssn_check_status"] == "VERIFIED"
          and license_obj["lawful_status_check_status"] == "VERIFIED"):
        license_obj["status"] = "ACTIVE"
    store.touch(license_obj)
    return ok(serialize.license(license_obj))


@bp.post("/licenses/<lid>/reinstate")
def reinstate_license(lid):
    """SUSPENDED -> ACTIVE, registrar of the issuing jurisdiction only, and
    only once no derived-ACTIVE disqualification remains on the backing
    record."""
    user_id, role = v.auth_context()
    v.require_role(role, {"JurisdictionRegistrar"})
    license_obj = _license_or_404(lid)
    if license_obj["issuing_jurisdiction_id"] != user_id:
        raise err("ERR_JURISDICTION_OWNERSHIP_MISMATCH",
                  "only the issuing jurisdiction's registrar may reinstate")
    if license_obj["status"] != "SUSPENDED":
        raise err("ERR_INVALID_STATE", "only a SUSPENDED license may be reinstated")
    if state.active_disqualifications(license_obj["record_id"]):
        raise err("ERR_ACTIVE_DISQUALIFICATION",
                  "an ACTIVE disqualification blocks reinstatement")
    license_obj["status"] = "ACTIVE"
    store.touch(license_obj)
    return ok(serialize.license(license_obj))
