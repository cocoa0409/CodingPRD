"""Safety contacts, beacon sessions, heatmap, route plans, clock."""
from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta
from flask import Blueprint, request

from db import db
from errors import (err_validation, err_not_found, err_unique, err_forbidden,
                    err_invalid_state, err_safety, err_subscription,
                    err_free_tier_cap)
from middleware import require_roles, check_self_or_admin
from response import (ok_object, ok_list, init_common, touch, parse_pagination,
                      parse_iso_dt, parse_iso_date)
from serializers import contact_view, beacon_view, heatmap_cell_view, route_plan_view
from services import (has_active_subscription, logical_now_iso_ms, logical_now_dt,
                      recompute_heatmap, MIN_CELL_COUNT, FREE_WEEKLY_ROUTE_CAP,
                      PLAN_LOAD_DIVISOR, PLAN_ACTIVITY_DIVISOR, CAP_RATIO, CAP_BONUS)

bp = Blueprint("safety", __name__)


def _get_athlete_or_404(aid):
    a = db.athletes.get(aid)
    if not a:
        raise err_not_found("Athlete not found")
    return a


# -------------------------------------------------------- safety contacts ----

@bp.post("/v1/athletes/<aid>/safety_contacts")
def create_contact(aid):
    user_id, role = require_roles("Athlete", "PlatformAdmin")
    _get_athlete_or_404(aid)
    check_self_or_admin(user_id, role, aid)
    body = request.get_json(silent=True) or {}
    email = body.get("contact_email")
    label = body.get("label")
    if not isinstance(email, str) or not email:
        raise err_validation("contact_email required")
    if not isinstance(label, str) or not label or len(label) > 40:
        raise err_validation("label must be 1..40 chars")
    for c in db.safety_contacts.values():
        if c["athlete_id"] == aid and c["contact_email"] == email:
            raise err_unique("contact_email duplicate for athlete")
    c = init_common({
        "athlete_id": aid,
        "contact_email": email,
        "label": label,
    })
    db.safety_contacts[c["id"]] = c
    return ok_object(contact_view(c), 201)


@bp.get("/v1/athletes/<aid>/safety_contacts")
def list_contacts(aid):
    require_roles("Athlete", "PlatformAdmin")
    _get_athlete_or_404(aid)
    items = [c for c in db.safety_contacts.values() if c["athlete_id"] == aid]
    items.sort(key=lambda c: c["created_at"])
    limit, offset, _ = parse_pagination(request.args)
    return ok_list([contact_view(c) for c in items], limit, offset)


@bp.get("/v1/safety_contacts/<cid>")
def get_contact(cid):
    require_roles("Athlete", "PlatformAdmin")
    c = db.safety_contacts.get(cid)
    if not c:
        raise err_not_found("Safety contact not found")
    return ok_object(contact_view(c))


# -------------------------------------------------------- beacon sessions ----

@bp.post("/v1/athletes/<aid>/beacon_sessions")
def create_beacon(aid):
    user_id, role = require_roles("Athlete", "PlatformAdmin")
    _get_athlete_or_404(aid)
    check_self_or_admin(user_id, role, aid)
    # safety: needs >= 1 safety contact (safety rules precede subscription
    # gating in the PRD 2.5 validation priority order)
    has_contact = any(c["athlete_id"] == aid for c in db.safety_contacts.values())
    if not has_contact:
        raise err_safety("Beacon requires at least one safety contact")
    # subscription gate
    if not has_active_subscription(aid):
        raise err_subscription("Beacon requires an ACTIVE subscription")
    # one LIVE session per athlete
    for b in db.beacon_sessions.values():
        if b["athlete_id"] == aid and b["status"] == "LIVE":
            raise err_unique("One LIVE beacon session per athlete")
    b = init_common({
        "athlete_id": aid,
        "started_at": logical_now_iso_ms(),
        "last_location": None,
        "status": "LIVE",
    })
    db.beacon_sessions[b["id"]] = b
    return ok_object(beacon_view(b), 201)


@bp.get("/v1/athletes/<aid>/beacon_sessions")
def list_beacons(aid):
    require_roles("Athlete", "PlatformAdmin")
    _get_athlete_or_404(aid)
    status_f = request.args.get("status")
    items = [b for b in db.beacon_sessions.values() if b["athlete_id"] == aid]
    if status_f:
        items = [b for b in items if b["status"] == status_f]
    items.sort(key=lambda b: b["created_at"])
    limit, offset, _ = parse_pagination(request.args)
    return ok_list([beacon_view(b) for b in items], limit, offset)


@bp.get("/v1/beacon_sessions/<bid>")
def get_beacon(bid):
    require_roles("Athlete", "PlatformAdmin")
    b = db.beacon_sessions.get(bid)
    if not b:
        raise err_not_found("Beacon session not found")
    return ok_object(beacon_view(b))


def _get_beacon_scoped(aid, bid):
    _get_athlete_or_404(aid)
    b = db.beacon_sessions.get(bid)
    if not b or b["athlete_id"] != aid:
        raise err_not_found("Beacon session not found")
    return b


@bp.post("/v1/athletes/<aid>/beacon_sessions/<bid>/ping")
def ping_beacon(aid, bid):
    user_id, role = require_roles("Athlete", "PlatformAdmin")
    b = _get_beacon_scoped(aid, bid)
    check_self_or_admin(user_id, role, aid)
    body = request.get_json(silent=True) or {}
    lat = body.get("lat"); lng = body.get("lng")
    if not isinstance(lat, (int, float)) or isinstance(lat, bool):
        raise err_validation("lat required")
    if not isinstance(lng, (int, float)) or isinstance(lng, bool):
        raise err_validation("lng required")
    if b["status"] != "LIVE":
        raise err_invalid_state("Only LIVE sessions may be pinged")
    b["last_location"] = {"lat": lat, "lng": lng}
    touch(b)
    return ok_object(beacon_view(b))


@bp.post("/v1/athletes/<aid>/beacon_sessions/<bid>/stop")
def stop_beacon(aid, bid):
    user_id, role = require_roles("Athlete", "PlatformAdmin")
    b = _get_beacon_scoped(aid, bid)
    check_self_or_admin(user_id, role, aid)
    if b["status"] != "LIVE":
        raise err_invalid_state("Only LIVE sessions may be stopped")
    b["status"] = "ENDED"
    touch(b)
    return ok_object(beacon_view(b))


# ---------------------------------------------------------------- heatmap ----

@bp.get("/v1/heatmap")
def get_heatmap():
    require_roles("Athlete", "PlatformAdmin", "Moderator")
    recompute_heatmap()
    city_f = request.args.get("city")
    sport_f = request.args.get("sport_type")
    cells = [c for c in db.heatmap_cells.values() if c["contribution_count"] >= MIN_CELL_COUNT] \
        if hasattr(db, "heatmap_cells") else []
    if city_f:
        cells = [c for c in cells if c["city"] == city_f]
    if sport_f:
        cells = [c for c in cells if c["sport_type"] == sport_f]
    cells.sort(key=lambda c: c["created_at"])
    limit, offset, _ = parse_pagination(request.args)
    return ok_list([heatmap_cell_view(c) for c in cells], limit, offset)


# ------------------------------------------------------------- route plans ----

@bp.post("/v1/athletes/<aid>/route_plans")
def create_route_plan(aid):
    user_id, role = require_roles("Athlete", "PlatformAdmin")
    _get_athlete_or_404(aid)
    check_self_or_admin(user_id, role, aid)
    body = request.get_json(silent=True) or {}
    name = body.get("name")
    waypoints = body.get("waypoints")
    distance_m = body.get("distance_m")
    week_start = body.get("week_start")
    if not isinstance(name, str) or not (1 <= len(name) <= 80):
        raise err_validation("name must be 1..80 chars")
    if not isinstance(waypoints, list) or not (2 <= len(waypoints) <= 50):
        raise err_validation("waypoints must contain 2..50 points")
    for p in waypoints:
        if not isinstance(p, dict) or not isinstance(p.get("lat"), (int, float)) \
                or not isinstance(p.get("lng"), (int, float)):
            raise err_validation("waypoints entries need lat/lng")
    if not isinstance(distance_m, (int, float)) or isinstance(distance_m, bool) or distance_m <= 0:
        raise err_validation("distance_m must be > 0")
    if parse_iso_date(week_start) is None:
        raise err_validation("week_start must be YYYY-MM-DD")
    # free-tier weekly cap evaluated BEFORE the generic subscription gate
    existing = sum(1 for rp in db.route_plans.values()
                   if rp["athlete_id"] == aid and rp["week_start"] == week_start)
    if existing >= FREE_WEEKLY_ROUTE_CAP and not has_active_subscription(aid):
        raise err_free_tier_cap()
    # route_load_score
    ws = parse_iso_date(week_start)
    recent_distance = 0.0
    for act in db.activities.values():
        if act["athlete_id"] != aid or act["status"] != "COMPLETED":
            continue
        ad = parse_iso_dt(act["started_at"])
        if ad is None:
            continue
        d = ad.date()
        if (ws - timedelta(days=28)) <= d <= ws:
            recent_distance += act["distance_m"]
    raw = distance_m / PLAN_LOAD_DIVISOR + recent_distance / PLAN_ACTIVITY_DIVISOR
    if recent_distance > 0 and distance_m > recent_distance * CAP_RATIO:
        raw += CAP_BONUS
    score = float(Decimal(str(raw)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
    rp = init_common({
        "athlete_id": aid,
        "name": name,
        "waypoints": waypoints,
        "distance_m": distance_m,
        "week_start": week_start,
        "estimated_load_score": score,
    })
    db.route_plans[rp["id"]] = rp
    return ok_object(route_plan_view(rp), 201)


@bp.get("/v1/athletes/<aid>/route_plans")
def list_route_plans(aid):
    require_roles("Athlete", "PlatformAdmin")
    _get_athlete_or_404(aid)
    ws_f = request.args.get("week_start")
    items = [r for r in db.route_plans.values() if r["athlete_id"] == aid]
    if ws_f:
        items = [r for r in items if r["week_start"] == ws_f]
    items.sort(key=lambda r: r["created_at"])
    limit, offset, _ = parse_pagination(request.args)
    return ok_list([route_plan_view(r) for r in items], limit, offset)


@bp.get("/v1/route_plans/<rid>")
def get_route_plan(rid):
    require_roles("Athlete", "PlatformAdmin")
    rp = db.route_plans.get(rid)
    if not rp:
        raise err_not_found("Route plan not found")
    return ok_object(route_plan_view(rp))


# ------------------------------------------------------------------ clock ----

@bp.post("/v1/_clock/set_current_utc")
def set_clock():
    require_roles("PlatformAdmin")
    body = request.get_json(silent=True) or {}
    to = body.get("to_iso8601")
    dt = parse_iso_dt(to)
    if dt is None:
        raise err_validation("to_iso8601 must be ISO8601 UTC")
    db.current_utc_iso = to if isinstance(to, str) else dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return ok_object({"current_utc": db.current_utc_iso})
