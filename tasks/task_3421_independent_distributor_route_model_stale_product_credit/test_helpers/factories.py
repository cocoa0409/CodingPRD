"""Payload factories — one per entity/action, input fields only (PRD §3, §4).

Computed and system-managed fields (units_total, version, statuses, timestamps)
are never placed into request payloads here; the server owns them.
"""
from typing import List, Optional

from .constants import (
    DEFAULT_CLOCK_UTC,
    FINANCED_AMOUNT_CENTS,
    FINANCING_ANNUAL_RATE,
    FINANCING_TERM_WEEKS,
    STANDARD_PRODUCT_CATALOG,
    TEST_DEFAULTS,
)


# --- Clock (PRD §2.4) ----------------------------------------------------------

def clock_payload(current_utc: str = DEFAULT_CLOCK_UTC) -> dict:
    return {"current_utc": current_utc}


# --- Bakery (PRD §3.1) ----------------------------------------------------------

def catalog_entry(sku: str, display_name: str, shelf_life_days: int,
                  list_price_cents: int) -> dict:
    return {
        "sku": sku,
        "display_name": display_name,
        "shelf_life_days": shelf_life_days,
        "list_price_cents": list_price_cents,
    }


def create_bakery_payload(**overrides) -> dict:
    defaults = {
        "name": TEST_DEFAULTS["BAKERY_NAME"],
        "daily_capacity_units": TEST_DEFAULTS["BAKERY_CAPACITY_UNITS"],
        "product_catalog": [dict(e) for e in STANDARD_PRODUCT_CATALOG],
    }
    defaults.update(overrides)
    return defaults


# --- Production day (PRD §3.3) ---------------------------------------------------

def create_production_day_payload(date: str,
                                  capacity_override_units: Optional[int] = None
                                  ) -> dict:
    payload = {"date": date}
    if capacity_override_units is not None:
        payload["capacity_override_units"] = capacity_override_units
    return payload


# --- Territory (PRD §3.1) ---------------------------------------------------------

def create_territory_payload(**overrides) -> dict:
    defaults = {
        "area_code": TEST_DEFAULTS["TERRITORY_AREA_CODE"],
        "list_price_cents": TEST_DEFAULTS["TERRITORY_LIST_PRICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


# --- Distributor (PRD §3.1) --------------------------------------------------------

def create_distributor_payload(**overrides) -> dict:
    defaults = {
        "legal_name": TEST_DEFAULTS["DISTRIBUTOR_LEGAL_NAME"],
        "credit_limit_cents": TEST_DEFAULTS["DISTRIBUTOR_CREDIT_LIMIT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


# --- Route agreement (PRD §3.1) -----------------------------------------------------

def create_agreement_payload(territory_id: str, distributor_id: str,
                             bakery_id: str, **overrides) -> dict:
    defaults = {
        "territory_id": territory_id,
        "distributor_id": distributor_id,
        "bakery_id": bakery_id,
        "purchase_price_cents": TEST_DEFAULTS["PURCHASE_PRICE_CENTS"],
        "financed_amount_cents": 0,
        "discount_pct": TEST_DEFAULTS["DISCOUNT_PCT"],
        "start_date": TEST_DEFAULTS["AGREEMENT_START_DATE"],
        "end_date": TEST_DEFAULTS["AGREEMENT_END_DATE"],
    }
    defaults.update(overrides)
    return defaults


def suspend_agreement_payload(reason: str = "SERVICE_DEFAULT") -> dict:
    return {"reason": reason}


def reinstate_agreement_payload(resolution: Optional[str] = None) -> dict:
    payload: dict = {}
    if resolution is not None:
        payload["resolution"] = resolution
    return payload


def exit_agreement_payload(mode: str = "VOLUNTARY") -> dict:
    return {"mode": mode}


# --- Financing plan (PRD §3.2) ---------------------------------------------------------

def create_financing_plan_payload(expected_agreement_version: int,
                                  **overrides) -> dict:
    defaults = {
        "financier_type": "COMPANY",
        "principal_cents": FINANCED_AMOUNT_CENTS,
        "annual_interest_rate": FINANCING_ANNUAL_RATE,
        "term_weeks": FINANCING_TERM_WEEKS,
        "expected_agreement_version": expected_agreement_version,
    }
    defaults.update(overrides)
    return defaults


def financing_payment_payload(amount_cents: int) -> dict:
    return {"amount_cents": amount_cents}


# --- Retail account and audits (PRD §3.5) -------------------------------------------------

def create_retail_account_payload(**overrides) -> dict:
    defaults = {
        "store_name": TEST_DEFAULTS["STORE_NAME"],
        "delivery_weekdays": ["MON", "WED", "FRI"],
    }
    defaults.update(overrides)
    return defaults


def audit_payload(audit_date: str, shelf_stock_score: int,
                  rotation_score: int, display_score: int) -> dict:
    return {
        "audit_date": audit_date,
        "shelf_stock_score": shelf_stock_score,
        "rotation_score": rotation_score,
        "display_score": display_score,
    }


# --- Daily order (PRD §3.3, §3.4) -------------------------------------------------------------

def order_line(sku: str, qty: int) -> dict:
    return {"sku": sku, "qty": qty}


def create_order_payload(delivery_date: str, lines: List[dict]) -> dict:
    return {"delivery_date": delivery_date, "lines": lines}


def confirm_order_payload(expected_production_day_version: int) -> dict:
    return {"expected_production_day_version": expected_production_day_version}


def record_delivery_payload(delivered_lines: List[dict]) -> dict:
    return {"delivered_lines": delivered_lines}


def reconcile_payload(verified_lines: List[dict]) -> dict:
    return {"verified_lines": verified_lines}


# --- Stale return claim (PRD §3.6) ----------------------------------------------------------------

def claim_item(sku: str, delivery_date: str, pulled_qty: int,
               pull_date: str) -> dict:
    return {
        "sku": sku,
        "delivery_date": delivery_date,
        "pulled_qty": pulled_qty,
        "pull_date": pull_date,
    }


def create_claim_payload(items: List[dict]) -> dict:
    return {"items": items}


def decide_claim_payload(decision: str,
                         decision_note: Optional[str] = None) -> dict:
    payload: dict = {"decision": decision}
    if decision_note is not None:
        payload["decision_note"] = decision_note
    return payload


def resubmit_claim_payload(items: List[dict]) -> dict:
    return {"items": items}
