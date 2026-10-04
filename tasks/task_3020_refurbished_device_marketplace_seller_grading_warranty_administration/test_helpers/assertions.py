"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

COMMON_FIELDS = ("id", "created_at", "updated_at", "version")


def assert_common_fields(data: dict):
    """Every top-level resource carries the four system-managed properties."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID string, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be a positive integer"


def assert_seller(data: dict):
    assert_common_fields(data)
    for field in ("legal_name", "country_code", "onboarding_state", "performance_tier"):
        assert isinstance(data.get(field), str) and data[field], f"{field} must be a non-empty string"
    assert data["country_code"] == data["country_code"].upper() and len(data["country_code"]) == 2
    assert isinstance(data["refurbishment_capacity_units"], int) and data["refurbishment_capacity_units"] >= 1
    assert data["onboarding_state"] in [s.value for s in
                                        ("APPLICANT", "DOCUMENT_VERIFIED", "AUDIT_SCHEDULED", "APPROVED", "REJECTED", "SUSPENDED")]
    assert data["performance_tier"] in ["ELITE", "STANDARD", "PROBATION", "SUSPENDED"]
    assert isinstance(data["exposure_floor_cents"], int) and data["exposure_floor_cents"] >= 0
    assert isinstance(data["suspension_trigger_count"], int) and data["suspension_trigger_count"] >= 0
    assert isinstance(data["blocklisted"], bool)
    assert data.get("latest_score_id") is None or isinstance(data["latest_score_id"], str)


def assert_seller_audit_record(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("seller_id", "")), "seller_id must be a UUID"
    assert data["audit_state"] in ["IN_PROGRESS", "PASSED", "FAILED"]
    assert is_iso8601_timestamp(data.get("audit_scheduled_for", ""))
    assert isinstance(data["audit_scope_note"], str) and 1 <= len(data["audit_scope_note"]) <= 500
    assert isinstance(data["declared_monthly_throughput"], int) and data["declared_monthly_throughput"] >= 1
    if data.get("audit_score") is not None:
        assert 0 <= data["audit_score"] <= 100


def assert_device_listing(data: dict):
    assert_common_fields(data)
    for field in ("seller_id", "serving_seller_id", "servicing_seller_id", "model_code", "imei"):
        assert is_valid_uuid(data[field]) if field.endswith("seller_id") else isinstance(data.get(field), str), field
    assert len(data["imei"]) == 15 and data["imei"].isdigit(), "imei must be exactly 15 digits"
    assert data["cosmetic_grade"] in ["FLAWLESS", "GOOD", "FAIR", "POOR"]
    assert data["functional_grade"] in ["FULLY_FUNCTIONAL", "MINOR_FAULTS", "MAJOR_FAULTS"]
    assert 1 <= data["battery_health_pct"] <= 100
    assert data["carrier_lock_status"] in ["UNLOCKED", "LOCKED", "UNKNOWN"]
    assert data["part_provenance"] in ["OEM_ONLY", "OEM_EQUIVALENT", "AFTERMARKET"]
    assert data["listing_state"] in ["DRAFT", "UNDER_REVIEW", "LISTED", "DELISTED", "SUSPENDED", "WITHDRAWN"]
    assert data["serving_seller_id"] == data["seller_id"]
    assert isinstance(data["mystery_shop_disclosed"], bool)
    assert isinstance(data["list_price_cents"], int) and data["list_price_cents"] >= 0
    assert isinstance(data["active_reservation_days"], int) and data["active_reservation_days"] >= 0


def assert_mystery_shop_verification(data: dict):
    assert_common_fields(data)
    assert data["verification_state"] in ["OPEN", "DISCLOSED", "VOIDED"]
    assert data["rationale_code"] in ["GRADE_GHOST", "PART_PROVENANCE", "BATTERY_MISMATCH"]
    assert data["ordered_cosmetic_grade"] in ["FLAWLESS", "GOOD", "FAIR", "POOR"]
    assert is_iso8601_timestamp(data.get("verification_start", ""))
    assert is_iso8601_timestamp(data.get("verification_end", ""))
    assert isinstance(data["value_at_risk"], int) and data["value_at_risk"] >= 0


def assert_warranty_reservation(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("listing_id", ""))
    assert data["warranty_state"] in ["ACTIVE", "REPAIRING", "REPLACED", "SUSPENDED", "COMPLETED"]
    assert is_iso8601_timestamp(data.get("activated_on", ""))
    assert is_iso8601_timestamp(data.get("expired_on", ""))
    assert isinstance(data["warranty_period_days"], int) and data["warranty_period_days"] >= 1
    assert isinstance(data["reserved_units"], int) and data["reserved_units"] >= 0
    assert isinstance(data["claims_filed_count"], int) and data["claims_filed_count"] >= 0


def assert_warranty_claim(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("listing_id", ""))
    assert data["claim_state"] in ["FILED", "UNDER_REVIEW", "APPROVED", "REJECTED", "RESOLVED"]
    assert data["claim_reason_code"] in [
        "BATTERY_SWELL", "TOUCH_FAILURE", "CAMERA_FAILURE", "UNLOCKED_PROMISE_BREACH",
    ]
    if data.get("resolution_type") is not None:
        assert data["resolution_type"] in ["REPAIR", "REPLACE"]
    assert isinstance(data["seller_funded_amount_cents"], int) and data["seller_funded_amount_cents"] >= 0
    assert isinstance(data["claim_reserve_cents"], int) and data["claim_reserve_cents"] >= 0
    assert isinstance(data["on_time_flag"], bool)


def assert_service_score(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("seller_id", ""))
    assert data["section_state"] in ["OPEN", "CLOSED"]
    for field in ("claim_failure_rate_pct", "on_time_resolution_pct",
                  "grading_compliance_pct", "return_rate_pct", "service_score"):
        assert isinstance(data.get(field), (int, float)), f"{field} must be numeric"
    assert 0.0 <= data["service_score"] <= 100.0
    assert isinstance(data["threshold_breached"], bool)


def assert_trade_in(data: dict):
    assert_common_fields(data)
    assert data["submission_state"] in ["SUBMITTED", "INSPECTED", "PRICE_REVISED", "ACCEPTED", "REJECTED"]
    assert data["self_declared_cosmetic_grade"] in ["FLAWLESS", "GOOD", "FAIR", "POOR"]
    assert data["self_declared_functional_grade"] in ["FULLY_FUNCTIONAL", "MINOR_FAULTS", "MAJOR_FAULTS"]
    assert 1 <= data["self_declared_battery_health_pct"] <= 100
    assert isinstance(data["provisional_quote_cents"], int)
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0
    assert isinstance(data["inspection_fee_cents"], int) and data["inspection_fee_cents"] >= 0


def assert_grading_definition(data: dict):
    assert_common_fields(data)
    assert data["definition_state"] in ["DRAFT", "ACTIVE", "RETIRED"]
    assert set(data["cosmetic_thresholds"].keys()) == {"FLAWLESS", "GOOD", "FAIR", "POOR"}
    assert set(data["functional_thresholds"].keys()) == {"FULLY_FUNCTIONAL", "MINOR_FAULTS", "MAJOR_FAULTS"}
    assert 1 <= data["battery_floor_pct"] <= 100
    assert is_iso8601_timestamp(data.get("effective_from", ""))
    if data["definition_state"] in ("DRAFT", "ACTIVE"):
        assert data.get("retired_on") is None


def assert_exposure_floor_read(data: dict):
    """Invariants of the exposure-floor trace read."""
    assert is_valid_uuid(data.get("seller_id", ""))
    for field in ("published_exposure_floor_cents", "traced_exposure_cents", "reserved_claim_cents"):
        assert isinstance(data.get(field), int), f"{field} must be an integer number of cents"
        assert data[field] >= 0, f"{field} must not be negative"
    assert isinstance(data.get("cell_count"), int) and data["cell_count"] >= 0


def assert_buy_box_read(data: dict):
    assert is_valid_uuid(data.get("winner_listing_id", ""))
    assert isinstance(data.get("buy_box_price_cents"), int)
    assert isinstance(data.get("winner_rank_score"), (int, float))
    assert isinstance(data.get("ranked_listing_ids"), list)