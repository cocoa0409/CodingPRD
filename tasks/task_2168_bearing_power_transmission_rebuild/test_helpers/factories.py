"""Payload factories - one per entity, client-supplied input fields only."""
from .constants import FOUR_BANDS, ONE_BAND, TEST_DEFAULTS


def customer_payload(**overrides) -> dict:
    payload = {"name": "Northgate Mill", "account_code": "NGM-001"}
    payload.update(overrides)
    return payload


def asset_payload(**overrides) -> dict:
    payload = {
        "asset_tag": "CONV-04-GBX",
        "criticality": "STANDARD",
        "duty_class": "CONTINUOUS",
    }
    payload.update(overrides)
    return payload


def clearance_standard_payload(**overrides) -> dict:
    payload = {
        "model_code": TEST_DEFAULTS["MODEL_CODE"],
        "base_core_value_cents": TEST_DEFAULTS["BASE_CORE_VALUE_CENTS"],
        "max_rebuild_count": TEST_DEFAULTS["MAX_REBUILD_COUNT"],
        "warranty_hours": TEST_DEFAULTS["WARRANTY_HOURS"],
        "warranty_months": TEST_DEFAULTS["WARRANTY_MONTHS"],
        "cleanroom_required": False,
        "required_feature_codes": ["BORE"],
        "feature_bands": ONE_BAND,
    }
    payload.update(overrides)
    return payload


def four_band_standard_payload(**overrides) -> dict:
    payload = clearance_standard_payload(feature_bands=FOUR_BANDS)
    payload.update(overrides)
    return payload


def bench_payload(**overrides) -> dict:
    payload = {"bench_code": "B-1", "parallel_slots": 1, "cleanroom": False}
    payload.update(overrides)
    return payload


def core_unit_payload(customer_id, clearance_standard_id, **overrides) -> dict:
    payload = {
        "customer_id": customer_id,
        "clearance_standard_id": clearance_standard_id,
        "serial_no": "SN-77001",
        "rebuild_count": 0,
        "declared_condition_grade": "GRADE_B",
    }
    payload.update(overrides)
    return payload


def rebuild_order_payload(customer_id, core_unit_id, customer_asset_id, **overrides) -> dict:
    payload = {
        "customer_id": customer_id,
        "core_unit_id": core_unit_id,
        "customer_asset_id": customer_asset_id,
        "labor_hours": TEST_DEFAULTS["LABOR_HOURS"],
    }
    payload.update(overrides)
    return payload


def part_line_payload(expected_order_version, **overrides) -> dict:
    payload = {
        "part_no": TEST_DEFAULTS["OEM_PART_NO"],
        "source_class": "OEM",
        "qty": TEST_DEFAULTS["OEM_QTY"],
        "unit_cost_cents": TEST_DEFAULTS["OEM_UNIT_COST_CENTS"],
        "expected_order_version": expected_order_version,
    }
    payload.update(overrides)
    return payload


def vibration_reading_payload(customer_asset_id, **overrides) -> dict:
    payload = {
        "customer_asset_id": customer_asset_id,
        "reading_at": "2026-08-02T06:00:00Z",
        "overall_velocity_mm_s": 2.10,
        "bpfo_amplitude_g": 0.30,
        "bpfi_amplitude_g": 0.25,
        "baseline_amplitude_g": 0.20,
    }
    payload.update(overrides)
    return payload


def inspection_payload(rebuild_order_id, **overrides) -> dict:
    payload = {"rebuild_order_id": rebuild_order_id}
    payload.update(overrides)
    return payload


def measurement_payload(feature_code, measured_um, **overrides) -> dict:
    payload = {"feature_code": feature_code, "measured_um": measured_um}
    payload.update(overrides)
    return payload


def bench_reservation_payload(rebuild_order_id, bench_id, window_start_at,
                              window_end_at, **overrides) -> dict:
    payload = {
        "rebuild_order_id": rebuild_order_id,
        "bench_id": bench_id,
        "window_start_at": window_start_at,
        "window_end_at": window_end_at,
    }
    payload.update(overrides)
    return payload


def installation_payload(core_unit_id, customer_asset_id, rebuild_order_id,
                         expected_asset_version, **overrides) -> dict:
    payload = {
        "core_unit_id": core_unit_id,
        "customer_asset_id": customer_asset_id,
        "rebuild_order_id": rebuild_order_id,
        "expected_asset_version": expected_asset_version,
    }
    payload.update(overrides)
    return payload


def warranty_claim_payload(installation_id, **overrides) -> dict:
    payload = {"installation_id": installation_id, "claimed_reason": "seized bearing"}
    payload.update(overrides)
    return payload


def manual_credit_note_payload(amount_cents, expected_customer_version, **overrides) -> dict:
    payload = {
        "amount_cents": amount_cents,
        "memo": "goodwill freight credit",
        "expected_customer_version": expected_customer_version,
    }
    payload.update(overrides)
    return payload
