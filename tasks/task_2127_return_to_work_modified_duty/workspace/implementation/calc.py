"""Every calculation in the program (PRD 3.x). All money is whole cents and
every rounding step happens exactly where the specification places it."""
from decimal import Decimal
import math

from store import db, ordered
from util import D, rhu, rhu_int, rhu_f, clamp, dec_floor, parse_date, days_between

# ---------------------------------------------------------------- constants
LIFT_REFERENCE_LBS = D(50)
STANDING_REFERENCE_MINUTES = D(120)
HOURS_REFERENCE_PER_DAY = D(8)

WEIGHT_LIFT = D("0.35")
WEIGHT_STANDING = D("0.20")
WEIGHT_HOURS = D("0.25")
WEIGHT_KEYBOARD = D("0.10")
WEIGHT_RISK = D("0.10")
RISK_CLASS_PENALTY = {"LOW": D("0.0"), "MEDIUM": D("0.35"), "HIGH": D("0.75")}
SEVERITY_DAMPING_PIVOT = D(60)
MIN_ELIGIBLE_MATCH_SCORE = D("40.0")
RISK_CLASS_RANK = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}

RISK_BASE_BY_JOB_RISK_CLASS = {"LOW": D(12), "MEDIUM": D(28), "HIGH": D(46)}
RISK_SEVERITY_WEIGHT = D("0.45")
RISK_HEADROOM_WEIGHT = D("22.0")
COMPLIANCE_SEVERITY_POINTS = {"NONE": D(0), "MINOR": D(4), "MAJOR": D(11),
                              "CRITICAL": D(25)}
REINJURY_SEVERITY_POINTS = {"NEAR_MISS": 6, "MINOR": 14, "SIGNIFICANT": 26,
                            "SEVERE": 40}
AUDIT_DECAY_PER_30_DAYS = D("0.5")
RISK_ESCALATION_THRESHOLD = 70

STATUTORY_REPLACEMENT_RATE = D("0.6667")
WORKDAYS_PER_WEEK = D(5)
TIER1_MAX_WEEKS = 8
TIER2_MAX_WEEKS = 16
TIER1_MULTIPLIER = D("1.00")
TIER2_MULTIPLIER = D("0.90")
TIER3_MULTIPLIER = D("0.80")
WEEKLY_DIFFERENTIAL_CAP_CENTS = D(90000)
BENEFIT_OFFSET_RATE = D("0.05")

MONTHLY_PREMIUM_BY_TIER_CENTS = {"TIER_A": D(68000), "TIER_B": D(52000),
                                 "TIER_C": D(41000)}
BASE_EMPLOYEE_CONTRIBUTION_RATE = D("0.28")
SUBSIDY_T1_UPTO_CENTS = D(38000)
SUBSIDY_T2_UPTO_CENTS = D(55000)
SUBSIDY_FACTOR_T1 = D("0.90")
SUBSIDY_FACTOR_T2 = D("0.70")
SUBSIDY_FACTOR_T3 = D("0.55")
PREMIUM_WEEKS_PER_MONTH = D(4)

DURATION_SOFT_CAP_DAYS = 90
DURATION_HARD_CAP_DAYS = 180
PROGRESSION_REVIEW_INTERVAL_DAYS = 30

PROGRESSION_HOURS_STEP = D(1)
PROGRESSION_LIFT_STEP_PCT = D("0.25")
MAX_PROGRESSION_STEPS = 4
MAX_REVIEW_DEFERRALS = 2
REVIEW_DEFERRAL_DAYS = 14

CASE_REVIEW_MAJORITY = D("0.6600")
CASE_REVIEW_MODIFY_HOURS_FACTOR = D("0.5")
CASE_REVIEW_MODIFY_FOLLOWUP_DAYS = 14
COMPLIANCE_STRIKE_POINTS = {"NONE": 0, "MINOR": 0, "MAJOR": 1, "CRITICAL": 2}
COMPLIANCE_STRIKE_SUSPENSION_THRESHOLD = 2

TRAINING_EXPIRY_WARNING_DAYS = 30
SEAT_CHANGEOVER_BUFFER_DAYS = 1

DEFAULT_WINDOW_START = "1970-01-01"
DEFAULT_WINDOW_END = "2999-12-31"

SEAT_HOLDING_STATUSES = ("ADJUSTER_PENDING", "ACTIVE", "PROGRESSION_HOLD")
LIVE_PLACEMENT_STATUSES = ("PROPOSED", "ADJUSTER_PENDING", "ACTIVE",
                           "PROGRESSION_HOLD", "SUSPENDED")
DURATION_STATUSES = ("ACTIVE", "PROGRESSION_HOLD", "SUSPENDED", "COMPLETED",
                     "TERMINATED_EARLY")


# ------------------------------------------------------- collection helpers
def placements_of_claim(claim_id):
    return ordered([p for p in db.placements.values()
                    if p["claim_id"] == claim_id])


def placements_of_job(job_id):
    return ordered([p for p in db.placements.values()
                    if p["transitional_job_id"] == job_id])


def placements_of_restriction_set(rs_id):
    return ordered([p for p in db.placements.values()
                    if p["restriction_set_id"] == rs_id])


def placements_of_supervisor(supervisor_id):
    return ordered([p for p in db.placements.values()
                    if p["supervisor_id"] == supervisor_id])


def audits_of_placement(placement_id):
    return ordered([a for a in db.audits.values()
                    if a["placement_id"] == placement_id])


def reinjury_reports_of_placement(placement_id):
    return ordered([r for r in db.reinjury_reports.values()
                    if r["placement_id"] == placement_id])


def directives_of_placement(placement_id):
    return ordered([d for d in db.directives.values()
                    if d["placement_id"] == placement_id])


def reviews_of_placement(placement_id):
    return ordered([r for r in db.progression_reviews.values()
                    if r["placement_id"] == placement_id])


def case_reviews_of_placement(placement_id):
    return ordered([c for c in db.case_reviews.values()
                    if c["placement_id"] == placement_id])


def votes_of_case_review(case_review_id):
    return ordered([v for v in db.votes.values()
                    if v["case_review_id"] == case_review_id])


def restriction_sets_of_claim(claim_id):
    return ordered([r for r in db.restriction_sets.values()
                    if r["claim_id"] == claim_id])


def training_records_of_supervisor(supervisor_id):
    return ordered([t for t in db.training_records.values()
                    if t["supervisor_id"] == supervisor_id])


def wage_entries_of_claim(claim_id):
    return ordered([w for w in db.wage_entries.values()
                    if w["claim_id"] == claim_id])


def wage_entries_of_placement(placement_id):
    return ordered([w for w in db.wage_entries.values()
                    if w["placement_id"] == placement_id])


def active_restriction_set(claim_id):
    for rs in restriction_sets_of_claim(claim_id):
        if rs["status"] == "ACTIVE":
            return rs
    return None


def case_reviews_of_claim(claim_id):
    out = []
    for p in placements_of_claim(claim_id):
        out.extend(case_reviews_of_placement(p["id"]))
    return out


# ---------------------------------------------- restriction_severity_index
def restriction_severity_index(rs):
    contribution = (
        D("0.40") * (min(D(rs["max_lift_lbs"]), LIFT_REFERENCE_LBS)
                     / LIFT_REFERENCE_LBS) * D(100)
        + D("0.20") * (min(D(rs["max_continuous_standing_minutes"]),
                           STANDING_REFERENCE_MINUTES)
                       / STANDING_REFERENCE_MINUTES) * D(100)
        + D("0.25") * (min(D(rs["max_hours_per_day"]), HOURS_REFERENCE_PER_DAY)
                       / HOURS_REFERENCE_PER_DAY) * D(100)
        + D("0.10") * (D(100) if rs["overhead_reach_allowed"] else D(0))
        + D("0.05") * (D(100) if rs["driving_allowed"] else D(0))
    )
    return int(clamp(rhu(D(100) - contribution, 0), 0, 100))


# ------------------------------------------------------ restriction_match_score
def _headroom(limit, demand):
    limit = D(limit)
    if limit <= 0:
        return D(0)
    return clamp((limit - D(demand)) / limit, 0, 1)


def restriction_match_score(rs, job):
    lift_h = _headroom(rs["max_lift_lbs"], job["demand_lift_lbs"])
    stand_h = _headroom(rs["max_continuous_standing_minutes"],
                        job["demand_standing_minutes"])
    hours_h = _headroom(rs["max_hours_per_day"], job["demand_hours_per_day"])
    key_h = _headroom(rs["keyboard_minutes_per_hour"],
                      job["demand_keyboard_minutes_per_hour"])
    risk_term = D(1) - RISK_CLASS_PENALTY[job["risk_class"]]
    raw = D(100) * (WEIGHT_LIFT * lift_h + WEIGHT_STANDING * stand_h
                    + WEIGHT_HOURS * hours_h + WEIGHT_KEYBOARD * key_h
                    + WEIGHT_RISK * risk_term)
    severity = D(restriction_severity_index(rs))
    damping = min(D("1.0"), SEVERITY_DAMPING_PIVOT / max(severity, D(1)))
    return rhu_f(clamp(raw * damping, 0, 100), 2)


# ---------------------------------------------------------- reinjury risk
def _pressure_ratio(demand, limit):
    limit = D(limit)
    demand = D(demand)
    if limit <= 0:
        return D("1.5") if demand > 0 else D(0)
    return demand / limit


def _demand_pressure(rs, job):
    ratios = [
        _pressure_ratio(job["demand_lift_lbs"], rs["max_lift_lbs"]),
        _pressure_ratio(job["demand_standing_minutes"],
                        rs["max_continuous_standing_minutes"]),
        _pressure_ratio(job["demand_hours_per_day"], rs["max_hours_per_day"]),
        _pressure_ratio(job["demand_keyboard_minutes_per_hour"],
                        rs["keyboard_minutes_per_hour"]),
    ]
    return clamp(max(ratios), 0, D("1.5"))


def _structural(rs, job):
    return (RISK_BASE_BY_JOB_RISK_CLASS[job["risk_class"]]
            + RISK_SEVERITY_WEIGHT * D(restriction_severity_index(rs))
            + RISK_HEADROOM_WEIGHT * _demand_pressure(rs, job))


def _observed(placement):
    clock_date = db.today()
    total = D(0)
    for audit in audits_of_placement(placement["id"]):
        observed_on = parse_date(audit["observed_on"])
        elapsed = max(0, days_between(observed_on, clock_date))
        blocks = elapsed // 30
        decay = clamp(D(1) - AUDIT_DECAY_PER_30_DAYS * D(blocks), 0, 1)
        total += COMPLIANCE_SEVERITY_POINTS[audit["finding_severity"]] * decay
    for report in reinjury_reports_of_placement(placement["id"]):
        if report["report_status"] in ("TRIAGED", "ESCALATED"):
            total += D(REINJURY_SEVERITY_POINTS[report["severity"]])
    return total


def reinjury_risk_baseline(rs, job):
    return int(clamp(rhu(_structural(rs, job), 0), 0, 100))


def reinjury_risk_surveillance(placement):
    job = db.jobs[placement["transitional_job_id"]]
    rs = active_restriction_set(placement["claim_id"])
    if rs is None:
        rs = db.restriction_sets[placement["restriction_set_id"]]
    value = _structural(rs, job) + _observed(placement)
    return int(clamp(rhu(value, 0), 0, 100))


# --------------------------------------------- benefit continuation premium
def premium_split(employee):
    total_cents = MONTHLY_PREMIUM_BY_TIER_CENTS[employee["benefit_tier"]]
    provisional_employee = rhu(total_cents * BASE_EMPLOYEE_CONTRIBUTION_RATE, 0)
    provisional_employer = total_cents - provisional_employee
    if provisional_employer <= SUBSIDY_T1_UPTO_CENTS:
        subsidy_factor = SUBSIDY_FACTOR_T1
    elif provisional_employer <= SUBSIDY_T2_UPTO_CENTS:
        subsidy_factor = SUBSIDY_FACTOR_T2
    else:
        subsidy_factor = SUBSIDY_FACTOR_T3
    employee_share = rhu(provisional_employee * subsidy_factor, 0)
    employer_share = total_cents - employee_share
    return int(employer_share), int(employee_share)


def benefit_continuation_status(placement, employee):
    status = placement["placement_status"]
    if status in ("COMPLETED", "TERMINATED_EARLY", "DECLINED"):
        return "LAPSED"
    if status in ("PROPOSED", "ADJUSTER_PENDING"):
        return "PENDING"
    if employee["benefit_tier"] in ("TIER_A", "TIER_B"):
        return "EMPLOYER_SUBSIDIZED"
    return "EMPLOYEE_PAID"


# --------------------------------------------------------- projected weekly
def projected_weekly_cost_cents(placement, job, employee):
    hours = D(placement["scheduled_hours_per_day"])
    rate = D(job["hourly_rate_cents"])
    weekly_transitional = rate * hours * WORKDAYS_PER_WEEK
    transitional_wage_cents = rhu(weekly_transitional, 0)
    gap = D(employee["pre_injury_weekly_wage_cents"]) - weekly_transitional
    if gap < 0:
        gap = D(0)
    differential_cents = rhu(STATUTORY_REPLACEMENT_RATE * gap, 0)
    employer_share, _ = premium_split(employee)
    benefit_cents = rhu(D(employer_share) / PREMIUM_WEEKS_PER_MONTH, 0)
    return int(transitional_wage_cents + differential_cents + benefit_cents)


# ------------------------------------------------------- duration ledger
def _effective_through(placement):
    status = placement["placement_status"]
    if status in ("COMPLETED", "TERMINATED_EARLY"):
        return parse_date(placement["ended_on"]) if placement["ended_on"] else None
    if status in ("ACTIVE", "PROGRESSION_HOLD", "SUSPENDED"):
        return db.today()
    return None


def cumulative_days(placement):
    if not placement.get("activated_on"):
        return 0
    through = _effective_through(placement)
    if through is None:
        return 0
    end_date = parse_date(placement["end_date"])
    limit = min(through, end_date)
    activated = parse_date(placement["activated_on"])
    return max(0, days_between(activated, limit) + 1)


def claim_cumulative_transitional_days(claim_id):
    total = 0
    for p in placements_of_claim(claim_id):
        if p["placement_status"] in DURATION_STATUSES:
            total += cumulative_days(p)
    return total


def projected_cumulative(placement, new_end_date):
    claim_total = claim_cumulative_transitional_days(placement["claim_id"])
    start = parse_date(placement["start_date"])
    return (claim_total - cumulative_days(placement)
            + max(0, days_between(start, new_end_date) + 1))


# ---------------------------------------------------------- claim posture
def claim_wage_differential_paid_cents(claim_id):
    return sum(w["net_amount_cents"] for w in wage_entries_of_claim(claim_id))


def claim_rtw_posture(claim):
    if claim["claim_status"] == "SUSPENDED":
        return "FROZEN"
    for cr in case_reviews_of_claim(claim["id"]):
        if cr["review_status"] in ("OPEN", "VOTING"):
            return "FROZEN"
    for p in placements_of_claim(claim["id"]):
        if (p["placement_status"] in ("ACTIVE", "PROGRESSION_HOLD", "SUSPENDED")
                and p["compliance_status"] in ("WATCH", "NONCOMPLIANT")):
            return "RESTRICTED"
    if claim_cumulative_transitional_days(claim["id"]) >= DURATION_SOFT_CAP_DAYS:
        return "RESTRICTED"
    return "OPEN"


# ------------------------------------------------- supervisor derived fields
def supervisor_compliance_strike_points(supervisor_id):
    total = 0
    for p in placements_of_supervisor(supervisor_id):
        for audit in audits_of_placement(p["id"]):
            total += COMPLIANCE_STRIKE_POINTS[audit["finding_severity"]]
    return total


def supervisor_effective_strike_points(supervisor):
    return max(0, supervisor_compliance_strike_points(supervisor["id"])
               - supervisor["strike_forgiveness_points"])


def supervisor_training_status(supervisor_id):
    pool = [t for t in training_records_of_supervisor(supervisor_id)
            if t["curriculum_code"] == "RTW_CORE"
            and t["record_status"] != "SUPERSEDED"]
    if not pool:
        return "NONE"
    governing = None
    for record in pool:
        if governing is None:
            governing = record
            continue
        if record["valid_through"] > governing["valid_through"]:
            governing = record
    return governing["record_status"]


# ------------------------------------------------------- progression targets
def progression_step_target(placement, rs, job, employee):
    target_hours = min(
        D(placement["scheduled_hours_per_day"]) + PROGRESSION_HOURS_STEP,
        D(rs["max_hours_per_day"]),
        D(employee["pre_injury_weekly_hours"]) / WORKDAYS_PER_WEEK,
    )
    stepped_lift = rhu(D(job["demand_lift_lbs"])
                       * (D(1) + PROGRESSION_LIFT_STEP_PCT), 2)
    target_lift = min(stepped_lift, D(rs["max_lift_lbs"]))
    return rhu_f(target_hours, 2), rhu_f(target_lift, 2)


# ------------------------------------------------------------- panel tally
def case_review_tally(case_review):
    counted = [v for v in votes_of_case_review(case_review["id"])
               if v["vote_status"] == "COUNTED"]
    vote_count = len(counted)
    continue_votes = sum(1 for v in counted if v["ballot"] == "CONTINUE")
    modify_votes = sum(1 for v in counted if v["ballot"] == "MODIFY")
    terminate_votes = sum(1 for v in counted if v["ballot"] == "TERMINATE")
    max_count = max(continue_votes, modify_votes, terminate_votes)
    winning = None
    if vote_count > 0:
        for ballot, count in (("TERMINATE", terminate_votes),
                              ("MODIFY", modify_votes),
                              ("CONTINUE", continue_votes)):
            if count == max_count:
                winning = ballot
                break
    ratio = 0.0 if vote_count == 0 else rhu_f(D(max_count) / D(vote_count), 4)
    return {
        "vote_count": vote_count,
        "continue_votes": continue_votes,
        "modify_votes": modify_votes,
        "terminate_votes": terminate_votes,
        "decision_ratio": ratio,
        "winning_ballot": winning,
    }


# ------------------------------------------------------------- wage ledger
def wage_period_amount(placement, job, employee, variant, period_start,
                       period_end):
    pre_injury_daily = D(employee["pre_injury_weekly_wage_cents"]) / WORKDAYS_PER_WEEK
    rate = D(job["hourly_rate_cents"])

    def day_gap(hours):
        gap = pre_injury_daily - rate * D(hours)
        return gap if gap > 0 else D(0)

    if variant == "PROVISIONAL":
        counted_day_count = 0
        cursor = period_start
        while cursor <= period_end:
            if cursor.weekday() < 5:
                counted_day_count += 1
            cursor = cursor.fromordinal(cursor.toordinal() + 1)
        gross_pre_cap = rhu(D(counted_day_count) * STATUTORY_REPLACEMENT_RATE
                            * day_gap(placement["scheduled_hours_per_day"]), 0)
        tier_multiplier = TIER1_MULTIPLIER
    else:
        entries = [e for e in placement["logged_hours"]
                   if period_start <= parse_date(e["work_date"]) <= period_end]
        entries.sort(key=lambda e: e["work_date"])
        counted_day_count = len(entries)
        gross_pre_tier = D(0)
        for entry in entries:
            gross_pre_tier += rhu(STATUTORY_REPLACEMENT_RATE
                                  * day_gap(entry["hours_worked"]), 0)
        start = parse_date(placement["start_date"])
        elapsed_weeks = (days_between(start, period_start) // 7) + 1
        if elapsed_weeks <= TIER1_MAX_WEEKS:
            tier_multiplier = TIER1_MULTIPLIER
        elif elapsed_weeks <= TIER2_MAX_WEEKS:
            tier_multiplier = TIER2_MULTIPLIER
        else:
            tier_multiplier = TIER3_MULTIPLIER
        gross_pre_cap = rhu(gross_pre_tier * tier_multiplier, 0)

    period_weeks = int(math.ceil(counted_day_count / float(WORKDAYS_PER_WEEK)))
    gross_differential_cents = int(min(gross_pre_cap,
                                       WEEKLY_DIFFERENTIAL_CAP_CENTS
                                       * D(period_weeks)))
    if (variant == "FINAL"
            and benefit_continuation_status(
                placement, employee) == "EMPLOYER_SUBSIDIZED"):
        offset_cents = int(rhu(D(gross_differential_cents)
                               * BENEFIT_OFFSET_RATE, 0))
    else:
        offset_cents = 0
    net_amount_cents = gross_differential_cents - offset_cents
    return {
        "counted_day_count": counted_day_count,
        "tier_multiplier": float(tier_multiplier),
        "gross_differential_cents": gross_differential_cents,
        "offset_cents": offset_cents,
        "net_amount_cents": net_amount_cents,
    }


def ordered_jobs_of_supervisor(supervisor_id):
    return ordered([j for j in db.jobs.values()
                    if j["supervisor_id"] == supervisor_id])
