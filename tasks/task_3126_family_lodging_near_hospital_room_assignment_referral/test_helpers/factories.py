"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS as D


def create_hospital_payload(**overrides) -> dict:
    defaults = {"name": D["HOSPITAL_NAME"], "city": D["HOSPITAL_CITY"]}
    defaults.update(overrides)
    return defaults


def create_house_payload(hospital_id, **overrides) -> dict:
    defaults = {
        "name": D["HOUSE_NAME"],
        "city": D["HOUSE_CITY"],
        "associated_hospital_id": hospital_id,
    }
    defaults.update(overrides)
    return defaults


def create_room_payload(**overrides) -> dict:
    defaults = {
        "room_number": D["ROOM_NUMBER"],
        "bed_count": D["BED_COUNT"],
        "occupancy_limit": D["OCCUPANCY_LIMIT"],
    }
    defaults.update(overrides)
    return defaults


def create_family_payload(**overrides) -> dict:
    defaults = {
        "family_name": D["FAMILY_NAME"],
        "primary_contact_name": D["PRIMARY_CONTACT"],
        "home_city": D["HOME_CITY"],
        "distance_miles": D["DISTANCE_MILES"],
        "child_patient_name": D["CHILD_PATIENT_NAME"],
    }
    defaults.update(overrides)
    return defaults


def create_referral_payload(family_id, hospital_id, **overrides) -> dict:
    defaults = {
        "family_id": family_id,
        "hospital_id": hospital_id,
        "treating_unit": D["TREATING_UNIT"],
        "care_type": D["CARE_TYPE"],
        "acuity_level": D["ACUITY_LEVEL"],
        "attending_clinician": D["ATTENDING_CLINICIAN"],
    }
    defaults.update(overrides)
    return defaults


def create_stay_request_payload(family_id, house_id, referral_id, expected_family_version, **overrides) -> dict:
    defaults = {
        "family_id": family_id,
        "house_id": house_id,
        "referral_id": referral_id,
        "expected_nights": D["EXPECTED_NIGHTS"],
        "self_reported_acuity": D["SELF_REPORTED_ACUITY"],
        "expected_family_version": expected_family_version,
    }
    defaults.update(overrides)
    return defaults


def register_guest_payload(**overrides) -> dict:
    defaults = {
        "guest_name": "Aunt May",
        "relationship": "aunt",
        "is_overnight": True,
    }
    defaults.update(overrides)
    return defaults


def record_screening_payload(**overrides) -> dict:
    defaults = {"temperature_tenths_c": 370, "symptom_count": 0}
    defaults.update(overrides)
    return defaults


def create_contribution_request_payload(**overrides) -> dict:
    defaults = {
        "nightly_rate_cents": 2500,
        "planned_nights": 4,
        "hardship_tier": "NONE",
    }
    defaults.update(overrides)
    return defaults


def create_volunteer_group_payload(**overrides) -> dict:
    defaults = {"group_name": "Rotary Chefs", "contact_email": "chefs@rotary.org"}
    defaults.update(overrides)
    return defaults


def create_meal_shift_payload(**overrides) -> dict:
    defaults = {"shift_date": "2026-09-08", "meal_type": "LUNCH", "servings_planned": 20}
    defaults.update(overrides)
    return defaults


def create_care_space_payload(**overrides) -> dict:
    defaults = {"space_name": "Family Room 2A", "space_type": "FAMILY_ROOM", "capacity": 6}
    defaults.update(overrides)
    return defaults


def create_care_space_booking_payload(family_id, **overrides) -> dict:
    defaults = {
        "family_id": family_id,
        "start_at": "2026-09-03T09:00:00Z",
        "end_at": "2026-09-03T10:00:00Z",
        "party_size": 3,
    }
    defaults.update(overrides)
    return defaults


def create_in_kind_donation_payload(**overrides) -> dict:
    defaults = {
        "donor_name": "Rotary Club",
        "supply_category": "HYGIENE_KIT",
        "quantity_received": 10,
    }
    defaults.update(overrides)
    return defaults
