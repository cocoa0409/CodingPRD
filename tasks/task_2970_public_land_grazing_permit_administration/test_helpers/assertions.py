"""Entity shape assertions and the PRD's ledger / money invariant checkers."""
import pytest
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .types import (
    AccountStatus,
    AllotmentStatus,
    AoiStatus,
    AppealStatus,
    AssessmentStatus,
    BillStatus,
    BillType,
    DecisionStatus,
    DecisionType,
    HealthDetermination,
    IncidentStatus,
    OrderStatus,
    OrderType,
    PermitStatus,
    PermitteeStatus,
    ProjectStatus,
    RecordStatus,
)

AUM_TOLERANCE = 0.005
PCT_TOLERANCE = 0.00005


def assert_aums(actual, expected):
    """Fractional AUM equality at the PRD's 2-decimal-place width."""
    assert actual == pytest.approx(float(expected), abs=AUM_TOLERANCE), (
        "expected %s AUMs, got %r" % (expected, actual)
    )


def assert_pct(actual, expected):
    """Adjustment fraction equality at the PRD's 4-decimal-place width."""
    assert actual == pytest.approx(float(expected), abs=PCT_TOLERANCE), (
        "expected %s, got %r" % (expected, actual)
    )


def assert_common_fields(data: dict):
    """PRD 2.4: every persisted resource carries id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a server-minted UUID, got %r" % data.get("id")
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be an ISO 8601 UTC instant, got %r" % data.get("created_at"))
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        "updated_at must be an ISO 8601 UTC instant, got %r" % data.get("updated_at"))
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "version must be an integer starting at 1, got %r" % data.get("version"))


def validate_unpaginated_list(response) -> list:
    """Validate a 200 list response whose meta carries no pagination fields."""
    assert response.status_code == 200, (
        "expected 200 for a list response, got %s: %s" % (response.status_code, response.text))
    body = response.json()
    assert body.get("response_type") == "array", (
        "expected response_type 'array', got %r" % body.get("response_type"))
    assert isinstance(body.get("data"), list), "data must hold the array of resources directly"
    return body["data"]


def assert_allotment(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 120
    assert isinstance(data["admin_unit_code"], str)
    assert isinstance(data["acres"], int) and data["acres"] >= 1
    assert isinstance(data["total_permitted_aums"], int) and data["total_permitted_aums"] >= 1
    assert isinstance(data["season_start"], str) and len(data["season_start"]) == 5
    assert isinstance(data["season_end"], str) and len(data["season_end"]) == 5
    assert data["allotment_status"] in (
        AllotmentStatus.OPEN, AllotmentStatus.RESTRICTED, AllotmentStatus.CLOSED)
    assert data["health_determination"] in (
        HealthDetermination.NOT_ASSESSED, HealthDetermination.MEETING,
        HealthDetermination.MEETING_WITH_PROBLEMS, HealthDetermination.NOT_MEETING)
    for field in ("effective_capacity_aums", "allocated_aums", "open_aums",
                  "required_pasture_rotation_count", "current_grazing_year"):
        assert isinstance(data[field], int), "%s must be an integer, got %r" % (field, data[field])
    assert_ledger_conserved(data)


def assert_ledger_conserved(allotment: dict):
    """PRD 2.9 AUM invariant: open_aums + allocated_aums == effective_capacity_aums."""
    assert allotment["open_aums"] + allotment["allocated_aums"] == allotment["effective_capacity_aums"], (
        "AUM invariant violated: open %s + allocated %s != effective %s" % (
            allotment["open_aums"], allotment["allocated_aums"], allotment["effective_capacity_aums"]))


def assert_pasture(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("allotment_id", ""))
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 80
    assert isinstance(data["pasture_aum_capacity"], int) and data["pasture_aum_capacity"] >= 1
    assert isinstance(data["sequence_order"], int) and data["sequence_order"] >= 1
    assert isinstance(data["rest_required"], bool)
    assert isinstance(data["scheduled_aums"], (int, float))


def assert_permittee(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 120
    assert "@" in data["contact_email"]
    assert data["permittee_status"] in (
        PermitteeStatus.IN_GOOD_STANDING, PermitteeStatus.DEBT_FLAGGED)
    assert isinstance(data["outstanding_balance_cents"], int)
    assert isinstance(data["billed_trespass_incident_count"], int)


def assert_base_property(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("permittee_id", ""))
    assert data["base_property_type"] in ("LAND", "LIVESTOCK")
    assert isinstance(data["legal_description"], str) and 1 <= len(data["legal_description"]) <= 200
    assert isinstance(data["carrying_capacity_aums"], int) and data["carrying_capacity_aums"] >= 0
    assert isinstance(data["qualified_aums"], int)
    assert isinstance(data["controlled_since_date"], str)


def assert_permit(data: dict):
    assert_common_fields(data)
    for field in ("allotment_id", "permittee_id", "base_property_id"):
        assert is_valid_uuid(data.get(field, "")), "%s must be a UUID" % field
    assert data["permit_status"] in (
        PermitStatus.PENDING_REVIEW, PermitStatus.ISSUED, PermitStatus.SUSPENDED,
        PermitStatus.CANCELLED, PermitStatus.EXPIRED, PermitStatus.TRANSFERRED)
    assert data["account_status"] in (AccountStatus.CURRENT, AccountStatus.DELINQUENT)
    assert isinstance(data["permitted_aums"], int) and data["permitted_aums"] >= 1
    assert data["livestock_kind"] in ("CATTLE", "SHEEP", "HORSES")
    assert data["preference_priority"] in (1, 2)
    assert isinstance(data["consecutive_nonuse_years"], int)
    if data["permit_status"] != PermitStatus.SUSPENDED:
        assert data.get("suspension_reason") is None, (
            "suspension_reason is null whenever permit_status is not SUSPENDED")
    else:
        assert data.get("suspension_reason") in ("NONPAYMENT", "DECISION", None)


def assert_aoi(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("permit_id", ""))
    assert data["aoi_status"] in (
        AoiStatus.DRAFT, AoiStatus.ISSUED, AoiStatus.USE_REPORTED,
        AoiStatus.BILLED, AoiStatus.CLOSED, AoiStatus.VOIDED)
    for field in ("grazing_year", "authorized_aums", "authorized_aums_at_issue",
                  "nonuse_aums", "billable_aums", "distinct_pasture_count"):
        assert isinstance(data[field], int), "%s must be an integer, got %r" % (field, data[field])
    assert isinstance(data["planned_aums_total"], (int, float))
    assert isinstance(data["actual_aums_total"], (int, float))
    assert data["billable_aums"] == data["authorized_aums"] - data["nonuse_aums"], (
        "billable_aums is always authorized_aums less nonuse_aums")
    if data["nonuse_aums"] == 0:
        assert data.get("nonuse_reason") is None, "nonuse_reason is null whenever nonuse_aums is 0"


def assert_use_record(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("aoi_id", ""))
    assert is_valid_uuid(data.get("pasture_id", ""))
    assert data["record_status"] in (
        RecordStatus.SCHEDULED, RecordStatus.ACTUAL_REPORTED, RecordStatus.ACCEPTED)
    assert isinstance(data["planned_head_count"], int) and data["planned_head_count"] >= 1
    assert isinstance(data["planned_aums"], (int, float))
    if data["record_status"] == RecordStatus.SCHEDULED:
        assert data.get("actual_aums") is None, "actual_aums is null until the leg is reported"


def assert_bill(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("permittee_id", ""))
    assert data["bill_type"] in (
        BillType.PRELIMINARY_USE, BillType.FINAL_USE, BillType.REVISED_USE,
        BillType.UNAUTHORIZED_USE, BillType.PROJECT_COST_SHARE,
        BillType.ADJUSTMENT_DEBIT, BillType.ADJUSTMENT_CREDIT)
    assert data["bill_status"] in (
        BillStatus.ISSUED, BillStatus.PAID, BillStatus.DELINQUENT, BillStatus.VOIDED)
    for field in ("base_amount_cents", "admin_fee_cents", "penalty_amount_cents",
                  "total_amount_cents", "amount_paid_cents", "fee_rate_cents_per_aum"):
        assert isinstance(data[field], int), "%s must be integer cents, got %r" % (field, data[field])
    assert isinstance(data["billed_aums"], (int, float))
    assert isinstance(data["due_date"], str)


def assert_use_bill_amounts(bill: dict, billed_aums, base_amount_cents, admin_fee_cents,
                            total_amount_cents):
    """PRD 3.6 five-step use-bill arithmetic, checked field by field."""
    assert_aums(bill["billed_aums"], billed_aums)
    assert bill["base_amount_cents"] == base_amount_cents, (
        "base_amount_cents expected %s, got %s" % (base_amount_cents, bill["base_amount_cents"]))
    assert bill["admin_fee_cents"] == admin_fee_cents, (
        "admin_fee_cents expected %s, got %s" % (admin_fee_cents, bill["admin_fee_cents"]))
    assert bill["penalty_amount_cents"] == 0, "penalty_amount_cents is 0 on every use bill"
    assert bill["total_amount_cents"] == total_amount_cents, (
        "total_amount_cents expected %s, got %s" % (total_amount_cents, bill["total_amount_cents"]))
    assert bill["fee_rate_cents_per_aum"] == 172, "the grazing fee rate is 172 cents per AUM"


def assert_assessment(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("allotment_id", ""))
    assert data["assessment_status"] in (
        AssessmentStatus.DRAFT, AssessmentStatus.FIELD_REVIEW, AssessmentStatus.FINALIZED)
    assert data["monitoring_method"] in ("INDICATOR_ASSESSMENT", "UTILIZATION_MAPPING")
    for field in ("upland_score", "riparian_score", "water_quality_score", "remand_count"):
        assert isinstance(data[field], int)
    assert isinstance(data["author_user_id"], str) and data["author_user_id"]


def assert_decision(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("allotment_id", ""))
    assert data["decision_type"] in (
        DecisionType.ISSUANCE, DecisionType.STOCKING_ADJUSTMENT,
        DecisionType.SUSPENSION, DecisionType.CANCELLATION)
    assert data["decision_status"] in (
        DecisionStatus.DRAFT, DecisionStatus.PROPOSED, DecisionStatus.FINAL,
        DecisionStatus.EFFECTIVE, DecisionStatus.STAYED, DecisionStatus.VACATED)
    assert data["nepa_status"] in ("PENDING", "COMPLETE")
    assert data["nepa_level"] in ("CX", "EA", "EIS")
    assert isinstance(data["authoring_officer_id"], str) and data["authoring_officer_id"]


def assert_appeal(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("decision_id", ""))
    assert is_valid_uuid(data.get("appellant_permittee_id", ""))
    assert data["appeal_status"] in (
        AppealStatus.FILED, AppealStatus.UNDER_REVIEW, AppealStatus.REMANDED,
        AppealStatus.AFFIRMED, AppealStatus.REVERSED, AppealStatus.DISMISSED)
    assert isinstance(data["stay_granted"], bool)
    assert isinstance(data["remand_count"], int)


def assert_closure_order(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("allotment_id", ""))
    assert data["order_type"] in (
        OrderType.DROUGHT_REDUCTION, OrderType.WILDFIRE_CLOSURE, OrderType.FULL_CLOSURE)
    assert data["order_status"] in (OrderStatus.ACTIVE, OrderStatus.LIFTED, OrderStatus.EXPIRED)
    assert isinstance(data["reduction_pct"], (int, float))
    assert isinstance(data["issuing_officer_id"], str) and data["issuing_officer_id"]


def assert_trespass_incident(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("allotment_id", ""))
    assert data["incident_status"] in (
        IncidentStatus.DETECTED, IncidentStatus.BILLED, IncidentStatus.RESOLVED)
    assert data["willfulness"] in ("NON_WILLFUL", "WILLFUL", "REPEATED_WILLFUL")
    assert isinstance(data["head_count"], int) and data["head_count"] >= 1
    assert isinstance(data["unauthorized_days"], int) and data["unauthorized_days"] >= 1
    assert isinstance(data["unauthorized_aums"], (int, float))
    assert isinstance(data["billed_aums"], int)
    assert isinstance(data["prior_billed_incident_count"], int)


def assert_project(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("allotment_id", ""))
    assert data["project_type"] in ("FENCE", "WATER_DEVELOPMENT", "SEEDING")
    assert data["project_status"] in (
        ProjectStatus.PROPOSED, ProjectStatus.APPROVED,
        ProjectStatus.COST_ALLOCATED, ProjectStatus.TERMINATED)
    assert data["maintenance_responsibility"] in ("AGENCY", "PERMITTEE", "SHARED")
    for field in ("total_cost_cents", "permittee_share_cents", "allocated_share_cents"):
        assert isinstance(data[field], int)
