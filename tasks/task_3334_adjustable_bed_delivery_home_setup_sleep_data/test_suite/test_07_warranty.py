"""Warranty claims: proration variants, deny/appeal cycle, order-state gating,
referential and temporal rejection, and review RBAC."""
from test_helpers import (
    ApiErrorId,
    create_customer,
    create_delivery_visit,
    create_delivery_window,
    create_full_catalog,
    create_product_models,
    file_warranty_claim,
    ingest_night,
    initiate_return,
    inspect_return,
    make_customer_headers,
    pair_device,
    register_device,
    set_clock,
    setup_customer_with_completed_assessment,
    setup_delivered_order,
    validate_error,
    validate_paginated,
    validate_success,
    verify_visit,
)
from test_helpers.fixtures import ADMIN, SALES, SERVICE

ELEC_MODEL = {"sku": "ELEC-1", "name": "Remote One", "category": "ELECTRONICS",
              "price_cents": 12000, "replacement_part_price_cents": 12000,
              "warranty_months": 24}


def _deliver_with_catalog(api, store, customer, fa, line_items, serial,
                          window_start="2026-09-01T08:00:00Z",
                          window_end="2026-09-01T12:00:00Z"):
    from test_helpers import create_order
    order = create_order(customer["id"], fa["id"], line_items)
    validate_success(api.confirm_order(
        order["id"], {"payment_method": "PAY_IN_FULL"}, SALES))
    window = create_delivery_window(store["id"], window_start=window_start,
                                    window_end=window_end)
    visit = create_delivery_visit(order["id"], window["id"])
    device = register_device(order["id"], kind="BASE", serial_number=serial)
    pair_device(device["id"])
    verify_visit(visit["id"])
    return order, device


def test_warranty_credit_time_based_vs_nights_used_diverge(api):
    """PRD §3.8: "Under `TIME_BASED`, the remaining fraction is 1 minus
    `months_in_service` divided by `warranty_months`, floored at 0. Under
    `NIGHTS_USED`, the expected lifetime is `warranty_months` multiplied by 30
    nights, and the remaining fraction is 1 minus `final_nights_used` divided
    by that expectation, floored at 0, ignoring calendar time entirely."

    Design: Difficulty/dual_variant_calc/warranty_credit_time_based_vs_nights_used_diverge
    """
    set_clock()
    from test_helpers import create_store
    store = create_store()
    create_full_catalog()
    create_product_models([ELEC_MODEL])
    from test_helpers import create_completed_assessment
    customer = create_customer(store["id"], email="w@x.com",
                               full_name="Walt W")
    fa = create_completed_assessment(customer["id"], store["id"])
    order, device = _deliver_with_catalog(api,
        store, customer, fa,
        [{"sku": "MAT-1", "qty": 1}, {"sku": "ELEC-1", "qty": 1}], "SN-W1")
    ingest_night(device["id"], "2026-09-01", minutes_asleep=400,
                 restlessness_events=5, avg_heart_rate=62)
    ingest_night(device["id"], "2026-09-02", minutes_asleep=410,
                 restlessness_events=6, avg_heart_rate=63)
    ingest_night(device["id"], "2026-09-03", minutes_asleep=420,
                 restlessness_events=7, avg_heart_rate=64)
    # 361 whole days after 2026-09-01 -> months_in_service = floor(361/30) = 12.
    set_clock("2027-08-27T00:00:00Z")

    claim_t = file_warranty_claim(order["id"], device["id"], customer["id"],
                                  component_category="ELECTRONICS",
                                  proration_variant="TIME_BASED",
                                  description="remote dead")
    assert claim_t["months_in_service"] == 12
    claim_t = validate_success(api.review_warranty_claim(
        claim_t["id"], {"decision": "APPROVE"}, SERVICE))
    assert claim_t["status"] == "APPROVED"
    assert claim_t["credit_cents"] == 6000, (
        f"TIME_BASED: round(12000 * (1 - 12/24)) = 6000, got "
        f"{claim_t['credit_cents']}")
    assert claim_t["applied_to"] == "STORE_CREDIT"

    claim_n = file_warranty_claim(order["id"], device["id"], customer["id"],
                                  component_category="ELECTRONICS",
                                  proration_variant="NIGHTS_USED",
                                  description="remote dead again")
    assert claim_n["final_nights_used"] == 3, (
        f"3 nights finalized by the clock sweep, got "
        f"{claim_n['final_nights_used']}")
    claim_n = validate_success(api.review_warranty_claim(
        claim_n["id"], {"decision": "APPROVE"}, SERVICE))
    assert claim_n["credit_cents"] == 11950, (
        f"NIGHTS_USED: round(12000 * (1 - 3/720)) = 11950, got "
        f"{claim_n['credit_cents']}")
    assert claim_n["credit_cents"] != claim_t["credit_cents"]
    cust = validate_success(api.get_customer(customer["id"], ADMIN))
    assert cust["store_credit_cents"] == 17950, (
        f"both credits land on store credit: 6000 + 11950 = 17950, got "
        f"{cust['store_credit_cents']}")


def test_warranty_months_in_service_snapshot_at_filing(api):
    """PRD §3.8: "At filing, the server snapshots `months_in_service` as the
    whole days since the order's `trial_verified_at` divided by 30, rounded
    down, and `final_nights_used` as the device's current
    `final_nights_count`."

    Design: Difficulty/dual_variant_calc/warranty_credit_time_based_vs_nights_used_diverge
    """
    set_clock()
    from test_helpers import create_store
    store = create_store()
    create_full_catalog()
    create_product_models([ELEC_MODEL])
    from test_helpers import create_completed_assessment
    customer = create_customer(store["id"], email="w2@x.com",
                               full_name="Walt W")
    fa = create_completed_assessment(customer["id"], store["id"])
    order, device = _deliver_with_catalog(api,
        store, customer, fa, [{"sku": "ELEC-1", "qty": 1}], "SN-W2")
    ingest_night(device["id"], "2026-09-01", minutes_asleep=400,
                 restlessness_events=5, avg_heart_rate=62)
    # 730 whole days after 2026-09-01 -> floor(730/30) = 24 -- expired for
    # ELECTRONICS, so instead file at day 719: floor(719/30) = 23 < 24.
    set_clock("2028-08-20T00:00:00Z")  # 719 days later
    claim = file_warranty_claim(order["id"], device["id"], customer["id"],
                                component_category="ELECTRONICS",
                                proration_variant="TIME_BASED",
                                description="snapshot check")
    assert claim["months_in_service"] == 23, (
        f"floor(719/30) = 23, got {claim['months_in_service']}")
    assert claim["final_nights_used"] == 1, (
        f"the one ingested night is FINAL after the sweep, got "
        f"{claim['final_nights_used']}")
    assert claim["status"] == "FILED"
    assert claim.get("credit_cents") is None
    assert claim.get("applied_to") is None


def test_warranty_claim_denied_appealed_approved_cycle(api):
    """PRD §3.8: "A `decision` of `DENY` moves the claim from `FILED` — or
    later from `APPEALED` — to `DENIED`, with an optional `denial_reason`
    recorded." and "Approval is terminal; a `DENIED` claim can be appealed by
    the `Customer`, moving to `APPEALED`, and the `DENIED → APPEALED → DENIED`
    cycle may repeat."

    Design: Difficulty/non_linear_state_machine/warranty_claim_denied_appealed_approved_cycle
    """
    ctx = setup_delivered_order(
        email="c@x.com", serial_number="SN-C1",
        line_items=[{"sku": "CHAM-1", "qty": 1}])
    order, customer, device = ctx["order"], ctx["customer"], ctx["device"]
    claim = file_warranty_claim(order["id"], device["id"], customer["id"],
                                component_category="CHAMBER",
                                proration_variant="TIME_BASED",
                                description="slow leak")

    denied = validate_success(api.review_warranty_claim(
        claim["id"], {"decision": "DENY", "denial_reason": "wear"}, SERVICE))
    assert denied["status"] == "DENIED"
    appealed = validate_success(api.appeal_warranty_claim(
        claim["id"], make_customer_headers(customer["id"])))
    assert appealed["status"] == "APPEALED"
    denied2 = validate_success(api.review_warranty_claim(
        claim["id"], {"decision": "DENY", "denial_reason": "still wear"},
        SERVICE))
    assert denied2["status"] == "DENIED", "the DENIED -> APPEALED -> DENIED cycle repeats"
    appealed2 = validate_success(api.appeal_warranty_claim(
        claim["id"], make_customer_headers(customer["id"])))
    assert appealed2["status"] == "APPEALED"
    approved = validate_success(api.review_warranty_claim(
        claim["id"], {"decision": "APPROVE"}, SERVICE))
    assert approved["status"] == "APPROVED"
    # months_in_service 0 of 60 -> remaining fraction 1.0 -> full base 40000.
    assert approved["credit_cents"] == 40000, (
        f"credit computed only on the final APPROVE: round(40000 * 1.0) = "
        f"40000, got {approved['credit_cents']}")
    assert approved["applied_to"] == "STORE_CREDIT"
    cust = validate_success(api.get_customer(customer["id"], ADMIN))
    assert cust["store_credit_cents"] == 40000


def test_warranty_claim_approval_is_terminal(api):
    """PRD §3.8: "Approval is terminal; a `DENIED` claim can be appealed by
    the `Customer`, moving to `APPEALED`, and the `DENIED → APPEALED → DENIED`
    cycle may repeat."

    Design: Difficulty/non_linear_state_machine/warranty_claim_denied_appealed_approved_cycle
    """
    ctx = setup_delivered_order(
        email="c2@x.com", serial_number="SN-C2",
        line_items=[{"sku": "CHAM-1", "qty": 1}])
    order, customer, device = ctx["order"], ctx["customer"], ctx["device"]
    claim = file_warranty_claim(order["id"], device["id"], customer["id"],
                                component_category="CHAMBER",
                                proration_variant="TIME_BASED",
                                description="slow leak")
    approved = validate_success(api.review_warranty_claim(
        claim["id"], {"decision": "APPROVE"}, SERVICE))
    assert approved["status"] == "APPROVED"
    resp = api.appeal_warranty_claim(
        claim["id"], make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    after = validate_success(api.get_warranty_claim(claim["id"], SERVICE))
    assert after["status"] == "APPROVED", "approval is terminal"
    assert after["credit_cents"] == 40000


def test_warranty_review_rejected_once_order_returned(api):
    """PRD §3.8: "A `decision` of `APPROVE` requires the parent order to be
    outside `CANCELLED` and `RETURNED`, else the review fails with
    `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/warranty_review_gated_by_order_not_returned
    """
    ctx = setup_delivered_order(email="a@x.com", serial_number="SN-A1")
    order, customer, device = ctx["order"], ctx["customer"], ctx["device"]
    claim = file_warranty_claim(order["id"], device["id"], customer["id"],
                                component_category="STRUCTURAL",
                                proration_variant="TIME_BASED",
                                description="squeak")
    tr = initiate_return(order["id"], customer["id"], reason="changed mind")
    inspect_return(tr["id"], outcome="APPROVED", condition="GOOD")
    o = validate_success(api.get_order(order["id"], ADMIN))
    assert o["order_status"] == "RETURNED"

    resp = api.review_warranty_claim(claim["id"], {"decision": "APPROVE"},
                                     SERVICE)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    after = validate_success(api.get_warranty_claim(claim["id"], SERVICE))
    assert after["status"] == "FILED"
    assert after.get("credit_cents") is None


def test_warranty_review_approves_while_order_delivered(api):
    """PRD §3.8: "A `decision` of `APPROVE` requires the parent order to be
    outside `CANCELLED` and `RETURNED`, else the review fails with
    `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/warranty_review_gated_by_order_not_returned
    """
    ctx = setup_delivered_order(email="a2@x.com", serial_number="SN-A2")
    order, customer, device = ctx["order"], ctx["customer"], ctx["device"]
    claim = file_warranty_claim(order["id"], device["id"], customer["id"],
                                component_category="STRUCTURAL",
                                proration_variant="TIME_BASED",
                                description="squeak")
    o = validate_success(api.get_order(order["id"], ADMIN))
    assert o["order_status"] == "DELIVERED"
    approved = validate_success(api.review_warranty_claim(
        claim["id"], {"decision": "APPROVE"}, SERVICE))
    assert approved["status"] == "APPROVED"
    assert approved["credit_cents"] is not None


def test_warranty_claim_device_not_on_order_rejected(api):
    """PRD §3.8: "The `device_id` must be registered under the named order or
    the request is rejected with `ERR_DEVICE_NOT_ON_ORDER`."

    Design: Corner/validations/warranty_claim_device_not_on_order_rejected
    """
    set_clock()
    from test_helpers import create_store, create_completed_assessment
    from test_helpers import create_order
    store = create_store()
    create_full_catalog()
    cust_a = create_customer(store["id"], email="a@x.com", full_name="Ann A")
    cust_b = create_customer(store["id"], email="b@x.com", full_name="Bob B")
    fa_a = create_completed_assessment(cust_a["id"], store["id"])
    fa_b = create_completed_assessment(cust_b["id"], store["id"])
    order_a = create_order(cust_a["id"], fa_a["id"], [{"sku": "MAT-1", "qty": 1}])
    validate_success(api.confirm_order(
        order_a["id"], {"payment_method": "PAY_IN_FULL"}, SALES))
    order_b = create_order(cust_b["id"], fa_b["id"], [{"sku": "MAT-1", "qty": 1}])
    validate_success(api.confirm_order(
        order_b["id"], {"payment_method": "PAY_IN_FULL"}, SALES))
    dev_b = register_device(order_b["id"], kind="PUMP", serial_number="SN-BP")

    resp = api.create_warranty_claim(
        {"order_id": order_a["id"], "device_id": dev_b["id"],
         "component_category": "PUMP", "proration_variant": "TIME_BASED",
         "description": "wrong order"},
        make_customer_headers(cust_a["id"]))
    validate_error(resp, ApiErrorId.ERR_DEVICE_NOT_ON_ORDER)
    rows, meta = validate_paginated(api.list_warranty_claims(
        ADMIN, params={"order_id": order_a["id"]}))
    assert meta["total_count"] == 0


def test_warranty_claim_filed_beyond_warranty_months_rejected(api):
    """PRD §3.8: "The claim is only inside its warranty window when
    `months_in_service` is strictly less than the `warranty_months` for the
    claimed `component_category` — `STRUCTURAL` allows 120 months, `CHAMBER`
    60, `PUMP` 36, and `ELECTRONICS` 24; a `months_in_service` equal to the
    limit means the warranty has already expired and the filing is rejected
    with `ERR_WARRANTY_EXPIRED`."

    Design: Corner/validations/warranty_claim_filed_beyond_warranty_months_rejected
    """
    set_clock()
    from test_helpers import create_store, create_completed_assessment
    store = create_store()
    create_full_catalog()
    create_product_models([ELEC_MODEL])
    customer = create_customer(store["id"], email="x@x.com", full_name="Xu X")
    fa = create_completed_assessment(customer["id"], store["id"])
    order, device = _deliver_with_catalog(api,
        store, customer, fa, [{"sku": "ELEC-1", "qty": 1}], "SN-X1")
    # 726 days after 2026-09-01: floor(726/30) = 24 >= warranty_months 24.
    set_clock("2028-08-26T00:00:00Z")
    resp = api.create_warranty_claim(
        {"order_id": order["id"], "device_id": device["id"],
         "component_category": "ELECTRONICS", "proration_variant": "TIME_BASED",
         "description": "too late"},
        make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_WARRANTY_EXPIRED)


def test_customer_cannot_review_own_warranty_claim(api):
    """PRD §2.1: "A request whose role is not authorized for the endpoint it
    targets is rejected with `ERR_FORBIDDEN` (HTTP 403)." and PRD §4: the
    review endpoint is authorized for `ServiceAgent` only.

    Design: Corner/rbac/customer_cannot_review_own_warranty_claim
    """
    ctx = setup_delivered_order(email="c3@x.com", serial_number="SN-C3")
    order, customer, device = ctx["order"], ctx["customer"], ctx["device"]
    claim = file_warranty_claim(order["id"], device["id"], customer["id"],
                                component_category="STRUCTURAL",
                                proration_variant="TIME_BASED",
                                description="squeak")
    resp = api.review_warranty_claim(
        claim["id"], {"decision": "APPROVE"},
        make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    after = validate_success(api.get_warranty_claim(claim["id"], SERVICE))
    assert after["status"] == "FILED"
