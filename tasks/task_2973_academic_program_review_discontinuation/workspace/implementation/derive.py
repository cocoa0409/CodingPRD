"""The six calculations of the PRD and the rounding discipline of 2.7.

Every derived figure in this API is recomputed from scratch from raw rows, so
no derived value is ever stored, patched incrementally or allowed to go stale.
"""

from decimal import Decimal, ROUND_CEILING, ROUND_DOWN, ROUND_HALF_UP

from store import db, days, now

# --------------------------------------------------------------------------
# rounding disciplines (PRD 2.7)
# --------------------------------------------------------------------------

TWO = Decimal("0.01")
ONE = Decimal("1")


def half_up_cents(value):
    """Money: round half up, applied exactly once, to whole cents."""
    return int(Decimal(value).quantize(ONE, rounding=ROUND_HALF_UP))


def half_up_2(value):
    """FTE and composite score: two decimals, round half up, applied once."""
    return Decimal(value).quantize(TWO, rounding=ROUND_HALF_UP)


def round_up_int(value):
    """Counts of terms and seats: round up to the next whole number."""
    return int(Decimal(value).quantize(ONE, rounding=ROUND_CEILING))


def truncate_cents(value):
    """The severance budget ceiling: truncated downward."""
    return int(Decimal(value).quantize(ONE, rounding=ROUND_DOWN))


def clamp(value, low, high):
    if value < low:
        return Decimal(low)
    if value > high:
        return Decimal(high)
    return value


def f2(value):
    """A two-decimal Decimal rendered as a JSON number."""
    if value is None:
        return None
    return float(half_up_2(value))


# --------------------------------------------------------------------------
# constants
# --------------------------------------------------------------------------

DEGREE_WEIGHTS = {
    # enrollment, completion, demand, efficiency
    "UNDERGRADUATE": (Decimal("0.35"), Decimal("0.25"), Decimal("0.20"), Decimal("0.20")),
    "GRADUATE": (Decimal("0.25"), Decimal("0.30"), Decimal("0.15"), Decimal("0.30")),
    "CERTIFICATE": (Decimal("0.30"), Decimal("0.20"), Decimal("0.35"), Decimal("0.15")),
}

ENROLLMENT_GAIN = Decimal("2.5")
ENROLLMENT_BASE = Decimal("50")
COMPLETION_SCALE = Decimal("250")
COST_BENCHMARK_CENTS = Decimal("50000")
EFFICIENCY_GAIN = Decimal("60")
SMALL_PROGRAM_HEADCOUNT = 60
SMALL_PROGRAM_CAP = Decimal("39.99")

SECTIONS_PER_FTE = Decimal("6")
SEVERANCE_RATE = Decimal("0.15")
CREDITS_PER_SEAT = Decimal("3")

TENURE_TIER_RANK = {
    "ADJUNCT": 1,
    "NON_TENURE_TRACK": 2,
    "TENURE_TRACK": 3,
    "TENURED": 4,
}
STATUTORY_NOTICE_DAYS = {
    "TENURED": 365,
    "TENURE_TRACK": 180,
    "NON_TENURE_TRACK": 90,
    "ADJUNCT": 30,
}
AGENCY_NOTICE_DAYS = {"ACCREDITOR": 30, "STATE_AGENCY": 45, "FEDERAL": 60}

ACTIVE_FTE_STATES = ("ASSIGNED", "TEACH_OUT_RETAINED", "REASSIGNMENT_PROPOSED",
                     "NOTICE_ISSUED")
PLAN_STATES_DEMANDING_SECTIONS = ("DRAFT", "SUBMITTED", "APPROVED", "IN_EFFECT")
GUARANTEE_SUPPLY_STATUSES = ("PLANNED", "OFFERED", "SUBSTITUTED")
OPEN_ADVISING_STATUSES = ("PENDING", "ADVISED", "PLAN_SIGNED")
UNACKNOWLEDGED_STATUSES = ("PENDING", "SENT", "OVERDUE")


# --------------------------------------------------------------------------
# child collections
# --------------------------------------------------------------------------

def snapshots_of(program_id):
    rows = [s for s in db.snapshots.values() if s["program_id"] == program_id]
    return sorted(rows, key=lambda s: s["term_index"])


def rolling_window(program_id):
    """The three observations with the highest term_index, ascending."""
    ordered = snapshots_of(program_id)
    return ordered[-3:]


def appointments_of(program_id):
    return [a for a in db.appointments.values() if a["program_id"] == program_id]


def plans_of(program_id):
    return [p for p in db.plans.values() if p["program_id"] == program_id]


def guarantees_of(plan_id):
    return [g for g in db.guarantees.values() if g["teach_out_plan_id"] == plan_id]


def students_of(plan_id):
    return [s for s in db.students.values() if s["teach_out_plan_id"] == plan_id]


def notifications_of(decision_id):
    return [n for n in db.notifications.values() if n["decision_id"] == decision_id]


def decisions_of(cycle_id):
    return [d for d in db.decisions.values() if d["cycle_id"] == cycle_id]


def visits_of(cycle_id):
    return [v for v in db.visits.values() if v["cycle_id"] == cycle_id]


def reports_of(visit_id):
    rows = [r for r in db.reports.values() if r["visit_id"] == visit_id]
    return sorted(rows, key=lambda r: r["sequence_number"])


def self_study_of(cycle_id):
    for s in db.self_studies.values():
        if s["cycle_id"] == cycle_id:
            return s
    return None


# --------------------------------------------------------------------------
# seat ledger primitives (PRD 2.11 conservation)
# --------------------------------------------------------------------------

def guarantee_committed(guarantee_id):
    total = 0
    for (gid, _sid), seats in db.holdings.items():
        if gid == guarantee_id:
            total += seats
    return total


def student_committed(student_id):
    total = 0
    for (_gid, sid), seats in db.holdings.items():
        if sid == student_id:
            total += seats
    return total


def holding(guarantee_id, student_id):
    return db.holdings.get((guarantee_id, student_id), 0)


def release_all_holdings(student_id):
    for key in [k for k in db.holdings if k[1] == student_id]:
        del db.holdings[key]


# --------------------------------------------------------------------------
# calculation 1: dual-variant cost accounting (PRD 3.1)
# --------------------------------------------------------------------------

def snapshot_cost_per_credit_hour(snapshot):
    if snapshot["credit_hours"] == 0:
        return None
    return half_up_cents(
        Decimal(snapshot["direct_cost_cents"]) / Decimal(snapshot["credit_hours"])
    )


def cost_figures(program_id):
    window = rolling_window(program_id)
    if not window:
        return None, None
    cost_sum = sum(s["direct_cost_cents"] for s in window)
    hours_sum = sum(s["credit_hours"] for s in window)
    rolling = None
    if hours_sum != 0:
        rolling = half_up_cents(Decimal(cost_sum) / Decimal(hours_sum))
    newest = window[-1]
    latest = None
    if newest["credit_hours"] != 0:
        latest = half_up_cents(
            Decimal(newest["direct_cost_cents"]) / Decimal(newest["credit_hours"])
        )
    return rolling, latest


# --------------------------------------------------------------------------
# calculation 2: composite score and viability band (PRD 3.2)
# --------------------------------------------------------------------------

def band_for(score):
    if score is None:
        return "INSUFFICIENT_DATA"
    if score >= Decimal("60.00"):
        return "CONTINUE_ELIGIBLE"
    if score >= Decimal("40.00"):
        return "IMPROVEMENT_ELIGIBLE"
    return "NONVIABLE"


def composite_score(program):
    window = rolling_window(program["id"])
    if not window:
        return None, "INSUFFICIENT_DATA"

    oldest = window[0]
    newest = window[-1]

    base_heads = Decimal(oldest["enrollment_headcount"])
    latest_heads = Decimal(newest["enrollment_headcount"])
    if base_heads == 0:
        enrollment = Decimal("100") if latest_heads > 0 else ENROLLMENT_BASE
    else:
        trend_pct = (latest_heads - base_heads) / base_heads * Decimal("100")
        enrollment = clamp(ENROLLMENT_BASE + ENROLLMENT_GAIN * trend_pct, 0, 100)

    heads_sum = sum(s["enrollment_headcount"] for s in window)
    completions_sum = sum(s["completions_count"] for s in window)
    if heads_sum == 0:
        completion = Decimal("0") if completions_sum == 0 else Decimal("100")
    else:
        completion = clamp(
            COMPLETION_SCALE * Decimal(completions_sum) / Decimal(heads_sum), 0, 100
        )

    demand = clamp(Decimal(newest["market_demand_index"]), 0, 100)

    rolling, _latest = cost_figures(program["id"])
    if rolling is None:
        efficiency = Decimal("0")
    elif rolling == 0:
        efficiency = Decimal("100")
    else:
        efficiency = clamp(
            EFFICIENCY_GAIN * (COST_BENCHMARK_CENTS / Decimal(rolling)), 0, 100
        )

    weights = DEGREE_WEIGHTS[program["degree_level"]]
    weighted = (weights[0] * enrollment + weights[1] * completion
                + weights[2] * demand + weights[3] * efficiency)

    if heads_sum < SMALL_PROGRAM_HEADCOUNT and weighted > SMALL_PROGRAM_CAP:
        weighted = SMALL_PROGRAM_CAP

    score = half_up_2(weighted)
    return score, band_for(score)


# --------------------------------------------------------------------------
# calculation 4: staffing reduction waterfall (PRD 3.11)
# --------------------------------------------------------------------------

def guaranteed_section_count(program_id):
    live_plan_ids = set(
        p["id"] for p in plans_of(program_id)
        if p["state"] in PLAN_STATES_DEMANDING_SECTIONS
    )
    count = 0
    for g in db.guarantees.values():
        if g["teach_out_plan_id"] in live_plan_ids:
            if g["status"] in GUARANTEE_SUPPLY_STATUSES:
                count += 1
    return count


def fte_sum(rows):
    total = Decimal("0")
    for row in rows:
        total += row["fte"]
    return half_up_2(total)


def notice_pay_for(appointment):
    statutory = STATUTORY_NOTICE_DAYS[appointment["tenure_status"]]
    return half_up_cents(
        Decimal(appointment["annual_salary_cents"]) * appointment["fte"]
        * Decimal(statutory) / Decimal("365")
    )


def waterfall(program):
    """Steps 1 through 4, in the fixed order the PRD pins."""
    program_id = program["id"]
    roster = appointments_of(program_id)

    baseline = fte_sum(roster)
    active = fte_sum([a for a in roster if a["state"] in ACTIVE_FTE_STATES])
    reassigned = fte_sum([a for a in roster if a["state"] == "REASSIGNED"])
    separated = fte_sum([a for a in roster if a["state"] == "SEPARATED"])

    # step 1: instructional demand that must survive the reduction
    sections = guaranteed_section_count(program_id)
    retained = half_up_2(Decimal(sections) / SECTIONS_PER_FTE)
    if retained > baseline:
        retained = baseline

    # step 2: the unshielded pool
    assigned = [a for a in roster if a["state"] == "ASSIGNED"]
    assigned_pool = fte_sum(assigned)
    reducible = assigned_pool - retained
    if reducible < 0:
        reducible = Decimal("0.00")

    # step 3: the money
    window = rolling_window(program_id)
    window_cost = sum(s["direct_cost_cents"] for s in window)
    cap = truncate_cents(SEVERANCE_RATE * Decimal(window_cost))

    # step 4: the walk
    notice_pay = {}
    for appointment in roster:
        notice_pay[appointment["id"]] = notice_pay_for(appointment)

    ordered = sorted(
        assigned,
        key=lambda a: (TENURE_TIER_RANK[a["tenure_status"]], -a["fte"],
                       a["created_at"], a["_seq"]),
    )

    positions = dict((a["id"], None) for a in roster)
    running_fte = Decimal("0")
    running_liability = 0
    position = 1
    for appointment in ordered:
        if running_fte >= reducible:
            break
        pay = notice_pay[appointment["id"]]
        if running_liability + pay > cap:
            break
        positions[appointment["id"]] = position
        position += 1
        running_fte += appointment["fte"]
        running_liability += pay

    deferred = reducible - running_fte
    if deferred < 0:
        deferred = Decimal("0")

    return {
        "faculty_fte_baseline": baseline,
        "active_fte_total": active,
        "reassigned_fte_total": reassigned,
        "separated_fte_total": separated,
        "assigned_pool_fte": assigned_pool,
        "retained_teach_out_fte": retained,
        "reducible_fte": reducible,
        "severance_budget_cap_cents": cap,
        "staffing_liability_cents": running_liability,
        "deferred_fte": half_up_2(deferred),
        "notice_pay": notice_pay,
        "positions": positions,
        "guaranteed_section_count": sections,
    }


def deferred_fte(program):
    return waterfall(program)["deferred_fte"]


def appointment_position(appointment):
    program = db.programs.get(appointment["program_id"])
    if program is None:
        return None
    return waterfall(program)["positions"].get(appointment["id"])


# --------------------------------------------------------------------------
# calculation 3: dual-variant student projection (PRD 3.10)
# --------------------------------------------------------------------------

def student_projection(student):
    plan = db.plans.get(student["teach_out_plan_id"])
    status = student["advising_status"]
    if status == "PENDING":
        variant = "OPTIMISTIC_FULL_LOAD"
        load = student["max_credits_per_term"]
    else:
        variant = "CONSERVATIVE_ADVISED_LOAD"
        load = student["advised_credits_per_term"]
        if load is None:
            # never advised: the last computed projection is the optimistic one
            load = student["max_credits_per_term"]

    credits = Decimal(student["credits_remaining"])
    terms = round_up_int(credits / Decimal(load))
    completion = None
    if terms > 0 and plan is not None:
        completion = plan["first_teach_out_term_index"] + terms - 1
    at_risk = False
    if completion is not None and plan is not None:
        at_risk = completion > plan["final_award_term_index"]
    seats = round_up_int(credits / CREDITS_PER_SEAT)
    return {
        "projection_variant": variant,
        "projected_terms_remaining": terms,
        "projected_completion_term_index": completion,
        "at_risk": at_risk,
        "required_seat_count": seats,
    }


# --------------------------------------------------------------------------
# calculation 6: the plan's seat ledger (PRD 3.9)
# --------------------------------------------------------------------------

def plan_ledger(plan):
    guarantees = guarantees_of(plan["id"])
    students = students_of(plan["id"])

    guaranteed_total = sum(
        g["seats_guaranteed"] for g in guarantees
        if g["status"] in GUARANTEE_SUPPLY_STATUSES
    )
    committed_total = sum(
        guarantee_committed(g["id"]) for g in guarantees if g["status"] != "WAIVED"
    )

    open_students = [s for s in students
                     if s["advising_status"] in OPEN_ADVISING_STATUSES]
    required_total = 0
    at_risk_count = 0
    for student in open_students:
        projection = student_projection(student)
        required_total += projection["required_seat_count"]
        if projection["at_risk"]:
            at_risk_count += 1

    shortfall = required_total - guaranteed_total
    if shortfall < 0:
        shortfall = 0

    return {
        "guaranteed_seat_total": guaranteed_total,
        "committed_seat_total": committed_total,
        "required_seat_total": required_total,
        "seat_shortfall": shortfall,
        "at_risk_student_count": at_risk_count,
        "open_student_count": len(open_students),
        "substituted_guarantee_count": len(
            [g for g in guarantees if g["status"] == "SUBSTITUTED"]),
        "waived_guarantee_count": len(
            [g for g in guarantees if g["status"] == "WAIVED"]),
    }


# --------------------------------------------------------------------------
# calculation 5: agency notice deadline and compliance counters (PRD 3.7)
# --------------------------------------------------------------------------

def notice_due_at(decision, agency_type):
    anchor = decision.get("ratified_at") or now()
    return anchor + days(AGENCY_NOTICE_DAYS[agency_type])


def notification_counters(decision):
    rows = notifications_of(decision["id"])
    live = [n for n in rows if n["status"] != "VOIDED"]
    unacknowledged = [n for n in live if n["status"] in UNACKNOWLEDGED_STATUSES]
    return len(live), len(unacknowledged)


def compliance_posture(cycle):
    live = []
    for decision in decisions_of(cycle["id"]):
        live.extend([n for n in notifications_of(decision["id"])
                     if n["status"] != "VOIDED"])
    if not live:
        return "NOT_APPLICABLE"
    for notification in live:
        if notification["status"] != "ACKNOWLEDGED":
            return "NOTICES_PENDING"
    return "NOTICES_CLEARED"
