"""Payment runs: composition guards, discount tiers, lifecycle cascades.

Covers PRD §3.8 run composition (manual and automatic fill), OCC on
composition (§2.9), the gross-keyed discount tier, segregation of duties on
release, the three-hop release/settle cascades, and unlock compensation.
"""
from test_helpers import (
    ADMIN,
    FINANCE,
    ApiErrorId,
    add_run_item,
    audit_invoice_to_cleared,
    build_cleared_invoice,
    build_eur_invoice,
    build_locked_run,
    create_active_client,
    create_carrier,
    create_active_contract,
    create_invoice,
    create_payment_run,
    create_shipment,
    ftl_lane_us_us,
    get_invoice,
    get_payment_run,
    list_run_advices,
    list_run_items,
    lock_run,
    ltl_lane_us_ca,
    make_treasury_approver_headers,
    release_run,
    settle_run,
    set_clock,
    setup_eur_fx_chain,
    setup_standard_chain,
    unlock_run,
    validate_error,
    validate_success,
)


def _ftl_invoice(chain, number, pro, billed=505000, invoice_date="2026-08-04"):
    """5000 kg FTL shipment rated exactly at 505000 (101/kg), cleared."""
    shipment = create_shipment(
        chain["client"]["id"],
        chain["carrier"]["id"],
        pro_number=pro,
        origin_country="US",
        dest_country="US",
        mode="FTL",
        actual_weight_kg=5000,
        accessorials_rendered=[],
    )
    invoice = create_invoice(
        chain["client"]["id"],
        chain["carrier"]["id"],
        invoice_number=number,
        shipment_id=shipment["id"],
        invoice_date=invoice_date,
        billed_total_minor=billed,
        lines=[{"charge_code": "BASE_FREIGHT", "billed_amount_minor": billed}],
    )
    finalized = audit_invoice_to_cleared(invoice["id"])
    assert finalized["audit_status"] == "CLEARED", "Setup failed: FTL invoice not CLEARED"
    return finalized


class TestDiscountTierKeyedOnGross:
    """Two 505000 items: gross 1010000 crosses the 1000000 tier, so the tier
    is read off the pre-discount gross, not the post-discount net."""

    def _setup(self, api):
        chain = setup_standard_chain(lanes=[ftl_lane_us_us()])
        inv1 = _ftl_invoice(chain, "INV-0501", "PRO-5001")
        # inv2 must not fuzzy-match inv1 at capture (PRD §3.3: equal billed
        # totals within a 7-day invoice-date window flag FUZZY, which would
        # route finalization to EXCEPTION with DUPLICATE_FUZZY), so its
        # invoice_date is placed 8 days after inv1's.
        inv2 = _ftl_invoice(chain, "INV-0502", "PRO-5002", invoice_date="2026-08-12")
        run = create_payment_run(chain["client"]["id"])
        add_run_item(run["id"], inv1["id"])
        add_run_item(run["id"], inv2["id"])
        return chain, inv1, inv2, run

    def test_lock_computes_tier_150bp_from_gross(self, api):
        """PRD §3.8: "The evaluation order is pinned to break the circularity
        between gross and discount: first `gross_total_minor` is the sum of the
        items' `scheduled_amount_minor`; then the discount tier is read off
        that pre-discount gross — a gross of at least 5,000,000 minor units
        earns 250 basis points, a gross of at least 1,000,000 earns 150 basis
        points, anything below earns none; then each item's `discount_minor` is
        its `scheduled_amount_minor` multiplied by the tier's basis points and
        divided by ten thousand, rounded half up; finally `discount_total_minor`
        is the sum of the item discounts and `total_minor` is
        `gross_total_minor` minus `discount_total_minor`."

        Keying on the post-discount net (994850 < 1000000) would wrongly earn
        no discount.

        Design: Difficulty/combinatorial_formula/run_discount_tier_gross_keyed_mode_c
        """
        _chain, _i1, _i2, run = self._setup(api)
        locked = lock_run(run["id"])
        assert locked["gross_total_minor"] == 1010000
        assert locked["discount_total_minor"] == 15150
        assert locked["total_minor"] == 994850

    def test_each_item_discount_is_rounded_half_up(self, api):
        """PRD §3.8: "then each item's `discount_minor` is its
        `scheduled_amount_minor` multiplied by the tier's basis points and
        divided by ten thousand, rounded half up".

        Each 505000 item at 150 bp discounts round_half_up(7575.0) = 7575.

        Design: Difficulty/combinatorial_formula/run_discount_tier_gross_keyed_mode_c
        """
        _chain, inv1, inv2, run = self._setup(api)
        lock_run(run["id"])
        items = {item["invoice_id"]: item for item in list_run_items(run["id"])}
        assert items[inv1["id"]]["discount_minor"] == 7575
        assert items[inv2["id"]]["discount_minor"] == 7575
        assert items[inv1["id"]]["scheduled_amount_minor"] == 505000


class TestEmptyRunLock:
    def test_lock_without_items_is_rejected(self, api):
        """PRD §3.8: "Locking (`DRAFT` → `LOCKED`) prices the run's
        early-settlement discount and requires at least one item
        (`ERR_EMPTY_PAYMENT_RUN`)."

        Design: Difficulty/boundary_precision_check/empty_payment_run_lock_rejected
        """
        chain = setup_standard_chain(with_contract=False)
        run = create_payment_run(chain["client"]["id"])
        res = api.lock_payment_run(run["id"], FINANCE)
        validate_error(res, ApiErrorId.ERR_EMPTY_PAYMENT_RUN, expected_status=409)
        current = get_payment_run(run["id"])
        assert current["status"] == "DRAFT"

    def test_auto_fill_with_zero_eligible_surfaces_at_lock(self, api):
        """PRD §3.8: "Eligible invoices are added in `due_date` ascending
        order, ties broken by the invoice's `created_at` ascending; an empty
        eligible set adds zero items, which surfaces later when locking fails."

        With no invoices at all, automatic fill adds nothing and the lock then
        fails with `ERR_EMPTY_PAYMENT_RUN`.

        Design: Difficulty/boundary_precision_check/empty_payment_run_lock_rejected
        """
        chain = setup_standard_chain(with_contract=False)
        run = create_payment_run(chain["client"]["id"])
        filled = validate_success(
            api.auto_fill_payment_run(
                run["id"], {"expected_payment_run_version": run["version"]}, FINANCE
            ),
            200,
        )
        # Each successful composition step increments the run's version (§2.9).
        assert filled["version"] == run["version"] + 1
        assert list_run_items(run["id"]) == []
        res = api.lock_payment_run(run["id"], FINANCE)
        validate_error(res, ApiErrorId.ERR_EMPTY_PAYMENT_RUN, expected_status=409)


class TestReleaseCascade:
    """Release hops: items RELEASED, invoices SCHEDULED with scheduled_minor,
    one remittance advice per carrier GENERATED; settle replays to PAID/SENT."""

    def _setup(self, api):
        chain = setup_standard_chain()
        invoice = build_cleared_invoice(chain)
        run = build_locked_run(chain["client"]["id"], [invoice["id"]])
        return chain, invoice, run

    def test_release_advances_items_invoice_and_spawns_advice(self, api):
        """PRD §3.8: "Release cascades in three hops. Hop one: every item moves
        `SCHEDULED` → `RELEASED`. Hop two, per item: the item's invoice moves
        from payment status `UNPAID` to `SCHEDULED`, and the item's
        `scheduled_amount_minor` is added to the invoice's `scheduled_minor` —
        the accumulator that tracks, in run currency, what is scheduled against
        the invoice in released runs. Hop three: one remittance advice is
        created per distinct carrier among the items, born `GENERATED`, with
        `total_minor` equal to the sum of each of that carrier's items'
        `scheduled_amount_minor` minus `discount_minor`, and `item_count` equal
        to the number of that carrier's items".

        The 87500 gross earns no discount tier, so the advice totals 87500.

        Design: Difficulty/transitive_cascade/payment_run_release_three_hop_cascade
        """
        chain, invoice, run = self._setup(api)
        released = release_run(run["id"])
        assert released["status"] == "RELEASED"
        items = list_run_items(run["id"])
        assert len(items) == 1 and items[0]["status"] == "RELEASED"
        current = get_invoice(invoice["id"])
        assert current["payment_status"] == "SCHEDULED"
        assert current["scheduled_minor"] == 87500
        advices = list_run_advices(run["id"])
        assert len(advices) == 1
        assert advices[0]["status"] == "GENERATED"
        assert advices[0]["carrier_id"] == chain["carrier"]["id"]
        assert advices[0]["total_minor"] == 87500
        assert advices[0]["item_count"] == 1

    def test_settle_replays_the_chain_to_paid_and_sent(self, api):
        """PRD §3.8: "Every item moves `RELEASED` → `PAID`. Per item, the
        invoice's `paid_minor` grows by the item's `scheduled_amount_minor`
        minus its `discount_minor`, in run currency; the invoice's payment
        status becomes `PAID` when the item's `discount_minor` is zero, and
        `SHORT_PAID` when a retained discount leaves it short. Every remittance
        advice of the run moves `GENERATED` → `SENT`."

        Design: Difficulty/transitive_cascade/payment_run_release_three_hop_cascade
        """
        _chain, invoice, run = self._setup(api)
        release_run(run["id"])
        settled = settle_run(run["id"])
        assert settled["status"] == "SETTLED"
        items = list_run_items(run["id"])
        assert items[0]["status"] == "PAID"
        current = get_invoice(invoice["id"])
        assert current["payment_status"] == "PAID"
        assert current["paid_minor"] == 87500
        advices = list_run_advices(run["id"])
        assert advices[0]["status"] == "SENT"


class TestUnlockCompensation:
    """Unlock deletes items and zeroes totals, returning every invoice's
    payment dimension to its pre-lock values with zero drift."""

    def test_unlock_deletes_items_and_zeroes_totals(self, api):
        """PRD §3.8: "Unlocking (`LOCKED` → `DRAFT`) is the compensation: every
        item is deleted and all three totals reset to zero. Because items only
        begin to affect invoices at release, an unlock normally has no invoice
        effects to reverse".

        Design: Difficulty/compensating_invariant/run_lock_unlock_money_conservation
        """
        chain = setup_standard_chain()
        invoice = build_cleared_invoice(chain)
        run = build_locked_run(chain["client"]["id"], [invoice["id"]])
        unlocked = unlock_run(run["id"])
        assert unlocked["status"] == "DRAFT"
        assert unlocked["gross_total_minor"] == 0
        assert unlocked["discount_total_minor"] == 0
        assert unlocked["total_minor"] == 0
        assert list_run_items(run["id"]) == []
        current = get_invoice(invoice["id"])
        assert current["payment_status"] == "UNPAID"
        assert current["scheduled_minor"] == 0
        assert current["approved_amount_minor"] == 87500

    def test_invoice_is_schedulable_again_after_unlock(self, api):
        """PRD §3.8: "Unlocking (`LOCKED` → `DRAFT`) is the compensation: every
        item is deleted and all three totals reset to zero." PRD §3.8: "Adding
        a single item names an `invoice_id`; the invoice must be audit-`CLEARED`
        and payment-`UNPAID` (`ERR_INVOICE_NOT_PAYABLE`), its carrier must be
        `ACTIVE` (`ERR_CARRIER_NOT_ACTIVE`), and when the invoice currency
        differs from the run currency a covering exchange rate must exist
        (`ERR_FX_RATE_MISSING`)."

        After the compensation the invoice again satisfies composition
        preconditions, so a fresh run accepts it at its approved amount.

        Design: Difficulty/compensating_invariant/run_lock_unlock_money_conservation
        """
        chain = setup_standard_chain()
        invoice = build_cleared_invoice(chain)
        run = build_locked_run(chain["client"]["id"], [invoice["id"]])
        unlock_run(run["id"])
        second_run = create_payment_run(chain["client"]["id"])
        item = add_run_item(second_run["id"], invoice["id"])
        assert item["scheduled_amount_minor"] == 87500
        assert item["invoice_id"] == invoice["id"]


class TestCompositionGuards:
    def test_item_add_rejected_when_carrier_suspended(self, api):
        """PRD §3.8: "Adding a single item names an `invoice_id`; the invoice
        must be audit-`CLEARED` and payment-`UNPAID`
        (`ERR_INVOICE_NOT_PAYABLE`), its carrier must be `ACTIVE`
        (`ERR_CARRIER_NOT_ACTIVE`), and when the invoice currency differs from
        the run currency a covering exchange rate must exist
        (`ERR_FX_RATE_MISSING`)."

        The carrier is suspended after the invoice cleared; the item add fails
        and no item is created.

        Design: Difficulty/cross_entity_state_dependency/run_item_rejected_when_carrier_suspended
        """
        chain = setup_standard_chain()
        invoice = build_cleared_invoice(chain)
        validate_success(api.suspend_carrier(chain["carrier"]["id"], ADMIN), 200)
        run = create_payment_run(chain["client"]["id"])
        res = api.add_payment_run_item(
            run["id"],
            {"expected_payment_run_version": run["version"], "invoice_id": invoice["id"]},
            FINANCE,
        )
        validate_error(res, ApiErrorId.ERR_CARRIER_NOT_ACTIVE, expected_status=409)
        assert list_run_items(run["id"]) == []

    def test_item_add_rejected_when_carrier_never_onboarded(self, api):
        """PRD §3.8: "its carrier must be `ACTIVE` (`ERR_CARRIER_NOT_ACTIVE`)".
        A carrier still PENDING_ONBOARD is not ACTIVE, so scheduling against
        its cleared invoice fails identically.

        Design: Difficulty/cross_entity_state_dependency/run_item_rejected_when_carrier_suspended
        """
        set_clock()
        client = create_active_client()
        # The carrier is never onboard-approved: it stays PENDING_ONBOARD.
        pending = create_carrier(client["id"])
        create_active_contract(pending["id"])
        shipment = create_shipment(client["id"], pending["id"])
        invoice = create_invoice(
            client["id"], pending["id"], shipment_id=shipment["id"]
        )
        finalized = audit_invoice_to_cleared(invoice["id"])
        assert finalized["audit_status"] == "CLEARED", "Setup failed: not CLEARED"
        run = create_payment_run(client["id"])
        res = api.add_payment_run_item(
            run["id"],
            {"expected_payment_run_version": run["version"], "invoice_id": invoice["id"]},
            FINANCE,
        )
        validate_error(res, ApiErrorId.ERR_CARRIER_NOT_ACTIVE, expected_status=409)

    def test_release_by_creator_violates_segregation_of_duties(self, api):
        """PRD §3.8: "Release (`LOCKED` → `RELEASED`) belongs to
        `TreasuryApprover` and enforces segregation of duties: the acting
        operator must be neither the run's `created_by_user_id` nor its
        `locked_by_user_id`, failing with `ERR_SEGREGATION_OF_DUTIES`
        otherwise."

        The run's creator/locker (op-fin-1) is refused even while presenting
        the TreasuryApprover role; a distinct treasury operator succeeds.

        Design: Corner/validations/segregation_release_by_creator_forbidden
        """
        chain = setup_standard_chain()
        invoice = build_cleared_invoice(chain)
        run = build_locked_run(chain["client"]["id"], [invoice["id"]])
        res = api.release_payment_run(
            run["id"], make_treasury_approver_headers("op-fin-1")
        )
        validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, expected_status=403)
        released = release_run(run["id"])  # op-treasury-1
        assert released["status"] == "RELEASED"

    def test_run_date_before_current_logical_date_rejected(self, api):
        """PRD §3.8: "The `run_date` must not lie before the current logical
        date (`ERR_RUN_DATE_PAST`)." The logical clock starts at
        2026-08-01T00:00:00Z (PRD §2.4), so a 2026-07-01 run date is refused.

        Design: Corner/validations/run_date_in_past_rejected
        """
        chain = setup_standard_chain(with_contract=False)
        res = api.create_payment_run(
            chain["client"]["id"], {"run_date": "2026-07-01", "currency": "USD"}, FINANCE
        )
        validate_error(res, ApiErrorId.ERR_RUN_DATE_PAST, expected_status=409)

    def test_item_add_without_fx_path_rejected(self, api):
        """PRD §3.7: "When no such rate exists, the operation that needed the
        conversion fails with `ERR_FX_RATE_MISSING`." The payment-date variant
        resolves the rate as of the run's `run_date`; the only EUR->USD rate is
        effective 2026-08-03, so a run dated 2026-08-02 has no covering rate
        for the cleared EUR invoice.

        Design: Corner/validations/run_item_without_fx_path_rejected
        """
        chain = setup_eur_fx_chain(fx_rates=(("2026-08-03", 1_100_000),))
        lines = [
            {"charge_code": "BASE_FREIGHT", "billed_amount_minor": 333},
            {"charge_code": "DETENTION", "billed_amount_minor": 333},
            {"charge_code": "STORAGE", "billed_amount_minor": 333},
        ]
        invoice = build_eur_invoice(chain, lines)
        finalized = audit_invoice_to_cleared(invoice["id"])
        assert finalized["audit_status"] == "CLEARED", "Setup failed: not CLEARED"
        run = create_payment_run(
            chain["client"]["id"], run_date="2026-08-02", currency="USD"
        )
        res = api.add_payment_run_item(
            run["id"],
            {"expected_payment_run_version": run["version"], "invoice_id": finalized["id"]},
            FINANCE,
        )
        validate_error(res, ApiErrorId.ERR_FX_RATE_MISSING, expected_status=409)

    def test_second_item_add_with_stale_version_rejected(self, api):
        """PRD §2.9: "Composing a payment run (`POST
        /fap/payment-runs/{id}/items`, and the run's automatic fill via `POST
        /fap/payment-runs/{id}/auto_fill`) likewise requires
        `expected_payment_run_version` matching the run's current `version`;
        each successful composition step increments the run's `version` by one,
        so a caller batching items from an older observed version is rejected
        with `ERR_STALE_VERSION` (HTTP 412) rather than silently building on
        state it has not seen."

        The first add bumps the run version, so the second add carrying the
        pre-add version is rejected.

        Design: Corner/cross_cutting_layers/occ_stale_version_on_run_add_item_returns_412
        """
        chain = setup_standard_chain()
        inv1 = build_cleared_invoice(chain, invoice_number="INV-0001")
        inv2_shipment = create_shipment(
            chain["client"]["id"],
            chain["carrier"]["id"],
            pro_number="PRO-1002",
            ship_date="2026-08-14",
        )
        inv2 = create_invoice(
            chain["client"]["id"],
            chain["carrier"]["id"],
            invoice_number="INV-0002",
            shipment_id=inv2_shipment["id"],
            invoice_date="2026-08-15",
            billed_total_minor=87900,
            lines=[
                {"charge_code": "BASE_FREIGHT", "billed_amount_minor": 75400},
                {"charge_code": "FUEL_SURCHARGE", "billed_amount_minor": 7500},
                {"charge_code": "LIFTGATE", "billed_amount_minor": 5000},
            ],
        )
        finalized2 = audit_invoice_to_cleared(inv2["id"])
        assert finalized2["audit_status"] == "CLEARED", "Setup failed: inv2 not CLEARED"
        run = create_payment_run(chain["client"]["id"])
        stale_version = run["version"]
        add_run_item(run["id"], inv1["id"])
        res = api.add_payment_run_item(
            run["id"],
            {"expected_payment_run_version": stale_version, "invoice_id": inv2["id"]},
            FINANCE,
        )
        validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)


class TestAutoFillSelection:
    def test_due_window_boundary_and_eligibility(self, api):
        """PRD §3.8: "an invoice is eligible when it belongs to the run's
        client, is audit-`CLEARED` and payment-`UNPAID`, its carrier is
        `ACTIVE`, the run's `country_scope` is unset or matches the carrier's
        `country`, the invoice's `due_date` falls on or before the `run_date`
        plus seven days (inclusive), the invoice currency either equals the run
        currency or has an exchange-rate path into it, and the invoice is not
        already an item of any run in `DRAFT`, `LOCKED`, or `RELEASED`."

        With carrier terms of 14 days and run date 2026-08-10, the due window
        ends 2026-08-17 inclusive: INV-0002 (due 08-15) and INV-0001 (due
        08-17, the boundary) join the run; INV-0501 (due 08-18) is excluded.

        Design: Corner/calculations/auto_fill_selector_ranking_and_due_window
        """
        chain = setup_standard_chain(
            lanes=[ltl_lane_us_ca(), ftl_lane_us_us()],
            carrier_overrides={"payment_terms_days": 14},
        )
        client_id = chain["client"]["id"]
        carrier_id = chain["carrier"]["id"]
        # i1: LTL 87500 dated 2026-08-03 -> due 2026-08-17 (inclusive boundary).
        sh1 = create_shipment(client_id, carrier_id, pro_number="PRO-1001")
        i1 = create_invoice(
            client_id, carrier_id, invoice_number="INV-0001", shipment_id=sh1["id"]
        )
        # i2: LTL 88000 dated 2026-08-01 (variance exactly 500, clears) -> due 2026-08-15.
        sh2 = create_shipment(
            client_id, carrier_id, pro_number="PRO-1002", ship_date="2026-08-01"
        )
        i2 = create_invoice(
            client_id,
            carrier_id,
            invoice_number="INV-0002",
            shipment_id=sh2["id"],
            invoice_date="2026-08-01",
            billed_total_minor=88000,
            lines=[
                {"charge_code": "BASE_FREIGHT", "billed_amount_minor": 75500},
                {"charge_code": "FUEL_SURCHARGE", "billed_amount_minor": 7500},
                {"charge_code": "LIFTGATE", "billed_amount_minor": 5000},
            ],
        )
        # i8: FTL 505000 dated 2026-08-04 -> due 2026-08-18 (outside the window).
        i8 = _ftl_invoice(chain, "INV-0501", "PRO-5001")
        for invoice in (i1, i2):
            finalized = audit_invoice_to_cleared(invoice["id"])
            assert finalized["audit_status"] == "CLEARED", "Setup failed: not CLEARED"
        run = create_payment_run(client_id, run_date="2026-08-10", currency="USD")
        validate_success(
            api.auto_fill_payment_run(
                run["id"], {"expected_payment_run_version": run["version"]}, FINANCE
            ),
            200,
        )
        items = list_run_items(run["id"])
        selected = {item["invoice_id"] for item in items}
        assert len(items) == 2, f"expected 2 eligible invoices, got {len(items)}"
        assert selected == {i1["id"], i2["id"]}
        assert i8["id"] not in selected
