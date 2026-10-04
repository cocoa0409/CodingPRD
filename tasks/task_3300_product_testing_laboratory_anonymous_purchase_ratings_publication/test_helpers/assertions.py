"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)


def assert_product_category(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["refresh_cycle_months"], int) and data["refresh_cycle_months"] >= 1
    assert 0 <= data["market_share_pct"] <= 100
    assert 0 <= data["member_interest_pct"] <= 100
    assert data["status"] in ["ACTIVE", "SUSPENDED", "RETIRED"]
    assert "selection_score" in data
    assert data.get("version", 0) >= 1


def assert_test_program(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data.get("category_id", "")), "category_id must be valid UUID"
    assert isinstance(data["fiscal_year"], int)
    assert isinstance(data["budget_cents"], int) and data["budget_cents"] >= 0
    assert isinstance(data["committed_cents"], int) and data["committed_cents"] >= 0
    assert data["status"] in [
        "PROPOSED", "APPROVED", "SAMPLE_SOURCING", "TESTING",
        "SCORING", "READY_FOR_PUBLICATION", "PUBLISHED", "CANCELLED",
    ]
    assert data.get("version", 0) >= 1


def assert_lab_protocol(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["protocol_code"], str) and len(data["protocol_code"]) > 0
    assert isinstance(data["measurement_repeat_min"], int) and data["measurement_repeat_min"] >= 1
    assert 1 <= data["perf_weight_pct"] <= 98
    assert 1 <= data["reliability_weight_pct"] <= 98
    assert data["convenience_weight_pct"] == 100 - data["perf_weight_pct"] - data["reliability_weight_pct"]
    assert data["convenience_weight_pct"] >= 1
    assert data["status"] in ["DRAFT", "IN_REVIEW", "ACTIVE", "SUPERSEDED", "RETIRED"]
    assert data.get("version", 0) >= 1


def assert_test_sample(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["model_label"], str) and len(data["model_label"]) > 0
    assert isinstance(data["required_units"], int) and data["required_units"] >= 1
    assert data["sourcing_mode"] == "ANONYMOUS_RETAIL"
    assert isinstance(data["sourced_units"], int) and data["sourced_units"] >= 0
    assert isinstance(data["sourcing_complete"], bool)
    assert isinstance(data["tested_units"], int) and data["tested_units"] >= 0
    assert isinstance(data["testing_complete"], bool)
    assert data["status"] in ["PLANNED", "SOURCING", "IN_LAB", "SCORED"]
    assert data.get("version", 0) >= 1


def assert_purchase_order(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["lines"], list) and len(data["lines"]) >= 1
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["shipping_cents"], int) and data["shipping_cents"] >= 0
    assert isinstance(data["tax_cents"], int)
    assert isinstance(data["total_cents"], int)
    assert data["total_cents"] == data["subtotal_cents"] + data["shipping_cents"] + data["tax_cents"]
    assert data["status"] in ["DRAFT", "PLACED", "RECEIVED", "VERIFIED", "CANCELLED"]
    assert data.get("version", 0) >= 1


def assert_measurement(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["unit_index"], int) and data["unit_index"] >= 1
    assert isinstance(data["metric_code"], str) and len(data["metric_code"]) > 0
    assert "value_num" in data
    # append-only: no version, no updated_at
    assert "version" not in data, "Measurement must not carry version"
    assert "updated_at" not in data, "Measurement must not carry updated_at"


def assert_survey_wave(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["min_responses"], int) and data["min_responses"] >= 1
    assert isinstance(data["response_count"], int) and data["response_count"] >= 0
    assert isinstance(data["threshold_met"], bool)
    assert isinstance(data["responses"], list)
    assert data["status"] in ["OPEN", "CLOSED", "QUALIFIED", "DISQUALIFIED"]
    assert data.get("version", 0) >= 1


def assert_rating_publication(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["rated_models"], list)
    assert isinstance(data["model_count"], int) and data["model_count"] == len(data["rated_models"])
    assert isinstance(data["manufacturer_responses"], list)
    assert data["status"] in [
        "DRAFT", "UNDER_REVIEW", "REVISION_REQUESTED",
        "APPROVED", "PUBLISHED", "WITHDRAWN",
    ]
    assert data.get("version", 0) >= 1


def assert_safety_finding(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["severity"] in ["CRITICAL", "MAJOR", "MINOR"]
    assert isinstance(data["hazard_flag"], bool)
    assert isinstance(data["escalation_tier"], int) and 0 <= data["escalation_tier"] <= 3
    assert data["status"] in ["OPEN", "ESCALATED", "RESOLVED", "CLOSED"]
    assert data.get("version", 0) >= 1


def assert_member(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert isinstance(data["subscriptions"], list)
    assert data["status"] in ["ACTIVE", "LAPSED", "CANCELLED"]
    assert data.get("version", 0) >= 1


def assert_program_budget_invariant(program: dict):
    """committed_cents never exceeds budget and never goes negative."""
    assert 0 <= program["committed_cents"] <= program["budget_cents"]
