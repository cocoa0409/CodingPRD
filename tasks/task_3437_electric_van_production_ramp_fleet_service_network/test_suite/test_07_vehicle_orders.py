"""Vehicle orders: listing filters and pagination, input validation, the
franchise-law review gate, ownership checks, promise dates, and the order
state machine's auto-fulfillment."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    confirm_order,
    create_confirmed_order,
    create_fleet_customer,
    create_order,
    create_submitted_order,
    create_supplier,
    create_vehicle_order_payload,
    hold_order,
    make_fleet_manager_headers,
    read_order,
    set_logical_clock,
    setup_base_fleet,
    setup_customer_with_depot,
    setup_fulfilled_order,
    submit_order,
    transition_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

_COMPLIANCE = TEST_USERS["compliance_officer_headers"]


def test_vehicle_orders_list_filters_by_fk_and_paginates(api):
    """PRD section 3.5: "Orders can be read individually or listed filtered by
    `fleet_customer_id`, `depot_id`, or `battery_supplier_id`."; PRD section
    2.3: "`limit` defaults to 10, with a minimum of 1 and a maximum of 100;
    `offset` defaults to 0. List responses are always sorted by `created_at`
    ascending. The `meta` object of a list response carries `limit`, `offset`,
    `total_count`, and `has_more`, so a client can page deterministically
    through any collection."

    Design: Corner/entities/vehicle_orders_list_filters_by_fk_and_paginates
    """
    customer, depot = setup_customer_with_depot()
    supplier = create_supplier()
    create_order(customer, depot, supplier)
    create_order(
        customer, depot, supplier,
        quantity=1, battery_pack_kwh=52, telematics_tier="ADVANCED",
        delivery_method="CUSTOMER_PICKUP",
    )
    page1, meta1 = validate_paginated(
        api.list_vehicle_orders(
            _COMPLIANCE, params={"fleet_customer_id": customer["id"], "limit": 1, "offset": 0}
        )
    )
    assert len(page1) == 1
    assert meta1["total_count"] == 2 and meta1["has_more"] is True
    assert meta1["limit"] == 1 and meta1["offset"] == 0
    page2, meta2 = validate_paginated(
        api.list_vehicle_orders(
            _COMPLIANCE, params={"fleet_customer_id": customer["id"], "limit": 1, "offset": 1}
        )
    )
    assert len(page2) == 1 and meta2["has_more"] is False
    by_depot, meta_d = validate_paginated(
        api.list_vehicle_orders(_COMPLIANCE, params={"depot_id": depot["id"]})
    )
    assert len(by_depot) == 2 and meta_d["total_count"] == 2
    by_supplier, meta_s = validate_paginated(
        api.list_vehicle_orders(_COMPLIANCE, params={"battery_supplier_id": supplier["id"]})
    )
    assert len(by_supplier) == 2 and meta_s["total_count"] == 2
    all_rows, meta_all = validate_paginated(api.list_vehicle_orders(_COMPLIANCE))
    assert len(all_rows) == 2
    assert meta_all["limit"] == 10 and meta_all["offset"] == 0, "default pagination window"


def test_vehicle_order_invalid_pack_enum_rejected(api):
    """PRD section 3.5: an order names "a uniform `battery_pack_kwh` of `52`
    or `77` for every van" — a value outside that declared set is a
    400 ERR_VALIDATION.

    Design: Corner/entities/vehicle_order_invalid_pack_enum_rejected
    """
    customer, depot = setup_customer_with_depot()
    supplier = create_supplier()
    fm = make_fleet_manager_headers(customer["id"])
    payload = create_vehicle_order_payload(
        customer["id"], depot["id"], supplier["id"], battery_pack_kwh=99
    )
    resp = api.create_vehicle_order(payload, fm)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)
    rows, meta = validate_paginated(
        api.list_vehicle_orders(_COMPLIANCE, params={"fleet_customer_id": customer["id"]})
    )
    assert rows == [] and meta["total_count"] == 0


def test_order_auto_fulfills_when_quantity_registered(api):
    """PRD section 3.5: "The first VIN registered against a `CONFIRMED` order
    moves it `CONFIRMED → IN_PRODUCTION`; when `registered_count` reaches
    `quantity` the order moves `IN_PRODUCTION → FULFILLED` automatically."

    Design: Corner/state_machines/order_auto_fulfills_when_quantity_registered
    """
    fleet = setup_fulfilled_order(quantity=1)
    order = fleet["order"]
    assert order["status"] == "FULFILLED", (
        "the single-VIN order walked CONFIRMED -> IN_PRODUCTION -> FULFILLED in one registration"
    )
    assert order["registered_count"] == 1


def test_order_cancel_from_confirmed_rejected(api):
    """PRD section 3.5: "The owning fleet manager may cancel from `DRAFT`,
    `SUBMITTED`, or `FRANCHISE_HOLD`; attempting cancellation from `FULFILLED`
    or `CANCELLED` is refused with `ERR_ALREADY_TERMINAL`, and any other
    out-of-state transition attempt draws `ERR_INVALID_STATE`."

    Design: Corner/state_machines/order_cancel_from_confirmed_rejected
    """
    fleet = setup_base_fleet(quantity=2, register_count=0)
    order = fleet["order"]
    resp = api.transition_vehicle_order(
        order["id"], transition_payload("CANCELLED"),
        make_fleet_manager_headers(fleet["customer"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert read_order(order["id"])["status"] == "CONFIRMED"


def test_franchise_hold_then_exemption_approval_succeeds(api):
    """PRD section 3.5: "a hold is not terminal, and an order in
    `FRANCHISE_HOLD` can still be approved to `CONFIRMED` later under exactly
    the same review rule" and "when the delivery depot's `state_code` is one
    of the franchise-blocked states `TX`, `MI`, or `WV` and the order's
    `delivery_method` is `DIRECT_DELIVERY`, approval is refused with
    `ERR_FRANCHISE_EXEMPTION_REQUIRED` unless the request carries a non-empty
    `exemption_document_ref`, which is then stored on the order."

    Design: Corner/validations/franchise_hold_then_exemption_approval_succeeds
    """
    customer, depot = setup_customer_with_depot(depot_state="TX")
    supplier = create_supplier()
    order = create_submitted_order(customer, depot, supplier)
    held = hold_order(order)
    assert held["status"] == "FRANCHISE_HOLD"
    confirmed = confirm_order(order, exemption_document_ref="TX-EXEMPT-2026-881")
    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["exemption_document_ref"] == "TX-EXEMPT-2026-881"
    assert confirmed["promised_delivery_date"] == "2026-10-06", (
        "the promise date is computed at confirmation from the logical clock"
    )


def test_fleet_manager_cannot_touch_other_customers_order(api):
    """PRD section 2.1: "A fleet manager whose `X-User-ID` does not equal the
    owning customer's id is rejected with `ERR_OWNERSHIP_MISMATCH` (HTTP 403)
    on depot creation, charging-project creation, vehicle-order creation and
    the order's submission or cancellation, service-visit creation and
    cancellation, and warranty-claim creation."

    Design: Corner/validations/fleet_manager_cannot_touch_other_customers_order
    """
    customer_a, depot_a = setup_customer_with_depot()
    customer_b = create_fleet_customer(
        company_name="Beta Freight", contact_email="ops@beta.test", account_tier="PRIORITY"
    )
    supplier = create_supplier()
    order = create_order(customer_a, depot_a, supplier)
    resp = api.transition_vehicle_order(
        order["id"], transition_payload("SUBMITTED"),
        make_fleet_manager_headers(customer_b["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH)
    assert read_order(order["id"])["status"] == "DRAFT"


def test_delivery_promise_dates_from_confirm_date(api):
    """PRD section 3.5: "On entry to `CONFIRMED`, `promised_delivery_date` is
    computed from the logical clock as the confirm date plus 28 base days,
    plus 7 additional days for each started block of ten vans — the order's
    `quantity` divided by ten and rounded up to a whole number. An order of 2
    vans confirmed on 2026-09-01 is promised 35 days later, on 2026-10-06";
    and "A new order's `supply_risk_flag` is false, `registered_count` and
    `hold_count` are 0, and `promised_delivery_date` and
    `exemption_document_ref` are null."

    Design: Corner/calculations/delivery_promise_dates_from_confirm_date
    """
    customer, depot = setup_customer_with_depot()
    supplier = create_supplier()
    order_a = create_submitted_order(customer, depot, supplier)
    assert order_a["promised_delivery_date"] is None, "no promise while not yet CONFIRMED"
    order_b = create_submitted_order(
        customer, depot, supplier,
        quantity=25, battery_pack_kwh=52, telematics_tier="ADVANCED",
        delivery_method="CUSTOMER_PICKUP",
    )
    confirmed_a = confirm_order(order_a)
    assert confirmed_a["promised_delivery_date"] == "2026-10-06", (
        "28 + 7 x ceil(2/10) = 35 days after 2026-09-01"
    )
    confirmed_b = confirm_order(order_b)
    assert confirmed_b["promised_delivery_date"] == "2026-10-20", (
        "28 + 7 x ceil(25/10) = 49 days after 2026-09-01"
    )


def test_confirm_review_on_draft_order_surfaces_state_error(api):
    """PRD section 2.8: "Every request is checked against the following
    ordered rule stack, and the first failing check wins — a request that
    would fail two checks always surfaces the earlier one." — rule 6 (state
    preconditions, `ERR_INVALID_STATE`) precedes rule 8 (franchise law,
    `ERR_FRANCHISE_EXEMPTION_REQUIRED`).

    Design: Difficulty/priority_pair_validation_conflict/state_beats_franchise_safety_on_order_review
    """
    customer, depot = setup_customer_with_depot(depot_state="TX")
    supplier = create_supplier()
    order = create_order(customer, depot, supplier)  # left in DRAFT
    resp = api.transition_vehicle_order(order["id"], transition_payload("CONFIRMED"), _COMPLIANCE)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert read_order(order["id"])["status"] == "DRAFT", "no partial transition"


def test_franchise_error_surfaces_once_order_is_submitted(api):
    """PRD section 3.5: "when the delivery depot's `state_code` is one of the
    franchise-blocked states `TX`, `MI`, or `WV` and the order's
    `delivery_method` is `DIRECT_DELIVERY`, approval is refused with
    `ERR_FRANCHISE_EXEMPTION_REQUIRED` unless the request carries a non-empty
    `exemption_document_ref`".

    Design: Difficulty/priority_pair_validation_conflict/state_beats_franchise_safety_on_order_review
    """
    customer, depot = setup_customer_with_depot(depot_state="TX")
    supplier = create_supplier()
    order = create_submitted_order(customer, depot, supplier)
    resp = api.transition_vehicle_order(order["id"], transition_payload("CONFIRMED"), _COMPLIANCE)
    validate_error(resp, ApiErrorId.ERR_FRANCHISE_EXEMPTION_REQUIRED)
    assert read_order(order["id"])["status"] == "SUBMITTED", (
        "the rejected approval leaves the order untouched"
    )
