"""Business logic: derived state, calculations, cascades (PRD section 3)."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import STORE, new_record, bump
from helpers import date_obj, age_years, add_months

# ---- Calculation constants (SCAFFOLD 1.3 / PRD 3, verbatim) ----
AGE_MIN_YEARS = 16
AGE_MAX_YEARS = 24
INCOME_BASE_CENTS = 1500000
INCOME_PER_MEMBER_CENTS = 500000
HOUSEHOLD_SIZE_MAX = 12
BARRIER_MIN_COUNT = 1

TRADE_WEIGHT = Decimal("0.5")
CAPACITY_WEIGHT = Decimal("0.3")
GEO_WEIGHT = Decimal("0.2")
SEAT_SCORE_CAP = 10
BED_SCORE_CAP = 10
GEO_MATCH_POINTS = 10

ROLLING_WINDOW_DAYS = 90
BOARD_REVIEW_THRESHOLD_POINTS = 10
SANCTION_POINTS_MIN = 1
SANCTION_POINTS_MAX = 5

MAX_DAILY_HOURS = 10
WBL_COMPLETION_MIN_HOURS = 120
MAX_SUPERVISION_ACTIVE = 3

TRANSPORT_T1_MAX_MILES = 25
TRANSPORT_T1_CENTS = 2500
TRANSPORT_T2_MAX_MILES = 100
TRANSPORT_T2_CENTS = 7500
TRANSPORT_T3_CENTS = 15000
HOUSING_STIPEND_CENTS = 50000
TRANSITION_WINDOW_MONTHS = 12

GRADUATION_RATE_FLOOR = Decimal("0.6")
PLACEMENT_RATE_FLOOR = Decimal("0.7")
PER_GRADUATE_BASE_CENTS = 200000
WAGE_REFERENCE_CENTS = 150000
WAGE_RATIO_CAP = Decimal("2.0")

ZERO_TOLERANCE_CODES = {"VIOLENCE", "DRUGS", "WEAPONS"}
TRAINING_TERMINAL = {"COMPLETED", "UNENROLLED", "SEPARATED"}
APPLICATION_NONTERMINAL = {"SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED"}


def q(value, places):
    return value.quantize(Decimal(places), rounding=ROUND_HALF_UP)


# ---- Derived: trade program seats / status ----
def program_enrolled_count(program_id):
    return sum(
        1
        for e in STORE.enrollments.values()
        if e["trade_program_id"] == program_id
        and e["training_status"] in ("REMEDIATION", "TRAINING")
    )


def program_open_seats(program):
    return program["capacity"] - program_enrolled_count(program["id"])


def program_status(program):
    if program["_closed"]:
        return "CLOSED"
    return "FULL" if program_open_seats(program) <= 0 else "OPEN"


# ---- Derived: center beds ----
def center_beds_in_use(center_id):
    n = 0
    for d in STORE.dormitory_assignments.values():
        if d["status"] != "ACTIVE":
            continue
        e = STORE.enrollments.get(d["enrollment_id"])
        if e is None:
            continue
        p = STORE.trade_programs.get(e["trade_program_id"])
        if p is not None and p["center_id"] == center_id:
            n += 1
    return n


# ---- Derived: conduct hold (recomputed after incident transitions, on read) ----
def recompute_conduct_hold(enrollment_id):
    e = STORE.enrollments.get(enrollment_id)
    if e is None:
        return
    today = STORE.clock_date()
    window_start = today - timedelta(days=ROLLING_WINDOW_DAYS)
    points = 0
    board = False
    for i in STORE.conduct_incidents.values():
        if i["enrollment_id"] != enrollment_id:
            continue
        if i["status"] == "BOARD_REVIEW":
            board = True
        if i["status"] == "SANCTIONED" and i.get("sanction_points"):
            occurred = date_obj(i["occurred_at"])
            if window_start <= occurred <= today:
                points += i["sanction_points"]
    e["conduct_hold"] = board or points >= BOARD_REVIEW_THRESHOLD_POINTS


# ---- Derived: employer agreement status ----
def agreement_status(agreement):
    today = STORE.clock_date_str()
    if agreement["effective_start"] <= today <= agreement["effective_end"]:
        return "ACTIVE"
    return "EXPIRED"


# ---- Derived: transition plan status / money fields ----
def plan_status(plan):
    tracks = (
        plan["job_placement_status"],
        plan["housing_status"],
        plan["transportation_status"],
    )
    if all(t in ("COMPLETED", "WAIVED") for t in tracks):
        return "COMPLETED"
    if STORE.clock_date_str() > plan["expires_at"]:
        return "EXPIRED"
    return "ACTIVE"


def plan_housing_stipend(plan):
    return HOUSING_STIPEND_CENTS if plan["housing_status"] == "COMPLETED" else 0


def plan_transport_allowance(plan):
    if plan["transportation_status"] != "COMPLETED":
        return 0
    d = plan.get("_transport_distance")
    if d is None:
        return 0
    d = Decimal(str(d))
    if d <= TRANSPORT_T1_MAX_MILES:
        return TRANSPORT_T1_CENTS
    if d <= TRANSPORT_T2_MAX_MILES:
        return TRANSPORT_T2_CENTS
    return TRANSPORT_T3_CENTS


# ---- Prerequisite evaluation ----
def _verified_types_for_enrollment(enrollment_id):
    return {
        c["credential_type"]
        for c in STORE.credentials.values()
        if c["enrollment_id"] == enrollment_id and c["status"] == "VERIFIED"
    }


def prereqs_met_for_enrollment(enrollment):
    program = STORE.trade_programs[enrollment["trade_program_id"]]
    held = _verified_types_for_enrollment(enrollment["id"])
    return all(t in held for t in program["required_credential_types"])


def prereqs_met_for_applicant(applicant_id, program):
    """A credential counts when it belongs to an enrollment of this applicant
    and its status is VERIFIED."""
    enrollment_ids = {
        e["id"] for e in STORE.enrollments.values() if e["applicant_id"] == applicant_id
    }
    held = {
        c["credential_type"]
        for c in STORE.credentials.values()
        if c["enrollment_id"] in enrollment_ids and c["status"] == "VERIFIED"
    }
    return all(t in held for t in program["required_credential_types"])


# ---- calculations.eligibility_determination ----
def run_determination(application, applicant):
    age = age_years(applicant["date_of_birth"], STORE.clock_date())
    income_limit = INCOME_BASE_CENTS + (application["household_size"] - 1) * INCOME_PER_MEMBER_CENTS
    reasons = []
    if age < AGE_MIN_YEARS or age > AGE_MAX_YEARS:
        reasons.append("AGE_OUT_OF_RANGE")
    if application["annual_income_cents"] > income_limit:
        reasons.append("INCOME_EXCEEDS_LIMIT")
    if len(application["barrier_flags"]) < BARRIER_MIN_COUNT:
        reasons.append("NO_BARRIER_DOCUMENTED")
    application["determination_reasons"] = reasons
    application["determined_at"] = STORE.clock_ts()
    application["status"] = "ELIGIBLE" if not reasons else "INELIGIBLE"


# ---- calculations.center_assignment_ranking ----
def rank_centers(applicant, residential_track):
    candidates = []
    for c in STORE.centers.values():
        quals = [
            t
            for t in STORE.trade_programs.values()
            if t["center_id"] == c["id"]
            and t["trade_code"] == applicant["desired_trade_code"]
            and program_status(t) == "OPEN"
            and program_open_seats(t) >= 1
        ]
        if not quals:
            continue
        beds_available = c["total_beds"] - center_beds_in_use(c["id"])
        if residential_track and beds_available < 1:
            continue
        trade_points = min(max(program_open_seats(t) for t in quals), SEAT_SCORE_CAP)
        capacity_points = min(beds_available, BED_SCORE_CAP)
        geo_points = GEO_MATCH_POINTS if c["region_code"] == applicant["home_region_code"] else 0
        score = q(
            TRADE_WEIGHT * trade_points
            + CAPACITY_WEIGHT * capacity_points
            + GEO_WEIGHT * geo_points,
            "0.01",
        )
        candidates.append(
            {
                "center": c,
                "score": score,
                "trade_points": trade_points,
                "capacity_points": capacity_points,
                "geo_points": geo_points,
                "beds_available": beds_available,
            }
        )
    candidates.sort(
        key=lambda r: (-r["score"], -r["beds_available"], r["center"]["_seq"])
    )
    return candidates


# ---- Enrollment terminal cascade (complete / unenroll / separate / board) ----
def create_transition_plan(enrollment, hire_inherit):
    today = STORE.clock_date_str()
    plan = new_record()
    plan.update(
        {
            "enrollment_id": enrollment["id"],
            "separation_date": today,
            "expires_at": add_months(today, TRANSITION_WINDOW_MONTHS),
            "job_placement_status": "PENDING",
            "housing_status": "PENDING",
            "transportation_status": "PENDING",
            "job_starting_wage_cents": None,
            "_transport_distance": None,
        }
    )
    if hire_inherit:
        hires = [
            w
            for w in STORE.wbl_placements.values()
            if w["enrollment_id"] == enrollment["id"]
            and w["status"] == "COMPLETED"
            and w.get("converted_to_hire") is True
        ]
        if hires:
            hires.sort(key=lambda w: w["_seq"])
            plan["job_placement_status"] = "COMPLETED"
            plan["job_starting_wage_cents"] = hires[0]["hire_wage_cents"]
    STORE.transition_plans[plan["id"]] = plan
    return plan


def finalize_enrollment_terminal(enrollment, new_status, reason, make_plan, hire_inherit):
    """Depth-3 cascade: enrollment -> dormitory rows + program seat + WBL
    placements -> center occupancy; applicant flips to RELEASED."""
    today = STORE.clock_date_str()
    enrollment["training_status"] = new_status
    enrollment["exit_date"] = today
    enrollment["exit_reason"] = reason
    enrollment["residential_status"] = "RELEASED"
    bump(enrollment)
    for d in STORE.dormitory_assignments.values():
        if d["enrollment_id"] == enrollment["id"] and d["status"] == "ACTIVE":
            d["status"] = "TERMINATED"
            d["move_out_date"] = today
            bump(d)
    for w in STORE.wbl_placements.values():
        if w["enrollment_id"] == enrollment["id"] and w["status"] == "ACTIVE":
            w["status"] = "TERMINATED"
            bump(w)
    applicant = STORE.applicants.get(enrollment["applicant_id"])
    if applicant is not None:
        applicant["assignment_status"] = "RELEASED"
        bump(applicant)
    if make_plan:
        create_transition_plan(enrollment, hire_inherit)


# ---- calculations.performance_rate + operator_performance_payment ----
def performance_calc(contract, variant):
    """variant: 'FINAL' or 'PROVISIONAL'. Returns Decimals for rates plus
    integer money fields; serialization converts."""
    today = STORE.clock_date_str()
    period_start = contract["current_period_start"]
    enrollments = [
        e
        for e in STORE.enrollments.values()
        if STORE.trade_programs[e["trade_program_id"]]["center_id"] == contract["center_id"]
    ]
    cohort = [
        e
        for e in enrollments
        if e["exit_date"] is not None and period_start <= e["exit_date"] <= today
    ]
    graduates = [e for e in cohort if e["training_status"] == "COMPLETED"]
    leavers = [e for e in cohort if e["training_status"] in ("SEPARATED", "UNENROLLED")]
    plans = {p["enrollment_id"]: p for p in STORE.transition_plans.values()}
    placed = [
        e
        for e in graduates
        if plans.get(e["id"]) is not None
        and plans[e["id"]]["job_placement_status"] == "COMPLETED"
    ]
    actives = [
        e for e in enrollments if e["training_status"] in ("REMEDIATION", "TRAINING")
    ]
    g, l, a, pl = len(graduates), len(leavers), len(actives), len(placed)
    if variant == "FINAL":
        grad_rate = q(Decimal(g) / Decimal(g + l), "0.0001") if (g + l) else Decimal("0.0")
    else:
        grad_rate = (
            q(Decimal(g + a) / Decimal(g + l + a), "0.0001") if (g + l + a) else Decimal("0.0")
        )
    place_rate = q(Decimal(pl) / Decimal(g), "0.0001") if g else Decimal("0.0")
    wages = [
        (plans[e["id"]]["job_starting_wage_cents"] or 0) for e in placed
    ]
    if wages:
        avg_wage = int(q(Decimal(sum(wages)) / Decimal(len(wages)), "1"))
    else:
        avg_wage = 0
    # Pinned order: round each per-graduate award to whole cents, then sum.
    payment = 0
    for w in wages:
        ratio = Decimal(w) / Decimal(WAGE_REFERENCE_CENTS)
        if ratio > WAGE_RATIO_CAP:
            ratio = WAGE_RATIO_CAP
        payment += int(q(Decimal(PER_GRADUATE_BASE_CENTS) * ratio, "1"))
    return {
        "period_start": period_start,
        "period_end": today,
        "graduates_count": g,
        "leavers_count": l,
        "projected_actives_count": a,
        "graduation_rate": grad_rate,
        "placement_rate": place_rate,
        "avg_starting_wage_cents": avg_wage,
        "payment_cents": payment,
    }
