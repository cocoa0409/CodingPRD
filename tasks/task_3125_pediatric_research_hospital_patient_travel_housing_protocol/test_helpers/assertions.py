"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
    assert_cost_precision,
)


def assert_common_fields(data: dict):
    """Every entity in this program declares common fields enabled."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_research_fund(data: dict):
    assert_common_fields(data)
    assert isinstance(data["fund_code"], str) and data["fund_code"]
    assert isinstance(data["fiscal_year"], int)
    assert isinstance(data["fundraising_raised_cents"], int)
    assert isinstance(data["federal_grant_cents"], int)
    assert_cost_precision(data["research_balance_cents"])
    assert_cost_precision(data["patient_support_balance_cents"])


def assert_clinical_protocol(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("DRAFT", "OPEN", "HELD", "CLOSED")
    assert data["required_stage"] in ("NEWLY_DIAGNOSED", "RELAPSED", "REFRACTORY", "REMISSION")
    assert data["age_tier"] in ("PAEDIATRIC", "ADOLESCENT", "MIXED")
    for field in ("protocol_budget_cents", "reserved_cents", "committed_cents",
                  "available_cents", "capacity", "enrolled_count"):
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert isinstance(data["is_protocol_held"], bool)
    assert isinstance(data["is_budget_saturated"], bool)
    assert data["available_cents"] == (
        data["protocol_budget_cents"] - data["reserved_cents"] - data["committed_cents"]
    ), "available_cents must equal budget less reserved less committed"


def assert_protocol_budget_envelope(data: dict):
    """Domain invariant: the three counters never overdraw the envelope."""
    assert data["reserved_cents"] >= 0
    assert data["committed_cents"] >= 0
    assert data["available_cents"] == (
        data["protocol_budget_cents"] - data["reserved_cents"] - data["committed_cents"]
    )
    assert data["enrolled_count"] >= 0
    assert data["enrolled_count"] <= data["capacity"]


def assert_referral(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("SUBMITTED", "ACCEPTED", "DECLINED", "WITHDRAWN", "ARRIVED")
    assert data["applied_tier"] in (
        "PENDING", "ON_CAMPUS", "PARTNER_CLASS_A", "PARTNER_CLASS_B",
        "PARTNER_CLASS_C", "DECLINED",
    )
    assert data["eligibility_alias"] == data["eligibility_alias"].lower()
    assert isinstance(data["computed_age_years"], int)
    assert isinstance(data["screening_fee_cents"], int)
    assert data["selector_window_days"] <= 540
    assert data["reservation_basis_cents"] >= 0


def assert_enrollment(data: dict):
    assert_common_fields(data)
    assert data["status"] in (
        "PENDING_CONSENT", "ENROLLED", "ACTIVE_TREATMENT", "ON_HIATUS",
        "SURVIVORSHIP", "WITHDRAWN", "COMPLETED",
    )
    assert data["assent_state"] in ("NOT_REQUIRED", "PENDING", "OBTAINED")
    assert isinstance(data["is_assent_required"], bool)


def assert_housing_facility(data: dict):
    assert_common_fields(data)
    assert data["tier"] in ("ON_CAMPUS", "PARTNER_CLASS_A", "PARTNER_CLASS_B", "PARTNER_CLASS_C")
    assert data["status"] in ("OPEN", "SUSPENDED", "CLOSED")
    assert data["is_on_campus"] is (data["tier"] == "ON_CAMPUS")
    assert data["is_partner_site"] is (data["tier"] != "ON_CAMPUS")
    assert data["immunosuppression_capable"] is (data["tier"] in ("ON_CAMPUS", "PARTNER_CLASS_A"))
    assert data["is_step_down_capable"] is (data["tier"] in ("PARTNER_CLASS_A", "PARTNER_CLASS_B"))
    assert isinstance(data["total_beds"], int) and data["total_beds"] > 0
    assert isinstance(data["buffer_beds"], int) and data["buffer_beds"] >= 0
    assert data["active_beds_committed"] <= data["total_beds"]


def assert_housing_assignment(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("SCHEDULED", "ACTIVE", "VACATED", "CANCELLED")
    assert data["assigned_tier"] in (
        "ON_CAMPUS", "PARTNER_CLASS_A", "PARTNER_CLASS_B", "PARTNER_CLASS_C",
    )
    assert data["housing_cost_cents"] == min(data["billed_nights"], 180) * data["nightly_rate_cents"]
    assert data["nightly_rate_cents"] in (11000, 13000, 15000, 19000)
    assert isinstance(data["is_active_occupancy"], bool)


def assert_pledge(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("ACTIVE", "SETTLED_FINAL", "VOIDED")
    assert data["covered_days"] >= 0
    assert_cost_precision(data["provisional_settled_cents"])
    assert_cost_precision(data["final_settled_cents"])
    assert data["billing_permitted_cents"] >= 0
    assert data["provisional_settled_cents"] == data["covered_days"] * 450


def assert_travel_arrangement(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("REQUESTED", "CONFIRMED", "DISBURSED", "CANCELLED")
    assert data["mode"] in ("AIR_ECONOMY", "AIR_MEDICAL", "GROUND", "RAIL")
    assert 2 <= data["traveler_count"] <= 6
    assert data["trip_reason"] in (
        "PROTOCOL_REVIEW", "THERAPY_ADMINISTRATION", "SURVIVORSHIP_VISIT", "FAMILY_REQUEST",
    )
    assert data["family_day_units"] >= 0
    assert data["transport_cost_cents"] >= 0


def assert_protocol_hold(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("ACTIVE", "RELEASED", "ESCALATED")
    assert data["hold_reason"] in ("IRB_REVIEW", "SAFETY_SIGNAL", "FUNDING_REVIEW", "SPONSOR_AUDIT")
    assert data["is_review_lock"] is (
        data["hold_reason"] == "IRB_REVIEW" and data["status"] == "ESCALATED"
    )


def assert_milestone(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("PENDING", "DUE", "EXECUTED", "MISSED")
    assert data["milestone_sequence"] >= 1


def assert_family_service_ledger(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("ACTIVE", "FROZEN")
    assert isinstance(data["ledger_epoch"], int) and data["ledger_epoch"] >= 0
    assert isinstance(data["accumulated_cents"], int) and data["accumulated_cents"] >= 0


def assert_sibling_service(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("ACTIVE", "COMPLETED", "CANCELLED")
    assert data["service_type"] in (
        "TUITION_STIPEND", "COUNSELING_SESSION", "RECREATION_PROGRAM", "SIBLING_CAMP",
    )
    assert data["sessions_delivered"] >= 0
    assert isinstance(data["has_reached_monthly_limit"], bool)


def assert_fund_pool_conservation(fund: dict):
    """The two derived pools together equal net fundraising."""
    assert fund["research_balance_cents"] + fund["patient_support_balance_cents"] == (
        fund["fundraising_raised_cents"] - fund["federal_grant_cents"]
    ), "research + patient-support pools must sum to net fundraising"
    assert_cost_precision(fund["research_balance_cents"])
    assert_cost_precision(fund["patient_support_balance_cents"])