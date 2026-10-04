"""Segment, effort, leaderboard, flag routes."""
from flask import Blueprint, request

from db import db
from errors import (err_validation, err_not_found, err_unique, err_forbidden,
                    err_invalid_state, err_safety, err_segment_overlap,
                    err_subscription, err_flag_self)
from middleware import require_roles, check_self_or_admin
from response import (ok_object, ok_list, init_common, touch, parse_pagination)
from serializers import segment_view, effort_view, flag_view
from services import (SEGMENT_SPORTS, retro_sweep_for_segment, recompute_ranks,
                      recompute_activity_elevation, recompute_heatmap,
                      haversine_m, OVERLAP_EPSILON_M, has_active_subscription,
                      apply_auto_hide)

bp = Blueprint("segments", __name__)


# ------------------------------------------------------------- segments ----

@bp.post("/v1/segments")
def create_segment():
    require_roles("Athlete", "PlatformAdmin")
    body = request.get_json(silent=True) or {}
    creator_id = body.get("creator_id")
    name = body.get("name")
    sport_type = body.get("sport_type")
    start_lat = body.get("start_lat"); start_lng = body.get("start_lng")
    end_lat = body.get("end_lat"); end_lng = body.get("end_lng")
    distance_m = body.get("distance_m")
    city = body.get("city")
    hazard_index = body.get("hazard_index", 0)

    if not isinstance(name, str) or not (3 <= len(name) <= 80):
        raise err_validation("name must be 3..80 chars")
    if sport_type not in SEGMENT_SPORTS:
        raise err_validation("sport_type must be RIDE, RUN or SWIM")
    for v in (start_lat, start_lng, end_lat, end_lng):
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            raise err_validation("coordinates required")
    if not isinstance(distance_m, (int, float)) or isinstance(distance_m, bool) or distance_m <= 0:
        raise err_validation("distance_m must be > 0")
    if not isinstance(city, str) or not city:
        raise err_validation("city required")
    if not isinstance(hazard_index, int) or isinstance(hazard_index, bool) or not (0 <= hazard_index <= 10):
        raise err_validation("hazard_index must be 0..10")
    # body FK: creator must exist
    if not isinstance(creator_id, str) or creator_id not in db.athletes:
        raise err_validation("creator_id does not reference an existing athlete")

    # uniqueness: (name, sport_type) unique among all non-DELETED segments;
    # a retired segment keeps its name reserved (PRD 3.5)
    for s in db.segments.values():
        if s["name"] == name and s["sport_type"] == sport_type:
            raise err_unique("segment (name, sport_type) taken")

    seg = init_common({
        "creator_id": creator_id,
        "name": name,
        "sport_type": sport_type,
        "start_lat": start_lat, "start_lng": start_lng,
        "end_lat": end_lat, "end_lng": end_lng,
        "distance_m": distance_m,
        "city": city,
        "hazard_index": hazard_index,
        "status": "DRAFT",
        "effort_count": 0,
    })
    db.segments[seg["id"]] = seg
    return ok_object(segment_view(seg), 201)


@bp.get("/v1/segments/<sid>")
def get_segment(sid):
    require_roles("Athlete", "PlatformAdmin", "Moderator")
    s = db.segments.get(sid)
    if not s:
        raise err_not_found("Segment not found")
    return ok_object(segment_view(s))


@bp.get("/v1/segments")
def list_segments():
    require_roles("Athlete", "PlatformAdmin", "Moderator")
    status_f = request.args.get("status")
    sport_f = request.args.get("sport_type")
    creator_f = request.args.get("creator_id")
    items = list(db.segments.values())
    if status_f:
        items = [s for s in items if s["status"] == status_f]
    if sport_f:
        items = [s for s in items if s["sport_type"] == sport_f]
    if creator_f:
        items = [s for s in items if s["creator_id"] == creator_f]
    items.sort(key=lambda s: s["created_at"])
    limit, offset, _ = parse_pagination(request.args)
    return ok_list([segment_view(s) for s in items], limit, offset)


@bp.post("/v1/segments/<sid>/activate")
def activate_segment(sid):
    user_id, role = require_roles("Athlete", "PlatformAdmin")
    s = db.segments.get(sid)
    if not s:
        raise err_not_found("Segment not found")
    check_self_or_admin(user_id, role, s["creator_id"])
    # state gate
    if s["status"] == "ACTIVE":
        raise err_invalid_state("Segment already ACTIVE")
    if s["status"] == "RETIRED" and int(s.get("effort_count", 0)) != 0:
        raise err_invalid_state("Segment with recorded efforts cannot re-activate")
    # safety
    if s.get("hazard_index", 0) != 0:
        raise err_safety("Hazardous segments cannot be activated")
    # overlap: both endpoints strictly within 50m of another ACTIVE same-sport segment
    for o in db.segments.values():
        if o["id"] == s["id"] or o["status"] != "ACTIVE" or o["sport_type"] != s["sport_type"]:
            continue
        d_start = haversine_m(s["start_lat"], s["start_lng"], o["start_lat"], o["start_lng"])
        d_end = haversine_m(s["end_lat"], s["end_lng"], o["end_lat"], o["end_lng"])
        if d_start < OVERLAP_EPSILON_M and d_end < OVERLAP_EPSILON_M:
            raise err_segment_overlap()
    s["status"] = "ACTIVE"
    touch(s)
    retro_sweep_for_segment(s)
    recompute_heatmap()
    return ok_object(segment_view(s))


@bp.post("/v1/segments/<sid>/retire")
def retire_segment(sid):
    user_id, role = require_roles("Athlete", "PlatformAdmin")
    s = db.segments.get(sid)
    if not s:
        raise err_not_found("Segment not found")
    check_self_or_admin(user_id, role, s["creator_id"])
    if s["status"] == "RETIRED":
        raise err_invalid_state("Segment already RETIRED")
    was_active = s["status"] == "ACTIVE"
    s["status"] = "RETIRED"
    touch(s)
    if was_active:
        affected_activities = set()
        for e in db.efforts.values():
            if e["segment_id"] == sid and e["flag_status"] == "ELIGIBLE":
                e["flag_status"] = "EXCLUDED"
                e["exclusion_reason"] = "SEGMENT_HAZARDOUS"
                touch(e)
                affected_activities.add(e["activity_id"])
        for act_id in affected_activities:
            act = db.activities.get(act_id)
            if act:
                recompute_activity_elevation(act)
                touch(act)
        recompute_heatmap()
    return ok_object(segment_view(s))


@bp.get("/v1/segments/<sid>/efforts")
def list_segment_efforts(sid):
    require_roles("Athlete", "PlatformAdmin", "Moderator")
    if not db.segments.get(sid):
        raise err_not_found("Segment not found")
    flag_f = request.args.get("flag_status")
    items = [e for e in db.efforts.values() if e["segment_id"] == sid]
    if flag_f:
        items = [e for e in items if e["flag_status"] == flag_f]
    items.sort(key=lambda e: e["created_at"])
    limit, offset, _ = parse_pagination(request.args)
    return ok_list([effort_view(e) for e in items], limit, offset)


@bp.get("/v1/segments/<sid>/leaderboard")
def leaderboard(sid):
    user_id, role = require_roles("Athlete", "PlatformAdmin", "Moderator")
    if not db.segments.get(sid):
        raise err_not_found("Segment not found")
    limit, offset, limit_explicit = parse_pagination(request.args)
    if limit_explicit and limit > 10:
        # subscription gating: requester must hold ACTIVE subscription
        ok = False
        if role == "Athlete" and has_active_subscription(user_id):
            ok = True
        if not ok:
            raise err_subscription("Full leaderboard requires an ACTIVE subscription")
    elig = [e for e in db.efforts.values()
            if e["segment_id"] == sid and e["flag_status"] == "ELIGIBLE"]
    elig.sort(key=lambda e: (e["elapsed_time_s"], e["created_at"]))
    recompute_ranks(sid)
    return ok_list([effort_view(e) for e in elig], limit, offset)


# -------------------------------------------------------------- efforts ----

@bp.get("/v1/athletes/<aid>/efforts")
def list_athlete_efforts(aid):
    require_roles("Athlete", "PlatformAdmin", "Moderator")
    if not db.athletes.get(aid):
        raise err_not_found("Athlete not found")
    flag_f = request.args.get("flag_status")
    items = [e for e in db.efforts.values() if e["athlete_id"] == aid]
    if flag_f:
        items = [e for e in items if e["flag_status"] == flag_f]
    items.sort(key=lambda e: e["created_at"])
    limit, offset, _ = parse_pagination(request.args)
    return ok_list([effort_view(e) for e in items], limit, offset)


@bp.get("/v1/efforts")
def list_efforts_flat():
    require_roles("Athlete", "PlatformAdmin", "Moderator")
    act_f = request.args.get("activity_id")
    seg_f = request.args.get("segment_id")
    ath_f = request.args.get("athlete_id")
    flag_f = request.args.get("flag_status")
    items = list(db.efforts.values())
    if act_f:
        items = [e for e in items if e["activity_id"] == act_f]
    if seg_f:
        items = [e for e in items if e["segment_id"] == seg_f]
    if ath_f:
        items = [e for e in items if e["athlete_id"] == ath_f]
    if flag_f:
        items = [e for e in items if e["flag_status"] == flag_f]
    items.sort(key=lambda e: e["created_at"])
    limit, offset, _ = parse_pagination(request.args)
    return ok_list([effort_view(e) for e in items], limit, offset)


@bp.get("/v1/efforts/<eid>")
def get_effort(eid):
    require_roles("Athlete", "PlatformAdmin", "Moderator")
    e = db.efforts.get(eid)
    if not e:
        raise err_not_found("Effort not found")
    return ok_object(effort_view(e))


# ---------------------------------------------------------------- flags ----

@bp.post("/v1/efforts/<eid>/flags")
def create_flag(eid):
    user_id, role = require_roles("Athlete", "PlatformAdmin", "Moderator")
    e = db.efforts.get(eid)
    if not e:
        raise err_not_found("Effort not found")
    body = request.get_json(silent=True) or {}
    reporter_id = body.get("reporter_id")
    reason = body.get("reason")
    note = body.get("note")
    # body FK existence (priority 4)
    if not isinstance(reporter_id, str) or reporter_id not in db.athletes:
        raise err_validation("reporter_id does not reference an existing athlete")
    if reason not in ("IMPOSSIBLE_TIME", "VEHICLE_ASSISTED", "WRONG_CATEGORY"):
        raise err_validation("reason must be IMPOSSIBLE_TIME, VEHICLE_ASSISTED or WRONG_CATEGORY")
    if note is not None and (not isinstance(note, str) or len(note) > 500):
        raise err_validation("note must be at most 500 chars")
    act = db.activities.get(e["activity_id"])
    if not act:
        raise err_not_found("Activity not found")
    # state checks (priority 5)
    if act["status"] != "COMPLETED":
        raise err_invalid_state("Target activity is not COMPLETED")
    if act.get("flag_status") == "CONFIRMED":
        raise err_invalid_state("Target activity flag_status is CONFIRMED")
    # reporter != owner (ERR_FLAG_SELF)
    if reporter_id == act["athlete_id"]:
        raise err_flag_self()
    # no second OPEN flag on the same effort
    for f in db.flags.values():
        if f["effort_id"] == eid and f["status"] == "OPEN":
            raise err_unique("An OPEN flag already exists on this effort")

    flag = init_common({
        "effort_id": eid,
        "reporter_id": reporter_id,
        "reason": reason,
        "note": note,
        "status": "OPEN",
    })
    db.flags[flag["id"]] = flag
    # All ELIGIBLE efforts of the activity -> FLAGGED (community-flagged: no exclusion_reason)
    affected_segments = set()
    for eff in db.efforts.values():
        if eff["activity_id"] == act["id"] and eff["flag_status"] == "ELIGIBLE":
            eff["flag_status"] = "FLAGGED"
            touch(eff)
            affected_segments.add(eff["segment_id"])
    if act["flag_status"] == "NONE":
        act["flag_status"] = "FLAGGED"
    recompute_activity_elevation(act)
    touch(act)
    for sid2 in affected_segments:
        recompute_ranks(sid2)
    recompute_heatmap()
    return ok_object(flag_view(flag), 201)


@bp.get("/v1/efforts/<eid>/flags")
def list_effort_flags(eid):
    require_roles("Athlete", "PlatformAdmin", "Moderator")
    if not db.efforts.get(eid):
        raise err_not_found("Effort not found")
    status_f = request.args.get("status")
    items = [f for f in db.flags.values() if f["effort_id"] == eid]
    if status_f:
        items = [f for f in items if f["status"] == status_f]
    items.sort(key=lambda f: f["created_at"])
    limit, offset, _ = parse_pagination(request.args)
    return ok_list([flag_view(f) for f in items], limit, offset)


@bp.get("/v1/flags")
def list_flags_flat():
    require_roles("Athlete", "PlatformAdmin", "Moderator")
    effort_f = request.args.get("effort_id")
    reporter_f = request.args.get("reporter_id")
    status_f = request.args.get("status")
    items = list(db.flags.values())
    if effort_f:
        items = [f for f in items if f["effort_id"] == effort_f]
    if reporter_f:
        items = [f for f in items if f["reporter_id"] == reporter_f]
    if status_f:
        items = [f for f in items if f["status"] == status_f]
    items.sort(key=lambda f: f["created_at"])
    limit, offset, _ = parse_pagination(request.args)
    return ok_list([flag_view(f) for f in items], limit, offset)


@bp.get("/v1/flags/<fid>")
def get_flag(fid):
    require_roles("Athlete", "PlatformAdmin", "Moderator")
    f = db.flags.get(fid)
    if not f:
        raise err_not_found("Flag not found")
    return ok_object(flag_view(f))


@bp.post("/v1/flags/<fid>/uphold")
def uphold_flag(fid):
    require_roles("Moderator", "PlatformAdmin")
    f = db.flags.get(fid)
    if not f:
        raise err_not_found("Flag not found")
    if f["status"] != "OPEN":
        raise err_invalid_state("Only OPEN flags may be resolved")
    f["status"] = "UPHELD"
    touch(f)
    e = db.efforts.get(f["effort_id"])
    act = db.activities.get(e["activity_id"]) if e else None
    athlete = db.athletes.get(act["athlete_id"]) if act else None
    affected_segments = set()
    if e and e["flag_status"] == "FLAGGED":
        e["flag_status"] = "EXCLUDED"
        e["exclusion_reason"] = "FLAG_UPHELD"
        touch(e)
        affected_segments.add(e["segment_id"])
    if act:
        if act["flag_status"] == "FLAGGED":
            act["flag_status"] = "CONFIRMED"
        recompute_activity_elevation(act)
        touch(act)
    if athlete:
        athlete["safety_score"] = max(0, int(athlete.get("safety_score", 100)) - 10)
        touch(athlete)
        if athlete["safety_score"] < 50:
            apply_auto_hide(athlete)
    for sid2 in affected_segments:
        recompute_ranks(sid2)
    recompute_heatmap()
    return ok_object(flag_view(f))


@bp.post("/v1/flags/<fid>/reject")
def reject_flag(fid):
    require_roles("Moderator", "PlatformAdmin")
    f = db.flags.get(fid)
    if not f:
        raise err_not_found("Flag not found")
    if f["status"] != "OPEN":
        raise err_invalid_state("Only OPEN flags may be resolved")
    f["status"] = "REJECTED"
    touch(f)
    e = db.efforts.get(f["effort_id"])
    act = db.activities.get(e["activity_id"]) if e else None
    if act:
        other_open = [x for x in db.flags.values()
                      if x["status"] == "OPEN" and x["effort_id"] in
                      {ee["id"] for ee in db.efforts.values() if ee["activity_id"] == act["id"]}]
        if not other_open:
            affected_segments = set()
            for eff in db.efforts.values():
                if eff["activity_id"] == act["id"] and eff["flag_status"] == "FLAGGED":
                    eff["flag_status"] = "ELIGIBLE"
                    eff["exclusion_reason"] = None
                    touch(eff)
                    affected_segments.add(eff["segment_id"])
            if act["flag_status"] == "FLAGGED":
                act["flag_status"] = "CLEARED"
            recompute_activity_elevation(act)
            touch(act)
            athlete = db.athletes.get(act["athlete_id"])
            if athlete:
                athlete["safety_score"] = min(100, int(athlete.get("safety_score", 100)) + 5)
                touch(athlete)
            for sid2 in affected_segments:
                recompute_ranks(sid2)
    recompute_heatmap()
    return ok_object(flag_view(f))
