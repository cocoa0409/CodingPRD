"""Core business services: geometry, obfuscation, matching, integrity checks,
rank snapshots, heatmap, challenge progress, cascades, lazy transitions."""
import math
from datetime import timedelta, timezone, date

from db import db
from response import now_iso_ms, touch, parse_iso_dt, parse_iso_date

EARTH_RADIUS_M = 6371000
OVERLAP_EPSILON_M = 50
EVENT_WINDOW_S = 3600
MIN_CELL_COUNT = 3
FREE_WEEKLY_ROUTE_CAP = 3
PLAN_LOAD_DIVISOR = 1000
PLAN_ACTIVITY_DIVISOR = 2000
CAP_RATIO = 1.5
CAP_BONUS = 25

MAX_SPEED = {"RIDE": 80, "RUN": 30, "SWIM": 10, "EBikeRide": 45,
             "VIRTUAL_RIDE": 100, "VIRTUAL_RUN": 100}
ASSIST_FACTOR = {"RIDE": 0.8, "RUN": 0.8, "SWIM": 0.8, "EBikeRide": 0.7,
                 "VIRTUAL_RIDE": 0.9, "VIRTUAL_RUN": 0.9}

SPORT_TYPES = {"RIDE", "RUN", "VIRTUAL_RIDE", "VIRTUAL_RUN", "SWIM", "EBikeRide"}
SEGMENT_SPORTS = {"RIDE", "RUN", "SWIM"}


def haversine_m(lat1, lng1, lat2, lng2):
    r = EARTH_RADIUS_M
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def logical_now_dt():
    dt = parse_iso_dt(db.current_utc_iso)
    return dt


def logical_now_iso_ms():
    dt = logical_now_dt()
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def logical_today():
    return logical_now_dt().date()


def effective_category(activity):
    return activity.get("corrected_sport_type") or activity.get("sport_type")


def active_zones_of(athlete_id):
    return [z for z in db.privacy_zones.values()
            if z["athlete_id"] == athlete_id and z["status"] == "ACTIVE"]


def recompute_obfuscation(activity):
    """Route obfuscation (calculation: route_obfuscation)."""
    zones = active_zones_of(activity["athlete_id"])
    surviving = []
    for p in activity.get("track_points") or []:
        inside = any(haversine_m(p["lat"], p["lng"], z["center_lat"], z["center_lng"]) <= z["radius_m"]
                     for z in zones)
        if not inside:
            surviving.append(p)
    activity["obfuscated_track"] = surviving
    if surviving:
        activity["obfuscated_start_lat"] = surviving[0]["lat"]
        activity["obfuscated_start_lng"] = surviving[0]["lng"]
        activity["obfuscated_end_lat"] = surviving[-1]["lat"]
        activity["obfuscated_end_lng"] = surviving[-1]["lng"]
    else:
        activity["obfuscated_start_lat"] = None
        activity["obfuscated_start_lng"] = None
        activity["obfuscated_end_lat"] = None
        activity["obfuscated_end_lng"] = None


def recompute_activity_elevation(activity):
    """elevation_gain_m = sum of ELIGIBLE efforts' elevation_gain_m."""
    total = 0
    for e in db.efforts.values():
        if e["activity_id"] == activity["id"] and e["flag_status"] == "ELIGIBLE":
            total += e.get("elevation_gain_m") or 0
    activity["elevation_gain_m"] = total


def recompute_ranks(segment_id):
    """1-based rank among ELIGIBLE efforts, elapsed ASC then created_at ASC."""
    elig = [e for e in db.efforts.values()
            if e["segment_id"] == segment_id and e["flag_status"] == "ELIGIBLE"]
    elig.sort(key=lambda e: (e["elapsed_time_s"], e["created_at"]))
    for i, e in enumerate(elig):
        e["rank_snapshot"] = i + 1


def category_matches_segment(cat, seg_sport):
    """Category matching asymmetries: RIDE segments also match EBikeRide;
    VIRTUAL_RIDE -> RIDE, VIRTUAL_RUN -> RUN; SWIM only SWIM."""
    if seg_sport == "RIDE":
        return cat in ("RIDE", "EBikeRide", "VIRTUAL_RIDE")
    if seg_sport == "RUN":
        return cat in ("RUN", "VIRTUAL_RUN")
    if seg_sport == "SWIM":
        return cat == "SWIM"
    return False


def speed_and_vehicle_check(effort, activity):
    """Run the speed/vehicle integrity check over one effort."""
    from decimal import Decimal, ROUND_HALF_UP
    seg = db.segments.get(effort["segment_id"])
    cat = effective_category(activity)
    elapsed = effort["elapsed_time_s"]
    dist = effort["distance_m"]
    # avg_speed_kmh rounded half-up to 2dp
    avg = Decimal(str(dist)) / Decimal(str(elapsed)) * Decimal("3.6")
    effort["avg_speed_kmh"] = float(avg.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

    max_speed = MAX_SPEED.get(cat, 80)
    assist = ASSIST_FACTOR.get(cat, 0.8)
    expected_min = (seg["distance_m"] * 3.6 / max_speed) * assist
    if elapsed < expected_min:
        effort["flag_status"] = "FLAGGED"
        effort["exclusion_reason"] = "SPEED_IMPOSSIBLE"
        if activity["flag_status"] == "NONE":
            activity["flag_status"] = "FLAGGED"
        return
    if cat == "EBikeRide" and seg["sport_type"] == "RIDE":
        effort["flag_status"] = "FLAGGED"
        effort["exclusion_reason"] = "VEHICLE_ASSISTED"
        if activity["flag_status"] == "NONE":
            activity["flag_status"] = "FLAGGED"
        return
    effort["flag_status"] = "ELIGIBLE"
    effort["exclusion_reason"] = None


def create_effort(activity, segment):
    """Author one SegmentEffort per segment_matching rules."""
    from response import init_common
    hint = None
    for h in activity.get("effort_hints") or []:
        if h.get("segment_id") == segment["id"]:
            hint = h
            break
    if hint is not None:
        elapsed = hint["elapsed_time_s"]
        elev = hint.get("elevation_gain_m", 0)
    else:
        elapsed = activity["duration_s"]
        elev = 0
    effort = init_common({
        "activity_id": activity["id"],
        "segment_id": segment["id"],
        "athlete_id": activity["athlete_id"],
        "elapsed_time_s": elapsed,
        "distance_m": segment["distance_m"],
        "elevation_gain_m": elev,
        "avg_speed_kmh": 0.0,
        "flag_status": "ELIGIBLE",
        "exclusion_reason": None,
        "rank_snapshot": None,
    })
    db.efforts[effort["id"]] = effort
    segment["effort_count"] = int(segment.get("effort_count", 0)) + 1
    speed_and_vehicle_check(effort, activity)
    recompute_activity_elevation(activity)
    return effort


def match_segment_for_activity(segment, activity):
    """Should this activity get an effort on this segment?"""
    if activity["status"] != "COMPLETED" or activity.get("auto_hidden"):
        return False
    if segment["status"] != "ACTIVE" or segment.get("hazard_index", 0) != 0:
        return False
    return category_matches_segment(effective_category(activity), segment["sport_type"])


def match_sweep_for_activity(activity):
    """Upload sweep: match all qualifying ACTIVE segments."""
    for seg in db.segments.values():
        if match_segment_for_activity(seg, activity):
            create_effort(activity, seg)
    for seg in db.segments.values():
        recompute_ranks(seg["id"])


def retro_sweep_for_segment(segment):
    """Retroactive sweep on activation."""
    for act in db.activities.values():
        if match_segment_for_activity(segment, act):
            create_effort(act, segment)
    recompute_ranks(segment["id"])


# ---------------------------------------------------------------- heatmap ----

def activity_qualifies_heatmap(activity):
    """COMPLETED, not auto-hidden, flag_status NONE/CLEARED, sport RIDE/RUN,
    owner not opted out."""
    if activity["status"] != "COMPLETED":
        return False
    if activity.get("auto_hidden"):
        return False
    if activity.get("flag_status") not in ("NONE", "CLEARED"):
        return False
    if activity.get("sport_type") not in ("RIDE", "RUN"):
        return False
    owner = db.athletes.get(activity["athlete_id"])
    if not owner or owner.get("heatmap_opt_out"):
        return False
    return True


def _cell_for(city, sport_type):
    from response import init_common
    key = (city, sport_type)
    for c in _heatmap_cells().values():
        if (c["city"], c["sport_type"]) == key:
            return c
    cell = init_common({
        "city": city,
        "sport_type": sport_type,
        "contribution_count": 0,
    })
    _heatmap_cells()[cell["id"]] = cell
    return cell


def _heatmap_cells():
    if not hasattr(db, "heatmap_cells"):
        db.heatmap_cells = {}
    return db.heatmap_cells


def heatmap_city_of(activity):
    """City from any matched segment of the activity; UNMAPPED default."""
    for e in db.efforts.values():
        if e["activity_id"] == activity["id"]:
            seg = db.segments.get(e["segment_id"])
            if seg:
                return seg["city"]
    return "UNMAPPED"


def recompute_heatmap():
    """Recompute all cell counts exactly from scratch."""
    cells = _heatmap_cells()
    for c in cells.values():
        c["contribution_count"] = 0
    for act in db.activities.values():
        if activity_qualifies_heatmap(act):
            city = heatmap_city_of(act)
            cell = _cell_for(city, act["sport_type"])
            cell["contribution_count"] += 1


# ------------------------------------------------------- challenge progress --

def challenge_progress_for_activity(activity):
    """Accumulate progress on the owner's JOINED participations."""
    if activity["status"] != "COMPLETED" or activity.get("auto_hidden"):
        return
    if activity.get("flag_status") not in ("NONE", "CLEARED"):
        return
    act_date = parse_iso_dt(activity["started_at"])
    if act_date is None:
        return
    act_date = act_date.date()
    for part in db.participations.values():
        if part["athlete_id"] != activity["athlete_id"] or part["status"] != "JOINED":
            continue
        ch = db.challenges.get(part["challenge_id"])
        if not ch or ch["status"] != "ACTIVE":
            continue
        sd = parse_iso_date(ch["start_date"]); ed = parse_iso_date(ch["end_date"])
        if not sd or not ed or not (sd <= act_date <= ed):
            continue
        key = "_contributed_activity_ids"
        contributed = part.setdefault(key, [])
        if activity["id"] in contributed:
            continue
        contributed.append(activity["id"])
        # Live accumulation (PRD 3.7): the completing activity contributes
        # because the participation is JOINED at completion time. Recompute
        # over the late-join baseline set plus every live-contributed id.
        _recompute_participation_progress(
            part, ch,
            after_instant=parse_iso_dt(part["joined_at"]),
            extra_ids=set(contributed),
        )


def _participating_activities(part, ch, after_instant=None, extra_ids=None):
    """Qualifying activities of the athlete within window; each at most once."""
    sd = parse_iso_date(ch["start_date"]); ed = parse_iso_date(ch["end_date"])
    extra_ids = extra_ids or set()
    out = []
    for act in db.activities.values():
        if act["athlete_id"] != part["athlete_id"]:
            continue
        if act["status"] != "COMPLETED" or act.get("auto_hidden"):
            continue
        if act.get("flag_status") not in ("NONE", "CLEARED"):
            continue
        ad = parse_iso_dt(act["started_at"])
        if ad is None or not (sd <= ad.date() <= ed):
            continue
        if after_instant is not None and act["id"] not in extra_ids:
            comp = act.get("_completed_at_dt")
            if comp is None or comp <= after_instant:
                continue
        out.append(act)
    return out


def _recompute_participation_progress(part, ch, after_instant=None, extra_ids=None):
    acts = _participating_activities(part, ch, after_instant=after_instant, extra_ids=extra_ids)
    if ch["goal_type"] == "DISTANCE_M":
        val = sum(a["distance_m"] for a in acts)
    elif ch["goal_type"] == "ELEVATION_M":
        val = sum(a.get("elevation_gain_m") or 0 for a in acts)
    else:  # ACTIVE_DAYS
        val = len({parse_iso_dt(a["started_at"]).date() for a in acts})
    part["progress_value"] = val
    if part["status"] == "JOINED" and val >= ch["goal_target"]:
        part["status"] = "COMPLETED"
        touch(part)


def retroactive_join_progress(part, ch):
    """Late-join baseline: count only activities completed strictly after joined_at."""
    joined_dt = parse_iso_dt(part["joined_at"])
    contributed = []
    for act in _participating_activities(part, ch, after_instant=joined_dt):
        contributed.append(act["id"])
    part["_contributed_activity_ids"] = contributed
    _recompute_participation_progress(part, ch, after_instant=joined_dt)


# ------------------------------------------------------------ lazy flips ----

def lazy_lapse_subscription(sub):
    if sub["status"] == "ACTIVE":
        exp = parse_iso_dt(sub["expires_at"])
        if exp is not None and logical_now_dt() >= exp:
            sub["status"] = "LAPSED"
            touch(sub)


def lazy_close_challenge(ch):
    if ch["status"] == "ACTIVE":
        ed = parse_iso_date(ch["end_date"])
        if ed is not None and logical_today() > ed:
            ch["status"] = "CLOSED"
            touch(ch)


def lazy_complete_event(ev):
    if ev["status"] == "PUBLISHED":
        sched = parse_iso_dt(ev["scheduled_at"])
        if sched is not None and logical_now_dt() > sched:
            ev["status"] = "COMPLETED"
            touch(ev)


def has_active_subscription(athlete_id):
    for s in db.subscriptions.values():
        if s["athlete_id"] == athlete_id:
            lazy_lapse_subscription(s)
            if s["status"] == "ACTIVE":
                return True
    return False


# -------------------------------------------------------------- cascades ----

def archive_club_cascade(club):
    if club["status"] == "ARCHIVED":
        return
    club["status"] = "ARCHIVED"
    touch(club)
    for m in db.memberships.values():
        if m["club_id"] == club["id"] and m["status"] in ("PENDING", "ACTIVE"):
            m["status"] = "REMOVED"
            touch(m)
    for ch in db.challenges.values():
        if ch["club_id"] == club["id"] and ch["status"] in ("DRAFT", "ACTIVE"):
            ch["status"] = "CANCELLED"
            touch(ch)
            for p in db.participations.values():
                if p["challenge_id"] == ch["id"] and p["status"] == "JOINED":
                    p["status"] = "WITHDRAWN"
                    touch(p)
    for ev in db.events.values():
        if ev["club_id"] == club["id"] and ev["status"] == "PUBLISHED":
            ev["status"] = "CANCELLED"
            touch(ev)


def membership_exit_cascade(club_id, athlete_id):
    """Withdrawal cascade for REMOVED/LEFT: participations + RSVPs."""
    for p in db.participations.values():
        if p["athlete_id"] != athlete_id or p["status"] != "JOINED":
            continue
        ch = db.challenges.get(p["challenge_id"])
        if ch and ch["club_id"] == club_id:
            p["status"] = "WITHDRAWN"
            touch(p)
    for r in db.rsvps.values():
        if r["athlete_id"] != athlete_id or r["status"] != "GOING":
            continue
        ev = db.events.get(r["event_id"])
        if ev and ev["club_id"] == club_id:
            r["status"] = "DECLINED"
            touch(r)
            ev["rsvp_count"] = max(0, int(ev.get("rsvp_count", 0)) - 1)
            touch(ev)


def delete_athlete_cascade(athlete):
    """Full erasure cascade per state machine."""
    aid = athlete["id"]
    athlete["status"] = "DELETED"
    athlete["email"] = f"deleted-{aid}@erased.invalid"
    athlete["display_name"] = "Deleted Athlete"
    touch(athlete)

    # Efforts: exclude all (exclusion_reason unchanged-if-set else FLAG_UPHELD)
    affected_segments = set()
    for e in db.efforts.values():
        if e["athlete_id"] == aid and e["flag_status"] != "EXCLUDED":
            e["flag_status"] = "EXCLUDED"
            if not e.get("exclusion_reason"):
                e["exclusion_reason"] = "FLAG_UPHELD"
            touch(e)
            affected_segments.add(e["segment_id"])
    # Activities: COMPLETED -> REJECTED
    for act in db.activities.values():
        if act["athlete_id"] == aid and act["status"] == "COMPLETED":
            act["status"] = "REJECTED"
            touch(act)
    # OPEN flags reported by athlete -> REJECTED
    for f in db.flags.values():
        if f["reporter_id"] == aid and f["status"] == "OPEN":
            f["status"] = "REJECTED"
            touch(f)
    # Memberships ACTIVE -> LEFT
    for m in db.memberships.values():
        if m["athlete_id"] == aid and m["status"] == "ACTIVE":
            m["status"] = "LEFT"
            touch(m)
    # JOINED participations -> WITHDRAWN
    for p in db.participations.values():
        if p["athlete_id"] == aid and p["status"] == "JOINED":
            p["status"] = "WITHDRAWN"
            touch(p)
    # GOING RSVPs -> DECLINED, decrement event counts
    for r in db.rsvps.values():
        if r["athlete_id"] == aid and r["status"] == "GOING":
            r["status"] = "DECLINED"
            touch(r)
            ev = db.events.get(r["event_id"])
            if ev:
                ev["rsvp_count"] = max(0, int(ev.get("rsvp_count", 0)) - 1)
                touch(ev)
    # LIVE beacons -> ENDED
    for b in db.beacon_sessions.values():
        if b["athlete_id"] == aid and b["status"] == "LIVE":
            b["status"] = "ENDED"
            touch(b)
    # Owned clubs archived
    for c in db.clubs.values():
        if c["owner_id"] == aid and c["status"] == "ACTIVE":
            archive_club_cascade(c)
    for sid in affected_segments:
        recompute_ranks(sid)
    recompute_heatmap()


def apply_auto_hide(athlete):
    """When safety_score < 50: hide every COMPLETED activity."""
    for act in db.activities.values():
        if act["athlete_id"] == athlete["id"] and act["status"] == "COMPLETED":
            if not act.get("auto_hidden"):
                act["auto_hidden"] = True
                touch(act)
    recompute_heatmap()
