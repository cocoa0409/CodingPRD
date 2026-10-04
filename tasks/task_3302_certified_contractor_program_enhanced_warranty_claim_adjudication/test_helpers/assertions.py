"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_contractor(data: dict):
    assert is_valid_uuid(data.get("id", "")), "contractor id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert isinstance(data.get("legal_name"), str)
    assert data.get("status") in ("ACTIVE", "SUSPENDED", "REVOKED")
    assert isinstance(data.get("workmanship_score"), int)
    assert 0 <= data["workmanship_score"] <= 100, "workmanship_score is bounded to [0, 100]"
    assert isinstance(data.get("complaint_score_24mo"), int)
    assert isinstance(data.get("lifetime_substantiated_count"), int)
    assert isinstance(data.get("outstanding_liability_cents"), int)


def assert_training_course(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert isinstance(data.get("title"), str)
    assert isinstance(data.get("credits"), int)
    assert isinstance(data.get("validity_months"), int)
    assert data.get("version") >= 1


def assert_training_enrollment(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("contractor_id", ""))
    assert is_valid_uuid(data.get("course_id", ""))
    assert data.get("status") in ("ENROLLED", "COMPLETED")
    assert data.get("version") >= 1


def assert_certification(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("contractor_id", ""))
    assert data.get("tier") in ("BRONZE", "SILVER", "GOLD")
    assert data.get("status") in (
        "PENDING_VERIFICATION",
        "ACTIVE",
        "SUSPENDED",
        "EXPIRED",
        "DENIED",
        "REVOKED",
    )
    assert data.get("version") >= 1


def assert_catalog_item(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert isinstance(data.get("sku"), str)
    assert data.get("component_type") in (
        "SHINGLE",
        "UNDERLAYMENT",
        "STARTER",
        "RIDGE_CAP",
        "VENTILATION",
        "OTHER",
    )
    assert data.get("manufacturer") in ("GAF", "OTHER")


def assert_registration(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("certification_id", ""))
    assert data.get("status") in ("DRAFT", "ACTIVE", "VOID")
    assert data.get("coverage_class") in ("DRAFT", "QUALIFYING_SYSTEM", "MIXED_MANUFACTURER")
    assert data.get("version") >= 1


def assert_registration_component(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("registration_id", ""))
    assert isinstance(data.get("catalog_sku"), str)
    assert data.get("component_type") in (
        "SHINGLE",
        "UNDERLAYMENT",
        "STARTER",
        "RIDGE_CAP",
        "VENTILATION",
        "OTHER",
    )
    assert data.get("manufacturer") in ("GAF", "OTHER")
    assert isinstance(data.get("material_cost_cents"), int)
    assert data["material_cost_cents"] >= 0


def assert_claim(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("registration_id", ""))
    assert data.get("status") in (
        "SUBMITTED",
        "EVIDENCE_REVIEW",
        "INSPECTION_REQUESTED",
        "INSPECTION_COMPLETED",
        "RESOLVED",
        "DENIED",
    )
    assert isinstance(data.get("photo_count"), int)
    assert data["photo_count"] >= 0
    assert isinstance(data.get("claim_labor_cost_cents"), int)
    assert isinstance(data.get("filing_workmanship_score"), int)
    assert data.get("version") >= 1


def assert_inspection_order(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("claim_id", ""))
    assert data.get("status") in ("REQUESTED", "SCHEDULED", "COMPLETED")
    assert data.get("version") >= 1


def assert_remedy_allocation(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("claim_id", ""))
    assert data.get("determination") in (
        "MANUFACTURER_DEFECT",
        "INSTALLATION_ERROR",
        "MIXED",
        "NO_DEFECT",
    )
    assert data.get("schedule_used") in ("STANDARD", "ENHANCED", "ENHANCED_PLUS")
    assert isinstance(data.get("completed_years"), int)
    assert isinstance(data.get("material_pct"), int)
    assert isinstance(data.get("prorated_material_pool_cents"), int)
    assert isinstance(data.get("material_covered_cents"), int)
    assert isinstance(data.get("homeowner_material_share_cents"), int)
    assert isinstance(data.get("labor_covered_cents"), int)
    assert isinstance(data.get("contractor_liability_cents"), int)
    assert isinstance(data.get("workmanship_delta_applied"), int)
    assert data.get("status") in ("ACTIVE", "REVERSED")


def assert_complaint(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("contractor_id", ""))
    assert data.get("category") in (
        "WORKMANSHIP",
        "COMMUNICATION",
        "PROPERTY_DAMAGE",
        "CONTRACT_DISPUTE",
    )
    assert data.get("status") in ("FILED", "SUBSTANTIATED", "DISMISSED")
    assert data.get("version") >= 1


def assert_distributor(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert isinstance(data.get("name"), str)
    assert isinstance(data.get("lead_pool_total"), int)
    assert isinstance(data.get("lead_pool_available"), int)
    assert 0 <= data["lead_pool_available"] <= data["lead_pool_total"]


def assert_lead_assignment(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("distributor_id", ""))
    assert is_valid_uuid(data.get("contractor_id", ""))
    assert isinstance(data.get("territory_code"), str)
    assert data.get("required_tier") in ("BRONZE", "SILVER", "GOLD")
    assert data.get("status") in ("ASSIGNED", "RETURNED")
