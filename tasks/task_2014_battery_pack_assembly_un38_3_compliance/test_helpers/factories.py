"""Payload factories — one per entity, input fields only.

Uniqueness counters keep codes distinct within a test (the server restarts
between tests, so counters only need to disambiguate intra-test creation).
"""
from itertools import count

from .constants import (
    DEFAULT_CELLS_REQUIRED,
    DEFAULT_RATED_CAPACITY_MAH,
    DEFAULT_RECEIVING_SOC,
    STANDARD_PASSING_MATRIX,
    STANDARD_WELD,
)

_program_seq = count(1)
_lot_seq = count(1)
_bom_seq = count(1)
_location_seq = count(1)
_recall_seq = count(1)
_fw_seq = count(1)


def _next(seq, prefix):
    return f"{prefix}-{next(seq)}"


def next_program_code() -> str:
    return _next(_program_seq, "PRG-T")


def next_lot_code() -> str:
    return _next(_lot_seq, "LOT-T")


def next_bom_code() -> str:
    return _next(_bom_seq, "BOM-T")


def next_location_code() -> str:
    return _next(_location_seq, "SL-T")


def next_recall_code() -> str:
    return _next(_recall_seq, "RC-T")


def next_binary_sha256() -> str:
    """64 lowercase hex characters, unique per call within a test run."""
    return f"{next(_fw_seq):064x}"


def create_program_payload(program_code=None, storage_capacity_wh=100000) -> dict:
    return {
        "program_code": program_code or next_program_code(),
        "storage_capacity_wh": storage_capacity_wh,
    }


def create_cell_lot_payload(lot_code=None, cell_count=100, rated_capacity_mah=DEFAULT_RATED_CAPACITY_MAH,
                            receiving_soc_percent=DEFAULT_RECEIVING_SOC) -> dict:
    return {
        "lot_code": lot_code or next_lot_code(),
        "cell_count": cell_count,
        "rated_capacity_mah": rated_capacity_mah,
        "receiving_soc_percent": receiving_soc_percent,
    }


def create_cell_inspection_payload(measured_soc_percent=DEFAULT_RECEIVING_SOC, measured_voltage_v=3.55,
                                   visual_defect_count=0, outcome="PASS") -> dict:
    return {
        "measured_soc_percent": measured_soc_percent,
        "measured_voltage_v": measured_voltage_v,
        "visual_defect_count": visual_defect_count,
        "outcome": outcome,
    }


def create_pack_bom_payload(cell_lot_id, bom_code=None, cells_required=DEFAULT_CELLS_REQUIRED,
                            series_count=2, parallel_count=2, welding_profile="WELD_PROFILE_A",
                            version_note=None) -> dict:
    payload = {
        "bom_code": bom_code or next_bom_code(),
        "cell_lot_id": cell_lot_id,
        "cells_required": cells_required,
        "series_count": series_count,
        "parallel_count": parallel_count,
        "welding_profile": welding_profile,
    }
    if version_note is not None:
        payload["version_note"] = version_note
    return payload


def create_battery_pack_payload(bom_id, expected_bom_version) -> dict:
    return {"bom_id": bom_id, "expected_bom_version": expected_bom_version}


def create_welding_record_payload(weld_profile_used="WELD_PROFILE_A", **overrides) -> dict:
    payload = dict(STANDARD_WELD)
    payload.update(overrides)
    payload["weld_profile_used"] = weld_profile_used
    return payload


def create_bms_firmware_payload(firmware_version="1.0.0", binary_sha256=None,
                                supports_soc_hysteresis=False) -> dict:
    return {
        "firmware_version": firmware_version,
        "binary_sha256": binary_sha256 or next_binary_sha256(),
        "supports_soc_hysteresis": supports_soc_hysteresis,
    }


def create_firmware_approval_payload(decision="APPROVE",
                                     rationale="Approved after full bench validation review.") -> dict:
    return {"decision": decision, "rationale": rationale}


def create_bms_flash_record_payload(bms_firmware_id) -> dict:
    return {"bms_firmware_id": bms_firmware_id}


def create_dossier_matrix_payload(expected_pack_version, **overrides) -> dict:
    """The eight-field T1..T8 test matrix plus the pack OCC guard."""
    payload = dict(STANDARD_PASSING_MATRIX)
    payload.update(overrides)
    payload["expected_pack_version"] = expected_pack_version
    return payload


def create_storage_location_payload(location_code=None, fire_zone="ZONE_A", capacity_wh=5000,
                                    accepts_soc_band=None) -> dict:
    return {
        "location_code": location_code or next_location_code(),
        "fire_zone": fire_zone,
        "capacity_wh": capacity_wh,
        "accepts_soc_band": list(accepts_soc_band) if accepts_soc_band is not None else ["SOC_LOW", "SOC_MID", "SOC_HIGH"],
    }


def create_storage_placement_payload(storage_location_id, battery_pack_id) -> dict:
    return {"storage_location_id": storage_location_id, "battery_pack_id": battery_pack_id}


def create_transport_shipment_payload(carrier_code="DHL-DG", un_class_code="UN3480",
                                      declared_weight_kg=10.00) -> dict:
    return {
        "carrier_code": carrier_code,
        "un_class_code": un_class_code,
        "declared_weight_kg": declared_weight_kg,
    }


def create_attach_pack_payload(battery_pack_id) -> dict:
    return {"battery_pack_id": battery_pack_id}


def create_return_authorization_payload(battery_pack_id, reason_code="DEFECT",
                                        target_soc_percent=25.0) -> dict:
    return {
        "battery_pack_id": battery_pack_id,
        "reason_code": reason_code,
        "target_soc_percent": target_soc_percent,
    }


def create_recall_campaign_payload(recall_code=None, severity="CLASS_II", scope_lot_id=None,
                                   scope_bom_id=None, scope_serial_prefix=None) -> dict:
    payload = {
        "recall_code": recall_code or next_recall_code(),
        "severity": severity,
    }
    if scope_lot_id is not None:
        payload["scope_lot_id"] = scope_lot_id
    if scope_bom_id is not None:
        payload["scope_bom_id"] = scope_bom_id
    if scope_serial_prefix is not None:
        payload["scope_serial_prefix"] = scope_serial_prefix
    return payload
