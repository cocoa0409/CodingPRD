"""Serializers: shape resources for public vs owner/privileged reads."""
from db import db


def athlete_view(a):
    return dict(a)


def subscription_view(s):
    return {k: v for k, v in s.items() if not k.startswith("_")}


def zone_view(z):
    return dict(z)


def activity_view(a, viewer_user_id, viewer_role):
    """Non-owner, non-privileged callers see obfuscated route in place of raw."""
    out = {k: v for k, v in a.items() if not k.startswith("_")}
    privileged = viewer_role in ("PlatformAdmin", "Moderator")
    is_owner = viewer_role == "Athlete" and viewer_user_id == a["athlete_id"]
    if not (privileged or is_owner):
        out["start_lat"] = a.get("obfuscated_start_lat")
        out["start_lng"] = a.get("obfuscated_start_lng")
        out["end_lat"] = a.get("obfuscated_end_lat")
        out["end_lng"] = a.get("obfuscated_end_lng")
        out["track_points"] = a.get("obfuscated_track") or []
    return out


def segment_view(s):
    return dict(s)


def effort_view(e):
    return dict(e)


def flag_view(f):
    return dict(f)


def club_view(c):
    return dict(c)


def membership_view(m):
    return dict(m)


def challenge_view(ch):
    return dict(ch)


def participation_view(p):
    return {k: v for k, v in p.items() if not k.startswith("_")}


def event_view(ev):
    return dict(ev)


def rsvp_view(r):
    return dict(r)


def contact_view(c):
    return dict(c)


def beacon_view(b):
    return dict(b)


def heatmap_cell_view(c):
    return dict(c)


def route_plan_view(rp):
    return dict(rp)
