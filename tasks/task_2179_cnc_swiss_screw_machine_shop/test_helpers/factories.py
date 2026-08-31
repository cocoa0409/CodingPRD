"""Payload factories - one per resource, input fields only."""

from .constants import SCENARIO

# In-spec five-reading subgroups reused across the suite.
MEASUREMENTS_AT_CPK_MIN = [6.343, 6.35, 6.35, 6.35, 6.357]
MEASUREMENTS_TIGHTER = [6.344, 6.35, 6.35, 6.35, 6.356]
MEASUREMENTS_BELOW_CPK_MIN = [6.343, 6.35, 6.35, 6.349, 6.358]
MEASUREMENTS_SHIFTED_HIGH = [6.366, 6.368, 6.368, 6.368, 6.37]


def clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}


def create_operator_payload(**overrides) -> dict:
    payload = {
        "name": "Rey Molina",
        "badge_code": "BM-01",
        "certifications": ["SWISS_SETUP", "LIGHTS_OUT"],
    }
    payload.update(overrides)
    return payload


def create_machine_payload(**overrides) -> dict:
    payload = {
        "asset_tag": "SW-01",
        "max_bar_diameter_mm": 20.0,
        "lights_out_certified": True,
    }
    payload.update(overrides)
    return payload


def create_part_payload(**overrides) -> dict:
    """The 12.7 mm 303SS part P-4471 that most scenarios quote and run."""
    payload = {
        "part_number": "P-4471",
        "alloy_code": "303SS",
        "bar_diameter_mm": 12.7,
        "cut_off_length_mm": 26.5,
        "cycle_time_sec": 42,
        "setup_hours": 3.5,
        "material_cost_cents_per_meter": 1850,
        "finished_mass_g": 18.3,
        "lights_out_eligible": True,
        "secondary_required": True,
        "secondary_minutes_per_piece": 0.4,
    }
    payload.update(overrides)
    return payload


def create_second_part_payload(**overrides) -> dict:
    """The 16.0 mm C360 part P-8802 used for changeover and alloy scenarios."""
    payload = {
        "part_number": "P-8802",
        "alloy_code": "C360",
        "bar_diameter_mm": 16.0,
        "cut_off_length_mm": 32.0,
        "cycle_time_sec": 55,
        "setup_hours": 2.0,
        "material_cost_cents_per_meter": 2600,
        "finished_mass_g": 36.01,
        "lights_out_eligible": False,
        "secondary_required": False,
        "secondary_minutes_per_piece": 0,
    }
    payload.update(overrides)
    return payload


def create_characteristic_payload(part_id: str, **overrides) -> dict:
    payload = {
        "part_id": part_id,
        "char_code": "OD-A",
        "nominal": 6.35,
        "usl": 6.375,
        "lsl": 6.325,
        "sample_freq_pieces": 200,
        "required_gauge_type": "MICROMETER",
        "cpk_min": 1.385,
        "subgroup_size": 5,
    }
    payload.update(overrides)
    return payload


def create_gauge_payload(**overrides) -> dict:
    payload = {
        "gauge_code": "MIC-207",
        "gauge_type": "MICROMETER",
        "calibrated_at": "2026-08-15T00:00:00Z",
        "calibration_due_at": "2027-02-15T00:00:00Z",
        "grr_pct": 6.2,
    }
    payload.update(overrides)
    return payload


def calibration_payload(**overrides) -> dict:
    payload = {
        "calibrated_at": "2026-09-01T08:00:00Z",
        "calibration_due_at": "2027-03-01T00:00:00Z",
        "grr_pct": 6.2,
    }
    payload.update(overrides)
    return payload


def create_bar_stock_lot_payload(**overrides) -> dict:
    payload = {
        "heat_number": "H-88231",
        "alloy_code": "303SS",
        "bar_diameter_mm": 12.7,
        "bar_length_mm": 3600,
        "bars_received": 20,
        "mass_kg_per_meter": 0.995,
        "feeder_slots": 1,
    }
    payload.update(overrides)
    return payload


def create_second_bar_stock_lot_payload(**overrides) -> dict:
    payload = {
        "heat_number": "H-99001",
        "alloy_code": "C360",
        "bar_diameter_mm": 16.0,
        "bar_length_mm": 3000,
        "bars_received": 10,
        "mass_kg_per_meter": 1.077,
        "feeder_slots": 1,
    }
    payload.update(overrides)
    return payload


def certify_payload(certificate_number: str = "CERT-1") -> dict:
    return {"certificate_number": certificate_number}


def create_quote_payload(part_id: str, **overrides) -> dict:
    payload = {
        "part_id": part_id,
        "customer_code": "ACME",
        "lot_qty": 200,
        "requested_lights_out_hours": 0,
    }
    payload.update(overrides)
    return payload


def price_payload(costing_basis: str = "STANDARD_CYCLE") -> dict:
    return {"costing_basis": costing_basis}


def accept_quote_payload(**overrides) -> dict:
    payload = {
        "customer_po_number": "ACME-9911",
        "total_committed_qty": 200,
        "expires_on": SCENARIO["PO_EXPIRES_ON"],
    }
    payload.update(overrides)
    return payload


def create_release_payload(blanket_po_id: str, expected_blanket_po_version: int, **overrides) -> dict:
    payload = {
        "blanket_po_id": blanket_po_id,
        "qty": 200,
        "due_at": SCENARIO["DUE_AT"],
        "expected_blanket_po_version": expected_blanket_po_version,
    }
    payload.update(overrides)
    return payload


def create_tool_assignment_payload(machine_id: str, **overrides) -> dict:
    payload = {
        "machine_id": machine_id,
        "station": 5,
        "tool_code": "T05-OD",
        "expected_life_pieces": 1500,
        "drift_limit_um": 8,
    }
    payload.update(overrides)
    return payload


def offset_log_payload(pieces_produced: int, measured_drift_um: float) -> dict:
    return {"pieces_produced": pieces_produced, "measured_drift_um": measured_drift_um}


def create_work_order_payload(
    release_id: str, machine_id: str, bar_lot_id: str, expected_machine_version: int, **overrides
) -> dict:
    payload = {
        "release_id": release_id,
        "machine_id": machine_id,
        "bar_lot_id": bar_lot_id,
        "qty_ordered": 200,
        "scheduled_start_at": SCENARIO["WINDOW_START"],
        "scheduled_end_at": SCENARIO["WINDOW_END"],
        "expected_machine_version": expected_machine_version,
        "lights_out_hours": 0,
    }
    payload.update(overrides)
    return payload


def complete_machining_payload(**overrides) -> dict:
    payload = {"qty_good": 200, "qty_scrap": 0, "actual_run_seconds": 9300}
    payload.update(overrides)
    return payload


def create_spc_sample_payload(
    work_order_id: str, characteristic_id: str, gauge_id: str, **overrides
) -> dict:
    payload = {
        "work_order_id": work_order_id,
        "characteristic_id": characteristic_id,
        "gauge_id": gauge_id,
        "piece_index": 200,
        "measurements": list(MEASUREMENTS_AT_CPK_MIN),
    }
    payload.update(overrides)
    return payload


def create_routing_step_payload(work_order_id: str, **overrides) -> dict:
    payload = {"work_order_id": work_order_id, "sequence": 1, "operation": "DEBURR"}
    payload.update(overrides)
    return payload


def disposition_payload(decision: str, note: str = "recorded by quality") -> dict:
    return {"decision": decision, "note": note}
