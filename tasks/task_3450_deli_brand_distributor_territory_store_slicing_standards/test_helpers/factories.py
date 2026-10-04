"""Payload factories — one per entity, input fields only (PRD §3, §4).

Codes default to uuid-suffixed values so multiple creates inside one test
never collide on the unique-code rule; pass explicit codes when a test
needs deterministic values.
"""
import uuid

from .constants import (
    DEFAULT_DELIVERY_WEEK,
    DEFAULT_PROMO_END_DATE,
    DEFAULT_PROMO_START_DATE,
    DEFAULT_RUN_WINDOW_END,
    DEFAULT_RUN_WINDOW_START,
    DEFAULT_VISIT_WINDOW_END,
    DEFAULT_VISIT_WINDOW_START,
)


def _uniq(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def create_distributor_payload(**overrides):
    defaults = {"code": _uniq("D"), "name": "Test Distributor"}
    defaults.update(overrides)
    return defaults


def create_territory_payload(**overrides):
    defaults = {"code": _uniq("T"), "name": "Test Territory", "region": "NE"}
    defaults.update(overrides)
    return defaults


def create_grant_payload(distributor_id, expected_territory_version):
    return {
        "distributor_id": distributor_id,
        "expected_territory_version": expected_territory_version,
    }


def create_account_payload(territory_id, **overrides):
    defaults = {
        "name": "Test Store",
        "channel": "INDEPENDENT_GROCER",
        "territory_id": territory_id,
    }
    defaults.update(overrides)
    return defaults


def create_review_account_payload(decision="APPROVE"):
    return {"decision": decision}


def create_product_payload(**overrides):
    defaults = {
        "code": _uniq("P"),
        "name": "Test Product",
        "base_price_cents": 500,
        "shelf_life_opened_hours": 72,
        "shelf_life_unopened_days": 30,
        "allergen_tags": [],
    }
    defaults.update(overrides)
    return defaults


def create_authorization_payload(account_id, product_id):
    return {"account_id": account_id, "product_id": product_id}


def create_order_payload(lines, delivery_week=DEFAULT_DELIVERY_WEEK):
    """lines: list of {"product_id": ..., "qty_requested": ...}."""
    return {"delivery_week": delivery_week, "lines": list(lines)}


def order_line_request(product_id, qty_requested):
    return {"product_id": product_id, "qty_requested": qty_requested}


def create_plant_payload(**overrides):
    defaults = {"code": _uniq("PL"), "name": "Test Plant"}
    defaults.update(overrides)
    return defaults


def create_production_run_payload(plant_id, product_id, **overrides):
    defaults = {
        "plant_id": plant_id,
        "line_code": "L1",
        "product_id": product_id,
        "window_start": DEFAULT_RUN_WINDOW_START,
        "window_end": DEFAULT_RUN_WINDOW_END,
        "capacity_units": 100,
        "planned_units": 10,
    }
    defaults.update(overrides)
    return defaults


def create_delivery_payload(order_id, account_id, lines):
    """lines: list of {"lot_id": ..., "qty": ...}."""
    return {"order_id": order_id, "account_id": account_id, "lines": list(lines)}


def delivery_line(lot_id, qty):
    return {"lot_id": lot_id, "qty": qty}


def create_service_visit_payload(account_id, **overrides):
    defaults = {
        "account_id": account_id,
        "window_start": DEFAULT_VISIT_WINDOW_START,
        "window_end": DEFAULT_VISIT_WINDOW_END,
    }
    defaults.update(overrides)
    return defaults


def create_submit_visit_payload(score=90, rotation_compliant=True,
                                slicer_presentation_ok=True, cleaned_slicer_ids=None):
    payload = {
        "score": score,
        "rotation_compliant": rotation_compliant,
        "slicer_presentation_ok": slicer_presentation_ok,
    }
    if cleaned_slicer_ids is not None:
        payload["cleaned_slicer_ids"] = list(cleaned_slicer_ids)
    return payload


def create_review_visit_payload(verdict="VERIFY"):
    return {"verdict": verdict}


def create_slicer_payload(account_id, **overrides):
    defaults = {"account_id": account_id, "label": _uniq("S")}
    defaults.update(overrides)
    return defaults


def create_opened_log_payload(product_id, slicer_id, opened_at=None):
    payload = {"product_id": product_id, "slicer_id": slicer_id}
    if opened_at is not None:
        payload["opened_at"] = opened_at
    return payload


def create_certification_payload(account_id, associate_name="Associate",
                                 slicing_module_passed=True,
                                 allergen_module_passed=True):
    return {
        "account_id": account_id,
        "associate_name": associate_name,
        "slicing_module_passed": slicing_module_passed,
        "allergen_module_passed": allergen_module_passed,
    }


def create_promo_program_payload(account_id, product_id, **overrides):
    defaults = {
        "account_id": account_id,
        "product_id": product_id,
        "promo_price_cents": 900,
        "start_date": DEFAULT_PROMO_START_DATE,
        "end_date": DEFAULT_PROMO_END_DATE,
        "budget_cents": 40000,
        "estimated_units": 10,
    }
    defaults.update(overrides)
    return defaults


def create_settlement_payload(redemption_lines):
    """redemption_lines: list of {"period": "YYYY-MM-DD", "units": int}."""
    return {"redemption_lines": list(redemption_lines)}


def redemption_line(period, units):
    return {"period": period, "units": units}


def create_incident_payload(plant_id, **overrides):
    defaults = {
        "plant_id": plant_id,
        "title": "Test incident",
        "severity": "HIGH",
        "affected_run_ids": [],
    }
    defaults.update(overrides)
    return defaults


def create_incident_transition_payload(to, resolution_outcome=None):
    payload = {"to": to}
    if resolution_outcome is not None:
        payload["resolution_outcome"] = resolution_outcome
    return payload
