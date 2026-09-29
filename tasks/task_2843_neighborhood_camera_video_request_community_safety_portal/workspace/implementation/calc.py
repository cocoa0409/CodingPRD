"""The nine deterministic calculations (PRD 2.6, 2.7, 3.3, 3.6, 3.7, 3.8)."""
import math
from decimal import Decimal, ROUND_HALF_UP

import store
from store import db

# ---- constants (SCAFFOLD.yaml calculations[].constants) --------------------
GLOBAL_MIN_DEVICE_FLOOR = 3
PORTAL_GRACE_DAYS = 45
BPS_SCALE = 10000
FATIGUE_TIER_1_MAX = 5
FATIGUE_TIER_2_MAX = 10
FATIGUE_TIER_3_MAX = 20
DISCRIMINATION_FLAG_THRESHOLD = Decimal("0.49")
STRIKE_REVIEW_THRESHOLD = 2
STRIKE_SUSPEND_THRESHOLD = 3
RECENT_POST_LOOKBACK_DAYS = 30
MAX_REVISION_CYCLES = 2
RESIDENT_FLAG_THRESHOLD = 2
AREA_MAX_RADIUS_M = 1500
AREA_PROXIMITY_M = 300
AREA_CANVASS_BUFFER_HOURS = 24
AREA_MAX_WINDOW_HOURS = 168
SOLICITATION_RESPONSE_HOURS = 72
SECONDS_PER_DAY = 86400

TWO_PLACES = Decimal("0.01")

W_PROTECTED = Decimal("0.34")
W_UNVERIFIED = Decimal("0.17")
W_LOCATION = Decimal("0.115")
W_HOSTILE = Decimal("0.085")


# ---- geometry (PRD 2.6) ---------------------------------------------------

def dist_sq(x1, y1, x2, y2):
    dx = x1 - x2
    dy = y1 - y2
    return dx * dx + dy * dy


# ---- decimals / rates (PRD 2.7) ------------------------------------------

def round2(value):
    return Decimal(value).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def round_half_up_int(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def share_rate_bps(numerator, denominator):
    if not denominator:
        return 0
    return round_half_up_int(
        (Decimal(numerator) * BPS_SCALE) / Decimal(denominator))


# ---- discrimination score (PRD 3.8) --------------------------------------

def discrimination_score(protected, unverified, location, hostile):
    terms = [
        round2(W_PROTECTED * protected),
        round2(W_UNVERIFIED * unverified),
        round2(W_LOCATION * location),
        round2(W_HOSTILE * hostile),
    ]
    total = terms[0] + terms[1] + terms[2] + terms[3]
    return round2(total)


def score_flags(score):
    return score >= DISCRIMINATION_FLAG_THRESHOLD


# ---- area sizing (PRD 3.3) ----------------------------------------------

def ceil_hours(start, end):
    seconds = (end - start).total_seconds()
    return int(math.ceil(seconds / 3600.0))


def radius_bump(radius_m):
    if radius_m <= 500:
        return 0
    if radius_m <= 1000:
        return 2
    return 5


def window_bump(start, end):
    hours = ceil_hours(start, end)
    return min(3, int(math.ceil(hours / 12.0)) - 1)


def effective_min_devices(agency, area):
    base = agency["min_device_threshold"]
    total = base + radius_bump(area["radius_m"]) + window_bump(
        area["window_start_utc"], area["window_end_utc"])
    return max(GLOBAL_MIN_DEVICE_FLOOR, total)


def device_is_eligible(device, resident, area, locked_at):
    """The six lock-time eligibility tests of PRD 3.3."""
    if device["status"] != "ACTIVE":
        return False
    if device["auto_decline_requests"]:
        return False
    if resident is None or resident["status"] != "ACTIVE":
        return False
    if resident["data_sharing_opt_out"]:
        return False
    d2 = dist_sq(device["grid_x_m"], device["grid_y_m"],
                 area["center_x_m"], area["center_y_m"])
    if d2 > area["radius_m"] * area["radius_m"]:
        return False
    gap = (locked_at - area["window_start_utc"]).total_seconds()
    if device["retention_window_days"] * SECONDS_PER_DAY < gap:
        return False
    return True


def build_roster(area, locked_at):
    """Ordered eligible-device roster: distance ASC then Device.created_at ASC."""
    rows = []
    for device in db.devices.values():
        resident = db.residents.get(device["owner_resident_id"])
        if not device_is_eligible(device, resident, area, locked_at):
            continue
        rows.append({
            "device_id": device["id"],
            "distance_sq": dist_sq(device["grid_x_m"], device["grid_y_m"],
                                   area["center_x_m"], area["center_y_m"]),
            "created_at": device["created_at"],
        })
    rows.sort(key=lambda r: (r["distance_sq"], r["created_at"]))
    return [{"device_id": r["device_id"], "distance_sq": r["distance_sq"]}
            for r in rows]


def roster_member_still_eligible(device):
    """Recount predicate for the eligibility-collapse rule (PRD 3.3).

    Only the three named triggers matter: the camera's status, the owner's
    account status and the owner's opt-out flag.  ``auto_decline_requests``
    excludes a camera from *future* eligible-device sets only (PRD 3.2).
    """
    if device is None or device["status"] != "ACTIVE":
        return False
    resident = db.residents.get(device["owner_resident_id"])
    if resident is None or resident["status"] != "ACTIVE":
        return False
    if resident["data_sharing_opt_out"]:
        return False
    return True


# ---- notification fatigue (PRD 3.7) --------------------------------------

def fatigue_penalty(snapshot, budget):
    if snapshot < FATIGUE_TIER_1_MAX:
        return 0
    if snapshot < FATIGUE_TIER_2_MAX:
        return 1
    if snapshot < FATIGUE_TIER_3_MAX:
        return 3
    return budget


def effective_budget(snapshot, budget):
    return max(0, budget - fatigue_penalty(snapshot, budget))


def derive_fatigue_state(resident, eff_budget):
    if resident["notification_mute_enabled"]:
        return "MUTED"
    sent = resident["notifications_sent_today"]
    if eff_budget > 0 and sent >= eff_budget:
        return "THROTTLED"
    if eff_budget == 0:
        return "THROTTLED"
    if sent >= FATIGUE_TIER_2_MAX:
        return "STRAINED"
    return "NORMAL"


# ---- clip retention (PRD 3.6) -------------------------------------------

def clip_retention(request_row, device, agency, shared_at, recorded_start):
    agency_candidate = store.add_days(shared_at,
                                      agency["post_share_retention_days"])
    portal_candidate = store.add_days(request_row["expires_at"],
                                      PORTAL_GRACE_DAYS)
    if request_row["compliance_state"] == "AUDIT_ESCALATED":
        return ("CASE_ANCHORED", max(agency_candidate, portal_candidate),
                "LEGAL_HOLD")
    device_candidate = store.add_days(recorded_start,
                                      device["retention_window_days"])
    return ("DEVICE_ANCHORED",
            min(agency_candidate, device_candidate, portal_candidate),
            "RETAINED")


# ---- moderation strikes (PRD 3.8) ---------------------------------------

def total_strike_score(resident):
    return (resident["accuracy_strike_count"]
            + 2 * resident["discrimination_strike_count"])


def privilege_for_score(score):
    if score >= STRIKE_SUSPEND_THRESHOLD:
        return "POSTING_SUSPENDED"
    if score == STRIKE_REVIEW_THRESHOLD:
        return "REVIEW_REQUIRED"
    return "UNRESTRICTED"
