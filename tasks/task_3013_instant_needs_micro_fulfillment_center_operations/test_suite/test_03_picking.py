"""Picking workflow: batch capacity ceilings, segregation of duties, the seal
fan-out, auto-close, age pre-screening, and perishable FRESH-lot gating."""
from test_helpers import (
    ApiErrorId,
    append_order,
    create_balance,
    create_customer,
    create_order_payload,
    create_picker,
    create_product,
    create_site,
    get_success_data,
    make_customer_headers,
    make_picker_headers,
    open_batch,
    order_line,
    place_order,
    read_balance,
    read_order,
    read_pick_batch,
    receive_perishable_stock,
    seed_on_hand,
    set_clock,
    setup_assigned_bag,
    validate_error,
    validate_success,
)


def _site_with_stock(product_qty=50, **site_overrides):
    site = create_site(**site_overrides)
    product = create_product(sku="SKU-CHIPS", price_cents=500)
    balance = create_balance(site["id"], product["id"])
    seed_on_hand(balance["id"], product_qty)
    return site, product, balance


class TestBatchCapacity:
    def test_batch_line_cap_inclusive_boundary(self, api):
        """PRD §2.9: "The line ceiling is inclusive — a batch already holding
        exactly batch_max_lines orders is full"

        Design: Difficulty/boundary_precision_check/batch_line_cap_inclusive_boundary
        """
        set_clock("2026-09-10T14:00:00Z")
        site, product, balance = _site_with_stock()
        customer = create_customer()
        picker = create_picker(site["id"], name="Pat Picker")
        orders = [
            place_order(customer["id"], site["id"], [order_line(product["id"], 1)])
            for _ in range(3)
        ]
        batch = open_batch(site["id"], picker["id"])
        append_order(batch["id"], orders[0]["id"], picker["id"])
        batch = append_order(batch["id"], orders[1]["id"], picker["id"])
        assert len(batch["order_ids"]) == 2, "== cap is full but legal"

        third = api.append_order_to_batch(
            batch["id"], {"order_id": orders[2]["id"]}, make_picker_headers(picker["id"])
        )
        validate_error(third, ApiErrorId.ERR_BATCH_FULL)
        assert read_order(orders[2]["id"])["status"] == "PLACED"
        assert read_balance(balance["id"])["reserved"] == 2

    def test_batch_line_cap_first_append_at_cap_then_reject(self, api):
        """PRD §2.9: "batch_max_lines caps the number of distinct orders in one
        open batch" and "Both rejections surface as ERR_BATCH_FULL."

        Design: Difficulty/boundary_precision_check/batch_line_cap_inclusive_boundary
        """
        set_clock("2026-09-10T14:00:00Z")
        site, product, balance = _site_with_stock(batch_max_lines=1)
        customer = create_customer()
        picker = create_picker(site["id"], name="Pat Picker")
        o1 = place_order(customer["id"], site["id"], [order_line(product["id"], 1)])
        o2 = place_order(customer["id"], site["id"], [order_line(product["id"], 1)])
        batch = open_batch(site["id"], picker["id"])
        batch = append_order(batch["id"], o1["id"], picker["id"])
        assert len(batch["order_ids"]) == 1
        resp = api.append_order_to_batch(
            batch["id"], {"order_id": o2["id"]}, make_picker_headers(picker["id"])
        )
        validate_error(resp, ApiErrorId.ERR_BATCH_FULL)

    def test_batch_line_and_item_cap_combined_pressure(self, api):
        """PRD §2.9: "batch_max_items caps the summed line quantities across
        those orders. The line ceiling is inclusive — a batch already holding
        exactly batch_max_lines orders is full — while the item ceiling rejects
        on overflow, when the incoming order's quantities would push the batch
        past batch_max_items. Both rejections surface as ERR_BATCH_FULL."

        Design: Difficulty/resource_temporal_overlap/batch_line_and_item_cap_combined_pressure
        """
        set_clock("2026-09-10T14:00:00Z")
        site, product, balance = _site_with_stock(
            code="SITE-C", name="Caps MFC", batch_max_lines=2, batch_max_items=5
        )
        customer = create_customer()
        picker = create_picker(site["id"], name="Pat Picker")
        o1 = place_order(customer["id"], site["id"], [order_line(product["id"], 3)])
        o2 = place_order(customer["id"], site["id"], [order_line(product["id"], 2)])
        o3 = place_order(customer["id"], site["id"], [order_line(product["id"], 1)])
        batch = open_batch(site["id"], picker["id"])
        batch = append_order(batch["id"], o1["id"], picker["id"])
        batch = append_order(batch["id"], o2["id"], picker["id"])
        # item cap is an overflow guard, so total_items == 5 is legal
        assert batch["total_items"] == 5, batch
        resp = api.append_order_to_batch(
            batch["id"], {"order_id": o3["id"]}, make_picker_headers(picker["id"])
        )
        validate_error(resp, ApiErrorId.ERR_BATCH_FULL)
        assert read_order(o3["id"])["status"] == "PLACED"
        assert len(read_pick_batch(batch["id"])["order_ids"]) == 2

    def test_batch_item_cap_overflow_rejection(self, api):
        """PRD §2.9: "the item ceiling rejects on overflow, when the incoming
        order's quantities would push the batch past batch_max_items."

        Design: Difficulty/resource_temporal_overlap/batch_line_and_item_cap_combined_pressure
        """
        set_clock("2026-09-10T14:00:00Z")
        site, product, balance = _site_with_stock(
            code="SITE-C", batch_max_lines=3, batch_max_items=5
        )
        customer = create_customer()
        picker = create_picker(site["id"], name="Pat Picker")
        o1 = place_order(customer["id"], site["id"], [order_line(product["id"], 3)])
        o2 = place_order(customer["id"], site["id"], [order_line(product["id"], 3)])
        batch = open_batch(site["id"], picker["id"])
        append_order(batch["id"], o1["id"], picker["id"])
        # 3 + 3 = 6 would push past batch_max_items 5
        resp = api.append_order_to_batch(
            batch["id"], {"order_id": o2["id"]}, make_picker_headers(picker["id"])
        )
        validate_error(resp, ApiErrorId.ERR_BATCH_FULL)
        assert read_order(o2["id"])["status"] == "PLACED"
        assert read_balance(balance["id"])["reserved"] == 3


class TestSegregationOfDuties:
    def test_self_seal_vs_batch_empty_priority(self, api):
        """PRD §2.6: "Only after existence does the server evaluate
        state-transition legality (ERR_INVALID_STATE), business-safety rules,
        capacity and fiscal constraints ... This ordering is normative: when
        several violations coexist, the earliest category in this sequence
        determines the response."
        PRD §2.9: "a self-seal attempt is rejected with
        ERR_SELF_SEAL_FORBIDDEN."

        Design: Difficulty/priority_pair_validation_conflict/self_seal_vs_batch_empty_priority
        """
        set_clock("2026-09-10T14:00:00Z")
        site = create_site()
        picker = create_picker(site["id"], name="Pat Picker")
        batch = open_batch(site["id"], picker["id"])  # empty batch
        resp = api.seal_pick_batch(batch["id"], make_picker_headers(picker["id"]))
        err = validate_error(resp, ApiErrorId.ERR_SELF_SEAL_FORBIDDEN)
        assert err["error_id"] != "ERR_BATCH_EMPTY", "safety outranks the empty-batch constraint"
        batch_after = read_pick_batch(batch["id"])
        assert batch_after["status"] == "OPEN"
        assert batch_after["sealed_by_id"] is None

    def test_self_seal_on_non_empty_batch_also_forbidden(self, api):
        """PRD §2.9: "the picker who seals a batch must be a different picker
        than the owner; a self-seal attempt is rejected with
        ERR_SELF_SEAL_FORBIDDEN."

        Design: Difficulty/priority_pair_validation_conflict/self_seal_vs_batch_empty_priority
        """
        set_clock("2026-09-10T14:00:00Z")
        site, product, _ = _site_with_stock()
        customer = create_customer()
        picker = create_picker(site["id"], name="Pat Picker")
        order = place_order(customer["id"], site["id"], [order_line(product["id"], 1)])
        batch = open_batch(site["id"], picker["id"])
        append_order(batch["id"], order["id"], picker["id"])
        resp = api.seal_pick_batch(batch["id"], make_picker_headers(picker["id"]))
        validate_error(resp, ApiErrorId.ERR_SELF_SEAL_FORBIDDEN)
        assert read_pick_batch(batch["id"])["status"] == "OPEN"

    def test_picker_cannot_seal_own_batch_peer_seal_succeeds(self, api):
        """PRD §2.9: "The picking workflow enforces segregation of duties.
        Exactly one picker owns a batch, and the picker who seals a batch must
        be a different picker than the owner; a self-seal attempt is rejected
        with ERR_SELF_SEAL_FORBIDDEN. Only ACTIVE pickers may own or seal
        batches."

        Design: Corner/rbac/picker_cannot_seal_own_batch
        """
        set_clock("2026-09-10T14:00:00Z")
        site, product, _ = _site_with_stock()
        customer = create_customer()
        pat = create_picker(site["id"], name="Pat Picker")
        sam = create_picker(site["id"], name="Sam Sealer")
        order = place_order(customer["id"], site["id"], [order_line(product["id"], 1)])
        batch = open_batch(site["id"], pat["id"])
        append_order(batch["id"], order["id"], pat["id"])
        own = api.seal_pick_batch(batch["id"], make_picker_headers(pat["id"]))
        validate_error(own, ApiErrorId.ERR_SELF_SEAL_FORBIDDEN)
        assert read_pick_batch(batch["id"])["status"] == "OPEN"
        sealed = get_success_data(api.seal_pick_batch(batch["id"], make_picker_headers(sam["id"])))
        assert sealed["status"] == "SEALED"
        assert sealed["sealed_by_id"] == sam["id"]


class TestSealCascade:
    def test_batch_seal_side_effects_move_every_order(self, api):
        """PRD §3.6: "The seal writes sealed_at and sealed_by_id, moves the
        batch to SEALED, and fans out a per-order cascade: every appended order
        transitions PICKING → AWAITING_HANDOFF; for every line, the reservation
        commits, subtracting the quantity from reserved and from on_hand"

        Design: Corner/state_machines/batch_seal_side_effects_move_every_order
        """
        set_clock("2026-09-10T14:00:00Z")
        site, product, balance = _site_with_stock()
        customer = create_customer()
        pat = create_picker(site["id"], name="Pat Picker")
        sam = create_picker(site["id"], name="Sam Sealer")
        o1 = place_order(customer["id"], site["id"], [order_line(product["id"], 1)])
        o2 = place_order(customer["id"], site["id"], [order_line(product["id"], 2)])
        batch = open_batch(site["id"], pat["id"])
        append_order(batch["id"], o1["id"], pat["id"])
        append_order(batch["id"], o2["id"], pat["id"])
        sealed = get_success_data(api.seal_pick_batch(batch["id"], make_picker_headers(sam["id"])))
        assert sealed["status"] == "SEALED"
        assert sealed["sealed_by_id"] == sam["id"]
        assert sealed["sealed_at"], "seal writes sealed_at"
        assert read_order(o1["id"])["status"] == "AWAITING_HANDOFF"
        assert read_order(o2["id"])["status"] == "AWAITING_HANDOFF"
        bal = read_balance(balance["id"])
        assert bal["on_hand"] == 47 and bal["reserved"] == 0, bal

    def test_batch_seal_commit_cascade_depth3(self, api):
        """PRD §3.6: "every appended order transitions PICKING →
        AWAITING_HANDOFF; for every line, the reservation commits, subtracting
        the quantity from reserved and from on_hand; and for every line on a
        perishable product, the quantity is deducted from that product's FRESH
        lots at the site in earliest-expiry-first order — ordered by expires_at
        ascending, ties broken by created_at ascending — attributing the pick
        to specific lots."

        Design: Difficulty/transitive_cascade/batch_seal_commit_cascade_depth3
        """
        from test_helpers import list_stock_lots

        set_clock("2026-09-10T14:00:00Z")
        site = create_site()
        milk = create_product(sku="SKU-MILK", name="Whole Milk 1L", price_cents=350,
                              product_class="PERISHABLE")
        balance = create_balance(site["id"], milk["id"])
        # Two FRESH lots: L1 (expires sooner, qty 3) then L2 (qty 10).
        lot1 = receive_perishable_stock(site["id"], milk["id"], 3, "2026-09-13T00:00:00Z",
                                        reference="PO-L1")
        lot2 = receive_perishable_stock(site["id"], milk["id"], 10, "2026-09-18T00:00:00Z",
                                        reference="PO-L2")
        customer = create_customer()
        pat = create_picker(site["id"], name="Pat Picker")
        sam = create_picker(site["id"], name="Sam Sealer")
        order = place_order(customer["id"], site["id"], [order_line(milk["id"], 4)])
        batch = open_batch(site["id"], pat["id"])
        append_order(batch["id"], order["id"], pat["id"])
        sealed = get_success_data(api.seal_pick_batch(batch["id"], make_picker_headers(sam["id"])))
        assert sealed["status"] == "SEALED" and sealed["sealed_by_id"] == sam["id"]
        assert read_order(order["id"])["status"] == "AWAITING_HANDOFF"
        bal = read_balance(balance["id"])
        assert bal["on_hand"] == 9 and bal["reserved"] == 0, bal
        remaining = {lot["id"]: lot["remaining_qty"] for lot in list_stock_lots()}
        assert remaining[lot1["id"]] == 0, "earliest-expiry-first: L1 drained first"
        assert remaining[lot2["id"]] == 9, "the 4th unit comes from L2"

    def test_batch_seal_requires_non_empty_batch(self, api):
        """PRD §3.6: "Sealing requires the batch to be OPEN with at least one
        appended order; sealing an empty batch is rejected with
        ERR_BATCH_EMPTY."

        Design: Corner/state_machines/batch_seal_side_effects_move_every_order
        """
        set_clock("2026-09-10T14:00:00Z")
        site = create_site()
        pat = create_picker(site["id"], name="Pat Picker")
        sam = create_picker(site["id"], name="Sam Sealer")
        batch = open_batch(site["id"], pat["id"])
        resp = api.seal_pick_batch(batch["id"], make_picker_headers(sam["id"]))
        validate_error(resp, ApiErrorId.ERR_BATCH_EMPTY)
        assert read_pick_batch(batch["id"])["status"] == "OPEN"


class TestBatchAutoClose:
    def test_batch_auto_closes_when_last_order_terminal(self, api):
        """PRD §3.6: "The batch closes automatically: once every appended order
        has reached a terminal state (DELIVERED or CANCELLED), the batch
        transitions SEALED → CLOSED with no operator action."

        Design: Corner/state_machines/batch_auto_closes_when_last_order_terminal
        """
        from test_helpers import (
            assign_bag,
            create_bag_for_order,
            create_driver,
            deliver_bag,
            seal_batch,
        )

        set_clock("2026-09-10T14:00:00Z")
        site, product, balance = _site_with_stock()
        customer = create_customer()
        pat = create_picker(site["id"], name="Pat Picker")
        sam = create_picker(site["id"], name="Sam Sealer")
        driver = create_driver(site["id"], name="Dee Driver", max_run_orders=4)
        o_a = place_order(customer["id"], site["id"], [order_line(product["id"], 1)])
        o_b = place_order(customer["id"], site["id"], [order_line(product["id"], 1)])
        batch = open_batch(site["id"], pat["id"])
        append_order(batch["id"], o_a["id"], pat["id"])
        append_order(batch["id"], o_b["id"], pat["id"])
        seal_batch(batch["id"], sam["id"])
        bag_a = assign_bag(create_bag_for_order(o_a["id"])["id"])
        bag_b = assign_bag(create_bag_for_order(o_b["id"])["id"])

        deliver_bag(bag_a["id"], driver["id"])
        assert read_pick_batch(batch["id"])["status"] == "SEALED", \
            "aggregate not yet terminal while the second order is in flight"
        deliver_bag(bag_b["id"], driver["id"])
        assert read_pick_batch(batch["id"])["status"] == "CLOSED", \
            "auto-transition on the last terminal child"


class TestAgePreScreen:
    def test_age_prescreen_at_batch_append_blocks_underage_customer(self, api):
        """PRD §3.6: "if the order contains_age_restricted, the customer's age
        at the logical clock must be at least 21 — a customer whose 21st
        birthday is the current date passes — otherwise the append is rejected
        with ERR_AGE_VERIFICATION_REQUIRED as a pre-screen ahead of the
        physical handoff."

        Design: Corner/validations/age_prescreen_at_batch_append_blocks_underage_customer
        """
        set_clock("2026-09-10T14:00:00Z")
        site = create_site()
        beer = create_product(sku="SKU-BEER-A", name="Lager 6-pack", price_cents=999,
                              product_class="AGE_RESTRICTED")
        balance = create_balance(site["id"], beer["id"])
        seed_on_hand(balance["id"], 10)
        young = create_customer(email="young@example.com", full_name="Yara Young",
                                date_of_birth="2005-09-11T00:00:00Z")
        ofage = create_customer(email="ofage@example.com", full_name="Otto Ofage",
                                date_of_birth="2005-09-10T00:00:00Z")
        picker = create_picker(site["id"], name="Pat Picker")
        o_young = place_order(young["id"], site["id"], [order_line(beer["id"], 1)])
        o_ofage = place_order(ofage["id"], site["id"], [order_line(beer["id"], 1)])
        batch = open_batch(site["id"], picker["id"])

        blocked = api.append_order_to_batch(
            batch["id"], {"order_id": o_young["id"]}, make_picker_headers(picker["id"])
        )
        validate_error(blocked, ApiErrorId.ERR_AGE_VERIFICATION_REQUIRED)
        assert read_order(o_young["id"])["status"] == "PLACED"

        allowed = api.append_order_to_batch(
            batch["id"], {"order_id": o_ofage["id"]}, make_picker_headers(picker["id"])
        )
        validate_success(allowed)
        assert read_order(o_ofage["id"])["status"] == "PICKING", \
            "birthday-today is the >= 21 boundary (inclusive)"


class TestPerishableFreshCover:
    def test_perishable_pick_requires_fresh_cover_not_just_on_hand(self, api):
        """PRD §3.2: "Perishable lines carry an additional gate, evaluated at
        batch-append time: the sum of remaining_qty across that product's FRESH
        lots at the site must cover the requested quantity, otherwise the
        append fails with ERR_PRODUCT_UNSELLABLE."

        Design: Corner/calculations/perishable_pick_requires_fresh_cover_not_just_on_hand
        """
        set_clock("2026-09-10T14:00:00Z")
        site = create_site()  # expiry_horizon_days 2
        milk = create_product(sku="SKU-MILK", name="Whole Milk 1L", price_cents=350,
                              product_class="PERISHABLE")
        balance = create_balance(site["id"], milk["id"])
        # One lot of 3 expiring 2026-09-11T14:00:00Z -> inside the horizon, EXPIRING.
        receive_perishable_stock(site["id"], milk["id"], 3, "2026-09-11T14:00:00Z",
                                 reference="PO-EXP")
        customer = create_customer()
        picker = create_picker(site["id"], name="Pat Picker")
        order = place_order(customer["id"], site["id"], [order_line(milk["id"], 1)])
        batch = open_batch(site["id"], picker["id"])
        resp = api.append_order_to_batch(
            batch["id"], {"order_id": order["id"]}, make_picker_headers(picker["id"])
        )
        validate_error(resp, ApiErrorId.ERR_PRODUCT_UNSELLABLE)
        assert read_balance(balance["id"])["on_hand"] == 3, \
            "the balance alone would have sufficed; the FRESH-cover gate rejects"
        assert read_order(order["id"])["status"] == "PLACED"


class TestSealCascadeBoundary:
    def test_batch_seal_commit_cascade_depth3_exact_lot_boundary(self, api):
        """PRD §3.6: "for every line on a perishable product, the quantity is
        deducted from that product's FRESH lots at the site in
        earliest-expiry-first order — ordered by expires_at ascending, ties
        broken by created_at ascending".

        An order whose quantity exactly exhausts the earliest lot consumes it
        wholly and leaves the later lot untouched.

        Design: Difficulty/transitive_cascade/batch_seal_commit_cascade_depth3
        """
        from test_helpers import list_stock_lots

        set_clock("2026-09-10T14:00:00Z")
        site = create_site()
        milk = create_product(sku="SKU-MILK", name="Whole Milk 1L", price_cents=350,
                              product_class="PERISHABLE")
        balance = create_balance(site["id"], milk["id"])
        lot1 = receive_perishable_stock(site["id"], milk["id"], 3, "2026-09-13T00:00:00Z",
                                        reference="PO-E1")
        lot2 = receive_perishable_stock(site["id"], milk["id"], 10, "2026-09-18T00:00:00Z",
                                        reference="PO-E2")
        customer = create_customer()
        pat = create_picker(site["id"], name="Pat Picker")
        sam = create_picker(site["id"], name="Sam Sealer")
        order = place_order(customer["id"], site["id"], [order_line(milk["id"], 3)])
        batch = open_batch(site["id"], pat["id"])
        append_order(batch["id"], order["id"], pat["id"])
        get_success_data(api.seal_pick_batch(batch["id"], make_picker_headers(sam["id"])))
        remaining = {lot["id"]: lot["remaining_qty"] for lot in list_stock_lots()}
        assert remaining[lot1["id"]] == 0, "the 3-unit order exactly drains the earliest lot"
        assert remaining[lot2["id"]] == 10, "the later lot is untouched"
        bal = read_balance(balance["id"])
        assert bal["on_hand"] == 10 and bal["reserved"] == 0, bal
