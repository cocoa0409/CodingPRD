"""Activity routes: upload with duplicate detection, lists, get, correct_category."""
from flask import Blueprint, request

from db import db
from errors import (err_validation, err_not_found, err_duplicate_activity,
                    err_inconsistent, err_forbidden)
from middleware import require_roles, check_self_or_admin
from response import (ok_object, ok_list, init_common, touch, parse_pagination,
                      parse_iso_dt)
from serializers import activity_view
from services import (SPORT_TYPES, recompute_obfuscation, match_sweep_for_activity,
                      challenge_progress_for_activity, recompute_heatmap,
                      speed_and_vehicle_check, recompute_ranks,
                      recompute_activity_elevation, logical_now_dt,
                      effective_category, category_matches_segment,
                      activity_qualifies_heatmap)

bp = Blueprint("activities", __name__)


def _validate_track_points(tp):
    if not isinstance(tp, list) or len(tp) < 2:
        raise err_validation("track_points must contain >= 2 points")
    for p in tp:
        if not isinstance(p, dict):
            raise err_validation("track_points entries must be objects")
        if not isinstance(p.get("lat"), (int, float)) or not isinstance(p.get("lng"), (int, float)):
            raise err_validation("track_points entries need lat/lng")
        if "t_offset_s" not in p:
            raise err_validation("track_points entries need t_offset_s")


def _find_duplicate(athlete_id, idem_key, device_source, started_dt, distance_m):
    """Return the canonical (earliest-created) non-REJECTED activity matching
    the duplicate criteria, or None."""
    cands = []
    for a in db.activities.values():
        if a["athlete_id"] != athlete_id or a["status"] == "REJECTED":
            continue
        if idem_key is not None and a.get("idempotency_key") == idem_key:
            cands.append(a)
            continue
        if a.get("device_source") != device_source:
            continue
        prev_dt = parse_iso_dt(a["started_at"])
        if prev_dt is None:
            continue
        if abs((started_dt - prev_dt).total_seconds()) > 120:
            continue
        base = a["distance_m"]
        if base <= 0:
            continue
        if abs(distance_m - base) > 0.05 * base:
            continue
        cands.append(a)
    if not cands:
        return None
    cands.sort(key=lambda a: a["created_at"])
    return cands[0]


@bp.post("/v1/athletes/<aid>/activities")
def upload_activity(aid):
    user_id, role = require_roles("Athlete", "PlatformAdmin")
    a = db.athletes.get(aid)
    if not a:
        raise err_not_found("Athlete not found")
    check_self_or_admin(user_id, role, aid)
    body = request.get_json(silent=True) or {}

    device_source = body.get("device_source")
    sport_type = body.get("sport_type")
    started_at = body.get("started_at")
    duration_s = body.get("duration_s")
    distance_m = body.get("distance_m")
    track_points = body.get("track_points")
    start_lat = body.get("start_lat"); start_lng = body.get("start_lng")
    end_lat = body.get("end_lat"); end_lng = body.get("end_lng")
    idem_key = body.get("idempotency_key")
    effort_hints = body.get("effort_hints", [])
    strict = body.get("strict_duplicate", False)

    if not isinstance(device_source, str) or not device_source:
        raise err_validation("device_source required")
    if sport_type not in SPORT_TYPES:
        raise err_validation("sport_type invalid")
    started_dt = parse_iso_dt(started_at)
    if started_dt is None:
        raise err_validation("started_at must be ISO8601 UTC")
    if not isinstance(duration_s, int) or isinstance(duration_s, bool) or duration_s <= 0:
        raise err_validation("duration_s must be > 0")
    if not isinstance(distance_m, (int, float)) or isinstance(distance_m, bool) or distance_m <= 0:
        raise err_validation("distance_m must be > 0")
    _validate_track_points(track_points)
    for v in (start_lat, start_lng, end_lat, end_lng):
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            raise err_validation("start/end lat/lng required")
    if not isinstance(idem_key, str) or not idem_key:
        raise err_validation("idempotency_key required")
    if not isinstance(effort_hints, list):
        raise err_validation("effort_hints must be an array")

    act = init_common({
        "athlete_id": aid,
        "device_source": device_source,
        "sport_type": sport_type,
        "started_at": started_at,
        "duration_s": duration_s,
        "distance_m": distance_m,
        "track_points": track_points,
        "start_lat": start_lat, "start_lng": start_lng,
        "end_lat": end_lat, "end_lng": end_lng,
        "idempotency_key": idem_key,
        "effort_hints": effort_hints,
        "duplicate_of_id": None,
        "status": "PROCESSING",
        "flag_status": "NONE",
        "auto_hidden": False,
        "corrected_sport_type": None,
        "obfuscated_track": [],
        "obfuscated_start_lat": None, "obfuscated_start_lng": None,
        "obfuscated_end_lat": None, "obfuscated_end_lng": None,
        "elevation_gain_m": 0,
    })

    dup = _find_duplicate(aid, idem_key, device_source, started_dt, distance_m)
    if dup is not None:
        if strict:
            raise err_duplicate_activity()
        act["status"] = "DUPLICATE"
        act["duplicate_of_id"] = dup["id"]
        db.activities[act["id"]] = act
        return ok_object(activity_view(act, user_id, role), 201)

    # COMPLETED path
    act["status"] = "COMPLETED"
    act["_completed_at_dt"] = logical_now_dt()
    db.activities[act["id"]] = act
    # 1. obfuscation
    recompute_obfuscation(act)
    # 2. segment match sweep + speed checks
    match_sweep_for_activity(act)
    # 3. challenge progress
    challenge_progress_for_activity(act)
    # 4. heatmap contribution
    recompute_heatmap()
    touch(act)
    return ok_object(activity_view(act, user_id, role), 201)


@bp.get("/v1/athletes/<aid>/activities")
def list_athlete_activities(aid):
    user_id, role = require_roles("Athlete", "PlatformAdmin", "Moderator")
    if not db.athletes.get(aid):
        raise err_not_found("Athlete not found")
    status_f = request.args.get("status")
    sport_f = request.args.get("sport_type")
    items = [a for a in db.activities.values() if a["athlete_id"] == aid]
    if status_f:
        items = [a for a in items if a["status"] == status_f]
    if sport_f:
        items = [a for a in items if a["sport_type"] == sport_f]
    items.sort(key=lambda a: a["created_at"])
    limit, offset, _ = parse_pagination(request.args)
    return ok_list([activity_view(a, user_id, role) for a in items], limit, offset)


@bp.get("/v1/activities")
def list_activities_flat():
    user_id, role = require_roles("Athlete", "PlatformAdmin", "Moderator")
    athlete_f = request.args.get("athlete_id")
    dup_f = request.args.get("duplicate_of_id")
    status_f = request.args.get("status")
    sport_f = request.args.get("sport_type")
    items = list(db.activities.values())
    if athlete_f:
        items = [a for a in items if a["athlete_id"] == athlete_f]
    if dup_f:
        items = [a for a in items if a.get("duplicate_of_id") == dup_f]
    if status_f:
        items = [a for a in items if a["status"] == status_f]
    if sport_f:
        items = [a for a in items if a["sport_type"] == sport_f]
    items.sort(key=lambda a: a["created_at"])
    limit, offset, _ = parse_pagination(request.args)
    return ok_list([activity_view(a, user_id, role) for a in items], limit, offset)


@bp.get("/v1/activities/<aid>")
def get_activity(aid):
    user_id, role = require_roles("Athlete", "PlatformAdmin", "Moderator")
    a = db.activities.get(aid)
    if not a:
        raise err_not_found("Activity not found")
    privileged = role in ("PlatformAdmin", "Moderator")
    is_owner = role == "Athlete" and user_id == a["athlete_id"]
    if a.get("auto_hidden") and not (privileged or is_owner):
        raise err_not_found("Activity not found")
    return ok_object(activity_view(a, user_id, role))


@bp.post("/v1/activities/<aid>/correct_category")
def correct_category(aid):
    user_id, role = require_roles("Athlete", "PlatformAdmin", "Moderator")
    a = db.activities.get(aid)
    if not a:
        raise err_not_found("Activity not found")
    if role == "Athlete" and user_id != a["athlete_id"]:
        raise err_forbidden("Only the owner may correct category")
    body = request.get_json(silent=True) or {}
    new_cat = body.get("corrected_sport_type")
    current_eff = effective_category(a)
    if new_cat not in SPORT_TYPES or new_cat == current_eff:
        raise err_inconsistent("corrected_sport_type invalid or equal to current effective category")
    a["corrected_sport_type"] = new_cat
    # Exclude ELIGIBLE efforts whose segment no longer matches the new category
    affected_segments = set()
    for e in db.efforts.values():
        if e["activity_id"] != aid:
            continue
        seg = db.segments.get(e["segment_id"])
        if not seg:
            continue
        if e["flag_status"] == "ELIGIBLE" and not category_matches_segment(new_cat, seg["sport_type"]):
            e["flag_status"] = "EXCLUDED"
            e["exclusion_reason"] = "CATEGORY_MISMATCH"
            touch(e)
            affected_segments.add(e["segment_id"])
    # Re-run speed/vehicle checks on remaining ELIGIBLE efforts
    for e in db.efforts.values():
        if e["activity_id"] == aid and e["flag_status"] == "ELIGIBLE":
            speed_and_vehicle_check(e, a)
            touch(e)
            affected_segments.add(e["segment_id"])
    recompute_activity_elevation(a)
    for sid in affected_segments:
        recompute_ranks(sid)
    recompute_heatmap()
    touch(a)
    return ok_object(activity_view(a, user_id, role))
