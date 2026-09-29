"""Entity assertions, instant canonicalisation and ledger invariant checkers."""

from datetime import datetime, timezone
from decimal import Decimal

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AffiliationStatus,
    ConfirmationStatus,
    DepositStatus,
    DisputeStatus,
    EnrollmentStatus,
    ExchangeRequestStatus,
    GetawayOfferStatus,
    LedgerEntryType,
    MatchingRunStatus,
    QualityRating,
    RelatedEntityType,
    RentalStatus,
)


# ------------------------------------------------------------------ instants

def canonical_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, with or without fractional seconds.

    Comparisons on instants are made on the parsed value so that a server
    rendering `2029-06-14T00:00:00.000Z` and one rendering
    `2029-06-14T00:00:00Z` are both accepted (PRD §2.4 fixes the semantics of
    the instant, and both spellings denote the same instant).
    """
    assert isinstance(value, str) and value, f"Expected an ISO 8601 instant, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def instants_equal(actual: str, expected: str) -> bool:
    """True when two ISO 8601 renderings denote the same instant."""
    return canonical_instant(actual) == canonical_instant(expected)


def assert_instant_equals(actual: str, expected: str, label: str = "instant") -> None:
    assert instants_equal(actual, expected), (
        f"Expected {label} {expected}, got {actual}"
    )


def assert_instant_absent(value, label: str = "instant") -> None:
    assert value is None, f"Expected {label} to be null, got {value!r}"


def assert_iso_date(value: str, label: str = "date") -> None:
    assert isinstance(value, str), f"{label} must be a string, got {value!r}"
    datetime.strptime(value, "%Y-%m-%d")


def assert_two_decimal_string(value, label: str = "score") -> None:
    """The only non-integer API values carry exactly 2 decimal places (PRD §2.6)."""
    assert value is not None, f"{label} must be present"
    text = str(value)
    assert "." in text and len(text.split(".")[1]) == 2, (
        f"{label} must carry exactly 2 decimal places, got {value!r}"
    )
    assert Decimal("1.00") <= Decimal(text) <= Decimal("10.00"), (
        f"{label} must lie between 1.00 and 10.00, got {value!r}"
    )


def decimal_of(value) -> Decimal:
    return Decimal(str(value))


def assert_decimal_equals(actual, expected: str, label: str = "value") -> None:
    """Compare a decimal-valued field numerically.

    The PRD fixes the numeric value of multipliers, scores and factors but not
    their JSON spelling, so `1.5`, `"1.50"` and `1.50` all satisfy a claim
    about the factor 1.50.
    """
    assert actual is not None, f"{label} must be present"
    assert decimal_of(actual) == Decimal(expected), (
        f"Expected {label} {expected}, got {actual!r}"
    )


# ------------------------------------------------------------ common fields

def assert_common_fields(data: dict, entity: str = "record") -> None:
    """Every record family carries id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity}.id must be a UUID string, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be an ISO 8601 UTC timestamp, "
        f"got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be an ISO 8601 UTC timestamp, "
        f"got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer of at least 1, got {data.get('version')!r}"
    )


def _values(enum_cls) -> list:
    return [member.value for member in enum_cls]


# ------------------------------------------------------------------ entities

def assert_membership_tier(data: dict) -> None:
    assert_common_fields(data, "membership tier")
    assert data["tier_code"] in ("BASIC", "PLUS", "ELITE")
    for field in (
        "annual_dues_cents",
        "base_exchange_fee_cents",
        "priority_surcharge_cents",
        "priority_window_days",
        "max_active_requests",
        "cancellation_fee_cents",
        "reinstatement_fee_cents",
        "extension_fee_cents_per_month",
    ):
        assert isinstance(data[field], int) and data[field] >= 0, (
            f"membership tier {field} must be a non-negative integer, got {data[field]!r}"
        )
    assert 0 <= data["deposit_first_bonus_pct"] <= 100


def assert_resort(data: dict) -> None:
    assert_common_fields(data, "resort")
    assert 1 <= len(data["name"]) <= 120
    assert 2 <= len(data["region_code"]) <= 8
    assert data["required_annual_deposit_units"] >= 1
    assert data["initial_quality_rating"] in _values(QualityRating)
    assert data["units_per_size"] >= 1
    assert 1 <= data["demand_index"] <= 5
    assert data["affiliation_status"] in _values(AffiliationStatus)
    assert data["quality_rating"] in _values(QualityRating)
    assert data["review_count"] >= 0
    assert 0 <= data["downgrade_notches"] <= 3
    assert data["complaint_strikes"] >= 0
    assert data["deposits_committed_count"] >= 0
    assert data["committed_nights"] == data["deposits_committed_count"] * 8, (
        "committed_nights must equal eight nights per committed deposit"
    )
    if data["quality_score"] is not None:
        assert_two_decimal_string(data["quality_score"], "resort.quality_score")


def assert_season_band(data: dict) -> None:
    assert_common_fields(data, "season band")
    assert is_valid_uuid(data["resort_id"])
    assert data["band_code"] in ("PLATINUM", "GOLD", "SILVER", "BRONZE")
    for field in ("start_month_day", "end_month_day"):
        value = data[field]
        assert len(value) == 5 and value[2] == "-", (
            f"season band {field} must be MM-DD, got {value!r}"
        )
    # PRD §3.1 fixes the numeric factor (1.50 / 1.25 / 1.00 / 0.70) but not its
    # JSON spelling, so compare numerically rather than by string form.
    assert decimal_of(data["season_multiplier"]) in (
        Decimal("1.50"),
        Decimal("1.25"),
        Decimal("1.00"),
        Decimal("0.70"),
    )


def assert_member(data: dict) -> None:
    assert_common_fields(data, "member")
    assert "@" in data["email"]
    assert 1 <= len(data["full_name"]) <= 120
    assert is_valid_uuid(data["tier_id"])
    assert data["enrollment_status"] in _values(EnrollmentStatus)
    assert data["trading_power_balance"] >= 0, "trading_power_balance may never go below 0"
    assert data["wallet_credit_cents"] >= 0, "wallet_credit_cents may never go below 0"
    assert data["active_request_count"] >= 0
    if data["dues_paid_through"] is not None:
        assert_iso_date(data["dues_paid_through"], "member.dues_paid_through")


def assert_deposit(data: dict) -> None:
    assert_common_fields(data, "deposit")
    assert is_valid_uuid(data["member_id"])
    assert is_valid_uuid(data["resort_id"])
    assert data["unit_size"] in ("STUDIO", "ONE_BR", "TWO_BR", "THREE_BR")
    assert_iso_date(data["check_in_date"], "deposit.check_in_date")
    assert_iso_date(data["occupancy_end_date"], "deposit.occupancy_end_date")
    assert data["season_band_code"] in ("PLATINUM", "GOLD", "SILVER", "BRONZE")
    assert isinstance(data["awarded_power"], int) and data["awarded_power"] >= 1, (
        "awarded_power is floored at 1 point"
    )
    assert data["restoration_haircut_power"] >= 0
    assert data["remaining_power"] == data["awarded_power"] - data["restoration_haircut_power"], (
        "remaining_power must equal awarded_power minus restoration_haircut_power"
    )
    assert 0 <= data["extension_months_purchased"] <= 12
    assert is_iso8601_timestamp(data["expires_at"])
    assert data["deposit_status"] in _values(DepositStatus)
    assert data["rental_status"] in _values(RentalStatus)


def assert_exchange_request(data: dict) -> None:
    assert_common_fields(data, "exchange request")
    assert is_valid_uuid(data["member_id"])
    assert is_valid_uuid(data["requested_resort_id"])
    assert data["requested_unit_size"] in ("STUDIO", "ONE_BR", "TWO_BR", "THREE_BR")
    assert_iso_date(data["window_start_date"], "window_start_date")
    assert_iso_date(data["window_end_date"], "window_end_date")
    assert data["funding_mode"] in ("DEPOSIT_FIRST", "REQUEST_FIRST")
    assert data["power_budget"] >= 0
    assert data["required_power_estimate"] >= 1
    assert data["quoted_charge_cents"] >= 0
    assert data["charge_refunded_cents"] >= 0
    assert data["status"] in _values(ExchangeRequestStatus)
    assert data["priority_score"] >= 0, "priority_score is floored at 0"
    assert data["decline_count"] >= 0


def assert_confirmation(data: dict) -> None:
    assert_common_fields(data, "confirmation")
    assert is_valid_uuid(data["exchange_request_id"])
    assert is_valid_uuid(data["awarded_deposit_id"])
    assert_iso_date(data["awarded_check_in_date"], "awarded_check_in_date")
    assert data["power_debited"] >= 0
    assert data["status"] in _values(ConfirmationStatus)


def assert_matching_run(data: dict) -> None:
    assert_common_fields(data, "matching run")
    assert data["run_sequence"] >= 1
    assert is_iso8601_timestamp(data["as_of_utc"])
    assert data["status"] in _values(MatchingRunStatus)
    for counter in (
        "lapsed_member_count",
        "expired_deposit_count",
        "probation_resort_count",
        "expired_request_count",
        "denied_request_count",
        "matched_count",
        "waitlisted_count",
        "completed_confirmation_count",
        "getaway_listed_count",
    ):
        assert isinstance(data[counter], int) and data[counter] >= 0, (
            f"run counter {counter} must be a non-negative integer, got {data[counter]!r}"
        )


def assert_getaway_offer(data: dict) -> None:
    assert_common_fields(data, "getaway offer")
    assert is_valid_uuid(data["deposit_id"])
    assert 29900 <= data["list_price_cents"] <= 249900, (
        "list_price_cents is clamped into the 29900..249900 corridor"
    )
    assert data["urgency_discount_pct"] in (0, 10, 20, 35)
    assert data["status"] in _values(GetawayOfferStatus)


def assert_dispute(data: dict) -> None:
    assert_common_fields(data, "dispute")
    assert is_valid_uuid(data["member_id"])
    assert data["subject_type"] in ("TRADING_POWER", "RESORT_QUALITY")
    assert 1 <= len(data["narrative"]) <= 2000
    assert data["status"] in _values(DisputeStatus)
    assert 0 <= data["round_count"] <= 2
    assert isinstance(data["granted_power_adjustment"], int)


def assert_quality_review(data: dict) -> None:
    assert_common_fields(data, "quality review")
    assert is_valid_uuid(data["resort_id"])
    assert is_valid_uuid(data["confirmation_id"])
    for field in ("cleanliness_score", "service_score", "amenities_score"):
        assert 1 <= data[field] <= 10, f"{field} must be an integer from 1 to 10"
    assert_two_decimal_string(data["composite_score"], "composite_score")


def assert_ledger_entry(data: dict) -> None:
    assert_common_fields(data, "ledger entry")
    assert is_valid_uuid(data["member_id"])
    assert data["entry_type"] in _values(LedgerEntryType)
    assert isinstance(data["power_delta"], int)
    assert isinstance(data["cash_delta_cents"], int)
    assert data["related_entity_type"] in _values(RelatedEntityType)
    assert is_valid_uuid(data["related_entity_id"])
    assert isinstance(data["description"], str) and data["description"]


# ------------------------------------------------------- domain invariants

def sum_power(entries) -> int:
    return sum(entry["power_delta"] for entry in entries)


def sum_cash(entries) -> int:
    return sum(entry["cash_delta_cents"] for entry in entries)


def assert_balances_match_ledger(member: dict, entries) -> None:
    """Both member balances are sums over that member's ledger entries."""
    own = [entry for entry in entries if entry["member_id"] == member["id"]]
    assert sum_power(own) == member["trading_power_balance"], (
        f"trading_power_balance {member['trading_power_balance']} must equal the "
        f"ledger power sum {sum_power(own)}"
    )
    assert sum_cash(own) == member["wallet_credit_cents"], (
        f"wallet_credit_cents {member['wallet_credit_cents']} must equal the "
        f"ledger cash sum {sum_cash(own)}"
    )


def assert_resort_occupancy_counters(resort: dict, deposits) -> None:
    """deposits_committed_count counts BANKED, RESERVED and USED weeks only."""
    committed = [
        deposit
        for deposit in deposits
        if deposit["resort_id"] == resort["id"]
        and deposit["deposit_status"] in ("BANKED", "RESERVED", "USED")
    ]
    assert resort["deposits_committed_count"] == len(committed), (
        f"deposits_committed_count {resort['deposits_committed_count']} must equal "
        f"the {len(committed)} committed weeks of this resort"
    )
    assert resort["committed_nights"] == 8 * len(committed)


def assert_active_request_count(member: dict, requests) -> None:
    live = [
        request
        for request in requests
        if request["member_id"] == member["id"]
        and request["status"] in ("SUBMITTED", "WAITLISTED", "MATCHED")
    ]
    assert member["active_request_count"] == len(live), (
        f"active_request_count {member['active_request_count']} must equal the "
        f"{len(live)} SUBMITTED, WAITLISTED or MATCHED requests of this member"
    )


def entries_of_type(entries, entry_type: str) -> list:
    return [entry for entry in entries if entry["entry_type"] == entry_type]
