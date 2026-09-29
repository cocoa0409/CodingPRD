"""
The award waterfall, the administration fee band and the program pool guard.

Every fixture here builds a rated veteran first, because the exemption rate and
the program's rating floor both read the veteran's combined rating.
"""

import pytest
from test_helpers import (
    CLOCK_START_INSTANT,
    STATE_AUDITOR_HEADERS,
    approve_application_action,
    assert_cents,
    assert_exact_whole,
    create_approved_application,
    create_rated_veteran,
    create_state_program,
    create_submitted_application,
    file_benefit_application,
    read_application,
    read_state_program,
    set_clock,
    validate_error,
    validate_success,
)


@pytest.fixture
def property_exemption_award(api):
    """An approved property-tax exemption for a seventy-percent-rated veteran."""
    set_clock(api, CLOCK_START_INSTANT)
    return create_approved_application(
        api,
        program_kwargs={
            "program_type": "PROPERTY_TAX_EXEMPTION",
            "fiscal_year": 2026,
            "annual_pool_cents": 100000000,
            "min_rating_pct": 0,
            "max_award_cents": 100000000,
        },
        application_kwargs={"assessed_property_value_cents": 8500000},
        awarded_rating_pct=70,
    )


@pytest.fixture
def pool_boundary_pair(api):
    """
    One rated veteran with two tuition programs: one pool exactly the size of
    the award, one pool a single cent short.
    """
    set_clock(api, CLOCK_START_INSTANT)
    ctx = create_rated_veteran(api, awarded_rating_pct=30)
    exact = create_state_program(
        api,
        program_type="TUITION_WAIVER",
        fiscal_year=2026,
        annual_pool_cents=990000,
        min_rating_pct=0,
        max_award_cents=100000000,
    )
    short = create_state_program(
        api,
        program_type="TUITION_WAIVER",
        fiscal_year=2026,
        annual_pool_cents=989999,
        min_rating_pct=0,
        max_award_cents=100000000,
    )
    app_exact = file_benefit_application(
        api, ctx["veteran"]["id"], exact, tuition_credits_requested=22
    )
    app_short = file_benefit_application(
        api, ctx["veteran"]["id"], short, tuition_credits_requested=22
    )
    return {
        "exact": exact,
        "short": short,
        "app_exact": app_exact,
        "app_short": app_short,
    }


@pytest.fixture
def already_allocated_application(api):
    """An approved tuition waiver whose program pool is exactly full."""
    set_clock(api, CLOCK_START_INSTANT)
    ctx = create_submitted_application(
        api,
        program_kwargs={
            "program_type": "TUITION_WAIVER",
            "fiscal_year": 2026,
            "annual_pool_cents": 540000,
            "min_rating_pct": 0,
            "max_award_cents": 100000000,
        },
        application_kwargs={"tuition_credits_requested": 12},
        awarded_rating_pct=30,
    )
    ctx["application"] = validate_success(
        api.application_determination(
            ctx["application"]["id"], approve_application_action(), STATE_AUDITOR_HEADERS
        )
    )
    return ctx


class TestAdminFeeBandKeyedOnGross:
    """The fee band reads the gross award, so the net is 4998000 and not 5049000."""

    def test_the_gross_award_uses_the_seventy_percent_exemption_rate(
        self, api, property_exemption_award
    ):
        """
        "**First**, read the exemption rate from the veteran's `combined_rating_pct`, taking the first band that matches from the top: a rating of 100 or more gives 1.00, at least 70 gives 0.60"
        and the product is rounded half-up to whole cents.

        Design: Difficulty/combinatorial_formula/state_benefit_admin_fee_band_keyed_on_gross_not_net
        """
        application = property_exemption_award["application"]
        assert_cents(application["gross_award_cents"], 5100000)
        assert_exact_whole(
            application["rating_at_approval_pct"], 70, "rating_at_approval_pct"
        )

    def test_the_fee_band_is_selected_on_the_gross_figure(
        self, api, property_exemption_award
    ):
        """
        "**Third**, select the administration fee band **on the gross award and never on the net**: a gross of at least 5000000 cents attracts 0.02, at least 2000000 cents attracts 0.01, and anything lower attracts 0.00."

        Design: Difficulty/combinatorial_formula/state_benefit_admin_fee_band_keyed_on_gross_not_net
        """
        application = property_exemption_award["application"]
        assert_cents(application["admin_fee_cents"], 102000)
        assert application["admin_fee_cents"] != 51000

    def test_the_net_award_is_the_gross_less_the_fee(self, api, property_exemption_award):
        """
        "**Fifth**, `benefit_amount_cents` is `gross_award_cents` minus `admin_fee_cents`, and it is that net figure — not the gross — that is charged against the pool."
        A fee band keyed on the net would have paid 5049000 instead.

        Design: Difficulty/combinatorial_formula/state_benefit_admin_fee_band_keyed_on_gross_not_net
        """
        application = read_application(
            api, property_exemption_award["application"]["id"]
        )
        assert_cents(application["benefit_amount_cents"], 4998000)
        assert application["benefit_amount_cents"] != 5049000
        assert application["determination_status"] == "APPROVED"
        assert application["disbursement_status"] == "PENDING"

    def test_the_pool_is_charged_the_net_award(self, api, property_exemption_award):
        """
        Approval "increases the program's `allocated_cents` by `benefit_amount_cents`", and
        "Comparison is exact integer cents."

        Design: Difficulty/combinatorial_formula/state_benefit_admin_fee_band_keyed_on_gross_not_net
        """
        program = read_state_program(api, property_exemption_award["program"]["id"])
        assert_cents(program["allocated_cents"], 4998000)


class TestPoolGuardToTheCent:
    """A pool that exactly fits the award is accepted; one cent short is not."""

    def test_an_approval_that_exactly_fills_the_pool_succeeds(
        self, api, pool_boundary_pair
    ):
        """
        The guard "must be at most `annual_pool_cents`, else `ERR_PROGRAM_POOL_EXHAUSTED` — the comparison is inclusive, so an allocation that exactly fills the pool is accepted and the next cent is not".

        Design: Difficulty/boundary_precision_check/approval_filling_program_pool_to_the_cent_succeeds_while_one_cent_short_is_rejected
        """
        approved = validate_success(
            api.application_determination(
                pool_boundary_pair["app_exact"]["id"],
                approve_application_action(),
                STATE_AUDITOR_HEADERS,
            )
        )
        assert approved["determination_status"] == "APPROVED"
        assert_cents(approved["benefit_amount_cents"], 990000)
        assert_cents(approved["admin_fee_cents"], 0)
        program = read_state_program(api, pool_boundary_pair["exact"]["id"])
        assert_cents(program["allocated_cents"], 990000)

    def test_a_pool_one_cent_short_refuses_the_same_award(self, api, pool_boundary_pair):
        """
        The same twenty-two credits are computed the same way — "multiply `tuition_credits_requested` by the unit credit cost of 45000 cents" —
        so only the pool differs.

        Design: Difficulty/boundary_precision_check/approval_filling_program_pool_to_the_cent_succeeds_while_one_cent_short_is_rejected
        """
        response = api.application_determination(
            pool_boundary_pair["app_short"]["id"],
            approve_application_action(),
            STATE_AUDITOR_HEADERS,
        )
        validate_error(response, "ERR_PROGRAM_POOL_EXHAUSTED", 409)

    def test_the_refused_application_and_its_pool_are_untouched(
        self, api, pool_boundary_pair
    ):
        """
        Nothing is committed on refusal, and the ledger only counts applications
        "whose `disbursement_status` is either `PENDING` or `ISSUED`".

        Design: Difficulty/boundary_precision_check/approval_filling_program_pool_to_the_cent_succeeds_while_one_cent_short_is_rejected
        """
        api.application_determination(
            pool_boundary_pair["app_short"]["id"],
            approve_application_action(),
            STATE_AUDITOR_HEADERS,
        )
        application = read_application(api, pool_boundary_pair["app_short"]["id"])
        assert application["determination_status"] == "SUBMITTED"
        program = read_state_program(api, pool_boundary_pair["short"]["id"])
        assert_cents(program["allocated_cents"], 0)


class TestReapprovalPrecedence:
    """Re-approving an allocated application is a state error, not a pool error."""

    def test_the_second_approval_is_refused_as_an_invalid_transition(
        self, api, already_allocated_application
    ):
        """
        "**Approving** (`APPROVE`) requires `determination_status` to be `SUBMITTED`",
        and an action applied from any other from-state "is refused with `ERR_INVALID_STATE_TRANSITION` (409)".

        Design: Difficulty/priority_pair_validation_conflict/reapprove_allocated_application_returns_invalid_state_not_pool_exhausted
        """
        response = api.application_determination(
            already_allocated_application["application"]["id"],
            approve_application_action(),
            STATE_AUDITOR_HEADERS,
        )
        validate_error(response, "ERR_INVALID_STATE_TRANSITION", 409)

    def test_the_pool_error_never_surfaces_even_though_the_pool_is_full(
        self, api, already_allocated_application
    ):
        """
        The fiscal guard sits in "**Band 9 — fiscal capacity, evaluated last.**",
        behind the state precondition, so a full pool cannot be reported here.

        Design: Difficulty/priority_pair_validation_conflict/reapprove_allocated_application_returns_invalid_state_not_pool_exhausted
        """
        program = read_state_program(api, already_allocated_application["program"]["id"])
        assert_cents(program["allocated_cents"], 540000)
        assert_cents(program["annual_pool_cents"], 540000)
        error = validate_error(
            api.application_determination(
                already_allocated_application["application"]["id"],
                approve_application_action(),
                STATE_AUDITOR_HEADERS,
            ),
            "ERR_INVALID_STATE_TRANSITION",
            409,
        )
        assert error["error_id"] != "ERR_PROGRAM_POOL_EXHAUSTED"

    def test_the_refusal_leaves_the_award_and_the_ledger_alone(
        self, api, already_allocated_application
    ):
        """
        The approval that did land is the only commitment, because
        "Approving an application raises `allocated_cents` by exactly that application's `benefit_amount_cents`".

        Design: Difficulty/priority_pair_validation_conflict/reapprove_allocated_application_returns_invalid_state_not_pool_exhausted
        """
        api.application_determination(
            already_allocated_application["application"]["id"],
            approve_application_action(),
            STATE_AUDITOR_HEADERS,
        )
        application = read_application(
            api, already_allocated_application["application"]["id"]
        )
        assert application["determination_status"] == "APPROVED"
        assert_cents(application["benefit_amount_cents"], 540000)
        program = read_state_program(api, already_allocated_application["program"]["id"])
        assert_cents(program["allocated_cents"], 540000)
