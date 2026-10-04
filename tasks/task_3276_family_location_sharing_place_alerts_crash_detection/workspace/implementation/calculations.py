"""Calculation rules from SCAFFOLD §1.3."""
import math
from decimal import Decimal, ROUND_HALF_UP

EARTH_RADIUS_M = 6371000

TIER_UNITS = {"FREE": 0, "PLUS": 2, "PROTECT": 4}
TIER_IDENTITY_CREDITS = {"FREE": 0, "PLUS": 0, "PROTECT": 1}
TIER_RETENTION_DAYS = {"FREE": 7, "PLUS": 30, "PROTECT": 60}
TIER_FLOOR = {"FREE": 60, "PLUS": 30, "PROTECT": 15}
# Tier speed-event threshold (m/s): average speed of a consecutive pair
# must exceed this to count as a speed event.
TIER_SPEED_EVENT_THRESHOLD = {"FREE": 35.0, "PLUS": 35.0, "PROTECT": 35.0}

BASE_SECONDS = {"HIGH": 15, "BALANCED": 60, "SAVER": 300}
MOTION_MULT = {"DRIVING": 0.25, "WALKING": 0.5, "STILL": 2.0, "UNKNOWN": 1.0}

MINOR_FLOOR = 8.0
MAJOR_FLOOR = 16.0
SEVERE_FLOOR = 24.0

MILE_METRES = 1609


def round_half_up(value):
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def haversine_m(lat1, lng1, lat2, lng2):
    """Distance in metres, computed to 0.1 m precision (not rounded)."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2
    a = min(1.0, max(0.0, a))
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def geofence_inside(place, fix):
    """(inside: bool, accuracy_rejected: bool). Accuracy above the place's
    floor is REJECTED_ACCURACY for that place's purposes only."""
    if fix["accuracy_m"] > place["accuracy_floor_m"]:
        return False, True
    effective = place["radius_m"] + min(fix["accuracy_m"], place["accuracy_floor_m"])
    dist = haversine_m(fix["lat"], fix["lng"], place["center_lat"], place["center_lng"])
    return dist <= effective, False


def effective_sample_interval(profile, motion_context, battery_pct, tier):
    """Pinned order: raw = base * motion * battery; interval = max(raw, tier
    floor); round_half_up once; clamp [15, 900]."""
    base = BASE_SECONDS.get(profile, 60)
    motion = MOTION_MULT.get(motion_context, 1.0)
    if battery_pct <= 15:
        batt = 2.0
    elif battery_pct <= 30:
        batt = 1.5
    else:
        batt = 1.0
    raw = base * motion * batt
    interval = max(raw, TIER_FLOOR.get(tier, 60))
    interval = round_half_up(interval)
    return max(15, min(900, interval))


def crash_severity(delta_v):
    """None when below threshold, else MINOR | MAJOR | SEVERE (2dp compare)."""
    dv = Decimal(str(delta_v)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if dv < Decimal("8.00"):
        return None
    if dv < Decimal("16.00"):
        return "MINOR"
    if dv < Decimal("24.00"):
        return "MAJOR"
    return "SEVERE"


def trip_distance_m(fixes):
    """Per-segment round_half_up to integer metres, then integer sum."""
    total = 0
    for a, b in zip(fixes, fixes[1:]):
        seg = haversine_m(a["lat"], a["lng"], b["lat"], b["lng"])
        total += round_half_up(seg)
    return total


def speed_event_count(fixes, tier):
    """Count consecutive-fix pairs whose average speed exceeds the tier's
    speed-event threshold."""
    threshold = TIER_SPEED_EVENT_THRESHOLD.get(tier, 35.0)
    count = 0
    for a, b in zip(fixes, fixes[1:]):
        if (a["speed_mps"] + b["speed_mps"]) / 2.0 > threshold:
            count += 1
    return count


def phone_use_event_count(fixes):
    return sum(1 for f in fixes if f.get("phone_in_use") and f["speed_mps"] >= 1.0)


def driver_score(distance_m, speed_events, phone_events):
    score = 100 - 8 * min(speed_events, 5) - 5 * min(phone_events, 6) - (distance_m // MILE_METRES)
    return max(0, min(100, int(score)))


def age_years(birthdate_dt, now_dt):
    """floor((now - birthdate) / 365.25 days)."""
    delta_seconds = (now_dt - birthdate_dt).total_seconds()
    if delta_seconds < 0:
        return 0
    return int(delta_seconds // (365.25 * 86400))
