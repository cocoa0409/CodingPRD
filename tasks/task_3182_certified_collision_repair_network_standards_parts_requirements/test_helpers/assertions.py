"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)

SHOP_STATUSES = ["APPLICANT", "CERTIFIED", "PROBATION", "SUSPENDED", "EXPIRED", "DECERTIFIED"]
REQUIREMENT_STATUSES = ["DRAFT", "PUBLISHED", "SUPERSEDED", "RETIRED"]
CYCLE_STATUSES = ["OPEN", "AUDIT_SCHEDULED", "UNDER_AUDIT", "CORRECTIVE_ACTION", "CLOSED_PASS", "CLOSED_FAIL"]
ATTESTATION_STATUSES = ["ACTIVE", "LAPSED", "UNDER_CORRECTION", "SUPERSEDED"]
AUDIT_STATUSES = ["SCHEDULED", "IN_PROGRESS", "FINDINGS_ISSUED", "VERIFICATION", "PASSED", "FAILED", "CANCELLED"]
CORRECTIVE_ACTION_STATUSES = ["OPEN", "SUBMITTED", "VERIFIED", "REJECTED"]
TECHNICIAN_STATUSES = ["PROVISIONAL", "CURRENT", "LAPSED", "INACTIVE"]
ORDER_STATUSES = ["ESTIMATE", "APPROVED", "IN_REPAIR", "QC", "REWORK", "CALIBRATION", "COMPLETE", "WARRANTY_ACTIVE", "CLOSED", "VOIDED"]
STEP_STATUSES = ["RECORDED", "VOIDED"]
LINE_STATUSES = ["ACTIVE", "REMOVED"]
CLAIM_STATUSES = ["FILED", "UNDER_REVIEW", "ESCALATED", "RESOLVED_ACCEPTED", "RESOLVED_DENIED", "CLOSED"]
RELATION_STATUSES = ["ACTIVE", "SUSPENDED", "TERMINATED"]
REFERRAL_STATUSES = ["UNROUTED", "ROUTED", "ACCEPTED", "DECLINED", "EXPIRED"]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_shop(data: dict):
    _assert_common(data)
    assert isinstance(data.get("legal_name"), str) and data["legal_name"]
    assert isinstance(data.get("state_code"), str) and len(data["state_code"]) == 2
    assert data.get("certification_status") in SHOP_STATUSES
    assert isinstance(data.get("locator_hidden"), bool)
    assert isinstance(data.get("structural_capability"), bool)
    assert isinstance(data.get("lifetime_repair_count"), int)
    assert isinstance(data.get("pending_referral_count"), int)
    assert isinstance(data.get("warranty_reserve_cents"), int)
    assert data.get("live_compliance_score") is not None


def assert_requirement(data: dict):
    _assert_common(data)
    assert isinstance(data.get("requirement_code"), str) and data["requirement_code"]
    assert data.get("category") in ["EQUIPMENT", "TRAINING", "TOOLING", "STRUCTURAL"]
    assert isinstance(data.get("requirement_version"), int) and data["requirement_version"] >= 1
    assert data.get("status") in REQUIREMENT_STATUSES


def assert_cycle(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("shop_id", ""))
    assert isinstance(data.get("cycle_index"), int) and data["cycle_index"] >= 1
    assert data.get("status") in CYCLE_STATUSES


def assert_attestation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("shop_id", ""))
    assert is_valid_uuid(data.get("requirement_id", ""))
    assert data.get("status") in ATTESTATION_STATUSES


def assert_audit(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("cycle_id", ""))
    assert data.get("status") in AUDIT_STATUSES
    assert isinstance(data.get("round_number"), int) and data["round_number"] >= 1
    assert isinstance(data.get("severity_points"), int)


def assert_corrective_action(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("audit_id", ""))
    assert is_valid_uuid(data.get("attestation_id", ""))
    assert data.get("finding_severity") in ["MINOR", "MAJOR", "CRITICAL"]
    assert data.get("status") in CORRECTIVE_ACTION_STATUSES
    assert is_iso8601_timestamp(data.get("due_at", ""))


def assert_technician(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("shop_id", ""))
    assert data.get("tech_role") in ["STRUCTURAL", "NON_STRUCTURAL", "ESTIMATOR", "REFINISH", "ADAS_SPECIALIST"]
    assert data.get("status") in TECHNICIAN_STATUSES
    assert data.get("curriculum_progress_pct") is not None


def assert_course(data: dict):
    _assert_common(data)
    assert isinstance(data.get("course_code"), str) and data["course_code"]
    assert isinstance(data.get("validity_months"), int) and data["validity_months"] >= 1
    assert isinstance(data.get("active"), bool)


def assert_completion(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("technician_id", ""))
    assert is_valid_uuid(data.get("course_id", ""))
    assert data.get("status") in ["CURRENT", "EXPIRED"]


def assert_repair_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("shop_id", ""))
    assert isinstance(data.get("vin"), str) and len(data["vin"]) == 17
    assert data.get("status") in ORDER_STATUSES
    assert isinstance(data.get("rework_count"), int)
    assert data.get("oe_parts_ratio_by_cost") is not None
    assert data.get("oe_parts_ratio_by_count") is not None


def assert_procedure_step(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("repair_order_id", ""))
    assert data.get("step_type") in [
        "PRE_SCAN", "STRUCTURAL_MEASURE", "WELD_BOND", "POST_SCAN",
        "ADAS_CALIBRATION_STATIC", "ADAS_CALIBRATION_DYNAMIC",
    ]
    assert data.get("result") in ["PASS", "FAIL", "NOT_APPLICABLE"]
    assert data.get("status") in STEP_STATUSES


def assert_part_line(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("repair_order_id", ""))
    assert data.get("part_class") in ["OE", "OE_SURPLUS", "AFTERMARKET", "RECYCLED", "REMANUFACTURED"]
    assert isinstance(data.get("unit_cost_cents"), int) and data["unit_cost_cents"] >= 0
    assert isinstance(data.get("quantity"), int) and data["quantity"] >= 1
    assert data.get("line_status") in LINE_STATUSES


def assert_warranty_claim(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("repair_order_id", ""))
    assert data.get("defect_category") in ["WORKMANSHIP", "PART_DEFECT", "CORROSION", "PAINT_ADHESION", "CALIBRATION_DRIFT"]
    assert data.get("status") in CLAIM_STATUSES


def assert_insurer_relation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("shop_id", ""))
    assert isinstance(data.get("insurer_code"), str) and data["insurer_code"]
    assert isinstance(data.get("steering_enabled"), bool)
    assert data.get("status") in RELATION_STATUSES


def assert_referral(data: dict):
    _assert_common(data)
    assert data.get("source_type") in ["DEALER", "INSURER", "CONSUMER_DIRECT"]
    assert data.get("status") in REFERRAL_STATUSES


def assert_shop_invariants(data: dict):
    """Domain invariants that must hold for a shop after any operation."""
    assert data["warranty_reserve_cents"] >= 0, "reserve never negative"
    assert data["pending_referral_count"] >= 0, "pending referral count never negative"
    assert data["lifetime_repair_count"] >= 0
    assert 0.0 <= data["live_compliance_score"] <= 100.0
