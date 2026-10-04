"""Cargo cancellation, feed-gas resale, settlement, and annual reconciliation."""
import pytest

from test_helpers import (
    CM,
    GS,
    OP,
    ApiErrorId,
    RECONCILE_PAYLOAD,
    create_cancelled_slot,
    create_commercial_train,
    create_confirmed_adp_with_slots,
    create_customer,
    create_draft_adp,
    add_cargo_slot,
    create_resale_payload,
    create_spa_payload,
    get_success_data,
    make_customer_rep_headers,
    setup_settled_cancellation,
    validate_error,
    validate_success,
)


class TestCancellationNotice:
    def test_cancellation_notice_exact_threshold(self, api):
        """PRD §3.7: "The cancellation is notice-gated: the whole days between the
        current logical instant and the slot's `window_start`, rounded down, must
        be at least the SPA's `cancellation_notice_days`, otherwise the request is
        rejected with `ERR_INSUFFICIENT_NOTICE`."

        Design: Difficulty/boundary_precision_check/cancellation_notice_exact_threshold
        """
        ctx = create_confirmed_adp_with_slots(
            [
                {
                    "window_start": "2027-01-10T00:00:00Z",
                    "window_end": "2027-01-17T00:00:00Z",
                },
                {
                    "window_start": "2027-01-10T00:00:00Z",
                    "window_end": "2027-01-17T00:00:00Z",
                },
            ]
        )
        get_success_data(api.set_clock("2026-12-11T00:00:00Z", OP))
        cx1 = get_success_data(
            api.cancel_cargo_slot(ctx["slots"][0]["id"], ctx["rep"])
        )
        assert cx1["notice_days_provided"] == 30, (
            f"exactly 30 whole days of notice must succeed, recorded "
            f"{cx1['notice_days_provided']}"
        )

    def test_cancellation_one_second_below_threshold_rejected(self, api):
        """PRD §3.7: "the whole days between the current logical instant and the
        slot's `window_start`, rounded down, must be at least the SPA's
        `cancellation_notice_days`, otherwise the request is rejected with
        `ERR_INSUFFICIENT_NOTICE`."

        Design: Difficulty/boundary_precision_check/cancellation_notice_exact_threshold
        """
        ctx = create_confirmed_adp_with_slots(
            [
                {
                    "window_start": "2027-01-10T00:00:00Z",
                    "window_end": "2027-01-17T00:00:00Z",
                }
            ]
        )
        get_success_data(api.set_clock("2026-12-11T00:00:01Z", OP))
        resp = api.cancel_cargo_slot(ctx["slots"][0]["id"], ctx["rep"])
        err = validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_NOTICE.value)
        assert err["error_id"] == "ERR_INSUFFICIENT_NOTICE"
        slot = get_success_data(api.get_cargo_slot(ctx["slots"][0]["id"], CM))
        assert slot["lift_status"] == "SCHEDULED"

    def test_clock_default_before_any_set(self, api):
        """PRD §2.4: "At startup, before any clock-setting call, the current
        logical UTC is exactly `2026-09-01T00:00:00Z`." PRD §3.7: "On success a
        `CargoCancellation` is created in `REGISTERED`, stamped with `cancelled_at`
        from the logical clock and the computed `notice_days_provided`".

        Design: Corner/endpoints/clock_default_before_any_set
        """
        ctx = create_confirmed_adp_with_slots(
            [
                {
                    "window_start": "2027-01-10T00:00:00Z",
                    "window_end": "2027-01-17T00:00:00Z",
                }
            ]
        )
        # never touch the clock: cancellation is stamped at the startup default
        cx = get_success_data(api.cancel_cargo_slot(ctx["slots"][0]["id"], ctx["rep"]))
        assert cx["notice_days_provided"] == 131, (
            f"131 whole days from 2026-09-01 to 2027-01-10, got "
            f"{cx['notice_days_provided']}"
        )
        assert cx["cancelled_at"] == "2026-09-01T00:00:00Z", (
            f"cancelled_at must be stamped from the startup-default clock, got "
            f"{cx['cancelled_at']}"
        )


class TestCancellationSettlement:
    def test_cancellation_settlement_with_resale_credit(self, api):
        """PRD §3.7: "First, the fixed fee due is as recorded at registration.
        Second, the gross proceeds are the sum of `gross_proceeds_usd` over the
        cancellation's `SOLD` resales. Third, the handling fee is 2% of the fixed
        fee due — computed on the gross fee, never on the net, which is what breaks
        the otherwise circular dependency. Fourth, the pipeline tariff is 0.35 USD
        per MMBTU times the sum of `offered_volume_mmbtu` over the `SOLD` resales.
        Fifth, `resale_credit_usd` is the lesser of the fixed fee due and the
        greater of zero and the gross proceeds minus the handling fee minus the
        pipeline tariff. Sixth, `net_due_usd` is the fixed fee due minus the resale
        credit."
        (gross 12,600,000; handling 252,000; tariff 0.35*3,960,000 = 1,386,000;
        credit min(12.6M, 9,504,000-1,638,000) = 7,866,000; net 4,734,000.00.)

        Design: Corner/calculations/cancellation_settlement_with_resale_credit
        """
        ctx = setup_settled_cancellation(resales=[(3960000, 2.40)])
        cx = ctx["cancellation"]
        resale = ctx["resales"][0]
        assert cx["fixed_fee_due_usd"] == pytest.approx(12600000.00, abs=0.01)
        assert resale["gross_proceeds_usd"] == pytest.approx(9504000.00, abs=0.01)
        assert cx["resale_credit_usd"] == pytest.approx(7866000.00, abs=0.01), (
            f"credit = min(12600000, 9504000-252000-1386000) = 7866000, got "
            f"{cx['resale_credit_usd']}"
        )
        assert cx["net_due_usd"] == pytest.approx(4734000.00, abs=0.01)
        assert cx["status"] == "SETTLED"

    def test_settlement_moves_slot_billing_to_final_invoiced(self, api):
        """PRD §3.7: "The cancelled slot's `billing_status` moves directly from
        `UNBILLED` to `FINAL_INVOICED` — the fixed fee is the final bill for a
        cancelled cargo — and the cancellation becomes `SETTLED`."

        Design: Corner/calculations/cancellation_settlement_with_resale_credit
        """
        ctx = setup_settled_cancellation(resales=[(3960000, 2.40)])
        assert ctx["slot"]["billing_status"] == "FINAL_INVOICED", (
            f"settled cancellation moves slot billing to FINAL_INVOICED, got "
            f"{ctx['slot']['billing_status']}"
        )
        assert ctx["cancellation"]["status"] == "SETTLED"

    def test_cancellation_credit_capped_at_gross(self, api):
        """PRD §3.7: "Fifth, `resale_credit_usd` is the lesser of the fixed fee
        due and the greater of zero and the gross proceeds minus the handling fee
        minus the pipeline tariff. Sixth, `net_due_usd` is the fixed fee due minus
        the resale credit."
        (Resale at 10.00/mmbtu: proceeds 39,600,000 far above the fee; credit caps
        at 12,600,000 and net due is exactly 0.00.)

        Design: Corner/calculations/cancellation_credit_capped_at_gross
        """
        ctx = setup_settled_cancellation(resales=[(3960000, 10.00)])
        cx = ctx["cancellation"]
        assert cx["resale_credit_usd"] == pytest.approx(12600000.00, abs=0.01), (
            f"credit must cap at the fixed fee due, got {cx['resale_credit_usd']}"
        )
        assert cx["net_due_usd"] == pytest.approx(0.00, abs=0.001)

    def test_cancellation_unsold_resale_zero_credit(self, api):
        """PRD §3.7: "Any resale still `OFFERED` at settlement is automatically
        flipped to `UNSOLD`." PRD §3.7: "the gross proceeds are the sum of
        `gross_proceeds_usd` over the cancellation's `SOLD` resales."

        Design: Corner/calculations/cancellation_unsold_resale_zero_credit
        """
        ctx = create_cancelled_slot()
        cx = ctx["cancellation"]
        resale = get_success_data(
            api.create_resale(cx["id"], create_resale_payload(1000000), GS)
        )
        cx = get_success_data(api.settle_cancellation(cx["id"], CM))
        resales = get_success_data(api.list_cancellation_resales(cx["id"], GS))
        resale = resales[0]
        assert resale["status"] == "UNSOLD", (
            f"offered resale must flip to UNSOLD at settle, got {resale['status']}"
        )
        assert cx["resale_credit_usd"] == pytest.approx(0.00, abs=0.001)
        assert cx["net_due_usd"] == pytest.approx(12600000.00, abs=0.01)

    def test_settle_twice_and_resale_after_settle_rejected(self, api):
        """PRD §3.7: "A `CommercialManager` settles a `REGISTERED` cancellation —
        settling an already-settled one is rejected with
        `ERR_CANCELLATION_INVALID_STATE`". PRD §3.7: "Offering a resale against an
        already-`SETTLED` cancellation is rejected with
        `ERR_CANCELLATION_INVALID_STATE`."

        Design: Corner/errors/settle_twice_and_resale_after_settle_rejected
        """
        ctx = setup_settled_cancellation()
        cx = ctx["cancellation"]
        resp = api.settle_cancellation(cx["id"], CM)
        err = validate_error(resp, ApiErrorId.ERR_CANCELLATION_INVALID_STATE.value)
        assert err["error_id"] == "ERR_CANCELLATION_INVALID_STATE"
        resp = api.create_resale(cx["id"], create_resale_payload(100000), GS)
        err = validate_error(resp, ApiErrorId.ERR_CANCELLATION_INVALID_STATE.value)
        assert err["error_id"] == "ERR_CANCELLATION_INVALID_STATE"

    def test_resale_sell_twice_rejected(self, api):
        """PRD §3.7: "selling a resale that is no longer `OFFERED` is rejected
        with `ERR_RESALE_INVALID_STATE`." PRD §3.7: "moves the resale from
        `OFFERED` to `SOLD` and computes `gross_proceeds_usd` as the offered volume
        times the sale price, rounded half-up to 2 decimal places".

        Design: Corner/errors/resale_sell_twice_rejected
        """
        ctx = create_cancelled_slot()
        cx = ctx["cancellation"]
        resale = get_success_data(
            api.create_resale(cx["id"], create_resale_payload(3960000), GS)
        )
        resale = get_success_data(
            api.sell_resale(resale["id"], {"sale_price_usd_per_mmbtu": 2.40}, GS)
        )
        resp = api.sell_resale(
            resale["id"], {"sale_price_usd_per_mmbtu": 3.00}, GS
        )
        err = validate_error(resp, ApiErrorId.ERR_RESALE_INVALID_STATE.value)
        assert err["error_id"] == "ERR_RESALE_INVALID_STATE"
        resales = get_success_data(api.list_cancellation_resales(cx["id"], GS))
        assert resales[0]["gross_proceeds_usd"] == pytest.approx(9504000.00, abs=0.01), (
            "gross_proceeds must remain from the first sale"
        )

    def test_resale_volume_exceeds_cancelled_feed_gas(self, api):
        """PRD §3.7: "the cumulative offered volume across all of the
        cancellation's resales that are not `UNSOLD` must never exceed the
        cancelled slot's `scheduled_feed_gas_mmbtu`, and a breach is rejected with
        `ERR_RESALE_VOLUME_EXCEEDED`."

        Design: Corner/validations/resale_volume_exceeds_cancelled_feed_gas
        """
        ctx = create_cancelled_slot()
        cx = ctx["cancellation"]
        get_success_data(
            api.create_resale(cx["id"], create_resale_payload(3960000), GS)
        )
        resp = api.create_resale(cx["id"], create_resale_payload(1), GS)
        err = validate_error(resp, ApiErrorId.ERR_RESALE_VOLUME_EXCEEDED.value)
        assert err["error_id"] == "ERR_RESALE_VOLUME_EXCEEDED"

    def test_customer_rep_cannot_create_turnaround_or_settle(self, api):
        """PRD §2.1: "A request whose role is not listed for the target endpoint is
        rejected with `ERR_FORBIDDEN` (HTTP 403)." PRD §4: POST
        `/api/trains/{id}/turnarounds` is listed for `TerminalOperator` and POST
        `/api/cargo-cancellations/{id}/settle` is listed for `CommercialManager`.

        Design: Corner/rbac/customer_rep_cannot_create_turnaround_or_settle
        """
        ctx = create_cancelled_slot()
        cx = ctx["cancellation"]
        train = create_commercial_train()
        resp = api.propose_turnaround(
            train["id"],
            {"planned_start_date": "2027-03-01", "planned_end_date": "2027-03-05"},
            ctx["rep"],
        )
        err = validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)
        assert err["error_id"] == "ERR_FORBIDDEN"
        resp = api.settle_cancellation(cx["id"], ctx["rep"])
        err = validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)
        assert err["error_id"] == "ERR_FORBIDDEN"


class TestAnnualReconciliation:
    def test_adp_reconciliation_deficiency_and_boundary(self, api):
        """PRD §3.9: "The contractual lower bound is the annual contract quantity
        multiplied by one minus the `tolerance_pct`, and the `shortfall_mmbtu` is
        the greater of zero and that lower bound rounded down to a whole MMBTU
        minus the delivered equivalent; when the delivered equivalent exactly
        equals the rounded-down bound, the shortfall is zero and no deficiency
        arises — the bound is inclusive. The `deficiency_amount_usd` is the
        shortfall multiplied by the sum of the SPA's
        `fixed_liquefaction_fee_usd_per_mmbtu` and the `commodity_multiplier` times
        the reference index price, rounded half-up to 2 decimal places."
        (ADP-A: bound 3,420,000, delivered 0 -> deficiency 3,420,000 * 7.065 =
        24,162,300.00. ADP-B: cancelled cargo counts in full; delivered 3,600,000
        == bound with tolerance 0 -> deficiency exactly 0.00.)

        Design: Corner/calculations/adp_reconciliation_deficiency_and_boundary
        """
        customer = create_customer(legal_name="Het LNG")
        create_commercial_train()
        spa_a = get_success_data(
            api.create_spa(
                create_spa_payload(
                    customer["id"], annual_contract_quantity_mmbtu=3600000
                ),
                CM,
            )
        )
        spa_b = get_success_data(
            api.create_spa(
                create_spa_payload(
                    customer["id"],
                    annual_contract_quantity_mmbtu=3600000,
                    tolerance_pct=0,
                ),
                CM,
            )
        )
        spa_a = get_success_data(api.commence_spa_deliveries(spa_a["id"], CM))
        spa_b = get_success_data(api.commence_spa_deliveries(spa_b["id"], CM))
        adp_a = create_draft_adp(spa_a["id"], spa_a["version"])
        adp_b = create_draft_adp(spa_b["id"], spa_b["version"])
        add_cargo_slot(adp_a["id"], quantity_mmbtu=3600000)
        slot_b = add_cargo_slot(adp_b["id"], quantity_mmbtu=3600000)
        rep = make_customer_rep_headers(customer["id"])
        get_success_data(api.propose_adp(adp_a["id"], CM))
        get_success_data(api.propose_adp(adp_b["id"], CM))
        get_success_data(api.confirm_adp(adp_a["id"], rep))
        get_success_data(api.confirm_adp(adp_b["id"], rep))
        get_success_data(api.lock_adp(adp_a["id"], CM))
        get_success_data(api.lock_adp(adp_b["id"], CM))
        # cancel B's slot (47 days notice from 2027-04-15 to 2027-06-01)
        get_success_data(api.set_clock("2027-04-15T00:00:00Z", OP))
        get_success_data(api.cancel_cargo_slot(slot_b["id"], rep))
        get_success_data(api.set_clock("2028-01-02T00:00:00Z", OP))

        adp_a = get_success_data(api.reconcile_adp(adp_a["id"], RECONCILE_PAYLOAD, CM))
        adp_b = get_success_data(api.reconcile_adp(adp_b["id"], RECONCILE_PAYLOAD, CM))
        assert adp_a["shortfall_mmbtu"] == 3420000
        assert adp_a["deficiency_amount_usd"] == pytest.approx(24162300.00, abs=0.01)
        assert adp_b["delivered_equivalent_mmbtu"] == 3600000, (
            "a cancelled cargo still counts toward take-or-pay"
        )
        assert adp_b["shortfall_mmbtu"] == 0, (
            "delivered == rounded-down bound is inclusive; shortfall must be zero"
        )
        assert adp_b["deficiency_amount_usd"] == pytest.approx(0.00, abs=0.001)

    def test_reconcile_before_year_end_rejected(self, api):
        """PRD §3.9: "The call requires the current logical UTC to be past the
        first instant of the year following the ADP's contract year and the ADP to
        be `LOCKED`; running it earlier or against a program in any other state is
        rejected with `ERR_RECONCILE_PREMATURE`."

        Design: Corner/validations/reconcile_before_year_end_rejected
        """
        ctx = create_confirmed_adp_with_slots(
            [{"quantity_mmbtu": 3600000}],
            annual_contract_quantity_mmbtu=3600000,
            tolerance_pct=0,
        )
        get_success_data(api.lock_adp(ctx["adp"]["id"], CM))
        get_success_data(api.set_clock("2027-12-31T23:59:59Z", OP))
        resp = api.reconcile_adp(ctx["adp"]["id"], RECONCILE_PAYLOAD, CM)
        err = validate_error(resp, ApiErrorId.ERR_RECONCILE_PREMATURE.value)
        assert err["error_id"] == "ERR_RECONCILE_PREMATURE"

    def test_reconcile_at_year_boundary_succeeds(self, api):
        """PRD §3.9: "The call requires the current logical UTC to be past the
        first instant of the year following the ADP's contract year and the ADP to
        be `LOCKED`; running it earlier or against a program in any other state is
        rejected with `ERR_RECONCILE_PREMATURE`." PRD §3.9: "The
        `deficiency_amount_usd` is the shortfall multiplied by the sum of the
        SPA's `fixed_liquefaction_fee_usd_per_mmbtu` and the
        `commodity_multiplier` times the reference index price".
        (Idle slot, tolerance 0: shortfall 3,600,000 * (3.50 + 1.15*3.10 = 7.065)
        = 25,434,000.00.)

        Design: Corner/validations/reconcile_before_year_end_rejected
        """
        ctx = create_confirmed_adp_with_slots(
            [{"quantity_mmbtu": 3600000}],
            annual_contract_quantity_mmbtu=3600000,
            tolerance_pct=0,
        )
        get_success_data(api.lock_adp(ctx["adp"]["id"], CM))
        get_success_data(api.set_clock("2027-12-31T23:59:59Z", OP))
        validate_error(
            api.reconcile_adp(ctx["adp"]["id"], RECONCILE_PAYLOAD, CM),
            ApiErrorId.ERR_RECONCILE_PREMATURE.value,
        )
        get_success_data(api.set_clock("2028-01-01T00:00:00Z", OP))
        adp = get_success_data(api.reconcile_adp(ctx["adp"]["id"], RECONCILE_PAYLOAD, CM))
        assert adp["deficiency_amount_usd"] == pytest.approx(25434000.00, abs=0.01)
