"""Calculation rules (scaffold table 1.3 / PRD section 3)."""
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP

from db import STORE

# wip_valuation constants
MATERIAL_COST_CENTS = {"MODEL_D": 4200000, "MODEL_B": 3600000, "MODEL_O": 3100000, "ART_CASE": 9000000}
STAGE_RATE_CENTS = {"RIM_BENDING": 14500, "SEASONING_CHECK": 9500, "ACTION_REGULATION": 21000, "VOICING": 24000}
PLANNED_HOURS = {"RIM_BENT": 120, "SEASONING": 40, "ACTION_REGULATION": 40, "VOICING": 200, "COMPLETED": 160}
STAGE_TO_OP = {
    "RIM_BENT": "RIM_BENDING",
    "SEASONING": "SEASONING_CHECK",
    "ACTION_REGULATION": "SEASONING_CHECK",
    "VOICING": "ACTION_REGULATION",
    "COMPLETED": "VOICING",
}
STAGE_CHAIN = ["COMMISSIONED", "RIM_BENT", "SEASONING", "ACTION_REGULATION", "VOICING", "COMPLETED"]
NEXT_STAGE = {STAGE_CHAIN[i]: STAGE_CHAIN[i + 1] for i in range(len(STAGE_CHAIN) - 1)}

# effective_training_hours constants
MISMATCHED_SUPERVISION_RATIO = Decimal("0.5")
HOURS_REQUIRED = {"RIM_BENDING": 600, "SEASONING_CHECK": 300}
FAIL_RETAIN_RATIO = Decimal("0.75")

# loan_fee_estimate constants
WEEKLY_RATE_CENTS = {"MODEL_D": 85000, "MODEL_B": 72000, "MODEL_O": 64000, "ART_CASE": 150000}
TIER_FACTOR = {"STANDARD": Decimal("1.0"), "PRIVILEGED": Decimal("0.8")}
MIN_FEE_CENTS = 55000
MAX_FEE_CENTS = 2000000

# seasoning_and_drying_gates constants
MOISTURE_READY_PCT = Decimal("8.0")
MIN_DRYING_DAYS = 240
SEASONING_MIN_DAYS = 365

# restoration_authenticity constants
AUTHENTICITY_MIN_PCT = Decimal("70.0")

TECH_BUFFER_SECONDS = 86400  # TECH_BUFFER_DAYS = 1

GRADE_BUMP = {"D": "C", "C": "B", "B": "A", "A": "A"}
GRADE_RANK = {"A": 0, "B": 1, "C": 2, "D": 3}


def d_num(v):
    return Decimal(str(v))


def rhu_int(dec):
    return int(dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rhu_1dp(dec):
    return dec.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def stage_logs_for(build_id):
    logs = [l for l in STORE["stage_logs"].values() if l["build_order_id"] == build_id]
    logs.sort(key=lambda l: l["_seq"])
    return logs


def wip_actual(order):
    """ACTUAL variant: allocated batch material + per-entry rounded labor."""
    total = MATERIAL_COST_CENTS[order["model"]] if order["wood_batch_id"] else 0
    for l in stage_logs_for(order["id"]):
        total += rhu_int(d_num(l["hours_applied"]) * STAGE_RATE_CENTS[l["operation_type"]])
    return total


def wip_provisional(order):
    """PROVISIONAL: actual + replacement material when batchless + planned labor."""
    total = wip_actual(order)
    if not order["wood_batch_id"]:
        total += MATERIAL_COST_CENTS[order["model"]]
    idx = STAGE_CHAIN.index(order["status"])
    for stage in STAGE_CHAIN[idx + 1:]:
        total += rhu_int(Decimal(PLANNED_HOURS[stage]) * STAGE_RATE_CENTS[STAGE_TO_OP[stage]])
    return total


def recompute_endorsement_hours(track):
    """Per-entry round-half-up to whole hours, THEN sum (pinned order, PRD 3.3:
    two 7-hour mismatched entries credit 4 + 4 = 8, not round(7.0) = 7)."""
    logged = Decimal("0")
    effective = Decimal("0")
    for e in track["supervision_log"]:
        hours = d_num(e["hours"])
        logged += hours
        ratio = Decimal("1.0") if e["specialty_match"] else MISMATCHED_SUPERVISION_RATIO
        effective += rhu_int(hours * ratio)
    track["logged_hours"] = float(logged)
    track["effective_hours"] = float(effective)


def maybe_promote_endorsement(track):
    """Auto IN_TRAINING -> PENDING_ASSESSMENT at the operation's hour bar."""
    if track["status"] != "IN_TRAINING":
        return False
    if d_num(track["effective_hours"]) >= d_num(HOURS_REQUIRED[track["operation_type"]]):
        track["status"] = "PENDING_ASSESSMENT"
        return True
    return False


def fail_scaled_hours(hours):
    """FAIL outcome: whole-hour floor of 0.75 * hours, per entry."""
    return int((d_num(hours) * FAIL_RETAIN_RATIO).to_integral_value(rounding=ROUND_FLOOR))


def top_supervisor_id(track):
    """Top supervisor by raw hours; tie -> earliest first entry logged (append
    order breaks equal timestamps). Empty log -> None (never blocks)."""
    totals = {}
    first_idx = {}
    for idx, e in enumerate(track["supervision_log"]):
        sup = e["supervising_craftsman_id"]
        if sup is None:
            continue
        totals[sup] = totals.get(sup, Decimal("0")) + d_num(e["hours"])
        if sup not in first_idx:
            first_idx[sup] = idx
    if not totals:
        return None
    return min(totals, key=lambda s: (-totals[s], first_idx[s]))


def tour_weeks(tour_start, tour_end):
    """ceil(whole-day length / 7): 7 days -> 1 week, 8 days -> 2 weeks.
    Whole-day length is the §2.4 floor of elapsed 86,400-second days, so a
    sub-day remainder never adds a week (7 days + 1 hour -> 1 week)."""
    seconds = int((tour_end - tour_start).total_seconds())
    days = seconds // 86400
    return -(-days // 7)


def loan_fee_cents(model, tier, weeks):
    raw = Decimal(WEEKLY_RATE_CENTS[model] * weeks) * TIER_FACTOR[tier]
    fee = rhu_int(raw)
    return min(MAX_FEE_CENTS, max(MIN_FEE_CENTS, fee))


def standings(artist):
    """(standing_realized, standing_forward): forward adds ON_TOUR tour weeks."""
    realized = artist["performances_logged"]
    forward = realized
    for l in STORE["loans"].values():
        if l["artist_id"] == artist["id"] and l["status"] == "ON_TOUR":
            forward += tour_weeks(l["tour_start"], l["tour_end"])
    return realized, forward


def authenticity_pct(authentic, total):
    """Null while total == 0; else round_half_up(100 * authentic / total, 1dp)."""
    if total == 0:
        return None
    return float(rhu_1dp(d_num(authentic) * 100 / d_num(total)))


def pct_passes(pct):
    """None (no parts replaced) is treated as authentic; 70.0 passes, 69.9 fails."""
    return pct is None or d_num(pct) >= AUTHENTICITY_MIN_PCT
