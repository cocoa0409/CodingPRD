"""Pinned calculation rules (PRD 2.9 / 3.x).  All money is whole cents."""
from decimal import Decimal, ROUND_HALF_UP, getcontext

from store import store

getcontext().prec = 50

# --- pinned constants ----------------------------------------------------
ADA_TAX_CREDIT_RATE = Decimal("0.26")
AMORTIZATION_MONTHS = Decimal(24)
MIN_COVERAGE_RATIO = Decimal("0.60")

W_COST = Decimal("0.65")
W_DISRUPTION = Decimal("0.20")
W_LAG = Decimal("0.15")
BUDGET_RATIO_CAP = Decimal("0.05")
LAG_CAP_DAYS = Decimal(60)
MITIGATION_TIER_1_MAX = Decimal("40.00")
MITIGATION_TIER_2_MAX = Decimal("65.00")
MITIGATION_TIER_3_MAX = Decimal("85.00")
UNDUE_SCORE_THRESHOLD = Decimal("70.00")
BORDERLINE_SCORE_THRESHOLD = Decimal("45.00")

SUBJECTIVE_WEIGHT = Decimal("0.6")
OBJECTIVE_WEIGHT = Decimal("0.4")
RECENCY_WEIGHTS = [Decimal("0.5"), Decimal("0.3"), Decimal("0.2")]
EFFECTIVE_THRESHOLD = Decimal("7.00")
MIN_TRIAL_REVIEWS = 3
MAX_TRIAL_EXTENSIONS = 1
TRIAL_EXTENSION_DAYS = 30

BASE_DOC_REQUEST_LIMIT = 2
INEFFECTIVE_TRIAL_BONUS = 1
RENEWAL_BONUS = 1
ABSOLUTE_DOC_REQUEST_CEILING = 4

INTEGRITY_BASE = 100
INTEGRITY_FLOOR = 0
PENALTY_DOC_OVERREACH = 25
PENALTY_UNAUTHORIZED_DISCLOSURE = 30
PENALTY_EXPIRED_DOC_WINDOW = 10
PENALTY_MISSED_RENEWAL = 15
MISSED_RENEWAL_GRACE_DAYS = 30
APPEAL_MANDATORY_REMAND_THRESHOLD = 60
APPEAL_WINDOW_DAYS = 30
MAX_APPEAL_SUPPLEMENTS = 2

BASE_REVIEW_CADENCE_DAYS = 365
BORDERLINE_CADENCE_DAYS = 180
ABSENCE_LINKED_CADENCE_DAYS = 90
TRIAL_GRANT_CADENCE_DAYS = 120
MAX_INTERACTIVE_ROUNDS = 2
MAX_OPEN_CASES_PER_EMPLOYEE = 2

TRIAL_WASHOUT_DAYS = 7
INTERMITTENT_WEEKLY_DAY_CAP = 5

FULL_ACCESS_ROLES = ("MedicalReviewOfficer", "ComplianceAuditor")
COORDINATOR_PERMITTED_FIELDS = {
    "functional_limitations", "work_restrictions", "restriction_duration",
    "prognosis", "accommodation_needed",
}
MANAGER_PERMITTED_FIELDS = {
    "work_restrictions", "restriction_duration", "accommodation_needed",
}
FINANCE_PERMITTED_FIELDS = {"accommodation_needed"}


def round_half_up(value, places):
    quant = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(quant, rounding=ROUND_HALF_UP)


def as_number(dec):
    return float(dec)


def dec(value):
    return Decimal(str(value))


# --- option_net_cost -----------------------------------------------------
def option_net_cost(one_time_cost_cents, recurring_monthly_cost_cents):
    frac = Decimal(1) - ADA_TAX_CREDIT_RATE
    one_time_component = round_half_up(Decimal(one_time_cost_cents) * frac, 0)
    recurring_component = round_half_up(
        Decimal(recurring_monthly_cost_cents) * AMORTIZATION_MONTHS * frac, 0)
    return int(one_time_component + recurring_component)


# --- essential_function_coverage ----------------------------------------
def pinned_denominator_functions(job_profile_id):
    return [f for f in store.essential_functions.values()
            if f["job_profile_id"] == job_profile_id
            and f["is_essential"] is True
            and f["status"] == "ACTIVE"]


def coverage_ratio(job_profile_id, coverage_function_ids):
    denominator = pinned_denominator_functions(job_profile_id)
    total = sum(f["criticality_weight"] for f in denominator)
    if total == 0:
        return Decimal("1.000000")
    ids = set(coverage_function_ids or [])
    covered = sum(f["criticality_weight"] for f in denominator if f["id"] in ids)
    return round_half_up(Decimal(covered) / Decimal(total), 6)


# --- undue_hardship_assessment ------------------------------------------
def hardship_assessment(option, profile, assessment_basis):
    assessed = int(option["option_net_cost_cents"])
    if assessment_basis == "EMPLOYER_WIDE":
        denominator = int(profile["employer_annual_budget_cents"])
    else:
        denominator = int(profile["department_annual_budget_cents"])
    budget_ratio = round_half_up(Decimal(assessed) / Decimal(denominator), 6)
    budget_ratio_norm = round_half_up(budget_ratio / BUDGET_RATIO_CAP * Decimal(100), 4)
    if budget_ratio_norm > Decimal("100.0000"):
        budget_ratio_norm = Decimal("100.0000")
    cov = dec(option["coverage_ratio"])
    disruption_index = round_half_up((Decimal(1) - cov) * Decimal(100), 4)
    lag_norm = round_half_up(
        Decimal(int(option["implementation_days"])) / LAG_CAP_DAYS * Decimal(100), 4)
    if lag_norm > Decimal("100.0000"):
        lag_norm = Decimal("100.0000")
    raw = round_half_up(
        W_COST * budget_ratio_norm + W_DISRUPTION * disruption_index + W_LAG * lag_norm, 2)
    if raw < MITIGATION_TIER_1_MAX:
        rate = Decimal("0.00")
    elif raw < MITIGATION_TIER_2_MAX:
        rate = Decimal("0.10")
    elif raw < MITIGATION_TIER_3_MAX:
        rate = Decimal("0.05")
    else:
        rate = Decimal("0.00")
    score = round_half_up(raw * (Decimal(1) - rate), 2)
    if score >= UNDUE_SCORE_THRESHOLD:
        verdict = "UNDUE"
    elif score >= BORDERLINE_SCORE_THRESHOLD:
        verdict = "BORDERLINE"
    else:
        verdict = "NOT_UNDUE"
    return {
        "assessed_net_cost_cents": assessed,
        "denominator_cents": denominator,
        "budget_ratio": as_number(budget_ratio),
        "budget_ratio_norm": as_number(budget_ratio_norm),
        "disruption_index": as_number(disruption_index),
        "lag_norm": as_number(lag_norm),
        "raw_hardship_score": as_number(raw),
        "mitigation_credit_rate": as_number(rate),
        "hardship_score": as_number(score),
        "hardship_verdict": verdict,
    }


# --- trial_effectiveness -------------------------------------------------
def review_composite(employee_rating, manager_rating, objective_metric_pct):
    subjective = (Decimal(employee_rating) + Decimal(manager_rating)) / Decimal(2)
    objective = Decimal(objective_metric_pct) / Decimal(10)
    return round_half_up(SUBJECTIVE_WEIGHT * subjective + OBJECTIVE_WEIGHT * objective, 4)


def ordered_reviews(trial_id):
    rows = [r for r in store.reviews.values() if r["trial_period_id"] == trial_id]
    return sorted(rows, key=lambda r: (r["review_date"], r["created_at"]))


def effectiveness_score(trial):
    rows = ordered_reviews(trial["id"])
    n = len(rows)
    if n == 0:
        return None
    if trial["scoring_mode"] == "CUMULATIVE_MEAN":
        total = sum((dec(r["review_composite"]) for r in rows), Decimal(0))
        return as_number(round_half_up(total / Decimal(n), 2))
    k = min(3, n)
    tail = list(reversed(rows[-k:]))          # tail[0] is the latest review
    raw_w = RECENCY_WEIGHTS[:k]
    weight_sum = sum(raw_w, Decimal(0))
    total = Decimal(0)
    for i in range(k):
        total += (raw_w[i] / weight_sum) * dec(tail[i]["review_composite"])
    return as_number(round_half_up(total, 2))


# --- documentation_budget ------------------------------------------------
def doc_rounds_of(request_id):
    return [d for d in store.doc_requests.values() if d["request_id"] == request_id]


def documentation_budget(req):
    raw_limit = BASE_DOC_REQUEST_LIMIT
    ineffective = any(t["request_id"] == req["id"]
                      and t["status"] == "CONCLUDED_INEFFECTIVE"
                      for t in store.trials.values())
    if ineffective:
        raw_limit += INEFFECTIVE_TRIAL_BONUS
    if req.get("renewal_of_request_id") is not None:
        raw_limit += RENEWAL_BONUS
    limit = min(raw_limit, ABSOLUTE_DOC_REQUEST_CEILING)
    count = len([d for d in doc_rounds_of(req["id"]) if d["status"] != "WITHDRAWN"])
    return limit, count, max(0, limit - count)


def apply_documentation_budget(req):
    limit, count, remaining = documentation_budget(req)
    req["medical_doc_request_limit"] = limit
    req["medical_doc_request_count"] = count
    req["documentation_budget_remaining"] = remaining


def refresh_doc_counters(req):
    """Recompute the count/remaining pair while leaving an explicitly raised
    limit (the ineffective-trial bonus) in place."""
    limit = req["medical_doc_request_limit"]
    count = len([d for d in doc_rounds_of(req["id"]) if d["status"] != "WITHDRAWN"])
    req["medical_doc_request_count"] = count
    req["documentation_budget_remaining"] = max(0, limit - count)


# --- interactive_process_integrity --------------------------------------
def integrity_score(req):
    overreach = max(0, req["medical_doc_request_count"] - BASE_DOC_REQUEST_LIMIT)
    unauthorized = len([d for d in store.disclosures.values()
                        if d["request_id"] == req["id"] and d["authorized"] is False])
    expired = len([d for d in doc_rounds_of(req["id"]) if d["status"] == "EXPIRED"])
    missed = 0
    if req["stage"] == "RENEWAL_DUE" and req.get("review_due_date"):
        from store import parse_date
        from datetime import timedelta
        due = parse_date(req["review_due_date"])
        if due is not None and store.today() > due + timedelta(days=MISSED_RENEWAL_GRACE_DAYS):
            missed = 1
    penalties = (PENALTY_DOC_OVERREACH * overreach
                 + PENALTY_UNAUTHORIZED_DISCLOSURE * unauthorized
                 + PENALTY_EXPIRED_DOC_WINDOW * expired
                 + PENALTY_MISSED_RENEWAL * missed)
    return max(INTEGRITY_FLOOR, INTEGRITY_BASE - penalties)


def apply_integrity_score(req):
    req["interactive_process_integrity_score"] = integrity_score(req)


# --- disclosure_authorization -------------------------------------------
def disclosure_authorized(disclosed_to_role, fields_disclosed):
    fields = set(fields_disclosed or [])
    if disclosed_to_role in FULL_ACCESS_ROLES:
        return True
    if disclosed_to_role == "AccommodationCoordinator":
        return fields.issubset(COORDINATOR_PERMITTED_FIELDS)
    if disclosed_to_role == "Manager":
        return fields.issubset(MANAGER_PERMITTED_FIELDS)
    if disclosed_to_role == "FinanceOfficer":
        return fields.issubset(FINANCE_PERMITTED_FIELDS)
    if disclosed_to_role == "AppealOfficer":
        return fields.issubset(COORDINATOR_PERMITTED_FIELDS)
    return False


# --- renewal_cadence -----------------------------------------------------
def renewal_cadence(req):
    from datetime import timedelta
    candidates = [BASE_REVIEW_CADENCE_DAYS]
    option_id = req.get("selected_option_id")
    if option_id:
        current = [a for a in store.assessments.values()
                   if a["option_id"] == option_id and a["status"] == "CURRENT"]
        if current and current[-1]["hardship_verdict"] == "BORDERLINE":
            candidates.append(BORDERLINE_CADENCE_DAYS)
    absence_id = req.get("absence_record_id")
    if absence_id:
        absence = store.absences.get(absence_id)
        if absence is not None and absence["status"] != "CLOSED":
            candidates.append(ABSENCE_LINKED_CADENCE_DAYS)
    if req.get("decision") == "GRANT_WITH_TRIAL":
        candidates.append(TRIAL_GRANT_CADENCE_DAYS)
    cadence = min(candidates)
    due = store.today() + timedelta(days=cadence)
    return cadence, due.isoformat()


def apply_renewal_cadence(req):
    cadence, due = renewal_cadence(req)
    req["review_cadence_days"] = cadence
    req["review_due_date"] = due
