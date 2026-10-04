"""Payload factories — one per creatable resource, input fields only."""
import itertools

from .constants import (
    DEFAULT_CANCELLATION_NOTICE_DAYS,
    DEFAULT_COMMODITY_MULTIPLIER,
    DEFAULT_DEMURRAGE_RATE_PER_DAY,
    DEFAULT_ESTIMATED_INDEX_PRICE,
    DEFAULT_FIXED_FEE,
    DEFAULT_TOLERANCE_PCT,
)

_counter = itertools.count(1)


def _seq() -> int:
    return next(_counter)


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "legal_name": f"Test Buyer {_seq()}",
        "credit_rating": "A",
    }
    defaults.update(overrides)
    return defaults


def create_spa_payload(customer_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "contract_year_start": 2027,
        "term_years": 5,
        "annual_contract_quantity_mmbtu": 36000000,
        "fixed_liquefaction_fee_usd_per_mmbtu": DEFAULT_FIXED_FEE,
        "commodity_multiplier": DEFAULT_COMMODITY_MULTIPLIER,
        "commodity_index": "HENRY_HUB",
        "destination_flexibility": "FOB",
        "title_transfer_point": "LOADING_FLANGE",
        "cancellation_notice_days": DEFAULT_CANCELLATION_NOTICE_DAYS,
        "tolerance_pct": DEFAULT_TOLERANCE_PCT,
        "estimated_index_price_usd_per_mmbtu": DEFAULT_ESTIMATED_INDEX_PRICE,
    }
    defaults.update(overrides)
    return defaults


def create_train_payload(**overrides) -> dict:
    defaults = {
        "name": f"Train {_seq()}",
        "design_capacity_mtpa": 5.0,
        "daily_capacity_mmbtu": 700000,
        "commissioning_cargoes_required": 0,
    }
    defaults.update(overrides)
    return defaults


def create_adp_payload(spa_id: str, expected_spa_version: int, **overrides) -> dict:
    defaults = {
        "spa_id": spa_id,
        "contract_year": 2027,
        "expected_spa_version": expected_spa_version,
    }
    defaults.update(overrides)
    return defaults


def create_cargo_slot_payload(**overrides) -> dict:
    defaults = {
        "window_start": "2027-06-01T00:00:00Z",
        "window_end": "2027-06-08T00:00:00Z",
        "quantity_mmbtu": 3600000,
    }
    defaults.update(overrides)
    return defaults


def create_vessel_nomination_payload(expected_cargo_slot_version: int, **overrides) -> dict:
    defaults = {
        "vessel_name": f"Gas Carrier {_seq()}",
        "imo_number": f"9{_seq():06d}"[-7:],
        "vessel_loa_m": 295,
        "vessel_dwt_t": 97000,
        "demurrage_rate_usd_per_day": DEFAULT_DEMURRAGE_RATE_PER_DAY,
        "expected_cargo_slot_version": expected_cargo_slot_version,
    }
    defaults.update(overrides)
    return defaults


def create_berth_payload(**overrides) -> dict:
    defaults = {
        "name": f"Berth {_seq()}",
        "max_loa_m": 320,
        "max_dwt_t": 120000,
    }
    defaults.update(overrides)
    return defaults


def create_pipeline_payload(**overrides) -> dict:
    defaults = {
        "name": f"PL-{_seq()}",
        "daily_capacity_mmbtu": 500000,
    }
    defaults.update(overrides)
    return defaults


def create_day_schedule_payload(**overrides) -> dict:
    defaults = {
        "gas_day": "2027-06-03",
        "capacity_mmbtu": 100000,
    }
    defaults.update(overrides)
    return defaults


def create_nomination_payload(cargo_slot_id: str, nominated_mmbtu: int, **overrides) -> dict:
    defaults = {
        "cargo_slot_id": cargo_slot_id,
        "nominated_mmbtu": nominated_mmbtu,
    }
    defaults.update(overrides)
    return defaults


def create_resale_payload(offered_volume_mmbtu: int, **overrides) -> dict:
    defaults = {"offered_volume_mmbtu": offered_volume_mmbtu}
    defaults.update(overrides)
    return defaults


def create_turnaround_payload(**overrides) -> dict:
    defaults = {
        "planned_start_date": "2027-03-01",
        "planned_end_date": "2027-03-05",
    }
    defaults.update(overrides)
    return defaults


def declare_cod_payload(**overrides) -> dict:
    defaults = {
        "cod_date": "2026-12-01",
        "performance_test_passed": True,
    }
    defaults.update(overrides)
    return defaults


def laytime_statement_payload(**overrides) -> dict:
    defaults = {"billing_basis": "SOF_BASIS"}
    defaults.update(overrides)
    return defaults
