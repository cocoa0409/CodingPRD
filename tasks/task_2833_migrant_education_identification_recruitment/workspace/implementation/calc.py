"""The eight named calculations of the specification.

Every one of them is a pure function of stored state plus the logical clock;
persistence of the results lives in flows.py and the route modules.
"""

import math
from datetime import timedelta
from decimal import Decimal

from store import store
from validation import add_months, add_years, parse_iso_date, round_half_up

ZERO = Decimal("0.00")

MOVE_BAND = {0: 0, 1: 18, 2: 26}

PLAN_WEIGHTS = {
    "SUPPLEMENTAL_INSTRUCTION": 4,
    "SUMMER_PROGRAM": 3,
    "OSY_ALTERNATIVE": 3,
    "CREDIT_ACCRUAL": 2,
}

BUDGET_PFS = Decimal("120.00")
BUDGET_NON_PFS = Decimal("75.00")

OPEN_PLAN_STATUSES = ("DRAFT", "ACTIVE")
LIVE_ASSIGNMENT_STATUSES = ("PLANNED", "ACTIVE")


# =========================================================================
# 1. priority for services  (pfs_priority_score)
# =========================================================================

def _ceil_blocks(days):
    return int(math.ceil(float(days) / 5.0)) if days else 0


def pfs_assessment(student):
    """Full derivation, including the components the active pathway drops."""
    clock_date = store.clock_date()
    window_start = clock_date - timedelta(days=365)
    recent = 0
    for move in store.moves.values():
        if move["student_id"] != student["id"]:
            continue
        if move["status"] != "VERIFIED":
            continue
        move_date = parse_iso_date(move["move_date"])
        if window_start <= move_date <= clock_date:
            recent += 1

    move_band_points = MOVE_BAND.get(recent, 30)
    interrupted = student.get("school_days_interrupted") or 0
    blocks = _ceil_blocks(interrupted)

    if student["schooling_status"] == "ENROLLED":
        variant = "INTERRUPTION_WEIGHTED"
        interruption_points = min(blocks * 4, 24)
        academic_points = 0
        if student.get("math_below_grade"):
            academic_points += 14
        if student.get("reading_below_grade"):
            academic_points += 14
        credit_points = min((student.get("credit_deficit") or 0) * 3, 18)
        credential_points = 0
        language_points = 0
        raw_score = move_band_points + interruption_points + academic_points + credit_points
        pfs_score = min(raw_score, 100)
        floor_applied = False
    else:
        variant = "OSY_PATHWAY"
        interruption_points = min(blocks * 6, 30)
        academic_points = 0
        credit_points = 0
        credential_points = 0 if student.get("has_hs_credential") else 20
        language_points = 10 if student.get("primary_language_not_english") else 0
        raw_score = move_band_points + interruption_points + credential_points + language_points
        floored = max(raw_score, 55)
        pfs_score = min(floored, 100)
        floor_applied = raw_score < 55

    return {
        "student_id": student["id"],
        "pfs_variant": variant,
        "pfs_score": pfs_score,
        "pfs_flag": pfs_score >= 60,
        "recent_verified_moves": recent,
        "move_band_points": move_band_points,
        "interruption_points": interruption_points,
        "academic_points": academic_points,
        "credential_points": credential_points,
        "language_points": language_points,
        "credit_points": credit_points,
        "raw_score": raw_score,
        "floor_applied": floor_applied,
    }


# =========================================================================
# 2. eligibility windows  (coe_eligibility_window)
# =========================================================================

def provisional_window_end(move_date):
    """36 calendar months after the move, stepped back one day; no age-out clip."""
    return add_months(parse_iso_date(move_date), 36) - timedelta(days=1)


def final_window(residency_date, birth_date):
    start = parse_iso_date(residency_date)
    uncapped_end = add_months(start, 36) - timedelta(days=1)
    age_out = add_years(parse_iso_date(birth_date), 22) - timedelta(days=1)
    end = age_out if age_out < uncapped_end else uncapped_end
    return start, end, age_out < uncapped_end


# =========================================================================
# 3. hour allocation  (service_hours_allocation)
# =========================================================================

def open_plans_for(student_id):
    rows = [
        plan for plan in store.plans.values()
        if plan["student_id"] == student_id and plan["status"] in OPEN_PLAN_STATUSES
    ]
    rows.sort(key=lambda p: (p["created_at"], p["id"]))
    return rows


def allocate_hours(student):
    """Rewrites priority_tier / allocated_hours / expected_service_hours.

    Returns the list of plans it touched (each of which must take a version
    increment).  Rounds every raw share BEFORE the shares are summed.
    """
    plans = open_plans_for(student["id"])
    if not plans:
        return []

    budget = BUDGET_PFS if student.get("pfs_flag") else BUDGET_NON_PFS
    tier = "PFS" if student.get("pfs_flag") else "NON_PFS"
    total_weight = sum(PLAN_WEIGHTS.get(plan["plan_type"], 0) for plan in plans)

    if total_weight == 0:
        for plan in plans:
            plan["priority_tier"] = tier
            plan["allocated_hours"] = ZERO
            plan["expected_service_hours"] = ZERO
        return plans

    shares = []
    for plan in plans:
        weight = Decimal(PLAN_WEIGHTS.get(plan["plan_type"], 0))
        shares.append(round_half_up(budget * weight / Decimal(total_weight)))

    residual = round_half_up(budget - sum(shares, ZERO))
    shares[0] = round_half_up(shares[0] + residual)

    for plan, share in zip(plans, shares):
        plan["priority_tier"] = tier
        plan["allocated_hours"] = share
        plan["expected_service_hours"] = share
    return plans


# =========================================================================
# 4. credit reconciliation  (transfer_credit_reconciliation)
# =========================================================================

def locally_accrued_credits(student_id):
    """Sum of credits_awarded over unreversed forward CREDIT_ACCRUAL sessions."""
    credit_plans = set(
        plan["id"] for plan in store.plans.values()
        if plan["student_id"] == student_id and plan["plan_type"] == "CREDIT_ACCRUAL"
    )
    total = ZERO
    for delivery in store.deliveries.values():
        if delivery["plan_id"] not in credit_plans:
            continue
        if delivery.get("reverses_delivery_id") is not None:
            continue
        if delivery.get("is_reversed"):
            continue
        total += delivery.get("credits_awarded") or ZERO
    return total


def cap_percentage(tier_key):
    if tier_key < Decimal("12.00"):
        return Decimal("0.50")
    if tier_key < Decimal("24.00"):
        return Decimal("0.35")
    return Decimal("0.25")


def reconcile_credits(student_id, reported_prior_credits):
    """The pinned six-step order; the tier is keyed on the PRE-cap total."""
    local_raw = locally_accrued_credits(student_id)          # step 1
    uncapped = Decimal(reported_prior_credits)               # step 2
    tier_key = local_raw + uncapped                          # step 3
    percentage = cap_percentage(tier_key)                    # step 4
    capped = percentage * tier_key
    accepted = round_half_up(uncapped if uncapped < capped else capped)   # step 5
    awarded_total = round_half_up(local_raw + accepted)      # step 6
    return {
        "locally_accrued_credits": round_half_up(local_raw),
        "uncapped_amount": uncapped,
        "tier_key": tier_key,
        "cap_percentage": percentage,
        "accepted_transfer": accepted,
        "awarded_total": awarded_total,
    }


# =========================================================================
# 5. quality-control sample selection  (qc_sample_selection)
# =========================================================================

def qc_candidates():
    rows = [
        coe for coe in store.coes.values()
        if coe["status"] == "SUBMITTED" and not coe.get("qc_hold_exempt")
    ]
    rows.sort(key=lambda c: (c["created_at"], c["id"]))
    return rows


def qc_sample(candidates):
    """Returns (target_n, selected list ordered by created_at ascending)."""
    count = len(candidates)
    target_n = max(int(math.ceil(count / 10.0)), 1)

    mandatory = [c for c in candidates if (c.get("risk_flag_count") or 0) >= 1]

    ranked = sorted(
        candidates,
        key=lambda c: (-(c.get("risk_flag_count") or 0), c["created_at"], c["id"]),
    )
    quota = ranked[:target_n]

    chosen_ids = set(c["id"] for c in mandatory) | set(c["id"] for c in quota)
    selected = [c for c in candidates if c["id"] in chosen_ids]
    return target_n, selected


def risk_flag_count(coe, move, student):
    flags = 0
    if move.get("work_type") == "FISHING":
        flags += 1
    for interview in store.interviews.values():
        if (interview["student_id"] == coe["student_id"]
                and interview["move_id"] == coe["move_id"]
                and interview["interview_kind"] == "INITIAL"
                and interview["outcome"] == "INCONCLUSIVE"):
            flags += 1
            break
    age = move.get("student_age_at_move")
    if move.get("worker_relationship") != "SELF" and age is not None and age >= 18:
        flags += 1
    return flags


# =========================================================================
# 6. coverage geometry  (area_coverage_occupancy)
# =========================================================================

def live_assignments(predicate):
    return [
        row for row in store.assignments.values()
        if row["status"] in LIVE_ASSIGNMENT_STATUSES and predicate(row)
    ]


def recruiter_conflict(recruiter_id, starts_on, ends_on):
    """Unbuffered inclusive pairwise interval intersection."""
    for row in live_assignments(lambda r: r["recruiter_id"] == recruiter_id):
        existing_start = parse_iso_date(row["starts_on"])
        existing_end = parse_iso_date(row["ends_on"])
        if starts_on <= existing_end and existing_start <= ends_on:
            return True
    return False


def peak_season_contained(area, starts_on, ends_on):
    peak_start = parse_iso_date(area["peak_season_start_date"])
    peak_end = parse_iso_date(area["peak_season_end_date"])
    return starts_on <= peak_start and ends_on >= peak_end


BUFFER = timedelta(days=3)


def peak_occupancy(area_id, starts_on, ends_on):
    """Largest number of three-day-buffered live intervals plus the candidate
    covering any single date of the candidate interval."""
    widened = []
    for row in live_assignments(lambda r: r["area_id"] == area_id):
        widened.append((
            parse_iso_date(row["starts_on"]) - BUFFER,
            parse_iso_date(row["ends_on"]) + BUFFER,
        ))
    peak = 0
    day = starts_on
    while day <= ends_on:
        count = 1  # the candidate itself
        for start, end in widened:
            if start <= day <= end:
                count += 1
        if count > peak:
            peak = count
        day = day + timedelta(days=1)
    return peak


def primary_slots_used(area_id):
    return len([
        row for row in store.assignments.values()
        if row["area_id"] == area_id
        and row["coverage_role"] == "PRIMARY"
        and row["status"] in LIVE_ASSIGNMENT_STATUSES
    ])


def active_assignment_count(recruiter_id):
    return len([
        row for row in store.assignments.values()
        if row["recruiter_id"] == recruiter_id
        and row["status"] in LIVE_ASSIGNMENT_STATUSES
    ])


# =========================================================================
# 7. eligibility term sweep helpers  (eligibility_term_sweep)
# =========================================================================

SWEEP_STATUSES = ("ACTIVE", "EXPIRING", "EXPIRED")


def sweep_batch():
    rows = [term for term in store.terms.values() if term["status"] in SWEEP_STATUSES]
    rows.sort(key=lambda t: (t["term_end_on"], t["created_at"], t["id"]))
    return rows


# =========================================================================
# 8. delivery ledger  (student_service_hours_ledger)
# =========================================================================

def plan_delivered_hours(plan_id):
    total = ZERO
    for delivery in store.deliveries.values():
        if delivery["plan_id"] != plan_id:
            continue
        if delivery.get("reverses_delivery_id") is not None:
            continue
        if delivery.get("is_reversed"):
            continue
        total += delivery.get("hours") or ZERO
    return round_half_up(total)


def student_ledger_hours(student_id):
    total = ZERO
    for plan in store.plans.values():
        if plan["student_id"] == student_id:
            total += plan.get("delivered_hours") or ZERO
    return round_half_up(total)


def derive_service_status(student_id):
    plans = [plan for plan in store.plans.values() if plan["student_id"] == student_id]
    if not plans:
        return "UNSERVED"
    if any(plan["status"] == "ACTIVE" for plan in plans):
        return "RECEIVING_SERVICES"
    if any(plan["status"] == "DRAFT" for plan in plans):
        return "PLAN_DRAFTED"
    return "EXITED"
