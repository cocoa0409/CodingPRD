"""Composite setup helpers for the white-label delivery workflows.

Every test starts against an empty database (the server is restarted per
test), so each fixture builds its full precondition chain from scratch using
only PRD-declared endpoints. The shared building blocks:

  new_merchant()            -> merchant dict (ONBOARDING)
  activate_merchant()       -> merchant ACTIVE
  add_store()               -> store ACTIVE
  add_policy()              -> policy DRAFT
  activate_policy()         -> policy ACTIVE (reads fresh merchant version)
  add_courier()             -> courier ACTIVE
  new_quote()               -> quote ACTIVE
  make_order_from_quote()   -> order QUOTED / PENDING
  accept_order()            -> order ACCEPTED / AUTHORIZED
  make_order_ready()        -> order READY_FOR_PICKUP
  batch_orders()            -> batch COURIER_ASSIGNED (reads fresh courier version)
  dispatch_batch()          -> batch DISPATCHED (drives final fee + allocation)
  drive_to_in_transit()     -> pickup + transit
  complete_delivery()       -> DELIVERED / SETTLED
  file_claim() / decide_claim() / settle_claim() -> refund-claim lifecycle
  finalize_report()         -> SLA report FINALIZED

The convenience entry point most tests use is base_chain(), which returns a
namespace dict with merchant / store / policy / courier / headers threaded
for ownership-gated calls.
"""
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    accept_order_payload,
    check_serviceability_payload,
    complete_disposition_payload,
    create_batch_payload,
    create_courier_payload,
    create_disposition_payload,
    create_merchant_payload,
    create_order_payload,
    create_pricing_policy_payload,
    create_quote_payload,
    create_refund_claim_payload,
    create_serviceability_override_payload,
    create_sla_report_payload,
    create_store_payload,
    decide_claim_payload,
    report_undeliverable_payload,
)
from .test_users import (
    make_courier_headers,
    make_merchant_headers,
    make_platform_admin_headers,
    make_support_agent_headers,
)

START_CLOCK = "2026-09-01T00:00:00Z"


def admin_headers() -> dict:
    return make_platform_admin_headers()


def support_headers() -> dict:
    return make_support_agent_headers()


def m_headers(merchant_id: str) -> dict:
    return make_merchant_headers(merchant_id)


def c_headers(courier_id: str) -> dict:
    return make_courier_headers(courier_id)


def set_clock(current_utc: str = START_CLOCK):
    """Drive the logical clock."""
    return get_success_data(api_client.set_clock({"current_utc": current_utc}, admin_headers()))


def set_surge(multiplier: float):
    """Set the platform surge multiplier."""
    return get_success_data(api_client.set_surge({"multiplier": multiplier}, admin_headers()))


# --- Tier 1: state progression for each entity --------------------------------

def new_merchant(**overrides) -> dict:
    """Create a merchant (ONBOARDING)."""
    return get_success_data(
        api_client.create_merchant(create_merchant_payload(**overrides), admin_headers())
    )


def activate_merchant(merchant_id: str) -> dict:
    return get_success_data(api_client.activate_merchant(merchant_id, admin_headers()))


def suspend_merchant(merchant_id: str) -> dict:
    return get_success_data(api_client.suspend_merchant(merchant_id, admin_headers()))


def resume_merchant(merchant_id: str) -> dict:
    return get_success_data(api_client.resume_merchant(merchant_id, admin_headers()))


def get_merchant(merchant_id: str) -> dict:
    return get_success_data(api_client.get_merchant(merchant_id, admin_headers()))


def merchant_version(merchant_id: str) -> int:
    return get_merchant(merchant_id)["version"]


def add_store(merchant_id: str, **overrides) -> dict:
    """Create a store under the merchant (ownership-gated -> merchant headers)."""
    return get_success_data(
        api_client.create_store(
            merchant_id, create_store_payload(**overrides), m_headers(merchant_id)
        )
    )


def add_policy(merchant_id: str, **overrides) -> dict:
    """Create a pricing policy (DRAFT)."""
    return get_success_data(
        api_client.create_pricing_policy(
            merchant_id, create_pricing_policy_payload(**overrides), m_headers(merchant_id)
        )
    )


def activate_policy(merchant_id: str, policy_id: str) -> dict:
    """Activate a policy; reads the merchant's fresh version for the OCC field."""
    version = merchant_version(merchant_id)
    return get_success_data(
        api_client.activate_pricing_policy(
            merchant_id, policy_id, {"expected_merchant_version": version},
            m_headers(merchant_id),
        )
    )


def add_courier(**overrides) -> dict:
    return get_success_data(
        api_client.create_courier(create_courier_payload(**overrides), admin_headers())
    )


def courier_version(courier_id: str) -> int:
    return get_success_data(api_client.get_courier(courier_id, admin_headers()))["version"]


# --- Tier 2/3: quote -> order lifecycle ----------------------------------------

def new_quote(merchant_id: str, store_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_quote(
            create_quote_payload(store_id, **overrides), m_headers(merchant_id)
        )
    )


def make_order_from_quote(merchant_id: str, quote_id: str, idempotency_key: str,
                          **overrides) -> dict:
    """Consume a quote into an order (QUOTED / PENDING)."""
    return get_success_data(
        api_client.create_order(
            create_order_payload(quote_id, idempotency_key, **overrides),
            m_headers(merchant_id),
        )
    )


def make_order(merchant_id: str, store_id: str, idempotency_key: str,
               quote_overrides: Optional[dict] = None, **order_overrides) -> dict:
    """Quote + order in one call."""
    quote = new_quote(merchant_id, store_id, **(quote_overrides or {}))
    return make_order_from_quote(merchant_id, quote["id"], idempotency_key, **order_overrides)


def accept_order(merchant_id: str, order_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.accept_order(order_id, accept_order_payload(**overrides), m_headers(merchant_id))
    )


def make_order_ready(merchant_id: str, order_id: str, promised_at: Optional[str] = None) -> dict:
    """ACCEPTED -> READY_FOR_PICKUP (accepts first if needed by caller order)."""
    if promised_at is not None:
        accept_order(merchant_id, order_id, promised_at=promised_at)
    return get_success_data(api_client.mark_ready(order_id, m_headers(merchant_id)))


def make_order_accepted(merchant_id: str, store_id: str, idempotency_key: str,
                        promised_at: Optional[str] = None,
                        quote_overrides: Optional[dict] = None) -> dict:
    order = make_order(merchant_id, store_id, idempotency_key, quote_overrides=quote_overrides)
    return accept_order(merchant_id, order["id"],
                        **({"promised_at": promised_at} if promised_at else {}))


def make_order_ready_fresh(merchant_id: str, store_id: str, idempotency_key: str,
                           promised_at: Optional[str] = None,
                           quote_overrides: Optional[dict] = None) -> dict:
    order = make_order_accepted(
        merchant_id, store_id, idempotency_key, promised_at=promised_at,
        quote_overrides=quote_overrides,
    )
    return make_order_ready(merchant_id, order["id"])


def get_order(merchant_id: str, order_id: str) -> dict:
    return get_success_data(api_client.get_order(order_id, m_headers(merchant_id)))


# --- Tier 3: batching and courier execution ------------------------------------

def batch_orders(store_id: str, courier_id: str, order_ids: List[str],
                 window_start: str = "2026-09-01T00:30:00Z",
                 window_end: str = "2026-09-01T01:30:00Z") -> dict:
    """Create a batch; reads the courier's fresh version for the OCC field."""
    version = courier_version(courier_id)
    return get_success_data(
        api_client.create_batch(
            create_batch_payload(
                store_id, courier_id, order_ids, version,
                dispatch_window_start=window_start, dispatch_window_end=window_end,
            ),
            admin_headers(),
        )
    )


def dispatch_batch(courier_id: str, batch_id: str) -> dict:
    return get_success_data(api_client.dispatch_batch(batch_id, c_headers(courier_id)))


def fail_batch(courier_id: str, batch_id: str) -> dict:
    return get_success_data(api_client.fail_batch(batch_id, c_headers(courier_id)))


def get_batch(batch_id: str) -> dict:
    return get_success_data(api_client.get_batch(batch_id, admin_headers()))


def drive_to_picked_up(courier_id: str, order_id: str) -> dict:
    return get_success_data(api_client.confirm_pickup(order_id, c_headers(courier_id)))


def drive_to_in_transit(courier_id: str, order_id: str) -> dict:
    drive_to_picked_up(courier_id, order_id)
    return get_success_data(api_client.start_transit(order_id, c_headers(courier_id)))


def complete_delivery(courier_id: str, order_id: str) -> dict:
    return get_success_data(api_client.complete_delivery(order_id, c_headers(courier_id)))


def report_undeliverable(courier_id: str, order_id: str, reason_code: str) -> dict:
    return get_success_data(
        api_client.report_undeliverable(
            order_id, report_undeliverable_payload(reason_code=reason_code), c_headers(courier_id)
        )
    )


def make_disposition(merchant_id: str, order_id: str, resolution: str) -> dict:
    return get_success_data(
        api_client.create_disposition(
            order_id, create_disposition_payload(resolution=resolution), m_headers(merchant_id)
        )
    )


def complete_disposition(courier_id: str, disposition_id: str, outcome: str) -> dict:
    return get_success_data(
        api_client.complete_disposition(
            disposition_id, complete_disposition_payload(outcome=outcome), c_headers(courier_id)
        )
    )


# --- Tier 3: refund-claim lifecycle --------------------------------------------

def file_claim(merchant_id: str, order_id: str, fault_code: str,
               claimed_amount_cents: int) -> dict:
    return get_success_data(
        api_client.create_refund_claim(
            create_refund_claim_payload(
                order_id, fault_code=fault_code, claimed_amount_cents=claimed_amount_cents
            ),
            m_headers(merchant_id),
        )
    )


def decide_claim(claim_id: str, decision: str) -> dict:
    get_success_data(api_client.start_claim_review(claim_id, support_headers()))
    return get_success_data(
        api_client.decide_claim(claim_id, decide_claim_payload(decision), support_headers())
    )


def settle_claim(claim_id: str) -> dict:
    return get_success_data(api_client.settle_claim(claim_id, admin_headers()))


def reverse_claim(claim_id: str) -> dict:
    return get_success_data(api_client.reverse_claim(claim_id, admin_headers()))


def get_claim(claim_id: str) -> dict:
    return get_success_data(api_client.get_refund_claim(claim_id, admin_headers()))


def make_claim_in_state(merchant_id: str, order_id: str, target_state: str,
                        fault_code: str = "COURIER_DELAY",
                        claimed_amount_cents: int = 200) -> dict:
    """Walk a claim to FILED / UNDER_REVIEW / APPROVED / DENIED / SETTLED / REVERSED."""
    claim = file_claim(merchant_id, order_id, fault_code, claimed_amount_cents)
    if target_state == "FILED":
        return claim
    get_success_data(api_client.start_claim_review(claim["id"], support_headers()))
    if target_state == "UNDER_REVIEW":
        return get_claim(claim["id"])
    decision = "APPROVE" if target_state in ("APPROVED", "SETTLED", "REVERSED") else "DENY"
    claim = get_success_data(
        api_client.decide_claim(claim["id"], decide_claim_payload(decision), support_headers())
    )
    if target_state in ("APPROVED", "DENIED"):
        return claim
    claim = settle_claim(claim["id"])
    if target_state == "SETTLED":
        return claim
    return reverse_claim(claim["id"])


# --- Tier 5: SLA reports / credits ---------------------------------------------

def open_report(merchant_id: str, period_start: str = "2026-09-01T00:00:00Z",
                period_end: str = "2026-09-02T00:00:00Z") -> dict:
    return get_success_data(
        api_client.create_sla_report(
            merchant_id,
            create_sla_report_payload(period_start=period_start, period_end=period_end),
            admin_headers(),
        )
    )


def finalize_report(report_id: str) -> dict:
    return get_success_data(api_client.finalize_sla_report(report_id, admin_headers()))


def list_report_credits(report_id: str) -> List[dict]:
    return get_success_data(api_client.list_report_credits(report_id, admin_headers()))


def add_override(merchant_id: str, store_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_serviceability_override(
            store_id, create_serviceability_override_payload(**overrides),
            m_headers(merchant_id),
        )
    )


def check_serviceability(merchant_id: str, store_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.check_serviceability(
            store_id, check_serviceability_payload(**overrides), m_headers(merchant_id)
        )
    )


# --- Composite entry points -----------------------------------------------------

def base_chain(set_clock_first: bool = True, surge: Optional[float] = None,
               merchant_overrides: Optional[dict] = None,
               store_overrides: Optional[dict] = None,
               policy_overrides: Optional[dict] = None,
               courier_overrides: Optional[dict] = None,
               with_policy_activated: bool = True,
               with_courier: bool = True,
               with_store: bool = True) -> Dict[str, Any]:
    """Clock -> merchant (ACTIVE) -> store -> policy (ACTIVE) -> courier.

    Returns a namespace dict: merchant, store, policy, courier, and the
    ownership-threaded headers (merchant_headers / courier_headers / admin).
    """
    if set_clock_first:
        set_clock()
    if surge is not None:
        set_surge(surge)
    merchant = new_merchant(**(merchant_overrides or {}))
    activate_merchant(merchant["id"])
    merchant = get_merchant(merchant["id"])
    mh = m_headers(merchant["id"])
    store = (
        add_store(merchant["id"], **(store_overrides or {})) if with_store else None
    )
    policy = add_policy(merchant["id"], **(policy_overrides or {}))
    if with_policy_activated:
        policy = activate_policy(merchant["id"], policy["id"])
        merchant = get_merchant(merchant["id"])
    courier = add_courier(**(courier_overrides or {})) if with_courier else None
    return {
        "merchant": merchant,
        "store": store,
        "policy": policy,
        "courier": courier,
        "merchant_headers": mh,
        "courier_headers": c_headers(courier["id"]) if courier else None,
        "admin_headers": admin_headers(),
        "support_headers": support_headers(),
    }


def ready_order_in_batch(env: Dict[str, Any], idempotency_key: str = "fx-1",
                         promised_at: Optional[str] = None,
                         quote_overrides: Optional[dict] = None,
                         window_start: str = "2026-09-01T00:30:00Z",
                         window_end: str = "2026-09-01T01:30:00Z") -> Dict[str, Any]:
    """Extend base_chain env with one READY_FOR_PICKUP order in a
    COURIER_ASSIGNED batch."""
    merchant_id = env["merchant"]["id"]
    order = make_order_ready_fresh(
        merchant_id, env["store"]["id"], idempotency_key,
        promised_at=promised_at, quote_overrides=quote_overrides,
    )
    batch = batch_orders(
        env["store"]["id"], env["courier"]["id"], [order["id"]],
        window_start=window_start, window_end=window_end,
    )
    env = dict(env)
    env.update({"order": order, "batch": batch})
    return env


def dispatched_order(env: Dict[str, Any], **kwargs) -> Dict[str, Any]:
    """Extend base_chain env with one order in a DISPATCHED batch."""
    env = ready_order_in_batch(env, **kwargs)
    batch = dispatch_batch(env["courier"]["id"], env["batch"]["id"])
    env = dict(env)
    env["batch"] = batch
    env["order"] = get_order(env["merchant"]["id"], env["order"]["id"])
    return env


def in_transit_order(env: Dict[str, Any], **kwargs) -> Dict[str, Any]:
    """Extend base_chain env with one order driven to IN_TRANSIT."""
    env = dispatched_order(env, **kwargs)
    env = dict(env)
    env["order"] = drive_to_in_transit(env["courier"]["id"], env["order"]["id"])
    return env


def delivered_order(env: Dict[str, Any], delivered_at: str = "2026-09-01T01:00:00Z",
                    **kwargs) -> Dict[str, Any]:
    """Extend base_chain env with one DELIVERED / SETTLED order (clock moved
    to `delivered_at` right before completion)."""
    env = in_transit_order(env, **kwargs)
    set_clock(delivered_at)
    env = dict(env)
    env["order"] = complete_delivery(env["courier"]["id"], env["order"]["id"])
    env["batch"] = get_batch(env["batch"]["id"])
    env["merchant"] = get_merchant(env["merchant"]["id"])
    return env
