"""The billing dimension: draft, submit, review, resubmit, void, pay."""
from test_helpers import (
    ApiErrorId, TEST_USERS, complete_prepared_span, current_version, draft_billing_line,
    pay_line, read_line, read_plan, read_span, resubmit_line, review_line, set_clock,
    setup_completed_span, setup_completed_span_with_draft_line,
    setup_completed_span_with_submitted_line, submit_line,
    validate_error, validate_paginated, validate_success,
)

ANALYST = TEST_USERS["analyst_headers"]
FORESTER = TEST_USERS["forester_headers"]


class TestParallelStatusDimensions:
    """execution_status stays frozen at COMPLETED while billing_status walks its cycle."""

    def test_billing_status_walks_its_cycle_without_moving_execution_status(self, api):
        """PRD §3.9: "That transition is the single hand-off between the two dimensions;
        nothing in the billing dimension ever moves the execution dimension back."
        PRD §3.3: "These two status dimensions are independent: field execution and invoicing
        evolve on the same record without either driving the other except at the single
        hand-off point described in §3.9."

        Design: Difficulty/non_linear_state_machine/work_order_execution_and_billing_dimensions_advance_independently
        """
        world = setup_completed_span()
        span_id = world["span"]["id"]
        assert read_span(span_id)["billing_status"] == "BILLABLE"

        line = draft_billing_line(span_id, "UNIT_PRICE")
        assert read_span(span_id)["billing_status"] == "LINE_DRAFTED"
        submit_line(line["id"])
        assert read_span(span_id)["billing_status"] == "SUBMITTED"
        review_line(line["id"], "DISPUTE", "unit count challenged")
        assert read_span(span_id)["billing_status"] == "DISPUTED"
        resubmit_line(line["id"])
        assert read_span(span_id)["billing_status"] == "SUBMITTED"
        review_line(line["id"], "APPROVE")
        assert read_span(span_id)["billing_status"] == "APPROVED"
        paid = pay_line(line["id"])

        assert paid["status"] == "PAID"
        assert read_span(span_id)["billing_status"] == "SETTLED"
        assert read_span(span_id)["execution_status"] == "COMPLETED", \
            "the execution dimension never moved during the billing walk"

    def test_dispute_and_resubmit_move_the_committed_ledger_down_and_back_up(self, api):
        """PRD §3.9: "An `outcome` of `DISPUTE` moves the line `SUBMITTED → DISPUTED` and the
        span's `billing_status` `SUBMITTED → DISPUTED`, and it removes the line from the plan's
        committed set, so `committed_cents` is recomputed downward."
        PRD §3.9: "The `BillingAnalyst` resubmits it unchanged, moving it
        `DISPUTED → SUBMITTED`, resetting `submitted_at` to the current logical clock — which
        restarts the 30-day dispute window — and re-entering it into the committed set so
        `committed_cents` is recomputed upward, subject once more to the budget ceiling."

        Design: Difficulty/non_linear_state_machine/work_order_execution_and_billing_dimensions_advance_independently
        """
        world = setup_completed_span_with_submitted_line()
        plan_id, line_id = world["plan"]["id"], world["line"]["id"]

        review_line(line_id, "DISPUTE", "unit count challenged")
        assert read_plan(plan_id)["committed_cents"] == 0, \
            "a DISPUTED line leaves the committed set"

        resubmit_line(line_id)

        assert read_plan(plan_id)["committed_cents"] == 820800
        assert read_line(line_id)["status"] == "SUBMITTED"
        assert read_span(world["span"]["id"])["execution_status"] == "COMPLETED"


class TestRejectionOrderOnBillingWrites:

    @staticmethod
    def _plan_with_disputed_and_submitted_lines():
        world = setup_completed_span(
            budget_cents=900_000,
            extra_spans=[{"span_miles": 2.5, "billing_method": "UNIT_PRICE",
                          "planned_unit_count": 200}])
        line_a = draft_billing_line(world["span"]["id"], "UNIT_PRICE")
        submit_line(line_a["id"])
        review_line(line_a["id"], "DISPUTE", "unit count challenged")
        second = complete_prepared_span(world["extra_spans"][0]["id"], world["crew"]["id"])
        line_b = draft_billing_line(second["span"]["id"], "UNIT_PRICE")
        submit_line(line_b["id"])
        world["line_a"] = line_a
        world["line_b"] = line_b
        return world

    def test_submit_from_disputed_reports_the_state_failure_not_the_budget_failure(self, api):
        """PRD §2.9: "10. The target resource is in a state from which the requested transition
        is declared — `ERR_INVALID_STATE` (409). This applies to every transition endpoint."
        PRD §3.9: "Submitting a drafted line is the analyst's request for payment. It requires
        the line to be at `DRAFT` and the owning span to be at `COMPLETED`, and it enforces the
        budget ceiling: the plan's `committed_cents`, recomputed with this line included, must
        not exceed the plan's `budget_cents`."

        Design: Difficulty/priority_pair_validation_conflict/invalid_state_precedes_budget_exceeded_on_billing_submit
        """
        world = self._plan_with_disputed_and_submitted_lines()

        resp = api.submit_billing_line(world["line_a"]["id"], ANALYST)

        error = validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
        assert resp.status_code == 409
        assert error["error_id"] != ApiErrorId.ERR_BUDGET_EXCEEDED.value

    def test_the_rejected_submit_leaves_the_line_and_the_ledger_untouched(self, api):
        """PRD §2.9: "When a request violates more than one rule, exactly one error is
        returned, and which one is not a matter of implementation convenience."
        PRD §3.9: "It is the exact integer sum of `final_payable_cents` across every billing
        line belonging to any span of the plan whose `status` is `DRAFT`, `SUBMITTED`,
        `APPROVED` or `PAID`, regardless of what `execution_status` those spans are in."

        Design: Difficulty/priority_pair_validation_conflict/invalid_state_precedes_budget_exceeded_on_billing_submit
        """
        world = self._plan_with_disputed_and_submitted_lines()

        api.submit_billing_line(world["line_a"]["id"], ANALYST)

        assert read_line(world["line_a"]["id"])["status"] == "DISPUTED"
        assert read_plan(world["plan"]["id"])["committed_cents"] == 820800, \
            "only the SUBMITTED line counts toward the plan's committed spend"

    def test_billing_method_mismatch_is_reported_before_the_supersession_check(self, api):
        """PRD §3.9: "The line's `billing_method` must equal the span's own `billing_method`; a
        `UNIT_PRICE` line on a `TIME_AND_MATERIALS` span, or the reverse, is rejected with
        `ERR_BILLING_METHOD_MISMATCH` (HTTP 422), and that check is evaluated before the
        supersession check below."

        Design: Difficulty/priority_pair_validation_conflict/billing_method_mismatch_precedes_not_supersedable_on_line_draft
        """
        world = setup_completed_span_with_submitted_line()
        span_id = world["span"]["id"]

        version = current_version(span_id)
        resp = api.create_billing_line(
            span_id,
            {"billing_method": "TIME_AND_MATERIALS", "expected_work_order_version": version},
            ANALYST)

        error = validate_error(resp, ApiErrorId.ERR_BILLING_METHOD_MISMATCH.value)
        assert resp.status_code == 422
        assert error["error_id"] != ApiErrorId.ERR_BILLING_LINE_NOT_SUPERSEDABLE.value
        assert read_line(world["line"]["id"])["status"] == "SUBMITTED"
        assert read_plan(world["plan"]["id"])["committed_cents"] == 820800

    def test_matching_method_on_a_submitted_span_reports_the_supersession_failure(self, api):
        """PRD §3.9: "A new draft may supersede an earlier `DRAFT` line on the same span, but
        only a `DRAFT` line: if any line on the span is in `SUBMITTED`, `APPROVED` or `PAID`,
        the new draft is rejected with `ERR_BILLING_LINE_NOT_SUPERSEDABLE` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/billing_method_mismatch_precedes_not_supersedable_on_line_draft
        """
        world = setup_completed_span_with_submitted_line()
        span_id = world["span"]["id"]

        version = current_version(span_id)
        resp = api.create_billing_line(
            span_id,
            {"billing_method": "UNIT_PRICE", "expected_work_order_version": version}, ANALYST)

        validate_error(resp, ApiErrorId.ERR_BILLING_LINE_NOT_SUPERSEDABLE.value)
        assert resp.status_code == 409
        assert read_line(world["line"]["id"])["status"] == "SUBMITTED"


class TestCommittedCentsConservation:

    def test_voiding_a_draft_returns_committed_cents_to_its_pre_line_value(self, api):
        """PRD §3.9: "A voided line leaves the committed set, and `committed_cents` returns to
        precisely the value it held before the line existed — the cents conservation
        invariant."
        PRD §2.10: "The second is committed cents: a plan's `committed_cents` is always the
        exact integer sum of `final_payable_cents` over the billing lines of its spans that are
        in `DRAFT`, `SUBMITTED`, `APPROVED` or `PAID`, so voiding a line returns the plan's
        committed total to precisely the value it held before that line existed."

        Design: Difficulty/compensating_invariant/billing_line_draft_then_void_conserves_plan_committed_cents
        """
        world = setup_completed_span()
        plan_id = world["plan"]["id"]
        assert read_plan(plan_id)["committed_cents"] == 0

        line = draft_billing_line(world["span"]["id"], "UNIT_PRICE")
        assert read_plan(plan_id)["committed_cents"] == 820800

        voided = validate_success(
            api.void_billing_line(line["id"], ANALYST, {"reason": "re-measure required"}), 200)

        assert voided["status"] == "VOID"
        assert read_plan(plan_id)["committed_cents"] == 0

    def test_voiding_the_last_line_drops_the_span_back_to_billable(self, api):
        """PRD §3.9: "If no non-`VOID` line remains on the span afterwards, the span's
        `billing_status` falls back to `BILLABLE`."
        PRD §3.9: "Voiding is available to the analyst from `DRAFT` or `DISPUTED`, optionally
        with a `reason`, and it is also what the plan-cancellation cascade and a superseding
        draft perform."

        Design: Difficulty/compensating_invariant/billing_line_draft_then_void_conserves_plan_committed_cents
        """
        world = setup_completed_span_with_draft_line()

        api.void_billing_line(world["line"]["id"], ANALYST, {"reason": "re-measure required"})

        span = read_span(world["span"]["id"])
        assert span["billing_status"] == "BILLABLE"
        assert span["execution_status"] == "COMPLETED"


class TestBillingTerminalStatesAndGuards:

    def test_paying_an_already_paid_line_is_rejected_as_terminal(self, api):
        """PRD §2.9: "11. The target resource is not already sitting in one of its terminal
        states — `ERR_ALREADY_TERMINAL` (409). This too applies to every transition endpoint."
        PRD §3.9: "`PAID` and `VOID` are the line's terminal states, and `SETTLED` is terminal
        on the span's billing dimension."

        Design: Corner/state_machines/corner_billing_line_pay_twice_returns_already_terminal
        """
        world = setup_completed_span_with_submitted_line()
        line_id = world["line"]["id"]
        review_line(line_id, "APPROVE")
        pay_line(line_id)

        resp = api.pay_billing_line(line_id, FORESTER)

        validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL.value)
        assert resp.status_code == 409
        assert read_line(line_id)["status"] == "PAID"
        assert read_span(world["span"]["id"])["billing_status"] == "SETTLED"
        assert read_plan(world["plan"]["id"])["committed_cents"] == 820800

    def test_dispute_after_the_thirty_day_window_is_rejected(self, api):
        """PRD §3.9: "Disputing is time-limited: the logical clock may be at most 30 calendar
        days after the line's `submitted_at`, and a later dispute is rejected with
        `ERR_DISPUTE_WINDOW_EXPIRED` (HTTP 422)."
        PRD §2.6: "Before any client sets it, the clock reads exactly `2026-08-01T00:00:00Z`;
        it never falls back to real time."

        Design: Corner/validations/corner_dispute_after_thirty_days_is_rejected
        """
        world = setup_completed_span_with_submitted_line()
        line_id = world["line"]["id"]
        set_clock("2026-09-01T00:00:00Z")

        resp = api.review_billing_line(
            line_id, {"outcome": "DISPUTE", "dispute_reason": "late challenge"}, FORESTER)

        validate_error(resp, ApiErrorId.ERR_DISPUTE_WINDOW_EXPIRED.value)
        assert resp.status_code == 422
        line = read_line(line_id)
        assert line["status"] == "SUBMITTED"
        assert line["submitted_at"] == "2026-08-01T00:00:00.000Z"
        assert read_plan(world["plan"]["id"])["committed_cents"] == 820800

    def test_stale_span_version_blocks_the_draft_and_the_fresh_version_succeeds(self, api):
        """PRD §2.8: "A `POST /vm/work-orders/{id}/billing-lines` request must carry
        `expected_work_order_version`, holding the client's last observed `version` of the span
        named in the path. If the span's current `version` differs — because production was
        filed, a refusal was finalized, or an earlier draft was created since the client read
        it — the request is rejected with `ERR_STALE_WORK_ORDER_VERSION` (HTTP 412)."
        PRD §3.9: "Drafting is permitted while the span's `billing_status` is `BILLABLE`,
        `LINE_DRAFTED` or `DISPUTED`, and it leaves that status at `LINE_DRAFTED` and
        increments the span's `version` by 1."

        Design: Corner/cross_cutting_complexity_layers/corner_stale_work_order_version_on_billing_line_returns_412
        """
        world = setup_completed_span()
        span_id = world["span"]["id"]
        version = current_version(span_id)

        stale = api.create_billing_line(
            span_id,
            {"billing_method": "UNIT_PRICE", "expected_work_order_version": version - 1},
            ANALYST)
        validate_error(stale, ApiErrorId.ERR_STALE_WORK_ORDER_VERSION.value)
        assert stale.status_code == 412

        fresh = api.create_billing_line(
            span_id,
            {"billing_method": "UNIT_PRICE", "expected_work_order_version": version}, ANALYST)
        line = validate_success(fresh, 201)

        assert line["final_payable_cents"] == 820800
        span = read_span(span_id)
        assert span["version"] == version + 1
        assert span["billing_status"] == "LINE_DRAFTED"
        _, meta = validate_paginated(
            api.list_billing_lines(ANALYST, params={"work_order_id": span_id}))
        assert meta["total_count"] == 1, "the rejected draft must not have been persisted"

    def test_billing_analyst_may_not_review_the_line_it_submitted(self, api):
        """PRD §3.9: "Review belongs to the utility, and never to the analyst that drafted or
        submitted the line — a `BillingAnalyst` cannot approve its own work, and only a
        `UtilityForester` may review, approve or pay."
        PRD §2.1: "If both headers are well formed but the named role is not among the roles
        authorized for the endpoint being called, the request is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/corner_billing_analyst_cannot_review_a_submitted_line
        """
        world = setup_completed_span_with_submitted_line()
        line_id = world["line"]["id"]

        resp = api.review_billing_line(line_id, {"outcome": "APPROVE"}, ANALYST)

        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)
        assert resp.status_code == 403
        assert read_line(line_id)["status"] == "SUBMITTED"

        approved = validate_success(
            api.review_billing_line(line_id, {"outcome": "APPROVE"}, FORESTER), 200)
        assert approved["status"] == "APPROVED"
