"""Composite setup builders.

Layered so a test names only the state it needs:

  tier 1  single-row creators (retailer, catalog item, customer, shopper)
  tier 2  entity graphs (draft order with lines)
  tier 3  lifecycle shortcuts (placed / batched / claimed / shopping)
  tier 4  accumulation and threshold targeting (rating histories, counters)
  tier 5  finalization and terminal states (checked out / delivered / abandoned)

Every builder threads identity: the headers used for a call always carry the
X-User-ID of the entity that owns the resource, so no builder can accidentally
pass an ownership check it should have failed.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data, validate_success

from . import factories as f
from .api_client import ApiClient
from .constants import CLOCK_0800, TIER_PROBATION
from .test_users import (
    ADMIN_HEADERS,
    SUPPORT_HEADERS,
    make_customer_headers,
    make_retailer_manager_headers,
    make_shopper_headers,
)

# --------------------------------------------------------------------------
# tier 1 — single rows
# --------------------------------------------------------------------------


def set_clock(api: ApiClient, when: str = CLOCK_0800) -> None:
    get_success_data(api.set_clock(when, ADMIN_HEADERS))


def make_retailer(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    payload = f.retailer_payload(**overrides)
    return get_success_data(api.create_retailer(payload, ADMIN_HEADERS), 201)


def make_catalog_item_each(api: ApiClient, retailer_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = f.catalog_item_each_payload(retailer_id, **overrides)
    return get_success_data(
        api.create_catalog_item(payload, make_retailer_manager_headers(retailer_id)), 201
    )


def make_catalog_item_per_lb(api: ApiClient, retailer_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = f.catalog_item_per_lb_payload(retailer_id, **overrides)
    return get_success_data(
        api.create_catalog_item(payload, make_retailer_manager_headers(retailer_id)), 201
    )


def make_customer(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    payload = f.customer_payload(**overrides)
    return get_success_data(api.create_customer(payload, SUPPORT_HEADERS), 201)


def make_shopper(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    payload = f.shopper_payload(**overrides)
    return get_success_data(api.create_shopper(payload, ADMIN_HEADERS), 201)


def make_batch(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    payload = f.batch_payload(**overrides)
    return get_success_data(api.create_batch(payload, ADMIN_HEADERS), 201)


def set_shopper_history(api: ApiClient, shopper_id: str, **counters: Any) -> Dict[str, Any]:
    return get_success_data(
        api.set_shopper_history(shopper_id, dict(counters), ADMIN_HEADERS)
    )


def backfill_ratings(
    api: ApiClient, shopper_id: str, stars_sequence: List[int]
) -> Dict[str, Any]:
    return get_success_data(
        api.backfill_ratings(
            f.ratings_backfill_payload(shopper_id, stars_sequence), ADMIN_HEADERS
        )
    )


def post_credit(
    api: ApiClient, customer_id: str, amount_cents: int, reason_code: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_customer_credit(
            customer_id,
            f.credit_entry_payload(amount_cents, reason_code, **overrides),
            SUPPORT_HEADERS,
        ),
        201,
    )


# --------------------------------------------------------------------------
# tier 2 — order graphs
# --------------------------------------------------------------------------


def make_draft_order(
    api: ApiClient, customer_id: str, retailer_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload = f.order_payload(customer_id, retailer_id, **overrides)
    return get_success_data(
        api.create_order(payload, make_customer_headers(customer_id)), 201
    )


def add_line_each(
    api: ApiClient, order_id: str, customer_id: str, catalog_item_id: str, requested_qty: int = 1,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = f.line_each_payload(catalog_item_id, requested_qty, **overrides)
    return get_success_data(
        api.create_order_line(order_id, payload, make_customer_headers(customer_id)), 201
    )


def add_line_per_lb(
    api: ApiClient, order_id: str, customer_id: str, catalog_item_id: str,
    requested_weight_lb: float = 2.0, **overrides: Any,
) -> Dict[str, Any]:
    payload = f.line_per_lb_payload(catalog_item_id, requested_weight_lb, **overrides)
    return get_success_data(
        api.create_order_line(order_id, payload, make_customer_headers(customer_id)), 201
    )


def submit_order(api: ApiClient, order_id: str, customer_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.submit_order(order_id, make_customer_headers(customer_id))
    )


# --------------------------------------------------------------------------
# tier 3 — lifecycle shortcuts
# --------------------------------------------------------------------------


def attach_order(api: ApiClient, batch_id: str, order_id: str) -> Dict[str, Any]:
    """Attach with the batch's CURRENT version, so the OCC guard passes."""
    batch = validate_success(api.get_batch(batch_id, ADMIN_HEADERS))
    payload = f.batch_order_payload(order_id, batch["version"])
    return get_success_data(api.add_order_to_batch(batch_id, payload, ADMIN_HEADERS), 201)


def dispatch(api: ApiClient, batch_id: str) -> Dict[str, Any]:
    return get_success_data(api.dispatch_batch(batch_id, ADMIN_HEADERS))


def claim(api: ApiClient, batch_id: str, shopper_id: str) -> Dict[str, Any]:
    return get_success_data(api.claim_batch(batch_id, make_shopper_headers(shopper_id)))


def start_shopping(api: ApiClient, batch_id: str, shopper_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.start_shopping(batch_id, make_shopper_headers(shopper_id))
    )


def pick_each(api: ApiClient, line_id: str, shopper_id: str, picked_qty: int) -> Dict[str, Any]:
    return get_success_data(
        api.pick_order_line(
            line_id, f.pick_each_payload(picked_qty), make_shopper_headers(shopper_id)
        )
    )


def pick_weighted(
    api: ApiClient, line_id: str, shopper_id: str, final_weight_lb: float
) -> Dict[str, Any]:
    return get_success_data(
        api.pick_order_line(
            line_id,
            f.pick_weighted_payload(final_weight_lb),
            make_shopper_headers(shopper_id),
        )
    )


def checkout(api: ApiClient, batch_id: str, shopper_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.checkout_batch(batch_id, make_shopper_headers(shopper_id))
    )


def deliver(api: ApiClient, batch_id: str, shopper_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.deliver_batch(batch_id, make_shopper_headers(shopper_id))
    )


def abandon(
    api: ApiClient, batch_id: str, shopper_id: str, reason_note: Optional[str] = None
) -> Dict[str, Any]:
    return get_success_data(
        api.abandon_batch(
            batch_id, make_shopper_headers(shopper_id), f.abandon_payload(reason_note)
        )
    )


def propose_replacement(
    api: ApiClient,
    batch_id: str,
    order_line_id: str,
    proposed_catalog_item_id: str,
    shopper_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = f.replacement_request_payload(
        batch_id, order_line_id, proposed_catalog_item_id, **overrides
    )
    return get_success_data(
        api.create_replacement_request(payload, make_shopper_headers(shopper_id)), 201
    )


def approve_replacement(api: ApiClient, request_id: str, customer_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.approve_replacement_request(request_id, make_customer_headers(customer_id))
    )


def reject_replacement(api: ApiClient, request_id: str, customer_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.reject_replacement_request(request_id, make_customer_headers(customer_id))
    )


# --------------------------------------------------------------------------
# tier 3/5 — whole-world composites
# --------------------------------------------------------------------------


def base_world(
    api: ApiClient,
    clock: str = CLOCK_0800,
    service_area_code: str = "SF-01",
    markup: float = 0.15,
    vehicle_capacity_units: int = 10,
    ebt_snap_balance_cents: int = 0,
    **retailer_overrides: Any,
) -> Dict[str, Any]:
    """Clock + one retailer + an EACH item + a customer + a shopper."""
    set_clock(api, clock)
    retailer = make_retailer(api, catalog_markup_pct=markup, **retailer_overrides)
    item = make_catalog_item_each(api, retailer["id"])
    customer_kwargs: Dict[str, Any] = {}
    if ebt_snap_balance_cents:
        customer_kwargs["ebt_snap_balance_cents"] = ebt_snap_balance_cents
    customer = make_customer(api, **customer_kwargs)
    shopper = make_shopper(
        api,
        service_area_code=service_area_code,
        vehicle_capacity_units=vehicle_capacity_units,
    )
    return {
        "clock": clock,
        "service_area_code": service_area_code,
        "retailer": retailer,
        "item": item,
        "customer": customer,
        "shopper": shopper,
    }


def placed_order(
    api: ApiClient,
    world: Dict[str, Any],
    requested_qty: int = 1,
    **order_overrides: Any,
) -> Dict[str, Any]:
    """A single-line EACH order taken all the way to PLACED / AUTHORIZED."""
    customer_id = world["customer"]["id"]
    order = make_draft_order(
        api, customer_id, world["retailer"]["id"], **order_overrides
    )
    line = add_line_each(
        api, order["id"], customer_id, world["item"]["id"], requested_qty
    )
    submitted = submit_order(api, order["id"], customer_id)
    return {"order": submitted, "line": line}


def batch_with_order(
    api: ApiClient,
    world: Dict[str, Any],
    order_id: str,
    tier_access_floor: str = TIER_PROBATION,
    **batch_overrides: Any,
) -> Dict[str, Any]:
    batch = make_batch(
        api,
        service_area_code=world["service_area_code"],
        tier_access_floor=tier_access_floor,
        **batch_overrides,
    )
    membership = attach_order(api, batch["id"], order_id)
    return {"batch": batch, "membership": membership}


def claimed_batch_world(
    api: ApiClient,
    clock: str = CLOCK_0800,
    service_area_code: str = "SF-01",
    requested_qty: int = 1,
    tip_amount_cents: int = 0,
    **world_overrides: Any,
) -> Dict[str, Any]:
    """base_world plus a placed order inside a batch claimed by the shopper."""
    world = base_world(
        api, clock=clock, service_area_code=service_area_code, **world_overrides
    )
    placed = placed_order(
        api, world, requested_qty=requested_qty, tip_amount_cents=tip_amount_cents
    )
    made = batch_with_order(api, world, placed["order"]["id"])
    dispatch(api, made["batch"]["id"])
    claim(api, made["batch"]["id"], world["shopper"]["id"])
    world.update(
        {
            "order": placed["order"],
            "line": placed["line"],
            "batch": made["batch"],
            "membership": made["membership"],
        }
    )
    return world


def shopping_batch_world(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    """claimed_batch_world advanced into SHOPPING."""
    world = claimed_batch_world(api, **kwargs)
    start_shopping(api, world["batch"]["id"], world["shopper"]["id"])
    return world


def checked_out_batch_world(api: ApiClient, requested_qty: int = 1, **kwargs: Any) -> Dict[str, Any]:
    """shopping_batch_world with the single line picked and the batch rung up."""
    world = shopping_batch_world(api, requested_qty=requested_qty, **kwargs)
    pick_each(api, world["line"]["id"], world["shopper"]["id"], requested_qty)
    checkout(api, world["batch"]["id"], world["shopper"]["id"])
    return world


def delivered_batch_world(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    """checked_out_batch_world handed over, so a PROVISIONAL payout exists."""
    world = checked_out_batch_world(api, **kwargs)
    deliver(api, world["batch"]["id"], world["shopper"]["id"])
    return world
