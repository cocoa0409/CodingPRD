"""The calculation rules of PRD §2.9 / §3.

Rounding is round-half-up at two decimal places wherever the PRD pins it;
comparisons against boundaries are made at full precision unless the PRD says
otherwise.
"""

from decimal import Decimal

import db
from services.common import rounded2

# --------------------------------------------------------------------------
# clinical_review_outcome
# --------------------------------------------------------------------------

FAIL_COVERAGE_THRESHOLD = Decimal("0.80")
OUTCOME_SCORE_CEILING = Decimal("10.0")


def clinical_review_outcome(submission, review_outcome_input, reviewer_deficiency_category):
    """Return (outcome, deficiency_code, score) for a submission leaving PENDING_REVIEW.

    Precedence: reviewer-reported FAIL, then coverage below 0.80, then coverage
    below 1.0, then full coverage.
    """
    required = Decimal(str(submission["required_view_count"]))
    accepted = Decimal(str(submission["accepted_view_count"]))
    coverage = accepted / required

    if review_outcome_input == "FAIL":
        return "FAIL", "IMAGE_QUALITY", Decimal("0.0")
    if review_outcome_input == "ACCEPT_WITH_DEFICIENCY":
        code = reviewer_deficiency_category or "IMAGE_QUALITY"
        return "ACCEPT_WITH_DEFICIENCY", code, rounded2(coverage * Decimal("10.0"))
    if coverage < FAIL_COVERAGE_THRESHOLD:
        return "FAIL", "IMAGE_QUALITY", Decimal("0.0")
    if coverage < Decimal("1.0"):
        code = reviewer_deficiency_category or "IMAGE_QUALITY"
        return "ACCEPT_WITH_DEFICIENCY", code, rounded2(coverage * Decimal("10.0"))
    return "ACCEPT", "NONE", OUTCOME_SCORE_CEILING


# --------------------------------------------------------------------------
# phantom_composite_score
# --------------------------------------------------------------------------

PHANTOM_PASS_THRESHOLD = Decimal("7.0")


def phantom_composite_score(spatial, contrast, artifact):
    total = Decimal(str(spatial)) + Decimal(str(contrast)) + Decimal(str(artifact))
    return rounded2(total / Decimal("3"))


def phantom_passed(phantom_total_score):
    """The rounded value is compared against the threshold."""
    return Decimal(str(phantom_total_score)) >= PHANTOM_PASS_THRESHOLD


# --------------------------------------------------------------------------
# survey_dose_deviation
# --------------------------------------------------------------------------

ABSOLUTE_DEVIATION_LIMIT_PCT = Decimal("10.0")
FULL_CREDIT_BAND_PCT = Decimal("5.0")


def survey_dose_deviation(reference, measured):
    deviation = (Decimal(str(measured)) - Decimal(str(reference))) / Decimal(str(reference)) * Decimal("100")
    return rounded2(deviation)


def dose_weight(deviation_pct):
    """Banded weight variant, judged against the rounded deviation."""
    magnitude = abs(Decimal(str(deviation_pct)))
    if magnitude <= FULL_CREDIT_BAND_PCT:
        return Decimal("1.0")
    if magnitude <= ABSOLUTE_DEVIATION_LIMIT_PCT:
        return Decimal("0.5")
    return Decimal("0.0")


def mean_of_band_weights(deviation_pct):
    """mean_of_bands variant: a survey inside the 10 % band reports 0.75."""
    magnitude = abs(Decimal(str(deviation_pct)))
    if magnitude <= FULL_CREDIT_BAND_PCT:
        return Decimal("1.0")
    if magnitude <= ABSOLUTE_DEVIATION_LIMIT_PCT:
        return Decimal("0.75")
    return Decimal("0.0")


# --------------------------------------------------------------------------
# random_site_audit_selection
# --------------------------------------------------------------------------

AUDIT_MANDATORY_CYCLE_PERIOD = 5
AUDIT_FAILING_SURVEY_TRIGGER = 2


def random_site_audit_selection(cycle, facility):
    failing = sum(
        1 for s in db.SURVEYS.values()
        if s["facility_id"] == facility["id"]
        and s["survey_status"] in ("REJECTED", "CORRECTIVE_REQUIRED")
    )
    if cycle["cycle_index"] % AUDIT_MANDATORY_CYCLE_PERIOD == 0:
        return "SELECTED"
    if failing >= AUDIT_FAILING_SURVEY_TRIGGER:
        return "SELECTED"
    if facility["rejected_survey_count"] >= 1:
        return "SELECTED"
    return "WAIVED"


# --------------------------------------------------------------------------
# registry_benchmark_classification
# --------------------------------------------------------------------------

WITHIN_BENCHMARK_RATIO = Decimal("1.00")
ABOVE_BENCHMARK_RATIO = Decimal("1.35")

MODALITY_CATEGORY_COMPARISON = {
    "MRI": Decimal("2.0"),
    "CT": Decimal("2.3"),
    "MAMM": Decimal("2.5"),
    "PET": Decimal("3.0"),
    "US": Decimal("2.2"),
}


def _submitted_peers(record, exclude_self=True):
    peers = []
    for other in db.DOSE_RECORDS.values():
        if other["unit_id"] != record["unit_id"]:
            continue
        if other["exam_category_code"] != record["exam_category_code"]:
            continue
        if other["submission_status"] != "SUBMITTED":
            continue
        if exclude_self and other["id"] == record["id"]:
            continue
        peers.append(other)
    return peers


def registry_benchmark_classification(record):
    """Return (benchmark_status, comparison_value) for a record being submitted."""
    unit = db.MODALITY_UNITS.get(record["unit_id"])
    modality_code = unit["modality_code"] if unit else None
    peers = _submitted_peers(record)
    if not peers:
        comparison = MODALITY_CATEGORY_COMPARISON.get(modality_code, Decimal("1.0"))
    else:
        comparison = max(Decimal(str(p["benchmark_comparison_value"])) for p in peers)
    ratio = Decimal(str(record["dose_index_value"])) / comparison
    if ratio <= WITHIN_BENCHMARK_RATIO:
        status = "WITHIN_BENCHMARK"
    elif ratio <= ABOVE_BENCHMARK_RATIO:
        status = "ABOVE_BENCHMARK"
    else:
        status = "CRITICAL"
    return status, comparison


# --------------------------------------------------------------------------
# facility_dose_index_benchmark
# --------------------------------------------------------------------------

def unit_submit_rank(record):
    """Ordering used when a unit's reported average is re-derived.

    Records submitted into the registry carry their fee; records still in
    flight tie on that key and are separated by creation order.
    """
    return (record.get("registry_fee_cents") or 0, record.get("created_at"))


def facility_dose_index_benchmark(record):
    """Unit-and-category dose index average, the record under test included.

    A unit already holding one submitted `CT_HEAD` record at `2.3` that then
    receives a `2.7` averages to `2.50`; leaving the record under test out of
    its own average would leave the same rows at `2.30`.
    """
    index_total = Decimal("0")
    count = 0
    for other in db.DOSE_RECORDS.values():
        if other["unit_id"] != record["unit_id"]:
            continue
        if other["exam_category_code"] != record["exam_category_code"]:
            continue
        if other["submission_status"] != "SUBMITTED":
            continue
        index_total += Decimal(str(other["dose_index_value"]))
        count += 1
    if count == 0:
        return Decimal("0")
    return index_total / Decimal(count)