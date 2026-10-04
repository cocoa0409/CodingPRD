"""Payload factories: one per writable endpoint, input fields only.

Registration payloads mint unique emails automatically so that repeated
registrations inside one test never collide on the uniqueness rule.
"""

import itertools
from typing import Any, Dict, List, Optional

_counter = itertools.count(1)


def _seq() -> int:
    return next(_counter)


# ── Clock and sweep ────────────────────────────────────────────────────────

def clock_payload(current_utc: str) -> Dict[str, Any]:
    return {"current_utc": current_utc}


# ── Schools ────────────────────────────────────────────────────────────────

def school_payload(**overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "name": "Ridgeview Elementary",
        "state_code": "TX",
        "district": "Ridgeview ISD",
        "poverty_pct": 80.0,
        "ell_pct": 90.0,
    }
    defaults.update(overrides)
    return defaults


# ── Teachers ───────────────────────────────────────────────────────────────

def teacher_payload(school_id: str, **overrides: Any) -> Dict[str, Any]:
    n = _seq()
    defaults: Dict[str, Any] = {
        "full_name": f"Teacher {n}",
        "email": f"teacher{n}@example.org",
        "school_id": school_id,
        "subjects_taught": ["LITERACY"],
    }
    defaults.update(overrides)
    return defaults


def employment_review_payload(action: str) -> Dict[str, Any]:
    return {"action": action}


# ── Vendors and catalog ────────────────────────────────────────────────────

def vendor_payload(**overrides: Any) -> Dict[str, Any]:
    n = _seq()
    defaults: Dict[str, Any] = {
        "name": f"SchoolMart {n}",
        "ship_from_state": "TX",
        "contact_email": f"ops{n}@schoolmart.example",
    }
    defaults.update(overrides)
    return defaults


def catalog_item_payload(**overrides: Any) -> Dict[str, Any]:
    n = _seq()
    defaults: Dict[str, Any] = {
        "sku": f"SM-BOOK-{n}",
        "name": "Leveled Readers Set",
        "category": "BOOKS",
        "subject_tags": ["LITERACY"],
        "unit_price_cents": 2500,
        "weight_oz": 10,
        "shipping_zone": "A",
    }
    defaults.update(overrides)
    return defaults


# Named catalog-item specifications reused across tests.

def book_item_spec() -> Dict[str, Any]:
    """The canonical 2500-cent, 10-oz, zone-A book from the shared fixture."""
    return catalog_item_payload(
        sku="SM-BOOK-1", unit_price_cents=2500, weight_oz=10, shipping_zone="A"
    )


def lab_item_spec() -> Dict[str, Any]:
    """A 800-cent, 200-oz, zone-B fragile beaker set."""
    return catalog_item_payload(
        sku="SM-LAB-1",
        name="Glass Beaker Set",
        category="LAB_EQUIPMENT",
        subject_tags=["SCIENCE"],
        unit_price_cents=800,
        weight_oz=200,
        shipping_zone="B",
        fragile=True,
    )


def pencil_item_spec() -> Dict[str, Any]:
    """A 300-cent, 4-oz, zone-A pencil box (tiny-goal fixture)."""
    return catalog_item_payload(
        sku="SM-PENCIL-1",
        name="Pencil Box",
        category="SUPPLIES",
        subject_tags=[],
        unit_price_cents=300,
        weight_oz=4,
        shipping_zone="A",
    )


def rug_item_spec() -> Dict[str, Any]:
    """A 1000-cent, 20-oz, zone-A classroom rug (second-vendor fixture)."""
    return catalog_item_payload(
        sku="RC-RUG-1",
        name="Classroom Rug",
        category="FURNITURE",
        subject_tags=[],
        unit_price_cents=1000,
        weight_oz=20,
        shipping_zone="A",
    )


def centrifuge_item_spec() -> Dict[str, Any]:
    """A 800-cent, 200-oz, zone-C fragile centrifuge (shipping-cap fixture)."""
    return catalog_item_payload(
        sku="SM-LAB-9",
        name="Centrifuge",
        category="LAB_EQUIPMENT",
        subject_tags=["SCIENCE"],
        unit_price_cents=800,
        weight_oz=200,
        shipping_zone="C",
        fragile=True,
    )


# ── Projects ───────────────────────────────────────────────────────────────

def project_payload(**overrides: Any) -> Dict[str, Any]:
    n = _seq()
    defaults: Dict[str, Any] = {
        "title": "Books for Budding Readers",
        "description": "Classroom library for grade 3-5 readers.",
        "subject": "LITERACY",
        "grade_band": "G3_5",
        "funding_window_days": 30,
    }
    defaults.update(overrides)
    return defaults


def add_item_payload(catalog_item_id: str, quantity: int, expected_project_version: int) -> Dict[str, Any]:
    return {
        "catalog_item_id": catalog_item_id,
        "quantity": quantity,
        "expected_project_version": expected_project_version,
    }


def submit_payload(expected_project_version: int) -> Dict[str, Any]:
    return {"expected_project_version": expected_project_version}


def review_payload(stage: str, outcome: str) -> Dict[str, Any]:
    return {"stage": stage, "outcome": outcome}


# ── Donors and donations ───────────────────────────────────────────────────

def donor_payload(**overrides: Any) -> Dict[str, Any]:
    n = _seq()
    defaults: Dict[str, Any] = {
        "display_name": f"Donor {n}",
        "email": f"donor{n}@example.org",
    }
    defaults.update(overrides)
    return defaults


def donation_payload(amount_cents: int, match_campaign_id: Optional[str] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"amount_cents": amount_cents}
    if match_campaign_id is not None:
        payload["match_campaign_id"] = match_campaign_id
    return payload


def reallocation_choice_payload(
    choice: str, expected_donation_version: int, equity_fund_id: Optional[str] = None
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "choice": choice,
        "expected_donation_version": expected_donation_version,
    }
    if equity_fund_id is not None:
        payload["equity_fund_id"] = equity_fund_id
    return payload


# ── Match campaigns ────────────────────────────────────────────────────────

def match_campaign_payload(**overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "sponsor_name": "Acme Foundation",
        "match_ratio": 1.0,
        "budget_cents": 100000,
        "target_type": "STATE",
        "target_value": "TX",
        "starts_at": "2026-09-01T00:00:00Z",
        "ends_at": "2026-12-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


# ── Purchase orders ────────────────────────────────────────────────────────

def po_advance_payload(
    action: str,
    tracking_number: Optional[str] = None,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    if tracking_number is not None:
        payload["tracking_number"] = tracking_number
    if reason is not None:
        payload["reason"] = reason
    return payload


# ── Thank-you packages ─────────────────────────────────────────────────────

def thank_you_package_payload(**overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "thank_you_note": "Thank you for funding our classroom library!",
        "impact_report": (
            "Every student now reads 20 minutes daily; fluency scores are "
            "already climbing across the board."
        ),
    }
    defaults.update(overrides)
    return defaults


# ── Fraud cases ────────────────────────────────────────────────────────────

def fraud_resolve_payload(outcome: str, notes: Optional[str] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"outcome": outcome}
    if notes is not None:
        payload["notes"] = notes
    return payload


# ── Equity funds ───────────────────────────────────────────────────────────

def equity_fund_payload(**overrides: Any) -> Dict[str, Any]:
    n = _seq()
    defaults: Dict[str, Any] = {
        "name": f"Lone Star Equity Fund {n}",
        "state_code": "TX",
        "min_poverty_pct": 75.0,
        "budget_cents": 50000,
        "window_start": "2026-09-01T00:00:00Z",
        "window_end": "2026-12-31T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults
