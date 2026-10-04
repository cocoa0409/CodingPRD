"""Payload factories — one per creation/action endpoint, input fields only.

Field names, types, required/optional sets, and enum members follow the PRD
verbatim. Scalar uniqueness rules (brand/plant/retailer name, item sku_code,
cycle period_code) make collisions fail with ERR_DUPLICATE, so factories mint
auto-unique names/codes unless the caller pins one explicitly.

`salvageable` is the only optional item field (PRD default false): the factory
omits it unless the caller passes salvageable explicitly, so a default payload
exercises the server-side default.
"""
import itertools

from .constants import TEST_DEFAULTS

_counter = itertools.count(1)
_UNSET = object()


def _unique(prefix: str) -> str:
    return f"{prefix}-{next(_counter)}"


# ─── Platform clock (PRD §2.4) ───────────────────────────────────────────────

def create_clock_payload(to_iso8601: str, **overrides) -> dict:
    payload = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload


# ─── Foundation entities ─────────────────────────────────────────────────────

def create_brand_payload(**overrides) -> dict:
    payload = {
        "name": _unique("B"),
        "category_name": TEST_DEFAULTS["BRAND_CATEGORY"],
        "core_flag": True,
        "private_label_share_pct": TEST_DEFAULTS["BRAND_PL_SHARE_PCT"],
        "annual_net_revenue_cents": TEST_DEFAULTS["BRAND_ANNUAL_NET_REVENUE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_plant_payload(**overrides) -> dict:
    payload = {
        "name": _unique("P"),
        "quarterly_capacity_units": TEST_DEFAULTS["PLANT_CAPACITY_UNITS"],
    }
    payload.update(overrides)
    return payload


def create_retailer_payload(**overrides) -> dict:
    payload = {
        "name": _unique("R"),
        "risk_rating": TEST_DEFAULTS["RETAILER_RISK_RATING"],
    }
    payload.update(overrides)
    return payload


def create_item_payload(brand_id=_UNSET, primary_plant_id=_UNSET, **overrides) -> dict:
    payload = {
        "sku_code": _unique("SKU"),
        "annual_units": TEST_DEFAULTS["ITEM_ANNUAL_UNITS"],
        "unit_net_revenue_cents": TEST_DEFAULTS["ITEM_UNIT_NET_REVENUE_CENTS"],
        "unit_cost_cents": TEST_DEFAULTS["ITEM_UNIT_COST_CENTS"],
        "units_on_hand": TEST_DEFAULTS["ITEM_UNITS_ON_HAND"],
    }
    if brand_id is not _UNSET:
        payload["brand_id"] = brand_id
    if primary_plant_id is not _UNSET:
        payload["primary_plant_id"] = primary_plant_id
    # Optional field: only emitted when the caller asks for it (PRD default
    # false must remain server-applied when omitted).
    if "salvageable" in overrides:
        payload["salvageable"] = overrides.pop("salvageable")
    payload.update(overrides)
    return payload


# ─── Rationalization cases & sell-down ───────────────────────────────────────

def create_rationalization_case_payload(item_id, **overrides) -> dict:
    payload = {"item_id": item_id}
    payload.update(overrides)
    return payload


def create_decide_payload(decision="APPROVE", **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def create_sell_down_payload(units_sold=1, expected_item_version=_UNSET, **overrides) -> dict:
    payload = {"units_sold": units_sold}
    if expected_item_version is not _UNSET:
        payload["expected_item_version"] = expected_item_version
    payload.update(overrides)
    return payload


# ─── Divestitures / TSA signing ──────────────────────────────────────────────

def create_divestiture_payload(brand_id=_UNSET, **overrides) -> dict:
    payload = {
        "acquirer_name": TEST_DEFAULTS["ACQUIRER_NAME"],
        "headline_price_cents": TEST_DEFAULTS["HEADLINE_PRICE_CENTS"],
        "expected_close_date": TEST_DEFAULTS["EXPECTED_CLOSE_DATE"],
    }
    if brand_id is not _UNSET:
        payload["brand_id"] = brand_id
    payload.update(overrides)
    return payload


def create_sign_spa_payload(**overrides) -> dict:
    payload = {
        "tsa_monthly_fee_cents": TEST_DEFAULTS["TSA_MONTHLY_FEE_CENTS"],
        "tsa_start_date": TEST_DEFAULTS["TSA_START_DATE"],
        "tsa_end_date": TEST_DEFAULTS["TSA_END_DATE"],
    }
    payload.update(overrides)
    return payload


# ─── Plant closures ──────────────────────────────────────────────────────────

def create_announce_closure_payload(closure_date=None, **overrides) -> dict:
    payload = {"closure_date": closure_date or TEST_DEFAULTS["CLOSURE_DATE"]}
    payload.update(overrides)
    return payload


# ─── Product transfers & qualification runs ──────────────────────────────────

def create_product_transfer_payload(
    item_id=_UNSET, source_plant_id=_UNSET, target_plant_id=_UNSET, **overrides
) -> dict:
    payload = {}
    if item_id is not _UNSET:
        payload["item_id"] = item_id
    if source_plant_id is not _UNSET:
        payload["source_plant_id"] = source_plant_id
    if target_plant_id is not _UNSET:
        payload["target_plant_id"] = target_plant_id
    payload.update(overrides)
    return payload


def create_qualification_run_payload(**overrides) -> dict:
    payload = {
        "run_date": TEST_DEFAULTS["RUN_DATE"],
        "units_produced": TEST_DEFAULTS["RUN_UNITS_PRODUCED"],
        "units_rejected": TEST_DEFAULTS["RUN_UNITS_REJECTED_CLEAR_PASS"],
    }
    payload.update(overrides)
    return payload


# ─── Combined negotiations ───────────────────────────────────────────────────

def create_brand_term(brand_id, baseline_facings=100, proposed_facings=90) -> dict:
    return {
        "brand_id": brand_id,
        "baseline_facings": baseline_facings,
        "proposed_facings": proposed_facings,
    }


def create_combined_negotiation_payload(
    retailer_id=_UNSET, brand_terms=_UNSET, **overrides
) -> dict:
    payload = {
        "period_code": TEST_DEFAULTS["NEGOTIATION_PERIOD_CODE"],
        "effective_from": TEST_DEFAULTS["NEGOTIATION_EFFECTIVE_FROM"],
        "effective_to": TEST_DEFAULTS["NEGOTIATION_EFFECTIVE_TO"],
    }
    if retailer_id is not _UNSET:
        payload["retailer_id"] = retailer_id
    if brand_terms is not _UNSET:
        payload["brand_terms"] = brand_terms
    payload.update(overrides)
    return payload


def create_negotiation_respond_payload(response="ACCEPT", **overrides) -> dict:
    payload = {"response": response}
    payload.update(overrides)
    return payload


# ─── Capital cycles & innovation projects ────────────────────────────────────

def create_capital_cycle_payload(**overrides) -> dict:
    payload = {
        "period_code": _unique("CYCLE"),
        "total_capital_cents": TEST_DEFAULTS["CYCLE_TOTAL_CAPITAL_CENTS"],
        "window_start": TEST_DEFAULTS["CYCLE_WINDOW_START"],
        "window_end": TEST_DEFAULTS["CYCLE_WINDOW_END"],
    }
    payload.update(overrides)
    return payload


def create_innovation_project_payload(
    brand_id=_UNSET, funding_cycle_id=_UNSET, **overrides
) -> dict:
    payload = {
        "title": _unique("PROJ"),
        "requested_capital_cents": TEST_DEFAULTS["PROJECT_REQUESTED_CAPITAL_CENTS"],
        "expected_revenue_cents_year3": TEST_DEFAULTS["PROJECT_EXPECTED_REVENUE_Y3_CENTS"],
        "strategic_fit_score": TEST_DEFAULTS["PROJECT_STRATEGIC_FIT_SCORE"],
    }
    if brand_id is not _UNSET:
        payload["brand_id"] = brand_id
    if funding_cycle_id is not _UNSET:
        payload["funding_cycle_id"] = funding_cycle_id
    payload.update(overrides)
    return payload
