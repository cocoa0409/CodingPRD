"""Payload factories — one per write endpoint, input fields only.

Every monetary and percentage value is emitted as a JSON **number**, never a string,
and every instant is emitted as a full ISO 8601 UTC instant with three fractional digits.
"""
from .constants import TEST_DEFAULTS


def create_project_payload(**overrides) -> dict:
    payload = {
        "name": TEST_DEFAULTS["PROJECT_NAME"],
        "contract_number": TEST_DEFAULTS["CONTRACT_NUMBER"],
        "owner_name": TEST_DEFAULTS["OWNER_NAME"],
        "schedule_data_date": TEST_DEFAULTS["SCHEDULE_DATA_DATE"],
        "escalation_contingency_budget": TEST_DEFAULTS["CONTINGENCY_BUDGET"],
    }
    payload.update(overrides)
    return payload


def create_material_package_payload(project_id=None, **overrides) -> dict:
    payload = {
        "project_id": project_id,
        "scope_code": TEST_DEFAULTS["SCOPE_CODE"],
        "description": TEST_DEFAULTS["PACKAGE_DESCRIPTION"],
        "commodity_index_code": TEST_DEFAULTS["COMMODITY_INDEX_CODE"],
        "estimated_cost": TEST_DEFAULTS["ESTIMATED_COST"],
        "required_onsite_date": TEST_DEFAULTS["REQUIRED_ONSITE_DATE"],
        "fabrication_duration_days": TEST_DEFAULTS["FABRICATION_DURATION_DAYS"],
        "delivery_transit_days": TEST_DEFAULTS["DELIVERY_TRANSIT_DAYS"],
        "submittal_review_days": TEST_DEFAULTS["SUBMITTAL_REVIEW_DAYS"],
    }
    payload.update(overrides)
    return payload


def create_supplier_payload(**overrides) -> dict:
    payload = {
        "legal_name": TEST_DEFAULTS["SUPPLIER_NAME"],
        "country_of_origin": TEST_DEFAULTS["COUNTRY_OF_ORIGIN"],
        "declared_tariff_rate_pct": TEST_DEFAULTS["DECLARED_TARIFF_RATE_PCT"],
    }
    payload.update(overrides)
    return payload


def suspend_supplier_payload(**overrides) -> dict:
    payload = {"reason": "Mill placed in receivership pending restructuring"}
    payload.update(overrides)
    return payload


def create_disruption_event_payload(**overrides) -> dict:
    payload = {
        "event_type": "TARIFF_IMPOSED",
        "effective_date": "2026-07-15T00:00:00.000Z",
        "description": "Section 232 tariff action against imported mill product",
        "tariff_rate_pct": 25.00,
    }
    payload.update(overrides)
    return payload


def create_quote_payload(material_package_id=None, supplier_id=None, **overrides) -> dict:
    payload = {
        "material_package_id": material_package_id,
        "supplier_id": supplier_id,
        "base_price": TEST_DEFAULTS["BASE_PRICE"],
        "received_at": TEST_DEFAULTS["RECEIVED_AT"],
        "price_hold_days": TEST_DEFAULTS["PRICE_HOLD_DAYS"],
    }
    payload.update(overrides)
    return payload


def revise_quote_payload(**overrides) -> dict:
    payload = {
        "base_price": 1175000.00,
        "received_at": TEST_DEFAULTS["RECEIVED_AT"],
        "price_hold_days": TEST_DEFAULTS["PRICE_HOLD_DAYS"],
    }
    payload.update(overrides)
    return payload


def create_index_reading_payload(**overrides) -> dict:
    payload = {
        "index_code": TEST_DEFAULTS["COMMODITY_INDEX_CODE"],
        "period": "2026-07",
        "value": 310.00,
        "published_at": "2026-07-15T00:00:00.000Z",
    }
    payload.update(overrides)
    return payload


def create_escalation_agreement_payload(quote_id=None, **overrides) -> dict:
    payload = {
        "quote_id": quote_id,
        "index_code": TEST_DEFAULTS["COMMODITY_INDEX_CODE"],
        "baseline_index_period": "2026-07",
        "cap_pct": TEST_DEFAULTS["CAP_PCT"],
        "contractor_share_pct": TEST_DEFAULTS["CONTRACTOR_SHARE_PCT"],
        "price_hold_through": TEST_DEFAULTS["PRICE_HOLD_THROUGH"],
        "deadband_pct": TEST_DEFAULTS["DEADBAND_PCT"],
        "proposed_terms_note": TEST_DEFAULTS["PROPOSED_TERMS_NOTE"],
    }
    payload.update(overrides)
    return payload


def propose_escalation_agreement_payload(**overrides) -> dict:
    payload = {}
    payload.update(overrides)
    return payload


def counter_escalation_agreement_payload(**overrides) -> dict:
    payload = {
        "cap_pct": 12.0,
        "contractor_share_pct": 30.0,
    }
    payload.update(overrides)
    return payload


def create_purchase_commitment_payload(
    quote_id=None, expected_project_version=None, **overrides
) -> dict:
    payload = {
        "quote_id": quote_id,
        "po_number": TEST_DEFAULTS["PO_NUMBER"],
        "expected_project_version": expected_project_version,
    }
    payload.update(overrides)
    return payload


def delivery_posture_payload(to_posture, **overrides) -> dict:
    payload = {"to_posture": to_posture}
    payload.update(overrides)
    return payload


def cancel_commitment_payload(**overrides) -> dict:
    payload = {"cancellation_reason": "Owner deferred the scope to a later phase"}
    payload.update(overrides)
    return payload


def create_storage_arrangement_payload(purchase_commitment_id=None, **overrides) -> dict:
    payload = {
        "purchase_commitment_id": purchase_commitment_id,
        "warehouse_name": TEST_DEFAULTS["WAREHOUSE_NAME"],
        "warehouse_address": TEST_DEFAULTS["WAREHOUSE_ADDRESS"],
        "stored_value": 862500.00,
        "monthly_storage_rate_pct": TEST_DEFAULTS["MONTHLY_STORAGE_RATE_PCT"],
        "stored_from": "2026-09-20T00:00:00.000Z",
        "planned_release_date": "2026-12-31T00:00:00.000Z",
    }
    payload.update(overrides)
    return payload


def create_storage_document_payload(**overrides) -> dict:
    payload = {
        "doc_type": "BAILMENT_AGREEMENT",
        "reference_number": "BAIL-2996-0001",
        "effective_date": "2026-09-01T00:00:00.000Z",
        "expires_at": "2027-09-01T00:00:00.000Z",
        "coverage_amount": 0.00,
        "verified": True,
    }
    payload.update(overrides)
    return payload


def revoke_storage_document_payload(**overrides) -> dict:
    payload = {"revocation_reason": "Policy cancelled by the carrier for non-payment"}
    payload.update(overrides)
    return payload


def create_substitution_request_payload(
    material_package_id=None, proposed_supplier_id=None, **overrides
) -> dict:
    payload = {
        "material_package_id": material_package_id,
        "proposed_supplier_id": proposed_supplier_id,
        "driver": "VALUE_ENGINEERING",
        "proposed_product": TEST_DEFAULTS["SUBSTITUTION_PRODUCT"],
        "cost_delta": 0.00,
        "schedule_delta_days": 0,
    }
    payload.update(overrides)
    return payload


def disposition_substitution_payload(disposition, **overrides) -> dict:
    payload = {"disposition": disposition}
    payload.update(overrides)
    return payload


def resubmit_substitution_payload(**overrides) -> dict:
    payload = {
        "proposed_product": "Revised alternate plate assembly with mill certification",
        "cost_delta": 0.00,
        "schedule_delta_days": 0,
    }
    payload.update(overrides)
    return payload


def rescind_substitution_payload(**overrides) -> dict:
    payload = {"rescission_reason": "Engineer of record withdrew the alternate approval"}
    payload.update(overrides)
    return payload


def create_change_order_request_payload(purchase_commitment_id=None, **overrides) -> dict:
    payload = {
        "purchase_commitment_id": purchase_commitment_id,
        "claimed_amount": 60000.00,
        "narrative": TEST_DEFAULTS["CHANGE_ORDER_NARRATIVE"],
    }
    payload.update(overrides)
    return payload


def disposition_change_order_payload(disposition, **overrides) -> dict:
    payload = {"disposition": disposition}
    payload.update(overrides)
    return payload


def set_clock_payload(to_iso8601, **overrides) -> dict:
    payload = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload
