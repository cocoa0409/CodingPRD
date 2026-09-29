"""
The two independent application dimensions and the rating floor on approval.

Determination and disbursement move separately, the pool follows the
disbursement dimension, and the rating floor reads the veteran's live rating.
"""

import pytest
from test_helpers import (
    CLOCK_START_INSTANT,
    STATE_AUDITOR_HEADERS,
    SYSTEM_ADMIN_HEADERS,
    add_decided_claim_to_context,
    approve_application_action,
    assert_cents,
    assert_combined_rating,
    claw_back_action,
    conditions,
    create_approved_application,
    create_rated_veteran,
    create_state_program,
    file_benefit_application,
    issue_application,
    read_application,
    read_state_program,
    read_veteran,
    set_clock,
    validate_error,
    validate_success,
)

TUITION_PROGRAM = {
    "program_type": "TUITION_WAIVER",
    "fiscal_year": 2026,
    "annual_pool_cents": 990000,
    "min_rating_pct": 0,
    "max_award_cents": 100000000,
}


@pytest.fixture
def issued_then_clawed_back(api):
    """A twelve-credit tuition waiver that was issued and then recovered."""
    set_clock(api, CLOCK_START_INSTANT)
    ctx = create_approved_application(
        api,
        program_kwargs=dict(TUITION_PROGRAM),
        application_kwargs={"tuition_credits_requested": 12},
        awarded_rating_pct=30,
    )
    ctx["issued"] = issue_application(api, ctx["application"]["id"], "2026-08-01")
    ctx["clawed_back"] = validate_success(
        api.application_disbursement(
            ctx["application"]["id"],
            claw_back_action("Enrolment was cancelled by the school"),
            SYSTEM_ADMIN_HEADERS,
        )
    )
    return ctx


@pytest.fixture
def clawback_then_second_award(api):
    """
    One program, two veterans: the first award is recovered and the second is
    approved afterwards against the freed pool.
    """
    set_clock(api, CLOCK_START_INSTANT)
    first = create_approved_application(
        api,
        program_kwargs=dict(TUITION_PROGRAM),
        application_kwargs={"tuition_credits_requested": 12},
        awarded_rating_pct=30,
    )
    program = first["program"]
    allocated_after_first = read_state_program(api, program["id"])["allocated_cents"]
    validate_success(
        api.application_disbursement(
            first["application"]["id"],
            claw_back_action("Duplicate payment discovered in the county ledger"),
            SYSTEM_ADMIN_HEADERS,
        )
    )
    allocated_after_clawback = read_state_program(api, program["id"])["allocated_cents"]

    second_veteran = create_rated_veteran(
        api, awarded_rating_pct=30, claimed_conditions=conditions("tinnitus")
    )
    second_application = file_benefit_application(
        api,
        second_veteran["veteran"]["id"],
        program,
        tuition_credits_requested=10,
        expected_program_version=read_state_program(api, program["id"])["version"],
    )
    second_application = validate_success(
        api.application_determination(
            second_application["id"], approve_application_action(), STATE_AUDITOR_HEADERS
        )
    )
    return {
        "first": first,
        "second": second_application,
        "program_id": program["id"],
        "allocated_after_first": allocated_after_first,
        "allocated_after_clawback": allocated_after_clawback,
    }


@pytest.fixture
def rating_gated_application(api):
    """A submitted tuition waiver whose program floor is above the veteran's rating."""
    set_clock(api, CLOCK_START_INSTANT)
    ctx = create_rated_veteran(api, awarded_rating_pct=30)
    program_kwargs = dict(TUITION_PROGRAM)
    program_kwargs["min_rating_pct"] = 50
    ctx["program"] = create_state_program(api, **program_kwargs)
    ctx["application"] = file_benefit_application(
        api, ctx["veteran"]["id"], ctx["program"], tuition_credits_requested=12
    )
    return ctx


class TestDisbursementDimensionMovesAlone:
    """Recovering money leaves the adjudication where it was."""

    def test_issuing_moves_only_the_disbursement_dimension(
        self, api, issued_then_clawed_back
    ):
        """
        Issuing "sets `disbursement_status` to `ISSUED` and `issued_on`, leaves `determination_status` untouched, and leaves the program's `allocated_cents` unchanged".

        Design: Difficulty/non_linear_state_machine/benefit_application_disbursement_dimension_moves_without_determination_dimension
        """
        issued = issued_then_clawed_back["issued"]
        assert issued["disbursement_status"] == "ISSUED"
        assert issued["issued_on"] == "2026-08-01"
        assert issued["determination_status"] == "APPROVED"
        assert_cents(issued["benefit_amount_cents"], 540000)

    def test_an_operator_clawback_leaves_the_determination_approved(
        self, api, issued_then_clawed_back
    ):
        """
        "Crucially, an operator claw-back **leaves `determination_status` at `APPROVED`**, because an operator recovery is not a re-adjudication."

        Design: Difficulty/non_linear_state_machine/benefit_application_disbursement_dimension_moves_without_determination_dimension
        """
        application = read_application(
            api, issued_then_clawed_back["application"]["id"]
        )
        assert application["disbursement_status"] == "CLAWED_BACK"
        assert application["determination_status"] == "APPROVED"
        assert application["determination_reason"] is None

    def test_the_clawback_reverses_the_pool_commitment(self, api, issued_then_clawed_back):
        """
        Clawing back "decreases the program's `allocated_cents` by `benefit_amount_cents`, exactly reversing the approval commitment".

        Design: Difficulty/non_linear_state_machine/benefit_application_disbursement_dimension_moves_without_determination_dimension
        """
        program = read_state_program(api, issued_then_clawed_back["program"]["id"])
        assert_cents(program["allocated_cents"], 0)
        assert_cents(program["annual_pool_cents"], 990000)


class TestClawbackFreesThePoolForTheNextAward:
    """The ledger is exactly the sum of the awards still committed to it."""

    def test_the_recovered_award_leaves_the_ledger_at_zero(
        self, api, clawback_then_second_award
    ):
        """
        "Applications whose disbursement dimension reads `NOT_APPLICABLE` — never approved, or denied — and applications that have been `CLAWED_BACK` are excluded."

        Design: Difficulty/compensating_invariant/clawback_returns_program_allocation_to_zero_so_the_next_approval_allocates_exactly_its_own_award
        """
        assert_cents(clawback_then_second_award["allocated_after_first"], 540000)
        assert_cents(clawback_then_second_award["allocated_after_clawback"], 0)

    def test_the_next_approval_allocates_exactly_its_own_award(
        self, api, clawback_then_second_award
    ):
        """
        "A state program's `allocated_cents` equals the sum of `benefit_amount_cents` over every state benefit application referencing that program whose `disbursement_status` is either `PENDING` or `ISSUED`."

        Design: Difficulty/compensating_invariant/clawback_returns_program_allocation_to_zero_so_the_next_approval_allocates_exactly_its_own_award
        """
        second = clawback_then_second_award["second"]
        assert_cents(second["benefit_amount_cents"], 450000)
        assert second["determination_status"] == "APPROVED"
        assert second["disbursement_status"] == "PENDING"
        program = read_state_program(api, clawback_then_second_award["program_id"])
        assert_cents(program["allocated_cents"], 450000)

    def test_the_recovered_application_keeps_its_own_figures(
        self, api, clawback_then_second_award
    ):
        """
        The recovered row still records what was adjudicated, since
        "every claw-back, whether operator-driven or triggered by a rating cascade, lowers it by exactly the same figure".

        Design: Difficulty/compensating_invariant/clawback_returns_program_allocation_to_zero_so_the_next_approval_allocates_exactly_its_own_award
        """
        application = read_application(
            api, clawback_then_second_award["first"]["application"]["id"]
        )
        assert application["determination_status"] == "APPROVED"
        assert application["disbursement_status"] == "CLAWED_BACK"
        assert_cents(application["benefit_amount_cents"], 540000)


class TestRatingFloorUnblockedByASecondDecision:
    """The floor is read against the rating the veteran holds at that instant."""

    def test_a_rating_below_the_program_floor_refuses_approval(
        self, api, rating_gated_application
    ):
        """
        "the veteran's `combined_rating_pct` must be at least the program's `min_rating_pct`, else `ERR_PROGRAM_MIN_RATING_NOT_MET`".

        Design: Difficulty/cross_entity_state_dependency/benefit_approval_unblocked_only_after_a_second_decision_lifts_the_veteran_combined_rating
        """
        veteran = read_veteran(api, rating_gated_application["veteran"]["id"])
        assert_combined_rating(veteran["combined_rating_pct"], 30)
        response = api.application_determination(
            rating_gated_application["application"]["id"],
            approve_application_action(),
            STATE_AUDITOR_HEADERS,
        )
        validate_error(response, "ERR_PROGRAM_MIN_RATING_NOT_MET", 409)
        application = read_application(api, rating_gated_application["application"]["id"])
        assert application["determination_status"] == "SUBMITTED"

    def test_a_second_grant_lifts_the_combined_rating_above_the_floor(
        self, api, rating_gated_application
    ):
        """
        "Two 50-percent ratings therefore combine to 75 before rounding and 80 after, never 100."
        A seventy on top of a thirty combines to seventy-nine and rounds to eighty.

        Design: Difficulty/cross_entity_state_dependency/benefit_approval_unblocked_only_after_a_second_decision_lifts_the_veteran_combined_rating
        """
        add_decided_claim_to_context(
            api,
            rating_gated_application,
            decision_outcome="GRANTED",
            awarded_rating_pct=70,
            claimed_conditions=conditions("lumbar_strain"),
        )
        veteran = read_veteran(api, rating_gated_application["veteran"]["id"])
        assert_combined_rating(veteran["combined_rating_pct"], 80)

    def test_the_same_application_is_approved_once_the_rating_rises(
        self, api, rating_gated_application
    ):
        """
        Nothing about the application changed, only the veteran, because
        approval "freezes `rating_at_approval_pct` at the veteran's `combined_rating_pct` as of that instant".

        Design: Difficulty/cross_entity_state_dependency/benefit_approval_unblocked_only_after_a_second_decision_lifts_the_veteran_combined_rating
        """
        validate_error(
            api.application_determination(
                rating_gated_application["application"]["id"],
                approve_application_action(),
                STATE_AUDITOR_HEADERS,
            ),
            "ERR_PROGRAM_MIN_RATING_NOT_MET",
            409,
        )
        add_decided_claim_to_context(
            api,
            rating_gated_application,
            decision_outcome="GRANTED",
            awarded_rating_pct=70,
            claimed_conditions=conditions("lumbar_strain"),
        )
        approved = validate_success(
            api.application_determination(
                rating_gated_application["application"]["id"],
                approve_application_action(),
                STATE_AUDITOR_HEADERS,
            )
        )
        assert approved["determination_status"] == "APPROVED"
        assert_cents(approved["benefit_amount_cents"], 540000)
        program = read_state_program(api, rating_gated_application["program"]["id"])
        assert_cents(program["allocated_cents"], 540000)
