"""Request-payload builders.

Each builder returns a valid payload for one write endpoint and accepts keyword
overrides so a test can perturb exactly the field under examination. Monetary
amounts are emitted as JSON integers of cents, exactly as the PRD declares them.
"""

from typing import Optional

from .types import JsonDict

# Canonical firing / testing windows used across the suite. Every window is
# half-open [start, end), so an end instant is free for the next booking.
WINDOW_AUG02_06_10 = ("2026-08-02T06:00:00Z", "2026-08-02T10:00:00Z")
WINDOW_AUG02_22_AUG03_02 = ("2026-08-02T22:00:00Z", "2026-08-03T02:00:00Z")
WINDOW_AUG03_14_18 = ("2026-08-03T14:00:00Z", "2026-08-03T18:00:00Z")
WINDOW_AUG04_06_10 = ("2026-08-04T06:00:00Z", "2026-08-04T10:00:00Z")
WINDOW_AUG04_22_AUG05_02 = ("2026-08-04T22:00:00Z", "2026-08-05T02:00:00Z")
WINDOW_AUG03_06_10 = ("2026-08-03T06:00:00Z", "2026-08-03T10:00:00Z")

CLOCK_AFTER_ALL_WINDOWS = "2026-08-05T06:00:00Z"
QUALIFIED_UNTIL_FAR_FUTURE = "2027-06-30T00:00:00Z"


def supplier_payload(**overrides) -> JsonDict:
    """A gas-valve supplier whose fresh audit reading scores in the QUALIFIED band."""
    payload = {
        "name": "Meridian Controls",
        "component_category": "GAS_VALVE",
        "audit_score": 96,
        "defect_ppm": 1000,
        "open_capa_count": 0,
    }
    payload.update(overrides)
    return payload


def safety_valve_supplier_payload(**overrides) -> JsonDict:
    """The second supplier: T&P relief valves. Registration data only; a fresh
    audit reading is supplied separately by whichever qualify call scores it."""
    payload = {
        "name": "Aegis Safety",
        "component_category": "TP_RELIEF_VALVE",
        "audit_score": 92,
        "defect_ppm": 1500,
        "open_capa_count": 1,
    }
    payload.update(overrides)
    return payload


def qualify_payload(**overrides) -> JsonDict:
    """A fresh audit reading plus an expiry strictly after the logical clock."""
    payload = {
        "audit_score": 96,
        "defect_ppm": 1000,
        "open_capa_count": 0,
        "qualified_until": QUALIFIED_UNTIL_FAR_FUTURE,
    }
    payload.update(overrides)
    return payload


def component_lot_payload(supplier_id: str, **overrides) -> JsonDict:
    """A gas-valve lot arriving with a signed certificate of conformance."""
    payload = {
        "supplier_id": supplier_id,
        "part_number": "GV-880",
        "category": "GAS_VALVE",
        "quantity": 50,
        "certificate_of_conformance": True,
    }
    payload.update(overrides)
    return payload


def safety_valve_lot_payload(supplier_id: str, **overrides) -> JsonDict:
    """A T&P relief-valve lot arriving with a signed certificate of conformance."""
    payload = {
        "supplier_id": supplier_id,
        "part_number": "TP-150",
        "category": "TP_RELIEF_VALVE",
        "quantity": 50,
        "certificate_of_conformance": True,
    }
    payload.update(overrides)
    return payload


def product_model_payload(**overrides) -> JsonDict:
    """A 50-gallon gas trade model with R-20 insulation."""
    payload = {
        "model_code": "GX50-T",
        "fuel_type": "GAS",
        "nominal_capacity_gallons": 50,
        "channel": "TRADE",
        "insulation_r_value": 20,
        "is_private_label": False,
    }
    payload.update(overrides)
    return payload


def heat_pump_model_payload(**overrides) -> JsonDict:
    """A 65-gallon heat-pump builder model with R-25 insulation (large tier)."""
    payload = {
        "model_code": "HP65-B",
        "fuel_type": "HEAT_PUMP",
        "nominal_capacity_gallons": 65,
        "channel": "BUILDER",
        "insulation_r_value": 25,
        "is_private_label": False,
    }
    payload.update(overrides)
    return payload


def large_gas_model_payload(**overrides) -> JsonDict:
    """A 75-gallon gas retail model with R-16 insulation (no R-value credit)."""
    payload = {
        "model_code": "GX75-R",
        "fuel_type": "GAS",
        "nominal_capacity_gallons": 75,
        "channel": "RETAIL",
        "insulation_r_value": 16,
        "is_private_label": False,
    }
    payload.update(overrides)
    return payload


def private_label_payload(base_model_id: str, **overrides) -> JsonDict:
    """A private-label variant that inherits its base model's fuel and capacity."""
    payload = {
        "model_code": "PL50-T",
        "fuel_type": "GAS",
        "nominal_capacity_gallons": 50,
        "channel": "RETAIL",
        "insulation_r_value": 20,
        "is_private_label": True,
        "base_model_id": base_model_id,
        "brand_label": "HouseBrand",
    }
    payload.update(overrides)
    return payload


def test_cell_payload(**overrides) -> JsonDict:
    """A two-slot cell with a twelve-hour per-model cooldown."""
    payload = {"cell_code": "CELL-1", "parallel_slots": 2, "cooldown_hours": 12}
    payload.update(overrides)
    return payload


def efficiency_test_payload(
    product_model_id: str, test_cell_id: str, window=WINDOW_AUG02_06_10, **overrides
) -> JsonDict:
    """A UEF test booked over a half-open window on the given cell."""
    payload = {
        "product_model_id": product_model_id,
        "test_cell_id": test_cell_id,
        "test_type": "UEF",
        "sample_size": 3,
        "window_start": window[0],
        "window_end": window[1],
    }
    payload.update(overrides)
    return payload


def furnace_payload(**overrides) -> JsonDict:
    """A firing furnace whose ceiling sits inside the declared 700-1000 C range."""
    payload = {"furnace_code": "FURN-A", "max_firing_temp_c": 900}
    payload.update(overrides)
    return payload


def lining_batch_payload(
    furnace_id: str, window=WINDOW_AUG02_06_10, **overrides
) -> JsonDict:
    """A slurry batch booked onto a furnace for a half-open firing window."""
    payload = {
        "furnace_id": furnace_id,
        "batch_code": "GLB-001",
        "slurry_mix_code": "SLR-7",
        "firing_temp_c": 840,
        "firing_start": window[0],
        "firing_end": window[1],
    }
    payload.update(overrides)
    return payload


def tank_lot_payload(product_model_id: str, **overrides) -> JsonDict:
    """A 120-tank production lot, so the required inspection sample is six."""
    payload = {
        "product_model_id": product_model_id,
        "lot_code": "TL-001",
        "planned_quantity": 120,
    }
    payload.update(overrides)
    return payload


def adhesion_inspection_payload(
    tank_lot_id: str, expected_version: int, **overrides
) -> JsonDict:
    """A passing adhesion record: class 1 is at or below the maximum class 2."""
    payload = {
        "tank_lot_id": tank_lot_id,
        "inspection_type": "ADHESION",
        "sample_size": 6,
        "adhesion_class": 1,
        "expected_tank_lot_version": expected_version,
    }
    payload.update(overrides)
    return payload


def holiday_inspection_payload(
    tank_lot_id: str, expected_version: int, **overrides
) -> JsonDict:
    """A passing holiday record: three holidays over six tanks is 0.5000."""
    payload = {
        "tank_lot_id": tank_lot_id,
        "inspection_type": "HOLIDAY",
        "sample_size": 6,
        "holiday_count": 3,
        "expected_tank_lot_version": expected_version,
    }
    payload.update(overrides)
    return payload


def failing_holiday_payload(
    tank_lot_id: str, expected_version: int, **overrides
) -> JsonDict:
    """A failing holiday record: four holidays over six tanks is 0.6667."""
    payload = {
        "tank_lot_id": tank_lot_id,
        "inspection_type": "HOLIDAY",
        "sample_size": 6,
        "holiday_count": 4,
        "scrap_quantity": 10,
        "expected_tank_lot_version": expected_version,
    }
    payload.update(overrides)
    return payload


def foam_payload(**overrides) -> JsonDict:
    """A 50 mm foaming pass, which achieves an R-value of 20.0."""
    payload = {"foam_density_kg_m3": 32.0, "foam_thickness_mm": 50}
    payload.update(overrides)
    return payload


def heater_unit_payload(
    tank_lot_id: str,
    safety_valve_lot_id: str,
    gas_control_lot_id: Optional[str] = None,
    **overrides,
) -> JsonDict:
    """Stages one unit; a gas model additionally names its gas-control lot."""
    payload: JsonDict = {
        "tank_lot_id": tank_lot_id,
        "safety_valve_lot_id": safety_valve_lot_id,
    }
    if gas_control_lot_id is not None:
        payload["gas_control_lot_id"] = gas_control_lot_id
    payload.update(overrides)
    return payload


def ship_payload(**overrides) -> JsonDict:
    """Ships into the trade channel with moderate installation water."""
    payload = {"install_water_hardness_gpg": 8.0, "distribution_channel": "TRADE"}
    payload.update(overrides)
    return payload


def certification_payload(product_model_id: str, expected_version: int, **overrides) -> JsonDict:
    """Opens a DRAFT certification pinned to the model version just read."""
    payload = {
        "product_model_id": product_model_id,
        "expected_product_model_version": expected_version,
    }
    payload.update(overrides)
    return payload


def approve_payload(**overrides) -> JsonDict:
    payload = {"effective_date": "2026-08-05T00:00:00Z"}
    payload.update(overrides)
    return payload


def reason_payload(reason_code: str = "AUDIT_FINDING", **overrides) -> JsonDict:
    payload = {"reason_code": reason_code}
    payload.update(overrides)
    return payload


def warranty_claim_payload(heater_unit_id: str, **overrides) -> JsonDict:
    """A tank-leak claim reporting the same water hardness the unit was shipped with."""
    payload = {
        "heater_unit_id": heater_unit_id,
        "failure_mode": "TANK_LEAK",
        "reported_water_hardness_gpg": 8.0,
    }
    payload.update(overrides)
    return payload


def recall_campaign_payload(scope_product_model_id: str, **overrides) -> JsonDict:
    """A gas-valve-kit campaign with a budget large enough for a small population."""
    payload = {
        "campaign_code": "RC-001",
        "scope_product_model_id": scope_product_model_id,
        "remedy_type": "GAS_VALVE_KIT",
        "budget_cents": 100000,
    }
    payload.update(overrides)
    return payload


def scope_payload(serial_range_start: str, serial_range_end: str, **overrides) -> JsonDict:
    payload = {
        "serial_range_start": serial_range_start,
        "serial_range_end": serial_range_end,
    }
    payload.update(overrides)
    return payload
