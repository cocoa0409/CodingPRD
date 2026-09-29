"""
Releases that put an aggregate back exactly where it started.

Money and capacity are both held in denormalised aggregates, and every release has to undo
its hold to the last cent and the last kilowatt. These tests release a hold and then prove
the aggregate is not merely close but identical to its pre-hold value.
"""

from test_helpers import (
    UTILITY_REVIEWER_HEADERS,
    ClaimStatus,
    EnrollmentStatus,
    EventStatus,
    PerformanceStatus,
    ProgramType,
    assert_cents,
    assert_ledger_conserved,
    assert_program_ledger,
    assert_quantity,
    factories,
    fixtures,
    get_success_data,
    validate_success,
)

TIGHT_STACK_PROGRAM = dict(
    name="Tight-Stack Municipal Adder",
    program_type=ProgramType.FEDERAL_ADDER,
    total_budget_cents=5000000,
    tier1_limit_kwh=20,
    tier1_rate_cents_per_kwh=10000,
    tier2_rate_cents_per_kwh=5000,
    per_project_cap_cents=500000,
    stack_priority=3,
    max_stack_pct_of_cost_bp=1500,
    requires_export_commitment=False,
    min_capacity_commitment_kw=3.0,
)

WINDOW_CLOSE = "2026-09-15T19:00:00Z"


class TestVoidingAReservation:
    """Voiding returns the cents and drops the claim out of the sibling set."""

    def _voided_then_reserved_again(self, api):
        """A 423000-cent state hold released, then a municipal claim taken out."""
        project = fixtures.installed_project(api)
        state_id = fixtures.create_state_program(api, project)
        tight_id = fixtures.create_federal_program(api, project, **TIGHT_STACK_PROGRAM)

        claim_a = fixtures.reserve_claim(api, project, state_id)
        voided = validate_success(
            api.void_claim(
                claim_a["id"],
                factories.void_payload(reason="Homeowner switched to the municipal adder."),
                headers=project.installer_headers,
            )
        )
        claim_b = fixtures.reserve_claim(
            api, project, tight_id, capacity_commitment_kw=5.0
        )
        return project, state_id, tight_id, voided, claim_b

    def test_voiding_returns_the_whole_hold_to_the_unencumbered_bucket(self, api):
        """The three-bucket ledger comes back to exactly its opening position.

        The reservation had moved 423000 cents out of the unencumbered bucket and into the
        encumbered one. Voiding moves precisely that figure back, so the program is once again
        holding its entire 5000000-cent budget free, with the bucket sum still equal to the
        immutable total.

        PRD 3.7: "Voiding moves the claim `RESERVED → VOID`, takes a `reason` string which is stored in `clawback_reason` as the release audit note, and releases the claim's effective hold from `reserved_budget_cents` back to `remaining_budget_cents`."
        PRD 2.10: "After every single claim transition the following must hold exactly: `total_budget_cents` equals `remaining_budget_cents` plus `reserved_budget_cents` plus `paid_budget_cents`."

        Design: Difficulty/compensating_invariant/voiding_reservation_restores_program_ledger_and_frees_stacking_headroom
        """
        _, state_id, _, voided, _ = self._voided_then_reserved_again(api)

        assert voided["status"] == ClaimStatus.VOID
        state = fixtures.read_program(api, state_id)
        assert_program_ledger(state, remaining=5000000, reserved=0, paid=0)
        assert_ledger_conserved(state)

    def test_the_voided_claim_no_longer_consumes_its_siblings_headroom(self, api):
        """The next claim sees the whole stacking ceiling as headroom.

        Had the 423000-cent hold still counted, the municipal claim would have been truncated
        to the 57000 cents left under the 480000-cent ceiling. Because a voided claim leaves
        the sibling set, the whole 211500-cent schedule award is reserved instead, and the
        municipal pool is encumbered by exactly that figure.

        PRD 3.7: "A voided claim also stops counting toward its siblings' stacking headroom, since `VOID` is one of the statuses excluded from the prior-committed set."
        PRD 3.7: "The amount already committed by siblings is the sum, over every other claim on the same bank whose `status` is not `VOID`, `DENIED` or `CLAWED_BACK`, of that sibling's effective hold — its `final_amount_cents` when written, otherwise its `reserved_amount_cents` — accumulated in ascending program `stack_priority` and then ascending claim `created_at`."

        Design: Difficulty/compensating_invariant/voiding_reservation_restores_program_ledger_and_frees_stacking_headroom
        """
        _, _, tight_id, _, claim_b = self._voided_then_reserved_again(api)

        assert_cents(claim_b, "stack_ceiling_cents", 480000)
        assert_cents(claim_b, "reserved_amount_cents", 211500)
        assert claim_b["reserved_amount_cents"] != 57000
        tight = fixtures.read_program(api, tight_id)
        assert_program_ledger(tight, remaining=4788500, reserved=211500, paid=0)


class TestWithdrawingAnEnrollment:
    """Withdrawal cancels the pending participation and returns its kilowatts."""

    def _withdrawn_before_the_event(self, api):
        """The event's only participant withdraws while the participation is pending."""
        project = fixtures.event_with_participation(api)
        withdrawn = validate_success(
            api.withdraw_enrollment(
                project.enrollment_id,
                factories.withdrawal_payload(reason="Home sold before the season."),
                headers=project.homeowner_headers,
            )
        )
        return project, withdrawn

    def test_withdrawal_returns_the_events_capacity_ledger_to_zero(self, api):
        """The kilowatt ledger is restored to exactly its pre-participation value.

        Calling the battery in had added its 5.0 kW snapshot to the event's committed
        capacity. The household's withdrawal cancels that pending participation and subtracts
        the same snapshot again, leaving the event with nothing committed.

        PRD 3.9: "Withdrawing from `ENROLLED` moves it to `WITHDRAWN` and runs the capacity compensation: every participation of this enrollment still in `PENDING` whose event is still `SCHEDULED` becomes `CANCELLED`, processed in ascending participation `created_at`, and for each one the event's `enrolled_pledged_kw` is reduced by that participation's `pledged_kw_snapshot`, restoring the ledger to its pre-participation value."
        PRD 2.10: "Each `DispatchEvent` maintains `enrolled_pledged_kw`, the sum of `pledged_kw_snapshot` over its participations that are in `PENDING`, `REPORTED` or `SETTLED`."

        Design: Difficulty/compensating_invariant/enrollment_withdrawal_restores_event_pledged_capacity_ledger
        """
        project, withdrawn = self._withdrawn_before_the_event(api)

        assert withdrawn["status"] == EnrollmentStatus.WITHDRAWN
        performance = get_success_data(
            api.get_performance(project.performance_id, headers=UTILITY_REVIEWER_HEADERS)
        )
        assert performance["status"] == PerformanceStatus.CANCELLED
        event = get_success_data(
            api.get_dispatch_event(project.event_id, headers=UTILITY_REVIEWER_HEADERS)
        )
        assert_quantity(event, "enrolled_pledged_kw", 0.0)

    def test_the_emptied_event_settles_paying_nothing(self, api):
        """A cancelled participation is skipped, so the settlement pays out zero.

        The event still settles once its window has closed, but the only participation it ever
        had is cancelled and contributes nothing. The event's payout total is zero and the
        withdrawn enrollment's season accumulators never move.

        PRD 3.9: "Cancelled participations are skipped entirely — they contribute nothing to any accumulator and nothing to the event total."
        PRD 3.9: "an event with no non-cancelled participations settles with a total of zero"

        Design: Difficulty/compensating_invariant/enrollment_withdrawal_restores_event_pledged_capacity_ledger
        """
        project, _ = self._withdrawn_before_the_event(api)
        fixtures.advance_clock(api, project, WINDOW_CLOSE)

        settled = fixtures.settle_event(api, project)

        assert settled["status"] == EventStatus.SETTLED
        assert_cents(settled, "total_net_payment_cents", 0)
        enrollment = get_success_data(
            api.get_enrollment(project.enrollment_id, headers=project.installer_headers)
        )
        assert enrollment["settled_event_count"] == 0
        assert_cents(enrollment, "performance_payment_cents_total", 0)
