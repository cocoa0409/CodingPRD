"""Athlete routes: register, get, export, delete."""
from flask import Blueprint, request

from db import db
from errors import (err_validation, err_not_found, err_unique, err_forbidden)
from middleware import get_auth, require_roles, check_self_or_admin
from response import ok_object, init_common, touch
from serializers import (athlete_view, activity_view, effort_view, segment_view,
                         membership_view, participation_view, rsvp_view, zone_view,
                         contact_view, subscription_view)
from services import lazy_lapse_subscription, delete_athlete_cascade

bp = Blueprint("athletes", __name__)


def _get_athlete_or_404(aid):
    a = db.athletes.get(aid)
    if not a:
        raise err_not_found("Athlete not found")
    return a


def _validate_lat_lng(lat, lng):
    if not isinstance(lat, (int, float)) or isinstance(lat, bool) or not (-90 <= lat <= 90):
        raise err_validation("home_lat must be -90..90")
    if not isinstance(lng, (int, float)) or isinstance(lng, bool) or not (-180 <= lng <= 180):
        raise err_validation("home_lng must be -180..180")


@bp.post("/v1/athletes")
def create_athlete():
    require_roles("Athlete", "PlatformAdmin")
    body = request.get_json(silent=True) or {}
    email = body.get("email")
    display_name = body.get("display_name")
    home_lat = body.get("home_lat")
    home_lng = body.get("home_lng")
    tier = body.get("tier", "FREE")
    heatmap_opt_out = body.get("heatmap_opt_out", False)

    if not isinstance(email, str) or not email:
        raise err_validation("email is required")
    email = email.lower()
    if not isinstance(display_name, str) or not display_name or len(display_name) > 60:
        raise err_validation("display_name must be 1..60 chars")
    _validate_lat_lng(home_lat, home_lng)
    if tier not in ("FREE", "SUMMIT"):
        raise err_validation("tier must be FREE or SUMMIT")
    if not isinstance(heatmap_opt_out, bool):
        raise err_validation("heatmap_opt_out must be boolean")

    # uniqueness: email globally unique
    for a in db.athletes.values():
        if a["email"] == email:
            raise err_unique("email taken")

    athlete = init_common({
        "email": email,
        "display_name": display_name,
        "home_lat": home_lat,
        "home_lng": home_lng,
        "tier": tier,
        "status": "ACTIVE",
        "heatmap_opt_out": heatmap_opt_out,
        "safety_score": 100,
    })
    db.athletes[athlete["id"]] = athlete
    return ok_object(athlete_view(athlete), 201)


@bp.get("/v1/athletes/<aid>")
def get_athlete(aid):
    require_roles("Athlete", "PlatformAdmin", "Moderator")
    a = _get_athlete_or_404(aid)
    # Lazy subscription lapse evaluation for this athlete's subscriptions
    for s in db.subscriptions.values():
        if s["athlete_id"] == aid:
            lazy_lapse_subscription(s)
    return ok_object(athlete_view(a))


@bp.get("/v1/athletes/<aid>/export")
def export_athlete(aid):
    user_id, role = require_roles("Athlete", "PlatformAdmin")
    a = _get_athlete_or_404(aid)
    check_self_or_admin(user_id, role, aid)
    activities = [dict(x) for x in db.activities.values() if x["athlete_id"] == aid]
    for x in activities:
        x.pop("_completed_at_dt", None)
    efforts = [dict(e) for e in db.efforts.values() if e["athlete_id"] == aid]
    segments = [segment_view(s) for s in db.segments.values() if s["creator_id"] == aid]
    memberships = [membership_view(m) for m in db.memberships.values() if m["athlete_id"] == aid]
    participations = [participation_view(p) for p in db.participations.values() if p["athlete_id"] == aid]
    rsvps = [rsvp_view(r) for r in db.rsvps.values() if r["athlete_id"] == aid]
    zones = [zone_view(z) for z in db.privacy_zones.values() if z["athlete_id"] == aid]
    contacts = [contact_view(c) for c in db.safety_contacts.values() if c["athlete_id"] == aid]
    subs = [subscription_view(s) for s in db.subscriptions.values() if s["athlete_id"] == aid]
    return ok_object({
        "profile": athlete_view(a),
        "activities": activities,
        "efforts": efforts,
        "segments": segments,
        "memberships": memberships,
        "participations": participations,
        "rsvps": rsvps,
        "privacy_zones": zones,
        "safety_contacts": contacts,
        "subscriptions": subs,
    })


@bp.delete("/v1/athletes/<aid>")
def delete_athlete(aid):
    user_id, role = require_roles("Athlete")
    a = _get_athlete_or_404(aid)
    if user_id != aid:
        raise err_forbidden("Self-deletion only")
    delete_athlete_cascade(a)
    return ok_object(athlete_view(a))
