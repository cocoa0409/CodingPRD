"""Domain assertions for the Private-Label Brand Development API.

Every helper states its expectation in domain language so a failure message
names the business rule that broke rather than a raw dictionary diff.
Timestamp comparisons go through the canonicaliser in ``api_client`` so that
differing fractional-second widths never masquerade as a defect.
"""

from typing import Optional

from test_helpers.api_client import canonicalize_iso, canonicalize_money
from test_helpers.constants import (
    COMMON_SYSTEM_FIELDS,
    DEFAULT_LIMIT,
)


# --- Envelope and system fields ------------------------------------------


def assert_instant_equals(actual, expected, label="timestamp"):
    """Compare two ISO 8601 UTC instants independently of fractional width."""
    assert canonicalize_iso(actual) == canonicalize_iso(expected), (
        f"{label}: expected instant {expected!r}, got {actual!r}"
    )


def assert_three_fractional_digits(value, label="timestamp"):
    """The contract renders instants with exactly three fractional digits."""
    assert isinstance(value, str), f"{label} must be a string, got {value!r}"
    assert value.endswith("Z"), f"{label} must be a UTC instant ending in Z: {value!r}"
    body = value[:-1]
    assert "." in body, f"{label} must carry fractional seconds: {value!r}"
    fraction = body.split(".", 1)[1]
    assert len(fraction) == 3, (
        f"{label} must carry exactly three fractional digits, got {value!r}"
    )


def assert_carries_common_fields(resource, label="resource"):
    """Assert the four common system fields are present and well formed."""
    for field in COMMON_SYSTEM_FIELDS:
        assert field in resource, f"{label} is missing {field}"
    assert isinstance(resource["version"], int), (
        f"{label}.version must be an integer, got {resource['version']!r}"
    )
    assert_three_fractional_digits(resource["created_at"], f"{label}.created_at")
    assert_three_fractional_digits(resource["updated_at"], f"{label}.updated_at")


def assert_freshly_created(resource, label="resource"):
    """A newly created resource opens at version 1 with updated_at == created_at."""
    assert_carries_common_fields(resource, label)
    assert resource["version"] == 1, (
        f"{label} must open at version 1, got {resource['version']}"
    )
    assert_instant_equals(
        resource["updated_at"], resource["created_at"], f"{label}.updated_at"
    )


def assert_append_only(resource, label="complaint"):
    """An append-only resource carries neither updated_at nor version."""
    assert "id" in resource, f"{label} is missing id"
    assert "created_at" in resource, f"{label} is missing created_at"
    assert "version" not in resource, f"{label} must not carry a version field"
    assert "updated_at" not in resource, f"{label} must not carry an updated_at field"


def assert_version_is(resource, expected, label="resource"):
    assert resource["version"] == expected, (
        f"{label}.version expected {expected}, got {resource['version']}"
    )


def assert_version_unchanged(before, after, label="resource"):
    assert before["version"] == after["version"], (
        f"{label}.version moved from {before['version']} to {after['version']} "
        "but the operation should not have mutated it"
    )


def assert_version_advanced_by(before, after, delta, label="resource"):
    expected = before["version"] + delta
    assert after["version"] == expected, (
        f"{label}.version expected {expected} after {delta} mutation(s), "
        f"got {after['version']}"
    )


def assert_pagination_defaults(meta):
    assert meta["limit"] == DEFAULT_LIMIT, (
        f"default limit must be {DEFAULT_LIMIT}, got {meta['limit']}"
    )
    assert meta["offset"] == 0, f"default offset must be 0, got {meta['offset']}"


def assert_page_window(meta, limit, offset, total_count):
    assert meta["limit"] == limit, f"limit expected {limit}, got {meta['limit']}"
    assert meta["offset"] == offset, f"offset expected {offset}, got {meta['offset']}"
    assert meta["total_count"] == total_count, (
        f"total_count expected {total_count}, got {meta['total_count']}"
    )
    assert meta["has_more"] == (offset + limit < total_count), (
        f"has_more inconsistent with offset {offset}, limit {limit}, "
        f"total_count {total_count}: got {meta['has_more']}"
    )


# --- Money and rounding ---------------------------------------------------


def assert_money_cents(value, expected, label="amount"):
    """Money is an integer number of cents, never a string."""
    assert not isinstance(value, str), (
        f"{label} must be a JSON number of cents, not the string {value!r}"
    )
    actual = canonicalize_money(value)
    assert actual == expected, f"{label} expected {expected} cents, got {actual}"


def assert_two_decimal_value(value, expected, label="value"):
    """Percentages, scores and nutrient grams carry two decimal places."""
    assert not isinstance(value, str), (
        f"{label} must be a JSON number, not the string {value!r}"
    )
    assert value is not None, f"{label} must not be null"
    assert round(float(value), 2) == round(float(expected), 2), (
        f"{label} expected {expected}, got {value}"
    )


def assert_retail_price_ends_in_nine(price_cents):
    assert price_cents is not None, "retail_price_cents must be set once locked"
    assert price_cents % 10 == 9, (
        f"retail_price_cents must end in the digit 9, got {price_cents}"
    )


# --- Two-dimensional item state ------------------------------------------


def assert_item_state(item, development_status, quality_posture):
    """Both item dimensions are asserted together; neither implies the other."""
    assert item["development_status"] == development_status, (
        f"item development_status expected {development_status}, "
        f"got {item['development_status']}"
    )
    assert item["quality_posture"] == quality_posture, (
        f"item quality_posture expected {quality_posture}, "
        f"got {item['quality_posture']}"
    )


def assert_artwork_state(round_, status, nutrition_status):
    """Both artwork dimensions are asserted together."""
    assert round_["status"] == status, (
        f"artwork round status expected {status}, got {round_['status']}"
    )
    assert round_["nutrition_status"] == nutrition_status, (
        f"artwork nutrition_status expected {nutrition_status}, "
        f"got {round_['nutrition_status']}"
    )


def assert_status(resource, expected, label="resource"):
    assert resource["status"] == expected, (
        f"{label} status expected {expected}, got {resource['status']}"
    )


# --- Ledger invariants ----------------------------------------------------


def assert_budget_ledger(
    ledger,
    dev_budget_cents=None,
    committed_budget_cents=None,
    lifetime_committed_cents=None,
    lifetime_released_cents=None,
    available_budget_cents=None,
    active_item_count=None,
):
    """Assert the requested ledger readings and the ledger's own identities."""
    if dev_budget_cents is not None:
        assert_money_cents(
            ledger["dev_budget_cents"], dev_budget_cents, "dev_budget_cents"
        )
    if committed_budget_cents is not None:
        assert_money_cents(
            ledger["committed_budget_cents"],
            committed_budget_cents,
            "committed_budget_cents",
        )
    if lifetime_committed_cents is not None:
        assert_money_cents(
            ledger["lifetime_committed_cents"],
            lifetime_committed_cents,
            "lifetime_committed_cents",
        )
    if lifetime_released_cents is not None:
        assert_money_cents(
            ledger["lifetime_released_cents"],
            lifetime_released_cents,
            "lifetime_released_cents",
        )
    if available_budget_cents is not None:
        assert_money_cents(
            ledger["available_budget_cents"],
            available_budget_cents,
            "available_budget_cents",
        )
    if active_item_count is not None:
        assert ledger["active_item_count"] == active_item_count, (
            f"active_item_count expected {active_item_count}, "
            f"got {ledger['active_item_count']}"
        )
    assert_budget_ledger_reconciles(ledger)


def assert_budget_ledger_reconciles(ledger):
    """committed == lifetime committed - lifetime released, and available follows."""
    expected_committed = (
        ledger["lifetime_committed_cents"] - ledger["lifetime_released_cents"]
    )
    assert ledger["committed_budget_cents"] == expected_committed, (
        "committed_budget_cents must equal lifetime_committed_cents minus "
        f"lifetime_released_cents ({expected_committed}), got "
        f"{ledger['committed_budget_cents']}"
    )
    expected_available = ledger["dev_budget_cents"] - ledger["committed_budget_cents"]
    assert ledger["available_budget_cents"] == expected_available, (
        "available_budget_cents must equal dev_budget_cents minus "
        f"committed_budget_cents ({expected_available}), got "
        f"{ledger['available_budget_cents']}"
    )


def assert_shelf_slots(
    gap,
    slots_consumed=None,
    slots_open=None,
    slots_consumed_lifetime=None,
    slots_released_lifetime=None,
    shelf_slots_quota=None,
):
    """Assert the requested slot readings and the slot identities."""
    if slots_consumed is not None:
        assert gap["slots_consumed"] == slots_consumed, (
            f"slots_consumed expected {slots_consumed}, got {gap['slots_consumed']}"
        )
    if slots_open is not None:
        assert gap["slots_open"] == slots_open, (
            f"slots_open expected {slots_open}, got {gap['slots_open']}"
        )
    if slots_consumed_lifetime is not None:
        assert gap["slots_consumed_lifetime"] == slots_consumed_lifetime, (
            f"slots_consumed_lifetime expected {slots_consumed_lifetime}, "
            f"got {gap['slots_consumed_lifetime']}"
        )
    if slots_released_lifetime is not None:
        assert gap["slots_released_lifetime"] == slots_released_lifetime, (
            f"slots_released_lifetime expected {slots_released_lifetime}, "
            f"got {gap['slots_released_lifetime']}"
        )
    if shelf_slots_quota is not None:
        assert gap["shelf_slots_quota"] == shelf_slots_quota, (
            f"shelf_slots_quota expected {shelf_slots_quota}, "
            f"got {gap['shelf_slots_quota']}"
        )
    assert_shelf_slots_reconcile(gap)


def assert_shelf_slots_reconcile(gap):
    """consumed == consumed lifetime - released lifetime, open == quota - consumed."""
    expected_consumed = (
        gap["slots_consumed_lifetime"] - gap["slots_released_lifetime"]
    )
    assert gap["slots_consumed"] == expected_consumed, (
        "slots_consumed must equal slots_consumed_lifetime minus "
        f"slots_released_lifetime ({expected_consumed}), got {gap['slots_consumed']}"
    )
    expected_open = gap["shelf_slots_quota"] - gap["slots_consumed"]
    assert gap["slots_open"] == expected_open, (
        "slots_open must equal shelf_slots_quota minus slots_consumed "
        f"({expected_open}), got {gap['slots_open']}"
    )


# --- Settlement arithmetic ------------------------------------------------


def assert_settlement(
    request,
    raw_increase_cents=None,
    increase_pct=None,
    escalation_tier=None,
    capped_increase_cents=None,
    offset_fee_cents=None,
    net_increase_cents=None,
):
    if raw_increase_cents is not None:
        assert_money_cents(
            request["raw_increase_cents"], raw_increase_cents, "raw_increase_cents"
        )
    if increase_pct is not None:
        assert_two_decimal_value(request["increase_pct"], increase_pct, "increase_pct")
    if escalation_tier is not None:
        assert request["escalation_tier"] == escalation_tier, (
            f"escalation_tier expected {escalation_tier}, "
            f"got {request['escalation_tier']}"
        )
    if capped_increase_cents is not None:
        assert_money_cents(
            request["capped_increase_cents"],
            capped_increase_cents,
            "capped_increase_cents",
        )
    if offset_fee_cents is not None:
        assert_money_cents(
            request["offset_fee_cents"], offset_fee_cents, "offset_fee_cents"
        )
    if net_increase_cents is not None:
        assert_money_cents(
            request["net_increase_cents"], net_increase_cents, "net_increase_cents"
        )


def assert_landed_costs(cost_model, as_quoted=None, audited: Optional[int] = -1):
    """Assert either landed-cost variant; pass ``audited=None`` to require null."""
    if as_quoted is not None:
        assert_money_cents(
            cost_model["landed_unit_cost_cents_as_quoted"],
            as_quoted,
            "landed_unit_cost_cents_as_quoted",
        )
    if audited is None:
        assert cost_model["landed_unit_cost_cents_audited"] is None, (
            "landed_unit_cost_cents_audited must be null with no finalized audit, "
            f"got {cost_model['landed_unit_cost_cents_audited']}"
        )
    elif audited != -1:
        assert_money_cents(
            cost_model["landed_unit_cost_cents_audited"],
            audited,
            "landed_unit_cost_cents_audited",
        )


def assert_declared_panel(
    round_,
    calories=None,
    fat_g=None,
    satfat_g=None,
    carb_g=None,
    fiber_g=None,
    sugars_g=None,
    added_sugars_g=None,
    protein_g=None,
    sodium_mg=None,
):
    """Assert the banded declared figures written by panel generation."""
    if calories is not None:
        assert round_["declared_calories"] == calories, (
            f"declared_calories expected {calories}, got {round_['declared_calories']}"
        )
    pairs = (
        ("declared_fat_g", fat_g),
        ("declared_satfat_g", satfat_g),
        ("declared_carb_g", carb_g),
        ("declared_fiber_g", fiber_g),
        ("declared_sugars_g", sugars_g),
        ("declared_added_sugars_g", added_sugars_g),
        ("declared_protein_g", protein_g),
    )
    for field, expected in pairs:
        if expected is not None:
            assert_two_decimal_value(round_[field], expected, field)
    if sodium_mg is not None:
        assert round_["declared_sodium_mg"] == sodium_mg, (
            f"declared_sodium_mg expected {sodium_mg}, "
            f"got {round_['declared_sodium_mg']}"
        )


def assert_panel_not_generated(round_):
    """Before generation every declared figure is null."""
    declared = [
        "declared_calories",
        "declared_fat_g",
        "declared_satfat_g",
        "declared_carb_g",
        "declared_fiber_g",
        "declared_sugars_g",
        "declared_added_sugars_g",
        "declared_protein_g",
        "declared_sodium_mg",
    ]
    for field in declared:
        assert round_[field] is None, (
            f"{field} must be null before the panel is generated, got {round_[field]}"
        )


def assert_scorecard_window(scorecard, field, expected_instant):
    assert_instant_equals(scorecard[field], expected_instant, f"scorecard.{field}")


def find_by_id(rows, resource_id):
    """Return the row with the given id from a listing, or fail."""
    for row in rows:
        if row.get("id") == resource_id:
            return row
    raise AssertionError(f"id {resource_id} not present in the {len(rows)}-row listing")


def ids_of(rows):
    return [row["id"] for row in rows]


def assert_supplier_status(supplier, expected):
    """The supplier's own state dimension is named qualification_status."""
    assert supplier["qualification_status"] == expected, (
        f"supplier qualification_status expected {expected}, "
        f"got {supplier['qualification_status']}"
    )
