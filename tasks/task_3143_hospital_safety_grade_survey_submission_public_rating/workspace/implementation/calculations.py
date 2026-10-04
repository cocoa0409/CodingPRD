"""Every calculation rule declared by the scaffold, implemented verbatim."""

from decimal import Decimal

from db import round_half_up, to_decimal

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DOMAINS = [
    "PATIENT_SAFETY",
    "INFECTION_PREVENTION",
    "CPOE",
    "STAFFING",
    "SURGICAL_VOLUME",
]

MEASURE_ROUND_DP = 1
DOMAIN_ROUND_DP = 2

STANDARDIZATION_MIDPOINT = Decimal("50.00")
STANDARDIZATION_SPAN = Decimal("15.00")
SCORE_FLOOR = Decimal("0.00")
SCORE_CEILING = Decimal("100.00")
COMPOSITE_ROUND_DP = 2
MAX_RENORMALIZATION_PASSES = 1

CUT_A = Decimal("85.00")
CUT_B = Decimal("62.50")
CUT_C = Decimal("45.00")
CUT_D = Decimal("30.00")
RELIABILITY_CAP_THRESHOLD = Decimal("0.60")

DOWNGRADE = {"A": "B", "B": "C", "C": "D", "D": "F", "F": "F"}
LETTER_ORDER = ["A", "B", "C", "D", "F"]
LETTER_RANKS = {"A": 4, "B": 3, "C": 2, "D": 1, "F": 0, None: 0}

SAMPLE_RATE_FULL = Decimal("0.50")
SAMPLE_RATE_PARTIAL = Decimal("0.25")
BASE_FULL = Decimal("1.00")
BASE_PARTIAL = Decimal("0.60")
BASE_NONE = Decimal("0.00")
RESPONDENT_SCALE_CAP = 500
COVERAGE_FLOOR = Decimal("0.50")
GRADE_CAP_THRESHOLD = Decimal("0.60")
VERIFICATION_FLOOR = Decimal("0.10")

DROPPED_MEASURE_POINT_PENALTY = Decimal("4.00")
ADJUSTED_ROUND_DP = 2

INVERSE_BOUND = Decimal("1.00")
BED_DIVISOR = Decimal("100")

COMPARABILITY_FLOOR = Decimal("0.80")
INDEX_ROUND_DP = 4

PROPENSITY_BASE = Decimal("34.00")
PROPENSITY_SLOPE = Decimal("0.60")
PROPENSITY_MIDPOINT = Decimal("50.00")

REQUIRED_CREDIT_COUNT = 8
REQUIRED_DOCUMENT_CODE_COUNT = 10
CREDIT_ROUND_DP = 4

REQUIRED_CREDIT_CODES = [
    "HAND_HYGIENE",
    "ICU_STAFFING",
    "BARCODE_MED_ADMIN",
    "SAFE_SURGERY_CHECKLIST",
    "CAUTI_BUNDLE",
    "CLABSI_BUNDLE",
    "VTE_PROPHYLAXIS",
    "MRSA_SCREENING",
]

DERIVATION_RULES = ["NONE", "RATE_TO_COUNT_FLOOR", "INVERSE_BOUNDED", "PER_100_BEDS_FLOOR"]


# ---------------------------------------------------------------------------
# derived_measure_value
# ---------------------------------------------------------------------------

def derived_measure_value(raw_value, derivation_rule):
    """Convert a raw value under the pinned derivation rule."""
    if raw_value is None:
        return None
    raw = to_decimal(raw_value)
    if derivation_rule == "NONE":
        return raw
    if derivation_rule == "RATE_TO_COUNT_FLOOR":
        return Decimal(int(raw.to_integral_value(rounding="ROUND_FLOOR")))
    if derivation_rule == "INVERSE_BOUNDED":
        return round_half_up(INVERSE_BOUND - raw, 4)
    if derivation_rule == "PER_100_BEDS_FLOOR":
        return Decimal(int((raw / BED_DIVISOR).to_integral_value(rounding="ROUND_FLOOR")))
    return raw


# ---------------------------------------------------------------------------
# domain_measure_rollup
# ---------------------------------------------------------------------------

def domain_measure_rollup(available, measure_definitions):
    """Bucket converted values by domain and average each bucket.

    `available` maps measure_code -> (derived_value, measure_status).
    A measure that was neither submitted nor sourced is skipped entirely: it
    contributes nothing and is not averaged.
    """
    buckets = {domain: [] for domain in DOMAINS}
    emitted = set()
    for definition in measure_definitions:
        code = definition["measure_code"]
        entry = available.get(code)
        if entry is None:
            continue
        derived_value, status = entry
        if status == "UNREPORTED_EXCLUDED" or derived_value is None:
            continue
        converted = to_decimal(derived_value) * to_decimal(definition.get("scale_factor", 1))
        converted_rounded = round_half_up(converted, MEASURE_ROUND_DP)
        bucket = buckets.get(definition["domain"])
        if bucket is not None:
            bucket.append(converted_rounded)

    # PRD §2.10: "The array's order is the evaluation order for the domain
    # rollup and for the composite", and §3.5 stores the run's `domain_scores`
    # "in the pinned definition order" — so a domain is emitted at the position
    # where the pinned array first declares it, not in the taxonomy's own order.
    domain_scores = []
    for definition in measure_definitions:
        domain = definition.get("domain")
        if domain in emitted or domain not in buckets:
            continue
        bucket = buckets[domain]
        emitted.add(domain)
        if not bucket:
            continue
        total = sum(bucket, Decimal("0"))
        score = round_half_up(total / Decimal(len(bucket)), DOMAIN_ROUND_DP)
        domain_scores.append({"domain": domain, "domain_score": score})
    return domain_scores


def domain_scores_map(domain_scores):
    return {entry["domain"]: to_decimal(entry["domain_score"]) for entry in domain_scores}


# ---------------------------------------------------------------------------
# composite_score
# ---------------------------------------------------------------------------

def _domain_reference(measure_definitions):
    """Per-domain weight, multiplier, peer_mean and peer_sd from the version."""
    refs = {}
    for definition in measure_definitions:
        domain = definition.get("domain")
        if domain not in DOMAINS:
            continue
        weight = to_decimal(definition.get("weight", 0) or 0)
        # PRD §2.10 declares the measure-definition field as `multiplier`, and
        # PRD §3.5 multiplies "the domain's `weight` and ... the domain's
        # multiplier" into the term. Reading a different key silently defaults
        # every multiplier to 1 and inflates the composite.
        multiplier = to_decimal(definition.get("multiplier", 1) or 1)
        peer_mean = definition.get("peer_mean")
        peer_sd = definition.get("peer_sd")
        refs[domain] = {
            "weight": weight,
            "multiplier": multiplier,
            "peer_mean": to_decimal(peer_mean) if peer_mean is not None else None,
            "peer_sd": to_decimal(peer_sd) if peer_sd is not None else None,
        }
    return refs


def _standardize(domain_score, peer_mean, peer_sd):
    if peer_sd is None or peer_sd == 0:
        raw = STANDARDIZATION_MIDPOINT
    else:
        raw = STANDARDIZATION_MIDPOINT + STANDARDIZATION_SPAN * (
            to_decimal(domain_score) - to_decimal(peer_mean)
        ) / to_decimal(peer_sd)
    if raw < SCORE_FLOOR:
        return SCORE_FLOOR
    if raw > SCORE_CEILING:
        return SCORE_CEILING
    return raw


def _retained_domain_order(measure_definitions):
    """Domains in pinned definition order, de-duplicated."""
    order = []
    for definition in measure_definitions:
        domain = definition.get("domain")
        if domain in DOMAINS and domain not in order:
            order.append(domain)
    return order


def composite_score(measure_definitions, domain_scores):
    """Peer-standardized, weight-renormalised average.

    A domain whose measures are all excluded never appears in `domain_scores`
    and therefore contributes neither a numerator term nor a denominator
    weight. Exactly one rounding, at the very end.
    """
    scores = domain_scores_map(domain_scores)
    refs = _domain_reference(measure_definitions)
    order = _retained_domain_order(measure_definitions)

    numerator = Decimal("0")
    denominator = Decimal("0")
    terms = []
    for domain in order:
        if domain not in scores:
            continue
        ref = refs.get(domain)
        if ref is None:
            continue
        standardized = _standardize(scores[domain], ref["peer_mean"], ref["peer_sd"])
        effective_weight = ref["weight"] * ref["multiplier"]
        if effective_weight == 0:
            continue
        term = standardized * effective_weight
        numerator += term
        denominator += effective_weight
        terms.append({
            "domain": domain,
            "standardized_score": standardized,
            "term": term,
        })
    if denominator == 0:
        return None, terms
    composite = round_half_up(numerator / denominator, COMPOSITE_ROUND_DP)
    return composite, terms


# ---------------------------------------------------------------------------
# grade_assignment
# ---------------------------------------------------------------------------

def base_letter_for(composite):
    if composite is None:
        return None
    composite = to_decimal(composite)
    if composite >= CUT_A:
        return "A"
    if composite >= CUT_B:
        return "B"
    if composite >= CUT_C:
        return "C"
    if composite >= CUT_D:
        return "D"
    return "F"


def grade_assignment(composite, reliability_weight):
    """Return (base_letter, letter_grade, grade_cap_applied)."""
    base_letter = base_letter_for(composite)
    if base_letter is None:
        return None, None, False
    if reliability_weight is None:
        return base_letter, base_letter, False
    if to_decimal(reliability_weight) >= RELIABILITY_CAP_THRESHOLD:
        return base_letter, base_letter, False
    return base_letter, DOWNGRADE[base_letter], True


# ---------------------------------------------------------------------------
# survey_certification_reliability
# ---------------------------------------------------------------------------

def sample_rate_of(completed_survey_count, entity_annual_discharges):
    if entity_annual_discharges is None or to_decimal(entity_annual_discharges) == 0:
        return None
    return round_half_up(
        to_decimal(completed_survey_count) / to_decimal(entity_annual_discharges), 4
    )


def survey_certification_reliability(started_survey_count, completed_survey_count,
                                     entity_annual_discharges, verification_cycle=0):
    """Return (reliability_weight, grade_cap_applied, verification_complete)."""
    rate = sample_rate_of(completed_survey_count, entity_annual_discharges)
    if rate is None:
        rate = Decimal("0.0000")
    if rate >= SAMPLE_RATE_FULL:
        base = BASE_FULL
    elif rate >= SAMPLE_RATE_PARTIAL:
        base = BASE_PARTIAL
    else:
        base = BASE_NONE

    capped_started = min(int(started_survey_count or 0), RESPONDENT_SCALE_CAP)
    coverage = COVERAGE_FLOOR + Decimal("0.50") * to_decimal(capped_started) / Decimal(RESPONDENT_SCALE_CAP)
    weight = round_half_up(base * coverage, 4)
    return weight, (weight < GRADE_CAP_THRESHOLD), (rate >= VERIFICATION_FLOOR)


# ---------------------------------------------------------------------------
# composite_adjusted_for_reanalysis
# ---------------------------------------------------------------------------

def composite_adjusted_for_reanalysis(preliminary_composite, reanalysis_deltas,
                                      dropped_measure_count, correction_deltas):
    """Frozen preliminary composite plus signed adjustments, minus the penalty."""
    adjusted = to_decimal(preliminary_composite)
    for delta in reanalysis_deltas:
        adjusted += to_decimal(delta)
    adjusted -= DROPPED_MEASURE_POINT_PENALTY * Decimal(int(dropped_measure_count or 0))
    for delta in correction_deltas:
        adjusted += to_decimal(delta)
    return round_half_up(adjusted, ADJUSTED_ROUND_DP)


# ---------------------------------------------------------------------------
# methodology_comparability_index
# ---------------------------------------------------------------------------

def methodology_comparability_index(later_definitions, earlier_definitions):
    """Denominator is the EARLIER version's measure-tree size."""
    if earlier_definitions is None:
        return None
    if len(earlier_definitions) == 0:
        return None
    earlier_rules = {}
    for definition in earlier_definitions:
        earlier_rules[definition.get("measure_code")] = definition.get("derivation_rule")
    later_rules = {}
    for definition in later_definitions:
        later_rules[definition.get("measure_code")] = definition.get("derivation_rule")

    matched = 0
    total = 0
    for code, rule in earlier_rules.items():
        total += 1
        if code in later_rules and later_rules[code] == rule:
            matched += 1
    return round_half_up(Decimal(matched) / Decimal(total), INDEX_ROUND_DP)


def is_comparable(index):
    if index is None:
        return False
    return to_decimal(index) >= COMPARABILITY_FLOOR


# ---------------------------------------------------------------------------
# employer_utilization_index
# ---------------------------------------------------------------------------

def employer_utilization_index(minimum_acceptable_letter, graded_letters, graded_composites):
    """Return (eligible_hospital_count, utilization_index, propensity_adjusted)."""
    floor_rank = LETTER_RANKS.get(minimum_acceptable_letter, 0)
    eligible = 0
    for letter in graded_letters:
        if LETTER_RANKS.get(letter, 0) >= floor_rank:
            eligible += 1
    denominator = len(graded_letters)
    if denominator == 0:
        index = Decimal("0.0000")
    else:
        index = round_half_up(Decimal(eligible) / Decimal(denominator), 4)

    propensity = None
    for composite in graded_composites:
        if composite is None:
            continue
        propensity = round_half_up(
            PROPENSITY_BASE + PROPENSITY_SLOPE * (to_decimal(composite) - PROPENSITY_MIDPOINT), 4
        )
        break
    return eligible, index, propensity


# ---------------------------------------------------------------------------
# safe_practice_credit
# ---------------------------------------------------------------------------

def safe_practice_credit(earned_credit_codes):
    earned = len(set(earned_credit_codes) & set(REQUIRED_CREDIT_CODES))
    return round_half_up(Decimal(earned) / Decimal(REQUIRED_CREDIT_COUNT), CREDIT_ROUND_DP)


def verification_completeness(document_codes):
    distinct = len(set(document_codes))
    return round_half_up(Decimal(distinct) / Decimal(REQUIRED_DOCUMENT_CODE_COUNT), CREDIT_ROUND_DP)


def documents_sufficient(document_codes):
    """True when at least six distinct document codes were supplied."""
    return len(set(document_codes)) >= 6


# ---------------------------------------------------------------------------
# embargo_release_readiness
# ---------------------------------------------------------------------------

def embargo_release_readiness(grade_statuses, review_statuses, correction_statuses,
                              now, publication_date, publish_executed):
    """publishable uses an at-or-after comparison against publication_date."""
    every_grade_resolved = all(
        status in ("SCORED", "CORRECTED", "CHAR_EXEMPT") for status in grade_statuses
    )
    no_review_pending = all(status != "PENDING" for status in review_statuses)
    no_correction_open = all(status not in ("PENDING", "ACCEPTED") for status in correction_statuses)
    clock_ok = now >= publication_date
    publishable = every_grade_resolved and no_review_pending and no_correction_open and clock_ok
    return publishable, (publishable and publish_executed)