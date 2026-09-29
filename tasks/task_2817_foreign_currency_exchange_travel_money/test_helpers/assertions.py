"""Entity assertions and domain invariant checkers for the Retail FX API."""

from typing import List, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .api_client import canonical_ts, same_instant
from .constants import (
    ASSESSMENT_OUTCOMES,
    ASSESSMENT_STATUSES,
    BRANCH_POSTURES,
    BRANCH_STATUSES,
    COMPLIANCE_STATUSES,
    COMMISSION_SCHEDULE_CODES,
    CONTRACT_STATUSES,
    CURRENCY_CLASSES,
    DEFECT_TYPES,
    DIRECTIONS,
    PLAN_STATUSES,
    POSITION_STATUSES,
    RATE_CARD_STATUSES,
    REPORT_STATUSES,
    REPORT_TYPES,
    RISK_TIERS,
    SEASONS,
    SETTLEMENT_STATUSES,
    SHIPMENT_DIRECTIONS,
    SHIPMENT_STATUSES,
    VAULT_FROZEN_MIN_BPS,
    VAULT_RESTRICTED_MIN_BPS,
    WHOLESALE_SOURCE_CODES,
)


# --------------------------------------------------------------------------- #
# Shared audit-stamp helpers (PRD 2.4)                                         #
# --------------------------------------------------------------------------- #
def assert_versioned_entity(data: dict) -> None:
    """A resource that carries the full audit set: id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "version must be an integer starting at 1"
    )


def assert_reference_entity(data: dict) -> None:
    """Immutable reference data: id and created_at only, no updated_at, no version.

    PRD 2.4: CurrencyProfile, WholesaleRate, TravelCorridor and ArmoredRoute
    carry no updated_at and no version field at all, and the server must not
    emit them.
    """
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "immutable reference data must not carry updated_at"
    assert "version" not in data, "immutable reference data must not carry version"


def assert_timestamp_equals(actual: Optional[str], expected: str) -> None:
    """Compare two instants without depending on the sub-second width."""
    assert actual is not None, f"expected instant {expected}, got null"
    assert same_instant(actual, expected), (
        f"expected instant {canonical_ts(expected)}, got {canonical_ts(actual)}"
    )


# --------------------------------------------------------------------------- #
# Entities                                                                     #
# --------------------------------------------------------------------------- #
def assert_branch(data: dict) -> None:
    assert_versioned_entity(data)
    assert isinstance(data["code"], str) and 1 <= len(data["code"]) <= 16
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["region_code"], str) and data["region_code"]
    assert data["home_currency_code"] == "USD", "home_currency_code is fixed at USD"
    assert data["status"] in BRANCH_STATUSES
    assert data["posture"] in BRANCH_POSTURES
    assert isinstance(data["vault_limit_usd_cents"], int)
    assert data["vault_limit_usd_cents"] >= 100000, "vault ceiling floor is 100000 cents"
    assert isinstance(data["vault_usd_equivalent_cents"], int)
    assert isinstance(data["vault_utilization_bps"], int)
    assert isinstance(data["buyback_liability_usd_cents"], int)
    assert isinstance(data["repatriation_pending"], bool)
    assert_branch_posture_band(data)


def assert_branch_posture_band(data: dict) -> None:
    """PRD 2.6: OPEN below 9000 bps, RESTRICTED from 9000 through 10000 inclusive,
    FROZEN only strictly above 10000."""
    bps = data["vault_utilization_bps"]
    if bps < VAULT_RESTRICTED_MIN_BPS:
        expected = "OPEN"
    elif bps <= VAULT_FROZEN_MIN_BPS:
        expected = "RESTRICTED"
    else:
        expected = "FROZEN"
    assert data["posture"] == expected, (
        f"{bps} bps must derive posture {expected}, got {data['posture']}"
    )


def assert_currency_profile(data: dict) -> None:
    assert_reference_entity(data)
    assert isinstance(data["iso_code"], str) and len(data["iso_code"]) == 3
    assert data["iso_code"].isupper()
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert data["minor_unit_digits"] in (0, 2, 3)
    assert data["currency_class"] in CURRENCY_CLASSES
    denoms = data["standard_denominations"]
    assert isinstance(denoms, list) and 1 <= len(denoms) <= 8
    assert all(isinstance(d, int) and d >= 1 for d in denoms)
    assert denoms == sorted(set(denoms)), "standard_denominations must be strictly ascending"
    assert isinstance(data["buyback_eligible"], bool)
    assert isinstance(data["damaged_note_recovery_bps"], int)
    assert 0 <= data["damaged_note_recovery_bps"] <= 10000
    if data["currency_class"] == "RESTRICTED":
        assert isinstance(data["export_limit_minor_units"], int), (
            "export_limit_minor_units is required exactly when the class is RESTRICTED"
        )
    else:
        assert data["export_limit_minor_units"] is None, (
            "export_limit_minor_units must be null for MAJOR and EXOTIC currencies"
        )


def assert_wholesale_rate(data: dict) -> None:
    assert_reference_entity(data)
    assert isinstance(data["currency_code"], str)
    assert isinstance(data["mid_rate_micros"], int) and data["mid_rate_micros"] >= 1
    assert is_iso8601_timestamp(data["effective_at"])
    assert data["source_code"] in WHOLESALE_SOURCE_CODES


def assert_travel_corridor(data: dict) -> None:
    assert_reference_entity(data)
    assert isinstance(data["code"], str) and data["code"]
    assert len(data["origin_country_code"]) == 2
    assert len(data["destination_country_code"]) == 2
    assert isinstance(data["destination_currency_code"], str)
    assert data["season"] in SEASONS
    assert is_iso8601_timestamp(data["season_start_date"])
    assert is_iso8601_timestamp(data["season_end_date"])
    assert 1 <= data["demand_index_bps"] <= 50000


def assert_armored_route(data: dict) -> None:
    assert_reference_entity(data)
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["carrier_name"], str) and data["carrier_name"]
    assert isinstance(data["region_code"], str) and data["region_code"]
    assert isinstance(data["daily_capacity_usd_cents"], int)
    assert data["daily_capacity_usd_cents"] >= 1
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_rate_card(data: dict) -> None:
    assert_versioned_entity(data)
    assert is_valid_uuid(data["branch_id"])
    assert isinstance(data["currency_code"], str)
    assert is_valid_uuid(data["wholesale_rate_id"])
    assert 0 <= data["buy_spread_bps"] <= 5000
    assert 0 <= data["sell_spread_bps"] <= 5000
    assert isinstance(data["buy_rate_micros"], int)
    assert isinstance(data["sell_rate_micros"], int)
    assert data["sell_rate_micros"] <= data["buy_rate_micros"], (
        "the spread-reduced sell rate is the smaller of the two (PRD 3.2)"
    )
    assert isinstance(data["board_display_label"], str) and data["board_display_label"]
    assert isinstance(data["disclosure_text_version"], int)
    assert data["disclosure_text_version"] >= 1
    assert data["commission_schedule_code"] in COMMISSION_SCHEDULE_CODES
    assert is_iso8601_timestamp(data["effective_from"])
    assert data["status"] in RATE_CARD_STATUSES


def assert_rate_card_derivation(card: dict, mid_rate_micros: int) -> None:
    """PRD 3.2: sell = round_half_up(mid * (10000 - sell_spread) / 10000) and
    buy = round_half_up(mid * (10000 + buy_spread) / 10000)."""
    assert card["sell_rate_micros"] == round_half_up(
        mid_rate_micros * (10000 - card["sell_spread_bps"]), 10000
    )
    assert card["buy_rate_micros"] == round_half_up(
        mid_rate_micros * (10000 + card["buy_spread_bps"]), 10000
    )


def assert_inventory_position(data: dict) -> None:
    assert_versioned_entity(data)
    assert is_valid_uuid(data["branch_id"])
    assert isinstance(data["currency_code"], str)
    assert data["status"] in POSITION_STATUSES
    assert_position_mix_invariants(data)


def assert_position_mix_invariants(data: dict) -> None:
    """PRD 2.9: the mix is ordered by denomination ascending; total_minor_units is
    the sum of denomination times available_note_count, quarantined_minor_units the
    sum of denomination times quarantined_note_count, and written-off notes feed
    neither."""
    mix = data["denomination_mix"]
    assert isinstance(mix, list)
    faces = [entry["denomination_minor_units"] for entry in mix]
    assert faces == sorted(faces), "denomination_mix must be ordered by denomination ascending"
    for entry in mix:
        for field in (
            "denomination_minor_units",
            "available_note_count",
            "quarantined_note_count",
            "written_off_note_count",
        ):
            assert isinstance(entry[field], int), f"{field} must be an integer"
            assert entry[field] >= 0, f"{field} must be non-negative"
    total = sum(e["denomination_minor_units"] * e["available_note_count"] for e in mix)
    quarantined = sum(
        e["denomination_minor_units"] * e["quarantined_note_count"] for e in mix
    )
    assert data["total_minor_units"] == total, (
        f"total_minor_units must equal the available-note sum {total}, "
        f"got {data['total_minor_units']}"
    )
    assert data["quarantined_minor_units"] == quarantined, (
        f"quarantined_minor_units must equal the quarantined-note sum {quarantined}, "
        f"got {data['quarantined_minor_units']}"
    )
    assert isinstance(data["usd_equivalent_cents"], int)


def assert_inventory_plan(data: dict) -> None:
    assert_versioned_entity(data)
    assert is_valid_uuid(data["branch_id"])
    assert is_valid_uuid(data["travel_corridor_id"])
    assert 1 <= data["season_days"] <= 366
    assert data["status"] in PLAN_STATUSES
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0
    assert isinstance(data["target_lines"], list)
    assert isinstance(data["computed_targets"], list)
    assert_computed_targets_shape(data["computed_targets"])


def assert_computed_targets_shape(targets: List[dict]) -> None:
    """PRD 3.3: one object per line carrying the line's currency_code and its
    resulting target_minor_units, ordered by currency_code ascending."""
    codes = [t["currency_code"] for t in targets]
    assert codes == sorted(codes), "computed_targets must be ordered by currency_code ascending"
    for entry in targets:
        assert set(entry.keys()) == {"currency_code", "target_minor_units"}, (
            "each computed target carries exactly currency_code and target_minor_units, "
            f"got {sorted(entry.keys())}"
        )
        assert isinstance(entry["target_minor_units"], int)


def assert_customer(data: dict) -> None:
    assert_versioned_entity(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert len(data["nationality_code"]) == 2
    assert data["structuring_risk_tier"] in RISK_TIERS
    assert isinstance(data["compliance_hold_active"], bool)
    for field in (
        "rolling_30d_settled_usd_cents",
        "calendar_month_settled_usd_cents",
        "near_threshold_txn_count",
        "distinct_branch_count",
        "structuring_risk_score",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer"
        assert data[field] >= 0, f"{field} must be non-negative"
    assert 0 <= data["structuring_risk_score"] <= 100
    assert_risk_tier_band(data)


def assert_risk_tier_band(data: dict) -> None:
    """PRD 3.6: NORMAL below 25, ELEVATED from 25 to below 70, HIGH from 70."""
    score = data["structuring_risk_score"]
    expected = "NORMAL" if score < 25 else ("ELEVATED" if score < 70 else "HIGH")
    assert data["structuring_risk_tier"] == expected, (
        f"score {score} must derive tier {expected}, got {data['structuring_risk_tier']}"
    )


def assert_exchange_transaction(data: dict) -> None:
    assert_versioned_entity(data)
    assert is_valid_uuid(data["branch_id"])
    assert is_valid_uuid(data["customer_id"])
    assert is_valid_uuid(data["rate_card_id"])
    assert data["direction"] in DIRECTIONS
    assert data["settlement_status"] in SETTLEMENT_STATUSES
    assert data["compliance_status"] in COMPLIANCE_STATUSES
    assert isinstance(data["fx_gross_minor_units"], int)
    assert isinstance(data["applied_rate_micros"], int)
    assert isinstance(data["quoted_usd_gross_cents"], int)
    assert isinstance(data["quoted_commission_cents"], int)
    assert isinstance(data["quoted_total_charge_cents"], int)
    assert is_iso8601_timestamp(data["quote_expires_at"])
    assert isinstance(data["quoted_by_user_id"], str) and data["quoted_by_user_id"]


def assert_quote_money(
    data: dict,
    fx_gross_minor_units: int,
    applied_rate_micros: int,
    gross_cents: int,
    commission_cents: int,
    total_charge_cents: int,
) -> None:
    """The five derived quote money fields of PRD 3.5."""
    assert data["fx_gross_minor_units"] == fx_gross_minor_units
    assert data["applied_rate_micros"] == applied_rate_micros
    assert data["quoted_usd_gross_cents"] == gross_cents
    assert data["quoted_commission_cents"] == commission_cents
    assert data["quoted_total_charge_cents"] == total_charge_cents


def assert_settlement_money(
    data: dict,
    gross_cents: int,
    commission_cents: int,
    total_charge_cents: int,
    price_adjustment_cents: Optional[int] = None,
) -> None:
    """The SETTLEMENT_FINAL money fields of PRD 3.5."""
    assert data["settled_usd_gross_cents"] == gross_cents
    assert data["settled_commission_cents"] == commission_cents
    assert data["settled_total_charge_cents"] == total_charge_cents
    if price_adjustment_cents is not None:
        assert data["price_adjustment_cents"] == price_adjustment_cents


def assert_buyback_contract(data: dict) -> None:
    assert_versioned_entity(data)
    assert is_valid_uuid(data["customer_id"])
    assert is_valid_uuid(data["origin_transaction_id"])
    assert is_valid_uuid(data["branch_id"])
    assert data["status"] in CONTRACT_STATUSES
    assert isinstance(data["locked_buy_rate_micros"], int)
    assert isinstance(data["locked_fx_minor_units"], int)
    assert isinstance(data["remaining_fx_minor_units"], int)
    assert isinstance(data["fee_usd_cents"], int)
    assert isinstance(data["liability_usd_cents"], int)
    assert isinstance(data["redemption_count"], int)
    assert is_iso8601_timestamp(data["rate_lock_expires_at"])
    assert data["remaining_fx_minor_units"] <= data["locked_fx_minor_units"]
    if data["status"] in ("REDEEMED", "CANCELLED", "EXPIRED"):
        assert data["liability_usd_cents"] == 0, (
            "a contract outside ISSUED/PARTIALLY_REDEEMED carries no liability"
        )


def assert_note_assessment(data: dict) -> None:
    assert_versioned_entity(data)
    assert is_valid_uuid(data["branch_id"])
    assert is_valid_uuid(data["inventory_position_id"])
    assert is_valid_uuid(data["exchange_transaction_id"])
    assert data["defect_type"] in DEFECT_TYPES
    assert data["status"] in ASSESSMENT_STATUSES
    assert data["note_count"] >= 1
    assert data["face_fx_minor_units"] == data["denomination_minor_units"] * data["note_count"]
    if data["outcome"] is not None:
        assert data["outcome"] in ASSESSMENT_OUTCOMES


def assert_compliance_report(data: dict) -> None:
    assert_versioned_entity(data)
    assert data["report_type"] in REPORT_TYPES
    assert data["status"] in REPORT_STATUSES
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert isinstance(data["aggregate_usd_cents"], int)
    assert isinstance(data["transaction_count"], int)
    assert isinstance(data["amendment_count"], int)
    if data["report_type"] == "COUNTERFEIT_SEIZURE":
        assert data["triggering_transaction_id"] is None
        assert is_valid_uuid(data["note_assessment_id"])
    else:
        assert data["note_assessment_id"] is None
        assert is_valid_uuid(data["triggering_transaction_id"])


def assert_cash_shipment(data: dict) -> None:
    assert_versioned_entity(data)
    assert is_valid_uuid(data["branch_id"])
    assert data["direction"] in SHIPMENT_DIRECTIONS
    assert data["status"] in SHIPMENT_STATUSES
    assert isinstance(data["auto_generated"], bool)
    assert isinstance(data["manifest_minor_units"], int)
    assert isinstance(data["manifest_usd_equivalent_cents"], int)
    manifest = data["manifest_denominations"]
    faces = [entry["denomination_minor_units"] for entry in manifest]
    assert faces == sorted(faces), "manifest must be ordered by denomination ascending"
    assert data["manifest_minor_units"] == sum(
        e["denomination_minor_units"] * e["note_count"] for e in manifest
    )


def assert_rate_board(data: dict) -> None:
    """PRD 2.10: the board projection carries branch_id, as_of, line_count,
    min_disclosure_text_version and lines."""
    assert is_valid_uuid(data["branch_id"])
    assert is_iso8601_timestamp(data["as_of"])
    assert isinstance(data["line_count"], int)
    assert isinstance(data["lines"], list)
    assert data["line_count"] == len(data["lines"])
    assert isinstance(data["min_disclosure_text_version"], int)


# --------------------------------------------------------------------------- #
# Arithmetic helpers that mirror the PRD's single rounding rule (PRD 2.5)       #
# --------------------------------------------------------------------------- #
def round_half_up(numerator: int, denominator: int) -> int:
    """Round a non-negative rational half up to an integer."""
    assert denominator > 0
    return (numerator * 2 + denominator) // (denominator * 2)


def usd_cents_from_minor(minor_units: int, rate_micros: int) -> int:
    """PRD 2.5: minor units times 1,000,000 divided by the rate, rounded half up."""
    return round_half_up(minor_units * 1_000_000, rate_micros)


def per_line_usd_cents(lines: List[dict], rate_micros: int) -> int:
    """PRD 3.5's pinned rounding order: convert and round each denomination line
    first, in ascending denomination order, then sum the rounded cents."""
    ordered = sorted(lines, key=lambda e: e["denomination_minor_units"])
    return sum(
        usd_cents_from_minor(
            e["denomination_minor_units"] * e["note_count"], rate_micros
        )
        for e in ordered
    )


def find_mix_entry(position: dict, denomination_minor_units: int) -> dict:
    for entry in position["denomination_mix"]:
        if entry["denomination_minor_units"] == denomination_minor_units:
            return entry
    raise AssertionError(
        f"denomination {denomination_minor_units} absent from the position mix"
    )


def assert_mix_counts(
    position: dict,
    denomination_minor_units: int,
    available: Optional[int] = None,
    quarantined: Optional[int] = None,
    written_off: Optional[int] = None,
) -> None:
    entry = find_mix_entry(position, denomination_minor_units)
    if available is not None:
        assert entry["available_note_count"] == available, (
            f"denomination {denomination_minor_units}: expected {available} available, "
            f"got {entry['available_note_count']}"
        )
    if quarantined is not None:
        assert entry["quarantined_note_count"] == quarantined
    if written_off is not None:
        assert entry["written_off_note_count"] == written_off


def assert_vault_state(
    branch: dict,
    vault_usd_equivalent_cents: int,
    vault_utilization_bps: int,
    posture: str,
) -> None:
    assert branch["vault_usd_equivalent_cents"] == vault_usd_equivalent_cents
    assert branch["vault_utilization_bps"] == vault_utilization_bps
    assert branch["posture"] == posture
    assert_branch_posture_band(branch)


def assert_denomination_entries(actual: List[dict], expected: List[dict]) -> None:
    """Compare a denomination array (manifest, requested, delivered) exactly."""
    assert len(actual) == len(expected), (
        f"expected {len(expected)} denomination entries, got {len(actual)}: {actual}"
    )
    for got, want in zip(actual, expected):
        assert got["denomination_minor_units"] == want["denomination_minor_units"], (
            f"expected denomination {want['denomination_minor_units']}, got {got}"
        )
        assert got["note_count"] == want["note_count"], (
            f"denomination {want['denomination_minor_units']}: expected "
            f"{want['note_count']} notes, got {got['note_count']}"
        )


# Convenience aliases for the two audit-stamp families of PRD 2.4.
assert_common_fields = assert_versioned_entity
assert_reference_data_fields = assert_reference_entity
