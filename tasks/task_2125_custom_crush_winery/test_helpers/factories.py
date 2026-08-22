"""Payload factories — one per resource, carrying only client-supplied fields."""
from .constants import TEST_DEFAULTS

DEFAULTS = {
    "CLIENT_NAME": "Coombsville Cellars",
    "CLIENT_PERMIT": "BW-CA-15001",
    "CLIENT_EMAIL": "ops@coombsville.example",
    "VESSEL_CODE": "T-101",
    "TANK_CAPACITY_GALLONS": 4000,
    "BARREL_CAPACITY_GALLONS": 60,
    "LINE_CODE": "L-1",
    "CASES_PER_HOUR": 180,
    "CHANGEOVER_MINUTES": 45,
    "DAILY_CAPACITY_HOURS": 16,
}


def create_client_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["CLIENT_NAME"],
        "ttb_permit_number": DEFAULTS["CLIENT_PERMIT"],
        "contact_email": DEFAULTS["CLIENT_EMAIL"],
    }
    payload.update(overrides)
    return payload


def create_contract_payload(client_id: str, **overrides) -> dict:
    payload = {
        "client_id": client_id,
        "harvest_year": TEST_DEFAULTS["HARVEST_YEAR"],
        "committed_tons": TEST_DEFAULTS["COMMITTED_TONS"],
        "tank_gallons_entitled": TEST_DEFAULTS["TANK_GALLONS_ENTITLED"],
        "barrel_slots_entitled": TEST_DEFAULTS["BARREL_SLOTS_ENTITLED"],
        "crush_rate_cents_per_ton": TEST_DEFAULTS["CRUSH_RATE_CENTS_PER_TON"],
        "storage_rate_cents_per_gallon_month": TEST_DEFAULTS[
            "STORAGE_RATE_CENTS_PER_GALLON_MONTH"
        ],
        "labor_rate_cents_per_hour": TEST_DEFAULTS["LABOR_RATE_CENTS_PER_HOUR"],
        "effective_from": TEST_DEFAULTS["EFFECTIVE_FROM"],
        "effective_to": TEST_DEFAULTS["EFFECTIVE_TO"],
    }
    payload.update(overrides)
    return payload


def create_vessel_payload(**overrides) -> dict:
    payload = {
        "vessel_code": DEFAULTS["VESSEL_CODE"],
        "vessel_type": "TANK",
        "capacity_gallons": DEFAULTS["TANK_CAPACITY_GALLONS"],
        "facility_zone": "ZONE_A",
    }
    payload.update(overrides)
    return payload


def create_barrel_payload(**overrides) -> dict:
    payload = {
        "vessel_code": "BBL-0442",
        "vessel_type": "BARREL",
        "capacity_gallons": DEFAULTS["BARREL_CAPACITY_GALLONS"],
        "facility_zone": "BARREL_HALL",
    }
    payload.update(overrides)
    return payload


def create_vessel_allocation_payload(
    contract_id: str, vessel_id: str, expected_vessel_version: int, **overrides
) -> dict:
    payload = {
        "contract_id": contract_id,
        "vessel_id": vessel_id,
        "start_at": "2026-09-01T00:00:00Z",
        "end_at": "2026-11-01T00:00:00Z",
        "allocated_gallons": 4000,
        "expected_vessel_version": expected_vessel_version,
    }
    payload.update(overrides)
    return payload


def create_harvest_intake_payload(contract_id: str, **overrides) -> dict:
    payload = {
        "contract_id": contract_id,
        "delivery_ticket": "DT-1001",
        "varietal": "CABERNET_SAUVIGNON",
        "appellation": "OAKVILLE",
        "block_code": "B12",
        "gross_weight_lbs": 42000,
        "tare_weight_lbs": 4000,
    }
    payload.update(overrides)
    return payload


def create_lot_payload(contract_id: str, intake_ids, **overrides) -> dict:
    payload = {
        "contract_id": contract_id,
        "lot_code": "CS-OAK-26-01",
        "vintage_year": 2026,
        "intake_ids": list(intake_ids),
    }
    payload.update(overrides)
    return payload


def create_blend_trial_payload(contract_id: str, components, **overrides) -> dict:
    payload = {
        "contract_id": contract_id,
        "trial_name": "Estate Cuvee",
        "target_lot_code": "BLEND-26-01",
        "declared_loss_pct": 2.00,
        "components": list(components),
    }
    payload.update(overrides)
    return payload


def blend_component(source_lot_id: str, volume_gallons: float) -> dict:
    return {"source_lot_id": source_lot_id, "volume_gallons": volume_gallons}


def create_work_order_payload(lot_id: str, **overrides) -> dict:
    payload = {
        "lot_id": lot_id,
        "operation_type": "PUMPOVER",
        "scheduled_at": "2026-09-12T15:00:00Z",
        "labor_hours": 2.50,
        "crew_size": 2,
    }
    payload.update(overrides)
    return payload


def create_bottling_line_payload(**overrides) -> dict:
    payload = {
        "line_code": DEFAULTS["LINE_CODE"],
        "cases_per_hour": DEFAULTS["CASES_PER_HOUR"],
        "changeover_minutes": DEFAULTS["CHANGEOVER_MINUTES"],
        "daily_capacity_hours": DEFAULTS["DAILY_CAPACITY_HOURS"],
    }
    payload.update(overrides)
    return payload


def create_bottling_run_payload(lot_id: str, line_id: str, **overrides) -> dict:
    payload = {
        "lot_id": lot_id,
        "line_id": line_id,
        "scheduled_start": "2026-10-12T09:00:00Z",
        "bottle_size_ml": 750,
        "cases_planned": 100,
    }
    payload.update(overrides)
    return payload


def create_dry_goods_item_payload(client_id: str, **overrides) -> dict:
    payload = {
        "client_id": client_id,
        "sku": "BTL-750-ANT",
        "item_type": "BOTTLE",
        "units_per_case": 12,
    }
    payload.update(overrides)
    return payload


def create_ttb_report_payload(client_id: str, **overrides) -> dict:
    payload = {
        "client_id": client_id,
        "period_start": "2026-09-01T00:00:00Z",
        "period_end": "2026-10-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_release_order_payload(lot_id: str, **overrides) -> dict:
    payload = {
        "lot_id": lot_id,
        "release_type": "TAXPAID_REMOVAL",
        "gallons": 100.00,
    }
    payload.update(overrides)
    return payload
