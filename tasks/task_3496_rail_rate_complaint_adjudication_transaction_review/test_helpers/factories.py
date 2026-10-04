"""Payload factories — one per entity, input fields only (PRD §3)."""
from .constants import FINDING_2025_SINGLE, SHIPPER_ADA


def create_carrier_payload(**overrides) -> dict:
    defaults = {
        "carrier_code": "OKTX",
        "legal_name": "Oklahoma & Texas Railway",
        "carrier_class": "I",
        "base_route_miles": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_finding_payload(**overrides) -> dict:
    defaults = dict(FINDING_2025_SINGLE)
    defaults.update(overrides)
    return defaults


def create_rate_complaint_payload(**overrides) -> dict:
    defaults = {
        "shipper_id": SHIPPER_ADA,
        "carrier_id": None,
        "commodity": "GRAIN",
        "challenged_rate_cents_per_ton": 19500,
        "alleged_variable_cost_cents_per_ton": 10000,
        "annual_tons": 1000,
        "relief_sought_cents": 400000001,
        "contested_fiscal_year": 2025,
    }
    defaults.update(overrides)
    return defaults


def determine_market_dominance_payload(**overrides) -> dict:
    defaults = {
        "product_competition_exists": False,
        "geographic_competition_exists": False,
    }
    defaults.update(overrides)
    return defaults


def create_evidence_payload(**overrides) -> dict:
    defaults = {
        "submission_type": "SAC_STUDY",
        "submitted_by_party": "SHIPPER",
        "reference_rate_cents_per_ton": 11200,
        "verified_variable_cost_cents_per_ton": 10500,
    }
    defaults.update(overrides)
    return defaults


def verify_evidence_payload(review_outcome="VERIFIED") -> dict:
    return {"review_outcome": review_outcome}


def decide_rate_complaint_payload(outcome="UPHELD", shipments=None) -> dict:
    payload = {"outcome": outcome}
    if shipments is not None:
        payload["shipments"] = shipments
    return payload


def reparation_event_payload(event_type="PAYMENT", amount_cents=None) -> dict:
    payload = {"event_type": event_type}
    if amount_cents is not None:
        payload["amount_cents"] = amount_cents
    return payload


def create_service_complaint_payload(**overrides) -> dict:
    defaults = {
        "shipper_id": "shp-gal",
        "carrier_id": None,
        "issue_type": "DELAY",
        "territory_code": "GULF-COAST",
    }
    defaults.update(overrides)
    return defaults


def escalate_payload(**overrides) -> dict:
    defaults = {"directive": "Restore service within 72 hours"}
    defaults.update(overrides)
    return defaults


def create_merger_application_payload(**overrides) -> dict:
    defaults = {
        "acquiring_carrier_id": None,
        "target_carrier_id": None,
        "transaction_value_cents": 900000000,
        "competition_preservation_score": 80,
        "service_reliability_score": 70,
        "shipper_impact_score": 60,
    }
    defaults.update(overrides)
    return defaults


def amend_merger_payload(expected_version, **overrides) -> dict:
    payload = {"expected_merger_application_version": expected_version}
    payload.update(overrides)
    return payload


def decide_merger_payload(outcome, conditions=None) -> dict:
    payload = {"outcome": outcome}
    if conditions is not None:
        payload["conditions"] = conditions
    return payload


def create_service_assurance_plan_payload(**overrides) -> dict:
    defaults = {
        "plan_name": "Service Assurance Plan",
        "commitments": ["Weekly service metrics to the Board"],
    }
    defaults.update(overrides)
    return defaults


def create_abandonment_payload(**overrides) -> dict:
    defaults = {
        "carrier_id": None,
        "line_segment_ref": "MP 100.0-MP 120.0",
        "segment_miles": 20,
    }
    defaults.update(overrides)
    return defaults


def decide_abandonment_payload(outcome="GRANTED", finding="SERVED") -> dict:
    return {"outcome": outcome, "public_convenience_finding": finding}


def create_petition_payload(**overrides) -> dict:
    defaults = {
        "shipper_id": "shp-gal",
        "incumbent_carrier_id": None,
        "interchange_code": "IX-KC",
        "facility_distance_miles": 10,
        "evidence_service_complaint_id": None,
        "service_start_date": "2026-10-01",
        "service_end_date": "2026-12-01",
    }
    defaults.update(overrides)
    return defaults
