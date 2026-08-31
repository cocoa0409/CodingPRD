"""Calculation rules (SCAFFOLD s1.3 / PRD s3)."""
from decimal import Decimal, ROUND_HALF_UP

import store
from constants import (
    ADMIN_FEE_RATE_HIGH, ADMIN_FEE_RATE_LOW, ADMIN_FEE_RATE_MID,
    ADMIN_FEE_TIER_HIGH_CENTS, ADMIN_FEE_TIER_LOW_CENTS, CATALOG_LIST_CENTS,
    CONDUCT_BASE_POINTS, DEPRECIATION_CAP, DEPRECIATION_PER_YEAR, DUTY_POINTS,
    FORWARD_WINDOW_DAYS, HARDSHIP_CAP_CENTS, HARDSHIP_RELIEF_RATE, LINE_RATE,
    MISSED_MULTIPLIER, REPEAT_MULTIPLIER_CAP, REPEAT_STEP, TERM_START_UTC,
)
from store import DB


def round_half_up_dec(value, places):
    quant = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(quant, rounding=ROUND_HALF_UP)


def round_half_up(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ------------------------------------------- damage_line_assessment
def provisional_subtotal(damage_lines):
    total = 0
    for line in damage_lines:
        total += CATALOG_LIST_CENTS[line["component_code"]] * line["quantity"]
    return total


def depreciation_rate(room):
    age = store.now().year - room["last_renovation_year"]
    if age < 0:
        age = 0
    rate = Decimal(DEPRECIATION_PER_YEAR) * Decimal(age)
    cap = Decimal(DEPRECIATION_CAP)
    return cap if rate > cap else rate


def assessed_subtotal(damage_lines, rate):
    """Depreciate and round EACH line, then sum."""
    total = 0
    for line in damage_lines:
        gross = Decimal(CATALOG_LIST_CENTS[line["component_code"]]) * Decimal(line["quantity"])
        total += round_half_up(gross * (Decimal(1) - rate))
    return total


# ------------------------------------------- damage_charge_settlement
def admin_rate_for(gross_cents):
    if gross_cents < ADMIN_FEE_TIER_LOW_CENTS:
        return Decimal(ADMIN_FEE_RATE_LOW)
    if gross_cents < ADMIN_FEE_TIER_HIGH_CENTS:
        return Decimal(ADMIN_FEE_RATE_MID)
    return Decimal(ADMIN_FEE_RATE_HIGH)


def settlement(gross_cents, hardship_flag):
    rate = admin_rate_for(gross_cents)
    admin_fee = round_half_up(Decimal(gross_cents) * rate)
    total_before_relief = gross_cents + admin_fee
    if hardship_flag:
        relief = round_half_up(Decimal(total_before_relief) * Decimal(HARDSHIP_RELIEF_RATE))
        relief = min(HARDSHIP_CAP_CENTS, relief)
    else:
        relief = 0
    final_amount = max(0, total_before_relief - relief)
    return admin_fee, relief, final_amount


# ------------------------------------------- program_reimbursement_amount
def reimbursement_amount(receipt_lines):
    total = 0
    for line in receipt_lines:
        rate = Decimal(LINE_RATE[line["line_category"]])
        total += round_half_up(Decimal(line["amount_cents"]) * rate)
    return total


# ------------------------------------------- ra_duty_load_score
def _ra_shifts(ra_id):
    return [s for s in store.all_rows("shifts") if s.get("assigned_ra_id") == ra_id]


def term_to_date_score(ra):
    current = store.now()
    term_start = store.parse_iso(TERM_START_UTC)
    total = 0
    for s in _ra_shifts(ra["id"]):
        if s["status"] not in ("COMPLETED", "MISSED"):
            continue
        start = store.parse_iso(s["start_at"])
        if not (term_start <= start < current):
            continue
        points = DUTY_POINTS[s["shift_type"]]
        total += points * MISSED_MULTIPLIER if s["status"] == "MISSED" else points
    return total


def forward_28_shifts(ra):
    current = store.now()
    horizon = current + store.days(FORWARD_WINDOW_DAYS)
    out = []
    for s in _ra_shifts(ra["id"]):
        if s["status"] not in ("ASSIGNED", "SWAP_PENDING", "CHECKED_IN"):
            continue
        start = store.parse_iso(s["start_at"])
        if current <= start < horizon:
            out.append(s)
    return out


def forward_28_score(ra):
    return sum(DUTY_POINTS[s["shift_type"]] for s in forward_28_shifts(ra))


# ------------------------------------------- conduct_sanction_points
def prior_sanctioned_count(case):
    return sum(
        1 for c in DB["conduct_cases"].values()
        if c["respondent_student_id"] == case["respondent_student_id"]
        and c["id"] != case["id"]
        and c["status"] == "SANCTIONED"
    )


def conduct_sanction_points(severity, priors):
    base = CONDUCT_BASE_POINTS[severity]
    multiplier = Decimal(1) + Decimal(REPEAT_STEP) * Decimal(priors)
    cap = Decimal(REPEAT_MULTIPLIER_CAP)
    if multiplier > cap:
        multiplier = cap
    return round_half_up(Decimal(base) * multiplier)


# ------------------------------------------- break_housing_capacity_projection
def colliding_break_holds(candidate):
    out = []
    for b in DB["breaks"].values():
        if b["room_id"] != candidate["room_id"] or b["id"] == candidate["id"]:
            continue
        if b["status"] not in ("APPROVED", "CHECKED_IN"):
            continue
        if b["start_date"] <= candidate["end_date"] and candidate["start_date"] <= b["end_date"]:
            out.append(b)
    return out
