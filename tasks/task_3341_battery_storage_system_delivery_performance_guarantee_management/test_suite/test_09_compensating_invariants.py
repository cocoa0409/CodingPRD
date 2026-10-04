"""Compensating invariant tests: the credit pool and the LD ledger return to
exact parity after draw/cancel and accrue/waive sequences."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_credit_pool_invariant,
    assert_ld_ledger_invariant,
    create_milestone,
    create_order,
    create_project,
    get_success_data,
    record_milestone_outcome,
    setup_active_ltsa,
    setup_executed_project,
    validate_error,
    validate_success,
)

DEV = TEST_USERS["project_developer_headers"]
SVC_MGR = TEST_USERS["service_manager_headers"]


class TestCreditPoolConservation:
    def test_draw_then_cancel_returns_pool_to_parity(self, api):
        """PRD §3.7: "The pool is a conserved quantity: it always equals the
        drawn amount plus what remains available, and cancelling a covered
        order subtracts its cost back out of `credit_drawn_cents`, returning
        the books to parity."
        PRD §3.7: "cancelling a covered order restores its draw as above."

        Design: Difficulty/compensating_invariant/credit_pool_conserved_through_draw_and_cancel
        """
        project = create_project(api=api)
        ltsa = setup_active_ltsa(project["id"], api=api, annual_fee_cents=2_000_000)
        assert ltsa["credit_pool_cents"] == 600000
        assert ltsa["credit_drawn_cents"] == 0

        order = create_order(
            ltsa["id"], api=api, part_description="Inverter fan",
            part_cost_cents=200000,
        )
        assert order["covered_by_credit"] is True
        mid = get_success_data(api.get_service_agreement(ltsa["id"], SVC_MGR))
        assert mid["credit_drawn_cents"] == 200000
        assert_credit_pool_invariant(mid)

        cancelled = validate_success(api.cancel_order(order["id"], SVC_MGR))
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["covered_by_credit"] is True
        after = get_success_data(api.get_service_agreement(ltsa["id"], SVC_MGR))
        assert after["credit_drawn_cents"] == 0, (
            "draw+cancel returns the ledger to exact parity"
        )
        assert after["credit_pool_cents"] == 600000
        assert_credit_pool_invariant(after)

    def test_multiple_draws_and_one_cancel_conserve_the_pool(self, api):
        """PRD §3.7: "The pool is a conserved quantity: it always equals the
        drawn amount plus what remains available, and cancelling a covered
        order subtracts its cost back out of `credit_drawn_cents`, returning
        the books to parity."

        Design: Difficulty/compensating_invariant/credit_pool_conserved_through_draw_and_cancel
        """
        project = create_project(api=api)
        ltsa = setup_active_ltsa(project["id"], api=api, annual_fee_cents=2_000_000)

        o1 = create_order(ltsa["id"], api=api, part_description="A", part_cost_cents=100000)
        o2 = create_order(ltsa["id"], api=api, part_description="B", part_cost_cents=150000)
        mid = get_success_data(api.get_service_agreement(ltsa["id"], SVC_MGR))
        assert mid["credit_drawn_cents"] == 250000
        assert_credit_pool_invariant(mid)

        validate_success(api.cancel_order(o1["id"], SVC_MGR))
        after = get_success_data(api.get_service_agreement(ltsa["id"], SVC_MGR))
        assert after["credit_drawn_cents"] == 150000, (
            "only the cancelled order's cost is subtracted back"
        )
        assert_credit_pool_invariant(after)


class TestLdLedgerConservation:
    def _setup_with_accrual(self, api):
        project, esa = setup_executed_project(
            api=api,
            esa_overrides={"ld_rate_per_day_cents": 40000, "ld_cap_cents": 1200000},
        )
        m1 = create_milestone(esa["id"], "DELIVERY", "2026-10-01T00:00:00Z", api=api)
        record_milestone_outcome(m1["id"], "MISSED", "2026-10-21T00:00:00Z", api=api)
        return project, esa

    def test_waiver_capped_at_outstanding_and_full_waiver_zeroes_net(self, api):
        """PRD §3.3: "the developer may waive accrued damages on a non-`DRAFT`
        agreement by supplying an `amount_cents`; the waiver must not exceed
        accrued minus already-waived, or the request fails with
        `ERR_WAIVER_EXCEEDS_ACCRUED`. Partial waivers are allowed, each adding
        to `waived_ld_cents` and recomputing `net_ld_due_cents`."
        PRD §3.3: "That amount is added to the agreement's `accrued_ld_cents`,
        and `net_ld_due_cents` is recomputed as accrued minus waived."

        Design: Difficulty/compensating_invariant/ld_ledger_conserved_through_accrue_and_waive
        """
        _, esa = self._setup_with_accrual(api)

        resp = api.waive_ld(esa["id"], {"amount_cents": 800001}, DEV)
        validate_error(resp, ApiErrorId.ERR_WAIVER_EXCEEDS_ACCRUED)

        waived = validate_success(api.waive_ld(esa["id"], {"amount_cents": 800000}, DEV))
        assert waived["accrued_ld_cents"] == 800000
        assert waived["waived_ld_cents"] == 800000
        assert waived["net_ld_due_cents"] == 0, (
            "net == accrued - waived holds exactly after a full waiver"
        )
        assert waived["status"] == "EXECUTED", (
            "800000 < cap 1200000 -> no termination; waiver changes no lifecycle state"
        )
        assert_ld_ledger_invariant(waived)

    def test_partial_waivers_accumulate_and_second_overdraw_fails(self, api):
        """PRD §3.3: "Partial waivers are allowed, each adding to
        `waived_ld_cents` and recomputing `net_ld_due_cents`."
        PRD §3.3: "the waiver must not exceed accrued minus already-waived, or
        the request fails with `ERR_WAIVER_EXCEEDS_ACCRUED`."

        Design: Difficulty/compensating_invariant/ld_ledger_conserved_through_accrue_and_waive
        """
        _, esa = self._setup_with_accrual(api)

        first = validate_success(api.waive_ld(esa["id"], {"amount_cents": 300000}, DEV))
        assert first["waived_ld_cents"] == 300000
        assert first["net_ld_due_cents"] == 500000
        assert_ld_ledger_invariant(first)

        # outstanding is now 500000; waiving 500001 must fail.
        resp = api.waive_ld(esa["id"], {"amount_cents": 500001}, DEV)
        validate_error(resp, ApiErrorId.ERR_WAIVER_EXCEEDS_ACCRUED)

        second = validate_success(api.waive_ld(esa["id"], {"amount_cents": 500000}, DEV))
        assert second["waived_ld_cents"] == 800000
        assert second["net_ld_due_cents"] == 0
        assert_ld_ledger_invariant(second)
