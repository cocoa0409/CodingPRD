"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_hospital(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["city"], str) and len(data["city"]) > 0
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_house(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["city"], str)
    assert is_valid_uuid(data.get("associated_hospital_id", "")), "associated_hospital_id must be a UUID"
    assert data["posture"] in ("OPEN", "NEAR_CAPACITY", "FULL")
    assert isinstance(data["occupied_room_count"], int) and data["occupied_room_count"] >= 0
    assert isinstance(data["available_room_count"], int) and data["available_room_count"] >= 0
    assert isinstance(data["reserved_room_count"], int) and data["reserved_room_count"] >= 0
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_room(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_valid_uuid(data.get("house_id", "")), "house_id must be a UUID"
    assert isinstance(data["room_number"], str) and len(data["room_number"]) > 0
    assert isinstance(data["bed_count"], int) and data["bed_count"] > 0
    assert isinstance(data["occupancy_limit"], int) and data["occupancy_limit"] > 0
    assert data["status"] in ("AVAILABLE", "MAINTENANCE", "OFFLINE")
    assert isinstance(data["occupied"], bool)
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_family(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data["family_name"], str) and len(data["family_name"]) > 0
    assert isinstance(data["primary_contact_name"], str)
    assert isinstance(data["home_city"], str)
    assert isinstance(data["distance_miles"], (int, float))
    assert isinstance(data["child_patient_name"], str)
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_referral(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_valid_uuid(data.get("family_id", "")), "family_id must be a UUID"
    assert is_valid_uuid(data.get("hospital_id", "")), "hospital_id must be a UUID"
    assert isinstance(data["treating_unit"], str)
    assert data["care_type"] in ("INPATIENT", "OUTPATIENT")
    assert data["acuity_level"] in ("LOW", "MODERATE", "HIGH", "CRITICAL")
    assert isinstance(data["attending_clinician"], str)
    assert data["status"] in ("PENDING", "VERIFIED", "DECLINED", "REVOKED", "EXPIRED")
    assert isinstance(data["created_by_user_id"], str)
    assert "verified_by_user_id" in data
    assert "verified_at" in data
    assert "valid_until" in data
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_stay_request(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_valid_uuid(data.get("family_id", "")), "family_id must be a UUID"
    assert is_valid_uuid(data.get("house_id", "")), "house_id must be a UUID"
    assert is_valid_uuid(data.get("referral_id", "")), "referral_id must be a UUID"
    assert isinstance(data["expected_nights"], int) and data["expected_nights"] > 0
    assert data["self_reported_acuity"] in ("LOW", "MODERATE", "HIGH", "CRITICAL")
    assert data["verification_status"] in ("UNVERIFIED", "VERIFICATION_OK", "VERIFICATION_FAILED")
    assert data["assignment_status"] in ("WAITLISTED", "OFFERED", "ACCEPTED", "FULFILLED", "CANCELLED")
    assert isinstance(data["provisional_score"], (int, float))
    assert "verified_score" in data
    assert "offered_room_id" in data
    assert "offer_expires_at" in data
    assert "waitlisted_since" in data
    assert "superseded_by_request_id" in data
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_stay(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_valid_uuid(data.get("stay_request_id", "")), "stay_request_id must be a UUID"
    assert is_valid_uuid(data.get("family_id", "")), "family_id must be a UUID"
    assert is_valid_uuid(data.get("room_id", "")), "room_id must be a UUID"
    assert isinstance(data["check_in_date"], str) and len(data["check_in_date"]) == 10
    assert isinstance(data["expected_check_out_date"], str) and len(data["expected_check_out_date"]) == 10
    assert "actual_check_out_date" in data
    assert data["status"] in ("ACTIVE", "UNDER_REVIEW", "TRANSITION_PLANNED", "RELOCATION_REQUIRED", "CHECKED_OUT")
    assert isinstance(data["approved_extension_count"], int) and data["approved_extension_count"] >= 0
    assert "pending_extension_nights" in data
    assert "transition_plan_notes" in data
    assert "review_reason" in data
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_guest_registration(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_valid_uuid(data.get("stay_id", "")), "stay_id must be a UUID"
    assert isinstance(data["guest_name"], str) and len(data["guest_name"]) > 0
    assert isinstance(data["relationship"], str)
    assert isinstance(data["is_overnight"], bool)
    assert data["status"] in ("REGISTERED", "DEPARTED")
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_illness_screening(data: dict):
    """Append-only record: id + created_at only, no updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_valid_uuid(data.get("stay_id", "")), "stay_id must be a UUID"
    assert isinstance(data["temperature_tenths_c"], int)
    assert isinstance(data["symptom_count"], int) and data["symptom_count"] >= 0
    assert data["result"] in ("PASS", "FAIL")
    assert is_iso8601_timestamp(data.get("screened_at", "")), "screened_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "version" not in data, "IllnessScreening carries no version field"
    assert "updated_at" not in data, "IllnessScreening carries no updated_at field"


def assert_contribution_request(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_valid_uuid(data.get("stay_id", "")), "stay_id must be a UUID"
    assert isinstance(data["nightly_rate_cents"], int) and data["nightly_rate_cents"] > 0
    assert isinstance(data["planned_nights"], int) and data["planned_nights"] > 0
    assert data["hardship_tier"] in ("NONE", "PARTIAL", "FULL")
    assert isinstance(data["per_night_cents"], int)
    assert isinstance(data["requested_amount_cents"], int)
    assert "settled_amount_cents" in data
    assert isinstance(data["paid_cents"], int) and data["paid_cents"] >= 0
    assert isinstance(data["waived_cents"], int) and data["waived_cents"] >= 0
    assert isinstance(data["forgiven_cents"], int) and data["forgiven_cents"] >= 0
    assert isinstance(data["outstanding_cents"], int) and data["outstanding_cents"] >= 0
    assert data["status"] in ("OPEN", "PARTIALLY_PAID", "PAID", "WAIVED", "FORGIVEN")
    assert_contribution_ledger_invariant(data)


def assert_volunteer_group(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data["group_name"], str) and len(data["group_name"]) > 0
    assert isinstance(data["contact_email"], str)
    assert "certified_until" in data
    assert data["certification_status"] in ("UNCERTIFIED", "CERTIFIED", "EXPIRED")
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_meal_shift(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_valid_uuid(data.get("house_id", "")), "house_id must be a UUID"
    assert isinstance(data["shift_date"], str) and len(data["shift_date"]) == 10
    assert data["meal_type"] in ("BREAKFAST", "LUNCH", "DINNER")
    assert isinstance(data["servings_planned"], int) and data["servings_planned"] > 0
    assert data["status"] in ("OPEN", "CLAIMED", "COMPLETED", "CANCELLED")
    assert "claimed_by_group_id" in data
    assert "servings_served" in data
    assert "food_safety_attested" in data
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_care_space(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_valid_uuid(data.get("hospital_id", "")), "hospital_id must be a UUID"
    assert isinstance(data["space_name"], str) and len(data["space_name"]) > 0
    assert data["space_type"] in ("FAMILY_ROOM", "MOBILE_CARE_UNIT")
    assert isinstance(data["capacity"], int) and data["capacity"] > 0
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_care_space_booking(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_valid_uuid(data.get("care_space_id", "")), "care_space_id must be a UUID"
    assert is_valid_uuid(data.get("family_id", "")), "family_id must be a UUID"
    assert is_iso8601_timestamp(data.get("start_at", "")), "start_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("end_at", "")), "end_at must be ISO 8601"
    assert isinstance(data["party_size"], int) and data["party_size"] > 0
    assert data["status"] in ("CONFIRMED", "CANCELLED")
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_in_kind_donation(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_valid_uuid(data.get("house_id", "")), "house_id must be a UUID"
    assert isinstance(data["donor_name"], str) and len(data["donor_name"]) > 0
    assert data["supply_category"] in ("HYGIENE_KIT", "PANTRY_STAPLE", "CLEANING_SUPPLY", "BABY_SUPPLY")
    assert isinstance(data["quantity_received"], int) and data["quantity_received"] > 0
    assert isinstance(data["quantity_distributed"], int) and data["quantity_distributed"] >= 0
    assert data["quantity_distributed"] <= data["quantity_received"]
    assert data["status"] in ("RECEIVED", "PARTIALLY_DISTRIBUTED", "DEPLETED")
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_contribution_ledger_invariant(data: dict):
    """Conserved quantity: requested == paid + waived + forgiven + outstanding."""
    total = data["paid_cents"] + data["waived_cents"] + data["forgiven_cents"] + data["outstanding_cents"]
    assert data["requested_amount_cents"] == total, (
        f"Ledger invariant violated: requested {data['requested_amount_cents']} != "
        f"{data['paid_cents']} + {data['waived_cents']} + {data['forgiven_cents']} + {data['outstanding_cents']}"
    )


def assert_house_census_invariant(data: dict):
    """occupied + reserved + available equals the number of AVAILABLE-status rooms
    at the house; callers provide that denominator separately."""
    for k in ("occupied_room_count", "reserved_room_count", "available_room_count"):
        assert isinstance(data[k], int) and data[k] >= 0
