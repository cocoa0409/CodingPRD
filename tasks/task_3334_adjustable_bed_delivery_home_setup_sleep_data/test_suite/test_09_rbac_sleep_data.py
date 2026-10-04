"""RBAC ownership and entitlement gating; sleep-night uniqueness scope."""
from test_helpers import (
    ApiErrorId,
    create_completed_assessment,
    create_customer,
    create_order,
    create_store,
    ingest_night,
    make_customer_headers,
    register_device,
    set_clock,
    setup_customer_with_completed_assessment,
    setup_delivered_order,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ADMIN, FINANCE, GATEWAY, SALES


def test_customer_cannot_read_other_customers_order(api):
    """PRD §2.1: "When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of
    the acting `Customer`; ownership checks on any resource that references a
    `Customer` compare the resource's foreign-key field to `X-User-ID`. A
    `Customer` may act only on resources whose `customer_id` equals
    `X-User-ID`; a mismatch surfaces as `ERR_FORBIDDEN`."

    Design: Corner/rbac/customer_cannot_read_other_customers_order
    """
    store, cust_a, fa_a = setup_customer_with_completed_assessment(
        email="a@x.com")
    cust_b = create_customer(store["id"], email="b@x.com", full_name="Bob B")
    fa_b = create_completed_assessment(cust_b["id"], store["id"])
    order_b = create_order(cust_b["id"], fa_b["id"], [{"sku": "MAT-1", "qty": 1}])

    resp = api.get_order(order_b["id"], make_customer_headers(cust_a["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    own = validate_success(
        api.get_order(order_b["id"], make_customer_headers(cust_b["id"])))
    assert own["id"] == order_b["id"], "the owning customer reads it fine"


def test_finance_agent_cannot_create_fit_assessment(api):
    """PRD §2.1: "A request whose role is not authorized for the endpoint it
    targets is rejected with `ERR_FORBIDDEN` (HTTP 403)." and PRD §4: the
    fit-assessment create endpoint is authorized for `SalesAssociate` only.

    Design: Corner/rbac/finance_agent_cannot_create_fit_assessment
    """
    set_clock()
    store = create_store()
    customer = create_customer(store["id"], email="p@x.com", full_name="Pia P")
    resp = api.create_fit_assessment(
        {"customer_id": customer["id"], "store_id": store["id"],
         "sleep_position": "BACK", "weight_band": "BAND_130_230",
         "partner_sleeper": False, "preferred_feel": "MEDIUM"}, FINANCE)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    rows, meta = validate_paginated(api.list_fit_assessments(
        SALES, params={"customer_id": customer["id"]}))
    assert meta["total_count"] == 0


def test_free_tier_customer_denied_full_sleep_detail(api):
    """PRD §3.6: "Listing sleep nights accepts `device_id`, `customer_id`, and
    a `detail` parameter; asking for `detail` equal to `FULL` requires the
    owning customer's `subscription_tier` to be `PLUS` or `PREMIUM` with
    `subscription_status` `ACTIVE`, and a `FREE` tier or `CANCELLED`
    subscription is rejected with `ERR_ENTITLEMENT_REQUIRED`."

    Design: Corner/rbac/free_tier_customer_denied_full_sleep_detail
    """
    ctx = setup_delivered_order(email="e@x.com", serial_number="SN-E1")
    customer, device = ctx["customer"], ctx["device"]
    ingest_night(device["id"], "2026-09-01")

    resp = api.list_sleep_nights(
        make_customer_headers(customer["id"]),
        params={"customer_id": customer["id"], "detail": "FULL"})
    validate_error(resp, ApiErrorId.ERR_ENTITLEMENT_REQUIRED)

    upgraded = validate_success(api.update_subscription(
        customer["id"], {"subscription_tier": "PLUS"}, ADMIN))
    assert "SCORE_DETAIL" in upgraded["entitlements"], (
        f"PLUS entitlements include SCORE_DETAIL, got "
        f"{upgraded['entitlements']}")

    rows, meta = validate_paginated(api.list_sleep_nights(
        make_customer_headers(customer["id"]),
        params={"customer_id": customer["id"], "detail": "FULL"}))
    assert meta["total_count"] == 1, (
        f"PLUS tier unlocks FULL detail, got {meta['total_count']} rows")

    rows, meta = validate_paginated(api.list_sleep_nights(
        make_customer_headers(customer["id"]),
        params={"customer_id": customer["id"], "detail": "BASIC"}))
    assert meta["total_count"] == 1


def test_duplicate_night_rejected_per_device_date(api):
    """PRD §3.6: "A second record for the same `(device_id, night_date)` pair
    is rejected with `ERR_DUPLICATE_NIGHT`."

    Design: Corner/validations/duplicate_night_rejected_per_device_date
    """
    from test_helpers import setup_confirmed_order
    store, customer, fa, order = setup_confirmed_order(email="q@x.com")
    dev_base = register_device(order["id"], kind="BASE", serial_number="SN-Q1")
    dev_sensor = register_device(order["id"], kind="SENSOR",
                                 serial_number="SN-Q2")
    ingest_night(dev_base["id"], "2026-09-01", minutes_asleep=400,
                 restlessness_events=5, avg_heart_rate=62)

    resp = api.ingest_sleep_night(dev_base["id"], {
        "night_date": "2026-09-01", "minutes_asleep": 410,
        "restlessness_events": 6, "avg_heart_rate": 63}, GATEWAY)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_NIGHT)

    # Same night_date on a different device is a different pair: allowed.
    night = validate_success(api.ingest_sleep_night(dev_sensor["id"], {
        "night_date": "2026-09-01", "minutes_asleep": 410,
        "restlessness_events": 6, "avg_heart_rate": 63}, GATEWAY),
        expected_status=201)
    assert night["device_id"] == dev_sensor["id"]

    rows, meta = validate_paginated(api.list_sleep_nights(
        ADMIN, params={"device_id": dev_base["id"]}))
    assert meta["total_count"] == 1, (
        f"exactly one night row for the base device, got "
        f"{meta['total_count']}")
