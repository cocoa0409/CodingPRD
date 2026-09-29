"""Consent-solicitation and shared-clip endpoints (PRD 3.5, 3.6)."""
from datetime import timedelta

from flask import Blueprint

import auth
import calc
import engine
import envelope
import fetch
import serialize
import store
import validators as v
from errors import ApiError
from routes_resident import require_active
from store import db, now

bp = Blueprint("consent", __name__)

SOLICITATION_STATUSES = ("SOLICITED", "SHARED", "DECLINED", "EXPIRED",
                         "WITHDRAWN")
DECLINE_REASONS = ("OWNER_DECLINE", "OWNER_OPT_OUT", "ACCOUNT_DEACTIVATED")
CLIP_STATUSES = ("RETAINED", "LEGAL_HOLD", "PURGE_PENDING", "PURGED")
PURGE_REASONS = ("OWNER_REVOCATION", "RETENTION_EXPIRED", "ACCOUNT_DEACTIVATED",
                 "LEGAL_RELEASE")
RETENTION_VARIANTS = ("DEVICE_ANCHORED", "CASE_ANCHORED")


@bp.post("/neighborhood-safety/consent-solicitations/<solicitation_id>/share")
def share_footage(solicitation_id):
    actor = auth.authenticate(("Resident",))
    sol = fetch.must("ConsentSolicitation", solicitation_id)
    body = v.body_json()
    recorded_start = v.dt_field(body, "recorded_start_utc")
    duration = v.int_field(body, "duration_seconds", lo=1, hi=3600)
    resident = db.residents.get(sol["resident_id"])
    auth.require_resident_scope(actor, sol["resident_id"])
    require_active(resident)
    request_row = db.video_requests.get(sol["video_request_id"])
    if request_row["lifecycle_state"] != "SOLICITING":
        raise ApiError("ERR_REQUEST_NOT_SOLICITING",
                       "The owning request is no longer soliciting")
    if sol["status"] not in ("SOLICITED", "SHARED"):
        raise ApiError("ERR_SOLICITATION_ALREADY_RESOLVED",
                       "Solicitation %s is closed" % sol["id"])
    device = db.devices.get(sol["device_id"])
    if device is None or device["status"] != "ACTIVE":
        raise ApiError("ERR_DEVICE_DECOMMISSIONED",
                       "The camera is no longer active")
    if resident["data_sharing_opt_out"]:
        raise ApiError("ERR_RESIDENT_OPTED_OUT",
                       "This resident has opted out of video requests")
    if now() >= sol["respond_deadline_utc"]:
        raise ApiError("ERR_SOLICITATION_DEADLINE_PASSED",
                       "The response deadline has passed")

    area = db.request_areas.get(request_row["request_area_id"])
    segment_end = recorded_start + timedelta(seconds=duration)
    if (recorded_start < area["window_start_utc"]
            or segment_end > area["window_end_utc"]):
        raise ApiError("ERR_CLIP_OUTSIDE_REQUEST_WINDOW",
                       "The segment falls outside the requested footage window")
    for other in db.clips.values():
        if other["device_id"] != device["id"] or other["status"] == "PURGED":
            continue
        other_end = other["recorded_start_utc"] + timedelta(
            seconds=other["duration_seconds"])
        if recorded_start < other_end and other["recorded_start_utc"] < segment_end:
            raise ApiError("ERR_DEVICE_WINDOW_CONFLICT",
                           "That segment overlaps footage already shared")

    agency = db.agencies.get(request_row["agency_id"])
    shared_at = now()
    variant, expires_at, status = calc.clip_retention(
        request_row, device, agency, shared_at, recorded_start)
    clip = engine.new_row({
        "consent_solicitation_id": sol["id"],
        "video_request_id": request_row["id"],
        "device_id": device["id"],
        "owner_resident_id": device["owner_resident_id"],
        "recorded_start_utc": recorded_start,
        "duration_seconds": duration,
        "shared_at": shared_at,
        "retention_variant": variant,
        "retention_expires_at": expires_at,
        "status": status,
        "purged_at": None,
        "purge_reason": None,
    })
    db.clips[clip["id"]] = clip

    first_share = sol["status"] == "SOLICITED"
    sol["clip_count"] += 1
    if first_share:
        sol["status"] = "SHARED"
        sol["responded_at"] = shared_at
    engine.touch(sol)
    if first_share:
        engine.sync_device(device)
    owner = db.residents.get(clip["owner_resident_id"])
    if owner is not None:
        owner["lifetime_shared_footage_seconds"] += duration
        engine.touch(owner)
        engine.sync_resident_footage(owner)
    engine.sync_request(request_row)
    return envelope.created(serialize.dump("SharedClip", clip))


@bp.post("/neighborhood-safety/consent-solicitations/<solicitation_id>/decline")
def decline_footage(solicitation_id):
    actor = auth.authenticate(("Resident",))
    sol = fetch.must("ConsentSolicitation", solicitation_id)
    body = v.body_json()
    v.enum_field(body, "decline_reason", DECLINE_REASONS)
    resident = db.residents.get(sol["resident_id"])
    auth.require_resident_scope(actor, sol["resident_id"])
    require_active(resident)
    request_row = db.video_requests.get(sol["video_request_id"])
    if request_row["lifecycle_state"] != "SOLICITING":
        raise ApiError("ERR_REQUEST_NOT_SOLICITING",
                       "The owning request is no longer soliciting")
    if sol["status"] != "SOLICITED":
        raise ApiError("ERR_SOLICITATION_ALREADY_RESOLVED",
                       "Solicitation %s is closed" % sol["id"])
    if now() >= sol["respond_deadline_utc"]:
        raise ApiError("ERR_SOLICITATION_DEADLINE_PASSED",
                       "The response deadline has passed")

    engine.decline_solicitation(sol, "OWNER_DECLINE")
    engine.sync_request(request_row)
    return envelope.ok(serialize.dump("ConsentSolicitation", sol))


@bp.post("/neighborhood-safety/shared-clips/<clip_id>/purge")
def purge_shared_clip(clip_id):
    actor = auth.authenticate(("Resident", "PlatformAdmin"))
    clip = fetch.must("SharedClip", clip_id)
    body = v.body_json()
    purge_reason = v.enum_field(body, "purge_reason", PURGE_REASONS)
    if actor.role == "Resident":
        auth.require_resident_scope(actor, clip["owner_resident_id"])
        require_active(db.residents.get(clip["owner_resident_id"]))
    if clip["status"] == "PURGED":
        raise ApiError("ERR_CLIP_ALREADY_PURGED",
                       "Clip %s has already been purged" % clip["id"])
    if clip["status"] == "LEGAL_HOLD":
        if purge_reason != "LEGAL_RELEASE" or actor.role != "PlatformAdmin":
            raise ApiError("ERR_CLIP_UNDER_LEGAL_HOLD",
                           "Only a platform administrator may release a hold")
    elif clip["status"] == "RETAINED":
        if purge_reason not in ("OWNER_REVOCATION", "RETENTION_EXPIRED",
                                "LEGAL_RELEASE"):
            raise ApiError("ERR_INVALID_REQUEST",
                           "purge_reason is not accepted from RETAINED")
    elif clip["status"] == "PURGE_PENDING":
        if purge_reason != "ACCOUNT_DEACTIVATED":
            raise ApiError("ERR_INVALID_REQUEST",
                           "purge_reason is not accepted from PURGE_PENDING")

    engine.purge_clip(clip, purge_reason)
    return envelope.ok(serialize.dump("SharedClip", clip))


# --------------------------------------------------------------------------
# reads
# --------------------------------------------------------------------------

@bp.get("/neighborhood-safety/consent-solicitations/<solicitation_id>")
def read_solicitation(solicitation_id):
    auth.authenticate(("PlatformAdmin", "AgencyAdmin", "Officer", "Resident"))
    sol = fetch.must("ConsentSolicitation", solicitation_id)
    return envelope.ok(serialize.dump("ConsentSolicitation", sol))


@bp.get("/neighborhood-safety/consent-solicitations")
def list_solicitations():
    auth.authenticate(("PlatformAdmin", "AgencyAdmin", "Officer", "Resident"))
    limit, offset = v.pagination()
    filters = {
        "video_request_id": v.query_str("video_request_id"),
        "device_id": v.query_str("device_id"),
        "resident_id": v.query_str("resident_id"),
        "status": v.query_enum("status", SOLICITATION_STATUSES),
    }
    suppressed = v.query_bool("notification_suppressed")
    rows = list(db.solicitations.values())
    for key, value in filters.items():
        if value is not None:
            rows = [r for r in rows if r[key] == value]
    if suppressed is not None:
        rows = [r for r in rows if r["notification_suppressed"] == suppressed]
    rows.sort(key=lambda r: (r["created_at"], r["dispatch_rank"]))
    page, total = v.paginate(rows, limit, offset)
    return envelope.collection(
        serialize.dump_all("ConsentSolicitation", page), limit, offset, total)


@bp.get("/neighborhood-safety/shared-clips/<clip_id>")
def read_clip(clip_id):
    auth.authenticate(("PlatformAdmin", "AgencyAdmin", "Officer", "Resident"))
    clip = fetch.must("SharedClip", clip_id)
    return envelope.ok(serialize.dump("SharedClip", clip))


@bp.get("/neighborhood-safety/shared-clips")
def list_clips():
    auth.authenticate(("PlatformAdmin", "AgencyAdmin", "Officer", "Resident"))
    limit, offset = v.pagination()
    filters = {
        "consent_solicitation_id": v.query_str("consent_solicitation_id"),
        "video_request_id": v.query_str("video_request_id"),
        "device_id": v.query_str("device_id"),
        "owner_resident_id": v.query_str("owner_resident_id"),
        "status": v.query_enum("status", CLIP_STATUSES),
        "retention_variant": v.query_enum("retention_variant",
                                          RETENTION_VARIANTS),
    }
    rows = list(db.clips.values())
    for key, value in filters.items():
        if value is not None:
            rows = [r for r in rows if r[key] == value]
    rows = store.by_created(rows)
    page, total = v.paginate(rows, limit, offset)
    return envelope.collection(serialize.dump_all("SharedClip", page), limit,
                               offset, total)
