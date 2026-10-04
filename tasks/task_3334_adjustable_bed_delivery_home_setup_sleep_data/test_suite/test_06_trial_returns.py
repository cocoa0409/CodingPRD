"""Trial window boundary and restocking-refund pinned rounding order."""
from test_helpers import (
    ApiErrorId,
    create_delivery_visit,
    create_delivery_window,
    create_full_catalog,
    create_product_models,
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
from test_helpers.fixtures import ADMIN, SALES


def _deliver_order(order_id, serial, window):
    """Schedule + verify a visit with one paired BASE device."""
    device = register_device(order_id, kind="BASE", serial_number=serial)
    pair_device(device["id"])
    visit = create_delivery_visit(order_id, window["id"])
    verify_visit(visit["id"])


def test_trial_return_night_99_allowed_night_100_rejected(api):
    """PRD §3.7: "The server computes `initiated_night_index` as the number of
    whole 86400-second days between `trial_verified_at` and the logical clock,
    rounded down. The trial is 100 nights: an index of 99 or less is
    permitted, while an index of 100 — that is, a clock at or past
    `trial_verified_at` plus exactly 100 days — is rejected with
    `ERR_TRIAL_WINDOW_EXPIRED`."

    Design: Difficulty/boundary_precision_check/trial_return_at_exactly_night_100_rejected_99_allowed
    """
    store, cust_a, fa_a = setup_customer_with_completed_assessment(
        email="a@x.com")
    from test_helpers import create_customer, create_completed_assessment
    from test_helpers import create_order
    cust_b = create_customer(store["id"], email="b@x.com", full_name="Bob B")
    fa_b = create_completed_assessment(cust_b["id"], store["id"])
    order_a = create_order(cust_a["id"], fa_a["id"], [{"sku": "MAT-1", "qty": 1}])
    validate_success(api.confirm_order(
        order_a["id"], {"payment_method": "PAY_IN_FULL"}, SALES))
    order_b = create_order(cust_b["id"], fa_b["id"], [{"sku": "MAT-1", "qty": 1}])
    validate_success(api.confirm_order(
        order_b["id"], {"payment_method": "PAY_IN_FULL"}, SALES))
    window = create_delivery_window(store["id"], capacity_slots=8,
                                    window_start="2026-09-01T08:00:00Z",
                                    window_end="2026-09-01T12:00:00Z")
    _deliver_order(order_a["id"], "SN-A1", window)
    _deliver_order(order_b["id"], "SN-B1", window)

    # 2026-09-01T00:00:00Z + 99 days = 2026-12-09T00:00:00Z; 23:59:59 is still
    # 99 whole days after verification.
    set_clock("2026-12-09T23:59:59Z")
    tr_a = initiate_return(order_a["id"], cust_a["id"], reason="night 99")
    assert tr_a["status"] == "INITIATED"
    assert tr_a["initiated_night_index"] == 99, (
        f"night index must be 99 one second before the boundary, got "
        f"{tr_a['initiated_night_index']}")

    set_clock("2026-12-10T00:00:00Z")
    resp = api.initiate_trial_return(
        order_b["id"],
        {"reason": "night 100", "refund_destination": "ORIGINAL_PAYMENT"},
        make_customer_headers(cust_b["id"]))
    validate_error(resp, ApiErrorId.ERR_TRIAL_WINDOW_EXPIRED)


def test_trial_return_night_100_rejection_leaves_no_record(api):
    """PRD §3.7: "an index of 100 — that is, a clock at or past
    `trial_verified_at` plus exactly 100 days — is rejected with
    `ERR_TRIAL_WINDOW_EXPIRED`."

    Design: Difficulty/boundary_precision_check/trial_return_at_exactly_night_100_rejected_99_allowed
    """
    ctx = setup_delivered_order(email="b2@x.com", serial_number="SN-B2")
    order, customer = ctx["order"], ctx["customer"]

    set_clock("2026-12-10T00:00:00Z")
    resp = api.initiate_trial_return(
        order["id"],
        {"reason": "too late", "refund_destination": "ORIGINAL_PAYMENT"},
        make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_TRIAL_WINDOW_EXPIRED)

    rows, meta = validate_paginated(api.list_trial_returns(
        ADMIN, params={"order_id": order["id"]}))
    assert meta["total_count"] == 0, (
        f"rejected initiation must persist no TrialReturn, got "
        f"{meta['total_count']}")
    o = validate_success(api.get_order(order["id"], ADMIN))
    assert o["order_status"] == "DELIVERED"


def test_restocking_refund_per_line_rounding_then_sum_then_fee(api):
    """PRD §3.7: "Each line's depreciation is the line's `line_total_cents`
    multiplied by its rate, rounded half-up per line before summing; the sum
    is `depreciation_cents`. The `restocking_fee_cents` is the greater of 9900
    and one tenth of the order's `total_paid_cents` rounded half-up. The
    `refund_cents` is the greater of 0 and `total_paid_cents` minus
    `depreciation_cents` minus `restocking_fee_cents`."

    Design: Difficulty/combinatorial_formula/restocking_refund_per_line_rounding_then_sum_then_fee
    """
    set_clock()
    from test_helpers import create_store, create_customer
    from test_helpers import create_completed_assessment, create_order
    store = create_store()
    create_full_catalog()
    create_product_models([
        {"sku": "BED-1", "name": "Sheets", "category": "BEDDING",
         "price_cents": 33333, "replacement_part_price_cents": 0,
         "warranty_months": 24},
    ])
    customer = create_customer(store["id"], email="r@x.com", full_name="Ree R")
    fa = create_completed_assessment(customer["id"], store["id"],
                                     sleep_position="SIDE",
                                     weight_band="UNDER_130",
                                     preferred_feel="PLUSH")
    order = create_order(customer["id"], fa["id"], [{"sku": "BED-1", "qty": 3}])
    assert order["subtotal_cents"] == 99999
    assert order["delivery_fee_cents"] == 9900
    assert order["total_due_cents"] == 109899
    validate_success(api.confirm_order(
        order["id"], {"payment_method": "PAY_IN_FULL"}, SALES))
    window = create_delivery_window(store["id"],
                                    window_start="2026-09-01T08:00:00Z",
                                    window_end="2026-09-01T12:00:00Z")
    visit = create_delivery_visit(order["id"], window["id"])
    device = register_device(order["id"], kind="BASE", serial_number="SN-R1")
    pair_device(device["id"])
    verify_visit(visit["id"])

    set_clock("2026-09-11T00:00:00Z")
    tr = initiate_return(order["id"], customer["id"], reason="too soft")
    tr = inspect_return(tr["id"], outcome="APPROVED", condition="DAMAGED")
    # One collapsed line: line_total 99999; DAMAGED other-category rate 0.10.
    assert tr["depreciation_cents"] == 10000, (
        f"round_half_up(99999 * 0.10) = 10000 per pinned per-line rounding, "
        f"got {tr['depreciation_cents']}")
    assert tr["restocking_fee_cents"] == 10990, (
        f"max(9900, round_half_up(0.10 * 109899)) = 10990, got "
        f"{tr['restocking_fee_cents']}")
    assert tr["refund_cents"] == 88909, (
        f"109899 - 10000 - 10990 = 88909, got {tr['refund_cents']}")
    assert tr["status"] == "REFUNDED"


def test_restocking_fee_floor_binds_on_small_order(api):
    """PRD §3.7: "The `restocking_fee_cents` is the greater of 9900 and one
    tenth of the order's `total_paid_cents` rounded half-up. The `refund_cents`
    is the greater of 0 and `total_paid_cents` minus `depreciation_cents`
    minus `restocking_fee_cents`."

    Design: Difficulty/combinatorial_formula/restocking_refund_per_line_rounding_then_sum_then_fee
    """
    set_clock()
    from test_helpers import create_store, create_customer
    from test_helpers import create_completed_assessment, create_order
    store = create_store()
    create_full_catalog()
    create_product_models([
        {"sku": "BED-1", "name": "Sheets", "category": "BEDDING",
         "price_cents": 33333, "replacement_part_price_cents": 0,
         "warranty_months": 24},
    ])
    customer = create_customer(store["id"], email="r2@x.com",
                               full_name="Ree R")
    fa = create_completed_assessment(customer["id"], store["id"])
    order = create_order(customer["id"], fa["id"], [{"sku": "BED-1", "qty": 1}])
    # subtotal 33333 < 200000 -> fee 9900 -> total_paid 43233.
    assert order["total_due_cents"] == 43233
    validate_success(api.confirm_order(
        order["id"], {"payment_method": "PAY_IN_FULL"}, SALES))
    window = create_delivery_window(store["id"],
                                    window_start="2026-09-01T08:00:00Z",
                                    window_end="2026-09-01T12:00:00Z")
    visit = create_delivery_visit(order["id"], window["id"])
    device = register_device(order["id"], kind="BASE", serial_number="SN-R2")
    pair_device(device["id"])
    verify_visit(visit["id"])

    tr = initiate_return(order["id"], customer["id"], reason="too small")
    tr = inspect_return(tr["id"], outcome="APPROVED", condition="DAMAGED")
    assert tr["depreciation_cents"] == 3333, (
        f"round_half_up(33333 * 0.10) = 3333, got {tr['depreciation_cents']}")
    assert tr["restocking_fee_cents"] == 9900, (
        f"max(9900, round_half_up(0.10 * 43233) = 4323) = 9900 floor, got "
        f"{tr['restocking_fee_cents']}")
    assert tr["refund_cents"] == 30000, (
        f"43233 - 3333 - 9900 = 30000, got {tr['refund_cents']}")
