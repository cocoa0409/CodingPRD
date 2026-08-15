"""Payload factories — one per entity, input fields only (PRD §3/§4)."""

DEFAULTS = {
    "AWS_REVISION": "D1.1:2025",
    "PROCESS": "SMAW",
    "BASE_METAL_SPEC": "A36",
    "PQR_THICKNESS_MIN_MM": 3.0,
    "PQR_THICKNESS_MAX_MM": 25.0,
    "WPS_THICKNESS_MIN_MM": 5.0,
    "WPS_THICKNESS_MAX_MM": 20.0,
    "JOINT_THICKNESS_MM": 10.0,
    "OVEN_TEMP_C": 150,
    "OVEN_CAPACITY_KG": 500,
    "LOT_RECEIVED_KG": 100.0,
    "ISSUED_KG": 50.0,
    "PASS_USED_KG": 1.0,
    "FIXTURE_CAPACITY": 4,
    "PROMISED_SHIP_DATE": "2026-12-01T00:00:00Z",
    "QUALIFIED_AT_UTC": "2026-08-01T00:00:00Z",
    "VT_START": "2026-08-02T09:00:00Z",
    "VT_END": "2026-08-02T09:30:00Z",
}


def create_shop_payload(**overrides) -> dict:
    defaults = {
        "shop_name": "Test Shop",
        "aws_d1_1_revision": DEFAULTS["AWS_REVISION"],
    }
    defaults.update(overrides)
    return defaults


def create_welder_payload(**overrides) -> dict:
    defaults = {"stencil": "W-1", "full_name": "Welder One"}
    defaults.update(overrides)
    return defaults


def create_ndt_vendor_payload(**overrides) -> dict:
    defaults = {
        "vendor_name": "NDT Vendor One",
        "supported_methods": ["UT"],
        "hourly_capacity": 1,
    }
    defaults.update(overrides)
    return defaults


def create_oven_payload(**overrides) -> dict:
    defaults = {
        "oven_code": "OV-1",
        "holding_temp_c": DEFAULTS["OVEN_TEMP_C"],
        "capacity_electrodes_kg": DEFAULTS["OVEN_CAPACITY_KG"],
    }
    defaults.update(overrides)
    return defaults


def create_pqr_payload(**overrides) -> dict:
    defaults = {
        "pqr_number": "PQR-1",
        "process": DEFAULTS["PROCESS"],
        "base_metal_spec": DEFAULTS["BASE_METAL_SPEC"],
        "thickness_range_min_mm": DEFAULTS["PQR_THICKNESS_MIN_MM"],
        "thickness_range_max_mm": DEFAULTS["PQR_THICKNESS_MAX_MM"],
        "test_report_id": "TR-1",
    }
    defaults.update(overrides)
    return defaults


def create_wps_payload(pqr_id, **overrides) -> dict:
    defaults = {
        "wps_number": "WPS-1",
        "revision": 1,
        "pqr_id": pqr_id,
        "process": DEFAULTS["PROCESS"],
        "base_metal_spec": DEFAULTS["BASE_METAL_SPEC"],
        "thickness_min_mm": DEFAULTS["WPS_THICKNESS_MIN_MM"],
        "thickness_max_mm": DEFAULTS["WPS_THICKNESS_MAX_MM"],
    }
    defaults.update(overrides)
    return defaults


def create_qualification_payload(welder_id, wps_id, **overrides) -> dict:
    defaults = {
        "welder_id": welder_id,
        "wps_id": wps_id,
        "process": DEFAULTS["PROCESS"],
        "qualified_at_utc": DEFAULTS["QUALIFIED_AT_UTC"],
    }
    defaults.update(overrides)
    return defaults


def create_consumable_lot_payload(oven_id, **overrides) -> dict:
    defaults = {
        "lot_number": "LOT-1",
        "filler_spec": "E7018",
        "process": DEFAULTS["PROCESS"],
        "received_kg": DEFAULTS["LOT_RECEIVED_KG"],
        "oven_id": oven_id,
    }
    defaults.update(overrides)
    return defaults


def create_consumable_issue_payload(lot_id, oven_id, welder_id,
                                    **overrides) -> dict:
    defaults = {
        "lot_id": lot_id,
        "oven_id": oven_id,
        "issued_to_welder_id": welder_id,
        "issued_kg": DEFAULTS["ISSUED_KG"],
    }
    defaults.update(overrides)
    return defaults


def create_fixture_payload(**overrides) -> dict:
    defaults = {
        "fixture_code": "FIX-1",
        "capacity_weldments": DEFAULTS["FIXTURE_CAPACITY"],
        "owner_party": "SHOP",
    }
    defaults.update(overrides)
    return defaults


def create_shop_order_payload(**overrides) -> dict:
    defaults = {
        "po_number": "PO-1",
        "customer_name": "Customer One",
        "promised_ship_date_utc": DEFAULTS["PROMISED_SHIP_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_weldment_payload(fixture_id, **overrides) -> dict:
    defaults = {
        "weldment_serial": "WM-1",
        "fixture_id": fixture_id,
        "drawing_revision": "R1",
    }
    defaults.update(overrides)
    return defaults


def create_joint_payload(wps_id, **overrides) -> dict:
    defaults = {
        "joint_number": "J-1",
        "wps_id": wps_id,
        "base_metal_thickness_mm": DEFAULTS["JOINT_THICKNESS_MM"],
        "required_ndt_methods": ["VT"],
    }
    defaults.update(overrides)
    return defaults


def create_weld_pass_payload(welder_id, qualification_id, lot_id,
                             **overrides) -> dict:
    defaults = {
        "welder_id": welder_id,
        "qualification_id": qualification_id,
        "consumable_lot_id": lot_id,
        "consumable_used_kg": DEFAULTS["PASS_USED_KG"],
        "is_repair": False,
    }
    defaults.update(overrides)
    return defaults


def create_distortion_report_payload(joint_id, **overrides) -> dict:
    defaults = {
        "joint_id": joint_id,
        "measured_deviation_mm": 5.0,
        "tolerance_mm": 2.0,
    }
    defaults.update(overrides)
    return defaults


def create_vt_inspection_payload(**overrides) -> dict:
    """VT is in-house: vendor_id stays null; result may ride along (PRD §3.6)."""
    defaults = {
        "method": "VT",
        "scheduled_start_utc": DEFAULTS["VT_START"],
        "scheduled_end_utc": DEFAULTS["VT_END"],
        "result": "PASS",
        "result_code": "OK",
    }
    defaults.update(overrides)
    return defaults


def create_ndt_inspection_payload(vendor_id, method="UT", **overrides) -> dict:
    defaults = {
        "method": method,
        "scheduled_start_utc": "2026-08-03T09:00:00Z",
        "scheduled_end_utc": "2026-08-03T10:00:00Z",
        "vendor_id": vendor_id,
    }
    defaults.update(overrides)
    return defaults


def record_result_payload(result="PASS", result_code="OK", **overrides) -> dict:
    defaults = {"result": result, "result_code": result_code}
    defaults.update(overrides)
    return defaults


def create_traveler_sign_off_payload(step_code, **overrides) -> dict:
    defaults = {"step_code": step_code}
    defaults.update(overrides)
    return defaults
