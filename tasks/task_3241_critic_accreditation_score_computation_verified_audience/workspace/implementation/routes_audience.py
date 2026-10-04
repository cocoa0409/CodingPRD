"""Routes: audience members, ticket verifications, audience ratings, bombing incidents."""
from datetime import timedelta
from flask import Blueprint, request
from db import db, _parse_iso
from errors import err
from middleware import require_roles
from helpers import (body_json, require_field, new_entity, touch,
                     get_or_404, list_page)
from response import (success_object, success_list, audience_member_view,
                      ticket_verification_view, audience_rating_view,
                      bombing_incident_view)
from scoring import (recompute_audience_score, compute_bombing_index,
                     BOMBING_THRESHOLD_BPS, DETECTION_WINDOW_HOURS)

bp = Blueprint("audience", __name__)

VIEW_ROLES = ("PlatformAdmin", "AccreditationBoard", "AudienceMember")


# ---------------- audience members ----------------

@bp.post("/audience-members")
def create_audience_member():
    require_roles("PlatformAdmin")
    body = body_json()
    email = require_field(body, "email")
    display_name = require_field(body, "display_name")
    if not isinstance(email, str) or not isinstance(display_name, str):
        raise err("ERR_INVALID_REQUEST", "email and display_name must be strings")
    for m in db.audience_members.values():
        if m["email"] == email:
            raise err("ERR_INVALID_REQUEST", "email must be unique")
    member = new_entity(db.audience_members, {
        "email": email,
        "display_name": display_name,
    })
    member["account_created_at"] = member["created_at"]
    return success_object(audience_member_view(member), status=201)


# ---------------- ticket verifications ----------------

@bp.post("/releases/<rid>/ticket-verifications")
def submit_ticket_verification(rid):
    user_id, _role = require_roles("AudienceMember")
    rel = get_or_404(db.releases, rid, "Release")
    body = body_json()
    member_id = require_field(body, "audience_member_id")
    showtime_at = require_field(body, "showtime_at")
    exhibitor_code = require_field(body, "exhibitor_code")
    if (not isinstance(member_id, str) or not isinstance(showtime_at, str)
            or not isinstance(exhibitor_code, str)):
        raise err("ERR_INVALID_REQUEST",
                  "audience_member_id, showtime_at and exhibitor_code must be strings")
    try:
        _parse_iso(showtime_at)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", "showtime_at must be an ISO 8601 instant")
    get_or_404(db.audience_members, member_id, "AudienceMember")
    if member_id != user_id:
        raise err("ERR_FORBIDDEN", "audience_member_id must equal X-User-ID")
    tv = new_entity(db.ticket_verifications, {
        "release_id": rel["id"],
        "audience_member_id": member_id,
        "showtime_at": showtime_at,
        "exhibitor_code": exhibitor_code,
        "status": "SUBMITTED",
    })
    return success_object(ticket_verification_view(tv), status=201)


def _tv_filter(t, args):
    release_id = args.get("release_id")
    member_id = args.get("audience_member_id")
    if release_id is not None and t["release_id"] != release_id:
        return False
    if member_id is not None and t["audience_member_id"] != member_id:
        return False
    return True


@bp.get("/ticket-verifications")
def list_ticket_verifications():
    require_roles(*VIEW_ROLES)
    items, limit, offset, total = list_page(
        db.ticket_verifications, ticket_verification_view,
        filters=lambda t: _tv_filter(t, request.args))
    return success_list(items, limit, offset, total)


@bp.get("/ticket-verifications/<tvid>")
def get_ticket_verification(tvid):
    require_roles(*VIEW_ROLES)
    tv = get_or_404(db.ticket_verifications, tvid, "TicketVerification")
    return success_object(ticket_verification_view(tv))


@bp.post("/ticket-verifications/<tvid>/transition")
def transition_ticket_verification(tvid):
    require_roles("PlatformAdmin")
    tv = get_or_404(db.ticket_verifications, tvid, "TicketVerification")
    body = body_json()
    action = require_field(body, "action")
    if action not in ("VERIFY", "REJECT"):
        raise err("ERR_INVALID_REQUEST", "Unknown action: %s" % action)
    if tv["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE",
                  "TicketVerification in status %s cannot transition" % tv["status"])
    if action == "VERIFY":
        rel = db.releases.get(tv["release_id"])
        if rel is None:
            raise err("ERR_NOT_FOUND", "Release not found: %s" % tv["release_id"])
        showtime = _parse_iso(tv["showtime_at"])
        start = _parse_iso(rel["theatrical_window_start"])
        end = _parse_iso(rel["theatrical_window_end"])
        if not (start <= showtime <= end):
            raise err("ERR_VERIFICATION_WINDOW_MISS",
                      "showtime_at is outside the release theatrical window")
        tv["status"] = "VERIFIED"
    else:
        tv["status"] = "REJECTED"
    touch(tv)
    return success_object(ticket_verification_view(tv))


# ---------------- audience ratings ----------------

@bp.post("/releases/<rid>/audience-ratings")
def create_audience_rating(rid):
    user_id, _role = require_roles("AudienceMember")
    rel = get_or_404(db.releases, rid, "Release")
    body = body_json()
    member_id = require_field(body, "audience_member_id")
    stars = require_field(body, "stars")
    if not isinstance(member_id, str):
        raise err("ERR_INVALID_REQUEST", "audience_member_id must be a string")
    if not isinstance(stars, int) or isinstance(stars, bool) or stars < 1 or stars > 5:
        raise err("ERR_INVALID_REQUEST", "stars must be an integer from 1 through 5")
    tvid = body.get("ticket_verification_id")
    if tvid is not None and not isinstance(tvid, str):
        raise err("ERR_INVALID_REQUEST", "ticket_verification_id must be a string")
    get_or_404(db.audience_members, member_id, "AudienceMember")
    if tvid is not None:
        get_or_404(db.ticket_verifications, tvid, "TicketVerification")
    if member_id != user_id:
        raise err("ERR_FORBIDDEN", "audience_member_id must equal X-User-ID")
    for r in db.audience_ratings.values():
        if (r["audience_member_id"] == member_id and r["release_id"] == rid
                and r["status"] != "INVALIDATED"):
            raise err("ERR_DUPLICATE_VERIFIED_RATING",
                      "Audience member already has a non-INVALIDATED rating on this release")
    rating = new_entity(db.audience_ratings, {
        "release_id": rel["id"],
        "audience_member_id": member_id,
        "stars": stars,
        "ticket_verification_id": tvid,
        "status": "UNVERIFIED",
    })
    # Creation recomputes the all-ratings diagnostic variant.
    recompute_audience_score(rel)
    return success_object(audience_rating_view(rating), status=201)


def _rating_filter(r, args):
    release_id = args.get("release_id")
    member_id = args.get("audience_member_id")
    tvid = args.get("ticket_verification_id")
    if release_id is not None and r["release_id"] != release_id:
        return False
    if member_id is not None and r["audience_member_id"] != member_id:
        return False
    if tvid is not None and r.get("ticket_verification_id") != tvid:
        return False
    return True


@bp.get("/audience-ratings")
def list_audience_ratings():
    require_roles(*VIEW_ROLES)
    items, limit, offset, total = list_page(
        db.audience_ratings, audience_rating_view,
        filters=lambda r: _rating_filter(r, request.args))
    return success_list(items, limit, offset, total)


@bp.get("/audience-ratings/<arid>")
def get_audience_rating(arid):
    require_roles(*VIEW_ROLES)
    rating = get_or_404(db.audience_ratings, arid, "AudienceRating")
    return success_object(audience_rating_view(rating))


@bp.post("/audience-ratings/<arid>/transition")
def transition_audience_rating(arid):
    user_id, role = require_roles("AudienceMember", "PlatformAdmin")
    rating = get_or_404(db.audience_ratings, arid, "AudienceRating")
    body = body_json()
    action = require_field(body, "action")
    if action not in ("VERIFY", "INVALIDATE"):
        raise err("ERR_INVALID_REQUEST", "Unknown action: %s" % action)
    rel = db.releases.get(rating["release_id"])

    if action == "VERIFY":
        if role != "AudienceMember":
            raise err("ERR_UNAUTHORIZED", "Only the owning AudienceMember may verify a rating")
        if rating["audience_member_id"] != user_id:
            raise err("ERR_FORBIDDEN", "Only the rating owner may verify it")
        if rating["status"] != "UNVERIFIED":
            raise err("ERR_INVALID_STATE",
                      "AudienceRating in status %s cannot be verified" % rating["status"])
        tvid = require_field(body, "ticket_verification_id")
        if not isinstance(tvid, str):
            raise err("ERR_INVALID_REQUEST", "ticket_verification_id must be a string")
        tv = db.ticket_verifications.get(tvid)
        if (tv is None or tv["status"] != "VERIFIED"
                or tv["release_id"] != rating["release_id"]
                or tv["audience_member_id"] != rating["audience_member_id"]):
            raise err("ERR_TICKET_NOT_VERIFIED",
                      "ticket_verification_id must reference a VERIFIED ticket verification "
                      "for the same release and the same audience member")
        if rel is not None and rel["audience_display_suspended"]:
            raise err("ERR_BOMBING_SUSPENSION_ACTIVE",
                      "Verified-path rating rejected while a CONFIRMED bombing incident "
                      "suspends the release")
        rating["status"] = "VERIFIED"
        rating["ticket_verification_id"] = tvid
        touch(rating)
        if rel is not None:
            recompute_audience_score(rel)
        return success_object(audience_rating_view(rating))

    # INVALIDATE — PlatformAdmin only.
    if role != "PlatformAdmin":
        raise err("ERR_UNAUTHORIZED", "Only PlatformAdmin may invalidate a rating")
    if rating["status"] not in ("UNVERIFIED", "VERIFIED"):
        raise err("ERR_INVALID_STATE",
                  "AudienceRating in status %s cannot be invalidated" % rating["status"])
    rating["status"] = "INVALIDATED"
    touch(rating)
    if rel is not None:
        recompute_audience_score(rel)
    return success_object(audience_rating_view(rating))


# ---------------- bombing incidents ----------------

@bp.post("/releases/<rid>/bombing-incidents")
def open_bombing_incident(rid):
    require_roles("PlatformAdmin")
    rel = get_or_404(db.releases, rid, "Release")
    index_bps = compute_bombing_index(rid)
    incident = new_entity(db.bombing_incidents, {
        "release_id": rel["id"],
        "detection_index_bps": index_bps,
        "auto_flagged": index_bps >= BOMBING_THRESHOLD_BPS,
        "status": "OPEN",
    })
    return success_object(bombing_incident_view(incident), status=201)


@bp.post("/bombing-incidents/<iid>/transition")
def transition_bombing_incident(iid):
    require_roles("PlatformAdmin")
    incident = get_or_404(db.bombing_incidents, iid, "BombingIncident")
    body = body_json()
    action = require_field(body, "action")
    if action not in ("CONFIRM", "DISMISS", "RESOLVE"):
        raise err("ERR_INVALID_REQUEST", "Unknown action: %s" % action)
    rel = db.releases.get(incident["release_id"])

    if action == "CONFIRM":
        if incident["status"] != "OPEN":
            raise err("ERR_INVALID_STATE",
                      "BombingIncident in status %s cannot be confirmed" % incident["status"])
        incident["status"] = "CONFIRMED"
        touch(incident)
        if rel is not None:
            rel["audience_display_suspended"] = True
            touch(rel)
            # Invalidate ratings created within the incident window. Entities
            # are stamped at the logical clock, so a rating created exactly at
            # the present instant is in-window (closed at `now`, half-open on
            # the past side).
            window_start = db.logical_clock - timedelta(hours=DETECTION_WINDOW_HOURS)
            for r in db.audience_ratings.values():
                if r["release_id"] != rel["id"]:
                    continue
                if r["status"] not in ("VERIFIED", "UNVERIFIED"):
                    continue
                created = _parse_iso(r["created_at"])
                if window_start <= created <= db.logical_clock:
                    r["status"] = "INVALIDATED"
                    touch(r)
            recompute_audience_score(rel)
        return success_object(bombing_incident_view(incident))

    if action == "DISMISS":
        if incident["status"] != "OPEN":
            raise err("ERR_INVALID_STATE",
                      "BombingIncident in status %s cannot be dismissed" % incident["status"])
        incident["status"] = "DISMISSED"
        touch(incident)
        return success_object(bombing_incident_view(incident))

    # RESOLVE
    if incident["status"] != "CONFIRMED":
        raise err("ERR_INVALID_STATE",
                  "BombingIncident in status %s cannot be resolved" % incident["status"])
    incident["status"] = "RESOLVED"
    touch(incident)
    if rel is not None:
        rel["audience_display_suspended"] = False
        touch(rel)
        recompute_audience_score(rel)
    return success_object(bombing_incident_view(incident))
