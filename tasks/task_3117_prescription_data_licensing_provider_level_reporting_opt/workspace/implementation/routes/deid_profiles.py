"""DeidentificationProfile endpoints."""

from flask import Blueprint

from db import db
from errors import err_not_found
from middleware import require_role, get_pagination, ALL_ROLES
from response import success_object, success_array
from services.common import body_json, require_fields, check_str, check_int_opt, check_enum, mint

bp = Blueprint("deid_profiles", __name__)

HASH_ALGORITHMS = {"SHA256", "SHA512"}


@bp.route("/deidentification-profiles", methods=["POST"])
def create_profile():
    require_role(["PrivacyOfficer"])
    data = body_json()
    require_fields(data, ["name", "salt_version"])
    name = check_str(data, "name")
    salt_version = check_str(data, "salt_version")
    k = 5
    if "k_anonymity_threshold" in data and data["k_anonymity_threshold"] is not None:
        k = check_int_opt(data, "k_anonymity_threshold", min_v=1)
    algo = "SHA256"
    if "hash_algorithm" in data and data["hash_algorithm"] is not None:
        algo = check_enum(data, "hash_algorithm", HASH_ALGORITHMS)
    profile = mint(db.deid_profiles, {
        "name": name,
        "k_anonymity_threshold": k,
        "salt_version": salt_version,
        "hash_algorithm": algo,
    }, common=False)
    return success_object(profile, status=201)


@bp.route("/deidentification-profiles/<pid>", methods=["GET"])
def get_profile(pid):
    require_role(ALL_ROLES)
    profile = db.deid_profiles.get(pid)
    if profile is None:
        raise err_not_found("De-identification profile not found")
    return success_object(profile)


@bp.route("/deidentification-profiles/<pid>/batches", methods=["GET"])
def list_profile_batches(pid):
    require_role(["PlatformAdmin", "DataAcquisitionManager", "PrivacyOfficer"])
    profile = db.deid_profiles.get(pid)
    if profile is None:
        raise err_not_found("De-identification profile not found")
    limit, offset = get_pagination()
    items = sorted(
        (b for b in db.batches.values() if b["deidentification_profile_id"] == pid),
        key=lambda b: b["created_at"],
    )
    total = len(items)
    return success_array(items[offset:offset + limit], limit, offset, total)
