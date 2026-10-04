"""Payload factories — one per entity, input fields only."""


def create_capacity_week_payload(**overrides) -> dict:
    defaults = {
        "mill_code": "MILL-ALX",
        "week_start_date": "2026-09-07",
        "total_capacity_mbf": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_allocate_payload(internal=600, market=400, **overrides) -> dict:
    defaults = {
        "internal_alloc_mbf": internal,
        "market_alloc_mbf": market,
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(**overrides) -> dict:
    defaults = {
        "sku_code": "LVL-DF-16",
        "product_family": "LVL_BEAM",
        "species": "DOUGLAS_FIR",
        "dimension_label": "16in",
        "index_premium_cents": 500,
    }
    defaults.update(overrides)
    return defaults


def create_specialty_product_payload(**overrides) -> dict:
    defaults = {
        "sku_code": "IJI-SP-11",
        "product_family": "I_JOIST",
        "species": "SOUTHERN_PINE",
        "dimension_label": "11.875in",
        "specialty_flag": True,
        "requires_code_report": True,
        "requires_design_support": True,
        "index_premium_cents": 800,
    }
    defaults.update(overrides)
    return defaults


def create_price_index_entry_payload(**overrides) -> dict:
    defaults = {
        "product_family": "LVL_BEAM",
        "species": "DOUGLAS_FIR",
        "effective_week_start": "2026-09-07",
        "index_price_cents_per_mbf": 72000,
    }
    defaults.update(overrides)
    return defaults


def create_branch_payload(**overrides) -> dict:
    defaults = {
        "branch_code": "BR-BOI",
        "region_code": "PNW",
        "species_preference": "DOUGLAS_FIR",
        "target_stock_mbf": 500,
        "activity_score": 90,
    }
    defaults.update(overrides)
    return defaults


def create_inventory_lot_payload(product_id, **overrides) -> dict:
    defaults = {
        "product_id": product_id,
        "qty_received_mbf": 100,
        "unit_cost_cents_per_mbf": 40000,
    }
    defaults.update(overrides)
    return defaults


def create_builder_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "Treeline Builders",
        "lien_rights_state_code": "ID",
    }
    defaults.update(overrides)
    return defaults


def create_job_payload(**overrides) -> dict:
    defaults = {
        "job_name": "Ridgeview Lot 7",
        "access_window_start": "2026-09-01T00:00:00Z",
        "access_window_end": "2026-12-31T23:59:59Z",
        "job_exposure_cap_cents": 100000000,
    }
    defaults.update(overrides)
    return defaults


def create_takeoff_request_payload(**overrides) -> dict:
    defaults = {
        "plan_reference": "PLAN-2211",
        "includes_floor_system_design": False,
    }
    defaults.update(overrides)
    return defaults


def create_submit_design_payload(**overrides) -> dict:
    defaults = {
        "design_package_reference": "DSN-A",
        "quoted_total_cents": 800000,
    }
    defaults.update(overrides)
    return defaults


def create_order_line(product_id, qty_mbf=10, price_basis="FIXED",
                      fixed_unit_price_cents_per_mbf=100000, **overrides) -> dict:
    line = {
        "product_id": product_id,
        "qty_mbf": qty_mbf,
        "price_basis": price_basis,
    }
    if price_basis == "FIXED":
        line["fixed_unit_price_cents_per_mbf"] = fixed_unit_price_cents_per_mbf
    line.update(overrides)
    return line


def create_sales_order_payload(branch_id, expected_builder_version,
                               lines=None, **overrides) -> dict:
    defaults = {
        "branch_id": branch_id,
        "pricing_week_mode": "LOCK_AT_ACCEPT",
        "lines": lines or [],
        "expected_builder_version": expected_builder_version,
    }
    defaults.update(overrides)
    return defaults


def create_accept_takeoff_payload(branch_id, **overrides) -> dict:
    defaults = {
        "branch_id": branch_id,
        "pricing_week_mode": "LOCK_AT_ACCEPT",
    }
    defaults.update(overrides)
    return defaults


def create_delivery_payload(**overrides) -> dict:
    defaults = {
        "boom_required": False,
        "window_start": "2026-09-10T09:00:00Z",
        "window_end": "2026-09-10T12:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_truck_shift_payload(**overrides) -> dict:
    defaults = {
        "fleet_code": "FLT-1",
        "shift_date": "2026-09-10",
        "window_start": "2026-09-10T08:00:00Z",
        "window_end": "2026-09-10T16:00:00Z",
        "boom_capable": True,
    }
    defaults.update(overrides)
    return defaults
