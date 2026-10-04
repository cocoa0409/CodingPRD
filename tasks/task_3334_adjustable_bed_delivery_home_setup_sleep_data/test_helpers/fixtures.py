"""Composite setup helpers for the adjustable-bed sleep retail API.

Every fixture builds its preconditions from scratch via PRD-declared
endpoints; the harness restarts the server (empty database) before each test.
Fixtures use get_success_data() so setup failures surface as clear
"Setup failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_START, TEST_DEFAULTS
from .factories import (
    create_customer_payload,
    create_delivery_visit_payload,
    create_delivery_window_payload,
    create_device_payload,
    create_fit_assessment_payload,
    create_order_payload,
    create_product_model_payload,
    create_store_payload,
)
from .test_users import TEST_USERS, make_customer_headers

ADMIN = TEST_USERS["admin_headers"]
ANON = TEST_USERS["anonymous_headers"]
SALES = TEST_USERS["sales_headers"]
TECH = TEST_USERS["technician_headers"]
SERVICE = TEST_USERS["service_headers"]
FINANCE = TEST_USERS["finance_headers"]
GATEWAY = TEST_USERS["gateway_headers"]

CHECKLIST_OK = TEST_DEFAULTS["CHECKLIST_ALL_TRUE"]


def set_clock(to_iso8601=CLOCK_START):
    """Pin the logical clock."""
    get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def create_store(**overrides):
    payload = create_store_payload(**overrides)
    return get_success_data(api_client.create_store(payload, ADMIN))


def create_product_models(specs):
    """specs: list of dicts of ProductModel fields. Returns list of models."""
    out = []
    for spec in specs:
        out.append(get_success_data(
            api_client.create_product_model(spec, ADMIN)))
    return out


def create_full_catalog():
    """One model per required recommendation category (MATTRESS,
    ADJUSTABLE_BASE, AIR_CHAMBER, PUMP) with distinct prices."""
    specs = [
        create_product_model_payload(
            sku="MAT-1", name="Mattress One", category="MATTRESS",
            price_cents=240000, replacement_part_price_cents=0,
            warranty_months=120),
        create_product_model_payload(
            sku="BASE-1", name="Base One", category="ADJUSTABLE_BASE",
            price_cents=180000, replacement_part_price_cents=0,
            warranty_months=120),
        create_product_model_payload(
            sku="CHAM-1", name="Chamber One", category="AIR_CHAMBER",
            price_cents=40000, replacement_part_price_cents=40000,
            warranty_months=60),
        create_product_model_payload(
            sku="PUMP-1", name="Pump One", category="PUMP",
            price_cents=30000, replacement_part_price_cents=30000,
            warranty_months=36),
    ]
    return create_product_models(specs)


def create_customer(store_id, email="a@x.com", full_name="Ann A", **overrides):
    payload = create_customer_payload(store_id, email=email,
                                      full_name=full_name, **overrides)
    return get_success_data(api_client.create_customer(payload, ANON))


def create_completed_assessment(customer_id, store_id, **overrides):
    """Create + complete a fit assessment. Returns the COMPLETED assessment."""
    payload = create_fit_assessment_payload(customer_id, store_id, **overrides)
    fa = get_success_data(api_client.create_fit_assessment(payload, SALES))
    return get_success_data(api_client.complete_fit_assessment(fa["id"], SALES))


def create_order(customer_id, fit_assessment_id, line_items=None, **overrides):
    payload = create_order_payload(customer_id, fit_assessment_id,
                                   line_items, **overrides)
    return get_success_data(
        api_client.create_order(payload, make_customer_headers(customer_id)))


def create_confirmed_order(customer_id, fit_assessment_id, line_items=None):
    """Create a PLACED order and confirm it PAY_IN_FULL. Returns the order."""
    order = create_order(customer_id, fit_assessment_id, line_items)
    return get_success_data(api_client.confirm_order(
        order["id"], {"payment_method": "PAY_IN_FULL"}, SALES))


def create_delivery_window(store_id, **overrides):
    payload = create_delivery_window_payload(store_id, **overrides)
    return get_success_data(api_client.create_delivery_window(payload, ADMIN))


def create_delivery_visit(order_id, window_id, **overrides):
    payload = create_delivery_visit_payload(order_id, window_id, **overrides)
    return get_success_data(api_client.create_delivery_visit(payload, SALES))


def register_device(order_id, kind="BASE", serial_number="SN-1", **overrides):
    payload = create_device_payload(order_id, kind=kind,
                                    serial_number=serial_number, **overrides)
    return get_success_data(api_client.create_device(payload, TECH))


def pair_device(device_id, connectivity_verified=True):
    return get_success_data(api_client.pair_device(
        device_id,
        {"target_status": "PAIRED", "connectivity_verified": connectivity_verified},
        TECH))


def verify_visit(visit_id):
    return get_success_data(api_client.complete_visit(
        visit_id, {"outcome": "VERIFIED",
                   "setup_checklist": dict(CHECKLIST_OK)}, TECH))


def setup_store_with_catalog():
    """Clock pinned + one store + the four-category catalog. Returns store."""
    set_clock()
    store = create_store()
    create_full_catalog()
    return store


def setup_customer_with_completed_assessment(email="a@x.com"):
    """Store + catalog + customer + COMPLETED assessment.
    Returns (store, customer, assessment)."""
    store = setup_store_with_catalog()
    customer = create_customer(store["id"], email=email)
    fa = create_completed_assessment(customer["id"], store["id"])
    return store, customer, fa


def setup_confirmed_order(email="a@x.com", line_items=None):
    """Full chain to a CONFIRMED (PAY_IN_FULL) order.
    Returns (store, customer, assessment, order)."""
    store, customer, fa = setup_customer_with_completed_assessment(email=email)
    order = create_confirmed_order(customer["id"], fa["id"], line_items)
    return store, customer, fa, order


def setup_scheduled_visit(email="a@x.com", line_items=None, window_capacity=4,
                          window_start=None, window_end=None):
    """CONFIRMED order + window + SCHEDULED visit.
    Returns dict with store, customer, assessment, order, window, visit."""
    store, customer, fa, order = setup_confirmed_order(email=email,
                                                       line_items=line_items)
    win_kwargs = {"capacity_slots": window_capacity}
    if window_start:
        win_kwargs["window_start"] = window_start
    if window_end:
        win_kwargs["window_end"] = window_end
    window = create_delivery_window(store["id"], **win_kwargs)
    visit = create_delivery_visit(order["id"], window["id"])
    return {
        "store": store, "customer": customer, "assessment": fa,
        "order": order, "window": window, "visit": visit,
    }


def setup_delivered_order(email="a@x.com", line_items=None, window_capacity=4,
                          window_start=None, window_end=None,
                          device_kind="BASE", serial_number="SN-1",
                          verify=True):
    """CONFIRMED order + scheduled visit + paired device + (optionally)
    VERIFIED visit (order DELIVERED, trial_verified_at stamped).
    Returns dict with store/customer/assessment/order/window/visit/device."""
    ctx = setup_scheduled_visit(email=email, line_items=line_items,
                                window_capacity=window_capacity,
                                window_start=window_start,
                                window_end=window_end)
    device = register_device(ctx["order"]["id"], kind=device_kind,
                             serial_number=serial_number)
    ctx["device"] = device
    if verify:
        pair_device(device["id"])
        ctx["visit"] = verify_visit(ctx["visit"]["id"])
        ctx["order"] = get_success_data(
            api_client.get_order(ctx["order"]["id"], ADMIN))
    return ctx


def setup_financed_order(email="f@x.com", line_items=None,
                         offer_type="ZERO_APR", term_months=12, apr_bps=0,
                         down_payment_cents=None, confirm=True,
                         extra_models=None):
    """PLACED order + financing plan (accepted, and activated if confirm).
    Returns dict with store/customer/assessment/order/plan."""
    store, customer, fa = setup_customer_with_completed_assessment(email=email)
    if extra_models:
        create_product_models(extra_models)
    order = create_order(customer["id"], fa["id"], line_items)
    plan_payload = {
        "order_id": order["id"],
        "offer_type": offer_type,
        "term_months": term_months,
        "apr_bps": apr_bps,
    }
    if down_payment_cents is not None:
        plan_payload["down_payment_cents"] = down_payment_cents
    plan = get_success_data(
        api_client.create_financing_plan(plan_payload, FINANCE))
    get_success_data(api_client.accept_financing_plan(
        plan["id"], make_customer_headers(customer["id"])))
    if confirm:
        order = get_success_data(api_client.confirm_order(
            order["id"],
            {"payment_method": "FINANCING", "financing_plan_id": plan["id"]},
            SALES))
        plan = get_success_data(
            api_client.get_financing_plan(plan["id"], FINANCE))
    return {
        "store": store, "customer": customer, "assessment": fa,
        "order": order, "plan": plan,
    }


def ingest_night(device_id, night_date, minutes_asleep=420,
                 restlessness_events=10, avg_heart_rate=64):
    """Ingest one sleep night via the device gateway. Returns the night."""
    return get_success_data(api_client.ingest_sleep_night(device_id, {
        "night_date": night_date,
        "minutes_asleep": minutes_asleep,
        "restlessness_events": restlessness_events,
        "avg_heart_rate": avg_heart_rate,
    }, GATEWAY))


def setup_financed_delivered_order(email="fd@x.com", line_items=None,
                                   offer_type="ZERO_APR", term_months=12,
                                   apr_bps=0, down_payment_cents=None,
                                   extra_models=None, payments=(),
                                   window_start=None, window_end=None):
    """Financed CONFIRMED order + scheduled visit + paired BASE device +
    VERIFIED visit (order DELIVERED). Optional payments recorded while the
    plan is ACTIVE (payments are recorded after delivery — the plan is
    already ACTIVE from confirmation, so order matters only for clarity).
    Returns dict with store/customer/assessment/order/plan/window/visit/device.
    """
    ctx = setup_financed_order(email=email, line_items=line_items,
                               offer_type=offer_type, term_months=term_months,
                               apr_bps=apr_bps,
                               down_payment_cents=down_payment_cents,
                               confirm=True, extra_models=extra_models)
    win_kwargs = {}
    if window_start:
        win_kwargs["window_start"] = window_start
    if window_end:
        win_kwargs["window_end"] = window_end
    window = create_delivery_window(ctx["store"]["id"], **win_kwargs)
    visit = create_delivery_visit(ctx["order"]["id"], window["id"])
    device = register_device(ctx["order"]["id"], kind="BASE",
                             serial_number="SN-FD1")
    pair_device(device["id"])
    ctx["visit"] = verify_visit(visit["id"])
    ctx["window"] = window
    ctx["device"] = device
    for amount in payments:
        record_payment(ctx["plan"]["id"], amount)
    ctx["order"] = get_success_data(
        api_client.get_order(ctx["order"]["id"], ADMIN))
    ctx["plan"] = get_success_data(
        api_client.get_financing_plan(ctx["plan"]["id"], FINANCE))
    return ctx


def record_payment(plan_id, amount_cents):
    """Record a financing payment as the finance agent. Returns the plan."""
    return get_success_data(api_client.record_payment(
        plan_id, {"amount_cents": amount_cents}, FINANCE))


def initiate_return(order_id, customer_id, reason="not for me",
                    refund_destination="ORIGINAL_PAYMENT"):
    """Initiate a trial return as the owning customer. Returns the return."""
    return get_success_data(api_client.initiate_trial_return(
        order_id, {"reason": reason, "refund_destination": refund_destination},
        make_customer_headers(customer_id)))


def inspect_return(return_id, outcome="APPROVED", condition="GOOD"):
    """Inspect a trial return as the service agent. Returns the return."""
    return get_success_data(api_client.inspect_trial_return(
        return_id, {"outcome": outcome, "condition": condition}, SERVICE))


def file_warranty_claim(order_id, device_id, customer_id,
                        component_category="CHAMBER",
                        proration_variant="TIME_BASED",
                        description="failure"):
    """File a warranty claim as the owning customer. Returns the claim."""
    return get_success_data(api_client.create_warranty_claim(
        {"order_id": order_id, "device_id": device_id,
         "component_category": component_category,
         "proration_variant": proration_variant,
         "description": description},
        make_customer_headers(customer_id)))
