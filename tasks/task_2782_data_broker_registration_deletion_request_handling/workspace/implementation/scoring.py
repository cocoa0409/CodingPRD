"""The nine calculations (PRD 2.7, 3.2, 3.4, 3.6, 3.8)."""
from decimal import Decimal

from core import D, rhu, rhu_cents

# ---------------------------------------------- disclosure completeness (1)
DISCLOSURE_WEIGHTS = {
    "SOURCES": D("20.00"),
    "RECIPIENTS": D("25.00"),
    "RETENTION": D("15.00"),
    "OPT_OUT_MECHANISM": D("20.00"),
    "SENSITIVE_CATEGORIES": D("12.00"),
    "MINORS_DATA": D("8.00"),
}
FULL_WEIGHT_MIN_LENGTH = 40
COMPLETENESS_SUBMIT_MINIMUM = D("80.00")
MANDATORY_CATEGORIES = ["SOURCES", "RECIPIENTS", "RETENTION",
                        "OPT_OUT_MECHANISM"]


def weight_credit(category, content_length):
    """Full weight when content_length >= 40, half weight when shorter."""
    full = DISCLOSURE_WEIGHTS[category]
    if content_length >= FULL_WEIGHT_MIN_LENGTH:
        return rhu(full, 2)
    return rhu(full / D(2), 2)


def completeness_score(items):
    total = D("0")
    for item in items:
        total += D(item["weight_credit"])
    return rhu(total, 2)


# ------------------------------------------------------- filing fees (2, 3)
BASE_FILING_FEE_CENTS = 40000
CATEGORY_SURCHARGE_CENTS = {
    "SOURCES": D("1500"),
    "RECIPIENTS": D("2500"),
    "RETENTION": D("1200"),
    "SENSITIVE_CATEGORIES": D("6000"),
    "OPT_OUT_MECHANISM": D("1800"),
    "MINORS_DATA": D("7500"),
}
SENSITIVE_SURCHARGE_MULTIPLIER = D("1.35")
PRORATION_DENOMINATOR_DAYS = D("365")


def item_surcharge_cents(category, covers_sensitive):
    """Fixed at insertion time and never recomputed (PRD 3.2)."""
    base = CATEGORY_SURCHARGE_CENTS[category]
    if covers_sensitive:
        base = base * SENSITIVE_SURCHARGE_MULTIPLIER
    return rhu_cents(base)


def provisional_filing_fee_cents(items):
    """Base plus the sum of the per-item surcharges. No proration."""
    total = BASE_FILING_FEE_CENTS
    for item in items:
        total += int(item["surcharge_cents"])
    return total


def final_filing_fee_cents(items, coverage_days):
    """Aggregate, prorate, then round exactly once at the end (PRD 3.2)."""
    aggregate = D(BASE_FILING_FEE_CENTS)
    for item in items:
        aggregate += D(item["surcharge_cents"])
    factor = D(coverage_days) / PRORATION_DENOMINATOR_DAYS
    if factor > D(1):
        factor = D(1)
    if factor < D(0):
        factor = D(0)
    return rhu_cents(aggregate * factor)


# ------------------------------------------------- identity assurance (4)
METHOD_BASE_SCORE = {
    "GOVT_ID": D("55.00"),
    "TWO_DATA_POINTS": D("30.00"),
    "PLATFORM_ASSERTION": D("25.00"),
    "AGENT_LOA": D("35.00"),
}
EVIDENCE_POINT_VALUE = D("7.50")
MAX_CREDITED_EVIDENCE_POINTS = 4
DOCUMENT_QUALITY_WEIGHT = D("0.20")
FRAUD_PENALTY_PER_FAILED_ATTEMPT = D("12.00")
PLATFORM_ASSERTED_FLOOR = D("70.00")
ASSURANCE_PASS_THRESHOLD = D("70.00")
ASSURANCE_INCONCLUSIVE_THRESHOLD = D("50.00")


def assurance(method, evidence_points_count, document_quality_score,
              failed_attempt_count, platform_assertion_reference,
              intake_channel):
    credited = min(int(evidence_points_count), MAX_CREDITED_EVIDENCE_POINTS)
    raw = (METHOD_BASE_SCORE[method]
           + EVIDENCE_POINT_VALUE * D(credited)
           + DOCUMENT_QUALITY_WEIGHT * D(document_quality_score))
    penalty = FRAUD_PENALTY_PER_FAILED_ATTEMPT * D(int(failed_attempt_count))
    platform_asserted = (method == "PLATFORM_ASSERTION"
                         and platform_assertion_reference is not None
                         and intake_channel == "STATE_PLATFORM")
    net = raw - penalty
    if platform_asserted:
        variant = "PLATFORM_ASSERTED"
        if net < PLATFORM_ASSERTED_FLOOR:
            net = PLATFORM_ASSERTED_FLOOR
    else:
        variant = "FRAUD_WEIGHTED"
        if net < D("0.00"):
            net = D("0.00")
    if net > D("100.00"):
        net = D("100.00")
    score = rhu(net, 2)
    if score >= ASSURANCE_PASS_THRESHOLD:
        outcome = "PASS"
    elif score >= ASSURANCE_INCONCLUSIVE_THRESHOLD:
        outcome = "INCONCLUSIVE"
    else:
        outcome = "FAIL"
    return {
        "variant_applied": variant,
        "raw_score": rhu(raw, 2),
        "fraud_penalty_applied": rhu(penalty, 2),
        "assurance_score": score,
        "outcome": outcome,
    }


# ------------------------------------------------ recipient reliability (6)
RELIABILITY_BASE = D("90.00")
RELIABILITY_ON_TIME_BONUS = D("2.00")
RELIABILITY_LATE_PENALTY = D("5.00")
RELIABILITY_FAIL_PENALTY = D("20.00")
RELIABILITY_WAIVE_PENALTY = D("25.00")
RELIABILITY_SUSPEND_THRESHOLD = D("70.00")


def reliability_score(on_time, late, failed, waived):
    raw = (RELIABILITY_BASE
           + RELIABILITY_ON_TIME_BONUS * D(int(on_time))
           - RELIABILITY_LATE_PENALTY * D(int(late))
           - RELIABILITY_FAIL_PENALTY * D(int(failed))
           - RELIABILITY_WAIVE_PENALTY * D(int(waived)))
    if raw < D("0.00"):
        raw = D("0.00")
    if raw > D("100.00"):
        raw = D("100.00")
    return rhu(raw, 2)


# --------------------------------------------------- completion ratio (7)
WAIVED_CREDIT_FRACTION = D("0.5")
COMPLETION_FULL = D("1.0000")
BREACH_RATIO_THRESHOLD = D("0.7500")


def completion_ratio(tasks):
    denominator = D("0")
    numerator = D("0")
    for task in tasks:
        weight = D(task["weight"])
        denominator += weight
        if task["status"] == "ACKED":
            numerator += weight
        elif task["status"] == "WAIVED":
            numerator += weight * WAIVED_CREDIT_FRACTION
    if denominator == D("0"):
        return rhu(COMPLETION_FULL, 4)
    return rhu(numerator / denominator, 4)


# ------------------------------------------------- regulator adequacy (9)
EVIDENCE_PER_CITATION = D("15.00")
MAX_CREDITED_CITATIONS = 5
COVERAGE_BONUS = D("15.00")
COVERAGE_BONUS_EVENT_TYPES = ["DELETION_REQUEST_RECEIVED", "DELETION_EXECUTED",
                              "SUPPRESSION_CREATED"]
LATE_RESPONSE_PENALTY = D("10.00")
ADEQUATE_THRESHOLD = D("65.00")
RESPONSE_GRACE_DAYS = 30


def deficiency_penalty_for(evidence_score):
    """Tier keyed on evidence_score, evaluated exactly once (PRD 3.8)."""
    if evidence_score >= D("80.00"):
        return D("0.00")
    if evidence_score >= D("60.00"):
        return D("8.00")
    if evidence_score >= D("40.00"):
        return D("20.00")
    return D("35.00")


def adequacy(cited_events, late):
    cited_count = len(cited_events)
    credited = min(cited_count, MAX_CREDITED_CITATIONS)
    credited_events = cited_events[:MAX_CREDITED_CITATIONS]
    present = set(e["event_type"] for e in credited_events)
    bonus = all(t in present for t in COVERAGE_BONUS_EVENT_TYPES)
    evidence = EVIDENCE_PER_CITATION * D(credited)
    if bonus:
        evidence += COVERAGE_BONUS
    if evidence > D("100.00"):
        evidence = D("100.00")
    evidence = rhu(evidence, 2)
    deficiency = deficiency_penalty_for(evidence)
    late_penalty = LATE_RESPONSE_PENALTY if late else D("0.00")
    adequacy_score = evidence - deficiency - late_penalty
    if adequacy_score < D("0.00"):
        adequacy_score = D("0.00")
    adequacy_score = rhu(adequacy_score, 2)
    verdict = "ADEQUATE" if adequacy_score >= ADEQUATE_THRESHOLD else "DEFICIENT"
    return {
        "cited_event_count": cited_count,
        "coverage_bonus_applied": bonus,
        "evidence_score": evidence,
        "deficiency_penalty": rhu(deficiency, 2),
        "late_response_penalty": rhu(late_penalty, 2),
        "adequacy_score": adequacy_score,
        "adequacy_verdict": verdict,
    }
