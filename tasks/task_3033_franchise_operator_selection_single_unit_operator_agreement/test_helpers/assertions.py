"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be a positive integer"


def assert_candidate(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert isinstance(data["home_market_code"], str)
    assert isinstance(data["relocation_willing"], bool)
    assert isinstance(data["liquid_capital_cents"], int) and data["liquid_capital_cents"] >= 0
    assert data["candidate_status"] in ["REGISTERED", "IN_SELECTION", "SELECTED", "WITHDRAWN", "DISQUALIFIED"]
    assert "active_application_id" in data


def assert_application(data: dict):
    _assert_common(data)
    assert data["stage"] in [
        "SUBMITTED", "SCREENING", "INTERVIEWS", "BUSINESS_ASSESSMENT",
        "IN_RESTAURANT", "COMMITTEE_REVIEW", "APPROVED", "REJECTED",
        "WITHDRAWN", "EXPIRED",
    ]
    assert data["assessment_verdict"] in ["PENDING", "PASS", "FAIL"]
    assert data["experience_verdict"] in ["PENDING", "PASS", "FAIL"]
    assert data["committee_decision"] in ["NONE", "APPROVE", "REJECT"]


def assert_interview_round(data: dict):
    _assert_common(data)
    assert isinstance(data["round_index"], int) and data["round_index"] >= 1
    assert data["status"] in ["SCHEDULED", "SUBMITTED", "CANCELLED"]


def assert_business_assessment(data: dict):
    _assert_common(data)
    assert data["status"] in ["DRAFT", "SUBMITTED", "EVALUATED"]


def assert_restaurant(data: dict):
    _assert_common(data)
    assert isinstance(data["site_code"], str)
    assert data["restaurant_status"] in ["PIPELINE", "AVAILABLE", "ASSIGNED", "TRANSITION"]
    assert data["sunday_closed"] is True


def assert_experience(data: dict):
    _assert_common(data)
    assert isinstance(data["required_shift_count"], int) and data["required_shift_count"] >= 0
    assert isinstance(data["completed_shift_count"], int) and data["completed_shift_count"] >= 0
    assert data["completed_shift_count"] <= data["required_shift_count"]
    assert data["status"] in ["SCHEDULED", "IN_PROGRESS", "COMPLETED", "SHORTFALL", "CANCELLED"]


def assert_operator(data: dict):
    _assert_common(data)
    assert data["operator_status"] in ["ONBOARDING", "ACTIVE", "SUSPENDED", "EXITING", "EXITED"]
    assert isinstance(data["residency_verified"], bool)
    assert isinstance(data["full_time_attested"], bool)
    assert isinstance(data["lifetime_revenue_share_cents"], int) and data["lifetime_revenue_share_cents"] >= 0


def assert_operator_agreement(data: dict):
    _assert_common(data)
    assert data["transferable"] is False
    assert data["equity_stake_bps"] == 0
    assert data["agreement_status"] in ["DRAFT", "EXECUTED", "SUSPENDED", "TERMINATED"]


def assert_operating_week(data: dict):
    _assert_common(data)
    assert data["operating_day_count"] == 6
    assert isinstance(data["forecast_revenue_cents"], int) and data["forecast_revenue_cents"] >= 0
    assert isinstance(data["planned_labor_hours"], int) and data["planned_labor_hours"] >= 0
    assert data["week_status"] in ["PLANNED", "OPEN", "CLOSED"]


def assert_scorecard(data: dict):
    _assert_common(data)
    assert data["scorecard_status"] in ["DRAFT", "PUBLISHED", "DISPUTED", "FINAL"]
    for f in ("food_safety_score", "service_speed_score", "community_engagement_score"):
        assert isinstance(data[f], int) and 0 <= data[f] <= 100


def assert_relocation_request(data: dict):
    _assert_common(data)
    assert data["kind"] in ["RELOCATION", "SECOND_LOCATION"]
    assert data["request_status"] in ["SUBMITTED", "COMMITTEE_REVIEW", "APPROVED", "DENIED", "WITHDRAWN"]
    assert isinstance(data["votes_for"], int) and data["votes_for"] >= 0
    assert isinstance(data["votes_against"], int) and data["votes_against"] >= 0


def assert_exit_case(data: dict):
    _assert_common(data)
    assert data["reason"] in ["VOLUNTARY", "INVOLUNTARY", "NON_RENEWAL"]
    assert data["exit_status"] in ["OPEN", "SUCCESSOR_PENDING", "SUCCESSOR_APPROVED", "COMPLETED", "CANCELLED"]


def assert_revenue_share_statement(data: dict):
    _assert_common(data)
    assert isinstance(data["gross_revenue_cents"], int) and data["gross_revenue_cents"] >= 0
    assert isinstance(data["brand_fee_cents"], int) and data["brand_fee_cents"] >= 0
    assert isinstance(data["occupancy_charge_cents"], int) and data["occupancy_charge_cents"] >= 0
    assert isinstance(data["operator_share_cents"], int) and data["operator_share_cents"] >= 0
    assert data["statement_kind"] in ["PROVISIONAL", "FINAL"]
    assert data["statement_status"] in ["ISSUED", "SETTLED", "VOID"]


def assert_committee_vote(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["vote"] in ["FOR", "AGAINST"]
    # Immutable ballot: no updated_at, no version.
    assert "updated_at" not in data
    assert "version" not in data
