"""Payload factories - one per entity, input fields only."""

from .constants import TEST_DEFAULTS


def create_customer_payload(**overrides) -> dict:
    payload = {"account_name": "Northgate Industrial"}
    payload.update(overrides)
    return payload


def create_site_payload(customer_id: str, **overrides) -> dict:
    payload = {
        "customer_id": customer_id,
        "address_label": "Pier 9 Yard",
        "jurisdiction_code": TEST_DEFAULTS["STD_JURISDICTION"],
        "soil_bearing_capacity_psf": TEST_DEFAULTS["STD_SOIL_PSF"],
    }
    payload.update(overrides)
    return payload


def create_standard_crane_payload(**overrides) -> dict:
    payload = {
        "model_code": TEST_DEFAULTS["STD_CRANE_MODEL"],
        "class_tons": TEST_DEFAULTS["STD_CLASS_TONS"],
        "gross_weight_lb": TEST_DEFAULTS["STD_GROSS_WEIGHT_LB"],
        "counterweight_lb": TEST_DEFAULTS["STD_COUNTERWEIGHT_LB"],
        "outrigger_pad_area_sqft": TEST_DEFAULTS["STD_PAD_AREA_SQFT"],
        "max_line_pull_lb": TEST_DEFAULTS["STD_MAX_LINE_PULL_LB"],
        "rated_max_wind_mph": TEST_DEFAULTS["STD_RATED_MAX_WIND_MPH"],
        "annual_inspection_expires_on": TEST_DEFAULTS["STD_ANNUAL_INSPECTION_EXPIRES_ON"],
        "mob_demob_cents": TEST_DEFAULTS["STD_MOB_DEMOB_CENTS"],
        "hourly_rate_cents": TEST_DEFAULTS["STD_HOURLY_RATE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_critical_crane_payload(**overrides) -> dict:
    payload = create_standard_crane_payload(
        model_code=TEST_DEFAULTS["CRIT_CRANE_MODEL"],
        class_tons=TEST_DEFAULTS["CRIT_CLASS_TONS"],
        gross_weight_lb=TEST_DEFAULTS["CRIT_GROSS_WEIGHT_LB"],
        counterweight_lb=TEST_DEFAULTS["CRIT_COUNTERWEIGHT_LB"],
        outrigger_pad_area_sqft=TEST_DEFAULTS["CRIT_PAD_AREA_SQFT"],
    )
    payload.update(overrides)
    return payload


def create_load_chart_entry_payload(crane_id: str, **overrides) -> dict:
    payload = {
        "crane_id": crane_id,
        "configuration": "MAIN_BOOM",
        "boom_length_ft": TEST_DEFAULTS["STD_BOOM_LENGTH_FT"],
        "radius_ft": TEST_DEFAULTS["STD_RADIUS_FT"],
        "gross_capacity_lb": TEST_DEFAULTS["STD_CHART_CAPACITY_LB"],
    }
    payload.update(overrides)
    return payload


def create_operator_payload(**overrides) -> dict:
    payload = {
        "full_name": "Ray Kolb",
        "role_type": "OPERATOR",
        "certification_number": "NCCCO-88421",
        "certification_expires_on": "2027-03-31T00:00:00Z",
        "endorsement_class_tons": 200,
    }
    payload.update(overrides)
    return payload


def create_rigger_payload(**overrides) -> dict:
    payload = {
        "full_name": "Dina Ruiz",
        "role_type": "RIGGER",
        "certification_number": "NCCER-5510",
        "certification_expires_on": "2027-04-30T00:00:00Z",
        "rigger_level": "BASIC",
    }
    payload.update(overrides)
    return payload


def create_engineer_payload(**overrides) -> dict:
    payload = {
        "full_name": "Alan Pope",
        "role_type": "ENGINEER",
        "certification_number": "PE-NJ-3391",
        "certification_expires_on": "2028-01-31T00:00:00Z",
        "pe_license_state": "NJ",
    }
    payload.update(overrides)
    return payload


def create_rigging_gear_payload(**overrides) -> dict:
    payload = {
        "gear_tag": "SL-5001",
        "gear_type": "SLING",
        "rated_wll_lb": 30_000,
        "weight_lb": TEST_DEFAULTS["SLING_WEIGHT_LB"],
        "inspection_interval_days": 90,
    }
    payload.update(overrides)
    return payload


def create_gear_inspection_payload(gear_id: str, **overrides) -> dict:
    payload = {
        "gear_id": gear_id,
        "result": "PASS",
        "inspector_note": "acceptance",
    }
    payload.update(overrides)
    return payload


def create_lift_plan_payload(site_id: str, **overrides) -> dict:
    payload = {
        "site_id": site_id,
        "job_reference": "JOB-0001",
        "window_start": TEST_DEFAULTS["WINDOW_START"],
        "window_end": TEST_DEFAULTS["WINDOW_END"],
        "load_weight_lb": TEST_DEFAULTS["STD_LOAD_WEIGHT_LB"],
    }
    payload.update(overrides)
    return payload


def site_survey_payload(**overrides) -> dict:
    payload = {
        "confirmed_soil_bearing_capacity_psf": TEST_DEFAULTS["STD_SOIL_PSF"],
        "access_notes": "apron",
        "mat_inventory_available": True,
    }
    payload.update(overrides)
    return payload


def configure_payload(crane_id, operator_id, rigger_id, expected_lift_plan_version,
                      **overrides) -> dict:
    payload = {
        "crane_id": crane_id,
        "operator_id": operator_id,
        "rigger_id": rigger_id,
        "configuration": "MAIN_BOOM",
        "boom_length_ft": TEST_DEFAULTS["STD_BOOM_LENGTH_FT"],
        "radius_ft": TEST_DEFAULTS["STD_RADIUS_FT"],
        "parts_of_line": TEST_DEFAULTS["PARTS_OF_LINE"],
        "block_weight_lb": TEST_DEFAULTS["BLOCK_WEIGHT_LB"],
        "jib_weight_lb": 0,
        "aux_head_weight_lb": 0,
        "expected_lift_plan_version": expected_lift_plan_version,
    }
    payload.update(overrides)
    return payload


def create_gear_assignment_payload(lift_plan_id, gear_id, expected_gear_version,
                                   **overrides) -> dict:
    payload = {
        "lift_plan_id": lift_plan_id,
        "gear_id": gear_id,
        "leg_count": 4,
        "sling_angle_deg": 60,
        "expected_gear_version": expected_gear_version,
    }
    payload.update(overrides)
    return payload


def create_engineering_review_payload(lift_plan_id, author_personnel_id, **overrides) -> dict:
    payload = {
        "lift_plan_id": lift_plan_id,
        "author_personnel_id": author_personnel_id,
        "analysis_notes": "rev 1 analysis",
    }
    payload.update(overrides)
    return payload


def create_permit_payload(lift_plan_id, **overrides) -> dict:
    payload = {
        "lift_plan_id": lift_plan_id,
        "permit_type": "ROAD_CLOSURE",
        "jurisdiction_code": TEST_DEFAULTS["STD_JURISDICTION"],
    }
    payload.update(overrides)
    return payload


def create_standby_event_payload(lift_plan_id, **overrides) -> dict:
    payload = {
        "lift_plan_id": lift_plan_id,
        "cause": "WEATHER",
        "started_at": "2026-09-10T09:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_invoice_payload(lift_plan_id, expected_lift_plan_version, **overrides) -> dict:
    payload = {
        "lift_plan_id": lift_plan_id,
        "billing_mode": "HOURLY",
        "expected_lift_plan_version": expected_lift_plan_version,
    }
    payload.update(overrides)
    return payload
