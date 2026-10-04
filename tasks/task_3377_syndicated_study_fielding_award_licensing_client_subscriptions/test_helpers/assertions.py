"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version starts at 1"


def assert_study(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["industry_code"], str) and data["industry_code"]
    assert isinstance(data["cycle_year"], int)
    assert isinstance(data["min_sample_per_brand"], int) and data["min_sample_per_brand"] >= 1
    assert data["status"] in [
        "DRAFT", "DESIGN_LOCKED", "FIELDING", "FIELDING_CLOSED", "SCORING",
        "SCORED", "AWARDS_SET", "PUBLISHED", "CANCELLED",
    ]
    assert "active_methodology_id" in data
    assert "published_at" in data
    assert "embargo_lift_at" in data


def assert_brand(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["industry_code"], str) and data["industry_code"]


def assert_client(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["client_type"] in ["BRAND", "AGENCY"]
    assert isinstance(data["country"], str) and data["country"]


def assert_methodology_version(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("study_id", "")), "study_id must be a UUID"
    assert data["change_class"] in ["FULL_COMPARABLE", "ADJUSTED", "BREAK"]
    assert isinstance(data["min_duration_seconds"], int) and data["min_duration_seconds"] >= 1
    assert isinstance(data["straightline_min_items"], int) and data["straightline_min_items"] >= 1
    assert data["pooled_sd_1000"] > 0
    assert data["z_value"] > 0
    assert data["tie_epsilon"] >= 0
    assert isinstance(data["version_no"], int) and data["version_no"] >= 1
    assert data["status"] in ["DRAFT", "PINNED", "SUPERSEDED"]


def assert_factor(data: dict):
    # Factor rows carry only id + created_at: no updated_at, no version (PRD §2.4).
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "factors never carry updated_at"
    assert "version" not in data, "factors never carry version"
    assert data["code"]
    assert 0 < data["weight_bp"] < 10000
    assert isinstance(data["ordinal"], int) and data["ordinal"] >= 1


def assert_sample_frame(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("study_id", ""))
    assert is_valid_uuid(data.get("brand_id", ""))
    assert data["source_type"] in ["PANEL", "CUSTOMER_LIST"]
    assert isinstance(data["target_completes"], int) and data["target_completes"] >= 1
    assert data["status"] in ["OPEN", "CLOSED"]


def assert_response(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("frame_id", ""))
    assert isinstance(data["respondent_token"], str) and data["respondent_token"]
    assert isinstance(data["duration_seconds"], int) and data["duration_seconds"] >= 0
    assert isinstance(data["item_count"], int) and data["item_count"] >= 1
    assert isinstance(data["distinct_values"], int) and data["distinct_values"] >= 1
    assert isinstance(data["factor_scores"], list)
    assert data["quality_status"] in ["ACCEPTED", "REJECTED"]
    assert data.get("reject_reason") in [None, "SPEEDER", "STRAIGHTLINE", "DUPLICATE"]
    assert "submitted_at" in data
    assert "study_id" in data and "brand_id" in data


def assert_brand_result(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("study_id", ""))
    assert is_valid_uuid(data.get("brand_id", ""))
    assert isinstance(data["provisional_accepted_n"], int)
    assert isinstance(data["accepted_n"], int)
    assert data["status"] in ["PROVISIONAL", "FINAL", "AWARDED"]
    for nullable in ("provisional_index", "final_index", "eligible",
                     "significance_group", "rank_position"):
        assert nullable in data, f"{nullable} must be present (null until computed)"


def assert_award(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("study_id", ""))
    assert is_valid_uuid(data.get("brand_id", ""))
    assert data["rank_position"] == 1
    assert data["significance_group"] == 1
    assert data["status"] in ["EMBARGOED", "PUBLISHED"]
    assert "published_at" in data


def assert_license(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("award_id", ""))
    assert is_valid_uuid(data.get("client_id", ""))
    assert data["tier"] in ["DIGITAL", "NATIONAL", "GLOBAL"]
    assert data["term_months"] in [12, 24, 36]
    assert isinstance(data["markets_count"], int) and data["markets_count"] >= 1
    assert isinstance(data["fee_quote_cents"], int)
    assert data["status"] in ["QUOTED", "ACTIVE", "SUSPENDED", "REVOKED", "WITHDRAWN", "EXPIRED"]
    assert isinstance(data["suspension_count"], int) and data["suspension_count"] >= 0
    for nullable in ("fee_final_cents", "activated_at", "expires_at"):
        assert nullable in data, f"{nullable} must be present (null until ACTIVE)"


def assert_usage_audit(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("license_id", ""))
    assert data["severity"] in ["MINOR", "MAJOR"]
    assert data["status"] in ["OPEN", "ESCALATED", "RESOLVED"]
    assert data.get("resolution") in [None, "CONFIRMED", "LICENSE_REVOKED_AUTO"]


def assert_subscription(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("client_id", ""))
    assert is_valid_uuid(data.get("study_id", ""))
    assert data["tier"] in ["DIAGNOSTIC", "BENCHMARK"]
    assert data["status"] in ["TRIAL", "ACTIVE", "CANCELLED", "EXPIRED"]
    assert "starts_at" in data and "ends_at" in data
