"""Composite setup builders.

The harness restarts the API server before every individual test, so each test starts
against an empty database. Every builder here therefore constructs its preconditions
from scratch through the public API only, and returns the created resources so a test
can assert against them.

All builders use the lenient success reader, so a broken precondition surfaces as a
setup failure rather than as a confusing assertion deep inside a test.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .constants import TEST_DEFAULTS
from .test_users import (
    make_claims_adjuster_headers,
    make_contractor_headers,
    make_credit_manager_headers,
    make_dispatch_planner_headers,
    make_yard_admin_headers,
    make_yard_loader_headers,
)
from .types import Payload

# A line specification is (form, quantity) or (form, quantity, use_prebuy).
LineSpec = Sequence[Any]


def advance_clock(api: ApiClient, to_iso8601: str) -> Dict[str, Any]:
    """Move the yard's logical clock and return the clock result body."""
    return get_success_data(api.set_clock(to_iso8601, headers=make_yard_admin_headers()))


# --------------------------------------------------------------- entity hierarchy


def seed_material(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Register one sellable material."""
    payload = f.create_material_payload(**overrides)
    return get_success_data(api.create_material(payload, headers=make_yard_admin_headers()), 201)


def seed_price_schedule(
    api: ApiClient, material: Dict[str, Any], **overrides: Any
) -> Dict[str, Any]:
    """File a price row against ``material`` at the material's current version."""
    payload = f.create_price_schedule_payload(material["id"], material["version"], **overrides)
    return get_success_data(api.create_price_schedule(payload, headers=make_yard_admin_headers()), 201)


def seed_inventory_lot(api: ApiClient, material_id: str, **overrides: Any) -> Dict[str, Any]:
    """Scale in one stockpile lot."""
    payload = f.create_inventory_lot_payload(material_id, **overrides)
    return get_success_data(api.create_inventory_lot(payload, headers=make_yard_admin_headers()), 201)


def seed_account(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Open one contractor trade account."""
    payload = f.create_contractor_account_payload(**overrides)
    return get_success_data(api.create_contractor_account(payload, headers=make_yard_admin_headers()), 201)


def seed_truck(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Commission one delivery truck."""
    payload = f.create_delivery_truck_payload(**overrides)
    return get_success_data(api.create_delivery_truck(payload, headers=make_dispatch_planner_headers()), 201)


def seed_purchase_order(
    api: ApiClient, account: Dict[str, Any], po_limit_cents: int, **overrides: Any
) -> Dict[str, Any]:
    """Register a job purchase order owned by ``account``."""
    payload = f.create_job_purchase_order_payload(account["id"], po_limit_cents, **overrides)
    return get_success_data(
        api.create_job_purchase_order(payload, headers=make_contractor_headers(account["id"])), 201
    )


def seed_prebuy(
    api: ApiClient,
    account: Dict[str, Any],
    material_id: str,
    locked_price_per_cubic_yard_cents: int,
    contracted_cubic_yards: float,
    season_start_date: str,
    season_end_date: str,
    activate: bool = True,
    **overrides: Any,
) -> Dict[str, Any]:
    """Write a season pre-buy contract, activating it unless asked not to."""
    payload = f.create_prebuy_contract_payload(
        account["id"],
        material_id,
        locked_price_per_cubic_yard_cents,
        contracted_cubic_yards,
        season_start_date,
        season_end_date,
        **overrides,
    )
    contract = get_success_data(
        api.create_prebuy_contract(payload, headers=make_contractor_headers(account["id"])), 201
    )
    if activate:
        contract = get_success_data(
            api.activate_prebuy_contract(contract["id"], headers=make_yard_admin_headers()), 200
        )
    return contract


def seed_catalogue(
    api: ApiClient,
    *,
    material: Optional[Payload] = None,
    price: Optional[Payload] = None,
    lot: Optional[Payload] = None,
    with_lot: bool = True,
) -> Dict[str, Any]:
    """Material plus its EFFECTIVE price row plus (optionally) one stockpile lot.

    Returns ``{"material", "price_schedule", "lot"}``; ``lot`` is ``None`` when
    ``with_lot`` is false. ``material`` is re-read after the lot is scaled in so its
    rolled-up available volume reflects the lot.
    """
    created_material = seed_material(api, **(material or {}))
    schedule = seed_price_schedule(api, created_material, **(price or {}))
    created_lot = None
    if with_lot:
        created_lot = seed_inventory_lot(api, created_material["id"], **(lot or {}))
        created_material = get_success_data(
            api.get_material(created_material["id"], headers=make_yard_admin_headers())
        )
    return {"material": created_material, "price_schedule": schedule, "lot": created_lot}


# ------------------------------------------------------------- order construction


def _add_lines(
    api: ApiClient,
    order_id: str,
    material_id: str,
    lines: Iterable[LineSpec],
    account_id: str,
) -> List[Dict[str, Any]]:
    created: List[Dict[str, Any]] = []
    headers = make_contractor_headers(account_id)
    for spec in lines:
        form, quantity = spec[0], spec[1]
        extra: Payload = {}
        if len(spec) > 2 and spec[2]:
            extra["use_prebuy"] = True
        line_material_id = spec[3] if len(spec) > 3 and spec[3] else material_id
        payload = f.create_order_line_payload(order_id, line_material_id, form, quantity, **extra)
        created.append(get_success_data(api.create_order_line(payload, headers=headers), 201))
    return created


def seed_delivery_order(
    api: ApiClient,
    account: Dict[str, Any],
    material_id: str,
    lines: Iterable[LineSpec] = (("BULK", 10.0),),
    *,
    driveway_access_class: str = "CLASS_A",
    delivery_distance_miles: float = 0.0,
    job_purchase_order_id: Optional[str] = None,
    confirm: bool = False,
    **order_overrides: Any,
) -> Dict[str, Any]:
    """A DELIVERY order with its lines, optionally confirmed.

    Returns ``{"order", "lines"}`` where ``order`` is the state after the last
    successful call.
    """
    headers = make_contractor_headers(account["id"])
    payload = f.create_delivery_order_payload(
        account["id"],
        driveway_access_class=driveway_access_class,
        delivery_distance_miles=delivery_distance_miles,
        **order_overrides,
    )
    if job_purchase_order_id is not None:
        payload["job_purchase_order_id"] = job_purchase_order_id
    order = get_success_data(api.create_material_order(payload, headers=headers), 201)
    created_lines = _add_lines(api, order["id"], material_id, lines, account["id"])
    if confirm:
        order = get_success_data(api.confirm_material_order(order["id"], headers=headers), 200)
        created_lines = [
            get_success_data(api.get_order_line(line["id"], headers=headers)) for line in created_lines
        ]
    return {"order": order, "lines": created_lines}


def seed_will_call_order(
    api: ApiClient,
    account: Dict[str, Any],
    material_id: str,
    lines: Iterable[LineSpec] = (("BULK", 10.0),),
    *,
    confirm: bool = False,
    **order_overrides: Any,
) -> Dict[str, Any]:
    """A WILL_CALL order with its lines, optionally confirmed."""
    headers = make_contractor_headers(account["id"])
    payload = f.create_will_call_order_payload(account["id"], **order_overrides)
    order = get_success_data(api.create_material_order(payload, headers=headers), 201)
    created_lines = _add_lines(api, order["id"], material_id, lines, account["id"])
    if confirm:
        order = get_success_data(api.confirm_material_order(order["id"], headers=headers), 200)
        created_lines = [
            get_success_data(api.get_order_line(line["id"], headers=headers)) for line in created_lines
        ]
    return {"order": order, "lines": created_lines}


def seed_confirmed_delivery_context(
    api: ApiClient,
    *,
    material: Optional[Payload] = None,
    price: Optional[Payload] = None,
    lot: Optional[Payload] = None,
    account: Optional[Payload] = None,
    lines: Iterable[LineSpec] = (("BULK", 10.0),),
    driveway_access_class: str = "CLASS_A",
    delivery_distance_miles: float = 0.0,
    truck: Optional[Payload] = None,
    confirm: bool = True,
) -> Dict[str, Any]:
    """Catalogue, account, truck and a DELIVERY order in one call.

    Returns ``{"material", "price_schedule", "lot", "account", "truck", "order",
    "lines"}``. This is the skeleton nearly every delivery-side scenario needs.
    """
    catalogue = seed_catalogue(api, material=material, price=price, lot=lot)
    created_account = seed_account(api, **(account or {}))
    created_truck = seed_truck(api, **(truck or {}))
    built = seed_delivery_order(
        api,
        created_account,
        catalogue["material"]["id"],
        lines,
        driveway_access_class=driveway_access_class,
        delivery_distance_miles=delivery_distance_miles,
        confirm=confirm,
    )
    return {**catalogue, "account": created_account, "truck": created_truck, **built}


def seed_confirmed_will_call_context(
    api: ApiClient,
    *,
    material: Optional[Payload] = None,
    price: Optional[Payload] = None,
    lot: Optional[Payload] = None,
    account: Optional[Payload] = None,
    lines: Iterable[LineSpec] = (("BULK", 10.0),),
    confirm: bool = True,
) -> Dict[str, Any]:
    """Catalogue, account and a confirmed WILL_CALL order in one call."""
    catalogue = seed_catalogue(api, material=material, price=price, lot=lot)
    created_account = seed_account(api, **(account or {}))
    built = seed_will_call_order(api, created_account, catalogue["material"]["id"], lines, confirm=confirm)
    return {**catalogue, "account": created_account, **built}


# ------------------------------------------------------- delivery-run progression


def seed_planned_load(
    api: ApiClient,
    order_id: str,
    truck_id: str,
    planned_cubic_yards: float,
    window_start: str,
    window_end: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """Book one truck load in a PLANNED window."""
    payload = f.create_delivery_load_payload(
        order_id, truck_id, planned_cubic_yards, window_start, window_end, **overrides
    )
    return get_success_data(api.create_delivery_load(payload, headers=make_dispatch_planner_headers()), 201)


def dispatch_load(
    api: ApiClient, load_id: str, dispatcher_user_id: Optional[str] = None
) -> Dict[str, Any]:
    """Release a PLANNED load to the road as the named planner."""
    headers = (
        make_dispatch_planner_headers(dispatcher_user_id)
        if dispatcher_user_id
        else make_dispatch_planner_headers()
    )
    return get_success_data(api.dispatch_delivery_load(load_id, headers=headers), 200)


def deliver_load(
    api: ApiClient,
    load_id: str,
    actual_net_cubic_yards: float,
    driveway_protection_used: bool = False,
    spillage_cubic_yards: Optional[float] = None,
    dispatcher_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Close out a DISPATCHED load."""
    headers = (
        make_dispatch_planner_headers(dispatcher_user_id)
        if dispatcher_user_id
        else make_dispatch_planner_headers()
    )
    payload = f.deliver_payload(actual_net_cubic_yards, driveway_protection_used, spillage_cubic_yards)
    return get_success_data(api.deliver_delivery_load(load_id, payload, headers=headers), 200)


def seed_dispatched_load(
    api: ApiClient,
    order_id: str,
    truck_id: str,
    planned_cubic_yards: float,
    window_start: str,
    window_end: str,
    dispatcher_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """A load that has already been released to the road."""
    load = seed_planned_load(api, order_id, truck_id, planned_cubic_yards, window_start, window_end)
    return dispatch_load(api, load["id"], dispatcher_user_id)


def seed_delivered_load(
    api: ApiClient,
    order_id: str,
    truck_id: str,
    planned_cubic_yards: float,
    window_start: str,
    window_end: str,
    *,
    actual_net_cubic_yards: Optional[float] = None,
    driveway_protection_used: bool = False,
    spillage_cubic_yards: Optional[float] = None,
    dispatcher_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """A load taken all the way to DELIVERED, which rolls the order forward."""
    load = seed_dispatched_load(
        api, order_id, truck_id, planned_cubic_yards, window_start, window_end, dispatcher_user_id
    )
    delivered = actual_net_cubic_yards if actual_net_cubic_yards is not None else planned_cubic_yards
    return deliver_load(
        api,
        load["id"],
        delivered,
        driveway_protection_used,
        spillage_cubic_yards,
        dispatcher_user_id,
    )


def seed_fulfilled_delivery_order(
    api: ApiClient,
    *,
    material: Optional[Payload] = None,
    price: Optional[Payload] = None,
    lot: Optional[Payload] = None,
    account: Optional[Payload] = None,
    lines: Iterable[LineSpec] = (("BULK", 10.0),),
    driveway_access_class: str = "CLASS_A",
    delivery_distance_miles: float = 0.0,
    truck: Optional[Payload] = None,
    window_start: str = "2026-08-02T08:00:00.000Z",
    window_end: str = "2026-08-02T10:00:00.000Z",
    driveway_protection_used: bool = False,
    dispatcher_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """A DELIVERY order carried through to FULFILLED by a single full load.

    Returns the confirmed-delivery context plus ``{"load", "order"}`` where ``order``
    is re-read after the delivery cascade.
    """
    context = seed_confirmed_delivery_context(
        api,
        material=material,
        price=price,
        lot=lot,
        account=account,
        lines=lines,
        driveway_access_class=driveway_access_class,
        delivery_distance_miles=delivery_distance_miles,
        truck=truck,
    )
    planned = sum(spec[1] for spec in lines if spec[0] == "BULK")
    load = seed_delivered_load(
        api,
        context["order"]["id"],
        context["truck"]["id"],
        planned,
        window_start,
        window_end,
        driveway_protection_used=driveway_protection_used,
        dispatcher_user_id=dispatcher_user_id,
    )
    order = get_success_data(
        api.get_material_order(
            context["order"]["id"], headers=make_contractor_headers(context["account"]["id"])
        )
    )
    return {**context, "load": load, "order": order}


def invoice_order(api: ApiClient, order_id: str) -> Dict[str, Any]:
    """Invoice a FULFILLED order on the settlement dimension."""
    return get_success_data(api.invoice_material_order(order_id, headers=make_credit_manager_headers()), 200)


def settle_order(api: ApiClient, order_id: str, paid_amount_cents: int) -> Dict[str, Any]:
    """Record payment against an invoiced order."""
    return get_success_data(
        api.settle_material_order(
            order_id, f.settle_order_payload(paid_amount_cents), headers=make_credit_manager_headers()
        ),
        200,
    )


# ------------------------------------------------------- will-call yard progression


def seed_will_call_ticket(
    api: ApiClient, order_id: str, account_id: str, requested_pickup_at: str, **overrides: Any
) -> Dict[str, Any]:
    """Issue a will-call ticket that joins the loading queue."""
    payload = f.create_will_call_ticket_payload(order_id, requested_pickup_at, **overrides)
    return get_success_data(
        api.create_will_call_ticket(payload, headers=make_contractor_headers(account_id)), 201
    )


def stage_next_ticket(
    api: ApiClient,
    staging_window_start: str,
    staging_window_end: str,
    loader_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Pull the next eligible ticket into a staging bay."""
    headers = make_yard_loader_headers(loader_user_id) if loader_user_id else make_yard_loader_headers()
    payload = f.stage_next_payload(staging_window_start, staging_window_end)
    return get_success_data(api.stage_next_will_call_ticket(payload, headers=headers), 200)


def acknowledge_safety(
    api: ApiClient, ticket_id: str, loader_user_id: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    """Record the safety briefing and PPE confirmation that unlock loading."""
    headers = make_yard_loader_headers(loader_user_id) if loader_user_id else make_yard_loader_headers()
    return get_success_data(
        api.safety_ack_will_call_ticket(ticket_id, f.safety_ack_payload(**overrides), headers=headers), 200
    )


def load_ticket(
    api: ApiClient,
    ticket_id: str,
    loaded_cubic_yards: float,
    pallet_count: Optional[int] = None,
    loader_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Load a briefed ticket, drawing the stockpile down."""
    headers = make_yard_loader_headers(loader_user_id) if loader_user_id else make_yard_loader_headers()
    payload = f.load_ticket_payload(loaded_cubic_yards, pallet_count)
    return get_success_data(api.load_will_call_ticket(ticket_id, payload, headers=headers), 200)


def release_ticket(
    api: ApiClient, ticket_id: str, loader_user_id: Optional[str] = None
) -> Dict[str, Any]:
    """Release the loaded vehicle and settle the order's final money."""
    headers = make_yard_loader_headers(loader_user_id) if loader_user_id else make_yard_loader_headers()
    return get_success_data(api.release_will_call_ticket(ticket_id, headers=headers), 200)


def seed_released_will_call_order(
    api: ApiClient,
    *,
    material: Optional[Payload] = None,
    price: Optional[Payload] = None,
    lot: Optional[Payload] = None,
    account: Optional[Payload] = None,
    lines: Iterable[LineSpec] = (("BULK", 10.0),),
    requested_pickup_at: str = "2026-08-01T06:00:00.000Z",
    staging_window_start: str = "2026-08-01T08:00:00.000Z",
    staging_window_end: str = "2026-08-01T09:00:00.000Z",
    loaded_cubic_yards: Optional[float] = None,
    pallet_count: Optional[int] = None,
    loader_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """A WILL_CALL order carried through queue, staging, briefing, load and release."""
    context = seed_confirmed_will_call_context(
        api, material=material, price=price, lot=lot, account=account, lines=lines
    )
    ticket = seed_will_call_ticket(
        api, context["order"]["id"], context["account"]["id"], requested_pickup_at
    )
    stage_next_ticket(api, staging_window_start, staging_window_end, loader_user_id)
    acknowledge_safety(api, ticket["id"], loader_user_id)
    volume = loaded_cubic_yards
    if volume is None:
        volume = sum(spec[1] for spec in lines if spec[0] == "BULK")
    load_ticket(api, ticket["id"], volume, pallet_count, loader_user_id)
    released = release_ticket(api, ticket["id"], loader_user_id)
    order = get_success_data(
        api.get_material_order(
            context["order"]["id"], headers=make_contractor_headers(context["account"]["id"])
        )
    )
    return {**context, "ticket": released, "order": order}


# -------------------------------------------------------------- claims progression


def seed_claim(
    api: ApiClient,
    order_id: str,
    account_id: str,
    claim_type: str,
    claimed_amount_cents: int,
    *,
    delivery_load_id: Optional[str] = None,
    will_call_ticket_id: Optional[str] = None,
    under_review: bool = False,
    adjuster_user_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """File a claim, optionally taking it straight under adjuster review."""
    payload = f.create_claim_case_payload(order_id, claim_type, claimed_amount_cents, **overrides)
    if delivery_load_id is not None:
        payload["delivery_load_id"] = delivery_load_id
    if will_call_ticket_id is not None:
        payload["will_call_ticket_id"] = will_call_ticket_id
    claim = get_success_data(
        api.create_claim_case(payload, headers=make_contractor_headers(account_id)), 201
    )
    if under_review:
        headers = (
            make_claims_adjuster_headers(adjuster_user_id)
            if adjuster_user_id
            else make_claims_adjuster_headers()
        )
        claim = get_success_data(api.start_review_claim_case(claim["id"], headers=headers), 200)
    return claim


def decide_claim(
    api: ApiClient,
    claim_id: str,
    decision: str,
    approved_amount_cents: Optional[int] = None,
    denial_reason: Optional[str] = None,
    adjuster_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Approve or deny a reviewed claim."""
    headers = (
        make_claims_adjuster_headers(adjuster_user_id)
        if adjuster_user_id
        else make_claims_adjuster_headers()
    )
    payload = f.decide_claim_payload(decision, approved_amount_cents, denial_reason)
    return get_success_data(api.decide_claim_case(claim_id, payload, headers=headers), 200)


# ------------------------------------------------------------- container returns


def find_container_return(api: ApiClient, order_id: str) -> Dict[str, Any]:
    """The container-return row the delivery or loading cascade created for an order."""
    body = api.list_container_returns(
        headers=make_yard_admin_headers(), params={"material_order_id": order_id}
    ).json()
    rows = body["data"]
    assert rows, f"no container return row was created for order {order_id}"
    return rows[0]


def receive_containers(
    api: ApiClient, container_return_id: str, returned_count: int, loader_user_id: Optional[str] = None
) -> Dict[str, Any]:
    """Receive returned containers and refund under the decay schedule."""
    headers = make_yard_loader_headers(loader_user_id) if loader_user_id else make_yard_loader_headers()
    return get_success_data(
        api.receive_container_return(
            container_return_id, f.receive_container_payload(returned_count), headers=headers
        ),
        200,
    )


def forfeit_containers(api: ApiClient, container_return_id: str) -> Dict[str, Any]:
    """Forfeit the remaining deposit on containers that never came back."""
    return get_success_data(
        api.forfeit_container_return(container_return_id, headers=make_yard_admin_headers()), 200
    )


# ----------------------------------------------------------------- read shortcuts


def read_order(api: ApiClient, order_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_material_order(order_id, headers=make_yard_admin_headers()))


def read_line(api: ApiClient, line_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_order_line(line_id, headers=make_yard_admin_headers()))


def read_lot(api: ApiClient, lot_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_inventory_lot(lot_id, headers=make_yard_admin_headers()))


def read_material(api: ApiClient, material_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_material(material_id, headers=make_yard_admin_headers()))


def read_account(api: ApiClient, account_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_contractor_account(account_id, headers=make_yard_admin_headers()))


def read_truck(api: ApiClient, truck_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_delivery_truck(truck_id, headers=make_dispatch_planner_headers()))


def read_load(api: ApiClient, load_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_delivery_load(load_id, headers=make_dispatch_planner_headers()))


def read_ticket(api: ApiClient, ticket_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_will_call_ticket(ticket_id, headers=make_yard_admin_headers()))


def read_claim(api: ApiClient, claim_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_claim_case(claim_id, headers=make_yard_admin_headers()))


def read_container_return(api: ApiClient, container_return_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_container_return(container_return_id, headers=make_yard_admin_headers()))


def read_prebuy(api: ApiClient, prebuy_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_prebuy_contract(prebuy_id, headers=make_yard_admin_headers()))


def read_purchase_order(api: ApiClient, po_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_job_purchase_order(po_id, headers=make_yard_admin_headers()))


def read_price_schedule(api: ApiClient, schedule_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_price_schedule(schedule_id, headers=make_yard_admin_headers()))


__all__ = [
    "LineSpec",
    "acknowledge_safety",
    "advance_clock",
    "decide_claim",
    "deliver_load",
    "dispatch_load",
    "find_container_return",
    "forfeit_containers",
    "invoice_order",
    "load_ticket",
    "read_account",
    "read_claim",
    "read_container_return",
    "read_line",
    "read_load",
    "read_lot",
    "read_material",
    "read_order",
    "read_prebuy",
    "read_price_schedule",
    "read_purchase_order",
    "read_ticket",
    "read_truck",
    "receive_containers",
    "release_ticket",
    "seed_account",
    "seed_catalogue",
    "seed_claim",
    "seed_confirmed_delivery_context",
    "seed_confirmed_will_call_context",
    "seed_delivered_load",
    "seed_delivery_order",
    "seed_dispatched_load",
    "seed_fulfilled_delivery_order",
    "seed_inventory_lot",
    "seed_material",
    "seed_planned_load",
    "seed_prebuy",
    "seed_price_schedule",
    "seed_purchase_order",
    "seed_released_will_call_order",
    "seed_truck",
    "seed_will_call_order",
    "seed_will_call_ticket",
    "settle_order",
    "stage_next_ticket",
]
