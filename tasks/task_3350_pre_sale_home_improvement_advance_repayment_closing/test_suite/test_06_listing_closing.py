"""Listing events, payoff basis, closing-statement fee math, and settlement."""
from test_helpers import (
    TEST_USERS,
    api_client,
    create_dispute,
    create_listing_event,
    get_case,
    get_closing_statement,
    make_listing_agent_headers,
    set_clock,
    setup_closed_sold_case,
    setup_closed_unsold_case,
    setup_listed_case,
    setup_ready_to_list_case,
    validate_error,
    validate_success,
)
from test_helpers import ApiErrorId as ERR

UNDERWRITER = TEST_USERS["program_underwriter_headers"]
HOMEOWNER = TEST_USERS["homeowner_headers"]


def _finalize(statement_id):
    resp = api_client.finalize_closing_statement(statement_id, UNDERWRITER)
    return validate_success(resp)


class TestProgramFeeVariantA:
    """Sold within the listing window: single 3% fee on the advance principal."""

    def test_variant_a_payoff_basis_and_program_fee(self, api):
        """PRD §3.8: "a sold case is `SOLD_WITHIN_WINDOW` when the number of days
        between `listed_at` and the closing event is fewer than
        `listing_window_days`"
        PRD §3.8: "the `program_fee_cents` is the `advance_repayment_cents`
        multiplied by 0.03, rounded half-up to a whole cent: a single 3 percent
        fee on the advance principal."

        Design: Difficulty/dual_variant_calc/program_fee_variant_a_sold_within_window
        """
        ctx = setup_closed_sold_case(
            listed_at="2026-09-10T00:00:00Z", offer_at="2026-10-01T00:00:00Z",
            closed_at="2026-10-15T00:00:00Z",
        )
        stmt = _finalize(ctx["statement"]["id"])
        assert stmt["payoff_basis"] == "SOLD_WITHIN_WINDOW"
        assert stmt["advance_repayment_cents"] == 5_000_000
        # round_half_up(5000000 * 0.03) = 150000
        assert stmt["program_fee_cents"] == 150_000

    def test_variant_a_net_repayment_composition(self, api):
        """PRD §3.8: "under variant A the `late_fee_cents` is 0."
        PRD §3.8: "Finally the `net_repayment_cents` is the
        `advance_repayment_cents` plus the `program_fee_cents` plus the
        `late_fee_cents` minus the `vendor_holdback_cents`."

        Design: Difficulty/dual_variant_calc/program_fee_variant_a_sold_within_window
        """
        ctx = setup_closed_sold_case(
            listed_at="2026-09-10T00:00:00Z", offer_at="2026-10-01T00:00:00Z",
            closed_at="2026-10-15T00:00:00Z",
        )
        stmt = _finalize(ctx["statement"]["id"])
        assert stmt["late_fee_cents"] == 0
        assert stmt["vendor_holdback_cents"] == 0
        # 5000000 + 150000 + 0 - 0
        assert stmt["net_repayment_cents"] == 5_150_000


class TestNetRepaymentCircularEvaluationOrder:
    """Variant B with two released disbursements: principal is summed from the
    ledger first, then the basis, then fee lines, then the net."""

    def test_variant_b_fee_lines_with_two_released_disbursements(self, api):
        """PRD §3.8: "Its `advance_repayment_cents` is the total advance
        principal being repaid: the sum of the `amount_cents` of every
        disbursement on the case in `RELEASED` status."
        PRD §3.8: "the `program_fee_cents` is the sum of two lines, each rounded
        half-up to a whole cent before summing: the `advance_repayment_cents`
        multiplied by 0.01, a reduced 1 percent base fee, plus the
        `advance_repayment_cents` multiplied by 0.005 per month late, a 0.5
        percent monthly accrual."

        Design: Difficulty/combinatorial_formula/net_repayment_circular_evaluation_order
        """
        ctx = setup_closed_unsold_case(
            listing_window_days=30, listed_at="2026-09-01T00:00:00Z",
            closed_at="2026-10-15T00:00:00Z",
            disb_amounts=[3_000_000, 2_000_000],
        )
        stmt = _finalize(ctx["statement"]["id"])
        assert stmt["advance_repayment_cents"] == 5_000_000
        assert stmt["payoff_basis"] == "NOT_LISTED_WITHIN_WINDOW"
        # months_late = ceil((44 - 30) / 30) = 1
        # fee = round(5000000*0.01) + round(5000000*0.005*1) = 50000 + 25000
        assert stmt["program_fee_cents"] == 75_000

    def test_variant_b_late_fee_and_net_repayment(self, api):
        """PRD §3.8: "The `late_fee_cents` applies only under variant B: it is
        the `advance_repayment_cents` multiplied by 0.002 per month late, rounded
        half-up to a whole cent, with the months-late figure computed the same
        way"
        PRD §3.8: "Finally the `net_repayment_cents` is the
        `advance_repayment_cents` plus the `program_fee_cents` plus the
        `late_fee_cents` minus the `vendor_holdback_cents`."

        Design: Difficulty/combinatorial_formula/net_repayment_circular_evaluation_order
        """
        ctx = setup_closed_unsold_case(
            listing_window_days=30, listed_at="2026-09-01T00:00:00Z",
            closed_at="2026-10-15T00:00:00Z",
            disb_amounts=[3_000_000, 2_000_000],
        )
        stmt = _finalize(ctx["statement"]["id"])
        # late fee = round(5000000 * 0.002 * 1) = 10000
        assert stmt["late_fee_cents"] == 10_000
        assert stmt["vendor_holdback_cents"] == 0
        # 5000000 + 75000 + 10000 - 0
        assert stmt["net_repayment_cents"] == 5_085_000


class TestClosingStatementBranching:
    def test_finalize_then_waive_on_unsold_with_market_risk(self, api):
        """PRD §3.8: "a `ProgramUnderwriter` may waive the fees, moving a
        `FINALIZED` statement to `WAIVED`, but only when the case is
        `CLOSED_UNSOLD` and the most recent listing event recorded before
        `closed_at` carries a `market_risk_flag` of true"
        PRD §3.8: "Waiving adjusts the `net_repayment_cents` to the
        `advance_repayment_cents` only, so that just the advance principal is
        owed."

        Design: Difficulty/non_linear_state_machine/closing_statement_draft_finalized_paid_waived_branching
        """
        ctx = setup_closed_unsold_case(
            listing_window_days=30, listed_at="2026-09-01T00:00:00Z",
            closed_at="2026-10-15T00:00:00Z", market_risk=True,
        )
        stmt = _finalize(ctx["statement"]["id"])
        assert stmt["status"] == "FINALIZED"
        resp = api_client.waive_closing_statement(stmt["id"], UNDERWRITER)
        waived = validate_success(resp)
        assert waived["status"] == "WAIVED"
        assert waived["net_repayment_cents"] == 5_000_000

    def test_finalize_then_pay_on_sold_case(self, api):
        """PRD §3.8: "The homeowner records payment, moving a `FINALIZED`
        statement to `PAID`, which requires the case to be `CLOSED_SOLD` or
        `CLOSED_UNSOLD`."

        Design: Difficulty/non_linear_state_machine/closing_statement_draft_finalized_paid_waived_branching
        """
        ctx = setup_closed_sold_case()
        stmt = _finalize(ctx["statement"]["id"])
        resp = api_client.pay_closing_statement(stmt["id"], HOMEOWNER)
        paid = validate_success(resp)
        assert paid["status"] == "PAID"


class TestListingWindowBoundary:
    """Days between listed_at and event_at vs listing_window_days (30)."""

    def test_closed_unsold_at_exactly_the_window_succeeds(self, api):
        """PRD §3.7: "A `CLOSED_UNSOLD` event moves the case from `LISTED` to
        `CLOSED_UNSOLD`, but only once the listing window has elapsed: the number
        of days between the case's `listed_at` and the event's `event_at` must be
        at least `listing_window_days`, failing otherwise with
        `ERR_LISTING_WINDOW_NOT_ELAPSED`"

        Design: Difficulty/boundary_precision_check/listing_window_days_boundary
        """
        ctx = setup_listed_case(
            listing_window_days=30, listed_at="2026-09-01T00:00:00Z"
        )
        set_clock("2026-10-01T00:00:00Z")
        resp = api_client.create_listing_event(
            ctx["case"]["id"],
            {"event_kind": "CLOSED_UNSOLD", "event_at": "2026-10-01T00:00:00Z"},
            make_listing_agent_headers(ctx["agent"]["id"]),
        )
        validate_success(resp, expected_status=201)
        # Exactly 30 days: the window has elapsed.
        assert get_case(ctx["case"]["id"])["status"] == "CLOSED_UNSOLD"

    def test_closed_unsold_one_day_before_the_window_fails(self, api):
        """PRD §3.7: "the number of days between the case's `listed_at` and the
        event's `event_at` must be at least `listing_window_days`, failing
        otherwise with `ERR_LISTING_WINDOW_NOT_ELAPSED`"

        Design: Difficulty/boundary_precision_check/listing_window_days_boundary
        """
        ctx = setup_listed_case(
            listing_window_days=30, listed_at="2026-09-01T00:00:00Z"
        )
        set_clock("2026-09-30T00:00:00Z")
        resp = api_client.create_listing_event(
            ctx["case"]["id"],
            {"event_kind": "CLOSED_UNSOLD", "event_at": "2026-09-30T00:00:00Z"},
            make_listing_agent_headers(ctx["agent"]["id"]),
        )
        # 29 days < 30: one day short.
        validate_error(resp, ERR.ERR_LISTING_WINDOW_NOT_ELAPSED)


class TestListingEventSequence:
    def test_duplicate_listed_event_rejected(self, api):
        """PRD §3.7: "only one `LISTED` event may exist for a case, and a second
        attempt is rejected with `ERR_DUPLICATE_LISTED_EVENT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/listing_event_sequence_closed_interval
        """
        ctx = setup_listed_case(listed_at="2026-09-01T00:00:00Z")
        resp = api_client.create_listing_event(
            ctx["case"]["id"],
            {"event_kind": "LISTED", "event_at": "2026-09-02T00:00:00Z",
             "price_cents": 104_000_000},
            make_listing_agent_headers(ctx["agent"]["id"]),
        )
        validate_error(resp, ERR.ERR_DUPLICATE_LISTED_EVENT)

    def test_closed_sold_before_offer_accepted_rejected(self, api):
        """PRD §3.7: "Listing events must respect a monotonic sequence — `LISTED`
        before `OFFER_ACCEPTED` before `CLOSED_SOLD` — and an out-of-order event
        is rejected with `ERR_LISTING_EVENT_ORDER`."

        Design: Difficulty/resource_temporal_overlap/listing_event_sequence_closed_interval
        """
        ctx = setup_listed_case(listed_at="2026-09-01T00:00:00Z")
        resp = api_client.create_listing_event(
            ctx["case"]["id"],
            {"event_kind": "CLOSED_SOLD", "event_at": "2026-09-15T00:00:00Z",
             "price_cents": 105_000_000},
            make_listing_agent_headers(ctx["agent"]["id"]),
        )
        validate_error(resp, ERR.ERR_LISTING_EVENT_ORDER)

    def test_price_reduced_recorded_without_case_transition(self, api):
        """PRD §3.7: "`PRICE_REDUCED` and `DELISTED` events are recorded without
        driving a case transition."

        Design: Corner/endpoints/listing_event_records_price_reduced
        """
        ctx = setup_listed_case(listed_at="2026-09-01T00:00:00Z")
        resp = api_client.create_listing_event(
            ctx["case"]["id"],
            {"event_kind": "PRICE_REDUCED", "event_at": "2026-09-10T00:00:00Z",
             "price_cents": 100_000_000},
            make_listing_agent_headers(ctx["agent"]["id"]),
        )
        event = validate_success(resp, expected_status=201)
        assert event["event_kind"] == "PRICE_REDUCED"
        assert get_case(ctx["case"]["id"])["status"] == "LISTED"


class TestProgramFeeVariantB:
    def test_variant_b_not_listed_within_window_fee_breakdown(self, api):
        """PRD §3.8: "an unsold case, which can only close after the window has
        elapsed, is `NOT_LISTED_WITHIN_WINDOW`."
        PRD §3.8: "the `program_fee_cents` is the sum of two lines, each rounded
        half-up to a whole cent before summing: the `advance_repayment_cents`
        multiplied by 0.01, a reduced 1 percent base fee, plus the
        `advance_repayment_cents` multiplied by 0.005 per month late, a 0.5
        percent monthly accrual."
        PRD §3.8: "The `late_fee_cents` applies only under variant B"

        Design: Corner/calculations/program_fee_variant_b_not_listed_within_window
        """
        ctx = setup_closed_unsold_case(
            listing_window_days=30, listed_at="2026-09-01T00:00:00Z",
            closed_at="2026-10-15T00:00:00Z",
        )
        stmt = _finalize(ctx["statement"]["id"])
        assert stmt["payoff_basis"] == "NOT_LISTED_WITHIN_WINDOW"
        # months_late = ceil((44 - 30) / 30) = 1
        assert stmt["program_fee_cents"] == 75_000
        assert stmt["late_fee_cents"] == 10_000


class TestClosingStatementReadAndFinalize:
    def test_closing_statement_computed_read_after_finalize(self, api):
        """PRD §3.8: "Finalization by a `ProgramUnderwriter` moves the statement
        from `DRAFT` to `FINALIZED` and computes the money."
        PRD §3.8: "Finally the `net_repayment_cents` is the
        `advance_repayment_cents` plus the `program_fee_cents` plus the
        `late_fee_cents` minus the `vendor_holdback_cents`."

        Design: Corner/endpoints/closing_statement_computed_read_after_finalize
        """
        ctx = setup_closed_sold_case(
            listed_at="2026-09-01T00:00:00Z", offer_at="2026-09-10T00:00:00Z",
            closed_at="2026-09-15T00:00:00Z",
        )
        _finalize(ctx["statement"]["id"])
        stmt = validate_success(
            api_client.get_closing_statement(ctx["case"]["id"], TEST_USERS["any_headers"])
        )
        assert stmt["status"] == "FINALIZED"
        # 14 days < 180 -> SOLD_WITHIN_WINDOW -> 5000000 + 150000 + 0 - 0
        assert stmt["net_repayment_cents"] == 5_150_000

    def test_finalize_blocked_by_non_terminal_dispute(self, api):
        """PRD §3.8: "Every dispute on the case must be in a terminal status —
        finalizing while any dispute is still open or in review is rejected with
        `ERR_DISPUTE_NOT_TERMINAL`."

        Design: Corner/validations/closing_statement_finalize_blocked_by_non_terminal_dispute
        """
        ctx = setup_closed_sold_case()
        dispute = create_dispute(
            ctx["case"]["id"], ctx["project"]["id"], ctx["engagement"]["id"]
        )
        api_client.review_dispute(dispute["id"], UNDERWRITER)
        resp = api_client.finalize_closing_statement(
            ctx["statement"]["id"], UNDERWRITER
        )
        validate_error(resp, ERR.ERR_DISPUTE_NOT_TERMINAL)


class TestReadinessToList:
    def test_case_ready_to_list_when_all_projects_verified(self, api):
        """PRD §3.6: "When every project on a case has reached `VERIFIED` or
        `CANCELLED` and no dispute on the case is `OPEN` or `IN_REVIEW`, the case
        advances automatically from `IN_PROGRESS` to `READY_TO_LIST`."
        PRD §3.6: "verification, performed by the `ListingAgent`, moves a project
        from `COMPLETE` to `VERIFIED` only when no such dispute exists."

        Design: Corner/state_machines/case_auto_transitions_to_ready_to_list_when_all_projects_verified
        """
        ctx = setup_ready_to_list_case()
        assert ctx["project"]["status"] == "VERIFIED"
        assert ctx["case"]["status"] == "READY_TO_LIST"
