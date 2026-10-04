"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_common_fields(data: dict):
    """Every resource carries a bare UUID id and an ISO 8601 created_at."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )


def assert_versioned_fields(data: dict):
    """Mutable resources additionally carry updated_at and version (PRD §2.5)."""
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1 on creation"


def assert_client_account(data: dict):
    assert_common_fields(data)
    assert_versioned_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["client_type"] in ("EMPLOYER", "HEALTH_PLAN")
    assert data["billing_model"] in ("ENGAGEMENT_MILESTONE", "OUTCOME_SHARED_SAVINGS")
    assert data["account_status"] in ("ACTIVE", "SUSPENDED", "CLOSED")
    assert isinstance(data["expected_monthly_engagement_rate"], (int, float))
    assert isinstance(data["savings_share_rate"], (int, float))


def assert_program_track(data: dict):
    """ProgramTrack carries id + created_at only — no version, no updated_at."""
    assert_common_fields(data)
    assert data["track_code"] in ("ACUTE", "CHRONIC", "SURGERY_AVOIDANCE")
    assert isinstance(data["base_fee_per_member_cents"], int)
    assert set(data["severity_weights"].keys()) == {"LOW", "HIGH"}


def assert_member(data: dict):
    assert_common_fields(data)
    assert_versioned_fields(data)
    assert data["member_status"] in (
        "PENDING_ELIGIBILITY", "ELIGIBLE", "INELIGIBLE", "ENROLLED", "GRADUATED", "DROPPED"
    )
    assert 0 <= data["baseline_pain_score"] <= 10
    assert 0 <= data["baseline_function_score"] <= 100
    assert isinstance(data["red_flag_multipliers"], list)
    assert isinstance(data["red_flag_weight"], (int, float))


def assert_eligibility_file(data: dict):
    assert_common_fields(data)
    assert_versioned_fields(data)
    assert data["file_status"] in ("INGESTED", "SCREENED", "ASSIGNED", "CLOSED")
    assert data["roster_format"] in ("STANDARD", "LEGACY")
    for field in ("member_row_count", "eligible_member_count", "ineligible_member_count",
                  "screened_member_count", "total_monthly_fee_cents",
                  "provisional_total_monthly_fee_cents", "fee_variance_cents"):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_enrollment(data: dict):
    assert_common_fields(data)
    assert_versioned_fields(data)
    assert data["enrollment_status"] in (
        "PENDING_SCREENING", "PENDING_CLINICAL_REVIEW", "AWAITING_TRANSITION_REVIEW",
        "ACTIVE", "ACTIVATION_FAILED", "COMPLETED", "DROPPED", "TRANSITIONED"
    )
    assert isinstance(data["adherence_rate"], (int, float))
    assert isinstance(data["weeks_active"], int)
    assert isinstance(data["dropout_risk_score"], int)
    assert 0 <= data["dropout_risk_score"] <= 100
    assert data["projected_engagement_milestone"] in (0, 1)
    assert isinstance(data["attributed_savings_cents"], int)


def assert_clinical_review(data: dict):
    assert_common_fields(data)
    assert_versioned_fields(data)
    assert data["review_status"] in ("SUBMITTED", "CONDUCTED")


def assert_exercise_session(data: dict):
    assert_common_fields(data)
    assert_versioned_fields(data)
    assert data["session_status"] in ("SCHEDULED", "COMPLETED", "MISSED")
    assert data["recorded_via"] in ("SENSOR", "CAMERA")


def assert_outreach_contact(data: dict):
    assert_common_fields(data)
    assert_versioned_fields(data)
    assert data["outreach_status"] in ("QUEUED", "DELIVERED", "FAILED")
    assert data["channel"] in ("PUSH", "SMS", "PHONE")


def assert_clinician(data: dict):
    """Clinician carries id + created_at only — no version, no updated_at."""
    assert_common_fields(data)
    assert data["discipline"] in ("PHYSICAL_THERAPIST", "PHYSICIAN")
    assert data["clinician_status"] in ("AVAILABLE", "LIMITED", "DEACTIVATED")


def assert_appointment(data: dict):
    assert_common_fields(data)
    assert_versioned_fields(data)
    assert data["appointment_status"] in ("SCHEDULED", "COMPLETED", "CANCELLED", "NO_SHOW")
    assert data["slot_type"] in ("INITIAL_CONSULT", "FOLLOW_UP")


def assert_outcome_measurement(data: dict):
    assert_common_fields(data)
    assert_versioned_fields(data)
    assert data["measurement_status"] in ("RECORDED", "SUPERSEDED", "FINALIZED")
    assert 0 <= data["pain_score"] <= 10
    assert 0 <= data["function_score"] <= 100


def assert_claim_line(data: dict):
    assert_common_fields(data)
    assert_versioned_fields(data)
    assert data["claim_severity"] in ("LOW", "MODERATE", "HIGH")
    assert data["claim_source"] in ("MEDICAL", "PHARMACY")
    assert isinstance(data["amount_cents"], int)
    assert data["amount_cents"] >= 0
    assert isinstance(data["line_instance_version"], int)


def assert_fee_invoice(data: dict):
    assert_common_fields(data)
    assert_versioned_fields(data)
    assert data["invoice_status"] in ("DRAFT", "FINALIZED", "VOID")
    for field in ("milestone_member_count", "milestone_engagement_component_cents",
                  "savings_share_component_cents", "additional_fee_component_cents",
                  "recalculated_component_cents", "provisional_amount_cents",
                  "final_amount_cents", "net_delta_cents"):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_care_transition(data: dict):
    assert_common_fields(data)
    assert_versioned_fields(data)
    assert data["transition_status"] in ("PENDING", "COMPLETED")
    assert isinstance(data["handoff_referral_count"], int)


# ─── Domain invariant checkers ────────────────────────
def assert_money_is_integer_cents(data: dict, field: str):
    """Every monetary quantity is an integer number of cents (PRD §2.7)."""
    value = data[field]
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{field} must be an integer number of cents, got {value!r}"
    )


def assert_enrollment_invariants(data: dict):
    """Invariants that must hold after any operation on an enrollment."""
    assert data["dropout_risk_score"] <= 100, "risk score saturates at the ceiling"
    assert data["dropout_risk_score"] >= 0
    assert data["adherence_rate"] >= 0.0
    assert data["weeks_active"] >= 0
    assert data["consult_cancellation_count"] >= 0
    if data["enrollment_status"] == "DROPPED":
        assert data["dropout_week"] is not None
    if data["enrollment_status"] == "COMPLETED":
        assert data["completed_week"] is not None


def assert_roster_fee_variance(data: dict):
    """fee_variance_cents is the chronological total minus the provisional total."""
    assert data["fee_variance_cents"] == (
        data["total_monthly_fee_cents"] - data["provisional_total_monthly_fee_cents"]
    ), "fee_variance_cents must equal total_monthly_fee_cents - provisional_total_monthly_fee_cents"


def assert_invoice_delta_invariant(data: dict):
    assert data["net_delta_cents"] == (
        data["final_amount_cents"] - data["provisional_amount_cents"]
    ), "net_delta_cents must equal final_amount_cents - provisional_amount_cents"