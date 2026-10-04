"""Payload factories — one per writable resource, input fields only."""
from .constants import TEST_DEFAULTS as D


def create_region_payload(**overrides) -> dict:
    payload = {
        "code": D["REGION_CODE"],
        "name": D["REGION_NAME"],
        "state_codes": list(D["STATE_CODES"]),
        "coordinator_user_id": D["COORDINATOR_USER_ID"],
        "volunteer_pool_target": D["VOLUNTEER_POOL_TARGET"],
        "authorized_agency_codes": list(D["AUTHORIZED_AGENCY_CODES"]),
    }
    payload.update(overrides)
    return payload


def create_operation_payload(region_id, **overrides) -> dict:
    payload = {
        "incident_code": D["INCIDENT_CODE"],
        "incident_type": D["INCIDENT_TYPE"],
        "declared_at": D["DECLARED_AT"],
        "region_id": region_id,
    }
    payload.update(overrides)
    return payload


def create_shelter_site_payload(region_id, **overrides) -> dict:
    payload = {
        "facility_name": D["FACILITY_NAME"],
        "address_line": D["ADDRESS_LINE"],
        "region_id": region_id,
        "capacity_beds": D["CAPACITY_BEDS"],
        "accessibility_rating": "FULL",
        "functional_needs_support": True,
        "generator_onsite": True,
        "agreement_expires_at": D["AGREEMENT_EXPIRES_AT"],
    }
    payload.update(overrides)
    return payload


def inspection_payload(expected_shelter_site_version, **overrides) -> dict:
    payload = {
        "expected_shelter_site_version": expected_shelter_site_version,
        "inspected_at": D["INSPECTED_AT"],
        "inspector_user_id": D["COORDINATOR_USER_ID"],
        "capacity_verified_beds": D["CAPACITY_BEDS"],
        "accessibility_verified": True,
        "functional_needs_verified": True,
        "deficiency_count": 0,
        "result": "PASS",
    }
    payload.update(overrides)
    return payload


def create_volunteer_payload(region_id, **overrides) -> dict:
    payload = {
        "full_name": D["VOLUNTEER_NAME"],
        "home_region_id": region_id,
        "qualified_role_codes": list(D["VOLUNTEER_ROLES"]),
    }
    payload.update(overrides)
    return payload


def create_shelter_operation_payload(shelter_site_id, operation_id) -> dict:
    return {
        "shelter_site_id": shelter_site_id,
        "disaster_relief_operation_id": operation_id,
    }


def create_deployment_payload(volunteer_id, operation_id, **overrides) -> dict:
    payload = {
        "volunteer_id": volunteer_id,
        "disaster_relief_operation_id": operation_id,
        "role_code": "SHELTER_MANAGER",
        "travel_mode": "AIR",
        "rotation_start_at": D["ROTATION_START_AT"],
        "rotation_days": D["ROTATION_DAYS"],
    }
    payload.update(overrides)
    return payload


def create_shift_payload(deployment_id, shelter_operation_id, **overrides) -> dict:
    payload = {
        "volunteer_deployment_id": deployment_id,
        "shelter_operation_id": shelter_operation_id,
        "functional_area": "REGISTRATION",
        "shift_start_at": "2026-09-03T08:00:00Z",
        "shift_end_at": "2026-09-03T16:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_client_payload(region_id, **overrides) -> dict:
    payload = {
        "full_name": D["CLIENT_NAME"],
        "household_size": D["HOUSEHOLD_SIZE"],
        "region_id": region_id,
    }
    payload.update(overrides)
    return payload


def register_client_payload(client_id, **overrides) -> dict:
    payload = {
        "client_id": client_id,
        "occupied_from_at": D["OCCUPIED_FROM_AT"],
        "functional_needs_flag": False,
    }
    payload.update(overrides)
    return payload


def check_out_payload(**overrides) -> dict:
    payload = {}
    payload.update(overrides)
    return payload


def feeding_service_payload(**overrides) -> dict:
    payload = {
        "meal_type": "DINNER",
        "served_at": "2026-09-03T18:00:00Z",
        "meals_planned": 60,
        "meals_served": 41,
        "unit_cost_cents": 100,
    }
    payload.update(overrides)
    return payload


def health_service_payload(client_id, **overrides) -> dict:
    payload = {
        "client_id": client_id,
        "encounter_type": "MEDICAL",
        "occurred_at": "2026-09-03T18:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_client_case_payload(client_id, operation_id, **overrides) -> dict:
    payload = {
        "client_id": client_id,
        "disaster_relief_operation_id": operation_id,
        "assigned_caseworker_id": D["CASEWORKER_ID"],
    }
    payload.update(overrides)
    return payload


def verify_eligibility_payload(**overrides) -> dict:
    payload = {"eligibility_status": "VERIFIED"}
    payload.update(overrides)
    return payload


def recovery_plan_payload(expected_client_case_version, **overrides) -> dict:
    payload = {
        "expected_client_case_version": expected_client_case_version,
        "recovery_plan_summary": "Initial recovery plan",
    }
    payload.update(overrides)
    return payload


def create_referral_payload(**overrides) -> dict:
    payload = {
        "agency_code": "SALVATION_ARMY",
        "assistance_type": "HOUSING",
        "estimated_value_cents": 12000,
    }
    payload.update(overrides)
    return payload


def create_assistance_request_payload(fund_pool_id, **overrides) -> dict:
    payload = {
        "fund_pool_id": fund_pool_id,
        "assistance_type": "HOUSING",
        "requested_amount_cents": 30000,
    }
    payload.update(overrides)
    return payload


def create_fund_pool_payload(**overrides) -> dict:
    payload = {
        "fund_code": "DR-9101-GEN",
        "restriction_type": "UNRESTRICTED",
        "total_received_cents": 500000,
    }
    payload.update(overrides)
    return payload


def cost_ledger_entry_payload(expected_operation_version, fund_pool_id, **overrides) -> dict:
    payload = {
        "expected_disaster_relief_operation_version": expected_operation_version,
        "fund_pool_id": fund_pool_id,
        "cost_category": "LOGISTICS",
        "amount_cents": 1000,
        "entry_type": "CHARGE",
        "incurred_at": "2026-09-03T10:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_blood_drive_payload(region_id, **overrides) -> dict:
    payload = {
        "region_id": region_id,
        "site_name": "VFW Hall",
        "scheduled_start_at": "2026-09-10T08:00:00Z",
        "scheduled_end_at": "2026-09-10T18:00:00Z",
        "target_units": 100,
    }
    payload.update(overrides)
    return payload
