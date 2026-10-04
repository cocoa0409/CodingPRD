"""Supersede chain, not-found envelope, required fields, device denormalization."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_completed_assessment,
    create_customer,
    create_full_catalog,
    create_order_payload,
    make_customer_headers,
    set_clock,
    setup_confirmed_order,
    setup_store_with_catalog,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ANON, SALES, TECH


def test_superseding_assessment_supersedes_predecessor(api):
    """PRD §3.2: "Completion also stamps `completed_at` with the logical clock
    and, when `supersedes_assessment_id` was supplied, transitions the
    referenced `COMPLETED` predecessor to `SUPERSEDED`."

    Design: Corner/entities/fit_assessment_supersede_self_reference_transitions_predecessor
    """
    store = setup_store_with_catalog()
    customer = create_customer(store["id"], email="s@x.com")
    fa_a = create_completed_assessment(customer["id"], store["id"])
    resp = api.create_fit_assessment(
        {"customer_id": customer["id"], "store_id": store["id"],
         "sleep_position": "STOMACH", "weight_band": "OVER_230",
         "partner_sleeper": False, "preferred_feel": "FIRM",
         "supersedes_assessment_id": fa_a["id"]},
        SALES)
    fa_b = validate_success(resp, expected_status=201)
    fa_b = validate_success(api.complete_fit_assessment(fa_b["id"], SALES))
    fa_a_after = validate_success(
        api.get_fit_assessment(fa_a["id"], SALES))
    assert fa_a_after["status"] == "SUPERSEDED", (
        f"predecessor must be SUPERSEDED, got {fa_a_after['status']}")
    assert fa_b["status"] == "COMPLETED"
    # STOMACH 65 + OVER_230 10 + FIRM 10 = 85
    assert fa_b["recommended_firmness"] == 85


def test_order_against_superseded_assessment_rejected(api):
    """PRD §3.3: "The referenced assessment must belong to the same customer
    as the order's `customer_id` and must currently be `COMPLETED` — a `DRAFT`
    or `SUPERSEDED` assessment, or one tied to a different customer, is
    rejected with `ERR_FIT_ASSESSMENT_MISMATCH`."

    Design: Corner/entities/fit_assessment_supersede_self_reference_transitions_predecessor
    """
    store = setup_store_with_catalog()
    customer = create_customer(store["id"], email="s2@x.com")
    fa_a = create_completed_assessment(customer["id"], store["id"])
    resp = api.create_fit_assessment(
        {"customer_id": customer["id"], "store_id": store["id"],
         "sleep_position": "SIDE", "weight_band": "UNDER_130",
         "partner_sleeper": False, "preferred_feel": "PLUSH",
         "supersedes_assessment_id": fa_a["id"]},
        SALES)
    fa_b = validate_success(resp, expected_status=201)
    validate_success(api.complete_fit_assessment(fa_b["id"], SALES))
    resp = api.create_order(
        create_order_payload(customer["id"], fa_a["id"],
                             [{"sku": "MAT-1", "qty": 1}]),
        make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_FIT_ASSESSMENT_MISMATCH)
    # Reverse reachability of the self-FK: exactly one successor lists A.
    rows, meta = validate_paginated(api.list_fit_assessments(
        SALES, params={"supersedes_assessment_id": fa_a["id"]}))
    assert len(rows) == 1 and rows[0]["id"] == fa_b["id"]


def test_get_unknown_order_returns_order_not_found(api, admin_headers):
    """PRD §5 error catalogue maps `ERR_ORDER_NOT_FOUND` to HTTP 404, and
    PRD §2.8: "an unknown identifier anywhere in the path short-circuits the
    request with the corresponding `ERR_*_NOT_FOUND` before any body
    validation runs."

    Design: Corner/entities/order_get_unknown_id_returns_order_not_found
    """
    set_clock()
    resp = api.get_order(
        "00000000-0000-4000-8000-000000000000", admin_headers)
    data = validate_error(resp, ApiErrorId.ERR_ORDER_NOT_FOUND)
    body = resp.json()
    assert body.get("response_type") == "error"
    assert data.get("error_id") == "ERR_ORDER_NOT_FOUND"
    assert data.get("message"), "error payload must carry a message"


def test_order_create_missing_line_items_returns_validation(api):
    """PRD §3.3: "The caller supplies `line_items` as an array of `{sku, qty}`
    elements; each `sku` must resolve to a catalog `ProductModel` or the
    request fails with `ERR_PRODUCT_MODEL_NOT_FOUND`." — line_items is a
    required input for order creation; its omission is a schema failure
    (PRD §2.7: generic schema/type/enum validation as `ERR_VALIDATION`).

    Design: Corner/entities/order_create_missing_line_items_returns_validation
    """
    store = setup_store_with_catalog()
    customer = create_customer(store["id"], email="m@x.com")
    fa = create_completed_assessment(customer["id"], store["id"])
    resp = api.create_order(
        {"customer_id": customer["id"], "fit_assessment_id": fa["id"]},
        make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_VALIDATION)
    rows, meta = validate_paginated(api.list_orders(
        SALES, params={"customer_id": customer["id"]}))
    assert rows == [], f"no order may be created, got {len(rows)} rows"


def test_device_customer_id_denormalized_from_order(api):
    """PRD §3.6: "Once hardware is installed, a `DeliveryTechnician` registers
    each `Device` under an `order_id`, supplying a `kind` of `BASE`, `PUMP`,
    `CHAMBER`, or `SENSOR`, a `serial_number` unique per `kind`, and the
    `firmware_version` flashed at install. Registration denormalizes
    `customer_id` from the order."

    Design: Corner/entities/device_customer_id_denormalized_from_order
    """
    store, customer, fa, order = setup_confirmed_order(email="d@x.com")
    resp = api.create_device(
        {"order_id": order["id"], "kind": "PUMP", "serial_number": "SN-P9",
         "firmware_version": "2.1"}, TECH)
    device = validate_success(resp, expected_status=201)
    assert device["customer_id"] == customer["id"], (
        f"customer_id must be denormalized from the order, got "
        f"{device['customer_id']}")
    assert device["pairing_status"] == "UNPAIRED"
    assert device["connectivity"] == "OFFLINE"
    assert device["final_nights_count"] == 0
    rows, meta = validate_paginated(api.list_devices(
        TECH, params={"customer_id": customer["id"]}))
    assert len(rows) == 1 and rows[0]["id"] == device["id"]
