"""Entity assertions and domain invariant checkers (PRD §2.9 common properties)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive int, got {data.get('version')!r}"
    )


def assert_comp_program(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["fiscal_year"], int)
    assert isinstance(data["merit_budget_cents"], int)
    assert isinstance(data["refresh_budget_cents"], int)
    assert isinstance(data["pricing_as_of_date"], str)
    assert data["status"] in [
        "DRAFT", "FRAMEWORK_LOCKED", "PRICING", "MAPPING_OPEN", "PUBLISHED", "ARCHIVED",
    ]
    assert isinstance(data["total_payroll_projection_cents"], int)
    assert isinstance(data["refresh_budget_spent_cents"], int)


def assert_job_family(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["name"], str) and data["name"]
    assert data["status"] in ["ACTIVE", "RETIRED"]


def assert_job_level(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["level_code"], str) and data["level_code"]
    assert isinstance(data["title"], str)
    assert isinstance(data["rank_order"], int)


def assert_geo_zone(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["zone_code"], str) and data["zone_code"]
    assert isinstance(data["differential_ratio"], (int, float))
    assert data["differential_ratio"] > 0
    assert isinstance(data["effective_ratio"], (int, float))
    assert data["effective_ratio"] > 0


def assert_job_profile(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["DRAFT", "IN_REVIEW", "APPROVED", "RETIRED"]
    assert data["flsa_classification"] in ["PENDING", "EXEMPT", "NON_EXEMPT"]
    assert isinstance(data["salary_basis_weekly_cents"], int)
    assert isinstance(data["duties_test_passed"], bool)


def assert_market_survey(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["SUBMITTED", "ACCEPTED", "REJECTED"]
    assert isinstance(data["survey_year"], int)


def assert_market_cut(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["p50_cents"], int)
    assert isinstance(data["sample_size"], int) and data["sample_size"] >= 1
    assert isinstance(data["excluded_from_composite"], bool)


def assert_progression_policy(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["min_midpoint_progression_pct"], (int, float))
    assert isinstance(data["max_overlap_pct"], (int, float))


def assert_pay_band(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["DRAFT", "PRICED", "COMP_APPROVED", "PUBLISHED", "SUPERSEDED"]
    assert data["target_percentile"] in ["P50", "P62_5", "P75"]
    assert isinstance(data["spread_pct"], (int, float)) and data["spread_pct"] >= 0
    if data.get("midpoint_cents") is not None:
        assert isinstance(data["midpoint_cents"], int)
        assert data["min_cents"] <= data["midpoint_cents"] <= data["max_cents"]


def assert_department(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["adjustment_pool_cents"], int)
    assert isinstance(data["committed_pool_cents"], int)
    assert isinstance(data["projected_payroll_cents"], int)


def assert_employee(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["employee_ref"], str) and data["employee_ref"]
    assert isinstance(data["base_salary_cents"], int)
    assert data["status"] in ["ACTIVE", "TERMINATED"]
    assert data["range_position"] in ["BELOW_MIN", "IN_RANGE", "ABOVE_MAX", "UNBANDED"]
    if data["range_position"] == "UNBANDED":
        assert data.get("compa_ratio") is None
    else:
        assert isinstance(data["compa_ratio"], (int, float))


def assert_mapping_decision(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [
        "DRAFT", "SUBMITTED", "HRBP_REVIEWED", "COMP_TRIAGED", "APPROVED",
        "REJECTED", "RETURNED", "WITHDRAWN", "REVERSED",
    ]


def assert_exception_request(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [
        "SUBMITTED", "HRBP_PASSED", "FINANCE_REVIEW", "APPROVED",
        "DENIED", "RETURNED", "RESCINDED",
    ]
    assert data["type"] in [
        "ABOVE_MAX_HIRE", "BELOW_MIN_RETENTION", "OFF_CYCLE_INCREASE", "GEO_MISMATCH",
    ]
    assert isinstance(data["finance_required"], bool)
    assert isinstance(data["requested_salary_cents"], int)


def assert_refresh_cycle(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [
        "SCHEDULED", "IMPACT_COMPUTED", "APPROVED", "APPLIED", "CANCELLED",
    ]
    assert isinstance(data["planned_window_start"], str)
    assert isinstance(data["planned_window_end"], str)
    assert isinstance(data["effective_date"], str)


def assert_ratio_precision_6(value: float):
    """Geo differential figures carry six decimal places (PRD §2.5)."""
    from decimal import Decimal
    d = Decimal(str(value))
    assert -d.as_tuple().exponent <= 6, f"expected <= 6 decimal places, got {value!r}"


def assert_pct_precision_4(value: float):
    """Policy/position percentages carry four decimal places (PRD §2.5)."""
    from decimal import Decimal
    d = Decimal(str(value))
    assert -d.as_tuple().exponent <= 4, f"expected <= 4 decimal places, got {value!r}"
