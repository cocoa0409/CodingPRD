"""Payload factories — one per creatable entity, input fields only.

Defaults are chosen to be valid against every PRD-stated constraint so tests
can override only the field under examination.
"""


def create_studio_payload(**overrides) -> dict:
    payload = {"name": "Studio One"}
    payload.update(overrides)
    return payload


def create_property_payload(studio_id: str, **overrides) -> dict:
    payload = {
        "studio_id": studio_id,
        "title": "Galaxy Racers",
        "category": "FILM",
        "reveal_date": "2026-09-01T00:00:00Z",
        "release_date": "2027-03-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_license_agreement_payload(property_id: str, **overrides) -> dict:
    payload = {
        "property_id": property_id,
        "territory": "GLOBAL",
        "royalty_rate_pct": 0.10,
        "advance_guarantee_cents": 0,
        "annual_minimum_guarantee_cents": 0,
        "start_date": "2026-01-01T00:00:00Z",
        "end_date": "2028-12-31T00:00:00Z",
        "approval_rights_required": False,
    }
    payload.update(overrides)
    return payload


def create_toy_line_payload(**overrides) -> dict:
    payload = {
        "name": "Evergreen Blocks",
        "brand_kind": "EVERGREEN",
        "target_street_date_input": "2027-01-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_sku_payload(toy_line_id: str, **overrides) -> dict:
    payload = {
        "toy_line_id": toy_line_id,
        "name": "Block Bucket",
        "age_grade_months": 36,
        "packaging_claims": ["BPA_FREE"],
        "moq_units": 1,
        "unit_cost_cents": 100,
        "tooling_cost_cents": 1000,
    }
    payload.update(overrides)
    return payload


def create_factory_payload(**overrides) -> dict:
    payload = {
        "name": "Shenzhen Plastics",
        "capacity_units_per_month": 1000,
        "tooling_lead_weeks": 4,
    }
    payload.update(overrides)
    return payload


def create_tooling_order_payload(toy_line_id: str, sku_id: str, factory_id: str, **overrides) -> dict:
    payload = {
        "toy_line_id": toy_line_id,
        "sku_id": sku_id,
        "factory_id": factory_id,
        "production_month": "2027-01",
        "units": 100,
    }
    payload.update(overrides)
    return payload


def create_retailer_payload(**overrides) -> dict:
    payload = {"name": "ToyBox Stores", "region": "NA"}
    payload.update(overrides)
    return payload


def create_line_review_payload(retailer_id: str, **overrides) -> dict:
    payload = {
        "retailer_id": retailer_id,
        "window_start": "2026-09-15T00:00:00Z",
        "window_end": "2026-11-15T00:00:00Z",
        "commitment_deadline": "2026-11-01T00:00:00Z",
        "shelf_slots_total": 20,
    }
    payload.update(overrides)
    return payload


def create_commitment_payload(line_review_id: str, sku_id: str, **overrides) -> dict:
    payload = {
        "line_review_id": line_review_id,
        "sku_id": sku_id,
        "committed_units": 100,
        "unit_price_cents": 500,
        "shelf_slots": 4,
    }
    payload.update(overrides)
    return payload


def create_shipment_payload(commitment_id: str, **overrides) -> dict:
    payload = {
        "commitment_id": commitment_id,
        "planned_ship_date": "2026-12-01T00:00:00Z",
        "units": 100,
    }
    payload.update(overrides)
    return payload


def create_safety_test_payload(sku_id: str, **overrides) -> dict:
    payload = {
        "sku_id": sku_id,
        "test_type": "MECHANICAL",
        "lab_name": "LabA",
        "claimed_age_grade_months": 36,
    }
    payload.update(overrides)
    return payload
