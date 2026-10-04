"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

HOSPITAL_STATUSES = ["OPEN", "SUSPENDED", "CLOSED"]
PROGRAM_STATUSES = ["ACTIVE", "SUSPENDED"]
REFERRAL_SOURCE_STATUSES = ["ACTIVE", "SUSPENDED"]
PROGRAM_CATEGORIES = ["ORTHOPEDIC", "BURN", "CLEFT_CRANIOFACIAL", "SPINAL_CORD", "NEUROMUSCULAR"]
CONDITION_CATEGORIES = PROGRAM_CATEGORIES + ["OTHER"]
SOURCE_TYPES = ["COMMUNITY_PHYSICIAN", "OUTREACH_CLINIC", "INTERNATIONAL_PARTNER"]
FAMILY_ABILITY = ["UNABLE", "PARTIAL", "ABLE", "DECLINED_TO_STATE"]
APPLICATION_STATUSES = [
    "SUBMITTED", "PENDING_REVIEW", "INFO_REQUESTED", "ACCEPTED", "DENIED", "WITHDRAWN",
]
REVIEW_ACTIONS = [
    "OPEN_ROUND", "REQUEST_INFO", "CAST_VOTE_ACCEPT", "CAST_VOTE_DENY", "RESUBMIT_INFO",
]
POLICY_STATUSES = ["VERIFIED", "LAPSED"]
BILLING_STATUSES = ["OPEN", "SETTLED"]
CLAIM_STATUSES = ["SUBMITTED", "ADJUDICATED", "DENIED_CLAIM"]
CLINICAL_STATUSES = ["PLANNING", "ACTIVE_TREATMENT", "SURVEILLANCE", "DISCHARGED"]
FUNDING_STATUSES = ["UNFUNDED", "PARTIALLY_FUNDED", "FULLY_FUNDED"]
STAGE_STATUSES = ["PLANNED", "SCHEDULED", "COMPLETED", "DEFERRED", "CANCELLED_STAGE"]
GRANT_TYPES = ["TRAVEL", "LODGING", "TRAVEL_AND_LODGING"]
GRANT_STATUSES = ["ACTIVE", "EXHAUSTED", "REVOKED"]
CLINIC_STATUSES = ["PROPOSED", "CONFIRMED", "IN_PROGRESS", "COMPLETED", "CANCELLED_CLINIC"]
SCREENING_STATUSES = ["BOOKED", "COMPLETED", "CONVERTED", "NO_SHOW", "EXPIRED"]
FUND_STATUSES = ["OPEN", "LOCKED", "CLOSED"]
ALLOCATION_STATUSES = ["PLEDGED", "COMMITTED", "RELEASED", "WITHDRAWN"]


def _assert_common(data: dict, with_version: bool = True):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    if with_version:
        assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
        assert isinstance(data.get("version"), int) and data["version"] >= 1, \
            "version must be a positive integer"
    else:
        assert "updated_at" not in data, "append-only resource must not carry updated_at"
        assert "version" not in data, "append-only resource must not carry version"


def assert_hospital(data: dict):
    _assert_common(data)
    for f in ("hospital_code", "name", "city", "state_code"):
        assert isinstance(data.get(f), str) and data[f], f"{f} must be a non-empty string"
    assert isinstance(data.get("latitude"), (int, float)) and -90 <= data["latitude"] <= 90
    assert isinstance(data.get("longitude"), (int, float)) and -180 <= data["longitude"] <= 180
    assert isinstance(data.get("annual_capacity"), int) and data["annual_capacity"] >= 1
    assert isinstance(data.get("admissions_ytd"), int) and data["admissions_ytd"] >= 0
    assert data.get("status") in HOSPITAL_STATUSES


def assert_program(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("hospital_id", "")), "hospital_id must be a UUID"
    assert data.get("category") in PROGRAM_CATEGORIES
    assert isinstance(data.get("accepts_international"), bool)
    assert isinstance(data.get("min_age_months"), int) and data["min_age_months"] >= 0
    assert isinstance(data.get("max_age_months"), int)
    assert data["max_age_months"] > data["min_age_months"]
    assert isinstance(data.get("staged_care_required"), bool)
    assert data.get("status") in PROGRAM_STATUSES


def assert_referral_source(data: dict):
    _assert_common(data)
    assert data.get("source_type") in SOURCE_TYPES
    assert isinstance(data.get("display_name"), str) and data["display_name"]
    assert isinstance(data.get("contact_email"), str) and data["contact_email"]
    assert isinstance(data.get("country_code"), str) and len(data["country_code"]) == 2
    assert data.get("status") in REFERRAL_SOURCE_STATUSES


def assert_application(data: dict):
    _assert_common(data)
    assert isinstance(data.get("patient_full_name"), str) and data["patient_full_name"]
    assert is_iso8601_timestamp(data.get("patient_date_of_birth", ""))
    assert data.get("condition_category") in CONDITION_CATEGORIES
    assert is_valid_uuid(data.get("referral_source_id", "")), "referral_source_id must be a UUID"
    assert is_valid_uuid(data.get("program_id", "")), "program_id must be a UUID"
    assert isinstance(data.get("home_latitude"), (int, float))
    assert isinstance(data.get("home_longitude"), (int, float))
    assert isinstance(data.get("is_international"), bool)
    assert data.get("family_ability_to_pay") in FAMILY_ABILITY
    assert isinstance(data.get("review_round"), int) and data["review_round"] >= 1
    assert isinstance(data.get("age_at_submission_months"), int)
    assert data.get("status") in APPLICATION_STATUSES


def assert_application_review(data: dict):
    # Append-only log: only id + created_at among common fields.
    _assert_common(data, with_version=False)
    assert is_valid_uuid(data.get("application_id", "")), "application_id must be a UUID"
    assert isinstance(data.get("round_number"), int) and data["round_number"] >= 1
    assert isinstance(data.get("reviewer_user_id"), str) and data["reviewer_user_id"]
    assert data.get("action") in REVIEW_ACTIONS
    assert isinstance(data.get("vote_weight"), int) and data["vote_weight"] >= 1


def assert_insurance_policy(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("application_id", "")), "application_id must be a UUID"
    assert isinstance(data.get("payer_name"), str) and data["payer_name"]
    assert isinstance(data.get("policy_number"), str) and data["policy_number"]
    assert isinstance(data.get("coverage_exists"), bool)
    assert data.get("status") in POLICY_STATUSES


def assert_billing_account(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("application_id", "")), "application_id must be a UUID"
    assert data.get("status") in BILLING_STATUSES
    for f in (
        "total_charged_cents", "insurance_paid_cents", "charity_writeoff_cents",
        "open_claim_cents",
    ):
        assert isinstance(data.get(f), int) and data[f] >= 0, f"{f} must be a non-negative integer"


def assert_billing_account_invariants(data: dict):
    """The family is never billed: family_balance_cents is always 0, and the
    conservation identity total == paid + writeoff + open holds."""
    assert data.get("family_balance_cents") == 0, \
        f"family_balance_cents must be 0, got {data.get('family_balance_cents')}"
    total = data["total_charged_cents"]
    decomposed = (
        data["insurance_paid_cents"]
        + data["charity_writeoff_cents"]
        + data["open_claim_cents"]
    )
    assert total == decomposed, (
        f"conservation violated: total_charged_cents {total} != "
        f"insurance_paid {data['insurance_paid_cents']} + writeoff "
        f"{data['charity_writeoff_cents']} + open {data['open_claim_cents']}"
    )


def assert_claim(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("billing_account_id", "")), "billing_account_id must be a UUID"
    assert is_iso8601_timestamp(data.get("service_date", ""))
    lines = data.get("lines")
    assert isinstance(lines, list) and len(lines) >= 1, "lines must be a non-empty array"
    for line in lines:
        assert isinstance(line.get("cpt_code"), str) and line["cpt_code"]
        assert isinstance(line.get("charge_cents"), int) and line["charge_cents"] >= 1
    assert isinstance(data.get("submitted_amount_cents"), int)
    assert data["submitted_amount_cents"] == sum(line["charge_cents"] for line in lines)
    assert isinstance(data.get("estimated_allowed_cents"), int)
    assert data.get("status") in CLAIM_STATUSES


def assert_care_plan(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("application_id", "")), "application_id must be a UUID"
    assert data.get("clinical_status") in CLINICAL_STATUSES
    assert data.get("funding_status") in FUNDING_STATUSES
    assert isinstance(data.get("planned_stage_count"), int) and data["planned_stage_count"] >= 1
    assert isinstance(data.get("completed_stage_count"), int) and data["completed_stage_count"] >= 0
    assert data["completed_stage_count"] <= data["planned_stage_count"]


def assert_staged_procedure(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("care_plan_id", "")), "care_plan_id must be a UUID"
    assert isinstance(data.get("stage_index"), int) and data["stage_index"] >= 1
    assert isinstance(data.get("min_age_months"), int) and data["min_age_months"] >= 0
    assert isinstance(data.get("max_age_months"), int)
    assert data["max_age_months"] > data["min_age_months"]
    assert is_iso8601_timestamp(data.get("scheduled_date", ""))
    assert isinstance(data.get("estimated_cost_cents"), int) and data["estimated_cost_cents"] >= 1
    assert data.get("status") in STAGE_STATUSES


def assert_travel_grant(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("application_id", "")), "application_id must be a UUID"
    assert data.get("grant_type") in GRANT_TYPES
    assert isinstance(data.get("straight_line_distance_miles"), (int, float))
    assert isinstance(data.get("road_distance_miles"), (int, float))
    assert isinstance(data.get("distance_eligible"), bool)
    assert isinstance(data.get("nightly_lodging_stipend_cents"), int)
    assert isinstance(data.get("travel_allowance_cents"), int)
    assert data.get("status") in GRANT_STATUSES


def assert_outreach_clinic(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("hospital_id", "")), "hospital_id must be a UUID"
    assert isinstance(data.get("location_name"), str) and data["location_name"]
    assert isinstance(data.get("latitude"), (int, float))
    assert isinstance(data.get("longitude"), (int, float))
    assert is_iso8601_timestamp(data.get("start_date", ""))
    assert is_iso8601_timestamp(data.get("end_date", ""))
    assert is_iso8601_timestamp(data.get("conversion_deadline", ""))
    assert isinstance(data.get("screening_capacity"), int) and data["screening_capacity"] >= 1
    assert isinstance(data.get("booked_screening_count"), int) and data["booked_screening_count"] >= 0
    assert data.get("status") in CLINIC_STATUSES


def assert_outreach_screening(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("clinic_id", "")), "clinic_id must be a UUID"
    assert isinstance(data.get("patient_full_name"), str) and data["patient_full_name"]
    assert is_iso8601_timestamp(data.get("patient_date_of_birth", ""))
    assert data.get("suspected_condition_category") in CONDITION_CATEGORIES
    assert is_iso8601_timestamp(data.get("screening_date", ""))
    assert data.get("status") in SCREENING_STATUSES


def assert_philanthropic_fund(data: dict):
    _assert_common(data)
    assert isinstance(data.get("fund_name"), str) and data["fund_name"]
    assert isinstance(data.get("fiscal_year"), int)
    assert isinstance(data.get("total_committed_cents"), int) and data["total_committed_cents"] >= 0
    assert isinstance(data.get("allocated_cents"), int) and data["allocated_cents"] >= 0
    assert isinstance(data.get("available_cents"), int) and data["available_cents"] >= 0
    assert data.get("status") in FUND_STATUSES


def assert_fund_invariants(data: dict):
    """allocated + available always equals total_committed."""
    assert data["allocated_cents"] + data["available_cents"] == data["total_committed_cents"], (
        f"fund conservation violated: allocated {data['allocated_cents']} + available "
        f"{data['available_cents']} != total_committed {data['total_committed_cents']}"
    )


def assert_fund_allocation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("fund_id", "")), "fund_id must be a UUID"
    assert is_valid_uuid(data.get("hospital_id", "")), "hospital_id must be a UUID"
    assert isinstance(data.get("amount_cents"), int) and data["amount_cents"] >= 1
    assert data.get("status") in ALLOCATION_STATUSES
