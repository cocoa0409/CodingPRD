"""Payload factories — one per creatable resource, input fields only."""
import uuid


def _suffix() -> str:
    return uuid.uuid4().hex[:8]


def create_brand_payload(**overrides) -> dict:
    defaults = {
        "name": f"Brand {_suffix()}",
        "kind": "PLATFORM_OWNED",
        "home_region": "US",
    }
    defaults.update(overrides)
    return defaults


def create_license_agreement_payload(brand_id, **overrides) -> dict:
    defaults = {
        "brand_id": brand_id,
        "territory_code": "US",
        "effective_start": "2026-01-01",
        "effective_end": "2026-12-31",
        "royalty_tiers": [{"up_to_units": None, "millicents_per_pod": 500}],
        "quality_min_cup_score": 80,
        "exclusive": False,
    }
    defaults.update(overrides)
    return defaults


def create_quality_audit_payload(**overrides) -> dict:
    defaults = {
        "audited_at": "2026-08-01T00:00:00Z",
        "cup_score": 90,
        "defect_rate_ppm": 50,
    }
    defaults.update(overrides)
    return defaults


def create_pod_variety_payload(brand_id, **overrides) -> dict:
    defaults = {
        "brand_id": brand_id,
        "name": f"Variety {_suffix()}",
        "roast_level": "MEDIUM",
        "flavor_family": "UNFLAVORED",
        "wholesale_price_cents": 100,
        "margin_cents": 20,
    }
    defaults.update(overrides)
    return defaults


def create_brewer_model_payload(**overrides) -> dict:
    defaults = {
        "model_code": f"K-{_suffix()}".upper(),
        "firmware_compat": "OPEN",
        "warranty_months": 12,
        "descale_interval_brews": 200,
        "msrp_cents": 7000,
        "unit_cost_cents": 6000,
    }
    defaults.update(overrides)
    return defaults


def create_facility_payload(**overrides) -> dict:
    defaults = {
        "name": f"Plant {_suffix()}",
        "kind": "OWNED",
        "region": "US",
    }
    defaults.update(overrides)
    return defaults


def create_filling_line_payload(**overrides) -> dict:
    defaults = {
        "line_code": f"L-{_suffix()}".upper(),
        "supported_roast": "UNIVERSAL",
        "supports_flavored": True,
        "material_capability": "BOTH",
        "capacity_pods_per_day": 100000,
        "changeover_hours": 0,
    }
    defaults.update(overrides)
    return defaults


def create_production_run_payload(line_id, variety_id, **overrides) -> dict:
    defaults = {
        "line_id": line_id,
        "variety_id": variety_id,
        "window_start": "2026-09-10T00:00:00Z",
        "window_end": "2026-09-11T00:00:00Z",
        "planned_units": 100,
    }
    defaults.update(overrides)
    return defaults


def create_household_payload(**overrides) -> dict:
    defaults = {
        "region": "NW",
        "size": 2,
    }
    defaults.update(overrides)
    return defaults


def create_brewer_payload(model_id, **overrides) -> dict:
    defaults = {
        "model_id": model_id,
        "serial_number": f"SN-{_suffix()}".upper(),
    }
    defaults.update(overrides)
    return defaults


def create_consumption_record_payload(**overrides) -> dict:
    defaults = {
        "period": "2026-08",
        "pods_brewed": 100,
    }
    defaults.update(overrides)
    return defaults


def create_service_event_payload(**overrides) -> dict:
    defaults = {
        "kind": "DESCALING",
        "note": "routine service",
    }
    defaults.update(overrides)
    return defaults


def create_retail_account_payload(**overrides) -> dict:
    defaults = {
        "name": f"Mart {_suffix()}",
        "region": "US",
        "shelf_slots_total": 10,
        "productivity_floor_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_assortment_plan_payload(expected_retail_account_version, slots, **overrides) -> dict:
    defaults = {
        "expected_retail_account_version": expected_retail_account_version,
        "period": "2026-10",
        "slots": slots,
    }
    defaults.update(overrides)
    return defaults


def make_slot(variety_id, facings=1, clearance_flag=False) -> dict:
    return {
        "variety_id": variety_id,
        "facings": facings,
        "clearance_flag": clearance_flag,
    }


def create_royalty_statement_payload(**overrides) -> dict:
    defaults = {
        "period": "2026-08",
        "sell_in_units": 10,
        "sell_through_units": 10,
        "unlicensed_share_pct": 0,
    }
    defaults.update(overrides)
    return defaults
