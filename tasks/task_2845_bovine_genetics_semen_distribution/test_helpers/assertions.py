"""Domain assertion helpers built on the framework's generic ones.

The arithmetic helpers reproduce the PRD's pinned rounding orders exactly so a
test can state the expected figure either as a literal or as a computation, and
the two must agree.
"""

from decimal import ROUND_HALF_UP, Decimal
from math import floor
from typing import Any, Dict, Iterable, List, Optional, Sequence

import pytest
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .api_client import canonical_instant
from .constants import (
    BASE_CENTS_PER_INDEX_POINT,
    CR_CEILING,
    CR_FLOOR,
    INBREEDING_PENALTY_PER_PCT,
    INDEX_BONUS_PER_POINT,
    BASE_CR,
    DOSE_SPERM_MILLIONS,
    LN2_DECAY_PCT_PER_DAY,
    LN2_SERVICE_FEE_CENTS,
    MARKET_FLOOR_CENTS,
    PAW_BASE,
    PAW_CAP_DAUGHTERS,
    PAW_FLOOR,
    PAW_SLOPE,
    PRODUCT_MULTIPLIER,
    PROGENY_BLEND_MIN,
    REBATE_TIERS,
    SCS_BASELINE,
    SEXED_PURITY_REF_PCT,
    SHRINK_MAX,
    SHRINK_MIN,
    W_FAT,
    W_FERT,
    W_HEALTH_BLEND,
    W_LONG,
    W_MILK,
    W_PROD_BLEND,
    W_PROTEIN,
    W_SCS,
)

JsonDict = Dict[str, Any]


# ----------------------------------------------------------------- rounding
def round_half_up(value: float, places: int = 0) -> float:
    """PRD 2.8: every rounding step in this API is round half up."""
    quantum = Decimal(1).scaleb(-places)
    result = Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)
    return int(result) if places == 0 else float(result)


def round_cents(value: float) -> int:
    return int(round_half_up(value, 0))


# ------------------------------------------------------- structural asserts
def assert_common_fields(row: JsonDict) -> None:
    """PRD 2.4: a server-minted UUID id plus created_at, updated_at, version."""
    assert is_valid_uuid(row["id"]), f"id is not a bare UUID: {row['id']!r}"
    assert "_" not in row["id"] and ":" not in row["id"], (
        "PRD 2.4 forbids a type prefix on id"
    )
    assert is_iso8601_timestamp(row["created_at"]), row["created_at"]
    assert is_iso8601_timestamp(row["updated_at"]), row["updated_at"]
    assert isinstance(row["version"], int)
    assert row["version"] >= 1


def assert_three_fractional_digits(value: str) -> None:
    """PRD 2.4: instants are rendered with exactly three fractional digits."""
    assert isinstance(value, str), f"not a timestamp: {value!r}"
    assert value.endswith("Z"), f"instant must be UTC with a trailing Z: {value!r}"
    body = value[:-1]
    assert "." in body, f"instant must carry a fractional part: {value!r}"
    assert len(body.split(".")[1]) == 3, (
        f"instant must carry exactly three fractional digits: {value!r}"
    )


def assert_instant_equals(actual: Optional[str], expected: Optional[str]) -> None:
    """Compare two instants after normalising the sub-second width."""
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"instant mismatch: {actual!r} != {expected!r}"
    )


def assert_envelope_meta(body: JsonDict) -> None:
    """PRD 2.2: the meta block carries a req_-prefixed id and a UTC instant."""
    meta = body["meta"]
    assert isinstance(meta["api_request_id"], str)
    assert meta["api_request_id"].startswith("req_"), meta["api_request_id"]
    assert_three_fractional_digits(meta["api_request_timestamp"])


def assert_decimal_places(value: float, places: int) -> None:
    assert value == pytest.approx(round_half_up(value, places), abs=1e-9), (
        f"{value} carries more than {places} decimal places"
    )


def assert_ids_ascending_by_created_at(rows: Sequence[JsonDict]) -> None:
    """PRD 2.3: list order is created_at ascending."""
    stamps = [canonical_instant(row["created_at"]) for row in rows]
    assert stamps == sorted(stamps), f"rows are not created_at ascending: {stamps}"


# ------------------------------------------------------- ledger invariants
def assert_dose_ledger_conserved(lot: JsonDict) -> None:
    """PRD 2.11: straw_count == available + reserved + consigned + used + destroyed."""
    total = (
        lot["doses_available"]
        + lot["doses_reserved"]
        + lot["doses_consigned"]
        + lot["doses_used"]
        + lot["doses_destroyed"]
    )
    assert total == lot["straw_count"], (
        "dose ledger broken: "
        f"{lot['doses_available']}+{lot['doses_reserved']}+{lot['doses_consigned']}"
        f"+{lot['doses_used']}+{lot['doses_destroyed']} != {lot['straw_count']}"
    )


def assert_buckets(
    lot: JsonDict,
    available: int,
    reserved: int,
    consigned: int,
    used: int,
    destroyed: int,
) -> None:
    actual = (
        lot["doses_available"],
        lot["doses_reserved"],
        lot["doses_consigned"],
        lot["doses_used"],
        lot["doses_destroyed"],
    )
    assert actual == (available, reserved, consigned, used, destroyed), (
        f"dose buckets {actual} != {(available, reserved, consigned, used, destroyed)}"
    )
    assert_dose_ledger_conserved(lot)


# --------------------------------------------------- genetic index (PRD 3.6)
def expected_shrink(reliability_pct: float) -> float:
    return min(SHRINK_MAX, max(SHRINK_MIN, reliability_pct / 100.0))


def expected_production_index(
    milk_kg: float, fat_kg: float, protein_kg: float, reliability_pct: float
) -> float:
    raw = W_MILK * milk_kg + W_FAT * fat_kg + W_PROTEIN * protein_kg
    return round_half_up(raw * expected_shrink(reliability_pct), 2)


def expected_health_index(
    somatic_cell_score: float,
    fertility_pct: float,
    longevity_months: float,
    reliability_pct: float,
) -> float:
    raw = (
        W_SCS * (SCS_BASELINE - somatic_cell_score) * 100
        + W_FERT * fertility_pct
        + W_LONG * longevity_months
    )
    return round_half_up(raw * expected_shrink(reliability_pct), 2)


def expected_evaluation_basis(progeny_daughter_count: int) -> str:
    return (
        "PROGENY_BLENDED"
        if progeny_daughter_count >= PROGENY_BLEND_MIN
        else "GENOMIC_ONLY"
    )


def expected_parent_average_weight(progeny_daughter_count: int) -> float:
    if expected_evaluation_basis(progeny_daughter_count) == "GENOMIC_ONLY":
        return PAW_BASE
    return max(
        PAW_FLOOR,
        PAW_BASE - PAW_SLOPE * min(progeny_daughter_count, PAW_CAP_DAUGHTERS),
    )


def expected_parent_average_index(
    sire_published_composite: float, dam_sire_published_composite: float
) -> float:
    """PRD 3.6: the divisor is always 2, an absent parent contributes 0.00."""
    return round_half_up((sire_published_composite + dam_sire_published_composite) / 2, 2)


def expected_composite_index(
    production_index: float,
    health_index: float,
    parent_average_index: float,
    parent_average_weight: float,
) -> float:
    blended = W_PROD_BLEND * production_index + W_HEALTH_BLEND * health_index
    return round_half_up(
        (1 - parent_average_weight) * blended
        + parent_average_weight * parent_average_index,
        2,
    )


# ------------------------------------------------- lot valuation (PRD 3.6)
def expected_standard_unit_value_cents(processing_cost_cents: int, straw_count: int) -> int:
    """PRD 2.8: the per-straw figure is rounded to whole cents first."""
    return round_cents(processing_cost_cents / straw_count)


def expected_market_unit_value_cents(
    published_composite_index: float,
    product_line: str,
    sexing_purity_pct: Optional[float] = None,
) -> int:
    value = (
        BASE_CENTS_PER_INDEX_POINT
        * max(0.0, published_composite_index)
        * PRODUCT_MULTIPLIER[product_line]
    )
    if product_line == "SEXED":
        assert sexing_purity_pct is not None
        value = value * (sexing_purity_pct / SEXED_PURITY_REF_PCT)
    return max(round_cents(value), MARKET_FLOOR_CENTS)


def expected_lot_carrying_value_cents(unit_value_cents: int, dose_count: int) -> int:
    """PRD 2.8: lot value is the rounded unit value multiplied by the dose count."""
    return unit_value_cents * dose_count


# --------------------------------------------- ejaculate yield (PRD 3.4)
def expected_theoretical_doses(volume_ml: float, concentration_m_per_ml: float) -> int:
    return int(floor(volume_ml * concentration_m_per_ml / DOSE_SPERM_MILLIONS))


# ------------------------------------------------ tank decay (PRD 3.8)
def expected_ln2_level_pct(last_service_fill_pct: float, elapsed_days: int) -> float:
    return round_half_up(
        max(0.0, last_service_fill_pct - LN2_DECAY_PCT_PER_DAY * elapsed_days), 1
    )


# ------------------------------------------------ settlement (PRD 3.8)
def expected_rebate_pct(pre_rebate_subtotal_cents: int) -> float:
    pct = 0.0
    for minimum, tier_pct in REBATE_TIERS:
        if pre_rebate_subtotal_cents >= minimum:
            pct = tier_pct
    return pct


def expected_settlement(
    doses_used: int,
    unit_price_cents: int,
    services_after_dispatch: int,
) -> Dict[str, int]:
    """PRD 3.8's pinned settlement order, returning all four figures."""
    gross = doses_used * unit_price_cents
    service_fee = LN2_SERVICE_FEE_CENTS * services_after_dispatch
    subtotal = gross + service_fee
    rebate = round_cents(gross * expected_rebate_pct(subtotal))
    return {
        "gross_cents": gross,
        "service_fee_cents": service_fee,
        "pre_rebate_subtotal_cents": subtotal,
        "rebate_cents": rebate,
        "settlement_total_cents": subtotal - rebate,
    }


def assert_settlement(transfer: JsonDict, expected: Dict[str, int]) -> None:
    assert transfer["gross_cents"] == expected["gross_cents"]
    assert transfer["service_fee_cents"] == expected["service_fee_cents"]
    assert transfer["rebate_cents"] == expected["rebate_cents"]
    assert transfer["settlement_total_cents"] == expected["settlement_total_cents"]


# --------------------------------------- expected conception rate (PRD 3.9)
def expected_conception_rate(
    product_line: str,
    published_composite_index: float,
    post_thaw_motility_pct: float,
    inbreeding_pct: float,
) -> float:
    rate = BASE_CR[product_line]
    rate *= 1 + INDEX_BONUS_PER_POINT * max(0.0, published_composite_index)
    rate *= post_thaw_motility_pct / 100.0
    rate *= 1 - INBREEDING_PENALTY_PER_PCT * inbreeding_pct
    rate = min(CR_CEILING, max(CR_FLOOR, rate))
    return round_half_up(rate, 4)


# ------------------------------------------------------------- misc helpers
def assert_null_fields(row: JsonDict, field_names: Iterable[str]) -> None:
    for name in field_names:
        assert row.get(name, None) is None, f"{name} should be null, got {row.get(name)!r}"


def assert_zero_fields(row: JsonDict, field_names: Iterable[str]) -> None:
    for name in field_names:
        assert row[name] == 0, f"{name} should be 0, got {row[name]!r}"


def ids_of(rows: Sequence[JsonDict]) -> List[str]:
    return [row["id"] for row in rows]


def assert_row_unchanged(before: JsonDict, after: JsonDict, *fields: str) -> None:
    """A refused write must leave version, updated_at and the named fields alone."""
    assert after["version"] == before["version"], (
        f"version moved on a refusal: {before['version']} -> {after['version']}"
    )
    assert_instant_equals(after["updated_at"], before["updated_at"])
    for field in fields:
        assert after[field] == before[field], (
            f"{field} moved on a refusal: {before[field]!r} -> {after[field]!r}"
        )
