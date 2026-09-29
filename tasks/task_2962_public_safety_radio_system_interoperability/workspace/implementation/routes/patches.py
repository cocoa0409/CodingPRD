"""Cross-agency interoperability patches."""
from flask import Blueprint

import common
import compute
import db
import enums
import response
import serialize
import validate
from errors import ApiError
from validate import DISPATCHER

bp = Blueprint("patches", __name__, url_prefix=common.PREFIX)

TERMINAL = ("RELEASED", "DENIED")


@bp.post("/interop-patches")
def request_patch():
    actor = validate.authenticate([DISPATCHER])
    body = validate.get_body()
    source = validate.req_fk(body, "source_talkgroup_id", "talkgroups")
    target = validate.req_fk(body, "target_talkgroup_id", "talkgroups")
    agency = validate.req_fk(body, "requesting_agency_id", "agencies")
    start = validate.req_dt(body, "scheduled_start")
    end = validate.req_dt(body, "scheduled_end")
    validate.window_order(start, end, "scheduled_start", "scheduled_end")
    common.require_scope(actor, agency["id"])
    if source["status"] != "ACTIVE" or target["status"] != "ACTIVE":
        raise ApiError("ERR_TALKGROUP_LOCKED")
    source_site = db.store.sites.get(source["home_site_id"])
    target_site = db.store.sites.get(target["home_site_id"])
    for site in (source_site, target_site):
        if site is not None and site["status"] == "OFF_AIR":
            raise ApiError("ERR_SITE_OFF_AIR")
    if "ENCRYPTED" in (source["encryption_mode"], target["encryption_mode"]):
        for site in (source_site, target_site):
            if site is None or site["coverage_class"] != "MISSION_CRITICAL":
                raise ApiError("ERR_COVERAGE_CLASS_INSUFFICIENT")
    if agency["recorder_retention_days"] < compute.PATCH_RETENTION_MIN_DAYS:
        raise ApiError("ERR_RECORDER_RETENTION_BELOW_MINIMUM")
    for other in db.store.patches.values():
        if other["status"] not in compute.OPEN_PATCH_STATUSES:
            continue
        named = (other["source_talkgroup_id"], other["target_talkgroup_id"])
        if source["id"] not in named and target["id"] not in named:
            continue
        if start < other["scheduled_end"] and other["scheduled_start"] < end:
            raise ApiError("ERR_PATCH_WINDOW_OVERLAP")
    modes = (source["encryption_mode"], target["encryption_mode"])
    if "ENCRYPTED" in modes and "CLEAR" in modes:
        raise ApiError("ERR_ENCRYPTION_MODE_MISMATCH")
    if source["id"] == target["id"]:
        raise ApiError("ERR_SELF_PATCH_NOT_PERMITTED")
    if agency["id"] not in (source["owner_agency_id"], target["owner_agency_id"]):
        raise ApiError("ERR_INTEROP_PRIVILEGE_INSUFFICIENT")
    if agency["interop_privilege"] != "PATCH_AUTHORITY":
        raise ApiError("ERR_PATCH_AUTHORITY_REQUIRED")
    if agency["billing_status"] == "SUSPENDED_FROM_VOTING":
        raise ApiError("ERR_AGENCY_VOTING_SUSPENDED")
    row = db.base_row({
        "source_talkgroup_id": source["id"],
        "target_talkgroup_id": target["id"],
        "requesting_agency_id": agency["id"],
        "scheduled_start": start,
        "scheduled_end": end,
        "status": "REQUESTED",
        "activated_at": None,
        "released_at": None,
        "release_reason": "NONE",
        "duration_minutes": None,
        "recorder_retention_days_at_activation": None,
    })
    db.store.patches[row["id"]] = row
    compute.recompute_after_patch_change([source["id"], target["id"]], [agency["id"]])
    return response.ok(serialize.patch(row), 201)


@bp.get("/interop-patches")
def list_patches():
    validate.authenticate(common.ANY_ROLE)
    filters = (
        ("source_talkgroup_id", validate.filter_str("source_talkgroup_id")),
        ("target_talkgroup_id", validate.filter_str("target_talkgroup_id")),
        ("requesting_agency_id", validate.filter_str("requesting_agency_id")),
        ("status", validate.filter_enum("status", enums.PATCH_STATUSES)),
    )
    return common.list_endpoint("patches", serialize.patch, filters)


@bp.get("/interop-patches/<patch_id>")
def read_patch(patch_id):
    validate.authenticate(common.ANY_ROLE)
    patch = validate.lookup("patches", patch_id)
    return response.ok(serialize.patch(patch))


@bp.post("/interop-patches/<patch_id>/decision")
def patch_decision(patch_id):
    actor = validate.authenticate([DISPATCHER])
    patch = validate.lookup("patches", patch_id)
    body = validate.get_body()
    decision = validate.req_enum(body, "decision", enums.PATCH_DECISIONS)
    common.require_scope(actor, patch["requesting_agency_id"])
    if patch["status"] in TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL")
    if patch["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    source = db.store.talkgroups.get(patch["source_talkgroup_id"])
    target = db.store.talkgroups.get(patch["target_talkgroup_id"])
    agency = db.store.agencies.get(patch["requesting_agency_id"])
    if decision == "DENY":
        patch["status"] = "DENIED"
        db.touch(patch)
        compute.recompute_after_patch_change(
            [patch["source_talkgroup_id"], patch["target_talkgroup_id"]],
            [patch["requesting_agency_id"]],
        )
        return response.ok(serialize.patch(patch))
    if source["status"] != "ACTIVE" or target["status"] != "ACTIVE":
        raise ApiError("ERR_TALKGROUP_LOCKED")
    if agency["recorder_retention_days"] < compute.PATCH_RETENTION_MIN_DAYS:
        raise ApiError("ERR_RECORDER_RETENTION_BELOW_MINIMUM")
    if agency["interop_privilege"] != "PATCH_AUTHORITY":
        raise ApiError("ERR_PATCH_AUTHORITY_REQUIRED")
    now = db.now()
    if now < patch["scheduled_start"] or now >= patch["scheduled_end"]:
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "The logical clock is outside the reserved patch window.",
        )
    patch["status"] = "ACTIVE"
    patch["activated_at"] = now
    patch["recorder_retention_days_at_activation"] = agency["recorder_retention_days"]
    db.touch(patch)
    compute.recompute_after_patch_change(
        [patch["source_talkgroup_id"], patch["target_talkgroup_id"]],
        [patch["requesting_agency_id"]],
    )
    return response.ok(serialize.patch(patch))


@bp.post("/interop-patches/<patch_id>/release")
def release_patch(patch_id):
    actor = validate.authenticate([DISPATCHER])
    patch = validate.lookup("patches", patch_id)
    common.require_scope(actor, patch["requesting_agency_id"])
    if patch["status"] in TERMINAL:
        raise ApiError("ERR_ALREADY_TERMINAL")
    if patch["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    compute.release_patches([patch], "OPERATOR")
    return response.ok(serialize.patch(patch))
