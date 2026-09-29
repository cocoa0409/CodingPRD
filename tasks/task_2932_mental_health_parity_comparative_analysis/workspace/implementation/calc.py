"""The nine calculation rules (PRD 3.1, 3.3, 3.5, 3.6, 3.7, 3.8, 3.9).

All arithmetic is exact decimal arithmetic; every rounding step is ROUND_HALF_UP
and happens exactly where the PRD pins it.
"""

from decimal import Decimal, ROUND_HALF_UP

from errors import ApiError
from store import creation_key, db

ZERO = Decimal("0")

# --- constants -------------------------------------------------------------
SUBSTANTIALLY_ALL_NUMERATOR = 2
SUBSTANTIALLY_ALL_DENOMINATOR = 3
PREDOMINANT_NUMERATOR = 1
PREDOMINANT_DENOMINATOR = 2

DISPARITY_THRESHOLD = Decimal("2.0")

UM_NQTL_TYPES = ("PRIOR_AUTHORIZATION", "MEDICAL_NECESSITY_CRITERIA",
                 "CONCURRENT_REVIEW", "STEP_THERAPY")
NETWORK_NQTL_TYPES = ("NETWORK_ADMISSION", "REIMBURSEMENT_RATE")
UM_WEIGHTS = (Decimal("0.6"), Decimal("0.4"))
NETWORK_WEIGHTS = (Decimal("0.3"), Decimal("0.7"))
ASYMMETRY_MULTIPLIER = Decimal("1.5")
FACTOR_CREDIT = Decimal("0.05")
EVIDENCE_CREDIT = Decimal("0.03")
DOC_CREDIT_CAP = Decimal("0.25")
STRINGENCY_VIOLATION_THRESHOLD = Decimal("5.0")

LATE_PENALTY = Decimal("15")
BREACH_PENALTY = Decimal("25")
REGULATORY_PRODUCTION_DAYS = 30
COOPERATIVE_FLOOR = Decimal("80")
DELINQUENT_FLOOR = Decimal("50")

TIER_A_FLOOR = Decimal("80")
TIER_B_FLOOR = Decimal("60")
TIER_CREDIT = {"A": Decimal("10"), "B": Decimal("6"), "C": Decimal("2")}
EVIDENCE_TARGET = Decimal("8")
RESPONSE_SUFFICIENCY_THRESHOLD = Decimal("85.0")

REMEDY_RATES = {
    "RETROSPECTIVE_CLAIMS_REPROCESSING": Decimal("1.00"),
    "DESIGN_CHANGE": Decimal("0.25"),
    "PROCESS_CHANGE": Decimal("0.10"),
}

MIN_FACTORS = 2
MIN_EVIDENTIARY_STANDARDS = 1
MAX_REVISION_ROUNDS = 3
MEASUREMENT_PERIOD_BUFFER_DAYS = 1
BREACH_GRACE_DAYS = 7
REGULATOR_RESPONSE_DAYS = 30
REOPEN_EXTENSION_DAYS = 14


def rnd(value, places):
    """ROUND_HALF_UP to the given number of decimal places."""
    if places == 0:
        exponent = Decimal("1")
    else:
        exponent = Decimal("1").scaleb(-places)
    return Decimal(value).quantize(exponent, rounding=ROUND_HALF_UP)


def clamp(value, low, high):
    if value < low:
        return Decimal(low)
    if value > high:
        return Decimal(high)
    return value


# --- 3.3 quantitative testing ---------------------------------------------

def _weight(row, basis):
    if basis == "PLAN_PAYMENTS":
        return row["projected_plan_payments_cents"]
    return row["projected_claims_count"]


def run_parity_test(classification_id, limitation_type, basis):
    """Steps one, two and three of PRD 3.3. Returns the computed fields."""
    rows = [r for r in db.treatment_limitations.values()
            if r["classification_id"] == classification_id
            and r["status"] == "ACTIVE"
            and r["limitation_type"] == limitation_type]
    ms_rows = [r for r in rows if r["benefit_side"] == "MEDICAL_SURGICAL"]

    total_weight = sum(_weight(r, basis) for r in ms_rows)
    subject_weight = sum(_weight(r, basis) for r in ms_rows if r["level_value"] > 0)
    if total_weight == 0:
        raise ApiError("ERR_EMPTY_TEST_POPULATION")

    # Both variants always publish the PLAN_PAYMENTS sums.
    total_ms_payments_cents = sum(r["projected_plan_payments_cents"] for r in ms_rows)
    subject_payments_cents = sum(r["projected_plan_payments_cents"]
                                 for r in ms_rows if r["level_value"] > 0)

    substantially_all_met = (subject_weight * SUBSTANTIALLY_ALL_DENOMINATOR
                             >= total_weight * SUBSTANTIALLY_ALL_NUMERATOR)
    substantially_all_ratio = rnd(Decimal(subject_weight) / Decimal(total_weight), 6)

    predominant_level = None
    if substantially_all_met:
        predominant_level = _predominant_level(ms_rows, basis)

    mh_level_value = _mh_level_under_test(rows)

    if not substantially_all_met:
        result = "NOT_APPLICABLE"
    elif mh_level_value is None:
        result = "NOT_APPLICABLE"
    elif mh_level_value > predominant_level:
        result = "FAIL"
    else:
        result = "PASS"

    return {
        "total_ms_payments_cents": total_ms_payments_cents,
        "subject_payments_cents": subject_payments_cents,
        "substantially_all_ratio": substantially_all_ratio,
        "substantially_all_met": substantially_all_met,
        "predominant_level": predominant_level,
        "mh_level_value": mh_level_value,
        "result": result,
    }


def _predominant_level(ms_rows, basis):
    subject_rows = [r for r in ms_rows if r["level_value"] > 0]
    denominator = sum(_weight(r, basis) for r in subject_rows)
    if denominator == 0:
        return None
    # Rows sharing a level_value are merged into one level before anything else.
    level_weight = {}
    for row in subject_rows:
        level = row["level_value"]
        level_weight[level] = level_weight.get(level, 0) + _weight(row, basis)
    # Single-level branch: strictly more than one half.
    for level, weight in level_weight.items():
        if weight * PREDOMINANT_DENOMINATOR > denominator * PREDOMINANT_NUMERATOR:
            return level
    # Combination branch: descending level_value, most restrictive first.
    cumulative = 0
    for level in sorted(level_weight.keys(), reverse=True):
        cumulative += level_weight[level]
        if cumulative * PREDOMINANT_DENOMINATOR > denominator * PREDOMINANT_NUMERATOR:
            return level
    return None


def _mh_level_under_test(rows):
    mh_rows = [r for r in rows
               if r["benefit_side"] == "MENTAL_HEALTH_SUD" and r["level_value"] > 0]
    if not mh_rows:
        return None
    mh_rows.sort(key=lambda r: (-r["level_value"], r["created_at"], r["_seq"]))
    return mh_rows[0]["level_value"]


# --- 3.6 denial-rate scoring ----------------------------------------------

def denial_rate_disparity_index(mh_denials, mh_claims, ms_denials, ms_claims):
    mh_raw = Decimal(mh_denials) / Decimal(mh_claims)
    ms_raw = Decimal(ms_denials) / Decimal(ms_claims)
    mh_denial_rate = rnd(mh_raw, 6)
    ms_denial_rate = rnd(ms_raw, 6)
    # Pinned order: the ratio comes from the two UNROUNDED quotients.
    disparity_ratio = rnd(mh_raw / ms_raw, 4)
    as_applied_flag = disparity_ratio >= DISPARITY_THRESHOLD
    return mh_denial_rate, ms_denial_rate, disparity_ratio, as_applied_flag


def network_composition_gap(ms_pct, mh_pct):
    return rnd(Decimal(ms_pct) - Decimal(mh_pct), 4)


# --- 3.7 stringency in operation ------------------------------------------

def stringency_in_operation_index(item):
    classification_id = item["classification_id"]
    disparities = [s["disparity_ratio"] for s in db.data_submissions.values()
                   if s["status"] == "VALIDATED"
                   and s["submission_type"] == "DENIAL_RATES"
                   and s["classification_id"] == classification_id
                   and s["disparity_ratio"] is not None]
    gaps = [s["network_composition_gap"] for s in db.data_submissions.values()
            if s["status"] == "VALIDATED"
            and s["submission_type"] == "NETWORK_COMPOSITION"
            and s["classification_id"] == classification_id
            and s["network_composition_gap"] is not None]
    disparity_input = max(disparities) if disparities else ZERO
    network_input = max(gaps) if gaps else ZERO

    analysis = latest_analysis(item["id"])
    factors = analysis["factor_count"] if analysis else 0
    standards = analysis["evidentiary_standard_count"] if analysis else 0

    if item["nqtl_type"] in NETWORK_NQTL_TYPES:
        weight_d, weight_n = NETWORK_WEIGHTS
    else:
        weight_d, weight_n = UM_WEIGHTS

    base = (weight_d * max(ZERO, disparity_input - Decimal(1))
            + weight_n * max(ZERO, network_input))
    if item["applied_to"] == "MENTAL_HEALTH_SUD_ONLY":
        base = base * ASYMMETRY_MULTIPLIER
    doc_credit = min(DOC_CREDIT_CAP,
                     FACTOR_CREDIT * Decimal(factors) + EVIDENCE_CREDIT * Decimal(standards))
    raw = base * Decimal(10) - doc_credit * Decimal(10)
    index = rnd(clamp(raw, Decimal(0), Decimal(10)), 2)
    flag = index >= STRINGENCY_VIOLATION_THRESHOLD
    return index, flag


def latest_analysis(nqtl_item_id):
    """Most recent non-WITHDRAWN analysis: created_at DESC then version DESC."""
    candidates = [a for a in db.analyses.values()
                  if a["nqtl_item_id"] == nqtl_item_id and a["status"] != "WITHDRAWN"]
    if not candidates:
        return None
    candidates.sort(key=lambda a: (a["created_at"], a["version"], a["_seq"]), reverse=True)
    return candidates[0]


# --- 3.5 administrator cooperation ----------------------------------------

def cooperation_counters(administrator_id, now):
    requests = [r for r in db.vendor_requests.values()
                if r["administrator_id"] == administrator_id]
    live = [r for r in requests if r["fulfillment_status"] in ("OPEN", "PARTIAL")]
    outstanding = len(live)
    late = len([r for r in live if now > r["due_at"]])
    regulator_late = len([r for r in live if now > r["regulatory_due_at"]])
    breaches = len([r for r in requests if r["escalation_status"] == "BREACH_DECLARED"])
    return outstanding, late, regulator_late, breaches


def cooperation_score(late_count, breach_count):
    raw = Decimal(100) - LATE_PENALTY * Decimal(late_count) - BREACH_PENALTY * Decimal(breach_count)
    if raw < ZERO:
        raw = ZERO
    if raw > Decimal(100):
        raw = Decimal(100)
    return rnd(raw, 2)


def cooperation_status(score):
    if score >= COOPERATIVE_FLOOR:
        return "COOPERATIVE"
    if score >= DELINQUENT_FLOOR:
        return "DELINQUENT"
    return "ESCALATED"


# --- 3.9 regulator response completeness ----------------------------------

def regulator_response_completeness(regulator_request):
    requested_types = regulator_request["requested_nqtl_types"]
    plan_year_id = regulator_request["plan_year_id"]
    requested_items = [i for i in db.nqtl_items.values()
                       if i["plan_year_id"] == plan_year_id
                       and i["nqtl_type"] in requested_types]
    requested_count = len(requested_items)
    covered = []
    evidence_total = 0
    for item in requested_items:
        certified = [a for a in db.analyses.values()
                     if a["nqtl_item_id"] == item["id"] and a["status"] == "CERTIFIED"]
        if not certified:
            continue
        certified.sort(key=lambda a: (a["created_at"], a["_seq"]), reverse=True)
        covered.append(item)
        evidence_total += certified[0]["evidentiary_standard_count"]
    covered_count = len(covered)
    if requested_count == 0:
        return requested_count, covered_count, None, None
    base = Decimal(100) * Decimal(covered_count) / Decimal(requested_count)
    # The tier is read from the base ALONE, before any credit is added.
    if base >= TIER_A_FLOOR:
        tier = "A"
    elif base >= TIER_B_FLOOR:
        tier = "B"
    else:
        tier = "C"
    credit = TIER_CREDIT[tier] * min(Decimal(1), Decimal(evidence_total) / EVIDENCE_TARGET)
    score = rnd(min(Decimal(100), base + credit), 2)
    sufficient = score >= RESPONSE_SUFFICIENCY_THRESHOLD
    return requested_count, covered_count, score, sufficient


# --- 3.8 remediation liability --------------------------------------------

def reprocessing_liability_cents(remedy_type, affected_claims_count, average_claim_cents):
    rate = REMEDY_RATES[remedy_type]
    product = Decimal(affected_claims_count) * Decimal(average_claim_cents) * rate
    return int(rnd(product, 0))


# --- 3.1 plan-year compliance posture -------------------------------------

def posture_inputs(plan_year_id):
    open_violation_count = len([i for i in db.nqtl_items.values()
                                if i["plan_year_id"] == plan_year_id
                                and i["status"] == "VIOLATION"])
    inventoried_count = len([i for i in db.nqtl_items.values()
                             if i["plan_year_id"] == plan_year_id
                             and i["status"] == "INVENTORIED"])
    item_ids = set(i["id"] for i in db.nqtl_items.values()
                   if i["plan_year_id"] == plan_year_id)
    notified_violation_count = len([n for n in db.notices.values()
                                    if n["notice_type"] == "VIOLATION_DISCLOSURE"
                                    and n["nqtl_item_id"] in item_ids])
    classification_ids = set(c["id"] for c in db.classifications.values()
                             if c["plan_year_id"] == plan_year_id)
    failing_parity_test_count = len([t for t in db.parity_tests.values()
                                     if t["status"] == "COMPUTED"
                                     and t["basis"] == "PLAN_PAYMENTS"
                                     and t["result"] == "FAIL"
                                     and t["classification_id"] in classification_ids])
    remediation_liability = 0
    for cap in db.caps.values():
        if cap["status"] != "APPROVED":
            continue
        item = db.nqtl_items.get(cap["nqtl_item_id"])
        if item is not None and item["plan_year_id"] == plan_year_id:
            remediation_liability += cap["reprocessing_liability_cents"]
    return {
        "open_violation_count": open_violation_count,
        "notified_violation_count": notified_violation_count,
        "failing_parity_test_count": failing_parity_test_count,
        "remediation_liability_cents": remediation_liability,
        "inventoried_count": inventoried_count,
    }


def compliance_posture(open_violation_count, failing_parity_test_count,
                       administrator_cooperation_status, inventoried_count):
    """Ordered ladder; the first matching clause wins."""
    if open_violation_count >= 1 or failing_parity_test_count >= 1:
        return "VIOLATION"
    if administrator_cooperation_status in ("DELINQUENT", "ESCALATED") or inventoried_count >= 1:
        return "AT_RISK"
    return "COMPLIANT"
