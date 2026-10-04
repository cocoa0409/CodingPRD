"""Partner capacity ceilings (PartnerCapacityProfile)."""

from flask import Blueprint, request

from db import DB, iso3, new_id, parse_iso
from errors import ApiError
from middleware import (ALLOCATION_PLANNER, GIVING_PARTNER_COORDINATOR,
                        IMPACT_AUDITOR, roles)
from response import pagination_meta, success
from routes import _common as common
from services import core, serial
from validation import (as_instant, as_int, as_str, body, paginate, pagination,
                        require)

bp = Blueprint("capacity", __name__)

PROFILE_VIEWERS = [GIVING_PARTNER_COORDINATOR, ALLOCATION_PLANNER, IMPACT_AUDITOR]


def _season_for_code(season_code):
    season = DB.season_by_code(season_code)
    if not season:
        raise ApiError("ERR_SEASON_NOT_FOUND")
    return season


def _supersede_earlier(partner_id, season_code, effective_from):
    """A later effective_from supersedes the earlier profile (terminal)."""
    for profile in DB.capacity_profiles.values():
        if profile.get("partner_id") != partner_id:
            continue
        if profile.get("season_code") != season_code:
            continue
        if profile.get("status") == "SUPERSEDED":
            continue
        if parse_iso(profile["effective_from"]) < effective_from:
            profile["status"] = "SUPERSEDED"
            DB.touch(profile)


@bp.route("/impact-program/giving-partners/<partner_id>/capacity-profiles", methods=["POST"])
@roles(GIVING_PARTNER_COORDINATOR)
def declare_profile(partner_id):
    partner = common.partner_or_404(partner_id)
    payload = body()
    require(payload, "season_code", "max_allocatable_units", "effective_from", "effective_to")
    season_code = as_str(payload, "season_code", required=True)
    max_units = as_int(payload, "max_allocatable_units", required=True, minimum=0)
    effective_from = as_instant(payload, "effective_from", required=True)
    effective_to = as_instant(payload, "effective_to", required=True)

    if effective_to < effective_from:
        raise ApiError("ERR_INVALID_REQUEST", "effective_to precedes effective_from.")

    _season_for_code(season_code)

    # PRD §3.2 makes selectability a half-open window (`effective_from` opens it,
    # `effective_to` closes it). Two profiles for the same partner and season
    # therefore conflict only when their windows truly overlap: an exactly
    # adjacent successor is legal, an overlapping one is ambiguous
    # (`ERR_CAPACITY_PROFILE_AMBIGUOUS`), and a window that never intersects
    # the successor at all is superseded by it. A profile the approval path
    # opened automatically (PRD §3.1, for a `PLANNED` season) is a placeholder
    # the coordinator replaces with the explicit ceiling.
    window_from = parse_iso(effective_from)
    window_to = parse_iso(effective_to)
    for profile in DB.capacity_profiles.values():
        if profile.get("partner_id") != partner_id or profile.get("season_code") != season_code:
            continue
        if profile.get("status") == "SUPERSEDED":
            continue
        if (profile.get("partner_open_season") or profile.get("_system_created")
                or not profile.get("effective_from") or not profile.get("effective_to")):
            # PRD §3.1's approval-time profile is a placeholder that carries no
            # declared window, so it never contends with the explicit ceiling.
            profile["status"] = "SUPERSEDED"
            DB.touch(profile)
            continue
        p_from = parse_iso(profile["effective_from"])
        p_to = parse_iso(profile["effective_to"])
        if p_from < window_to and window_from < p_to:
            raise ApiError("ERR_CAPACITY_PROFILE_AMBIGUOUS")
        if p_from < window_from:
            # The declared successor starts later and does not overlap, so the
            # earlier profile stops being selectable.
            profile["status"] = "SUPERSEDED"
            DB.touch(profile)
            continue
        raise ApiError("ERR_DUPLICATE_RESOURCE")

    now = iso3(DB.now())
    record = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "partner_id": partner_id,
        "season_code": season_code,
        "max_allocatable_units": max_units,
        "reserved_units": 0,
        "committed_units": 0,
        "capacity_utilization_units": 0,
        "effective_from": iso3(effective_from),
        "effective_to": iso3(effective_to),
        "status": "ACTIVE",
        "need_tier": partner.get("need_tier"),
    }
    DB.capacity_profiles[record["id"]] = record
    _supersede_earlier(partner_id, season_code, effective_from)
    core.refresh_profile_status(record)
    return success(serial.serialize("PartnerCapacityProfile", record)), 201


@bp.route("/impact-program/giving-partners/<partner_id>/capacity-profiles", methods=["GET"])
@roles(*PROFILE_VIEWERS)
def list_partner_profiles(partner_id):
    common.partner_or_404(partner_id)
    season_code = request.args.get("season_code")
    status = request.args.get("status")
    limit, offset = pagination()
    rows = [p for p in DB.capacity_profiles.values() if p.get("partner_id") == partner_id]
    if season_code:
        rows = [r for r in rows if r.get("season_code") == season_code]
    if status:
        rows = [r for r in rows if r.get("status") == status]
    rows.sort(key=lambda r: r.get("created_at") or "")
    page, total = paginate(rows, limit, offset)
    return success(serial.serialize_many("PartnerCapacityProfile", page),
                   pagination=pagination_meta(limit, offset, total))


@bp.route("/impact-program/capacity-profiles", methods=["GET"])
@roles(ALLOCATION_PLANNER, IMPACT_AUDITOR)
def list_profiles():
    partner_id = request.args.get("partner_id")
    season_code = request.args.get("season_code")
    status = request.args.get("status")
    limit, offset = pagination()
    rows = list(DB.capacity_profiles.values())
    if partner_id:
        rows = [r for r in rows if r.get("partner_id") == partner_id]
    if season_code:
        rows = [r for r in rows if r.get("season_code") == season_code]
    if status:
        rows = [r for r in rows if r.get("status") == status]
    rows.sort(key=lambda r: r.get("created_at") or "")
    page, total = paginate(rows, limit, offset)
    return success(serial.serialize_many("PartnerCapacityProfile", page),
                   pagination=pagination_meta(limit, offset, total))


@bp.route("/impact-program/capacity-profiles/<profile_id>", methods=["GET"])
@roles(ALLOCATION_PLANNER, IMPACT_AUDITOR)
def get_profile(profile_id):
    record = common.profile_or_404(profile_id)
    core.recompute_profile(record)
    return success(serial.serialize("PartnerCapacityProfile", record))