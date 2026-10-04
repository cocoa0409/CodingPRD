"""Payload factories — one per entity, input fields only (PRD §3.1–§3.8)."""
from .constants import TEST_DEFAULTS as D

# --- Site (PRD §3.1) ---------------------------------------------------------
SITE_FIELD_DEFAULTS = {
    "name": D["SITE_NAME"],
    "utility_territory": D["UTILITY_TERRITORY"],
    "grid_tariff_rate_cents_per_kwh": D["GRID_TARIFF_CENTS_PER_KWH"],
    "grid_outage_events_per_year": D["GRID_OUTAGE_EVENTS_PER_YEAR"],
    "grid_annual_outage_hours": D["GRID_ANNUAL_OUTAGE_HOURS"],
    "gas_commodity_rate_cents_per_therm": D["GAS_COMMODITY_RATE_CENTS_PER_THERM"],
    "expected_annual_site_load_kwh": D["EXPECTED_ANNUAL_SITE_LOAD_KWH"],
    "tax_rate_pct": D["TAX_RATE_PCT"],
    "allowed_downtime_hours_per_year": D["ALLOWED_DOWNTIME_HOURS_PER_YEAR"],
    "clearance_zone_capacity": D["CLEARANCE_ZONE_CAPACITY"],
    "footprint_sqm": D["FOOTPRINT_SQM"],
    "standby_charge_cents_per_kw_month": D["STANDBY_CHARGE_CENTS_PER_KW_MONTH"],
    "interconnect_exit_fee_cents_per_kw": D["INTERCONNECT_EXIT_FEE_CENTS_PER_KW"],
}


def create_site_payload(**overrides) -> dict:
    """Registration payload for a customer facility."""
    payload = dict(SITE_FIELD_DEFAULTS)
    payload.update(overrides)
    return payload


def create_site_payload_without(*field_names, **overrides) -> dict:
    """Site registration payload with the named fields omitted entirely."""
    payload = dict(SITE_FIELD_DEFAULTS)
    payload.update(overrides)
    for name in field_names:
        payload.pop(name, None)
    return payload


# --- Customer (PRD §3.2) -----------------------------------------------------
CUSTOMER_FIELD_DEFAULTS = {
    "name": D["CUSTOMER_NAME"],
    "industry_code": D["INDUSTRY_CODE"],
    "credit_tier": D["CREDIT_TIER"],
}


def create_customer_payload(**overrides) -> dict:
    """Customer offtaker payload."""
    payload = dict(CUSTOMER_FIELD_DEFAULTS)
    payload.update(overrides)
    return payload


# --- Ppa (PRD §3.2) ----------------------------------------------------------
def create_ppa_payload(site_id=None, customer_id=None, **overrides) -> dict:
    """Drafting payload for a power purchase agreement."""
    payload = {
        "site_id": site_id,
        "customer_id": customer_id,
        "term_years": D["TERM_YEARS"],
        "contracted_kw": D["CONTRACTED_KW"],
        "contracted_efficiency_kwh_per_therm": D["CONTRACTED_EFFICIENCY_KWH_PER_THERM"],
        "contracted_annual_kwh": D["CONTRACTED_ANNUAL_KWH"],
        "tariff_base_cents_per_kwh": D["TARIFF_BASE_CENTS_PER_KWH"],
        "escalator_pct": D["ESCALATOR_PCT"],
        "fuel_adder_cents_per_therm": D["FUEL_ADDER_CENTS_PER_THERM"],
        "guaranteed_availability_pct": D["GUARANTEED_AVAILABILITY_PCT"],
        "guaranteed_delivery_kwh": D["GUARANTEED_DELIVERY_KWH"],
        "customer_cure_deadline_days": D["CUSTOMER_CURE_DEADLINE_DAYS"],
        "fuel_responsibility": D["FUEL_RESPONSIBILITY"],
        "loss_floor_cents": D["LOSS_FLOOR_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_ppa_payload_without(*field_names, **overrides) -> dict:
    """PPA drafting payload with the named fields omitted entirely."""
    payload = create_ppa_payload(**overrides)
    for name in field_names:
        payload.pop(name, None)
    return payload


# --- ServicePlan (PRD §3.7) --------------------------------------------------
def create_service_plan_payload(**overrides) -> dict:
    """Hand-created service plan payload."""
    payload = {
        "remote_monitoring_status": "MONITORING_LINKED",
        "radius_buffer_m": 10.0,
        "window_start_iso8601": None,
        "window_end_iso8601": None,
    }
    payload.update(overrides)
    return payload


def create_service_plan_payload_without(*field_names, **overrides) -> dict:
    payload = create_service_plan_payload(**overrides)
    for name in field_names:
        payload.pop(name, None)
    return payload


# --- FuelDelivery (PRD §3.3) -------------------------------------------------
def create_fuel_delivery_payload(expected_site_version=None, **overrides) -> dict:
    """Fuel-delivery scheduling payload (blend-priced)."""
    payload = {
        "sourcing_mode": "FIXED_PRICE_BLEND",
        "volume_therms": 8000,
        "index_rate_cents_per_therm": None,
        "fixed_price_cents_per_therm": 4.40,
        "hedged_fraction": 1.0,
        "attesting_customer_id": None,
        "delivered_at": "2026-03-05T00:00:00Z",
        "confirm_after_iso8601": "2026-03-06T00:00:00Z",
        "hold_window_start_iso8601": None,
        "hold_window_end_iso8601": None,
        "expected_site_version": expected_site_version,
    }
    payload.update(overrides)
    return payload


def create_indexed_fuel_delivery_payload(expected_site_version=None, **overrides) -> dict:
    """Fuel-delivery scheduling payload on the indexed/hedged blend."""
    payload = create_fuel_delivery_payload(
        expected_site_version=expected_site_version,
        sourcing_mode="INDEXED_BLEND",
        index_rate_cents_per_therm=4.00,
        fixed_price_cents_per_therm=4.20,
        hedged_fraction=0.5,
    )
    payload.update(overrides)
    return payload


# --- Resource hold (PRD §3.3) ------------------------------------------------
def create_resource_hold_payload(**overrides) -> dict:
    """Resource-hold payload: requested_therms plus the paired window."""
    payload = {
        "requested_therms": 25000,
        "window_start_iso8601": "2026-04-01T00:00:00Z",
        "window_end_iso8601": "2026-04-04T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_resource_hold_payload_without(*field_names, **overrides) -> dict:
    payload = create_resource_hold_payload(**overrides)
    for name in field_names:
        payload.pop(name, None)
    return payload


# --- SettlementLine (PRD §3.4) ----------------------------------------------
def create_settlement_line_payload(expected_ppa_version=None, **overrides) -> dict:
    """Settlement-period preparation payload."""
    # PRD §3.4: "its `period_start` must not fall before the contract's
    # `state_entered_at` instant". The composite fixtures set the logical clock
    # (PRD §2.10) and activate the contract at that instant, so the default
    # period opens after it rather than straddling it.
    payload = {
        "period_start": "2026-03-11T00:00:00Z",
        "period_end": "2026-04-11T00:00:00Z",
        "metered_kwh": 200000,
        "downtime_hours": 3.0,
        "customer_index_cents_per_therm": None,
        "customer_source_deadline_iso8601": "2026-03-25T00:00:00Z",
        "hourly_settlement": False,
        "expected_ppa_version": expected_ppa_version,
    }
    payload.update(overrides)
    return payload


# --- PpaAccrual (PRD §3.3) ---------------------------------------------------
def create_accrual_payload(ppa_id=None, site_id=None, **overrides) -> dict:
    """Accrual-posting payload."""
    payload = {
        "ppa_id": ppa_id,
        "site_id": site_id,
        "source_settlement_line_id": None,
        "accrual_type": "CHARGE_ACCRUAL",
        "amount_cents": 100000,
        "period_anchor_iso8601": "2026-03-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


# --- SettlementAllowance (PRD §3.6) -----------------------------------------
def issue_allowance_payload(expected_ppa_version=None, **overrides) -> dict:
    """Allowance-issuing payload."""
    payload = {
        "allowance_kind": "CAPACITY_ALLOWANCE",
        "amount_cents": 185000,
        "expected_ppa_version": expected_ppa_version,
    }
    payload.update(overrides)
    return payload