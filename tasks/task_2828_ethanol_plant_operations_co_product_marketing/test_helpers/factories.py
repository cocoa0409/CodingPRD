"""
Request payload builders.

Every numeric field is sent with the JSON type the PRD declares for it: money
that ends in `_cents` is a whole number, per-unit prices and quantities are
JSON numbers rather than strings, and every instant is a full ISO 8601 UTC
instant rather than a bare date.
"""

from typing import Any, Dict, Optional

# ─── Plant ─────────────────────────────────────────────

def plant_payload(**overrides) -> Dict[str, Any]:
    """Commission the singleton plant.  Only name and nameplate are required."""
    payload: Dict[str, Any] = {
        "name": "Prairie Gold Ethanol",
        "nameplate_capacity_gallons": 120000000,
    }
    payload.update(overrides)
    return payload


def minimal_plant_payload(**overrides) -> Dict[str, Any]:
    """The two required inputs only, so every optional default is exercised."""
    payload: Dict[str, Any] = {
        "name": "Prairie Gold Ethanol",
        "nameplate_capacity_gallons": 120000000,
    }
    payload.update(overrides)
    return payload


def market_marks_payload(**overrides) -> Dict[str, Any]:
    """The five marks posted together for one contract month."""
    payload: Dict[str, Any] = {
        "marks_effective_month": "2026-10",
        "mark_corn_cents_per_bushel": 440.00,
        "mark_ethanol_cents_per_gallon": 178.00,
        "mark_natgas_cents_per_mmbtu": 265.75,
        "mark_soybean_meal_usd_per_ton": 330.00,
        "mark_sbo_cents_per_lb": 46.80,
    }
    payload.update(overrides)
    return payload


# ─── Corn procurement ──────────────────────────────────

def contract_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "supplier_name": "Miller Farms",
        "delivery_month": "2026-10",
        "bushels_contracted": 200000.00,
        "basis_cents_per_bushel": -18.0,
    }
    payload.update(overrides)
    return payload


def price_payload(futures_price_cents_per_bushel: float = 458.0) -> Dict[str, Any]:
    return {"futures_price_cents_per_bushel": futures_price_cents_per_bushel}


def roll_payload(
    delivery_month: str = "2026-12", roll_basis_adjustment_cents: float = -4.0
) -> Dict[str, Any]:
    return {
        "delivery_month": delivery_month,
        "roll_basis_adjustment_cents": roll_basis_adjustment_cents,
    }


def delivery_payload(**overrides) -> Dict[str, Any]:
    """A scale ticket.  Weights are whole pounds; tare is at least zero."""
    payload: Dict[str, Any] = {
        "ticket_number": "TK-0001",
        "gross_weight_lbs": 78640,
        "tare_weight_lbs": 26000.00,
    }
    payload.update(overrides)
    return payload


def grade_payload(**overrides) -> Dict[str, Any]:
    """A load exactly on every discount basis unless overridden."""
    payload: Dict[str, Any] = {
        "moisture_pct": 15.00,
        "test_weight_lb_per_bu": 54.0,
        "foreign_material_pct": 3.00,
        "damaged_kernels_pct": 5.00,
        "aflatoxin_ppb": 3,
    }
    payload.update(overrides)
    return payload


# ─── Fermentation ──────────────────────────────────────

def batch_payload(destination_tank_id: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "batch_code": "FB-1",
        "corn_bushels_charged": 900.00,
        "charge_test_weight_lb_per_bu": 54.0,
        "destination_tank_id": destination_tank_id,
    }
    payload.update(overrides)
    return payload


def health_reading_payload(**overrides) -> Dict[str, Any]:
    """A reading inside every band, worth a full 100.00 reading score."""
    payload: Dict[str, Any] = {
        "hours_elapsed": 12.0,
        "lactic_acid_ppm": 400,
        "acetic_acid_ppm": 150,
        "temperature_c": 32.0,
    }
    payload.update(overrides)
    return payload


def intervene_payload(intervention_note: str = "Dosed with antimicrobial") -> Dict[str, Any]:
    return {"intervention_note": intervention_note}


def dump_payload(dump_reason: str = "Irrecoverable infection") -> Dict[str, Any]:
    return {"dump_reason": dump_reason}


# ─── Tank farm ─────────────────────────────────────────

def tank_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "tank_code": "T-101",
        "product_type": "ETHANOL_200_PROOF",
        "capacity_gallons": 1000000.00,
    }
    payload.update(overrides)
    return payload


def hold_payload(hold_reason: str = "OFF_SPEC") -> Dict[str, Any]:
    return {"hold_reason": hold_reason}


def blend_payload(
    neat_source_tank_id: str,
    denaturant_source_tank_id: str,
    destination_tank_id: str,
    expected_destination_tank_version: int,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "blend_code": "BL-1",
        "neat_source_tank_id": neat_source_tank_id,
        "denaturant_source_tank_id": denaturant_source_tank_id,
        "destination_tank_id": destination_tank_id,
        "expected_destination_tank_version": expected_destination_tank_version,
        "neat_gallons": 2565.00,
        "denaturant_gallons": 60.00,
        "window_start": "2026-09-04T06:00:00Z",
        "window_end": "2026-09-04T10:00:00Z",
    }
    payload.update(overrides)
    return payload


# ─── Rail logistics ────────────────────────────────────

def track_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "track_code": "TRK-A",
        "spot_capacity": 110,
    }
    payload.update(overrides)
    return payload


def shipment_payload(
    track_id: str, source_tank_id: str, expected_track_version: int, **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "shipment_code": "SH-1",
        "track_id": track_id,
        "expected_track_version": expected_track_version,
        "source_tank_id": source_tank_id,
        "destination_terminal": "Chicago Terminal",
        "railcar_count": 100,
        "gallons_per_railcar": 2659.00,
        "window_start": "2026-09-04T06:00:00Z",
        "window_end": "2026-09-04T12:00:00Z",
        "price_cents_per_gallon": 181.50,
    }
    payload.update(overrides)
    return payload


def bol_payload(bol_number: str = "BOL-0001") -> Dict[str, Any]:
    return {"bol_number": bol_number}


def cancel_payload(cancellation_reason: str = "Buyer cancelled the train") -> Dict[str, Any]:
    return {"cancellation_reason": cancellation_reason}


# ─── Co-product marketing ──────────────────────────────

def flat_sale_payload(**overrides) -> Dict[str, Any]:
    """A FLAT quote: quoted_price is required and index_pct must be absent."""
    payload: Dict[str, Any] = {
        "sale_code": "CS-1",
        "buyer_name": "Heartland Feeders",
        "product": "DDGS_DRY",
        "pricing_basis": "FLAT",
        "quantity": 5.000,
        "quote_expires_at": "2026-09-10T00:00:00Z",
        "quoted_price": 210.00,
    }
    payload.update(overrides)
    return payload


def index_sale_payload(**overrides) -> Dict[str, Any]:
    """An INDEX quote: index_pct is required and quoted_price is ignored."""
    payload: Dict[str, Any] = {
        "sale_code": "CS-1",
        "buyer_name": "Heartland Feeders",
        "product": "DDGS_DRY",
        "pricing_basis": "INDEX",
        "quantity": 100.000,
        "quote_expires_at": "2026-09-10T00:00:00Z",
        "index_pct": 0.9200,
    }
    payload.update(overrides)
    return payload


def respond_payload(decision: str = "ACCEPT") -> Dict[str, Any]:
    return {"decision": decision}


# ─── Renewable credits and carbon ──────────────────────

def retire_payload(retirement_reference: str = "EMTS-2026-0001") -> Dict[str, Any]:
    return {"retirement_reference": retirement_reference}


def carbon_project_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "project_code": "CP-1",
        "project_name": "Amine carbon capture skid",
        "project_type": "CARBON_CAPTURE",
        "claimed_reduction_g_per_mj": 9.0,
        "certification_tier": "FULL",
    }
    payload.update(overrides)
    return payload


def submit_payload(verification_body: str = "Verra Assurance") -> Dict[str, Any]:
    return {"verification_body": verification_body}


def review_payload(determination: str = "CERTIFY", **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"determination": determination}
    payload.update(overrides)
    return payload


# ─── Futures book ──────────────────────────────────────

def hedge_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "position_code": "HP-1",
        "commodity": "ETHANOL",
        "direction": "SHORT",
        "contract_month": "2026-12",
        "contracts": 10,
        "entry_price": 182.00,
    }
    payload.update(overrides)
    return payload


def close_payload(contracts_to_close: int, exit_price: float) -> Dict[str, Any]:
    return {"contracts_to_close": contracts_to_close, "exit_price": exit_price}


# ─── Permit compliance ─────────────────────────────────

def permit_condition_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "condition_code": "PC-1",
        "permit_type": "AIR_EMISSIONS",
        "parameter_name": "VOC",
        "limit_value": 12.500,
        "unit": "lb/hr",
        "averaging_period_hours": 24,
        "severity": "MINOR",
    }
    payload.update(overrides)
    return payload


def permit_reading_payload(
    measured_at: str, value: float, sample_reference: Optional[str] = None
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"measured_at": measured_at, "value": value}
    if sample_reference is not None:
        payload["sample_reference"] = sample_reference
    return payload


def resolve_payload(resolution_note: str = "Thermal oxidiser rebalanced") -> Dict[str, Any]:
    return {"resolution_note": resolution_note}
