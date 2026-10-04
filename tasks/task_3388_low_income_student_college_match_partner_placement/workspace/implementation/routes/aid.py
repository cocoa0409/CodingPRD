"""AidPackage endpoints: get, list, revise (OCC), finalize."""
from flask import Blueprint, request

import serializers
import store
from auth import forbid, identity, require_roles
from calculations import latest_decided_verification, recompute_package
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_STALE_VERSION,
    ERR_VERIFICATION_REQUIRED,
)
from response import ok_object, paginated
from validation import get_body, is_int

bp = Blueprint("aid", __name__)

READ_ROLES = ("ProgramAdmin", "Student", "CollegeOfficer")


def get_package_or_404(package_id):
    package = store.aid_packages.get(package_id)
    if package is None:
        raise ApiError(ERR_NOT_FOUND, "aid package not found")
    return package


def check_package_ownership(role, uid, package):
    if role == "CollegeOfficer" and package["college_id"] != uid:
        forbid("a college officer may only act on their own college's aid packages")
    if role == "Student":
        application = store.applications.get(package["application_id"])
        if application is None or application["student_id"] != uid:
            forbid("a student may only view their own aid packages")


@bp.get("/aid-packages")
def list_packages():
    role, _ = identity()
    require_roles(role, READ_ROLES)
    items = list(store.aid_packages.values())
    for field in ("match_id", "application_id", "college_id", "status"):
        value = request.args.get(field)
        if value is not None:
            items = [p for p in items if p[field] == value]
    items.sort(key=lambda p: p["created_at"])
    return paginated(items, serializers.aid_package)


@bp.get("/aid-packages/<package_id>")
def get_package(package_id):
    role, uid = identity()
    require_roles(role, READ_ROLES)
    package = get_package_or_404(package_id)
    check_package_ownership(role, uid, package)
    return ok_object(serializers.aid_package(package))


@bp.post("/aid-packages/<package_id>/revise")
def revise_package(package_id):
    body = get_body()
    expected_version = body.get("expected_aid_package_version")
    if not is_int(expected_version):
        raise ApiError(ERR_INVALID_REQUEST, "expected_aid_package_version is required and must be an integer")
    new_coa = body.get("coa_cents")
    if new_coa is not None and not is_int(new_coa):
        raise ApiError(ERR_INVALID_REQUEST, "coa_cents must be an integer")
    role, uid = identity()
    require_roles(role, ("CollegeOfficer",))
    package = get_package_or_404(package_id)
    check_package_ownership(role, uid, package)
    if package["status"] != "FINALIZED":
        raise ApiError(ERR_INVALID_STATE, "only a FINALIZED package can be revised")
    if expected_version != package["version"]:
        raise ApiError(ERR_STALE_VERSION, "the package version has advanced since the caller last read it")
    if new_coa is not None:
        package["coa_cents"] = new_coa
    # All amounts recomputed under the package's current aid_variant.
    recompute_package(package)
    package["status"] = "REVISED"
    store.touch(package)
    return ok_object(serializers.aid_package(package))


@bp.post("/aid-packages/<package_id>/finalize")
def finalize_package(package_id):
    role, uid = identity()
    require_roles(role, ("CollegeOfficer",))
    package = get_package_or_404(package_id)
    check_package_ownership(role, uid, package)
    if package["status"] not in ("PROVISIONAL", "REVISED"):
        raise ApiError(ERR_INVALID_STATE, "only a PROVISIONAL or REVISED package can be finalized")
    # The application's latest decided income verification must carry the
    # outcome VERIFIED or WAIVED.
    latest = latest_decided_verification(package["application_id"])
    if latest is None or latest["outcome"] not in ("VERIFIED", "WAIVED"):
        raise ApiError(ERR_VERIFICATION_REQUIRED, "aid finalization requires a decided VERIFIED or WAIVED verification")
    if latest["outcome"] == "VERIFIED":
        # Recompute every amount under the VERIFIED contribution variant.
        package["aid_variant"] = "VERIFIED"
        recompute_package(package)
    # WAIVED: keep the PROVISIONAL variant amounts and aid_variant.
    package["status"] = "FINALIZED"
    store.touch(package)
    return ok_object(serializers.aid_package(package))
