"""Feature licenses: per-machine feature unlocks with bundle-discounted fees
and the OCC guard on the machine version (PRD section 3.7)."""

from flask import Blueprint, request

from auth import (
    as_enum,
    as_int,
    as_pos_int,
    as_str,
    body_json,
    caller,
    get_or_404,
    list_resources,
    need,
    require_role,
    access_denied,
)
from db import STORES, now
from domain import (
    active_license_count,
    add_months_dt,
    compute_license_fee,
    new_record,
    recompute_active_license_count,
    serialize,
    touch,
)
from envelope import created, ok, ok_list
from errors import (
    ERR_INVALID_REQUEST,
    ERR_LICENSE_ALREADY_EXISTS,
    ERR_MACHINE_POSTURE_BLOCKED,
    ERR_STALE_MACHINE_VERSION,
    ApiError,
    invalid_state,
)

bp = Blueprint("licenses", __name__)

FEATURE_CODES = {"AUTO_GUIDANCE", "SECTION_CONTROL", "VARIABLE_RATE_SPREAD", "TELEMATICS_PREMIUM"}
LICENSE_TYPES = {"PERPETUAL", "TERM"}


@bp.post("/feature-licenses")
def create_license():
    uid, role = caller()
    require_role(role, {"GrowerManager"})
    b = body_json()
    machine_id = as_str(need(b, "machine_id"), "machine_id")
    feature_code = as_enum(need(b, "feature_code"), "feature_code", FEATURE_CODES)
    license_type = as_enum(need(b, "license_type"), "license_type", LICENSE_TYPES)
    # term_months is required when license_type == TERM, ignored for PERPETUAL
    term_months = None
    if license_type == "TERM":
        term_months = as_pos_int(need(b, "term_months"), "term_months")
    elif "term_months" in b and b["term_months"] is not None:
        as_int(b["term_months"], "term_months")
    expected_machine_version = as_int(
        need(b, "expected_machine_version"), "expected_machine_version"
    )
    machine = get_or_404("machines", machine_id, "machine")
    if uid != machine["organization_id"]:
        raise access_denied("machine belongs to another organization")
    # Capacity: at most one non-REVOKED license per (machine, feature_code)
    for lic in STORES["feature_licenses"].values():
        if (
            lic["machine_id"] == machine_id
            and lic["feature_code"] == feature_code
            and lic["status"] != "REVOKED"
        ):
            raise ApiError(
                ERR_LICENSE_ALREADY_EXISTS,
                409,
                "a non-REVOKED license already exists for this machine and feature",
            )
    # Optimistic concurrency last, after every domain rule has passed
    if expected_machine_version != machine["version"]:
        raise ApiError(ERR_STALE_MACHINE_VERSION, 412, "machine version is stale")
    fee = compute_license_fee(machine_id, feature_code)
    rec = new_record(
        {
            "machine_id": machine_id,
            "feature_code": feature_code,
            "license_type": license_type,
            "term_months": term_months,
            "fee_cents": fee,
            "status": "PURCHASED",
            "activated_at": None,
            "expires_at": None,
        }
    )
    STORES["feature_licenses"][rec["id"]] = rec
    # License provisioning mutates the machine's configuration: version bump
    machine["active_license_count"] = active_license_count(machine_id)
    touch(machine)
    return created(serialize(rec))


def _license_org(lic):
    m = STORES["machines"].get(lic["machine_id"])
    return m["organization_id"] if m is not None else None


@bp.get("/feature-licenses/<lid>")
def get_license(lid):
    uid, role = caller()
    require_role(role, {"GrowerManager", "PlatformAdmin"})
    lic = get_or_404("feature_licenses", lid, "feature license")
    if role == "GrowerManager" and uid != _license_org(lic):
        raise access_denied("license belongs to another organization")
    return ok(serialize(lic))


@bp.get("/feature-licenses")
def list_licenses():
    uid, role = caller()
    require_role(role, {"GrowerManager", "PlatformAdmin"})
    filters = []
    for f in ("machine_id", "feature_code", "status"):
        v = request.args.get(f)
        if v is not None:
            filters.append((f, v))
    if role == "PlatformAdmin":
        visible = lambda r: True
    else:
        visible = lambda r: _license_org(r) == uid
    page, total, limit, offset = list_resources("feature_licenses", filters, visible)
    return ok_list([serialize(r) for r in page], total, limit, offset)


@bp.post("/feature-licenses/<lid>/activate")
def activate_license(lid):
    uid, role = caller()
    require_role(role, {"System"})
    lic = get_or_404("feature_licenses", lid, "feature license")
    if lic["status"] not in ("PURCHASED", "SUSPENDED"):
        raise invalid_state("license is not PURCHASED or SUSPENDED")
    machine = STORES["machines"].get(lic["machine_id"])
    if machine is None or machine["connectivity_posture"] != "CONNECTED":
        raise ApiError(ERR_MACHINE_POSTURE_BLOCKED, 409, "machine posture is not CONNECTED")
    lic["status"] = "ACTIVATED"
    if lic["activated_at"] is None:
        # First activation stamps activated_at and, for TERM, expires_at
        lic["activated_at"] = now()
        if lic["license_type"] == "TERM":
            lic["expires_at"] = add_months_dt(now(), lic["term_months"])
    touch(lic)
    recompute_active_license_count(machine)
    return ok(serialize(lic))


@bp.post("/feature-licenses/<lid>/suspend")
def suspend_license(lid):
    uid, role = caller()
    require_role(role, {"PlatformAdmin"})
    lic = get_or_404("feature_licenses", lid, "feature license")
    if lic["status"] != "ACTIVATED":
        raise invalid_state("license is not ACTIVATED")
    lic["status"] = "SUSPENDED"
    touch(lic)
    machine = STORES["machines"].get(lic["machine_id"])
    if machine is not None:
        recompute_active_license_count(machine)
    return ok(serialize(lic))


@bp.post("/feature-licenses/<lid>/revoke")
def revoke_license(lid):
    uid, role = caller()
    require_role(role, {"PlatformAdmin"})
    lic = get_or_404("feature_licenses", lid, "feature license")
    if lic["status"] not in ("PURCHASED", "ACTIVATED", "SUSPENDED"):
        raise invalid_state("license is not PURCHASED, ACTIVATED or SUSPENDED")
    lic["status"] = "REVOKED"
    touch(lic)
    machine = STORES["machines"].get(lic["machine_id"])
    if machine is not None:
        recompute_active_license_count(machine)
    return ok(serialize(lic))
