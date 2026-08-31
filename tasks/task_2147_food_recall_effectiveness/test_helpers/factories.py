"""Payload factories — one per resource, client-supplied input fields only."""

DEFAULTS = {
    "FIRM_NAME": "Northvale Foods",
    "REGISTRATION_NUMBER": "FFR-10021",
    "PRODUCT_DESCRIPTION": "Frozen spinach 1kg",
    "LOT_CODE": "L-88A",
    "CONSIGNEE_NAME": "Metro Distributors",
    "FACILITY_NAME": "Ridgeline Incineration",
    "SHIP_DATE": "2026-08-20T00:00:00Z",
}


def create_firm_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["FIRM_NAME"],
        "registration_number": DEFAULTS["REGISTRATION_NUMBER"],
    }
    payload.update(overrides)
    return payload


def create_recall_payload(firm_id, **overrides) -> dict:
    payload = {
        "firm_id": firm_id,
        "product_description": DEFAULTS["PRODUCT_DESCRIPTION"],
        "agency": "FDA",
        "initiation_type": "FIRM_INITIATED",
        "lot_codes": [DEFAULTS["LOT_CODE"]],
    }
    payload.update(overrides)
    return payload


def create_hazard_evaluation_payload(expected_recall_version, **overrides) -> dict:
    payload = {
        "probability_of_adverse_health": "HIGH",
        "severity_tier": 4,
        "exposure_population": 60000,
        "vulnerable_population": True,
        "evidence_strength": "CONFIRMED",
        "expected_recall_version": expected_recall_version,
    }
    payload.update(overrides)
    return payload


def create_consignee_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["CONSIGNEE_NAME"],
        "consignee_type": "DISTRIBUTOR",
    }
    payload.update(overrides)
    return payload


def create_distribution_record_payload(consignee_id, quantity_shipped, **overrides) -> dict:
    payload = {
        "consignee_id": consignee_id,
        "lot_code": DEFAULTS["LOT_CODE"],
        "quantity_shipped": quantity_shipped,
        "ship_date": DEFAULTS["SHIP_DATE"],
    }
    payload.update(overrides)
    return payload


def create_notification_payload(consignee_id, expected_consignee_version, **overrides) -> dict:
    payload = {
        "consignee_id": consignee_id,
        "method": "EMAIL",
        "expected_consignee_version": expected_consignee_version,
    }
    payload.update(overrides)
    return payload


def create_retrieval_receipt_payload(consignee_id, **overrides) -> dict:
    payload = {
        "consignee_id": consignee_id,
        "quantity_returned": 0,
        "quantity_destroyed_onsite": 0,
        "quantity_held_segregated": 0,
        "quantity_unrecoverable": 0,
    }
    payload.update(overrides)
    return payload


def create_public_warning_payload(**overrides) -> dict:
    payload = {
        "warning_type": "PRESS_RELEASE",
        "headline": "Do not eat lot L-88A",
        "body": "Listeria monocytogenes contamination confirmed.",
    }
    payload.update(overrides)
    return payload


def create_disposition_order_payload(quantity, **overrides) -> dict:
    payload = {
        "method": "DESTROY",
        "quantity": quantity,
        "facility_name": DEFAULTS["FACILITY_NAME"],
    }
    payload.update(overrides)
    return payload


def create_status_report_payload(period_start, period_end, **overrides) -> dict:
    payload = {
        "report_kind": "INTERIM",
        "period_start": period_start,
        "period_end": period_end,
    }
    payload.update(overrides)
    return payload


def create_cost_entry_payload(category, amount_cents, **overrides) -> dict:
    payload = {
        "category": category,
        "amount_cents": amount_cents,
        "description": "Recall cost line",
    }
    payload.update(overrides)
    return payload


def create_insurance_claim_payload(**overrides) -> dict:
    payload = {"claim_reference": "CLM-2026-0001"}
    payload.update(overrides)
    return payload
