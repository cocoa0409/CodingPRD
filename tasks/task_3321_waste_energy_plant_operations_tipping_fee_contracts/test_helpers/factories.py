"""Payload factories — one per entity, input fields only."""

MANIFEST_SEQ = {"n": 0}


def next_manifest_ref() -> str:
    MANIFEST_SEQ["n"] += 1
    return f"MAN-{MANIFEST_SEQ['n']:05d}"


def create_municipality_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "City of Alder",
        "population_served": 50000,
    }
    defaults.update(overrides)
    return defaults


def create_host_municipality_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "Host Town of Bracebridge",
        "population_served": 20000,
        "is_host_community": True,
        "priority_group": "HOST",
    }
    defaults.update(overrides)
    return defaults


def create_host_community_agreement_payload(**overrides) -> dict:
    defaults = {
        "municipality_id": None,
        "annual_payment_cents": 50000000,
        "payment_due_month": 3,
        "local_waste_priority_enabled": True,
        "effective_start": "2026-01-01T00:00:00Z",
        "effective_end": "2027-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_waste_supply_agreement_payload(**overrides) -> dict:
    defaults = {
        "municipality_id": None,
        "term_start": "2026-01-01T00:00:00Z",
        "term_end": "2027-01-01T00:00:00Z",
        "guaranteed_annual_tonnage": 1000,
        "tipping_fee_per_tonne_cents": 8000,
    }
    defaults.update(overrides)
    return defaults


def create_waste_delivery_payload(**overrides) -> dict:
    defaults = {
        "agreement_id": None,
        "manifest_ref": next_manifest_ref(),
        "tonnes": 10,
        "heating_value_mj_per_kg": 10,
        "delivered_at": "2026-09-02T08:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_boiler_payload(**overrides) -> dict:
    defaults = {
        "name": "Boiler-A",
        "max_thermal_capacity_mw": 50,
        "max_steam_tph": 60,
    }
    defaults.update(overrides)
    return defaults


def create_outage_window_payload(**overrides) -> dict:
    defaults = {
        "boiler_id": None,
        "starts_at": "2026-09-05T00:00:00Z",
        "ends_at": "2026-09-08T00:00:00Z",
        "reason": "scheduled maintenance",
        "kind": "PLANNED",
    }
    defaults.update(overrides)
    return defaults


def create_diversion_plan_payload(**overrides) -> dict:
    defaults = {
        "outage_id": None,
        "max_diversion_tpd": 200,
    }
    defaults.update(overrides)
    return defaults


def create_diversion_leg_payload(**overrides) -> dict:
    defaults = {
        "receiving_facility_name": "County Landfill 9",
        "planned_tonnes": 400,
    }
    defaults.update(overrides)
    return defaults


def create_daily_throughput_report_payload(**overrides) -> dict:
    defaults = {
        "report_date": "2026-09-11",
        "waste_processed_tonnes": 500,
        "avg_heating_value_mj_per_kg": 9.0,
        "operating_hours": 24,
    }
    defaults.update(overrides)
    return defaults


def create_power_purchase_agreement_payload(**overrides) -> dict:
    defaults = {
        "counterparty_name": "GridCo",
        "kind": "PPA",
        "energy_rate_cents_per_mwh": 7500,
        "capacity_payment_cents_per_mw_month": 200000,
        "contracted_mw": 60,
        "term_start": "2026-01-01T00:00:00Z",
        "term_end": "2027-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_merchant_ppa_payload(**overrides) -> dict:
    defaults = {
        "counterparty_name": "SpotMart",
        "kind": "MERCHANT",
        "energy_rate_cents_per_mwh": 7000,
        "capacity_payment_cents_per_mw_month": 0,
        "contracted_mw": 10,
        "term_start": "2026-01-01T00:00:00Z",
        "term_end": "2027-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_energy_delivery_payload(**overrides) -> dict:
    defaults = {
        "ppa_id": None,
        "period_start": "2026-10-01T00:00:00Z",
        "period_end": "2026-10-11T00:00:00Z",
        "delivered_mwh": 500,
    }
    defaults.update(overrides)
    return defaults


def create_metals_recovery_contract_payload(**overrides) -> dict:
    defaults = {
        "processor_name": "FerroProc",
        "ferrous_recovery_pct": 0.10,
        "nonferrous_recovery_pct": 0.02,
        "processing_fee_cents_per_tonne": 2500,
    }
    defaults.update(overrides)
    return defaults


def create_metals_recovery_batch_payload(**overrides) -> dict:
    defaults = {
        "contract_id": None,
        "ash_input_tonnes": 100,
        "ferrous_price_cents_per_tonne": 30000,
        "nonferrous_price_cents_per_tonne": 120000,
    }
    defaults.update(overrides)
    return defaults


def create_landfill_payload(**overrides) -> dict:
    defaults = {
        "name": "AshMonofill-1",
        "permit_number": "P-100",
        "remaining_capacity_tonnes": 1000,
        "daily_receipt_limit_tonnes": 500,
    }
    defaults.update(overrides)
    return defaults


def create_ash_shipment_payload(**overrides) -> dict:
    defaults = {
        "landfill_id": None,
        "tonnes": 10,
        "shipped_on": "2026-09-06",
        "disposal_fee_cents_per_tonne": 4000,
    }
    defaults.update(overrides)
    return defaults


def create_ash_test_payload(**overrides) -> dict:
    defaults = {
        "parameter": "TCLP-lead",
        "measured_value": 4.0,
        "limit_value": 5.0,
    }
    defaults.update(overrides)
    return defaults


def create_emissions_permit_payload(**overrides) -> dict:
    defaults = {
        "pollutant": "NOx",
        "hourly_limit": 200,
        "daily_limit": 150,
        "rolling_avg_window_hours": 24,
    }
    defaults.update(overrides)
    return defaults


def create_emissions_reading_payload(**overrides) -> dict:
    defaults = {
        "permit_id": None,
        "value": 100,
        "measured_at": "2026-09-02T06:00:00Z",
    }
    defaults.update(overrides)
    return defaults
