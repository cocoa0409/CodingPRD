"""Payload factories - one per resource, input fields only.

Monetary and decimal values are emitted as JSON numbers, never strings, and
every instant is a full ISO 8601 UTC instant with a trailing Z.
"""
import itertools

_seq = itertools.count(1)


def unique_suffix() -> str:
    return f"{next(_seq):04d}"


def market_requirement_payload(**overrides) -> dict:
    payload = {
        "market_code": "US",
        "required_languages": ["en"],
        "fiber_tolerance_pp": 3.0,
        "absolute_claim_tolerance_pp": 0.0,
        "min_durability_cycles": 20,
        "marking_duty_rate": 0.100,
        "requires_identity_disclosure": True,
        "requires_origin_statement": True,
    }
    payload.update(overrides)
    return payload


def brand_payload(**overrides) -> dict:
    payload = {
        "legal_name": "Acme Apparel Group",
        "party_type": "BRAND_OWNER",
        "rn_number": "RN12345",
        "licensor_brand_id": None,
        "responsibility_mode": "SELF_OF_RECORD",
    }
    payload.update(overrides)
    return payload


DEFAULT_FIBERS = [
    {"fiber_generic_name": "COTTON", "declared_pct": 60.0, "ornamentation_exempt": False},
    {"fiber_generic_name": "POLYESTER", "declared_pct": 40.0, "ornamentation_exempt": False},
]
# The printable string the DEFAULT_FIBERS declaration renders to.
DEFAULT_FIBER_TEXT = "60.0% COTTON, 40.0% POLYESTER"


def fiber_line(name, pct, ornamentation_exempt=False) -> dict:
    return {"fiber_generic_name": name, "declared_pct": pct,
            "ornamentation_exempt": ornamentation_exempt}


def style_payload(brand_id, **overrides) -> dict:
    payload = {
        "brand_id": brand_id,
        "style_code": f"ST-{unique_suffix()}",
        "product_class": "WOVEN_OUTERWEAR",
        "target_market_codes": ["US"],
        "net_weight_grams": 500.0,
        "declared_fibers": [dict(line) for line in DEFAULT_FIBERS],
    }
    payload.update(overrides)
    return payload


def material_input_payload(**overrides) -> dict:
    payload = {
        "stage": "YARN",
        "country_code": "US",
        "value_added_usd": 100.00,
        "weight_grams": 400.0,
        "is_ornamentation": False,
        "parent_input_id": None,
    }
    payload.update(overrides)
    return payload


def fiber_test_payload(style_id, **overrides) -> dict:
    payload = {
        "style_id": style_id,
        "test_type": "FIBER_CONTENT",
        "lab_code": "LAB-1",
        "method": "AATCC_20A",
        "specimen_received_at": "2026-08-01T09:00:00Z",
        "results_due_at": "2026-08-02T09:00:00Z",
        "wash_temp_c": None,
    }
    payload.update(overrides)
    return payload


def care_test_payload(style_id, **overrides) -> dict:
    payload = {
        "style_id": style_id,
        "test_type": "CARE_PERFORMANCE",
        "lab_code": "LAB-2",
        "method": "AATCC_135",
        "specimen_received_at": "2026-08-01T09:00:00Z",
        "results_due_at": "2026-08-02T09:00:00Z",
        "wash_temp_c": 40,
    }
    payload.update(overrides)
    return payload


def fiber_results_payload(**overrides) -> dict:
    payload = {
        "measured_fibers": [
            {"fiber_generic_name": "COTTON", "measured_pct": 60.0},
            {"fiber_generic_name": "POLYESTER", "measured_pct": 40.0},
        ],
    }
    payload.update(overrides)
    return payload


def care_results_payload(**overrides) -> dict:
    payload = {
        "cycles_run": 10,
        "dimensional_change_pct": 1.0,
        "colorfastness_grade": 4.5,
        "legibility_cycles": 60,
    }
    payload.update(overrides)
    return payload


def retest_payload(**overrides) -> dict:
    payload = {
        "specimen_received_at": "2026-08-05T09:00:00Z",
        "results_due_at": "2026-08-06T09:00:00Z",
    }
    payload.update(overrides)
    return payload


def permanent_label_payload(style_id, origin_determination_id, care_test_id,
                           **overrides) -> dict:
    payload = {
        "style_id": style_id,
        "market_codes": ["US"],
        "languages": ["en"],
        "placement_code": "NECK_CENTER_INSIDE",
        "durability_cycles_rating": 60,
        "wash_temp_c": 40,
        "bleach_code": "NO_BLEACH",
        "dry_code": "TUMBLE_LOW",
        "iron_code": "IRON_LOW",
        "dryclean_code": "DO_NOT_DRYCLEAN",
        "identity_display_mode": "RN",
        "fiber_content_text": DEFAULT_FIBER_TEXT,
        "origin_text": "Made in US",
        "origin_determination_id": origin_determination_id,
        "care_test_id": care_test_id,
    }
    payload.update(overrides)
    return payload


def hangtag_payload(expected_parent_label_spec_version, **overrides) -> dict:
    payload = {
        "market_codes": ["US"],
        "languages": ["en"],
        "marketing_claims": [],
        "fiber_content_text": DEFAULT_FIBER_TEXT,
        "origin_text": "Made in US",
        "expected_parent_label_spec_version": expected_parent_label_spec_version,
    }
    payload.update(overrides)
    return payload


def import_shipment_payload(importer_brand_id, style_id, **overrides) -> dict:
    payload = {
        "importer_brand_id": importer_brand_id,
        "style_id": style_id,
        "entry_number": f"ENT-{unique_suffix()}",
        "quantity_units": 1000,
        "declared_value_usd": 20000.00,
        "entry_market_code": "US",
    }
    payload.update(overrides)
    return payload


def marking_review_payload(**overrides) -> dict:
    payload = {"outcome": "DEFICIENT", "deficiency_code": "MISSING_ORIGIN"}
    payload.update(overrides)
    return payload


def compliance_audit_payload(brand_id, **overrides) -> dict:
    payload = {
        "brand_id": brand_id,
        "scope": "STYLE_DOSSIER",
        "audit_window_from": "2026-01-01T00:00:00Z",
        "audit_window_to": "2026-12-31T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def audit_finding_payload(style_id, **overrides) -> dict:
    payload = {
        "style_id": style_id,
        "finding_code": "FIBER_CONTENT_MISSTATED",
        "units_affected": 100,
    }
    payload.update(overrides)
    return payload


def disposition_payload(units_relabeled, units_destroyed, units_released,
                        corrective_label_spec_id=None) -> dict:
    payload = {
        "units_relabeled": units_relabeled,
        "units_destroyed": units_destroyed,
        "units_released": units_released,
    }
    if corrective_label_spec_id is not None:
        payload["corrective_label_spec_id"] = corrective_label_spec_id
    return payload
