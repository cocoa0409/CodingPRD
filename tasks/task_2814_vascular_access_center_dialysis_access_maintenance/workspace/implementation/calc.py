"""Calculations and cascades: triage scoring, partnership scoring and the
posture chain, allowed-amount resolution, device inventory arithmetic,
access counters and the intervention burden score, maturation readiness and
infection attribution.

Constants and orderings are transcribed from PRD.md sections 2.9 - 3.9.
"""
from datetime import timedelta
from decimal import Decimal, ROUND_FLOOR

from core import (
    db, now_dt, now_str, parse_date, parse_dt, round_half_up, touch,
)

# --- PRD 3.3: triage scoring -------------------------------------------------
TRIAGE_LOOKBACK_DAYS = 21
TREND_WEIGHT = Decimal("1.2")
TREND_CAP = 40
FLOW_CRITICAL = 600
FLOW_LOW = 800
VP_HIGH = 150
RECIRC_HIGH = Decimal("10.0")
MISSED_POINTS_PER = 6
MISSED_POINTS_CAP = 18
SAME_DAY_SCORE_MIN = 70
NEXT_DAY_SCORE_MIN = 45

# --- PRD 3.4: partnership scoring -------------------------------------------
PARTNERSHIP_WINDOW_DAYS = 90
GRACE_RATE = {"GOLD": Decimal("0.20"), "SILVER": Decimal("0.10"), "WATCH": Decimal("0")}
MISSED_PENALTY = 4
SAME_DAY_BONUS = 3
GOLD_MIN = 85
SILVER_MIN = 70
ACTIVE_MIN = 70
PROBATION_MIN = 50
OPEN_REFERRAL_STATUSES = ("SUBMITTED", "INFO_REQUESTED", "TRIAGED", "SCHEDULED", "COMPLETED")

# --- PRD 3.5: capacity ------------------------------------------------------
SURGE_ALLOWANCE = 1
SURGE_CUTOFF_HOUR_UTC = 15
RECOVERY_WINDOW_MIN = 90
RECOVERY_BAYS_PER_CASE = 1

# --- PRD 3.7: discharge criteria and burden ---------------------------------
MIN_OBSERVATIONS = 2
MIN_ALDRETE = 9
MIN_RECOVERY_SPAN_MIN = 15
W_ANGIOPLASTY = 2
W_THROMBECTOMY = 3
W_CATH_EXCHANGE = 1
W_MATURATION = 1
W_INFECTION = 5

# --- PRD 3.8: money ---------------------------------------------------------
M52_FACTOR = Decimal("0.50")
PLAIN_FACTOR = Decimal("1.00")
SESSION_CAP_CENTS = 480000
MAX_REBILLS = 2
MEDICAL_NECESSITY_LOOKBACK_DAYS = 30
FAMILY_DEVICE = {
    "ANGIOPLASTY": "BALLOON",
    "THROMBECTOMY": "SHEATH",
    "CATH_EXCHANGE": "SHEATH",
}

# --- PRD 3.9: conversion planning -------------------------------------------
MIN_DIAMETER_MM = Decimal("6.0")
MIN_FLOW_ML_MIN = 600
MAX_DEPTH_MM = Decimal("6.0")
MIN_DAYS_SINCE_PLACEMENT = 42
MIN_TARGET_READINGS = 2
CONVERSION_BURDEN_MIN = 4
ATTRIBUTION_WINDOW_DAYS = 30
INFECTION_DYSFUNCTION_THRESHOLD = 2

COUNTED_ACCESS_STATUSES = ("PLANNED", "PLACED", "MATURING", "IN_USE", "DYSFUNCTIONAL")


def seq_sorted(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def dec(value):
    return Decimal(str(value))


# ---------------------------------------------------------------------------
# Patient access_count (PRD 3.2)
# ---------------------------------------------------------------------------
def refresh_access_count(patient):
    count = 0
    for acc in db.accesses.values():
        if acc["patient_id"] == patient["id"] and acc["status"] in COUNTED_ACCESS_STATUSES:
            count += 1
    if patient["access_count"] != count:
        patient["access_count"] = count
        touch(patient)


# ---------------------------------------------------------------------------
# Access intervention counters and burden score (PRD 3.7)
# ---------------------------------------------------------------------------
def burden_score(access):
    return (
        W_ANGIOPLASTY * access["angioplasty_count"]
        + W_THROMBECTOMY * access["thrombectomy_count"]
        + W_CATH_EXCHANGE * access["catheter_exchange_count"]
        + W_MATURATION * access["maturation_intervention_count"]
        + W_INFECTION * access["attributable_infection_count"]
    )


def recompute_access_counters(access):
    """Recount from DISCHARGED procedures on the access, then rescore burden.

    Returns True when any counter or the burden score actually changed.
    """
    tally = {"ANGIOPLASTY": 0, "THROMBECTOMY": 0, "CATHETER_EXCHANGE": 0,
             "FISTULA_MATURATION_INTERVENTION": 0}
    for proc in db.procedures.values():
        if proc["access_id"] == access["id"] and proc["clinical_status"] == "DISCHARGED":
            tally[proc["procedure_type"]] += 1
    changed = False
    for field, key in (("angioplasty_count", "ANGIOPLASTY"),
                       ("thrombectomy_count", "THROMBECTOMY"),
                       ("catheter_exchange_count", "CATHETER_EXCHANGE"),
                       ("maturation_intervention_count", "FISTULA_MATURATION_INTERVENTION")):
        if access[field] != tally[key]:
            access[field] = tally[key]
            changed = True
    score = burden_score(access)
    if access["intervention_burden_score"] != score:
        access["intervention_burden_score"] = score
        changed = True
    return changed


# ---------------------------------------------------------------------------
# Triage scoring (PRD 3.3)
# ---------------------------------------------------------------------------
def reading_sort_key(reading):
    return (parse_dt(reading["reading_at"]), reading["created_at"], reading["_seq"])


def access_readings(access_id):
    rows = [r for r in db.readings.values() if r["access_id"] == access_id]
    return sorted(rows, key=reading_sort_key)


def readings_at_or_before_clock(access_id):
    clock = now_dt()
    return [r for r in access_readings(access_id) if parse_dt(r["reading_at"]) <= clock]


def triage_window_readings(access_id):
    clock = now_dt()
    start = clock - timedelta(days=TRIAGE_LOOKBACK_DAYS)
    out = []
    for reading in access_readings(access_id):
        moment = parse_dt(reading["reading_at"])
        if start <= moment <= clock:
            out.append(reading)
    return out


def compute_triage(readings, missed_treatment_count):
    """Returns (triage_score, triage_variant, urgency)."""
    latest = readings[-1]
    flow = latest["access_flow_ml_min"]
    if len(readings) >= 2:
        variant = "TREND_BASED"
        previous_flow = readings[-2]["access_flow_ml_min"]
        if previous_flow == 0:
            trend_points = 0
        else:
            decline_pct = (dec(previous_flow) - dec(flow)) / dec(previous_flow) * Decimal(100)
            trend_points = round_half_up(decline_pct * TREND_WEIGHT)
            if trend_points < 0:
                trend_points = 0
            if trend_points > TREND_CAP:
                trend_points = TREND_CAP
        if flow < FLOW_CRITICAL:
            absolute_points = 25
        elif flow < FLOW_LOW:
            absolute_points = 12
        else:
            absolute_points = 0
    else:
        variant = "ABSOLUTE_BASED"
        trend_points = 0
        if flow < FLOW_CRITICAL:
            absolute_points = 40
        elif flow < FLOW_LOW:
            absolute_points = 20
        else:
            absolute_points = 0
    pressure_points = 15 if latest["venous_pressure_mmhg"] >= VP_HIGH else 0
    recirc_points = 10 if dec(latest["recirculation_pct"]) >= RECIRC_HIGH else 0
    missed_points = min(MISSED_POINTS_CAP, MISSED_POINTS_PER * missed_treatment_count)
    total = trend_points + absolute_points + pressure_points + recirc_points + missed_points
    if total > 100:
        total = 100
    if total >= SAME_DAY_SCORE_MIN:
        urgency = "SAME_DAY"
    elif total >= NEXT_DAY_SCORE_MIN:
        urgency = "NEXT_DAY"
    else:
        urgency = "ROUTINE"
    return total, variant, urgency


# ---------------------------------------------------------------------------
# Partnership scoring window (PRD 3.4)
# ---------------------------------------------------------------------------
def partnership_window():
    clock = now_dt()
    return clock - timedelta(days=PARTNERSHIP_WINDOW_DAYS), clock


def window_referrals(facility_id):
    start, end = partnership_window()
    rows = []
    for referral in db.referrals.values():
        if referral["referring_facility_id"] != facility_id:
            continue
        if referral["status"] not in OPEN_REFERRAL_STATUSES:
            continue
        created = parse_dt(referral["created_at"])
        if start <= created <= end:
            rows.append(referral)
    return seq_sorted(rows)


def honored_same_day_count(referrals):
    ids = set(r["id"] for r in referrals)
    honored = 0
    for proc in db.procedures.values():
        if proc["referral_id"] not in ids:
            continue
        if proc["clinical_status"] != "DISCHARGED":
            continue
        referral = db.referrals[proc["referral_id"]]
        if referral.get("urgency") != "SAME_DAY":
            continue
        triaged_at = referral.get("triaged_at")
        if not triaged_at:
            continue
        if parse_dt(proc["scheduled_start"]).date() == parse_dt(triaged_at).date():
            honored += 1
    return honored


def partnership_aggregates(facility):
    """Pure computation shared by the scorer and the metrics read."""
    referrals = window_referrals(facility["id"])
    volume = len(referrals)
    raw_missed = sum(r["missed_treatment_count"] for r in referrals)
    tier = facility["partnership_tier"]
    grace = int((Decimal(volume) * GRACE_RATE[tier]).to_integral_value(rounding=ROUND_FLOOR))
    adjusted = raw_missed - grace
    if adjusted < 0:
        adjusted = 0
    honored = honored_same_day_count(referrals)
    return referrals, volume, raw_missed, grace, adjusted, honored


POSTURE_RANK = {"ACTIVE": 0, "PROBATION": 1, "SUSPENDED": 2}


def score_facility(facility):
    """The five-hop posture chain of PRD 3.4, in one pass."""
    _, volume, raw_missed, grace, adjusted, honored = partnership_aggregates(facility)

    score = 100 - MISSED_PENALTY * adjusted + SAME_DAY_BONUS * honored
    if score < 0:
        score = 0
    if score > 100:
        score = 100

    if score >= GOLD_MIN:
        tier = "GOLD"
    elif score >= SILVER_MIN:
        tier = "SILVER"
    else:
        tier = "WATCH"

    if score >= ACTIVE_MIN:
        posture = "ACTIVE"
    elif score >= PROBATION_MIN:
        posture = "PROBATION"
    else:
        posture = "SUSPENDED"

    previous_posture = facility["contract_status"]
    facility["partnership_score"] = score
    facility["partnership_tier"] = tier
    facility["contract_status"] = posture
    facility["referral_volume_window"] = volume
    facility["raw_missed_count_window"] = raw_missed
    facility["grace_credit_window"] = grace
    facility["adjusted_missed_count_window"] = adjusted
    facility["same_day_honored_window"] = honored
    facility["last_scored_at"] = now_str()
    touch(facility)

    if POSTURE_RANK[posture] > POSTURE_RANK[previous_posture]:
        posture_drop_cascade(facility, posture)


def posture_drop_cascade(facility, posture):
    """Hops 3, 4 and 5: hold referrals, cancel cases, release device units."""
    if posture == "SUSPENDED":
        holdable = ("SUBMITTED", "TRIAGED", "SCHEDULED")
    else:
        holdable = ("SUBMITTED", "TRIAGED")

    targets = [r for r in db.referrals.values()
               if r["referring_facility_id"] == facility["id"] and r["status"] in holdable]
    for referral in seq_sorted(targets):
        referral["status"] = "INFO_REQUESTED"
        referral["hold_reason"] = "FACILITY_POSTURE_HOLD"
        referral["info_request_count"] += 1
        referral["triage_score"] = None
        referral["triage_variant"] = None
        referral["urgency"] = None
        referral["triaged_at"] = None
        touch(referral)

        if posture != "SUSPENDED":
            continue
        cases = [p for p in db.procedures.values()
                 if p["referral_id"] == referral["id"] and p["clinical_status"] == "SCHEDULED"]
        for proc in seq_sorted(cases):
            proc["clinical_status"] = "CANCELLED"
            proc["cancel_reason"] = "FACILITY_POSTURE_HOLD"
            touch(proc)
            release_reserved_usages(proc)


# ---------------------------------------------------------------------------
# Device inventory arithmetic (PRD 2.11, 3.6)
# ---------------------------------------------------------------------------
def lot_headroom(lot):
    return lot["quantity_on_hand"] - lot["quantity_reserved"]


def procedure_usages(procedure_id, state=None):
    rows = [u for u in db.usages.values() if u["procedure_id"] == procedure_id]
    if state is not None:
        rows = [u for u in rows if u["state"] == state]
    return seq_sorted(rows)


def release_usage(usage):
    lot = db.lots[usage["device_lot_id"]]
    usage["state"] = "RELEASED"
    usage["released_at"] = now_str()
    touch(usage)
    lot["quantity_reserved"] -= usage["quantity"]
    touch(lot)


def release_reserved_usages(procedure):
    for usage in procedure_usages(procedure["id"], "RESERVED"):
        release_usage(usage)


def consume_usage(usage, waste=False):
    lot = db.lots[usage["device_lot_id"]]
    usage["state"] = "CONSUMED"
    usage["consumed_at"] = now_str()
    if waste:
        usage["wasted_quantity"] = usage["quantity"]
    touch(usage)
    lot["quantity_on_hand"] -= usage["quantity"]
    lot["quantity_reserved"] -= usage["quantity"]
    touch(lot)
    if lot["quantity_on_hand"] == 0 and lot["status"] == "AVAILABLE":
        lot["status"] = "DEPLETED"
        touch(lot)


def consume_reserved_usages(procedure, waste=False):
    for usage in procedure_usages(procedure["id"], "RESERVED"):
        consume_usage(usage, waste=waste)


def lot_sort_key(lot):
    return (parse_date(lot["expires_on"]), lot["created_at"], lot["_seq"])


# ---------------------------------------------------------------------------
# Allowed-amount resolution (PRD 3.8)
# ---------------------------------------------------------------------------
def procedure_code_lines(procedure_id):
    rows = [c for c in db.codes.values() if c["procedure_id"] == procedure_id]
    return sorted(rows, key=lambda c: (c["rank"], c["created_at"], c["_seq"]))


def position_factor(index):
    if index == 0:
        return 100
    if index == 1:
        return 50
    return 25


def resolve_lines(lines, variant):
    """Returns (per-line resolutions, total).  Rounds per line, then sums."""
    resolutions = []
    if not lines:
        return resolutions, 0
    primary_family = lines[0]["code_family"]
    for index, line in enumerate(lines):
        factor_pct = position_factor(index)
        modifier_factor = M52_FACTOR if line["modifier"] == "M52" else PLAIN_FACTOR
        bundled = (
            variant == "BUNDLED_ESRD"
            and index > 0
            and line["modifier"] != "M59"
            and (line["code_family"] == primary_family or line["code_family"] == "IMAGING")
        )
        if bundled:
            resolutions.append({
                "line": line,
                "is_bundled": True,
                "reduction_factor_pct": 0,
                "allowed_cents": 0,
            })
        else:
            cents = round_half_up(
                dec(line["base_allowed_cents"]) * modifier_factor * Decimal(factor_pct) / Decimal(100)
            )
            resolutions.append({
                "line": line,
                "is_bundled": False,
                "reduction_factor_pct": factor_pct,
                "allowed_cents": cents,
            })
    total = sum(r["allowed_cents"] for r in resolutions)
    return resolutions, total


def procedure_payer_program(procedure):
    """The payer model of the patient reached through the referral and its access."""
    referral = db.referrals.get(procedure["referral_id"])
    if referral is None:
        return None
    access = db.accesses.get(referral["access_id"])
    if access is None:
        return None
    patient = db.patients.get(access["patient_id"])
    if patient is None:
        return None
    return patient["payer_program"]


def recompute_allowed_amount(procedure):
    """Full recomputation over the whole line set; writes lines and procedure."""
    variant = procedure_payer_program(procedure)
    lines = procedure_code_lines(procedure["id"])
    resolutions, total = resolve_lines(lines, variant)
    for resolution in resolutions:
        line = resolution["line"]
        line["is_bundled"] = resolution["is_bundled"]
        line["reduction_factor_pct"] = resolution["reduction_factor_pct"]
        line["allowed_cents"] = resolution["allowed_cents"]
    procedure["reimbursement_variant"] = variant
    procedure["allowed_amount_cents"] = total
    return total


# ---------------------------------------------------------------------------
# Maturation readiness (PRD 3.9)
# ---------------------------------------------------------------------------
def evaluate_maturation(target_access, diameter_mm, flow_ml_min, depth_mm):
    reasons = []
    if dec(diameter_mm) < MIN_DIAMETER_MM:
        reasons.append("DIAMETER")
    if flow_ml_min < MIN_FLOW_ML_MIN:
        reasons.append("FLOW")
    if dec(depth_mm) > MAX_DEPTH_MM:
        reasons.append("DEPTH")
    days = (now_dt().date() - parse_date(target_access["placed_on"])).days
    if days < MIN_DAYS_SINCE_PLACEMENT:
        reasons.append("MATURATION_DAYS")
    if len(readings_at_or_before_clock(target_access["id"])) < MIN_TARGET_READINGS:
        reasons.append("SURVEILLANCE_COUNT")
    reasons.sort()
    return (len(reasons) == 0), reasons, days


# ---------------------------------------------------------------------------
# Access abandonment and the conversion hops (PRD 3.2, 3.7 hops 4-5, 3.9)
# ---------------------------------------------------------------------------
def abandon_access(access):
    """Terminal abandonment: cascades to plans whose target this access is."""
    access["status"] = "ABANDONED"
    access["abandoned_at"] = now_str()
    touch(access)
    patient = db.patients.get(access["patient_id"])
    if patient is not None:
        refresh_access_count(patient)
    plans = [p for p in db.plans.values()
             if p["target_access_id"] == access["id"]
             and p["status"] in ("DRAFT", "ACTIVE", "MATURATION_HOLD")]
    for plan in seq_sorted(plans):
        plan["status"] = "ABANDONED"
        touch(plan)


def convert_ready_plans(access):
    """Hop 4 then hop 5: convert ready plans, then retire their source access."""
    plans = [p for p in db.plans.values()
             if p["target_access_id"] == access["id"]
             and p["status"] == "ACTIVE"
             and p["readiness_met"] is True]
    for plan in seq_sorted(plans):
        plan["status"] = "CONVERTED"
        plan["converted_at"] = now_str()
        touch(plan)
        source = db.accesses.get(plan["from_access_id"])
        if source is not None and source["status"] != "ABANDONED":
            abandon_access(source)


def access_has_open_case(access_id):
    for proc in db.procedures.values():
        if proc["access_id"] == access_id and proc["clinical_status"] in ("SCHEDULED", "IN_ROOM", "RECOVERY"):
            return True
    return False
