"""Entity assertions and domain invariant checkers.

Explicit-status validators: the PRD (§4) returns 201 for resource-creating
POSTs and 200 for reads and every state-driving PATCH / action call, with the
scope-amendment call returning 201 because it can add scope-item records. All
validators here take the expected status explicitly; the create helper
defaults to 201.
"""

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_success,
)

from .types import (
    ApplicationStatus,
    AssessmentStatus,
    CommitmentStatus,
    ContractorStatus,
    EnrollmentStatus,
    EventStatus,
    FundingCycleStatus,
    InspectionOutcome,
    MaterialOrderStatus,
    PriorityMode,
    ProjectCancellationReason,
    ProjectStatus,
    ReadinessPosture,
    ScopeCategory,
    ScopeItemStatus,
    SelectionRunStatus,
    SponsorTier,
    Trade,
    VolunteerStatus,
    WarrantyClaimStatus,
    WorkOrderStatus,
)


# --- Explicit-status success validators --------------------------------------

def validate_created(response) -> dict:
    """Assert a 201 Created response envelope; returns the data payload."""
    return validate_success(response, expected_status=201)


def validate_ok(response) -> dict:
    """Assert a 200 OK response envelope; returns the data payload."""
    return validate_success(response, expected_status=200)


# --- Shared field helpers ------------------------------------------------------

def _assert_common_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be a positive integer"
    )


def _assert_append_only_fields(data: dict, entity: str):
    """ScopeItem is the single entity carrying only id + created_at."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601"
    )


def _enum_values(enum_cls):
    return [member.value for member in enum_cls]


# --- Per-entity assertions -----------------------------------------------------

def assert_funding_cycle(data: dict):
    _assert_common_fields(data, "FundingCycle")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["fiscal_year"], int)
    assert isinstance(data["total_budget_cents"], int) and data["total_budget_cents"] >= 0
    assert data["priority_mode"] in _enum_values(PriorityMode)
    assert data["status"] in _enum_values(FundingCycleStatus)
    for field in ("pool_cents", "reserved_cents", "spent_cents", "available_cents"):
        assert isinstance(data[field], int), f"FundingCycle.{field} must be int cents"
    assert_funding_cycle_ledger(data)


def assert_funding_cycle_ledger(data: dict):
    """Ledger invariant (PRD §2.6): available == pool - reserved - spent."""
    assert (
        data["available_cents"]
        == data["pool_cents"] - data["reserved_cents"] - data["spent_cents"]
    ), (
        "funding-pool ledger invariant violated: "
        f"available {data['available_cents']} != pool {data['pool_cents']} "
        f"- reserved {data['reserved_cents']} - spent {data['spent_cents']}"
    )


def assert_selection_run(data: dict):
    _assert_common_fields(data, "SelectionRun")
    assert is_valid_uuid(data.get("funding_cycle_id", ""))
    assert data["status"] in _enum_values(SelectionRunStatus)
    assert data["priority_mode_snapshot"] in _enum_values(PriorityMode)
    assert isinstance(data["ranked_application_ids"], list)
    assert isinstance(data["selected_application_ids"], list)
    assert data["applied_at"] is None or isinstance(data["applied_at"], str)


def assert_apply_result(data: dict):
    """Selection-run apply returns a summary object, not an entity."""
    assert isinstance(data["applied_count"], int) and data["applied_count"] >= 0
    assert isinstance(data["project_ids"], list)
    assert isinstance(data["deferred_application_ids"], list)


def assert_sponsor(data: dict):
    _assert_common_fields(data, "Sponsor")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert data["sponsor_tier"] in _enum_values(SponsorTier)


def assert_commitment(data: dict):
    _assert_common_fields(data, "SponsorshipCommitment")
    assert is_valid_uuid(data.get("sponsor_id", ""))
    assert is_valid_uuid(data.get("funding_cycle_id", ""))
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["team_build_event_date"] is None or isinstance(
        data["team_build_event_date"], str
    )
    assert data["status"] in _enum_values(CommitmentStatus)
    assert data["received_at"] is None or isinstance(data["received_at"], str)
    assert isinstance(data["allocated_amount_cents"], int)
    assert data["withdrawn_at"] is None or isinstance(data["withdrawn_at"], str)


def assert_application(data: dict):
    _assert_common_fields(data, "HomeownerApplication")
    assert is_valid_uuid(data.get("funding_cycle_id", ""))
    assert isinstance(data["homeowner_name"], str) and data["homeowner_name"]
    assert isinstance(data["date_of_birth"], str)
    assert isinstance(data["household_size"], int) and 1 <= data["household_size"] <= 8
    assert isinstance(data["household_income_cents"], int)
    assert data["household_income_cents"] >= 0
    assert isinstance(data["is_veteran"], bool)
    assert isinstance(data["has_disability"], bool)
    assert isinstance(data["ownership_doc_provided"], bool)
    assert isinstance(data["occupancy_doc_provided"], bool)
    assert isinstance(data["address"], str)
    assert data["status"] in _enum_values(ApplicationStatus)
    assert isinstance(data["is_older_adult"], bool)
    assert isinstance(data["priority_score"], int)
    assert data["decision_reason"] is None or isinstance(data["decision_reason"], str)


def assert_assessment(data: dict):
    _assert_common_fields(data, "HomeAssessment")
    assert is_valid_uuid(data.get("application_id", ""))
    assert isinstance(data["scheduled_on"], str)
    assert data["status"] in _enum_values(AssessmentStatus)
    assert data["completed_on"] is None or isinstance(data["completed_on"], str)


def assert_completed_assessment(data: dict):
    """A COMPLETED/SCOPED assessment additionally carries the recorded findings."""
    assert_assessment(data)
    severity = data["safety_hazard_max_severity"]
    assert isinstance(severity, int) and 0 <= severity <= 5
    assert isinstance(data["accessibility_needs_count"], int)
    assert data["accessibility_needs_count"] >= 0
    assert data["critical_systems_notes"] is None or isinstance(
        data["critical_systems_notes"], str
    )
    assert data["completed_on"] is not None


def assert_scope_item(data: dict):
    """ScopeItem is append-only: id + created_at, and never updated_at/version."""
    _assert_append_only_fields(data, "ScopeItem")
    assert "updated_at" not in data, "ScopeItem must not carry updated_at"
    assert "version" not in data, "ScopeItem must not carry version"
    assert is_valid_uuid(data.get("assessment_id", ""))
    assert data["category"] in _enum_values(ScopeCategory)
    assert data["required_trade"] in _enum_values(Trade)
    assert isinstance(data["volunteer_performable"], bool)
    assert isinstance(data["requires_permit"], bool)
    assert isinstance(data["est_low_cents"], int) and data["est_low_cents"] > 0
    assert isinstance(data["est_high_cents"], int)
    assert data["est_high_cents"] >= data["est_low_cents"]
    assert isinstance(data["description"], str)
    assert data["status"] in _enum_values(ScopeItemStatus)
    assert isinstance(data["midpoint_cents"], int) and data["midpoint_cents"] > 0
    # coherence rule (PRD §3.3): required_trade == NONE iff volunteer_performable
    assert (data["required_trade"] == Trade.NONE.value) == data["volunteer_performable"]


def assert_project(data: dict):
    _assert_common_fields(data, "Project")
    assert is_valid_uuid(data.get("application_id", ""))
    assert is_valid_uuid(data.get("funding_cycle_id", ""))
    assert data["status"] in _enum_values(ProjectStatus)
    assert data["cancellation_reason"] is None or data["cancellation_reason"] in _enum_values(
        ProjectCancellationReason
    )
    assert data["readiness_posture"] in _enum_values(ReadinessPosture)
    for field in (
        "provisional_estimate_cents",
        "envelope_cents",
        "reserved_balance_cents",
        "reconciled_cost_cents",
        "priority_score_snapshot",
    ):
        assert isinstance(data[field], int), f"Project.{field} must be int"
    assert data["completed_on"] is None or isinstance(data["completed_on"], str)
    assert data["follow_up_completed_on"] is None or isinstance(
        data["follow_up_completed_on"], str
    )
    assert data["warranty_valid_until"] is None or isinstance(
        data["warranty_valid_until"], str
    )
    assert_project_invariants(data)


def assert_project_invariants(data: dict):
    """Domain invariants on a single project read."""
    assert data["reserved_balance_cents"] >= 0
    assert data["reserved_balance_cents"] <= data["envelope_cents"], (
        f"reserved balance {data['reserved_balance_cents']} exceeds "
        f"envelope {data['envelope_cents']}"
    )
    # cancellation_reason stays null unless the project is CANCELLED (PRD §3.9)
    if data["status"] != ProjectStatus.CANCELLED.value:
        assert data["cancellation_reason"] is None
    else:
        assert data["cancellation_reason"] in _enum_values(ProjectCancellationReason)


def assert_event(data: dict):
    _assert_common_fields(data, "RebuildEvent")
    assert is_valid_uuid(data.get("project_id", ""))
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["event_date"], str)
    assert isinstance(data["max_volunteers"], int) and data["max_volunteers"] >= 1
    assert data["status"] in _enum_values(EventStatus)
    assert isinstance(data["open_slots"], int)


def assert_event_capacity(data: dict, active_enrollment_count: int):
    """Capacity invariant (PRD §3.6): max_volunteers == active + open_slots."""
    assert 0 <= data["open_slots"] <= data["max_volunteers"]
    assert data["max_volunteers"] == active_enrollment_count + data["open_slots"], (
        f"capacity invariant violated: max {data['max_volunteers']} != "
        f"active {active_enrollment_count} + open {data['open_slots']}"
    )


def assert_volunteer(data: dict):
    _assert_common_fields(data, "Volunteer")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["skills"], list)
    for skill in data["skills"]:
        assert skill in _enum_values(Trade)
    assert isinstance(data["team_leader_eligible"], bool)
    assert data["waiver_signed_on"] is None or isinstance(data["waiver_signed_on"], str)
    assert data["safety_training_completed_on"] is None or isinstance(
        data["safety_training_completed_on"], str
    )
    assert data["status"] in _enum_values(VolunteerStatus)
    assert isinstance(data["is_eligible"], bool)


def assert_enrollment(data: dict):
    _assert_common_fields(data, "EventEnrollment")
    assert is_valid_uuid(data.get("event_id", ""))
    assert is_valid_uuid(data.get("volunteer_id", ""))
    assert isinstance(data["is_team_leader"], bool)
    assert data["status"] in _enum_values(EnrollmentStatus)


def assert_contractor(data: dict):
    _assert_common_fields(data, "TradeContractor")
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["trade"] in _enum_values(Trade) and data["trade"] != Trade.NONE.value
    assert isinstance(data["license_number"], str) and data["license_number"]
    assert isinstance(data["license_expires_on"], str)
    assert isinstance(data["insurance_expires_on"], str)
    assert isinstance(data["max_concurrent_jobs"], int) and data["max_concurrent_jobs"] >= 1
    assert data["status"] in _enum_values(ContractorStatus)
    assert isinstance(data["strike_count"], int) and data["strike_count"] >= 0


def assert_work_order(data: dict):
    _assert_common_fields(data, "TradeWorkOrder")
    assert is_valid_uuid(data.get("project_id", ""))
    assert is_valid_uuid(data.get("contractor_id", ""))
    assert isinstance(data["scope_item_ids"], list) and data["scope_item_ids"]
    assert data["trade"] in _enum_values(Trade)
    assert data["status"] in _enum_values(WorkOrderStatus)
    assert data["quote_cents"] is None or (
        isinstance(data["quote_cents"], int) and data["quote_cents"] > 0
    )
    assert data["invoice_cents"] is None or (
        isinstance(data["invoice_cents"], int) and data["invoice_cents"] > 0
    )
    assert data["permit_number"] is None or isinstance(data["permit_number"], str)
    assert data["visit_start"] is None or isinstance(data["visit_start"], str)
    assert data["visit_end"] is None or isinstance(data["visit_end"], str)
    assert data["inspected_on"] is None or isinstance(data["inspected_on"], str)
    assert data["cancellation_reason"] is None or isinstance(
        data["cancellation_reason"], str
    )


def assert_material_order(data: dict):
    _assert_common_fields(data, "MaterialOrder")
    assert is_valid_uuid(data.get("project_id", ""))
    assert data["supplier"] is None or isinstance(data["supplier"], str)
    assert isinstance(data["lines"], list) and data["lines"]
    for line in data["lines"]:
        assert isinstance(line["item_name"], str) and line["item_name"]
        assert isinstance(line["quantity"], int) and line["quantity"] >= 1
        assert line["unit_price_dollars"] > 0
    assert data["status"] in _enum_values(MaterialOrderStatus)
    assert isinstance(data["subtotal_cents"], int) and data["subtotal_cents"] > 0
    assert isinstance(data["delivery_fee_cents"], int) and data["delivery_fee_cents"] >= 0
    assert isinstance(data["total_cents"], int)
    assert data["total_cents"] == data["subtotal_cents"] + data["delivery_fee_cents"]


def assert_warranty_claim(data: dict):
    _assert_common_fields(data, "WarrantyClaim")
    assert is_valid_uuid(data.get("project_id", ""))
    assert isinstance(data["description"], str) and data["description"]
    assert isinstance(data["claim_amount_cents"], int) and data["claim_amount_cents"] > 0
    assert data["status"] in _enum_values(WarrantyClaimStatus)
    assert data["payout_cents"] is None or (
        isinstance(data["payout_cents"], int) and data["payout_cents"] > 0
    )
    assert isinstance(data["submitted_on"], str)
    assert data["resolution_note"] is None or isinstance(data["resolution_note"], str)


def assert_clock_response(data: dict):
    assert isinstance(data["current_utc"], str) and data["current_utc"]


def assert_inspection_outcome(value: str):
    assert value in _enum_values(InspectionOutcome)
