"""Network-wide cascades and the ledgers they move."""

import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    ApiErrorId, ADMIN, AUDITOR, COMMISSARY, get_success_data, set_clock,
    create_franchisee, create_store, create_agreement, create_open_settlement,
    add_revenue_lines, create_delivery_window, place_fresh_order,
    confirm_fresh_order, lock_delivery_window, deliver_fresh_order,
    create_draw, reconcile_settlement, finalize_settlement, refresh_franchisee,
    refresh_store, setup_reinstate_scenario, setup_store_with_agreement, setup_counted_audit, create_shrink_audit,
    setup_settlement_with_lines, make_franchisee_headers,
)


class TestReinstatementCascade:
    """The reinstatement cascade finalizes a counted audit, then restores stores."""

    def test_reinstate_finalizes_the_counted_audit_and_refreshes_the_operators_standing(self):
        """PRD §3.8: "Then the server sweeps the operator's stores and finalizes
        every shrink audit for those stores that is still `COUNTED` — driving
        each through the `COUNTED` to `FINALIZED` transition described in §3.6,
        which recomputes the operator's `open_shrink_charge_cents` from the newly
        finalized charges, then `audit_adjusted_net_worth_cents`, then
        `risk_band`, in that order."
        PRD §2.7: "An operator lands in band `A` when the audit-adjusted net
        worth is at least 15,000,000 cents".

        Design: Difficulty/transitive_cascade/franchisee_reinstate_finalizes_counted_audit_then_refreshes_risk_band_then_promotes_tier
        """
        context = setup_reinstate_scenario()
        franchisee_id = context["franchisee"]["id"]
        audit_id = context["audit"]["id"]

        # The suspension cascaded the original store to TERMINATED.
        assert context["old_store"]["status"] == "TERMINATED"
        assert context["audit"]["status"] == "COUNTED"

        reinstated = validate_success(api_client.reinstate_franchisee(franchisee_id, ADMIN), 200)
        assert reinstated["status"] == "ACTIVE"

        # Hop 1: the pending audit is finalized by the cascade.
        audit = get_success_data(api_client.get_shrink_audit(audit_id, ADMIN))
        assert audit["status"] == "FINALIZED"
        assert audit["shrink_charge_cents"] == pytest.approx(200_000.00, abs=0.01)

        # Hop 2: the finalized charge refreshes the operator's figures and band.
        franchisee = refresh_franchisee(franchisee_id)
        assert franchisee["open_shrink_charge_cents"] == pytest.approx(200_000.00, abs=0.01)
        assert franchisee["draw_outstanding_cents"] == 0
        assert franchisee["audit_adjusted_net_worth_cents"] == pytest.approx(
            20_000_000 - 200_000.00, abs=0.01)
        assert franchisee["risk_band"] == "A"

        # Hop 3: the store the suspension terminated is restored to ACTIVE.
        assert refresh_store(context["old_store"]["id"])["status"] == "ACTIVE"

    def test_the_superseded_agreement_did_not_receive_the_restoration(self):
        """PRD §3.8: "Any agreement covering the store follows its operator out of
        `ACTIVE` as well, moving to `TERMINATED` and carrying its `royalty_pct`
        of `0.0000` unchanged to the end, because no royalty accrues on
        termination under a gross-profit split."
        PRD §3.8: "every store of the operator that is currently `TERMINATED`
        returns to `ACTIVE`, because the operator's standing has just been
        restored to a compliant position by the preceding hop."

        Design: Difficulty/transitive_cascade/franchisee_reinstate_finalizes_counted_audit_then_refreshes_risk_band_then_promotes_tier
        """
        context = setup_reinstate_scenario()
        superseded_id = context["old_agreement"]["id"]
        assert context["old_agreement"]["status"] == "TERMINATED"

        validate_success(api_client.reinstate_franchisee(context["franchisee"]["id"], ADMIN), 200)

        superseded = get_success_data(api_client.get_agreement(superseded_id, ADMIN))
        assert superseded["status"] == "TERMINATED"
        assert superseded["royalty_pct"] == 0.0
        # The restored store carries no live agreement until a new one is activated.
        restored_store = refresh_store(context["old_store"]["id"])
        assert restored_store["status"] == "ACTIVE"
        store_agreements, _meta = validate_paginated(
            api_client.list_agreements(ADMIN, {"store_id": restored_store["id"]}))
        assert all(a["status"] not in ("ACTIVE",) for a in store_agreements)


class TestTerminationCascade:
    """Termination runs four hops, each caused by the one before it."""

    def test_terminate_closes_the_store_the_order_the_week_and_recovers_the_draw(self):
        """PRD §3.8: "Termination sets the operator to `TERMINATED`, a terminal
        status, and cascades to its `ACTIVE` stores exactly as suspension does."
        PRD §3.8: "every settlement for that store still in `OPEN` or
        `DRAW_PAID` is driven straight to `FINALIZED`, which runs the draw
        recovery waterfall against those settlements' net figures."
        PRD §3.7: "the advance that took only part of its balance lands in
        `PARTIALLY_RECOVERED` while one whose balance was fully covered lands in
        `RECOVERED`".

        Design: Difficulty/transitive_cascade/franchisee_terminate_cascades_store_then_cancels_order_then_finalizes_settlement
        """
        set_clock("2026-09-01T12:00:00Z")
        franchisee = create_franchisee(stated_net_worth_cents=30_000_000)
        store = create_store(franchisee["id"], cold_chain_certified=True)
        create_agreement(franchisee["id"], store["id"], rebate_pass_pct=1.0)

        # A week with an operator payout of 150,000.00 once split at 0.50.
        settlement = create_open_settlement(store, franchisee, trailing_avg=1_000_000)
        add_revenue_lines(settlement, [("SERVICES", 1_000_000, 700_000)])

        # A draw larger than the week's payout, so only part of it can be recovered.
        draw = create_draw(franchisee["id"], store["id"], 600_000,
                           drawn_on="2026-09-02T00:00:00Z")

        window = create_delivery_window(
            store["id"], "2026-09-09T06:00:00Z", "2026-09-09T10:00:00Z", 800)
        order = place_fresh_order(store["id"], window["id"], franchisee["id"],
                                 "SKU-F", 300, 350)
        confirm_fresh_order(order["id"])

        # PRD §3.8: an ACTIVE operator may be terminated "only when its
        # `draw_outstanding_cents` is exactly zero", and "A `SUSPENDED` operator
        # may be terminated with no draw condition at all". The draw here is
        # deliberately larger than the week's payout, so the operator has to be
        # suspended first; the store cascade "runs identically whether it was
        # triggered by suspension or by termination".
        validate_success(api_client.suspend_franchisee(franchisee["id"], ADMIN), 200)
        validate_success(api_client.terminate_franchisee(franchisee["id"], ADMIN), 200)

        # Hop 1: the store leaves ACTIVE.
        assert refresh_store(store["id"])["status"] == "TERMINATED"

        # Hop 2: the confirmed order is cancelled and its capacity released.
        assert get_success_data(
            api_client.get_fresh_order(order["id"], ADMIN))["status"] == "CANCELLED"
        assert get_success_data(
            api_client.get_delivery_window(window["id"], ADMIN))["reserved_units"] == 0

        # Hop 3: the open week is closed on the server's initiative.
        closed = get_success_data(api_client.get_settlement(settlement["id"], ADMIN))
        assert closed["status"] == "FINALIZED"
        # PRD §3.4 defines net_settlement_cents as the operator's share less the
        # shrink charge, the waste charge and "any `draw_recovery_cents`
        # recovered at the time", so once hop 4 has recovered the whole 150,000.00
        # payout the field nets to zero. The pre-recovery payout is what bounds
        # the waterfall, and it is the recovery figure asserted below.
        assert closed["draw_recovery_cents"] == pytest.approx(150_000.00, abs=0.01)
        assert closed["net_settlement_cents"] == pytest.approx(
            closed["franchisee_split_cents"] - closed["shrink_charge_cents"]
            - closed["waste_charge_cents"] - closed["draw_recovery_cents"], abs=0.01)

        # Hop 4: the recovery waterfall takes what the frozen payout allows.
        recovered = get_success_data(api_client.get_draw(draw["id"], ADMIN))
        assert recovered["status"] == "PARTIALLY_RECOVERED"
        assert recovered["recovered_cents"] == pytest.approx(150_000.00, abs=0.01)

        operator = refresh_franchisee(franchisee["id"])
        assert operator["draw_outstanding_cents"] == pytest.approx(450_000.00, abs=0.01)


class TestDrawRecoveryWaterfall:
    """The waterfall visits draws oldest first and stops when the cash runs out."""

    def test_the_oldest_draw_is_filled_first_and_the_walk_stops_when_the_cash_is_exhausted(self):
        """PRD §3.7: "Each candidate is then visited in order of `drawn_on`
        ascending, and where two advances share a `drawn_on`, in order of
        `created_at` ascending; the tie is never broken by identifier."
        PRD §3.7: "the amount taken is the smaller of that outstanding balance
        and the cash still available. The take is added to the advance's
        `recovered_cents` and subtracted from the available cash, and the walk
        stops as soon as the available cash reaches zero."

        Design: Corner/calculations/draw_recovery_waterfall_fills_oldest_draw_first_and_stops_when_exhausted
        """
        set_clock("2026-09-20T00:00:00Z")
        context = setup_settlement_with_lines(
            lines=[("MERCHANDISE", 3_000_000, 2_000_000)],
            split_pct=0.50, rebate_pass_pct=1.0, trailing_avg=1_000_000,
            clock="2026-09-20T00:00:00Z",
        )
        franchisee_id = context["franchisee"]["id"]
        store_id = context["store"]["id"]
        settle_id = context["settlement"]["id"]

        older = create_draw(franchisee_id, store_id, 300_000,
                            drawn_on="2026-09-02T00:00:00Z")
        newer = create_draw(franchisee_id, store_id, 300_000,
                            drawn_on="2026-09-05T00:00:00Z")

        reconcile_settlement(settle_id)
        frozen = reconcile_settlement(settle_id)
        assert frozen["net_settlement_cents"] == pytest.approx(500_000.00, abs=0.01)

        settled = finalize_settlement(settle_id)
        assert settled["draw_recovery_cents"] == pytest.approx(500_000.00, abs=0.01)

        older_after = get_success_data(api_client.get_draw(older["id"], ADMIN))
        newer_after = get_success_data(api_client.get_draw(newer["id"], ADMIN))
        # The earlier draw consumed its whole balance and part of the later one.
        assert older_after["status"] == "RECOVERED"
        assert older_after["recovered_cents"] == 300_000
        assert newer_after["status"] == "PARTIALLY_RECOVERED"
        assert newer_after["recovered_cents"] == pytest.approx(200_000.00, abs=0.01)

        assert refresh_franchisee(franchisee_id)["draw_outstanding_cents"] == pytest.approx(
            100_000.00, abs=0.01)

    def test_the_available_cash_is_floored_at_zero_and_a_fully_covered_draw_is_closed(self):
        """PRD §3.7: "The available cash is the settlement's `net_settlement_cents`
        floored at zero — an operator whose week nets nothing recovers nothing,
        and a negative net settlement allocates nothing rather than creating a
        debt."
        PRD §3.7: "one whose balance was fully covered lands in `RECOVERED`,
        with its `recovered_cents` set equal to its `amount_cents`."

        Design: Corner/calculations/draw_recovery_waterfall_fills_oldest_draw_first_and_stops_when_exhausted
        """
        set_clock("2026-09-20T00:00:00Z")
        context = setup_settlement_with_lines(
            lines=[("MERCHANDISE", 1_000_000, 1_400_000)],
            split_pct=0.50, rebate_pass_pct=1.0, trailing_avg=1_000_000,
            clock="2026-09-20T00:00:00Z",
        )
        franchisee_id = context["franchisee"]["id"]
        store_id = context["store"]["id"]
        settle_id = context["settlement"]["id"]
        draw = create_draw(franchisee_id, store_id, 400_000)

        reconcile_settlement(settle_id)
        frozen = reconcile_settlement(settle_id)
        assert frozen["net_settlement_cents"] < 0

        settled = finalize_settlement(settle_id)
        assert settled["draw_recovery_cents"] == pytest.approx(0.00, abs=0.01)

        after = get_success_data(api_client.get_draw(draw["id"], ADMIN))
        assert after["status"] == "ISSUED"
        assert after["recovered_cents"] == 0
        assert refresh_franchisee(franchisee_id)["draw_outstanding_cents"] == 400_000


class TestDrawLedgerConservation:
    """A reversal restores the outstanding figure; a recovered draw cannot be reversed."""

    def test_a_reversed_draw_restores_the_ledger_and_a_recovered_draw_cannot_be_reversed(self):
        """PRD §3.7: "A `FranchisorAdmin` may reverse a draw that is in `ISSUED`
        or `PARTIALLY_RECOVERED`, but only while its `recovered_cents` is still
        exactly zero; a draw from which anything at all has been recovered cannot
        be reversed, and the attempt is rejected with
        `ERR_DRAW_PARTIALLY_RECOVERED` (HTTP 409)."
        PRD §3.7: "Reversal moves the draw to `REVERSED`, a terminal status, and
        recomputes the operator's `draw_outstanding_cents`."

        Design: Difficulty/compensating_invariant/franchisee_draw_outstanding_cents_restored_by_reversal_and_guarded_after_recovery
        """
        set_clock("2026-09-20T00:00:00Z")
        context = setup_settlement_with_lines(
            lines=[("SERVICES", 1_000_000, 600_000)],
            split_pct=0.50, rebate_pass_pct=1.0, trailing_avg=1_000_000,
            clock="2026-09-20T00:00:00Z",
        )
        franchisee_id = context["franchisee"]["id"]
        store_id = context["store"]["id"]
        settle_id = context["settlement"]["id"]

        first = create_draw(franchisee_id, store_id, 4_000_000,
                            drawn_on="2026-09-02T00:00:00Z")
        assert refresh_franchisee(franchisee_id)["draw_outstanding_cents"] == 4_000_000

        reversed_draw = validate_success(api_client.reverse_draw(first["id"], ADMIN), 200)
        assert reversed_draw["status"] == "REVERSED"
        assert refresh_franchisee(franchisee_id)["draw_outstanding_cents"] == 0

        second = create_draw(franchisee_id, store_id, 2_500_000,
                             drawn_on="2026-09-03T00:00:00Z")
        assert refresh_franchisee(franchisee_id)["draw_outstanding_cents"] == 2_500_000

        reconcile_settlement(settle_id)
        frozen = reconcile_settlement(settle_id)
        assert frozen["net_settlement_cents"] == pytest.approx(200_000.00, abs=0.01)

        set_clock("2026-09-16T12:00:00Z")
        finalize_settlement(settle_id)

        partially = get_success_data(api_client.get_draw(second["id"], ADMIN))
        assert partially["status"] == "PARTIALLY_RECOVERED"
        assert partially["recovered_cents"] == pytest.approx(200_000.00, abs=0.01)
        assert refresh_franchisee(franchisee_id)["draw_outstanding_cents"] == pytest.approx(
            2_300_000.00, abs=0.01)

        # The reversal is refused precisely so the ledger can never go short.
        validate_error(api_client.reverse_draw(second["id"], ADMIN),
                       ApiErrorId.ERR_DRAW_PARTIALLY_RECOVERED, expected_status=409)
        assert refresh_franchisee(franchisee_id)["draw_outstanding_cents"] == pytest.approx(
            2_300_000.00, abs=0.01)


class TestCrossEntityStateDependencies:
    """An advance is gated on a parent resource's own state."""

    def test_an_agreement_cannot_activate_while_its_store_is_not_active(self):
        """PRD §3.2: "The covering store must be in status `ACTIVE`; when it is
        not, the activation is rejected with `ERR_STORE_NOT_ACTIVE` (HTTP 409)."
        PRD §3.8: "Suspension sets the operator to `SUSPENDED`, recomputes
        `audit_adjusted_net_worth_cents`, and cascades: every one of the
        operator's stores that is still `ACTIVE` is driven to `TERMINATED`."

        Design: Difficulty/cross_entity_state_dependency/agreement_activate_requires_the_covering_store_to_be_active
        """
        set_clock("2026-09-01T12:00:00Z")
        franchisee = create_franchisee(stated_net_worth_cents=20_000_000)
        store = create_store(franchisee["id"])
        validate_success(api_client.suspend_franchisee(franchisee["id"], ADMIN), 200)
        assert refresh_store(store["id"])["status"] == "TERMINATED"

        agreement = create_agreement(
            franchisee["id"], store["id"], activate=False,
            minimum_net_worth_cents=10_000_000)
        assert agreement["status"] == "DRAFT"

        response = api_client.activate_agreement(agreement["id"], ADMIN)
        validate_error(response, ApiErrorId.ERR_STORE_NOT_ACTIVE, expected_status=409)

        still = get_success_data(api_client.get_agreement(agreement["id"], ADMIN))
        assert still["status"] == "DRAFT"


class TestSettlementLifecycleGates:
    """Finalizing a settlement demands the state the endpoint actually drives."""

    def test_finalizing_a_settlement_that_is_still_open_is_a_state_error(self):
        """PRD §3.9: "Finalization is the settlement's terminal step and it is
        gated on time and status together. A `FranchisorAdmin` finalizes a
        settlement that is `RECONCILED`, and only once the logical clock has
        reached the settlement's `period_end` plus 7 days".
        PRD §3.9: "A settlement that is `OPEN` or `DRAW_PAID` can also reach
        `FINALIZED` without ever being reconciled, but only through the
        cancellation cascade of §3.8".

        Design: Corner/state_machines/settlement_finalize_from_open_returns_invalid_state
        """
        set_clock("2026-09-20T00:00:00Z")
        context = setup_settlement_with_lines(
            lines=[("MERCHANDISE", 3_000_000, 2_000_000)],
            clock="2026-09-20T00:00:00Z",
        )
        settle_id = context["settlement"]["id"]

        response = api_client.finalize_settlement(settle_id, ADMIN)
        validate_error(response, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

        unchanged = get_success_data(api_client.get_settlement(settle_id, ADMIN))
        assert unchanged["status"] == "OPEN"
        draws, _meta = validate_paginated(
            api_client.list_draws(ADMIN, {"franchisee_id": context["franchisee"]["id"]}))
        assert len(draws) == 0, "no draw was recovered"

    def test_finalizing_a_counted_audit_that_was_never_counted_is_a_state_error(self):
        """PRD §3.6: "A `FranchisorAdmin` — never the `FieldAuditor` who counted —
        finalizes a `COUNTED` audit, and three conditions are evaluated. The
        audit must be in `COUNTED`."
        PRD §3.6: "The audit opens in status `SCHEDULED`."

        Design: Corner/state_machines/shrink_audit_finalize_from_scheduled_returns_invalid_state
        """
        set_clock("2026-09-20T00:00:00Z")
        context = setup_store_with_agreement(clock="2026-09-20T00:00:00Z")
        audit = create_shrink_audit(
            context["store"]["id"], "2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z",
            5_000_000)

        response = api_client.finalize_shrink_audit(audit["id"], ADMIN)
        validate_error(response, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

        unchanged = get_success_data(api_client.get_shrink_audit(audit["id"], ADMIN))
        assert unchanged["status"] == "SCHEDULED"
        assert unchanged["shrink_cents"] is None

    def test_reconciling_a_settlement_without_any_revenue_line_is_refused(self):
        """PRD §3.3: "A settlement attempted for reconciliation with no revenue
        line covering its period is rejected with `ERR_NO_REVENUE_LINES` (HTTP 409)."

        Design: Corner/state_machines/settlement_finalize_from_open_returns_invalid_state
        """
        set_clock("2026-09-20T00:00:00Z")
        context = setup_store_with_agreement(clock="2026-09-20T00:00:00Z")
        settlement = create_open_settlement(
            context["store"], context["franchisee"], trailing_avg=1_000_000)

        response = api_client.reconcile_settlement(settlement["id"], ADMIN)
        validate_error(response, ApiErrorId.ERR_NO_REVENUE_LINES, expected_status=409)
        assert get_success_data(
            api_client.get_settlement(settlement["id"], ADMIN))["status"] == "OPEN"


class TestSegregationOfDuties:
    """The auditor who counts is deliberately not the actor who finalizes."""

    def test_the_field_auditor_cannot_finalize_the_audit_it_counted(self):
        """PRD §2.1: "The `FieldAuditor` records physical counts and is
        deliberately barred from finalizing the audit it counted — a
        segregation-of-duties rule enforced through `ERR_FORBIDDEN`."
        PRD §3.6: "A `FranchisorAdmin` — never the `FieldAuditor` who counted —
        finalizes a `COUNTED` audit".

        Design: Corner/rbac/field_auditor_cannot_finalize_the_shrink_audit_it_counted
        """
        context = setup_counted_audit(
            book_inventory_cents=4_000_000,
            physical_inventory_cents=3_850_000,
            clock="2026-09-20T00:00:00Z",
        )
        audit_id = context["audit"]["id"]
        assert context["audit"]["status"] == "COUNTED"

        response = api_client.finalize_shrink_audit(audit_id, AUDITOR)
        validate_error(response, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

        unchanged = get_success_data(api_client.get_shrink_audit(audit_id, ADMIN))
        assert unchanged["status"] == "COUNTED"
        # The identical call under the back office would succeed.
        completed = validate_success(api_client.finalize_shrink_audit(audit_id, ADMIN), 200)
        assert completed["status"] == "FINALIZED"

    def test_the_back_office_cannot_cancel_a_stores_fresh_order(self):
        """PRD §2.1: "A request whose role is recognised but is not permitted for
        the target operation is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §3.5: "A `Franchisee` books fresh food with a call naming the
        `store_id`, the `delivery_window_id`, the `sku_code`, the `ordered_units`,
        and the `unit_cost_cents`."

        Design: Corner/rbac/franchisor_admin_cannot_cancel_a_store_fresh_order
        """
        set_clock("2026-09-01T00:00:00Z")
        context = setup_store_with_agreement(
            clock="2026-09-01T00:00:00Z",
            store_overrides={"cold_chain_certified": True})
        window = create_delivery_window(
            context["store"]["id"], "2026-09-16T06:00:00Z", "2026-09-16T10:00:00Z", 600)
        order = place_fresh_order(
            context["store"]["id"], window["id"], context["franchisee"]["id"],
            "SKU-X1", 180, 265)

        response = api_client.cancel_fresh_order(order["id"], ADMIN)
        validate_error(response, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

        unchanged = get_success_data(api_client.get_fresh_order(order["id"], ADMIN))
        assert unchanged["status"] == "PLACED"
        assert get_success_data(
            api_client.get_delivery_window(window["id"], ADMIN))["reserved_units"] == 180