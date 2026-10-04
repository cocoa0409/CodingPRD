"""Payload factories — one per entity, input fields only."""

DEFAULT_CONTRACTOR = {
    "legal_name": "Test Contractor Co",
    "license_number": "LIC-TEST",
    "license_expiry": "2035-01-01",
    "insurance_expiry": "2035-01-01",
    "territory_codes": ["T1"],
}


def create_contractor_payload(**overrides) -> dict:
    payload = dict(DEFAULT_CONTRACTOR)
    payload.update(overrides)
    return payload


def create_training_course_payload(**overrides) -> dict:
    payload = {"title": "Basics", "credits": 4, "validity_months": 36}
    payload.update(overrides)
    return payload


def create_training_enrollment_payload(**overrides) -> dict:
    payload = {}
    payload.update(overrides)
    return payload


def create_certification_payload(**overrides) -> dict:
    payload = {"tier": "BRONZE"}
    payload.update(overrides)
    return payload


def create_catalog_item_payload(**overrides) -> dict:
    payload = {"sku": "SH-G", "component_type": "SHINGLE", "manufacturer": "GAF"}
    payload.update(overrides)
    return payload


def create_registration_payload(**overrides) -> dict:
    payload = {
        "homeowner_name": "Homeowner H",
        "property_postal_code": "30001",
        "install_date": "2026-09-10",
    }
    payload.update(overrides)
    return payload


def create_registration_component_payload(**overrides) -> dict:
    payload = {"catalog_sku": "SH-G", "material_cost_cents": 25000}
    payload.update(overrides)
    return payload


def create_claim_payload(**overrides) -> dict:
    payload = {"description": "claim", "claim_labor_cost_cents": 10000}
    payload.update(overrides)
    return payload


def create_evidence_payload(**overrides) -> dict:
    payload = {"evidence_type": "PHOTO", "note": "photo"}
    payload.update(overrides)
    return payload


def create_complaint_payload(**overrides) -> dict:
    payload = {"category": "WORKMANSHIP"}
    payload.update(overrides)
    return payload


def create_distributor_payload(**overrides) -> dict:
    payload = {"name": "Dist", "territory_codes": ["T1"], "lead_pool_total": 1}
    payload.update(overrides)
    return payload


def create_lead_assignment_payload(**overrides) -> dict:
    payload = {
        "territory_code": "T1",
        "required_tier": "BRONZE",
        "start_date": "2026-10-01",
        "end_date": "2026-11-01",
    }
    payload.update(overrides)
    return payload
