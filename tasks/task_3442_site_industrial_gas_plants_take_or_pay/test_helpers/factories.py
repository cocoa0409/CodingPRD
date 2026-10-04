"""Payload factories — one per creatable resource, input fields only.

Optional fields that carry a server-side default per the PRD are OMITTED
unless explicitly overridden, so the default-applying behavior stays
observable:
- Customer.credit_standing (defaults STANDARD) and .blackout_windows ([])
- SupplyContract.makeup_credit_cap_pct (defaults 0.10)

All dates are absolute ISO 8601 instants placed AFTER the logical-clock start
(2026-09-01T00:00:00Z, PRD section 2.4) so every default chain is reachable by
tests that drive the clock forward.
"""
from .constants import CLOCK_START_UTC

DEFAULTS = {
    # Customer
    "CUSTOMER_NAME": "Fabrikam Chips",
    "CUSTOMER_SEGMENT": "ELECTRONICS",
    # SupplyModeEvaluation
    "SITE_LABEL": "FAB-1",
    "DEMAND_AVG_NM3H": 5000,
    "DEMAND_PEAK_NM3H": 7000,
    "REQUIRED_PURITY_PERCENT": 99.999,
    "REQUIRED_PRODUCT": "N2",
    "PIPELINE_AVAILABLE": True,
    # SupplyContract
    "TERM_MONTHS": 120,
    "START_DATE": "2026-10-01",
    "MIN_MONTHLY_VOLUME_NM3": 2000000,
    "UNIT_PRICE_CENTS_PER_NM3": 12,
    "MONTHLY_FACILITY_FEE_CENTS": 500000,
    "FACILITY_FEE_ESCALATION_PCT_ANNUAL": 0.03,
    "BASE_POWER_INDEX": 0.08,
    "POWER_KWH_PER_NM3": 0.42,
    # OnsitePlant
    "PLANT_NAME": "FAB-1 ASU",
    "NAMEPLATE_CAPACITY_NM3H": 6000,
    "CAPITAL_COST_CENTS": 120000000,
    # PipelineNetwork / PipelineConnection
    "NETWORK_NAME": "Gulf Coast N2",
    "NETWORK_NAMEPLATE_CAPACITY_NM3H": 10000,
    "RESERVED_FLOW_NM3H": 4000,
    "CONNECTION_PURPOSE": "BACKUP",
    # StorageTank (headroom-friendly: trigger level 20000 -> quantity 30000)
    "TANK_CAPACITY_LITERS": 50000,
    "TANK_REORDER_POINT_LITERS": 20000,
    "TANK_SAFETY_STOCK_LITERS": 5000,
    "TANK_REQUIRED_PURITY_PERCENT": 99.999,
    "TANK_MAX_IMPURITY_PPM": 10,
    # Telemetry (monotonic, after clock start)
    "FIRST_MEASURED_AT": "2026-10-01T00:00:00Z",
    "TRIGGER_MEASURED_AT": "2026-10-01T05:00:00Z",
    # Delivery confirmation / quality certificate
    "DELIVERED_QUANTITY_LITERS": 30000,
    "CERT_SAMPLED_AT": "2026-10-01T08:00:00Z",
    "CERT_MEASURED_PURITY_PERCENT": 99.9995,
    "CERT_MEASURED_IMPURITY_PPM": 5,
    # Turnaround (96h window, within [24h, 720h], after clock start)
    "TURNAROUND_WINDOW_START": "2026-11-01T00:00:00Z",
    "TURNAROUND_WINDOW_END": "2026-11-05T00:00:00Z",
    "TURNAROUND_SCOPE": "Scheduled maintenance outage",
    # Settlement
    "PERIOD_MONTH": "2027-12",
    "METERED_VOLUME_NM3": 1500000,
    "PROJECTED_VOLUME_NM3": 1800000,
    "POWER_INDEX_ACTUAL": 0.10,
}


def set_clock_payload(current_utc: str = CLOCK_START_UTC) -> dict:
    return {"current_utc": current_utc}


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["CUSTOMER_NAME"],
        "segment": DEFAULTS["CUSTOMER_SEGMENT"],
        # credit_standing / blackout_windows omitted: server defaults apply.
    }
    defaults.update(overrides)
    return defaults


def create_evaluation_payload(customer_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "site_label": DEFAULTS["SITE_LABEL"],
        "demand_avg_nm3h": DEFAULTS["DEMAND_AVG_NM3H"],
        "demand_peak_nm3h": DEFAULTS["DEMAND_PEAK_NM3H"],
        "required_purity_percent": DEFAULTS["REQUIRED_PURITY_PERCENT"],
        "required_product": DEFAULTS["REQUIRED_PRODUCT"],
        "pipeline_available": DEFAULTS["PIPELINE_AVAILABLE"],
    }
    defaults.update(overrides)
    return defaults


def create_contract_payload(customer_id: str, evaluation_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "evaluation_id": evaluation_id,
        "term_months": DEFAULTS["TERM_MONTHS"],
        "start_date": DEFAULTS["START_DATE"],
        "min_monthly_volume_nm3": DEFAULTS["MIN_MONTHLY_VOLUME_NM3"],
        "unit_price_cents_per_nm3": DEFAULTS["UNIT_PRICE_CENTS_PER_NM3"],
        "monthly_facility_fee_cents": DEFAULTS["MONTHLY_FACILITY_FEE_CENTS"],
        "facility_fee_escalation_pct_annual": DEFAULTS["FACILITY_FEE_ESCALATION_PCT_ANNUAL"],
        "base_power_index": DEFAULTS["BASE_POWER_INDEX"],
        "power_kwh_per_nm3": DEFAULTS["POWER_KWH_PER_NM3"],
        # makeup_credit_cap_pct omitted: server default 0.10 applies.
    }
    defaults.update(overrides)
    return defaults


def create_amendment_payload(kind: str = "AMENDMENT", expected_contract_version: int = 1,
                             **overrides) -> dict:
    defaults = {
        "kind": kind,
        "expected_contract_version": expected_contract_version,
    }
    defaults.update(overrides)
    return defaults


def create_plant_payload(contract_id: str, **overrides) -> dict:
    defaults = {
        "contract_id": contract_id,
        "name": DEFAULTS["PLANT_NAME"],
        "nameplate_capacity_nm3h": DEFAULTS["NAMEPLATE_CAPACITY_NM3H"],
        "capital_cost_cents": DEFAULTS["CAPITAL_COST_CENTS"],
        "power_kwh_per_nm3": DEFAULTS["POWER_KWH_PER_NM3"],
    }
    defaults.update(overrides)
    return defaults


def create_network_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["NETWORK_NAME"],
        "nameplate_capacity_nm3h": DEFAULTS["NETWORK_NAMEPLATE_CAPACITY_NM3H"],
    }
    defaults.update(overrides)
    return defaults


def create_connection_payload(network_id: str, contract_id: str, **overrides) -> dict:
    defaults = {
        "network_id": network_id,
        "contract_id": contract_id,
        "reserved_flow_nm3h": DEFAULTS["RESERVED_FLOW_NM3H"],
        "purpose": DEFAULTS["CONNECTION_PURPOSE"],
    }
    defaults.update(overrides)
    return defaults


def create_tank_payload(customer_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "site_label": DEFAULTS["SITE_LABEL"],
        "product": DEFAULTS["REQUIRED_PRODUCT"],
        "capacity_liters": DEFAULTS["TANK_CAPACITY_LITERS"],
        "reorder_point_liters": DEFAULTS["TANK_REORDER_POINT_LITERS"],
        "safety_stock_liters": DEFAULTS["TANK_SAFETY_STOCK_LITERS"],
        "required_purity_percent": DEFAULTS["TANK_REQUIRED_PURITY_PERCENT"],
        "max_impurity_ppm": DEFAULTS["TANK_MAX_IMPURITY_PPM"],
    }
    defaults.update(overrides)
    return defaults


def create_telemetry_payload(measured_at: str, level_liters: int) -> dict:
    return {"measured_at": measured_at, "level_liters": level_liters}


def create_confirm_delivery_payload(delivered_quantity_liters: int = DEFAULTS["DELIVERED_QUANTITY_LITERS"]) -> dict:
    return {"delivered_quantity_liters": delivered_quantity_liters}


def create_certificate_payload(**overrides) -> dict:
    defaults = {
        "sampled_at": DEFAULTS["CERT_SAMPLED_AT"],
        "measured_purity_percent": DEFAULTS["CERT_MEASURED_PURITY_PERCENT"],
        "measured_impurity_ppm": DEFAULTS["CERT_MEASURED_IMPURITY_PPM"],
    }
    defaults.update(overrides)
    return defaults


def create_certify_payload(decision: str = "CERTIFIED") -> dict:
    return {"decision": decision}


def create_turnaround_payload(**overrides) -> dict:
    defaults = {
        "window_start": DEFAULTS["TURNAROUND_WINDOW_START"],
        "window_end": DEFAULTS["TURNAROUND_WINDOW_END"],
        "scope": DEFAULTS["TURNAROUND_SCOPE"],
    }
    defaults.update(overrides)
    return defaults


def create_respond_payload(decision: str = "AGREE", expected_turnaround_version: int = 1,
                           **overrides) -> dict:
    defaults = {
        "decision": decision,
        "expected_turnaround_version": expected_turnaround_version,
    }
    defaults.update(overrides)
    return defaults


def create_settlement_payload(period_month: str = DEFAULTS["PERIOD_MONTH"],
                              variant: str = "FINAL", **overrides) -> dict:
    """Variant-correct payload: FINAL carries metered volume + actual power
    index; PROVISIONAL carries projected volume. Cross-variant fields are only
    ever present when a test injects them via overrides."""
    defaults = {"period_month": period_month, "variant": variant}
    if variant == "FINAL":
        defaults["metered_volume_nm3"] = DEFAULTS["METERED_VOLUME_NM3"]
        defaults["power_index_actual"] = DEFAULTS["POWER_INDEX_ACTUAL"]
    else:
        defaults["projected_volume_nm3"] = DEFAULTS["PROJECTED_VOLUME_NM3"]
    defaults.update(overrides)
    return defaults


__all__ = [
    "DEFAULTS",
    "set_clock_payload",
    "create_customer_payload",
    "create_evaluation_payload",
    "create_contract_payload",
    "create_amendment_payload",
    "create_plant_payload",
    "create_network_payload",
    "create_connection_payload",
    "create_tank_payload",
    "create_telemetry_payload",
    "create_confirm_delivery_payload",
    "create_certificate_payload",
    "create_certify_payload",
    "create_turnaround_payload",
    "create_respond_payload",
    "create_settlement_payload",
]
