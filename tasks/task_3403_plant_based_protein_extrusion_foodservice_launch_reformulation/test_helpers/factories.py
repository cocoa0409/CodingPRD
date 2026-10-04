"""Payload factories — one per endpoint body, input fields only.

Field names are PRD-exact. Conditionally-forbidden keys are omitted entirely
when not applicable (e.g. co-man fields on an OWNED line, budget fields on an
LTO program); conditionally-required-nullable keys (supersedes_product_id)
are sent as explicit null by default, matching PRD section 3.4 ("the first
generation carries null").

Default values are test-chosen inputs; domain thresholds live in
constants.py. All default dates are reachable from the logical-clock default
2026-09-01T00:00:00Z (PRD section 2.4).
"""
from .constants import DEFAULT_CLOCK_START_ISO

DEFAULTS = {
    # Supplier agreement terms (mirror the recipes' canonical rails).
    "SUPPLIER_CODE": "SUP-1",
    "ISOLATE_TYPE": "PEA",
    "COMMITTED_VOLUME_KG": 10000,
    "BASE_PRICE_PER_KG_CENTS": 500,
    "PRICE_FLOOR_CENTS": 400,
    "PRICE_CAP_CENTS": 540,
    "AGREEMENT_START_DATE": "2026-08-01T00:00:00Z",
    "AGREEMENT_END_DATE": "2027-08-01T00:00:00Z",
    # Lot receipt.
    "LOT_CODE": "LOT-1",
    "LOT_QUANTITY_KG": 500,
    "RECEIVED_AT": DEFAULT_CLOCK_START_ISO,
    "MARKET_INDEX_PCT": 0.0,
    "MOISTURE_PCT": 6.5,
    "PROTEIN_CONTENT_PCT": 82.0,
    # QC release commercial inputs.
    "INVOICED_UNIT_COST_CENTS": 500,
    "ACTUAL_FREIGHT_CENTS_PER_KG": 35,
    # Production line.
    "LINE_CODE": "LINE-1",
    "HOURLY_CAPACITY_KG": 250,
    "SUPPORTED_ISOLATE_TYPES": ["PEA", "SOY"],
    "COMAN_PARTNER_NAME": "CoPack Industries",
    "MONTHLY_RESERVED_CAPACITY_KG": 5000,
    # Equivalence audit (comfortably passing scores).
    "TEXTURE_SCORE": 90,
    "AUDIT_MOISTURE_VARIANCE_PCT": 1.0,
    # Supplier qualification audit score (comfortably above both gates).
    "QUALIFY_AUDIT_SCORE": 90,
    # Product.
    "PRODUCT_CODE": "PROD-1",
    "GENERATION_NUMBER": 1,
    # Label (HIGH_PROTEIN claim is supported at protein_g 22 >= 20).
    "LABEL_VERSION_NUMBER": 1,
    "PROTEIN_G": 22,
    "FAT_G": 5,
    "SODIUM_MG": 320,
    "CLAIMS": ["HIGH_PROTEIN"],
    "INGREDIENT_STATEMENT": "Water, pea protein isolate",
    # Production run window (half-open; within the default program window).
    "PLANNED_QUANTITY_KG": 100,
    "SCHEDULED_START": "2026-09-05T08:00:00Z",
    "SCHEDULED_END": "2026-09-05T12:00:00Z",
    "CHANNEL": "RETAIL_FROZEN",
    "ACTUAL_QUANTITY_KG": 100,
    # Growth program window (contains the default logical clock).
    "PROGRAM_CODE": "PROG-1",
    "PARTNER_CODE": "CHAIN-1",
    "PROGRAM_WINDOW_START": "2026-09-01T00:00:00Z",
    "PROGRAM_WINDOW_END": "2026-10-31T23:59:59Z",
    "COMMITTED_CASES": 10,
    "DEDICATED_RUN_REQUIRED": True,
    "BUDGET_CENTS": 50000,
    "COUPONS_ISSUED": 1000,
    # Demand forecast.
    "WEEK_START": "2026-09-07T00:00:00Z",
    "FORECAST_CASES": 200,
    # Write-down.
    "WRITE_DOWN_QUANTITY_CASES": 1,
    "WRITE_DOWN_REASON": "RECALL",
}


# --- Clock -------------------------------------------------------------------

def set_clock_payload(to_iso8601=DEFAULT_CLOCK_START_ISO, **overrides) -> dict:
    payload = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload


# --- Supplier ----------------------------------------------------------------

def create_supplier_payload(**overrides) -> dict:
    payload = {
        "supplier_code": DEFAULTS["SUPPLIER_CODE"],
        "isolate_type": DEFAULTS["ISOLATE_TYPE"],
        "committed_volume_kg": DEFAULTS["COMMITTED_VOLUME_KG"],
        "base_price_per_kg_cents": DEFAULTS["BASE_PRICE_PER_KG_CENTS"],
        "price_floor_cents": DEFAULTS["PRICE_FLOOR_CENTS"],
        "price_cap_cents": DEFAULTS["PRICE_CAP_CENTS"],
        "agreement_start_date": DEFAULTS["AGREEMENT_START_DATE"],
        "agreement_end_date": DEFAULTS["AGREEMENT_END_DATE"],
    }
    payload.update(overrides)
    return payload


def supplier_transition_payload(dimension, target_status, audit_score=None,
                                **overrides) -> dict:
    payload = {"dimension": dimension, "target_status": target_status}
    if audit_score is not None:
        payload["audit_score"] = audit_score
    payload.update(overrides)
    return payload


# --- Ingredient lot ----------------------------------------------------------

def create_ingredient_lot_payload(supplier_id, **overrides) -> dict:
    payload = {
        "supplier_id": supplier_id,
        "lot_code": DEFAULTS["LOT_CODE"],
        "quantity_kg": DEFAULTS["LOT_QUANTITY_KG"],
        "received_at": DEFAULTS["RECEIVED_AT"],
        "market_index_pct": DEFAULTS["MARKET_INDEX_PCT"],
        "moisture_pct": DEFAULTS["MOISTURE_PCT"],
        "protein_content_pct": DEFAULTS["PROTEIN_CONTENT_PCT"],
    }
    payload.update(overrides)
    return payload


def qc_decision_payload(decision, invoiced_unit_cost_cents=None,
                        actual_freight_cents_per_kg=None, **overrides) -> dict:
    payload = {"decision": decision}
    if invoiced_unit_cost_cents is not None:
        payload["invoiced_unit_cost_cents"] = invoiced_unit_cost_cents
    if actual_freight_cents_per_kg is not None:
        payload["actual_freight_cents_per_kg"] = actual_freight_cents_per_kg
    payload.update(overrides)
    return payload


# --- Production line ---------------------------------------------------------

def create_production_line_payload(site_type="OWNED", coman_partner_name=None,
                                   monthly_reserved_capacity_kg=None,
                                   **overrides) -> dict:
    payload = {
        "line_code": DEFAULTS["LINE_CODE"],
        "site_type": site_type,
        "hourly_capacity_kg": DEFAULTS["HOURLY_CAPACITY_KG"],
        "supported_isolate_types": list(DEFAULTS["SUPPORTED_ISOLATE_TYPES"]),
    }
    # Co-man contract fields are forbidden on OWNED lines: omit unless given.
    if coman_partner_name is not None:
        payload["coman_partner_name"] = coman_partner_name
    if monthly_reserved_capacity_kg is not None:
        payload["monthly_reserved_capacity_kg"] = monthly_reserved_capacity_kg
    payload.update(overrides)
    return payload


def line_operational_transition_payload(target_status, **overrides) -> dict:
    payload = {"target_status": target_status}
    payload.update(overrides)
    return payload


def certification_audit_payload(texture_score=None, moisture_variance_pct=None,
                                **overrides) -> dict:
    payload = {
        "texture_score": (DEFAULTS["TEXTURE_SCORE"]
                          if texture_score is None else texture_score),
        "moisture_variance_pct": (DEFAULTS["AUDIT_MOISTURE_VARIANCE_PCT"]
                                  if moisture_variance_pct is None
                                  else moisture_variance_pct),
    }
    payload.update(overrides)
    return payload


# --- Product and label -------------------------------------------------------

def create_product_payload(supersedes_product_id=None, **overrides) -> dict:
    payload = {
        "product_code": DEFAULTS["PRODUCT_CODE"],
        "generation_number": DEFAULTS["GENERATION_NUMBER"],
        "isolate_type": DEFAULTS["ISOLATE_TYPE"],
        # PRD: the first generation carries null.
        "supersedes_product_id": supersedes_product_id,
    }
    payload.update(overrides)
    return payload


def product_lifecycle_payload(target_state, **overrides) -> dict:
    payload = {"target_state": target_state}
    payload.update(overrides)
    return payload


def create_label_version_payload(**overrides) -> dict:
    payload = {
        "version_number": DEFAULTS["LABEL_VERSION_NUMBER"],
        "protein_g": DEFAULTS["PROTEIN_G"],
        "fat_g": DEFAULTS["FAT_G"],
        "sodium_mg": DEFAULTS["SODIUM_MG"],
        "claims": list(DEFAULTS["CLAIMS"]),
        "ingredient_statement": DEFAULTS["INGREDIENT_STATEMENT"],
    }
    payload.update(overrides)
    return payload


def label_transition_payload(target_status, expected_product_version=None,
                             **overrides) -> dict:
    payload = {"target_status": target_status}
    if expected_product_version is not None:
        payload["expected_product_version"] = expected_product_version
    payload.update(overrides)
    return payload


# --- Production run ----------------------------------------------------------

def create_production_run_payload(production_line_id, product_id,
                                  label_version_id, expected_line_version,
                                  program_id=None, **overrides) -> dict:
    payload = {
        "production_line_id": production_line_id,
        "product_id": product_id,
        "label_version_id": label_version_id,
        "channel": DEFAULTS["CHANNEL"],
        "planned_quantity_kg": DEFAULTS["PLANNED_QUANTITY_KG"],
        "scheduled_start": DEFAULTS["SCHEDULED_START"],
        "scheduled_end": DEFAULTS["SCHEDULED_END"],
        "expected_line_version": expected_line_version,
    }
    # A run is dedicated exactly when program_id is present; omit otherwise.
    if program_id is not None:
        payload["program_id"] = program_id
    payload.update(overrides)
    return payload


def run_transition_payload(target_status, actual_quantity_kg=None,
                           **overrides) -> dict:
    payload = {"target_status": target_status}
    if actual_quantity_kg is not None:
        payload["actual_quantity_kg"] = actual_quantity_kg
    payload.update(overrides)
    return payload


# --- Growth program ----------------------------------------------------------

def create_lto_program_payload(product_id, **overrides) -> dict:
    """FOODSERVICE_LTO: partner_code + committed_cases required; budget_cents
    and coupons_issued must be null and are therefore omitted entirely."""
    payload = {
        "program_code": DEFAULTS["PROGRAM_CODE"],
        "program_type": "FOODSERVICE_LTO",
        "partner_code": DEFAULTS["PARTNER_CODE"],
        "product_id": product_id,
        "window_start": DEFAULTS["PROGRAM_WINDOW_START"],
        "window_end": DEFAULTS["PROGRAM_WINDOW_END"],
        "committed_cases": DEFAULTS["COMMITTED_CASES"],
        "dedicated_run_required": DEFAULTS["DEDICATED_RUN_REQUIRED"],
    }
    payload.update(overrides)
    return payload


def create_sampling_program_payload(product_id, **overrides) -> dict:
    """SAMPLING_DEMO: budget_cents required, coupons_issued optional (default
    0); partner_code and committed_cases must be null and are omitted."""
    payload = {
        "program_code": DEFAULTS["PROGRAM_CODE"],
        "program_type": "SAMPLING_DEMO",
        "product_id": product_id,
        "window_start": DEFAULTS["PROGRAM_WINDOW_START"],
        "window_end": DEFAULTS["PROGRAM_WINDOW_END"],
        "budget_cents": DEFAULTS["BUDGET_CENTS"],
        "coupons_issued": DEFAULTS["COUPONS_ISSUED"],
    }
    payload.update(overrides)
    return payload


def program_lifecycle_payload(target_status, final_coupons_redeemed=None,
                              **overrides) -> dict:
    payload = {"target_status": target_status}
    if final_coupons_redeemed is not None:
        payload["final_coupons_redeemed"] = final_coupons_redeemed
    payload.update(overrides)
    return payload


# --- Finished goods batch ----------------------------------------------------

def reserve_batch_payload(program_id, quantity_cases, **overrides) -> dict:
    payload = {"program_id": program_id, "quantity_cases": quantity_cases}
    payload.update(overrides)
    return payload


# --- Demand forecast ---------------------------------------------------------

def create_demand_forecast_payload(product_id, **overrides) -> dict:
    payload = {
        "product_id": product_id,
        "channel": DEFAULTS["CHANNEL"],
        "week_start": DEFAULTS["WEEK_START"],
        "forecast_cases": DEFAULTS["FORECAST_CASES"],
    }
    payload.update(overrides)
    return payload


def forecast_transition_payload(target_status, actual_cases=None,
                                **overrides) -> dict:
    payload = {"target_status": target_status}
    if actual_cases is not None:
        payload["actual_cases"] = actual_cases
    payload.update(overrides)
    return payload


# --- Inventory write-down ----------------------------------------------------

def create_write_down_payload(finished_goods_batch_id, quantity_cases, reason,
                              demand_forecast_id=None, **overrides) -> dict:
    payload = {
        "finished_goods_batch_id": finished_goods_batch_id,
        "quantity_cases": quantity_cases,
        "reason": reason,
    }
    # demand_forecast_id is mandatory for FORECAST_MISS and null otherwise.
    if demand_forecast_id is not None:
        payload["demand_forecast_id"] = demand_forecast_id
    payload.update(overrides)
    return payload


def write_down_decision_payload(decision, **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload
