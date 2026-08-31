"""Payload factories — one per entity, client-supplied input fields only."""

DEFAULTS = {
    "VOLTAGE_CLASS": "DISTRIBUTION_12KV",
    "GROWTH_ZONE": "RAPID",
    "BASE_CYCLE_YEARS": 4,
    "PRESCRIPTION_CLEARANCE_FT": 10,
    "EFFECTIVE_FROM": "2026-01-01",
    "CIRCUIT_CODE": "CKT-A",
    "CUSTOMER_COUNT": 1200,
    "LAST_TRIM_COMPLETED_ON": "2024-03-15",
    "PROGRAM_YEAR": 2026,
    "PLANNED_SPAN_MILES": 10,
    "BUDGET_CENTS": 5_000_000,
    "SPAN_MILES": 2.5,
    "SPAN_PLANNED_UNITS": 200,
    "SPAN_CLEARANCE_FT": 12,
    "CREW_CODE": "CRW-1",
    "CREW_TYPE": "BUCKET",
    "HEADCOUNT": 3,
    "HOURLY_RATE_CENTS": 8533,
    "HOME_DISTRICT": "NORTH",
    "PREMISE_CODE": "PRM-1",
    "CONTACT_METHOD": "DOOR_HANGER",
    "UNIT_COUNT_AT_PREMISE": 30,
    "APPLICATOR_LICENSE_NO": "LIC-100",
    "BUFFER_FT": 25,
    "WINDOW_START": "2026-08-01",
    "WINDOW_END": "2026-08-31",
    "CHEMICAL_CODE": "GLYPHOSATE",
    "EVENT_CODE": "STM-1",
    "SEVERITY_LEVEL": 4,
}


def create_prescription_payload(**overrides) -> dict:
    payload = {
        "voltage_class": DEFAULTS["VOLTAGE_CLASS"],
        "growth_zone": DEFAULTS["GROWTH_ZONE"],
        "base_cycle_years": DEFAULTS["BASE_CYCLE_YEARS"],
        "clearance_radius_ft": DEFAULTS["PRESCRIPTION_CLEARANCE_FT"],
        "effective_from": DEFAULTS["EFFECTIVE_FROM"],
    }
    payload.update(overrides)
    return payload


def create_circuit_payload(**overrides) -> dict:
    payload = {
        "circuit_code": DEFAULTS["CIRCUIT_CODE"],
        "voltage_class": DEFAULTS["VOLTAGE_CLASS"],
        "growth_zone": DEFAULTS["GROWTH_ZONE"],
        "customer_count": DEFAULTS["CUSTOMER_COUNT"],
        "last_trim_completed_on": DEFAULTS["LAST_TRIM_COMPLETED_ON"],
    }
    payload.update(overrides)
    return payload


def create_work_plan_payload(circuit_id, **overrides) -> dict:
    payload = {
        "circuit_id": circuit_id,
        "program_year": DEFAULTS["PROGRAM_YEAR"],
        "planned_span_miles": DEFAULTS["PLANNED_SPAN_MILES"],
        "budget_cents": DEFAULTS["BUDGET_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_work_order_payload(work_plan_id, **overrides) -> dict:
    payload = {
        "work_plan_id": work_plan_id,
        "span_miles": DEFAULTS["SPAN_MILES"],
        "billing_method": "UNIT_PRICE",
        "planned_unit_count": DEFAULTS["SPAN_PLANNED_UNITS"],
    }
    payload.update(overrides)
    return payload


def create_crew_payload(**overrides) -> dict:
    payload = {
        "crew_code": DEFAULTS["CREW_CODE"],
        "crew_type": DEFAULTS["CREW_TYPE"],
        "headcount": DEFAULTS["HEADCOUNT"],
        "hourly_rate_cents": DEFAULTS["HOURLY_RATE_CENTS"],
        "home_district": DEFAULTS["HOME_DISTRICT"],
    }
    payload.update(overrides)
    return payload


def create_crew_assignment_payload(work_order_id, crew_id, **overrides) -> dict:
    payload = {
        "work_order_id": work_order_id,
        "crew_id": crew_id,
        "start_at": "2026-08-03T08:00:00Z",
        "end_at": "2026-08-03T16:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_production_entry_payload(crew_assignment_id, **overrides) -> dict:
    payload = {
        "crew_assignment_id": crew_assignment_id,
        "work_date": "2026-08-03",
        "units_trimmed": 180,
        "labor_hours": 8,
        "equipment_hours": 6,
        "disposal_tons": 1,
    }
    payload.update(overrides)
    return payload


def create_customer_notification_payload(work_order_id, **overrides) -> dict:
    payload = {
        "work_order_id": work_order_id,
        "premise_code": DEFAULTS["PREMISE_CODE"],
        "contact_method": DEFAULTS["CONTACT_METHOD"],
        "unit_count_at_premise": DEFAULTS["UNIT_COUNT_AT_PREMISE"],
    }
    payload.update(overrides)
    return payload


def create_hazard_tree_payload(circuit_id, **overrides) -> dict:
    payload = {
        "circuit_id": circuit_id,
        "species": "SILVER_MAPLE",
        "defect_class": "DEAD",
        "height_ft": 60,
        "offset_ft": 30,
    }
    payload.update(overrides)
    return payload


def create_herbicide_permit_payload(circuit_id, **overrides) -> dict:
    payload = {
        "circuit_id": circuit_id,
        "chemical_code": DEFAULTS["CHEMICAL_CODE"],
        "applicator_license_no": DEFAULTS["APPLICATOR_LICENSE_NO"],
        "buffer_ft": DEFAULTS["BUFFER_FT"],
        "window_start": DEFAULTS["WINDOW_START"],
        "window_end": DEFAULTS["WINDOW_END"],
    }
    payload.update(overrides)
    return payload


def create_storm_event_payload(**overrides) -> dict:
    payload = {
        "event_code": DEFAULTS["EVENT_CODE"],
        "severity_level": DEFAULTS["SEVERITY_LEVEL"],
        "affected_district": DEFAULTS["HOME_DISTRICT"],
    }
    payload.update(overrides)
    return payload


def create_outage_record_payload(circuit_id, **overrides) -> dict:
    payload = {
        "circuit_id": circuit_id,
        "outage_at": "2026-07-01T00:00:00Z",
        "cause_code": "TREE_GROWN_IN",
        "customers_affected": 300,
        "customer_minutes": 1500,
    }
    payload.update(overrides)
    return payload
