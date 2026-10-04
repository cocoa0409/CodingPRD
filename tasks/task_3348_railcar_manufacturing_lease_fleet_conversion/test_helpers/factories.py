"""Payload factories — one per creatable resource, plus action bodies.

Only fields the PRD declares as client-supplied inputs appear here.  Fields
whose value is derived by the server (``status``, ``completed_qty``,
``reserved_qty``, ``amendment_seq``, ``shop_days``, ``capital_allocation_cents``
and the like) are never sent.

Optional fields are omitted from the payload unless the caller supplies them,
so a test can exercise the server-side default by simply not passing a value.
"""

import datetime as _dt
from typing import Optional

from .constants import TEST_DEFAULTS as D


# ─── Date helpers ─────────────────────────────────────

def iso_date(value) -> str:
    """Render a date (or ISO string) as an ISO 8601 calendar date."""
    if isinstance(value, str):
        return value[:10]
    return value.isoformat()


def shift_date(date_str: str, days: int) -> str:
    """Return ``date_str`` advanced (or retreated) by ``days`` calendar days."""
    base = _dt.date.fromisoformat(iso_date(date_str))
    return (base + _dt.timedelta(days=days)).isoformat()


def days_between(start: str, end: str) -> int:
    """Whole days from ``start`` up to (not including) ``end``."""
    return (
        _dt.date.fromisoformat(iso_date(end)) - _dt.date.fromisoformat(iso_date(start))
    ).days


# ─── Catalogue ────────────────────────────────────────

def create_car_type_payload(
    model_code: str = None,
    car_class: str = None,
    build_hours: int = None,
    regulatory_life_years: int = None,
    line_count_family: str = None,
    **overrides,
) -> dict:
    """Car type registration body."""
    payload = {
        "model_code": model_code or D["CAR_TYPE_MODEL_CODE"],
        "car_class": car_class or D["CAR_TYPE_CAR_CLASS"],
        "build_hours": build_hours if build_hours is not None else D["CAR_TYPE_BUILD_HOURS"],
        "regulatory_life_years": (
            regulatory_life_years
            if regulatory_life_years is not None
            else D["CAR_TYPE_LIFE_YEARS"]
        ),
        "line_count_family": line_count_family or D["CAR_TYPE_LINE_FAMILY"],
    }
    payload.update(overrides)
    return payload


def create_component_payload(
    part_number: str = None,
    component_class: str = None,
    unit_cost_cents: int = None,
    lead_time_days: int = None,
    on_hand_qty: Optional[int] = None,
    **overrides,
) -> dict:
    """Component registration body.

    ``on_hand_qty`` is omitted unless supplied, because the component starts at
    zero when the caller does not open the stock position.
    """
    payload = {
        "part_number": part_number or D["COMPONENT_WHEELSET_PART_NUMBER"],
        "component_class": component_class or "WHEELSET",
        "unit_cost_cents": (
            unit_cost_cents
            if unit_cost_cents is not None
            else D["COMPONENT_WHEELSET_UNIT_COST_CENTS"]
        ),
        "lead_time_days": (
            lead_time_days if lead_time_days is not None else D["COMPONENT_LEAD_TIME_DAYS"]
        ),
    }
    if on_hand_qty is not None:
        payload["on_hand_qty"] = on_hand_qty
    payload.update(overrides)
    return payload


def create_car_type_component_requirement_payload(
    car_type_id: str = None,
    component_id: str = None,
    qty_per_car: int = None,
    **overrides,
) -> dict:
    """Bill-of-material row body."""
    payload = {
        "car_type_id": car_type_id,
        "component_id": component_id,
        "qty_per_car": qty_per_car if qty_per_car is not None else 1,
    }
    payload.update(overrides)
    return payload


# ─── Backlog ──────────────────────────────────────────

def create_production_order_payload(
    car_type_id: str = None,
    quantity: int = None,
    planned_shop_days: int = None,
    disposition: str = None,
    priority_rank: int = None,
    order_date: str = None,
    required_delivery_date: str = None,
    unit_price_cents: Optional[int] = None,
    lessee_id: Optional[str] = None,
    supersedes_production_order_id: Optional[str] = None,
    **overrides,
) -> dict:
    """Production order intake body.

    ``unit_price_cents`` is optional at intake — the server quotes the order —
    so it is omitted unless the caller supplies one explicitly.
    """
    payload = {
        "car_type_id": car_type_id,
        "quantity": quantity if quantity is not None else D["ORDER_QUANTITY"],
        "planned_shop_days": (
            planned_shop_days
            if planned_shop_days is not None
            else D["ORDER_QUANTITY"] * D["CAR_TYPE_BUILD_HOURS"]
        ),
        "disposition": disposition or D["ORDER_DISPOSITION"],
        "priority_rank": priority_rank if priority_rank is not None else D["ORDER_PRIORITY_RANK"],
        "order_date": order_date or D["ORDER_ORDER_DATE"],
        "required_delivery_date": (
            required_delivery_date or D["ORDER_REQUIRED_DELIVERY_DATE"]
        ),
    }
    if unit_price_cents is not None:
        payload["unit_price_cents"] = unit_price_cents
    if lessee_id is not None:
        payload["lessee_id"] = lessee_id
    if supersedes_production_order_id is not None:
        payload["supersedes_production_order_id"] = supersedes_production_order_id
    payload.update(overrides)
    return payload


def create_substitution_endorsement_payload(
    production_order_id: str = None,
    original_component_id: str = None,
    substitute_component_id: str = None,
    substitute_qty_per_car: int = None,
    decides_material: bool = False,
    expected_production_order_version: int = None,
    **overrides,
) -> dict:
    """Substitution endorsement body — carries the order's expected version."""
    payload = {
        "production_order_id": production_order_id,
        "original_component_id": original_component_id,
        "substitute_component_id": substitute_component_id,
        "substitute_qty_per_car": (
            substitute_qty_per_car if substitute_qty_per_car is not None else 1
        ),
        "decides_material": decides_material,
        "expected_production_order_version": expected_production_order_version,
    }
    payload.update(overrides)
    return payload


def patch_substitution_endorsement_payload(
    status: str = None,
    expected_substitution_endorsement_version: Optional[int] = None,
    **overrides,
) -> dict:
    """Endorsement edit body: reject a pending one, or return a rejected one."""
    payload = {"status": status}
    if expected_substitution_endorsement_version is not None:
        payload["expected_substitution_endorsement_version"] = (
            expected_substitution_endorsement_version
        )
    payload.update(overrides)
    return payload


def changeover_payload(
    production_order_id: str = None,
    scheduled_start_date: str = None,
    scheduled_end_date: str = None,
    **overrides,
) -> dict:
    """Line changeover body — the window width is the order's shop days."""
    payload = {
        "production_order_id": production_order_id,
        "scheduled_start_date": scheduled_start_date,
        "scheduled_end_date": scheduled_end_date,
    }
    payload.update(overrides)
    return payload


def complete_production_order_payload(
    completed_qty: int = None,
    lessee_id: Optional[str] = None,
    completion_date: Optional[str] = None,
    **overrides,
) -> dict:
    """Order completion body."""
    payload = {"completed_qty": completed_qty}
    if lessee_id is not None:
        payload["lessee_id"] = lessee_id
    if completion_date is not None:
        payload["completion_date"] = completion_date
    payload.update(overrides)
    return payload


def release_production_order_payload(
    lease_contract_id: Optional[str] = None, **overrides
) -> dict:
    """Order release body — names the contract the retained capital accrues to."""
    payload = {}
    if lease_contract_id is not None:
        payload["lease_contract_id"] = lease_contract_id
    payload.update(overrides)
    return payload


# ─── Commercial ───────────────────────────────────────

def create_lessee_payload(
    legal_name: str = None,
    credit_tier: str = None,
    utilization_threshold_pct: int = None,
    credit_ceiling_cents: int = None,
    **overrides,
) -> dict:
    """Lessee account registration body."""
    payload = {
        "legal_name": legal_name or D["LESSEE_LEGAL_NAME"],
        "credit_tier": credit_tier or D["LESSEE_CREDIT_TIER"],
        "utilization_threshold_pct": (
            utilization_threshold_pct
            if utilization_threshold_pct is not None
            else D["LESSEE_UTILIZATION_THRESHOLD_PCT"]
        ),
        "credit_ceiling_cents": (
            credit_ceiling_cents
            if credit_ceiling_cents is not None
            else D["LESSEE_CREDIT_CEILING_CENTS"]
        ),
    }
    payload.update(overrides)
    return payload


def create_lease_contract_payload(
    lessee_id: str = None,
    lease_type: str = None,
    per_diem_rate_cents: int = None,
    liability_bearer: str = None,
    term_start_date: str = None,
    term_end_date: str = None,
    fleet_car_cap: int = None,
    **overrides,
) -> dict:
    """Lease contract drafting body."""
    payload = {
        "lessee_id": lessee_id,
        "lease_type": lease_type or D["CONTRACT_LEASE_TYPE"],
        "per_diem_rate_cents": (
            per_diem_rate_cents
            if per_diem_rate_cents is not None
            else D["CONTRACT_PER_DIEM_RATE_CENTS"]
        ),
        "liability_bearer": liability_bearer or D["CONTRACT_LIABILITY_BEARER"],
        "term_start_date": term_start_date or D["CONTRACT_TERM_START_DATE"],
        "term_end_date": term_end_date or D["CONTRACT_TERM_END_DATE"],
        "fleet_car_cap": (
            fleet_car_cap if fleet_car_cap is not None else D["CONTRACT_FLEET_CAR_CAP"]
        ),
    }
    payload.update(overrides)
    return payload


def draft_lease_amendment_payload(
    per_diem_rate_cents: int = None,
    liability_bearer: str = None,
    expected_lease_version: int = None,
    **overrides,
) -> dict:
    """Amendment drafting body — carries the contract's expected version."""
    payload = {
        "per_diem_rate_cents": per_diem_rate_cents,
        "liability_bearer": liability_bearer,
        "expected_lease_version": expected_lease_version,
    }
    payload.update(overrides)
    return payload


def ratify_lease_amendment_payload(expected_lease_version: int = None, **overrides) -> dict:
    """Amendment ratification body — the same version precondition applies."""
    payload = {"expected_lease_version": expected_lease_version}
    payload.update(overrides)
    return payload


def terminate_lease_contract_payload(
    cascade_assignment_ids=None, **overrides
) -> dict:
    """Termination body — enumerate every live placement to close them."""
    payload = {}
    if cascade_assignment_ids is not None:
        payload["cascade_assignment_ids"] = list(cascade_assignment_ids)
    payload.update(overrides)
    return payload


# ─── Placements and returns ───────────────────────────

def create_car_assignment_payload(
    lease_fleet_car_id: str = None,
    lease_contract_id: str = None,
    lessee_id: str = None,
    start_date: str = None,
    end_date: str = None,
    mileage_allowance: int = None,
    **overrides,
) -> dict:
    """Placement creation body — the end date is exclusive."""
    payload = {
        "lease_fleet_car_id": lease_fleet_car_id,
        "lease_contract_id": lease_contract_id,
        "lessee_id": lessee_id,
        "start_date": start_date or D["ASSIGNMENT_START_DATE"],
        "end_date": end_date or D["ASSIGNMENT_END_DATE"],
        "mileage_allowance": (
            mileage_allowance
            if mileage_allowance is not None
            else D["ASSIGNMENT_MILEAGE_ALLOWANCE"]
        ),
    }
    payload.update(overrides)
    return payload


def suspend_car_assignment_payload(suspend_date: Optional[str] = None, **overrides) -> dict:
    """Suspension body — ``suspend_date`` fixes the date the meter stops."""
    payload = {}
    if suspend_date is not None:
        payload["suspend_date"] = suspend_date
    payload.update(overrides)
    return payload


def reassign_car_assignment_payload(
    target_lease_fleet_car_id: str = None,
    effective_date: Optional[str] = None,
    **overrides,
) -> dict:
    """Reassignment body — the target car must be free and on the same contract."""
    payload = {"target_lease_fleet_car_id": target_lease_fleet_car_id}
    if effective_date is not None:
        payload["effective_date"] = effective_date
    payload.update(overrides)
    return payload


def create_car_return_payload(
    lease_fleet_car_id: str = None,
    car_assignment_id: str = None,
    return_date: str = None,
    mileage_since_last: int = 0,
    condition_grade: str = "A",
    **overrides,
) -> dict:
    """Return recording body."""
    payload = {
        "lease_fleet_car_id": lease_fleet_car_id,
        "car_assignment_id": car_assignment_id,
        "return_date": return_date,
        "mileage_since_last": mileage_since_last,
        "condition_grade": condition_grade,
    }
    payload.update(overrides)
    return payload


# ─── Retrofit ─────────────────────────────────────────

def create_retrofit_program_payload(
    mandate_code: str = None,
    description: str = None,
    compliance_deadline_date: str = None,
    required_shop_days_per_car: int = None,
    required_component_id: Optional[str] = None,
    **overrides,
) -> dict:
    """Retrofit mandate program body."""
    payload = {
        "mandate_code": mandate_code or D["PROGRAM_MANDATE_CODE"],
        "description": description or "Regulatory retrofit mandate",
        "compliance_deadline_date": (
            compliance_deadline_date or D["PROGRAM_COMPLIANCE_DEADLINE_DATE"]
        ),
        "required_shop_days_per_car": (
            required_shop_days_per_car
            if required_shop_days_per_car is not None
            else D["PROGRAM_REQUIRED_SHOP_DAYS_PER_CAR"]
        ),
    }
    if required_component_id is not None:
        payload["required_component_id"] = required_component_id
    payload.update(overrides)
    return payload


def create_retrofit_program_car_type_payload(
    retrofit_program_id: str = None, car_type_id: str = None, **overrides
) -> dict:
    """Program coverage row body."""
    payload = {
        "retrofit_program_id": retrofit_program_id,
        "car_type_id": car_type_id,
    }
    payload.update(overrides)
    return payload


def create_retrofit_work_order_payload(
    retrofit_program_id: str = None,
    lease_fleet_car_id: str = None,
    shop_line: str = None,
    scheduled_start_date: str = None,
    scheduled_end_date: str = None,
    component_qty_consumed: int = 1,
    **overrides,
) -> dict:
    """Retrofit shop work scheduling body — the window is half-open."""
    payload = {
        "retrofit_program_id": retrofit_program_id,
        "lease_fleet_car_id": lease_fleet_car_id,
        "shop_line": shop_line or D["WORK_ORDER_SHOP_LINE"],
        "scheduled_start_date": scheduled_start_date,
        "scheduled_end_date": scheduled_end_date,
        "component_qty_consumed": component_qty_consumed,
    }
    payload.update(overrides)
    return payload


# ─── Purchasing ───────────────────────────────────────

def create_component_purchase_order_payload(
    component_id: str = None,
    qty_ordered: int = 1,
    unit_cost_cents: int = None,
    order_date: str = None,
    expected_receipt_date: Optional[str] = None,
    **overrides,
) -> dict:
    """Purchase order body.

    When ``expected_receipt_date`` is omitted the caller is responsible for
    deriving it as ``order_date`` plus the component's supplier lead time.
    """
    payload = {
        "component_id": component_id,
        "qty_ordered": qty_ordered,
        "unit_cost_cents": unit_cost_cents,
        "order_date": order_date or D["ORDER_ORDER_DATE"],
        "expected_receipt_date": expected_receipt_date,
    }
    payload.update(overrides)
    return payload


def create_component_receipt_payload(
    component_purchase_order_id: str = None,
    component_id: str = None,
    qty_received: int = 1,
    receipt_date: str = None,
    **overrides,
) -> dict:
    """Yard receipt booking body."""
    payload = {
        "component_purchase_order_id": component_purchase_order_id,
        "component_id": component_id,
        "qty_received": qty_received,
        "receipt_date": receipt_date,
    }
    payload.update(overrides)
    return payload


# ─── Disposal ─────────────────────────────────────────

def create_lease_fleet_sale_payload(
    lease_fleet_car_id: str = None,
    buyer_name: str = None,
    sale_price_cents: int = None,
    sale_date: str = None,
    writeback_liability_cents: int = 0,
    lease_contract_id: Optional[str] = None,
    net_book_value_cents: Optional[int] = None,
    lessee_id: Optional[str] = None,
    **overrides,
) -> dict:
    """Secondary-market sale body."""
    payload = {
        "lease_fleet_car_id": lease_fleet_car_id,
        "buyer_name": buyer_name or D["SALE_BUYER_NAME"],
        "sale_price_cents": sale_price_cents,
        "writeback_liability_cents": (
            writeback_liability_cents
            if writeback_liability_cents is not None
            else D["SALE_WRITEBACK_LIABILITY_CENTS"]
        ),
        "sale_date": sale_date,
    }
    if lease_contract_id is not None:
        payload["lease_contract_id"] = lease_contract_id
    if net_book_value_cents is not None:
        payload["net_book_value_cents"] = net_book_value_cents
    if lessee_id is not None:
        payload["lessee_id"] = lessee_id
    payload.update(overrides)
    return payload


def scrap_lease_fleet_car_payload(scrap_reason: Optional[str] = None, **overrides) -> dict:
    """Scrap body — the reason is optional."""
    payload = {}
    if scrap_reason is not None:
        payload["scrap_reason"] = scrap_reason
    payload.update(overrides)
    return payload


# ─── Clock ────────────────────────────────────────────

def set_clock_payload(to_iso8601: str = None, **overrides) -> dict:
    """Logical clock body."""
    payload = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload


__all__ = [
    # date helpers
    "iso_date", "shift_date", "days_between",
    # catalogue
    "create_car_type_payload", "create_component_payload",
    "create_car_type_component_requirement_payload",
    # backlog
    "create_production_order_payload", "create_substitution_endorsement_payload",
    "patch_substitution_endorsement_payload", "changeover_payload",
    "complete_production_order_payload", "release_production_order_payload",
    # commercial
    "create_lessee_payload", "create_lease_contract_payload",
    "draft_lease_amendment_payload", "ratify_lease_amendment_payload",
    "terminate_lease_contract_payload",
    # placements and returns
    "create_car_assignment_payload", "suspend_car_assignment_payload",
    "reassign_car_assignment_payload", "create_car_return_payload",
    # retrofit
    "create_retrofit_program_payload", "create_retrofit_program_car_type_payload",
    "create_retrofit_work_order_payload",
    # purchasing
    "create_component_purchase_order_payload", "create_component_receipt_payload",
    # disposal
    "create_lease_fleet_sale_payload", "scrap_lease_fleet_car_payload",
    # clock
    "set_clock_payload",
]
