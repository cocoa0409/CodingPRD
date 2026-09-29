"""Composite state builders.

Every helper drives the public API only: the harness restarts the server before
each test, so a test starts from an empty database and builds each precondition
by calling the endpoints the PRD publishes.

Helpers are phased.  A chain builder stops at a named state and returns it; the
deeper states are separate calls layered on top.  No builder's last hop
invalidates a state an earlier hop of the same builder established, so any
builder can be reused by any test.
"""

from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import validate_success

from . import factories
from .constants import (
    BAKERY_TWO_RUNGS,
    DELI_FOUR_RUNGS,
    MEAT_FOUR_RUNGS,
    MEAT_TWO_RUNGS,
    PRODUCE_TWO_RUNGS,
    SEAFOOD_TWO_RUNGS,
)
from .test_users import (
    admin_headers,
    auditor_headers,
    clerk_headers,
    make_partner_headers,
    manager_headers,
)


# --------------------------------------------------------------------------
# Primitive builders
# --------------------------------------------------------------------------


def set_clock(api, current_utc: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Move the logical clock; every role may call this endpoint."""
    response = api.set_clock(current_utc, headers or admin_headers())
    return validate_success(response)


def build_store(api, headers: Optional[Dict[str, str]] = None, **overrides) -> Dict[str, Any]:
    response = api.create_store(
        factories.create_store_payload(**overrides), headers or admin_headers()
    )
    return validate_success(response, expected_status=201)


def build_partner(api, headers: Optional[Dict[str, str]] = None, **overrides) -> Dict[str, Any]:
    response = api.create_food_bank_partner(
        factories.create_food_bank_partner_payload(**overrides), headers or admin_headers()
    )
    return validate_success(response, expected_status=201)


def build_ladder(
    api,
    headers: Optional[Dict[str, str]] = None,
    activate: bool = True,
    **overrides,
) -> Dict[str, Any]:
    """Create a ladder and, by default, activate it so lots can be priced against it."""
    acting = headers or admin_headers()
    ladder = validate_success(
        api.create_markdown_ladder(factories.create_markdown_ladder_payload(**overrides), acting),
        expected_status=201,
    )
    if activate:
        ladder = validate_success(api.activate_markdown_ladder(ladder["id"], acting))
    return ladder


def build_department(
    api,
    store_id: str,
    markdown_ladder_id: str,
    headers: Optional[Dict[str, str]] = None,
    **overrides,
) -> Dict[str, Any]:
    response = api.create_department(
        factories.create_department_payload(store_id, markdown_ladder_id, **overrides),
        headers or admin_headers(),
    )
    return validate_success(response, expected_status=201)


def build_item(
    api, department_id: str, headers: Optional[Dict[str, str]] = None, **overrides
) -> Dict[str, Any]:
    response = api.create_item(
        factories.create_item_payload(department_id, **overrides), headers or admin_headers()
    )
    return validate_success(response, expected_status=201)


def build_lot(
    api, item_id: str, headers: Optional[Dict[str, str]] = None, **overrides
) -> Dict[str, Any]:
    response = api.create_lot(
        factories.create_lot_payload(item_id, **overrides), headers or clerk_headers()
    )
    return validate_success(response, expected_status=201)


def reload_lot(api, lot_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return validate_success(api.get_lot(lot_id, headers or clerk_headers()))


def reload_department(
    api, department_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return validate_success(api.get_department(department_id, headers or manager_headers()))


def reload_item(api, item_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return validate_success(api.get_item(item_id, headers or manager_headers()))


def reload_label(api, label_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return validate_success(api.get_markdown_label(label_id, headers or clerk_headers()))


def reload_pickup(api, pickup_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return validate_success(api.get_donation_pickup(pickup_id, headers or manager_headers()))


def reload_shrink(api, shrink_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return validate_success(api.get_shrink_event(shrink_id, headers or manager_headers()))


def reload_audit(api, audit_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return validate_success(api.get_compliance_audit(audit_id, headers or auditor_headers()))


def reload_finding(
    api, finding_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return validate_success(api.get_audit_finding(finding_id, headers or auditor_headers()))


# --------------------------------------------------------------------------
# Registry chains
# --------------------------------------------------------------------------


def build_registry_chain(
    api,
    *,
    department_code: str,
    rungs: List[Dict[str, Any]],
    ladder_name: str,
    clock: str = "2026-08-10T08:00:00.000Z",
    store_overrides: Optional[Dict[str, Any]] = None,
    ladder_overrides: Optional[Dict[str, Any]] = None,
    department_overrides: Optional[Dict[str, Any]] = None,
    item_overrides: Optional[Dict[str, Any]] = None,
    lot_overrides: Optional[Dict[str, Any]] = None,
    with_lot: bool = True,
) -> SimpleNamespace:
    """Clock, store, active ladder, department, item and (optionally) one lot.

    The chain stops at a receipted lot that has never been priced, so it is a
    safe starting point for pricing, sales, shrink, donation and audit tests
    alike.
    """
    if clock is not None:
        set_clock(api, clock)

    store = build_store(api, **(store_overrides or {}))
    ladder = build_ladder(
        api,
        name=ladder_name,
        department_code=department_code,
        rungs=[dict(rung) for rung in rungs],
        **(ladder_overrides or {}),
    )
    department = build_department(
        api,
        store["id"],
        ladder["id"],
        code=department_code,
        **(department_overrides or {}),
    )
    item = build_item(api, department["id"], **(item_overrides or {}))
    lot = build_lot(api, item["id"], **(lot_overrides or {})) if with_lot else None
    return SimpleNamespace(
        store=store, ladder=ladder, department=department, item=item, lot=lot
    )


def build_meat_chain(api, **kwargs) -> SimpleNamespace:
    """MEAT department on a two-rung ladder, one 24-unit lot produced 2026-08-05."""
    kwargs.setdefault("department_code", "MEAT")
    kwargs.setdefault("rungs", MEAT_TWO_RUNGS)
    kwargs.setdefault("ladder_name", "MEAT-STD-2026")
    kwargs.setdefault("department_overrides", {"shelf_life_days_default": 10})
    return build_registry_chain(api, **kwargs)


def build_meat_four_rung_chain(api, **kwargs) -> SimpleNamespace:
    """MEAT department on the four-rung ladder, floor 60 percent, cap 75 percent."""
    kwargs.setdefault("department_code", "MEAT")
    kwargs.setdefault("rungs", MEAT_FOUR_RUNGS)
    kwargs.setdefault("ladder_name", "MEAT-STD-2026")
    kwargs.setdefault(
        "ladder_overrides",
        {"sell_through_floor_pct": 60, "max_total_discount_pct": 75},
    )
    kwargs.setdefault("department_overrides", {"shelf_life_days_default": 10})
    return build_registry_chain(api, **kwargs)


def build_deli_aggressive_chain(api, **kwargs) -> SimpleNamespace:
    """DELI department on the AGGRESSIVE profile: velocity multiplier 1.25."""
    kwargs.setdefault("department_code", "DELI")
    kwargs.setdefault("rungs", DELI_FOUR_RUNGS)
    kwargs.setdefault("ladder_name", "DELI-AGGR-2026")
    kwargs.setdefault(
        "ladder_overrides",
        {"sell_through_floor_pct": 60, "max_total_discount_pct": 70},
    )
    kwargs.setdefault(
        "department_overrides",
        {"shelf_life_days_default": 8, "markdown_policy_profile": "AGGRESSIVE"},
    )
    kwargs.setdefault(
        "item_overrides",
        {
            "upc": "000777888999",
            "description": "Rotisserie Chicken Breast",
            "base_retail_cents": 700,
            "unit_cost_cents": 300,
            "daily_forecast_units": 5.00,
            "shelf_life_days": 6,
        },
    )
    kwargs.setdefault(
        "lot_overrides", {"production_date": "2026-08-08", "quantity_original": 20}
    )
    return build_registry_chain(api, **kwargs)


def build_bakery_chain(api, **kwargs) -> SimpleNamespace:
    """BAKERY department on a two-rung ladder."""
    kwargs.setdefault("department_code", "BAKERY")
    kwargs.setdefault("rungs", BAKERY_TWO_RUNGS)
    kwargs.setdefault("ladder_name", "BAKERY-STD-2026")
    kwargs.setdefault(
        "ladder_overrides", {"max_total_discount_pct": 50}
    )
    kwargs.setdefault("department_overrides", {"shelf_life_days_default": 5})
    kwargs.setdefault(
        "item_overrides",
        {
            "upc": "000333222111",
            "description": "Sourdough Boule",
            "base_retail_cents": 449,
            "unit_cost_cents": 200,
            "daily_forecast_units": 6.00,
        },
    )
    kwargs.setdefault(
        "lot_overrides", {"production_date": "2026-08-05", "quantity_original": 20}
    )
    return build_registry_chain(api, **kwargs)


def build_seafood_chain(api, **kwargs) -> SimpleNamespace:
    """SEAFOOD department with a tight shrink budget and a two-hour tolerance."""
    kwargs.setdefault("department_code", "SEAFOOD")
    kwargs.setdefault("rungs", SEAFOOD_TWO_RUNGS)
    kwargs.setdefault("ladder_name", "SEAFOOD-STD-2026")
    kwargs.setdefault("ladder_overrides", {"max_total_discount_pct": 40})
    kwargs.setdefault(
        "department_overrides",
        {
            "shelf_life_days_default": 10,
            "past_date_tolerance_hours": 2,
            "shrink_budget_pct": 0.10,
        },
    )
    kwargs.setdefault(
        "item_overrides",
        {
            "upc": "000999888777",
            "description": "Atlantic Salmon Fillet",
            "base_retail_cents": 1200,
            "unit_cost_cents": 800,
            "daily_forecast_units": 2.00,
        },
    )
    kwargs.setdefault(
        "lot_overrides", {"production_date": "2026-08-05", "quantity_original": 6}
    )
    return build_registry_chain(api, **kwargs)


def build_produce_chain(api, **kwargs) -> SimpleNamespace:
    """PRODUCE department plus an ACTIVE food bank partner that accepts PRODUCE."""
    partner_overrides = kwargs.pop("partner_overrides", None) or {}
    kwargs.setdefault("department_code", "PRODUCE")
    kwargs.setdefault("rungs", PRODUCE_TWO_RUNGS)
    kwargs.setdefault("ladder_name", "PRODUCE-STD-2026")
    kwargs.setdefault("ladder_overrides", {"max_total_discount_pct": 50})
    kwargs.setdefault("department_overrides", {"shelf_life_days_default": 5})
    kwargs.setdefault(
        "item_overrides",
        {
            "upc": "000444555666",
            "description": "Organic Blueberries Pint",
            "base_retail_cents": 599,
            "unit_cost_cents": 250,
            "daily_forecast_units": 8.00,
        },
    )
    kwargs.setdefault(
        "lot_overrides", {"production_date": "2026-08-05", "quantity_original": 20}
    )
    chain = build_registry_chain(api, **kwargs)
    chain.partner = build_partner(
        api,
        service_region_code=chain.store["region_code"],
        accepted_department_codes=[chain.department["code"]],
        **partner_overrides,
    )
    chain.partner_headers = make_partner_headers(chain.partner["id"])
    return chain


# --------------------------------------------------------------------------
# Pricing extensions
# --------------------------------------------------------------------------


def cut_markdown(
    api,
    lot: Dict[str, Any],
    *,
    pricing_variant: Optional[str] = None,
    override_price_cents: Optional[int] = None,
    approval_manager_user_id: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
    expected_lot_version: Optional[int] = None,
) -> Dict[str, Any]:
    """Cut one markdown label on a lot and return the created label."""
    payload: Dict[str, Any] = {
        "expected_lot_version": (
            lot["version"] if expected_lot_version is None else expected_lot_version
        )
    }
    if pricing_variant is not None:
        payload["pricing_variant"] = pricing_variant
    if override_price_cents is not None:
        payload["override_price_cents"] = override_price_cents
    if approval_manager_user_id is not None:
        payload["approval_manager_user_id"] = approval_manager_user_id
    response = api.create_markdown(lot["id"], payload, headers or clerk_headers())
    return validate_success(response, expected_status=201)


def print_label(api, label_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return validate_success(api.print_markdown_label(label_id, headers or clerk_headers()))


def apply_label(api, label_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Application is the call that turns the promotional sell-through lift on."""
    return validate_success(api.apply_markdown_label(label_id, headers or clerk_headers()))


def cut_and_apply_markdown(api, lot: Dict[str, Any], **kwargs) -> Dict[str, Any]:
    """Cut a label and carry it all the way to APPLIED, returning the applied label."""
    label = cut_markdown(api, lot, **kwargs)
    print_label(api, label["id"])
    return apply_label(api, label["id"])


def post_sale(
    api,
    lot_id: str,
    quantity_units: int,
    register_lane_code: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"quantity_units": quantity_units}
    if register_lane_code is not None:
        payload["register_lane_code"] = register_lane_code
    # A sale brings no new resource into existence -- it transitions the lot and
    # returns the lot -- so per PRD 4 it answers HTTP 200, not 201.
    return validate_success(
        api.post_sale(lot_id, payload, headers or clerk_headers()), expected_status=200
    )


def withdraw_lot(
    api,
    lot_id: str,
    reason_note: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if reason_note is not None:
        payload["reason_note"] = reason_note
    return validate_success(api.withdraw_lot(lot_id, payload, headers or manager_headers()))


# --------------------------------------------------------------------------
# Shrink extensions
# --------------------------------------------------------------------------


def record_shrink(
    api,
    lot_id: str,
    quantity_units: int,
    cause_code: str = "SPOILAGE",
    note: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Record a shrink event.  Recording moves no units."""
    payload = factories.create_shrink_event_payload(lot_id, quantity_units, cause_code)
    if note is not None:
        payload["note"] = note
    return validate_success(
        api.create_shrink_event(payload, headers or clerk_headers()), expected_status=201
    )


def verify_shrink(
    api, shrink_event_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """Verify a recorded event.  The verifier must differ from the recorder."""
    return validate_success(
        api.verify_shrink_event(shrink_event_id, headers or manager_headers())
    )


def dispute_shrink(
    api,
    shrink_event_id: str,
    dispute_note: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if dispute_note is not None:
        payload["dispute_note"] = dispute_note
    return validate_success(
        api.dispute_shrink_event(shrink_event_id, payload, headers or manager_headers())
    )


def record_and_verify_shrink(
    api,
    lot_id: str,
    quantity_units: int,
    cause_code: str = "SPOILAGE",
    recorder_headers: Optional[Dict[str, str]] = None,
    verifier_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    event = record_shrink(
        api, lot_id, quantity_units, cause_code, headers=recorder_headers
    )
    return verify_shrink(api, event["id"], headers=verifier_headers)


# --------------------------------------------------------------------------
# Donation extensions
# --------------------------------------------------------------------------


def book_pickup(
    api,
    store_id: str,
    partner_id: str,
    *,
    dock_door_code: str = "D1",
    scheduled_window_start: str = "2026-08-12T14:00:00.000Z",
    scheduled_window_end: str = "2026-08-12T16:00:00.000Z",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    payload = factories.create_donation_pickup_payload(
        store_id,
        partner_id,
        dock_door_code=dock_door_code,
        scheduled_window_start=scheduled_window_start,
        scheduled_window_end=scheduled_window_end,
    )
    return validate_success(
        api.create_donation_pickup(payload, headers or admin_headers()), expected_status=201
    )


def pledge_lot(
    api,
    pickup_id: str,
    lot_id: str,
    quantity_units: int,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return validate_success(
        api.create_donation_assignment(
            pickup_id,
            factories.create_donation_assignment_payload(lot_id, quantity_units),
            headers or clerk_headers(),
        ),
        expected_status=201,
    )


def seal_pickup(
    api, pickup_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return validate_success(api.seal_donation_pickup(pickup_id, headers or manager_headers()))


def confirm_pickup(api, pickup_id: str, partner_id: str) -> Dict[str, Any]:
    """Confirmation belongs to the collecting partner itself."""
    return validate_success(
        api.confirm_donation_pickup(pickup_id, make_partner_headers(partner_id))
    )


def complete_pickup(api, pickup_id: str, partner_id: str) -> Dict[str, Any]:
    return validate_success(
        api.complete_donation_pickup(pickup_id, make_partner_headers(partner_id))
    )


def list_assignments_for_pickup(
    api, pickup_id: str, headers: Optional[Dict[str, str]] = None
) -> List[Dict[str, Any]]:
    from prd_bench_local_runner.testing import validate_paginated

    response = api.list_donation_assignments(
        headers or manager_headers(), params={"pickup_id": pickup_id, "limit": 100}
    )
    rows, _meta = validate_paginated(response)
    return rows


# --------------------------------------------------------------------------
# Compliance extensions
# --------------------------------------------------------------------------


def open_audit(
    api,
    department_id: str,
    window_start_at: str,
    window_end_at: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Only a ComplianceAuditor may open an audit."""
    payload = factories.create_compliance_audit_payload(
        department_id, window_start_at, window_end_at
    )
    return validate_success(
        api.create_compliance_audit(payload, headers or auditor_headers()),
        expected_status=201,
    )


def sweep_audit(
    api, audit_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    return validate_success(api.sweep_compliance_audit(audit_id, headers or auditor_headers()))


def escalate_audit(
    api,
    audit_id: str,
    escalation_note: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if escalation_note is not None:
        payload["escalation_note"] = escalation_note
    return validate_success(
        api.escalate_compliance_audit(audit_id, payload, headers or auditor_headers())
    )


def findings_for_audit(
    api, audit_id: str, headers: Optional[Dict[str, str]] = None
) -> List[Dict[str, Any]]:
    from prd_bench_local_runner.testing import validate_paginated

    response = api.list_audit_findings(
        headers or auditor_headers(), params={"audit_id": audit_id, "limit": 100}
    )
    rows, _meta = validate_paginated(response)
    return rows


def remediate_finding(
    api,
    finding_id: str,
    *,
    remediation: Optional[str] = None,
    waive: Optional[bool] = None,
    resolution_note: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if remediation is not None:
        payload["remediation"] = remediation
    if waive is not None:
        payload["waive"] = waive
    if resolution_note is not None:
        payload["resolution_note"] = resolution_note
    return validate_success(
        api.remediate_audit_finding(finding_id, payload, headers or auditor_headers())
    )


# --------------------------------------------------------------------------
# Ordering extensions
# --------------------------------------------------------------------------


def build_recommendation(
    api,
    item: Dict[str, Any],
    window_start_date: str,
    window_end_date: str,
    *,
    method: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
    expected_item_version: Optional[int] = None,
) -> Dict[str, Any]:
    payload = factories.create_order_recommendation_payload(
        item["id"],
        window_start_date,
        window_end_date,
        item["version"] if expected_item_version is None else expected_item_version,
    )
    if method is not None:
        payload["method"] = method
    return validate_success(
        api.create_order_recommendation(payload, headers or manager_headers()),
        expected_status=201,
    )
