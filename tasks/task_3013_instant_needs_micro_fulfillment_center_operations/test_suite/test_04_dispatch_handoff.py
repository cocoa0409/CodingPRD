"""Dispatch, handoff compliance, and delivery: the selector policy, the
parallel delivery/handoff dimensions, refusal flow, and loyalty accrual."""
from test_helpers import (
    ApiErrorId,
    append_order,
    assign_bag,
    create_bag_for_order,
    create_balance,
    create_customer,
    create_driver,
    create_picker,
    create_product,
    create_site,
    deliver_bag,
    get_success_data,
    handoff_scan_payload,
    list_stock_lots,
    make_customer_headers,
    make_driver_headers,
    make_picker_headers,
    open_batch,
    order_line,
    place_order,
    read_balance,
    read_customer,
    read_delivery_bag,
    read_order,
    read_pick_batch,
    seed_on_hand,
    set_clock,
    setup_assigned_bag,
    setup_sealed_order,
    validate_error,
    validate_success,
    wallet_adjust,
)


def _three_sealed_orders_with_bags():
    """Site (line cap 3) + stocked product + customer + Pat/Sam + one batch of
    three sealed orders; creates three bags. Returns dict of parts."""
    set_clock("2026-09-10T14:00:00Z")
    site = create_site(batch_max_lines=3)
    product = create_product(sku="SKU-CHIPS", price_cents=500)
    balance = create_balance(site["id"], product["id"])
    seed_on_hand(balance["id"], 50)
    customer = create_customer()
    pat = create_picker(site["id"], name="Pat Picker")
    sam = create_picker(site["id"], name="Sam Sealer")
    orders = [place_order(customer["id"], site["id"], [order_line(product["id"], 1)])
              for _ in range(3)]
    batch = open_batch(site["id"], pat["id"])
    for order in orders:
        append_order(batch["id"], order["id"], pat["id"])
    from test_helpers import seal_batch
    seal_batch(batch["id"], sam["id"])
    bags = [create_bag_for_order(order["id"]) for order in orders]
    return {"site": site, "product": product, "customer": customer, "bags": bags}


class TestDispatchSelector:
    def test_dispatch_selector_ranks_by_run_size_then_created_at(self, api):
        """PRD §3.7: "The selector's candidate set is the drivers of the bag's
        site whose status is AVAILABLE and whose current run — bags they hold
        in ASSIGNED or OUT_FOR_DELIVERY — carries strictly fewer orders than
        their max_run_orders. Candidates are ranked by current run size
        ascending, ties broken by the driver's created_at ascending — the
        earliest-rostered driver wins. An empty candidate set rejects the
        assignment with ERR_NO_DRIVER_AVAILABLE."

        Design: Corner/endpoints/dispatch_selector_ranks_by_run_size_then_created_at
        """
        parts = _three_sealed_orders_with_bags()
        site = parts["site"]
        d_old = create_driver(site["id"], name="D-OLD", max_run_orders=2)
        d_new = create_driver(site["id"], name="D-NEW", max_run_orders=2)
        bag1, bag2, bag3 = (b["id"] for b in parts["bags"])

        a1 = assign_bag(bag1)
        assert a1["driver_id"] == d_old["id"], "both at run 0; created_at tie-break"
        a2 = assign_bag(bag2)
        assert a2["driver_id"] == d_new["id"], "run 0 beats run 1"
        a3 = assign_bag(bag3)
        assert a3["driver_id"] == d_old["id"], "runs tie at 1; created_at tie-break again"

    def test_selector_rejects_when_no_driver_available(self, api):
        """PRD §3.7: "The selector's candidate set is the drivers of the bag's
        site whose status is AVAILABLE and whose current run — bags they hold
        in ASSIGNED or OUT_FOR_DELIVERY — carries strictly fewer orders than
        their max_run_orders. ... An empty candidate set rejects the assignment
        with ERR_NO_DRIVER_AVAILABLE."

        Design: Corner/endpoints/dispatch_selector_ranks_by_run_size_then_created_at
        """
        from test_helpers import SITE_OPS_HEADERS

        parts = _three_sealed_orders_with_bags()
        site = parts["site"]
        solo = create_driver(site["id"], name="Solo", max_run_orders=2)
        bag1, bag2, bag3 = (b["id"] for b in parts["bags"])
        assign_bag(bag1)
        assign_bag(bag2)
        # solo's run now carries 2 == max_run_orders: strictly-fewer fails.
        resp = api.assign_delivery_bag(bag3, {}, SITE_OPS_HEADERS)
        validate_error(resp, ApiErrorId.ERR_NO_DRIVER_AVAILABLE)


class TestParallelDimensions:
    def test_delivery_bag_parallel_delivery_and_handoff_dimensions(self, api):
        """PRD §3.7: "an order that contains_age_restricted may not depart
        unless the handoff has reached AGE_VERIFIED; departing otherwise is
        rejected with ERR_HANDOFF_NOT_VERIFIED."
        PRD §3.7: "Age-restricted handoff is a compliance gate with its own
        state machine living on the bag's handoff_status, which evolves
        independently of delivery_status."

        Design: Difficulty/non_linear_state_machine/delivery_bag_parallel_delivery_and_handoff_dimensions
        """
        (site, product, balance, customer, sealer, order, batch, driver, bag) = setup_assigned_bag(
            product_class="AGE_RESTRICTED", price_cents=99
        )
        early = api.depart_delivery_bag(bag["id"], make_driver_headers(driver["id"]))
        validate_error(early, ApiErrorId.ERR_HANDOFF_NOT_VERIFIED)

        scanned = validate_success(
            api.handoff_scan(
                bag["id"],
                handoff_scan_payload("1990-06-15", "1234"),
                make_driver_headers(driver["id"]),
            )
        )
        assert scanned["handoff_status"] == "AGE_VERIFIED"
        assert scanned["delivery_status"] == "ASSIGNED", "dimensions move independently"

        departed = validate_success(api.depart_delivery_bag(bag["id"], make_driver_headers(driver["id"])))
        assert departed["delivery_status"] == "OUT_FOR_DELIVERY"

    def test_handoff_scan_records_audit_last4(self, api):
        """PRD §3.7: "After assignment and before departure, the assigned
        driver scans the recipient's identification, supplying the
        scanned_birthdate and the scanned_id_last4 — the last four characters
        of the document, retained as the audit trail."

        Design: Difficulty/non_linear_state_machine/delivery_bag_parallel_delivery_and_handoff_dimensions
        """
        (_s, _p, _b, _c, _seal, _o, _batch, driver, bag) = setup_assigned_bag(
            product_class="AGE_RESTRICTED", price_cents=99
        )
        scanned = validate_success(
            api.handoff_scan(
                bag["id"],
                handoff_scan_payload("1990-06-15", "1234"),
                make_driver_headers(driver["id"]),
            )
        )
        assert scanned["scanned_id_last4"] == "1234", "audit trail retains the last four"
        assert scanned["handoff_status"] == "AGE_VERIFIED"

    def test_handoff_scan_on_bag_of_standard_order_rejected(self, api):
        """PRD §3.7: "The scan is permitted only when the order
        contains_age_restricted (scanning for an order with no restricted lines
        is rejected with ERR_HANDOFF_NOT_REQUIRED)"

        Design: Corner/state_machines/handoff_scan_on_bag_of_standard_order_rejected
        """
        (_s, _p, _b, _c, _seal, _o, _batch, driver, bag) = setup_assigned_bag()
        resp = api.handoff_scan(
            bag["id"],
            handoff_scan_payload("1990-06-15", "1234"),
            make_driver_headers(driver["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_HANDOFF_NOT_REQUIRED)
        assert read_delivery_bag(bag["id"])["handoff_status"] == "NONE"


class TestRefusalFlow:
    def test_handoff_failure_path_gated_by_handoff_status(self, api):
        """PRD §3.8: "After a handoff refusal, the assigned driver records the
        failed handoff, which requires handoff_status to be REFUSED (otherwise
        ERR_REFUSAL_REQUIRED) and transitions the order AWAITING_HANDOFF →
        HANDOFF_FAILED while the bag's delivery_status moves to FAILED in
        parallel."
        PRD §3.7: "otherwise it moves to REFUSED, and the order becomes
        eligible for the failed-handoff path of §3.8."

        Design: Difficulty/cross_entity_state_dependency/handoff_failure_path_gated_by_handoff_status
        """
        (site, product, balance, customer, sealer, order, batch, driver, bag) = setup_assigned_bag(
            product_class="AGE_RESTRICTED", price_cents=99
        )
        early = api.fail_handoff(bag["id"], make_driver_headers(driver["id"]))
        validate_error(early, ApiErrorId.ERR_REFUSAL_REQUIRED)

        scanned = validate_success(
            api.handoff_scan(
                bag["id"],
                handoff_scan_payload("2010-01-01", "9999"),
                make_driver_headers(driver["id"]),
            )
        )
        assert scanned["handoff_status"] == "REFUSED"

        failed = validate_success(api.fail_handoff(bag["id"], make_driver_headers(driver["id"])))
        assert failed["delivery_status"] == "FAILED"
        assert read_order(order["id"])["status"] == "HANDOFF_FAILED"

    def test_fail_handoff_without_refusal_leaves_dimensions_untouched(self, api):
        """PRD §3.8: "After a handoff refusal, the assigned driver records the
        failed handoff, which requires handoff_status to be REFUSED (otherwise
        ERR_REFUSAL_REQUIRED)"

        Design: Difficulty/cross_entity_state_dependency/handoff_failure_path_gated_by_handoff_status
        """
        (_s, _p, _b, _c, _seal, order, _batch, driver, bag) = setup_assigned_bag(
            product_class="AGE_RESTRICTED", price_cents=99
        )
        resp = api.fail_handoff(bag["id"], make_driver_headers(driver["id"]))
        validate_error(resp, ApiErrorId.ERR_REFUSAL_REQUIRED)
        bag_after = read_delivery_bag(bag["id"])
        assert bag_after["handoff_status"] == "NONE"
        assert bag_after["delivery_status"] == "ASSIGNED"
        assert read_order(order["id"])["status"] == "AWAITING_HANDOFF"


class TestDepartAndOwnership:
    def test_depart_without_assignment_returns_bag_not_assigned(self, api):
        """PRD §3.7: "The driver must be the bag's assignee, the bag must be
        ASSIGNED (otherwise ERR_BAG_NOT_ASSIGNED)"

        Design: Corner/errors/depart_without_assignment_returns_bag_not_assigned
        """
        (site, _p, _b, _c, _pk, _seal, order, _batch) = setup_sealed_order()
        driver = create_driver(site["id"], name="Dee Driver", max_run_orders=4)
        bag = create_bag_for_order(order["id"])  # created, never assigned
        resp = api.depart_delivery_bag(bag["id"], make_driver_headers(driver["id"]))
        validate_error(resp, ApiErrorId.ERR_BAG_NOT_ASSIGNED)
        bag_after = read_delivery_bag(bag["id"])
        assert bag_after["delivery_status"] == "UNASSIGNED"
        assert bag_after["driver_id"] is None

    def test_driver_cannot_act_on_another_drivers_bag(self, api, site_ops_headers):
        """PRD §2.9: "Drivers likewise may not act on bags assigned to another
        driver: handoff scans, departures, completions, and failure records on
        a bag whose driver_id differs from the acting driver's identity are
        rejected with ERR_UNAUTHORIZED."

        Design: Corner/rbac/driver_cannot_act_on_another_drivers_bag
        """
        (site, product, balance, customer, picker, sealer, order, batch) = setup_sealed_order()
        dee = create_driver(site["id"], name="Dee Driver", max_run_orders=4)
        dan = create_driver(site["id"], name="Dan Driver", max_run_orders=4)
        bag = assign_bag(create_bag_for_order(order["id"])["id"])
        assert bag["driver_id"] == dee["id"], "selector picks the earliest-rostered driver"
        resp = api.depart_delivery_bag(bag["id"], make_driver_headers(dan["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
        assert read_delivery_bag(bag["id"])["driver_id"] == dee["id"]


class TestDeliveryAndAccrual:
    def test_loyalty_record_then_absorb_variants_on_customer_wallet(self, api, site_ops_headers):
        """PRD §3.7: "Completion is the loyalty accrual point, and it follows a
        dual-variant rule: if the order absorbed wallet credit at placement —
        loyalty_credit_applied_cents greater than zero — the order earns
        exactly 0 cents, because the customer already saved at placement;
        otherwise the order earns the smaller of 500 cents and 3 percent of the
        sum of subtotal_cents and delivery_fee_cents, rounded half-up to
        integer cents."
        PRD §3.5: "The applied amount, recorded as
        loyalty_credit_applied_cents, is the smaller of the customer's
        wallet_credit_cents and the subtotal (the wallet floor is zero, so the
        wallet can absorb up to the full subtotal), and the wallet is debited
        by that amount immediately."

        Design: Difficulty/dual_variant_calc/loyalty_record_vs_absorb_variants_on_customer_wallet
        """
        (site, product, balance, customer, sealer, order1, batch, driver, bag1) = setup_assigned_bag(
            price_cents=500, qty=4, lot_expires_at=None
        )
        # First order: off-peak at the default 1.0 mile (within included) -> fee 199.
        resp1 = read_order(order1["id"])
        assert resp1["delivery_fee_cents"] == 199, resp1
        deliver_bag(bag1["id"], driver["id"])
        wallet_after_first = read_customer(customer["id"])["wallet_credit_cents"]
        # record variant: min(500, round_half_up(0.03 * (2000 + 199))) = 66
        assert wallet_after_first == 66

        wallet_adjust(customer["id"], 134, reason="promo top-up to 200")
        assert read_customer(customer["id"])["wallet_credit_cents"] == 200

        order2 = place_order(customer["id"], site["id"], [order_line(product["id"], 4)],
                             delivery_distance_miles=2.0)
        assert order2["loyalty_credit_applied_cents"] == 200, "absorb variant consumes the wallet"
        # order2 at 2.0 miles -> fee 199 + round_half_up(1.0 * 99) = 298
        assert order2["total_cents"] == 2000 + 0 + 298 - 200 == 2098

    def test_absorb_variant_earns_zero_on_delivery(self, api, site_ops_headers):
        """PRD §3.7: "if the order absorbed wallet credit at placement —
        loyalty_credit_applied_cents greater than zero — the order earns
        exactly 0 cents, because the customer already saved at placement"

        Design: Difficulty/dual_variant_calc/loyalty_record_vs_absorb_variants_on_customer_wallet
        """
        (site, product, balance, customer, picker, sealer, order1, batch) = setup_sealed_order(
            price_cents=500, qty=4
        )
        driver = create_driver(site["id"], name="Dee Driver", max_run_orders=4)
        deliver_bag(assign_bag(create_bag_for_order(order1["id"])["id"])["id"], driver["id"])
        assert read_customer(customer["id"])["wallet_credit_cents"] == 66
        wallet_adjust(customer["id"], 134, reason="promo top-up to 200")

        order2 = place_order(customer["id"], site["id"], [order_line(product["id"], 4)],
                             delivery_distance_miles=2.0)
        assert order2["loyalty_credit_applied_cents"] == 200
        assert read_customer(customer["id"])["wallet_credit_cents"] == 0

        pat2 = create_picker(site["id"], name="Pat Two")
        sam2 = create_picker(site["id"], name="Sam Two")
        batch2 = open_batch(site["id"], pat2["id"])
        append_order(batch2["id"], order2["id"], pat2["id"])
        from test_helpers import seal_batch
        seal_batch(batch2["id"], sam2["id"])
        bag2 = assign_bag(create_bag_for_order(order2["id"])["id"])
        deliver_bag(bag2["id"], driver["id"])
        assert read_customer(customer["id"])["wallet_credit_cents"] == 0, \
            "absorb variant earns exactly 0 on delivery"
