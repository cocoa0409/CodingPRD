"""The eight calculations of the specification."""
import math
from decimal import Decimal, ROUND_HALF_UP

import clock
import db

# ---- constants -----------------------------------------------------------
BASE_POINTS = Decimal("40")
PHOTO_BONUS_PER_EXTRA = Decimal("5")
PHOTO_BONUS_CAP = Decimal("20")
REVISION_PENALTY_STEP = Decimal("0.15")

ROLLING_WINDOW_N = 20
DECAY_HALF_LIFE_DAYS = Decimal("180")
NEUTRAL_SEED = Decimal("0.5")
PROBATION_FLOOR = Decimal("0.50")

QUORUM_MIN_VOTES = 2
CONSENSUS_WEIGHT_THRESHOLD = Decimal("3.0")
REVISION_WEIGHT_THRESHOLD = Decimal("2.0")
MAX_REVISION_ROUNDS = 2

GAP_RATIO_CEILING = Decimal("0.50")
SATURATION_MULTIPLIER = 2

FLOOR_FRACTION = Decimal("0.80")
MIN_RECORD_FLOOR = 2

STREAK_LENGTH = 5
STREAK_BONUS_POINTS = 5
TIER_MILESTONE_POINTS = 25

DRIFT_PER_LOAN_HOUR_PPM = Decimal("0.75")
DAMAGE_DRIFT_PENALTY_PPM = Decimal("200.00")
OVERDUE_DRIFT_PENALTY_PPM = Decimal("100.00")
CALIBRATION_DRIFT_LIMIT_PPM = Decimal("500.00")
CALIBRATION_RETIRE_PPM = Decimal("1000.00")
CALIBRATION_VALID_DAYS = 365
QUARANTINE_HOURS = 48

METERS_PER_DEGREE = Decimal("111320.0")
PHOTO_GEO_TOLERANCE_M = Decimal("250.00")
PHOTO_TIME_TOLERANCE_HOURS = 2

PASSING_EXAM_SCORE = 70
ARCHIVE_GRACE_DAYS = 30
RETRACTED_CONFIRM_SUSPEND_THRESHOLD = 2

LEVEL_RANK = {"BASIC": 1, "ADVANCED": 2, "EXPERT": 3}
TIER_RANK = {"BRONZE": 1, "SILVER": 2, "GOLD": 3, "PLATINUM": 4}


def rnd(value, places):
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    exp = Decimal(1).scaleb(-places)
    return value.quantize(exp, rounding=ROUND_HALF_UP)


def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def hours_between(start, end):
    """Exact fractional hours from start to end."""
    return dec((end - start).total_seconds()) / dec(3600)


def days_between(start, end):
    return dec((end - start).total_seconds()) / dec(86400)


# --------------------------------------------------------------------------
# observation_quality_points
# --------------------------------------------------------------------------
def raw_quality(observation, protocol, site):
    extra = observation["photo_count"] - protocol["min_photo_count"]
    if extra < 0:
        extra = 0
    photo_bonus = PHOTO_BONUS_PER_EXTRA * Decimal(extra)
    if photo_bonus > PHOTO_BONUS_CAP:
        photo_bonus = PHOTO_BONUS_CAP

    lag = hours_between(observation["observed_at"], observation["submitted_at"])
    if lag <= 6:
        timeliness = Decimal("1.00")
    elif lag <= 24:
        timeliness = Decimal("0.90")
    elif lag <= 72:
        timeliness = Decimal("0.75")
    else:
        timeliness = Decimal("0.50")

    weight = dec(site["priority_weight"])
    site_factor = max(Decimal("0.80"), min(Decimal("1.50"), weight))
    return (BASE_POINTS + photo_bonus) * timeliness * site_factor


def provisional_points(observation, protocol, site):
    return rnd(raw_quality(observation, protocol, site), 2)


def final_points(observation, protocol, site):
    raw = raw_quality(observation, protocol, site)
    confidence_multiplier = Decimal("0.60") + Decimal("0.10") * dec(observation["consensus_confidence"])
    revision_penalty = Decimal("1.00") - REVISION_PENALTY_STEP * Decimal(observation["revision_round"])
    return rnd(raw * confidence_multiplier * revision_penalty, 2)


# --------------------------------------------------------------------------
# volunteer_quality_score
# --------------------------------------------------------------------------
ADJUDICATED = ("ACCEPTED", "REJECTED", "RETRACTED")


def adjudicated_set(volunteer_id):
    return [o for o in db.observations.values()
            if o["volunteer_id"] == volunteer_id and o["review_status"] in ADJUDICATED]


def rolling_quality_score(volunteer_id):
    rows = adjudicated_set(volunteer_id)
    if not rows:
        return NEUTRAL_SEED
    rows.sort(key=lambda o: (o["observed_at"], o["created_at"], o["_seq"]), reverse=True)
    window = rows[:ROLLING_WINDOW_N]
    hits = sum(1 for o in window if o["review_status"] == "ACCEPTED")
    return rnd(Decimal(hits) / Decimal(len(window)), 4)


def lifetime_quality_score(volunteer_id):
    rows = adjudicated_set(volunteer_id)
    if not rows:
        return NEUTRAL_SEED
    now = clock.now()
    total_w = Decimal(0)
    total_hw = Decimal(0)
    for o in rows:
        age_days = days_between(o["observed_at"], now)
        weight = dec(math.pow(0.5, float(age_days / DECAY_HALF_LIFE_DAYS)))
        total_w += weight
        if o["review_status"] == "ACCEPTED":
            total_hw += weight
    if total_w == 0:
        return NEUTRAL_SEED
    return rnd(total_hw / total_w, 4)


def tier_for(lifetime_score):
    score = dec(lifetime_score)
    if score >= Decimal("0.90"):
        return "PLATINUM"
    if score >= Decimal("0.75"):
        return "GOLD"
    if score >= Decimal("0.60"):
        return "SILVER"
    return "BRONZE"


def tier_multiplier(lifetime_score):
    score = dec(lifetime_score)
    if score >= Decimal("0.90"):
        return Decimal("1.50")
    if score >= Decimal("0.75"):
        return Decimal("1.25")
    if score >= Decimal("0.60"):
        return Decimal("1.10")
    return Decimal("1.00")


# --------------------------------------------------------------------------
# verification_consensus
# --------------------------------------------------------------------------
def vote_weight(expert, confidence):
    return rnd(dec(expert["verification_weight"]) * (Decimal("0.6") + Decimal("0.1") * Decimal(confidence)), 4)


def consensus(observation):
    """Recompute the tallies over the current round; return the resolution."""
    rnd_no = observation["revision_round"]
    round_votes = [v for v in db.votes.values()
                   if v["observation_id"] == observation["id"] and v["round_number"] == rnd_no]

    confirm_w = Decimal(0)
    reject_w = Decimal(0)
    revision_w = Decimal(0)
    conf_num = Decimal(0)
    conf_den = Decimal(0)
    for v in round_votes:
        w = dec(v["weight_applied"])
        if v["decision"] == "CONFIRM":
            confirm_w += w
            expert = db.experts.get(v["expert_id"])
            ew = dec(expert["verification_weight"]) if expert else Decimal(0)
            conf_num += Decimal(v["confidence"]) * ew
            conf_den += ew
        elif v["decision"] == "REJECT":
            reject_w += w
        elif v["decision"] == "REQUEST_REVISION":
            revision_w += w

    observation["confirm_weight"] = rnd(confirm_w, 4)
    observation["reject_weight"] = rnd(reject_w, 4)
    observation["revision_weight"] = rnd(revision_w, 4)
    if conf_den == 0:
        observation["consensus_confidence"] = rnd(Decimal(0), 4)
    else:
        observation["consensus_confidence"] = rnd(conf_num / conf_den, 4)

    cw = dec(observation["confirm_weight"])
    rw = dec(observation["reject_weight"])
    vw = dec(observation["revision_weight"])

    if len(round_votes) < QUORUM_MIN_VOTES:
        return "HOLD"
    if rw >= CONSENSUS_WEIGHT_THRESHOLD and rw >= cw:
        return "REJECT"
    if cw >= CONSENSUS_WEIGHT_THRESHOLD and cw > rw:
        return "ACCEPT"
    if vw >= REVISION_WEIGHT_THRESHOLD:
        return "REVISE"
    return "HOLD"


# --------------------------------------------------------------------------
# photo_evidence_screening
# --------------------------------------------------------------------------
def geo_delta(exif_lat, exif_lon, obs_lat, obs_lon):
    dlat = dec(exif_lat) - dec(obs_lat)
    dlon = dec(exif_lon) - dec(obs_lon)
    dist = dec(math.sqrt(float(dlat * dlat + dlon * dlon)))
    return rnd(METERS_PER_DEGREE * dist, 2)


def screen_photo(captured_at, observed_at, delta_meters):
    lag = hours_between(observed_at, captured_at)
    if lag < -PHOTO_TIME_TOLERANCE_HOURS or lag > PHOTO_TIME_TOLERANCE_HOURS:
        return "REJECTED"
    if dec(delta_meters) > PHOTO_GEO_TOLERANCE_M:
        return "FLAGGED_MISMATCH"
    return "ACCEPTED"


# --------------------------------------------------------------------------
# equipment_calibration_drift
# --------------------------------------------------------------------------
def loan_hours_between(issued_at, returned_at):
    exact = hours_between(issued_at, returned_at)
    return int(math.ceil(float(exact)))


def drift_for(loan_hours, condition, was_overdue):
    if condition == "LOST":
        return rnd(Decimal("0.00"), 2)
    base = rnd(Decimal(loan_hours) * DRIFT_PER_LOAN_HOUR_PPM, 2)
    damage = DAMAGE_DRIFT_PENALTY_PPM if condition == "DAMAGED" else Decimal("0.00")
    overdue = OVERDUE_DRIFT_PENALTY_PPM if was_overdue else Decimal("0.00")
    return rnd(base + damage + overdue, 2)
