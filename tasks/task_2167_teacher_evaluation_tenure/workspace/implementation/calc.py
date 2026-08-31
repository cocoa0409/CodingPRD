"""Pure calculation rules (SCAFFOLD 1.3 / PRD 2.6, 3.2, 3.4-3.6, 3.9)."""
from decimal import Decimal

from store import D, round_half_up

SCORE_FLOOR = Decimal("1.00")
SCORE_CEILING = Decimal("4.00")
MISSING_OBSERVATION_FLOOR = Decimal("1.00")
FORMAL_SHARE = Decimal("0.75")
INFORMAL_SHARE = Decimal("0.25")
RELIABILITY_FLOOR = Decimal("0.60")
EVIDENCE_BONUS = Decimal("0.05")
EVIDENCE_PENALTY = Decimal("-0.10")
INFORMAL_STIPEND_RATIO = Decimal("0.4")
CALIBRATION_ROLLING_WINDOW = 3
CERTIFICATION_TERM_DAYS = 365
DAYS_PER_SERVICE_YEAR = 365
DISTRIBUTION_OUTLIER_PCT = Decimal("35.00")

DOMAIN_ORDER = ("PLANNING", "ENVIRONMENT", "INSTRUCTION", "PROFESSIONALISM")
DOMAIN_WEIGHT_FIELD = {
    "PLANNING": "planning_weight_pct",
    "ENVIRONMENT": "environment_weight_pct",
    "INSTRUCTION": "instruction_weight_pct",
    "PROFESSIONALISM": "professionalism_weight_pct",
}


def band(score, policy):
    """PRD 3.6 -- every comparison is inclusive at the threshold."""
    if score is None:
        return None
    value = D(score)
    if value >= D(policy["highly_effective_threshold"]):
        return "HIGHLY_EFFECTIVE"
    if value >= D(policy["effective_threshold"]):
        return "EFFECTIVE"
    if value >= D(policy["developing_threshold"]):
        return "DEVELOPING"
    return "INEFFECTIVE"


def domain_factor(observation, policy):
    if observation["observation_type"] == "FORMAL" and observation["announced"] is False:
        return D(policy["unannounced_multiplier"])
    return Decimal("1.00")


def weighted_contribution(raw_score, domain_code, observation, policy):
    weight = D(policy[DOMAIN_WEIGHT_FIELD[domain_code]])
    factor = domain_factor(observation, policy)
    return round_half_up(D(raw_score) * weight * factor / Decimal(100), 2)


def observation_weighted_score(contributions_by_domain, observation, policy):
    """Sum the four ALREADY-ROUNDED contributions in the pinned domain order."""
    base = Decimal("0.00")
    for domain in DOMAIN_ORDER:
        base += contributions_by_domain[domain]
    cap = D(policy["informal_cap"]) if observation["observation_type"] == "INFORMAL" else SCORE_CEILING
    return base if base < cap else cap


def _mean4(pool):
    total = Decimal(0)
    for value in pool:
        total += D(value)
    return round_half_up(total / Decimal(len(pool)), 4)


def observation_component(formal_scores, informal_scores, policy, variant):
    formal_pool = [D(s) for s in formal_scores]
    informal_pool = [D(s) for s in informal_scores]
    if variant == "FINAL":
        missing_formal = int(policy["required_formal_count"]) - len(formal_pool)
        for _ in range(max(0, missing_formal)):
            formal_pool.append(MISSING_OBSERVATION_FLOOR)
        missing_informal = int(policy["required_informal_count"]) - len(informal_pool)
        for _ in range(max(0, missing_informal)):
            informal_pool.append(MISSING_OBSERVATION_FLOOR)
    formal_avg = _mean4(formal_pool) if formal_pool else None
    informal_avg = _mean4(informal_pool) if informal_pool else None
    if formal_avg is None and informal_avg is None:
        return None
    if informal_avg is None:
        return formal_avg
    if formal_avg is None:
        return informal_avg
    return round_half_up(FORMAL_SHARE * formal_avg + INFORMAL_SHARE * informal_avg, 4)


def growth_component(certified_measures):
    if not certified_measures:
        return None
    coverage_total = Decimal(0)
    weighted_sum = Decimal(0)
    for measure in certified_measures:
        coverage = D(measure["coverage_pct"])
        coverage_total += coverage
        weighted_sum += D(measure["index_value"]) * coverage
    if coverage_total == 0:
        return None
    weighted_index = weighted_sum / coverage_total
    capped = coverage_total if coverage_total < Decimal(100) else Decimal(100)
    reliability = capped / Decimal(100)
    if reliability > Decimal("1.00"):
        reliability = Decimal("1.00")
    if reliability < RELIABILITY_FLOOR:
        reliability = RELIABILITY_FLOOR
    return round_half_up(Decimal("1.00") + (weighted_index - Decimal("1.00")) * reliability, 4)


def composite_pre(obs_component, growth_comp, policy):
    ow = D(policy["observation_weight_pct"]) / Decimal(100)
    gw = D(policy["growth_weight_pct"]) / Decimal(100)
    if obs_component is None and growth_comp is None:
        return None
    if growth_comp is None:
        raw = D(obs_component)
    elif obs_component is None:
        raw = D(growth_comp)
    else:
        raw = D(obs_component) * ow + D(growth_comp) * gw
    return round_half_up(raw, 2)


def evidence_sufficiency_adjustment(pre, evidence_artifact_count, policy):
    """Returns (adjustment, adjusted_score).  Keyed on the PRE-adjustment band."""
    if pre is None:
        return Decimal("0.00"), None
    pre_band = band(pre, policy)
    if int(evidence_artifact_count) >= int(policy["evidence_min_artifacts"]):
        adjustment = EVIDENCE_BONUS if pre_band in ("DEVELOPING", "INEFFECTIVE") else Decimal("0.00")
    else:
        adjustment = EVIDENCE_PENALTY if pre_band in ("EFFECTIVE", "HIGHLY_EFFECTIVE") else Decimal("0.00")
    adjusted = D(pre) + adjustment
    if adjusted < SCORE_FLOOR:
        adjusted = SCORE_FLOOR
    if adjusted > SCORE_CEILING:
        adjusted = SCORE_CEILING
    return adjustment, round_half_up(adjusted, 2)


def calibration_drift(decided_reviews):
    """decided_reviews ordered by created_at ASC.  Returns (rolling, anchor)."""
    if not decided_reviews:
        return Decimal("0.00"), Decimal("0.00")
    window = decided_reviews[-CALIBRATION_ROLLING_WINDOW:]
    total = Decimal(0)
    for review in window:
        total += D(review["deviation"])
    rolling = round_half_up(total / Decimal(len(window)), 2)
    anchor = round_half_up(D(decided_reviews[-1]["deviation"]), 2)
    return rolling, anchor


def stipend_for(observation, policy):
    base = int(policy["observation_stipend_cents"])
    if observation["observation_type"] == "FORMAL":
        return base
    return int(round_half_up(D(base) * INFORMAL_STIPEND_RATIO, 0))


def service_years(service_start, today):
    days = (today - service_start).days
    if days < 0:
        return 0
    return days // DAYS_PER_SERVICE_YEAR


def pct(count, total):
    if total == 0:
        return Decimal("0.00")
    return round_half_up(D(count) * Decimal(100) / D(total), 2)
