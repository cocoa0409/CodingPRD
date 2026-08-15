"""Payload factories — one per entity, input fields only (PRD §3)."""


def create_product_payload(**overrides) -> dict:
    defaults = {
        "sku_code": "BAR-VAN-70",
        "product_name": "Vanilla Bar 70ml",
        "format": "NOVELTY",
        "flavor_family": "VANILLA",
        "allergens": ["MILK"],
        "fill_volume_ml_per_unit": 70,
        "target_overrun_pct": 40,
        "units_per_pallet": 100,
        "shelf_life_days": 540,
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "customer_code": "C-DIST",
        "display_name": "Distributor Co",
        "kind": "DISTRIBUTOR",
    }
    defaults.update(overrides)
    return defaults


def create_contract_payload(customer_id, product_id, **overrides) -> dict:
    defaults = {
        "contract_code": "CT-1",
        "customer_id": customer_id,
        "product_id": product_id,
        "committed_units": 1000,
        "unit_price_cents": 100,
        "start_date": "2026-08-01",
        "end_date": "2027-08-01",
    }
    defaults.update(overrides)
    return defaults


def create_mix_batch_payload(product_id, **overrides) -> dict:
    defaults = {
        "batch_code": "MB-1",
        "product_id": product_id,
        "litres_produced": 500,
    }
    defaults.update(overrides)
    return defaults


def create_line_payload(**overrides) -> dict:
    defaults = {
        "line_code": "L-1",
        "format": "NOVELTY",
        "rate_units_per_hour": 12000,
    }
    defaults.update(overrides)
    return defaults


def create_changeover_payload(line_id, to_product_id, **overrides) -> dict:
    defaults = {
        "line_id": line_id,
        "to_product_id": to_product_id,
    }
    defaults.update(overrides)
    return defaults


def create_production_run_payload(product_id, line_id, **overrides) -> dict:
    defaults = {
        "run_code": "R-1",
        "product_id": product_id,
        "line_id": line_id,
        "planned_units": 1000,
        "scheduled_start": "2026-08-10T14:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_tunnel_payload(**overrides) -> dict:
    defaults = {
        "tunnel_code": "T-1",
        "max_units_per_hour": 20000,
    }
    defaults.update(overrides)
    return defaults


def create_tunnel_booking_payload(tunnel_id, run_id, **overrides) -> dict:
    defaults = {
        "tunnel_id": tunnel_id,
        "run_id": run_id,
        "start_at": "2026-08-10T13:00:00Z",
        "end_at": "2026-08-10T14:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_freezer_zone_payload(**overrides) -> dict:
    defaults = {
        "zone_code": "Z-A",
        "pallet_capacity": 400,
    }
    defaults.update(overrides)
    return defaults


def create_shipment_payload(customer_id, **overrides) -> dict:
    defaults = {
        "shipment_code": "SH-1",
        "customer_id": customer_id,
    }
    defaults.update(overrides)
    return defaults


def create_allocation_payload(lot_id, **overrides) -> dict:
    defaults = {
        "lot_id": lot_id,
        "units": 100,
    }
    defaults.update(overrides)
    return defaults


def create_temp_abuse_claim_payload(shipment_id, **overrides) -> dict:
    defaults = {
        "claim_code": "CL-1",
        "shipment_id": shipment_id,
        "declared_value_cents": 50000,
    }
    defaults.update(overrides)
    return defaults


def create_quality_complaint_payload(lot_id, **overrides) -> dict:
    defaults = {
        "complaint_code": "QC-1",
        "lot_id": lot_id,
        "complaint_type": "TEXTURE",
    }
    defaults.update(overrides)
    return defaults


def create_seasonal_build_plan_payload(product_id, zone_id, **overrides) -> dict:
    defaults = {
        "plan_code": "BP-1",
        "product_id": product_id,
        "zone_id": zone_id,
        "production_week_start": "2026-10-05",
        "sale_week_start": "2027-04-03",
        "target_units": 1000,
    }
    defaults.update(overrides)
    return defaults
