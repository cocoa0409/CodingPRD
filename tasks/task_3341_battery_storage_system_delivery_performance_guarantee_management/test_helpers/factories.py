"""Payload factories — one per entity, input fields only (PRD §3)."""

DEFAULTS = {
    "PROJECT_NAME": "Test BESS",
    "RATED_POWER_MW": 10,
    "RATED_ENERGY_MWH": 40,
    "BUDGET_CENTS": 20_000_000,
    "CONTRACTED_POWER_MW": 10,
    "CONTRACTED_ENERGY_MWH": 40,
    "GUARANTEED_CAPACITY_MWH": 38,
    "GUARANTEED_RTE_PCT": 0.88,
    "PRICE_PER_MWH_CENTS": 300_000,
    "LD_RATE_PER_DAY_CENTS": 40_000,
    "LD_CAP_CENTS": 1_200_000,
    "GUARANTEED_DELIVERY_DATE": "2026-10-01T00:00:00Z",
    "LONGSTOP_DATE": "2026-12-01T00:00:00Z",
    "ANNUAL_FEE_CENTS": 2_000_000,
    "LTSA_START": "2026-08-01T00:00:00Z",
    "LTSA_END": "2027-08-01T00:00:00Z",
}


def create_project_payload(**overrides):
    payload = {
        "name": DEFAULTS["PROJECT_NAME"],
        "market_application": "ENERGY_ARBITRAGE",
        "duty_cycle_profile": "ONE_CYCLE_DAILY",
        "rated_power_mw": DEFAULTS["RATED_POWER_MW"],
        "rated_energy_mwh": DEFAULTS["RATED_ENERGY_MWH"],
        "budget_cents": DEFAULTS["BUDGET_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_esa_payload(project_id, **overrides):
    payload = {
        "project_id": project_id,
        "contracted_power_mw": DEFAULTS["CONTRACTED_POWER_MW"],
        "contracted_energy_mwh": DEFAULTS["CONTRACTED_ENERGY_MWH"],
        "guaranteed_capacity_mwh": DEFAULTS["GUARANTEED_CAPACITY_MWH"],
        "guaranteed_rte_pct": DEFAULTS["GUARANTEED_RTE_PCT"],
        "price_per_mwh_cents": DEFAULTS["PRICE_PER_MWH_CENTS"],
        "ld_rate_per_day_cents": DEFAULTS["LD_RATE_PER_DAY_CENTS"],
        "ld_cap_cents": DEFAULTS["LD_CAP_CENTS"],
        "guaranteed_delivery_date": DEFAULTS["GUARANTEED_DELIVERY_DATE"],
        "longstop_date": DEFAULTS["LONGSTOP_DATE"],
    }
    payload.update(overrides)
    return payload


def create_milestone_payload(esa_id, **overrides):
    payload = {
        "esa_id": esa_id,
        "kind": "DELIVERY",
        "planned_date": "2026-10-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_permit_payload(project_id, **overrides):
    payload = {
        "project_id": project_id,
        "permit_type": "THERMAL_RUNAWAY_PLAN",
        "authority_reference": "AHJ-REF-1",
    }
    payload.update(overrides)
    return payload


def create_performance_test_payload(project_id, **overrides):
    payload = {
        "project_id": project_id,
        "test_type": "CAPACITY_TEST",
        "window_start": "2026-09-01T00:00:00Z",
        "window_end": "2026-10-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_augmentation_payload(project_id, **overrides):
    payload = {
        "project_id": project_id,
        "planned_window_start": "2026-09-01T00:00:00Z",
        "planned_window_end": "2026-10-01T00:00:00Z",
        "added_capacity_mwh": 2,
    }
    payload.update(overrides)
    return payload


def create_service_agreement_payload(project_id, **overrides):
    payload = {
        "project_id": project_id,
        "annual_fee_cents": DEFAULTS["ANNUAL_FEE_CENTS"],
        "covers_monitoring": True,
        "covers_maintenance": True,
        "covers_spare_parts": True,
        "covers_software_updates": True,
        "start_date": DEFAULTS["LTSA_START"],
        "end_date": DEFAULTS["LTSA_END"],
    }
    payload.update(overrides)
    return payload


def create_spare_part_order_payload(service_agreement_id, expected_version, **overrides):
    payload = {
        "service_agreement_id": service_agreement_id,
        "part_description": "Replacement part",
        "part_cost_cents": 100_000,
        "expected_service_agreement_version": expected_version,
    }
    payload.update(overrides)
    return payload


def create_warranty_claim_payload(esa_id, **overrides):
    payload = {
        "esa_id": esa_id,
        "defect_type": "CELL_DEFECT",
        "claimed_capacity_loss_mwh": 0.05,
    }
    payload.update(overrides)
    return payload


def create_bid_session_payload(project_id, **overrides):
    payload = {
        "project_id": project_id,
        "market": "DAY_AHEAD",
        "window_start": "2026-09-05T00:00:00Z",
        "window_end": "2026-09-05T04:00:00Z",
        "offer_mwh": 20,
        "offer_price_cents_per_mwh": 9_000,
    }
    payload.update(overrides)
    return payload
