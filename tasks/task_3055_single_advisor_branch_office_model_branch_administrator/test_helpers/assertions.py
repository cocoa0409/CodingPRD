"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1


def assert_advisor(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert data["status"] in [
        "CANDIDATE", "TRAINEE", "VALIDATED", "PRACTICING",
        "RETIRING", "RETIRED", "TERMINATED",
    ]
    assert isinstance(data["cumulative_commissions_cents"], int)


def assert_territory(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["community_name"], str) and data["community_name"]
    assert isinstance(data["household_capacity"], int) and data["household_capacity"] >= 1
    assert data["status"] in ["OPEN", "ASSIGNED", "RETIRED"]


def assert_branch(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["community_name"], str) and data["community_name"]
    assert data["operating_status"] in [
        "PROPOSED", "SITE_APPROVED", "OPEN", "SUSPENDED", "CLOSED",
    ]
    assert data["staffing_status"] in [
        "UNSTAFFED", "ADVISOR_ASSIGNED", "FULLY_STAFFED", "SUCCESSION_PENDING",
    ]
    assert isinstance(data["household_count"], int) and data["household_count"] >= 0
    assert isinstance(data["assets_under_care_dollars"], int) and data["assets_under_care_dollars"] >= 0
    assert data["service_tier"] in ["TIER_1", "TIER_2", "TIER_3"]
    assert isinstance(data["tier_score"], int)


def assert_administrator(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["monthly_salary_cents"], int) and data["monthly_salary_cents"] > 0
    assert data["status"] in ["HIRED", "ACTIVE", "ON_LEAVE", "RELEASED"]


def assert_training_program(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["advisor_id"], str)
    assert isinstance(data["goal_cents"], int) and data["goal_cents"] > 0
    assert data["status"] in [
        "ACTIVE", "MILESTONE_PENDING", "REMEDIATION", "COMPLETED", "FAILED",
    ]


def assert_lease(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["monthly_rent_cents"], int) and data["monthly_rent_cents"] > 0
    assert data["status"] in ["DRAFT", "SIGNED", "EXPIRED", "TERMINATED"]


def assert_financial_period(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["OPEN", "CLOSED", "FINALIZED"]
    assert isinstance(data["gross_revenue_cents"], int)
    assert isinstance(data["total_charges_cents"], int)
    assert isinstance(data["net_profit_cents"], int)
    assert isinstance(data["advisor_share_cents"], int)
    assert isinstance(data["deficit_carryforward_cents"], int)


def assert_charge(data: dict):
    _assert_common_fields(data)
    assert data["charge_type"] in [
        "LEASE_RENT", "BOA_PAYROLL", "EQUIPMENT", "DEFICIT_CARRYOVER",
    ]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["status"] in ["POSTED", "REVERSED"]


def assert_goodwill_transfer(data: dict):
    _assert_common_fields(data)
    assert data["valuation_mode"] in ["INTERNAL_SUCCESSION", "OPEN_MARKET"]
    assert isinstance(data["trailing_revenue_cents"], int)
    assert isinstance(data["offer_price_cents"], int)
    assert isinstance(data["escrow_deposit_cents"], int)
    assert isinstance(data["negotiation_round"], int)
    assert data["status"] in [
        "OFFERED", "NEGOTIATING", "ACCEPTED", "COMPLETED",
        "DECLINED", "EXPIRED", "CANCELLED",
    ]


def assert_solicitation_request(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["SUBMITTED", "APPROVED", "DENIED", "WITHDRAWN"]


def assert_production_record(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["gross_commission_cents"], int) and data["gross_commission_cents"] > 0
    assert 0 < data["payout_rate"] <= 1
    assert isinstance(data["commissions_cents"], int)
    assert data["status"] in ["POSTED", "REVERSED"]
    assert "version" not in data, "append-only record must not expose a version"


def assert_milestone_evaluation(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["production_cents"], int)
    assert data["outcome"] in ["PASS", "FAIL"]
    assert "version" not in data, "append-only record must not expose a version"


def assert_shelf_entry(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in ["PROPOSED", "APPROVED", "RETIRED"]
    assert "version" not in data, "append-only record must not expose a version"


def assert_contact(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["contact_outcome"] in [
        "NO_ANSWER", "PITCHED", "APPOINTMENT_SET", "CLIENT_CONVERTED",
    ]
    assert "version" not in data, "append-only record must not expose a version"
    assert "updated_at" not in data, "append-only record must not expose updated_at"


def assert_period_invariants(period: dict):
    """Domain invariants that must hold on any period snapshot."""
    assert period["net_profit_cents"] == (
        period["gross_revenue_cents"] - period["total_charges_cents"]
    ), "net_profit_cents must equal gross revenue minus total charges"
    if period["net_profit_cents"] <= 0:
        assert period["advisor_share_cents"] == 0, "non-positive net floors the share at 0"
    if period["net_profit_cents"] < 0 and period["status"] in ("CLOSED", "FINALIZED"):
        assert period["deficit_carryforward_cents"] == abs(period["net_profit_cents"])
