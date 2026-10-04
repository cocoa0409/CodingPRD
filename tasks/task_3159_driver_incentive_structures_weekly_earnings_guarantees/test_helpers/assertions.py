"""Entity assertions and domain invariant checkers."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


# --------------------------------------------------------------------------
# Common record properties (PRD §2.4)
# --------------------------------------------------------------------------
def assert_common_fields(data: dict, label: str = "record"):
    """Every primary entity carries id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{label}.id must be a UUID, got {data.get('id')}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be an ISO 8601 timestamp, got {data.get('created_at')}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be an ISO 8601 timestamp, got {data.get('updated_at')}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be an integer >= 1, got {data.get('version')}"
    )


# --------------------------------------------------------------------------
# Per-entity assertions
# --------------------------------------------------------------------------
def assert_market(data: dict):
    assert_common_fields(data, "market")
    assert isinstance(data["market_code"], str) and data["market_code"]
    assert isinstance(data["geo_cells"], list)
    assert isinstance(data["incentive_budget_cents"], int)
    assert isinstance(data["budget_spent_cents"], int)
    assert isinstance(data["budget_reserved_cents"], int)
    assert isinstance(data["budget_available_cents"], int)
    assert data["status"] in ("ACTIVE", "FROZEN", "CLOSED")


def assert_driver(data: dict):
    assert_common_fields(data, "driver")
    assert isinstance(data["market_id"], str)
    assert isinstance(data["display_name"], str)
    assert data["rate_posture"] in ("ELIGIBLE", "PROBATION", "INELIGIBLE")
    assert data["fraud_posture"] in ("CLEAR", "WATCH", "RESTRICTED")
    for counter in (
        "acceptance_rate_bps",
        "cancellation_rate_bps",
        "offers_total",
        "accepted_total",
        "cancelled_total",
    ):
        assert isinstance(data[counter], int) and data[counter] >= 0, (
            f"driver.{counter} must be a non-negative integer, got {data.get(counter)}"
        )
    assert data["account_status"] in ("ACTIVE", "DEACTIVATED")


def assert_program(data: dict):
    assert_common_fields(data, "program")
    assert data["program_type"] in ("STREAK", "BONUS_ZONE", "CHALLENGE", "GUARANTEE")
    assert data["status"] in ("DRAFT", "ACTIVE", "PAUSED", "RETIRED")
    assert data["stacking_class"] in ("STACKABLE", "EXCLUSIVE")
    assert isinstance(data["excluded_ride_types"], list)
    assert isinstance(data["promised_make_up_max_cents"], int)


def assert_ride(data: dict):
    assert_common_fields(data, "ride")
    assert data["ride_type"] in ("STANDARD", "SHARED", "SCHEDULED", "LUX")
    assert data["status"] in (
        "OFFERED",
        "ACCEPTED",
        "COMPLETED",
        "DRIVER_CANCELLED",
        "RIDER_CANCELLED",
        "DECLINED",
        "UNDER_REVIEW",
        "VOIDED",
    )
    assert isinstance(data["base_fare_cents"], int) and data["base_fare_cents"] >= 0
    assert isinstance(data["tips_cents"], int) and data["tips_cents"] >= 0
    assert isinstance(data["qualifying_earnings_cents"], int)


def assert_enrollment(data: dict):
    assert_common_fields(data, "enrollment")
    assert data["status"] in ("ACTIVE", "COMPLETED", "EXPIRED", "CANCELLED")
    assert isinstance(data["progress_count"], int) and data["progress_count"] >= 0
    assert isinstance(data["streak_broken"], bool)
    assert isinstance(data["payout_cents"], int) and data["payout_cents"] >= 0


def assert_settlement(data: dict):
    assert_common_fields(data, "settlement")
    assert data["status"] in ("DRAFT", "FINALIZED", "PAID", "REOPENED", "VOID")
    assert data["basis_variant"] in ("PROVISIONAL", "FINAL")
    for field in (
        "promised_cents",
        "actual_gross_cents",
        "qualifying_ride_count",
        "make_up_cents",
    ):
        assert isinstance(data[field], int), f"settlement.{field} must be an integer"


def assert_statement(data: dict):
    assert_common_fields(data, "statement")
    assert data["status"] in ("DRAFT", "PUBLISHED", "DISPUTED", "AMENDED")
    for field in (
        "base_fares_cents",
        "tips_cents_total",
        "bonus_total_cents",
        "make_up_total_cents",
        "adjustments_cents",
        "total_cents",
    ):
        assert isinstance(data[field], int), f"statement.{field} must be an integer"


def assert_appeal(data: dict):
    assert_common_fields(data, "appeal")
    assert data["subject_type"] in ("ELIGIBILITY", "STATEMENT")
    assert data["status"] in (
        "FILED",
        "UNDER_REVIEW",
        "MORE_INFO",
        "RESOLVED_UPHELD",
        "RESOLVED_OVERTURNED",
        "ESCALATED",
        "WITHDRAWN",
    )
    assert isinstance(data["round_count"], int) and data["round_count"] >= 0


def assert_fraud_flag(data: dict):
    assert_common_fields(data, "fraud_flag")
    assert data["signal_type"] in ("INFLATED_RIDE", "COLLUSION", "LOCATION_SPOOF")
    assert data["status"] in ("OPEN", "CONFIRMED", "DISMISSED")
    assert isinstance(data["severity"], int) and 1 <= data["severity"] <= 10
    assert isinstance(data["acute_score"], int)
    assert isinstance(data["chronic_score"], int)


def assert_supply_shortfall(data: dict):
    assert_common_fields(data, "supply_shortfall")
    assert data["status"] in ("OPEN", "ADDRESSED", "EXPIRED")
    assert isinstance(data["hour_bucket"], int) and 0 <= data["hour_bucket"] <= 167
    assert isinstance(data["severity_bps"], int) and 1 <= data["severity_bps"] <= 10000
    assert isinstance(data["recommended_bonus_cents"], int)


def assert_cost_forecast(data: dict):
    assert_common_fields(data, "cost_forecast")
    assert data["status"] in ("DRAFT", "APPROVED", "SUPERSEDED", "REJECTED")
    assert isinstance(data["projected_incremental_rides"], int)
    assert isinstance(data["projected_cannibalized_rides"], int)
    assert isinstance(data["projected_cost_cents"], int)
    assert isinstance(data["forecast_revision"], int)


# --------------------------------------------------------------------------
# Domain invariants
# --------------------------------------------------------------------------
def assert_market_budget_conservation(market: dict):
    """spent + reserved + available == incentive_budget_cents (PRD §2.7)."""
    total = (
        market["budget_spent_cents"]
        + market["budget_reserved_cents"]
        + market["budget_available_cents"]
    )
    assert total == market["incentive_budget_cents"], (
        f"budget conservation violated: spent {market['budget_spent_cents']} + "
        f"reserved {market['budget_reserved_cents']} + available "
        f"{market['budget_available_cents']} == {total}, expected "
        f"{market['incentive_budget_cents']}"
    )
    assert market["budget_available_cents"] >= 0


def assert_statement_total_invariant(statement: dict):
    """total_cents == base + tips + bonus + make_up + adjustments (PRD §3.10)."""
    expected = (
        statement["base_fares_cents"]
        + statement["tips_cents_total"]
        + statement["bonus_total_cents"]
        + statement["make_up_total_cents"]
        + statement["adjustments_cents"]
    )
    assert statement["total_cents"] == expected, (
        f"statement total_cents {statement['total_cents']} != invariant sum {expected}"
    )
