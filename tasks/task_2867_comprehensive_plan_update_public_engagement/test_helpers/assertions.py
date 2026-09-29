"""Domain assertions and reference calculators.

The calculators here re-implement the PRD's arithmetic exactly as written so that
a test can state an expected figure either as a literal or as a derivation, and
the two must agree. PRD section 2.6: "All rounding in this system is round half up,
and every rule below states exactly where the rounding happens, because rounding
at a different step produces a different answer."
"""

import re
from decimal import ROUND_HALF_UP, Decimal
from typing import Dict, Iterable, List, Optional, Sequence

from prd_bench_local_runner.testing import is_valid_uuid

from .constants import (
    CREDIT_HIGH_RATE,
    CREDIT_HIGH_THRESHOLD,
    CREDIT_MID_RATE,
    CREDIT_MID_THRESHOLD,
    IMPACT_WEIGHT_GHG,
    IMPACT_WEIGHT_HABITAT,
    IMPACT_WEIGHT_TRAFFIC,
    IMPACT_WEIGHT_WATER,
    JOBS_PER_HOUSEHOLD,
    MARKET_SOFTNESS_FACTOR,
    TIER_ORDER,
    TIER_SHARES,
    UNDERREPRESENTED_GROUPS,
    UNDERUTILIZED_REALIZATION_SHARE,
    VACANCY_MARGIN_FACTOR,
)

_THREE_DIGIT_INSTANT = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$"
)


# --------------------------------------------------------------------- rounding
def round_half_up(value, places: int = 0):
    """Round half up to `places` decimal places, PRD section 2.6."""
    quant = Decimal(1).scaleb(-places)
    result = Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP)
    return int(result) if places == 0 else float(result)


# ------------------------------------------------------------------- timestamps
def assert_three_digit_instant(value, field: str = "timestamp") -> None:
    """Every instant the service emits carries exactly three fractional digits + Z."""
    assert isinstance(value, str), f"{field} must be a string, got {value!r}"
    assert _THREE_DIGIT_INSTANT.match(value), (
        f"{field} must be ISO 8601 UTC with three fractional digits, got {value!r}"
    )


def assert_instant_equals(actual, expected, field: str = "timestamp") -> None:
    """Compare two instants after normalising fractional-second width."""
    from .api_client import canonical_instant

    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{field}: expected {expected!r}, got {actual!r}"
    )


def assert_envelope_meta_timestamp(response) -> None:
    body = response.json()
    ts = body["meta"]["api_request_timestamp"]
    assert_three_digit_instant(ts, "meta.api_request_timestamp")
    assert body["meta"]["api_request_id"].startswith("req_"), (
        f"api_request_id must start with 'req_', got {body['meta']['api_request_id']!r}"
    )


# ------------------------------------------------------------------- row shapes
def assert_versioned_row(row: Dict, expected_version: Optional[int] = None) -> None:
    assert is_valid_uuid(row["id"]), f"id must be a UUID, got {row['id']!r}"
    assert_three_digit_instant(row["created_at"], "created_at")
    assert_three_digit_instant(row["updated_at"], "updated_at")
    assert isinstance(row["version"], int), "version must be an integer"
    if expected_version is not None:
        assert row["version"] == expected_version, (
            f"expected version {expected_version}, got {row['version']}"
        )


def assert_config_row(row: Dict) -> None:
    """A Venue or ParticipationRecord: id + created_at, and no version machinery.

    PRD section 2.4: "A Venue carries only id and created_at: it has no updated_at
    and no version, and there is no endpoint that modifies one."
    """
    assert is_valid_uuid(row["id"]), f"id must be a UUID, got {row['id']!r}"
    assert_three_digit_instant(row["created_at"], "created_at")
    assert "updated_at" not in row, "a config row must not expose updated_at"
    assert "version" not in row, "a config row must not expose version"


def assert_created_equals_updated(row: Dict) -> None:
    assert_instant_equals(row["updated_at"], row["created_at"], "updated_at")


# ------------------------------------------------------------------- precision
def assert_one_decimal(value, field: str = "value") -> None:
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{field} must be a JSON number, got {value!r}"
    )
    assert round(float(value), 1) == float(value), (
        f"{field} must carry one decimal place, got {value!r}"
    )


def assert_two_decimals(value, field: str = "value") -> None:
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{field} must be a JSON number, got {value!r}"
    )
    assert round(float(value), 2) == float(value), (
        f"{field} must carry two decimal places, got {value!r}"
    )


def assert_whole_units(value, field: str = "value") -> None:
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{field} must be a whole unit count, got {value!r}"
    )


# ------------------------------------------------------------- land capacity
def expected_gross_capacity(vacant, underutilized, density) -> int:
    """"the vacant acreage plus the underutilized acreage, multiplied by the
    allowed density per acre, and that single product is rounded half up"."""
    return round_half_up((Decimal(str(vacant)) + Decimal(str(underutilized)))
                         * Decimal(str(density)))


def expected_net_capacity(vacant, underutilized, constrained, density) -> int:
    """The three NET_CAPACITY discounts of PRD section 3.2, rounded once at the end."""
    acreage = (Decimal(str(vacant)) - Decimal(str(constrained))) + (
        Decimal(str(underutilized)) * Decimal(str(UNDERUTILIZED_REALIZATION_SHARE))
    )
    return round_half_up(acreage * Decimal(str(density))
                         * Decimal(str(MARKET_SOFTNESS_FACTOR)))


def expected_projected_demand(
    method: str,
    base_households: int,
    rate: float,
    horizon_year: int,
    base_year: int,
    job_growth_total: int,
    demolition_replacement_units: int,
) -> int:
    """PRD section 3.2: household growth, job-driven households and the selected
    driver "are all carried at full precision; rounding any of them first changes
    the answer"."""
    years = horizon_year - base_year
    bh = Decimal(str(base_households))
    household_growth = bh * (Decimal(1) + Decimal(str(rate))) ** years - bh
    job_driven = Decimal(str(job_growth_total)) / Decimal(str(JOBS_PER_HOUSEHOLD))
    driver = household_growth if method == "TREND" else max(household_growth, job_driven)
    total = (driver + Decimal(str(demolition_replacement_units))) * Decimal(
        str(VACANCY_MARGIN_FACTOR)
    )
    return round_half_up(total)


def expected_capacity_gap(projected_demand: int, land_capacity: int) -> int:
    """"the projected demand less the land capacity, floored at zero"."""
    return max(0, projected_demand - land_capacity)


# ------------------------------------------------------------------- waterfall
def expected_waterfall(pool: int, assigned: Dict[str, Optional[int]]) -> Dict[str, Dict]:
    """Run the capacity waterfall of PRD section 3.3 over the four statutory tiers.

    `assigned` maps income tier to assigned_units, omitting tiers with no row.
    Returns tier -> {tier_capacity_units, carryover_in_units, accommodated_units,
    shortfall_units}. Tiers with no row are absent from the result.
    """
    carryover = 0
    out: Dict[str, Dict] = {}
    for tier in TIER_ORDER:
        if tier not in assigned or assigned[tier] is None:
            continue
        tier_capacity = round_half_up(
            Decimal(str(pool)) * Decimal(str(TIER_SHARES[tier]))
        )
        available = tier_capacity + carryover
        accommodated = min(assigned[tier], available)
        out[tier] = {
            "tier_capacity_units": tier_capacity,
            "carryover_in_units": carryover,
            "accommodated_units": accommodated,
            "shortfall_units": assigned[tier] - accommodated,
        }
        carryover = available - accommodated
    return out


def expected_shortfall_total(pool: int, assigned: Dict[str, Optional[int]]) -> int:
    rows = expected_waterfall(pool, assigned)
    return sum(row["shortfall_units"] for row in rows.values())


# --------------------------------------------------------------- impact scores
def expected_raw_impact_score(traffic, ghg, habitat, water) -> float:
    weighted = (
        Decimal(str(traffic)) * Decimal(str(IMPACT_WEIGHT_TRAFFIC))
        + Decimal(str(ghg)) * Decimal(str(IMPACT_WEIGHT_GHG))
        + Decimal(str(habitat)) * Decimal(str(IMPACT_WEIGHT_HABITAT))
        + Decimal(str(water)) * Decimal(str(IMPACT_WEIGHT_WATER))
    )
    return round_half_up(weighted, 2)


def expected_mitigation_credit(raw_score: float) -> float:
    """"a tier keyed on the raw score and never on the net score"."""
    raw = Decimal(str(raw_score))
    if raw >= Decimal(str(CREDIT_HIGH_THRESHOLD)):
        return round_half_up(raw * Decimal(str(CREDIT_HIGH_RATE)), 2)
    if raw >= Decimal(str(CREDIT_MID_THRESHOLD)):
        return round_half_up(raw * Decimal(str(CREDIT_MID_RATE)), 2)
    return 0.00


def expected_net_impact_score(raw_score: float, credit: float) -> float:
    return round_half_up(Decimal(str(raw_score)) - Decimal(str(credit)), 2)


def expected_impact_triple(traffic, ghg, habitat, water):
    raw = expected_raw_impact_score(traffic, ghg, habitat, water)
    credit = expected_mitigation_credit(raw)
    return raw, credit, expected_net_impact_score(raw, credit)


def assert_alternative_scores(alt: Dict) -> None:
    """Recompute an alternative's three scores from its own four indices."""
    raw, credit, net = expected_impact_triple(
        alt["traffic_vmt_index"],
        alt["ghg_index"],
        alt["habitat_index"],
        alt["water_index"],
    )
    assert alt["raw_impact_score"] == raw, (
        f"raw_impact_score: expected {raw}, got {alt['raw_impact_score']}"
    )
    assert alt["mitigation_credit"] == credit, (
        f"mitigation_credit: expected {credit}, got {alt['mitigation_credit']}"
    )
    assert alt["net_impact_score"] == net, (
        f"net_impact_score: expected {net}, got {alt['net_impact_score']}"
    )
    assert_two_decimals(alt["raw_impact_score"], "raw_impact_score")
    assert_two_decimals(alt["mitigation_credit"], "mitigation_credit")
    assert_two_decimals(alt["net_impact_score"], "net_impact_score")


# ------------------------------------------------------------------- equity
def expected_weight(weighting_variant: str, interpreter_used: bool) -> float:
    """"2.0 when the parent activity's weighting_variant is OUTREACH_WEIGHTED and
    the respondent's interpreter_used is true, and 1.0 in every other case"."""
    if weighting_variant == "OUTREACH_WEIGHTED" and interpreter_used:
        return 2.0
    return 1.0


def expected_is_underrepresented(demographic_group: str) -> bool:
    return demographic_group in UNDERREPRESENTED_GROUPS


def expected_equity_share_pct(underrepresented_weight: float, total_weight: float) -> float:
    """"one hundred times underrepresented_weight_total divided by
    participation_weight_total, rounded half up to one decimal place, or 0.0 when
    that denominator is zero"."""
    if not total_weight:
        return 0.0
    return round_half_up(
        Decimal(100) * Decimal(str(underrepresented_weight)) / Decimal(str(total_weight)),
        1,
    )


def expected_activity_totals(records: Sequence[Dict], weighting_variant: str) -> Dict:
    """Fold a list of (demographic_group, interpreter_used) dicts into the four
    activity counters plus the activity-level equity share."""
    record_count = 0
    ur_count = 0
    total_weight = Decimal(0)
    ur_weight = Decimal(0)
    for rec in records:
        weight = Decimal(str(expected_weight(weighting_variant,
                                             rec.get("interpreter_used", False))))
        flagged = expected_is_underrepresented(rec["demographic_group"])
        record_count += 1
        total_weight += weight
        if flagged:
            ur_count += 1
            ur_weight += weight
    return {
        "record_count": record_count,
        "underrepresented_record_count": ur_count,
        "total_weighted_count": float(round_half_up(total_weight, 1)),
        "underrepresented_weighted_count": float(round_half_up(ur_weight, 1)),
        "equity_share_pct": expected_equity_share_pct(
            float(round_half_up(ur_weight, 1)), float(round_half_up(total_weight, 1))
        ),
    }


# ------------------------------------------------------------------- posture
def expected_posture(
    state_review_status: str,
    open_consistency_link_count: int,
    adopted_scenario_id,
    housing_shortfall_total: int,
    equity_share_pct: float,
) -> str:
    """The five-rung ladder of PRD section 2.9, first match wins."""
    if state_review_status == "DEFICIENT":
        return "FROZEN"
    if open_consistency_link_count > 0:
        return "CONSISTENCY_HOLD"
    if adopted_scenario_id is None or housing_shortfall_total > 0:
        return "CAPACITY_HOLD"
    if equity_share_pct < 40.0:
        return "EQUITY_HOLD"
    return "CLEAR"


def assert_posture_consistent(plan: Dict) -> None:
    """The plan's own reported posture must match the ladder run over its own fields."""
    expected = expected_posture(
        plan["state_review_status"],
        plan["open_consistency_link_count"],
        plan["adopted_scenario_id"],
        plan["housing_shortfall_total"],
        plan["equity_share_pct"],
    )
    assert plan["compliance_posture"] == expected, (
        f"compliance_posture: ladder gives {expected}, plan reports "
        f"{plan['compliance_posture']}"
    )


# ------------------------------------------------------------------- misc
def assert_fields_equal(actual: Dict, expected: Dict) -> None:
    for key, want in expected.items():
        assert key in actual, f"missing field {key!r}"
        assert actual[key] == want, f"{key}: expected {want!r}, got {actual[key]!r}"


def assert_unchanged(before: Dict, after: Dict, fields: Iterable[str]) -> None:
    for field in fields:
        assert before[field] == after[field], (
            f"{field} changed from {before[field]!r} to {after[field]!r}"
        )


def ids_of(rows: Sequence[Dict]) -> List[str]:
    return [row["id"] for row in rows]


def assert_created_at_ascending(rows: Sequence[Dict]) -> None:
    """"List results are always ordered by created_at ascending"."""
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(stamps), f"rows not ordered by created_at ascending: {stamps}"


def assert_no_such_key(row: Dict, key: str) -> None:
    assert key not in row, f"{key!r} must not appear in the payload"
