"""Seasons: create, list, get, advance-phase (OCC)."""
from flask import Blueprint, request

from db import db, parse_iso
from errors import (
    err_invalid_request, err_duplicate, err_already_terminal,
    err_invalid_state, err_stale_season_version, err_not_found,
)
from middleware import require_roles
from paginate import parse_pagination, paginate
from response import success
from services import (
    new_resource, touch, get_or_404, cascade_season_post, find_slate,
)
from validate import (
    body_json, req_string, req_datetime, opt_int, opt_field,
)

bp = Blueprint("seasons", __name__)


@bp.post("/seasons")
@require_roles("LeagueOps", "PlatformAdmin")
def create_season(auth):
    body = body_json()
    rights_grant_id = req_string(body, "rights_grant_id")
    get_or_404(db.rights_grants, rights_grant_id)
    label = req_string(body, "label")
    weeks = opt_int(body, "regular_season_weeks")
    if weeks is None:
        from validate import req_int
        weeks = req_int(body, "regular_season_weeks", minimum=1, maximum=22)
    elif weeks < 1 or weeks > 22:
        raise err_invalid_request("regular_season_weeks must be between 1 and 22")
    season_start_date = req_datetime(body, "season_start_date")
    season_end_date = req_datetime(body, "season_end_date")
    grace_days = opt_int(body, "grace_days", default=7)
    if grace_days is None:
        grace_days = 7
    if grace_days < 0 or grace_days > 30:
        raise err_invalid_request("grace_days must be between 0 and 30")
    student_discount_pct = opt_int(body, "student_discount_pct", default=50)
    if student_discount_pct is None:
        student_discount_pct = 50
    if student_discount_pct < 0 or student_discount_pct > 90:
        raise err_invalid_request("student_discount_pct must be between 0 and 90")
    if parse_iso(season_end_date) <= parse_iso(season_start_date):
        raise err_invalid_request("season_end_date must be after season_start_date")
    for s in db.seasons.values():
        if s["rights_grant_id"] == rights_grant_id and s["label"] == label:
            raise err_duplicate("Season label already exists within this grant")

    season = new_resource()
    season.update({
        "rights_grant_id": rights_grant_id,
        "label": label,
        "regular_season_weeks": weeks,
        "season_start_date": season_start_date,
        "season_end_date": season_end_date,
        "phase": "PRE_SALE",
        "grace_days": grace_days,
        "student_discount_pct": student_discount_pct,
    })
    db.seasons[season["id"]] = season
    return success(season, status=201)


@bp.get("/seasons")
@require_roles("PlatformAdmin", "LeagueOps", "ComplianceAuditor", "SupportAgent")
def list_seasons(auth):
    limit, offset = parse_pagination()
    rights_grant_id = request.args.get("rights_grant_id")
    phase = request.args.get("phase")
    items = sorted(db.seasons.values(), key=lambda r: r["created_at"])
    if rights_grant_id is not None:
        items = [s for s in items if s["rights_grant_id"] == rights_grant_id]
    if phase is not None:
        items = [s for s in items if s["phase"] == phase]
    window, page = paginate(items, limit, offset)
    return success(window, pagination=page)


@bp.get("/seasons/<sid>")
@require_roles("PlatformAdmin", "LeagueOps", "ComplianceAuditor", "SupportAgent")
def get_season(sid, auth):
    season = get_or_404(db.seasons, sid)
    return success(season)


@bp.post("/seasons/<sid>/advance-phase")
@require_roles("LeagueOps")
def advance_phase(sid, auth):
    season = get_or_404(db.seasons, sid)
    if season["phase"] == "POST":
        raise err_already_terminal()
    if season["phase"] not in ("PRE_SALE", "REGULAR"):
        raise err_invalid_state()
    body = body_json()
    expected = opt_field(body, "expected_season_version")
    if expected is not None and expected != season["version"]:
        raise err_stale_season_version()
    if season["phase"] == "PRE_SALE":
        slates = [s for s in db.week_slates.values() if s["season_id"] == season["id"]]
        if not slates:
            raise err_invalid_state("Season requires at least one WeekSlate to advance to REGULAR")
        season["phase"] = "REGULAR"
        touch(season)
    else:  # REGULAR -> POST
        season["phase"] = "POST"
        touch(season)
        cascade_season_post(season)
    return success(season)
