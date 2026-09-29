"""Compensating actions that must land exactly where their subject started.

Two reversals run through this domain: voiding a certified charge and posting a
negative credit delta. Neither is allowed to decrement a stored aggregate. Both
rebuild the aggregate from the surviving inputs, so the tests below pin the
before figure, apply the reversal, and pin the after figure against it.
"""

from test_helpers import (
    STOP_CLNA_CERTIFIED,
    STOP_STATE_APPROVED,
    assert_cents,
    assert_cohort_figures,
    assert_credit_hours,
    assert_ledger,
    assert_ledger_identity,
    assert_pct,
    assert_rate,
    assert_version_bumped_by,
    errors,
    f,
    k,
    users,
    validate_error,
    validate_unpaginated,
)

# --- The two-line award the void runs against -------------------------------
CIP_NURSING = "51.3902"
ALLOCATION_CENTS = 5000000

LINE_UNIT_COST_CENTS = 250010
LINE_GROSS_CENTS = 250010
LINE_APPROVED_CENTS = 212509
CONSUMABLE_SHARE = 0.8500

FIRST_TIER_RATE = 0.0812
ADMIN_OBLIGATED_CENTS = 0

DIRECT_TWO_LINES_CENTS = 425018
POOL_TWO_LINES_CENTS = 34511
OBLIGATED_TWO_LINES_CENTS = 459529
REMAINING_TWO_LINES_CENTS = 4540471

DIRECT_ONE_LINE_CENTS = 212509
POOL_ONE_LINE_CENTS = 17256
OBLIGATED_ONE_LINE_CENTS = 229765
REMAINING_ONE_LINE_CENTS = 4770235

EMPTY_LEDGER_CENTS = 0
VOID_REASON = "Order cancelled by the vendor."

FIRST_SERVICE_START = "2026-09-01"
FIRST_SERVICE_END = "2026-09-30"
SECOND_SERVICE_START = "2026-10-01"
SECOND_SERVICE_END = "2026-10-31"

# --- The five-student cohort the credit reversal runs against ----------------
CIP_AGRIBUSINESS = "01.0101"
COHORT_SIZE = 5
COHORT_YEAR = 2026
VERIFIED_COUNT = 1

POSTING_CREDIT_HOURS = 2.0
REVERSAL_CREDIT_DELTA = -2.0
UNDERWATER_CREDIT_DELTA = -0.01
ZERO_CREDIT_HOURS = 0.00

AGREED_LEVEL_PCT = 44.44
MET_THRESHOLD_PCT = 40.00
BASELINE_PCT = 60.00
REPORTING_YEAR = 2027

DENOMINATOR_FULL = 5
DENOMINATOR_NARROWED = 4
NUMERATOR_COUNT = 1
FULL_COHORT_PCT = 20.00
NARROWED_COHORT_PCT = 25.00

REVERSAL_POSTED_ON = "2026-07-16"
UNDERWATER_POSTED_ON = "2026-07-17"
REPOST_POSTED_ON = "2026-07-18"


def _two_certified_lines(build):
    """An award carrying two certified consumable lines of identical gross value."""
    program = build.program(
        CIP_NURSING,
        stop_at=STOP_STATE_APPROVED,
        cluster=k.CLUSTER_HEALTH_SCIENCE,
        title="Practical Nursing",
    )
    grant = build.grant(allocation_cents=ALLOCATION_CENTS)
    first = build.expenditure(
        grant.grant_id,
        program.program_id,
        k.CATEGORY_CONSUMABLE,
        LINE_UNIT_COST_CENTS,
        service_period_start=FIRST_SERVICE_START,
        service_period_end=FIRST_SERVICE_END,
    )
    second = build.expenditure(
        grant.grant_id,
        program.program_id,
        k.CATEGORY_CONSUMABLE,
        LINE_UNIT_COST_CENTS,
        service_period_start=SECOND_SERVICE_START,
        service_period_end=SECOND_SERVICE_END,
    )
    first_certified = build.certify(first["id"])
    second_certified = build.certify(second["id"])
    return {
        "program_id": program.program_id,
        "grant_id": grant.grant_id,
        "first_id": first_certified["id"],
        "second_id": second_certified["id"],
    }


def _full_cohort(build):
    """Five concentrators for one indicator, one of them holding a credential."""
    program = build.program(
        CIP_AGRIBUSINESS,
        stop_at=STOP_CLNA_CERTIFIED,
        cluster=k.CLUSTER_AGRICULTURE,
        title="Agribusiness Systems",
    )
    students = build.cohort(
        program,
        COHORT_SIZE,
        verified_count=VERIFIED_COUNT,
        credit_delta=POSTING_CREDIT_HOURS,
        cohort_year=COHORT_YEAR,
    )
    indicator = build.agreed_indicator(
        program.program_id,
        k.INDICATOR_4S1_CREDENTIAL,
        AGREED_LEVEL_PCT,
        reporting_year=REPORTING_YEAR,
        baseline_pct=BASELINE_PCT,
        cohort_year=COHORT_YEAR,
    )
    return {
        "program_id": program.program_id,
        "course_id": program.secondary_course_id,
        "student_id": students[-1]["id"],
        "indicator_id": indicator["id"],
    }


def _void(api, expenditure_id):
    """Void one charge as the fiscal officer and return the stored row."""
    return validate_unpaginated(
        api.void_expenditure(
            expenditure_id,
            f.void_payload(VOID_REASON),
            users.headers(users.FISCAL_OFFICER),
        )
    )


def _post(api, student_id, course_id, credit_delta, posted_on):
    """Send one credit posting and return the raw response for the caller to read."""
    return api.post_credit(
        student_id,
        f.credit_posting_payload(course_id, credit_delta, posted_on),
        users.headers(users.REGISTRAR),
    )


def _read_grant(api, grant_id):
    return validate_unpaginated(
        api.get_grant(grant_id, users.headers(users.FISCAL_OFFICER))
    )


def _read_expenditure(api, expenditure_id):
    return validate_unpaginated(
        api.get_expenditure(expenditure_id, users.headers(users.FISCAL_OFFICER))
    )


def _read_student(api, student_id):
    return validate_unpaginated(
        api.get_student(student_id, users.headers(users.REGISTRAR))
    )


def _read_indicator(api, indicator_id):
    return validate_unpaginated(
        api.get_indicator(indicator_id, users.headers(users.REVIEWER))
    )


class TestVoidRebuildsTheObligationLedger:
    """A void never decrements the award; it re-sums the lines that survive."""

    def test_each_line_rounds_its_own_federal_share_before_the_ledger_sums_it(self, api, build):
        """PRD §3.7: "The approved amount of a line is its `gross_cents` multiplied by its
        `federal_share_pct`, rounded half-up to whole cents — and that rounding happens **here, once, per
        expenditure line**."
        PRD §3.7: "`EQUIPMENT`, `CONSUMABLE` and `ADMINISTRATION` are each reimbursed at a share of 0.8500."

        Design: Difficulty/compensating_invariant/voiding_recomputes_the_grant_ledger_from_scratch_instead_of_decrementing_it
        """
        state = _two_certified_lines(build)

        line = _read_expenditure(api, state["first_id"])

        assert_cents(line["gross_cents"], LINE_GROSS_CENTS, "gross_cents")
        assert_rate(line["federal_share_pct"], CONSUMABLE_SHARE, "federal_share_pct")
        assert_cents(line["approved_cents"], LINE_APPROVED_CENTS, "approved_cents")

    def test_two_identical_lines_obligate_the_sum_of_two_rounded_shares(self, api, build):
        """PRD §3.7: "Aggregating gross amounts across lines and rounding the product once at the end is
        forbidden: two lines of 250,010 gross cents at a 0.8500 share round to 212,509 cents each for a total
        of 425,018, whereas rounding a combined 500,020 gross at 0.8500 would yield 425,017 — and 425,018 is
        the correct figure."

        Design: Difficulty/compensating_invariant/voiding_recomputes_the_grant_ledger_from_scratch_instead_of_decrementing_it
        """
        state = _two_certified_lines(build)

        grant = _read_grant(api, state["grant_id"])

        assert_cents(
            grant["direct_obligated_cents"], DIRECT_TWO_LINES_CENTS, "direct_obligated_cents"
        )

    def test_the_certified_award_carries_the_first_tier_indirect_pool(self, api, build):
        """PRD §3.7: "Step two selects `indirect_rate` by a tier lookup keyed **only** on that direct total: a
        direct total below 5,000,000 cents (fifty thousand dollars) takes the rate 0.0812; a direct total
        below 20,000,000 cents (two hundred thousand dollars) takes 0.0650; anything at or above 20,000,000
        cents takes 0.0500."
        PRD §3.7: "Step three computes `indirect_pool_cents` as the direct total multiplied by
        `indirect_rate`, rounded half-up to whole cents, computed from scratch rather than incremented against
        its previous value. Step four sets `obligated_cents` to `direct_obligated_cents` plus
        `indirect_pool_cents`. Step five sets `remaining_cents` to `allocation_cents` minus `obligated_cents`."

        Design: Difficulty/compensating_invariant/voiding_recomputes_the_grant_ledger_from_scratch_instead_of_decrementing_it
        """
        state = _two_certified_lines(build)

        grant = _read_grant(api, state["grant_id"])

        assert_ledger(
            grant,
            DIRECT_TWO_LINES_CENTS,
            FIRST_TIER_RATE,
            POOL_TWO_LINES_CENTS,
            OBLIGATED_TWO_LINES_CENTS,
            REMAINING_TWO_LINES_CENTS,
            ADMIN_OBLIGATED_CENTS,
        )

    def test_voiding_nulls_the_approved_amount_so_the_row_leaves_the_roll_up(self, api, build):
        """PRD §3.7: "Voiding is the compensating action and works from either `CERTIFIED → VOIDED` or
        `OBLIGATED → VOIDED`, with no state preconditions beyond being in one of those two statuses. The
        request carries a `void_reason`. The void records that reason, sets `approved_cents` back to null so
        the row can never re-enter the roll-up"

        Design: Difficulty/compensating_invariant/voiding_recomputes_the_grant_ledger_from_scratch_instead_of_decrementing_it
        """
        state = _two_certified_lines(build)

        voided = _void(api, state["first_id"])

        assert voided["status"] == k.EXP_VOIDED
        assert voided["approved_cents"] is None
        assert voided["void_reason"] == VOID_REASON

    def test_the_void_rebuilds_the_ledger_over_the_surviving_line(self, api, build):
        """PRD §3.7: "Step one computes `direct_obligated_cents` as the sum of `approved_cents` over the
        award's expenditures whose `status` is `CERTIFIED` or `OBLIGATED`; `REQUESTED`, `BLOCKED`,
        `DISALLOWED` and `VOIDED` rows are excluded, which is exactly what makes a void an exact
        compensation."

        Design: Difficulty/compensating_invariant/voiding_recomputes_the_grant_ledger_from_scratch_instead_of_decrementing_it
        """
        state = _two_certified_lines(build)

        _void(api, state["first_id"])

        grant = _read_grant(api, state["grant_id"])
        assert_ledger(
            grant,
            DIRECT_ONE_LINE_CENTS,
            FIRST_TIER_RATE,
            POOL_ONE_LINE_CENTS,
            OBLIGATED_ONE_LINE_CENTS,
            REMAINING_ONE_LINE_CENTS,
            ADMIN_OBLIGATED_CENTS,
        )

    def test_the_rebuilt_indirect_pool_is_recomputed_rather_than_decremented(self, api, build):
        """PRD §3.7: "Step three computes `indirect_pool_cents` as the direct total multiplied by
        `indirect_rate`, rounded half-up to whole cents, computed from scratch rather than incremented
        against its previous value."

        Design: Difficulty/compensating_invariant/voiding_recomputes_the_grant_ledger_from_scratch_instead_of_decrementing_it
        """
        state = _two_certified_lines(build)
        before = _read_grant(api, state["grant_id"])
        assert_cents(before["indirect_pool_cents"], POOL_TWO_LINES_CENTS, "indirect_pool_cents")

        _void(api, state["first_id"])

        grant = _read_grant(api, state["grant_id"])
        assert_cents(grant["indirect_pool_cents"], POOL_ONE_LINE_CENTS, "indirect_pool_cents")

    def test_the_void_leaves_the_surviving_line_untouched(self, api, build):
        """PRD §3.7: "Step one computes `direct_obligated_cents` as the sum of `approved_cents` over the
        award's expenditures whose `status` is `CERTIFIED` or `OBLIGATED`; `REQUESTED`, `BLOCKED`,
        `DISALLOWED` and `VOIDED` rows are excluded, which is exactly what makes a void an exact
        compensation."

        Design: Difficulty/compensating_invariant/voiding_recomputes_the_grant_ledger_from_scratch_instead_of_decrementing_it
        """
        state = _two_certified_lines(build)
        before = _read_expenditure(api, state["second_id"])

        _void(api, state["first_id"])

        survivor = _read_expenditure(api, state["second_id"])
        assert survivor["status"] == k.EXP_CERTIFIED
        assert_cents(survivor["approved_cents"], LINE_APPROVED_CENTS, "approved_cents")
        assert_version_bumped_by(
            before["version"], survivor["version"], 0, "surviving expenditure version"
        )

    def test_voiding_both_lines_restores_the_award_to_its_opening_figures(self, api, build):
        """PRD §2.13: "This is what makes voiding a certified expenditure an exact compensation: the ledger is
        rebuilt over the award's remaining countable lines, restoring `remaining_cents` to precisely the
        figure it held before the certification, with no drift from repeated addition and subtraction."
        PRD §3.7: "A new award opens in `status` `OPEN` with `direct_obligated_cents`, `indirect_pool_cents`,
        `obligated_cents` and `admin_obligated_cents` all 0, `remaining_cents` equal to the full
        `allocation_cents`, `indirect_rate` at the tier that applies to a direct total of zero"

        Design: Difficulty/compensating_invariant/voiding_recomputes_the_grant_ledger_from_scratch_instead_of_decrementing_it
        """
        state = _two_certified_lines(build)

        _void(api, state["first_id"])
        _void(api, state["second_id"])

        grant = _read_grant(api, state["grant_id"])
        assert_ledger(
            grant,
            EMPTY_LEDGER_CENTS,
            FIRST_TIER_RATE,
            EMPTY_LEDGER_CENTS,
            EMPTY_LEDGER_CENTS,
            ALLOCATION_CENTS,
            ADMIN_OBLIGATED_CENTS,
        )

    def test_the_void_increments_both_the_charge_and_the_award_version(self, api, build):
        """PRD §3.7: "It then rebuilds the ledger identically to a certification, which restores
        `remaining_cents` to exactly the figure it held before the certification being undone. Both the
        expenditure's and the award's `version` increment."

        Design: Difficulty/compensating_invariant/voiding_recomputes_the_grant_ledger_from_scratch_instead_of_decrementing_it
        """
        state = _two_certified_lines(build)
        charge_before = _read_expenditure(api, state["first_id"])
        award_before = _read_grant(api, state["grant_id"])

        voided = _void(api, state["first_id"])

        award = _read_grant(api, state["grant_id"])
        assert_version_bumped_by(
            charge_before["version"], voided["version"], 1, "expenditure version"
        )
        assert_version_bumped_by(
            award_before["version"], award["version"], 1, "grant award version"
        )

    def test_the_conserved_quantity_survives_every_rebuild(self, api, build):
        """PRD §3.7: "After every rebuild, `allocation_cents` must equal `obligated_cents` plus
        `remaining_cents` exactly — that identity is the conserved quantity of the whole grant model."

        Design: Difficulty/compensating_invariant/voiding_recomputes_the_grant_ledger_from_scratch_instead_of_decrementing_it
        """
        state = _two_certified_lines(build)
        assert_ledger_identity(_read_grant(api, state["grant_id"]))

        _void(api, state["first_id"])
        assert_ledger_identity(_read_grant(api, state["grant_id"]))

        _void(api, state["second_id"])
        grant = _read_grant(api, state["grant_id"])
        assert_ledger_identity(grant)
        assert_cents(grant["allocation_cents"], ALLOCATION_CENTS, "allocation_cents")


class TestCreditReversalRestoresTheCohort:
    """A negative delta unwinds a posting without leaving residue anywhere."""

    def test_a_negative_delta_zeroes_the_students_credit_balance(self, api, build):
        """PRD §3.6: "A `credit_delta` may be negative, and that is precisely how an earlier posting is
        reversed"
        PRD §3.6: "First, `cte_credits_earned` is rebuilt as the sum of `credit_delta` across every accepted
        posting for that student whose target course was in `status` `ACTIVE` at the time of posting, rounded
        half-up to two decimal places."

        Design: Difficulty/compensating_invariant/reversing_a_credit_posting_restores_the_student_and_the_cohort_ledger_exactly
        """
        state = _full_cohort(build)

        student = validate_unpaginated(
            _post(
                api,
                state["student_id"],
                state["course_id"],
                REVERSAL_CREDIT_DELTA,
                REVERSAL_POSTED_ON,
            )
        )

        assert_credit_hours(
            student["cte_credits_earned"], ZERO_CREDIT_HOURS, "cte_credits_earned"
        )

    def test_the_zeroed_balance_demotes_the_student_to_participant(self, api, build):
        """PRD §3.6: "The credit comparison is inclusive — a balance of exactly 2.0 classifies as at least
        `CONCENTRATOR`, while 1.99 does not — and because postings may be negative, the classification can
        move backwards from `CONCENTRATOR` to `PARTICIPANT` just as readily as forwards."

        Design: Difficulty/compensating_invariant/reversing_a_credit_posting_restores_the_student_and_the_cohort_ledger_exactly
        """
        state = _full_cohort(build)
        before = _read_student(api, state["student_id"])
        assert before["concentrator_status"] == k.CONCENTRATOR_CONCENTRATOR

        _post(
            api,
            state["student_id"],
            state["course_id"],
            REVERSAL_CREDIT_DELTA,
            REVERSAL_POSTED_ON,
        )

        student = _read_student(api, state["student_id"])
        assert student["concentrator_status"] == k.CONCENTRATOR_PARTICIPANT

    def test_the_demotion_narrows_the_cohort_ledger_by_exactly_one_member(self, api, build):
        """PRD §3.6: "Every credit posting also propagates into accountability, refreshing
        `denominator_count`, `small_cohort_flag`, `preliminary_actual_pct` and
        `preliminary_status_projection` on each performance indicator of the student's program whose
        `cohort_year` matches, and increments the student's `version`."
        PRD §3.8: "`small_cohort_flag` is true exactly when `denominator_count` is below the federal minimum
        cohort size of 5."

        Design: Difficulty/compensating_invariant/reversing_a_credit_posting_restores_the_student_and_the_cohort_ledger_exactly
        """
        state = _full_cohort(build)
        assert_cohort_figures(
            _read_indicator(api, state["indicator_id"]),
            DENOMINATOR_FULL,
            NUMERATOR_COUNT,
            False,
        )

        _post(
            api,
            state["student_id"],
            state["course_id"],
            REVERSAL_CREDIT_DELTA,
            REVERSAL_POSTED_ON,
        )

        indicator = _read_indicator(api, state["indicator_id"])
        assert_cohort_figures(
            indicator, DENOMINATOR_NARROWED, NUMERATOR_COUNT, True
        )
        assert_pct(
            indicator["preliminary_actual_pct"],
            NARROWED_COHORT_PCT,
            "preliminary_actual_pct",
        )

    def test_a_reversal_that_would_go_under_water_is_refused(self, api, build):
        """PRD §3.6: "but the running balance may never go under water, so a posting whose delta would drive
        `cte_credits_earned` below zero is refused with `ERR_CREDIT_BALANCE_NEGATIVE`."

        Design: Difficulty/compensating_invariant/reversing_a_credit_posting_restores_the_student_and_the_cohort_ledger_exactly
        """
        state = _full_cohort(build)
        _post(
            api,
            state["student_id"],
            state["course_id"],
            REVERSAL_CREDIT_DELTA,
            REVERSAL_POSTED_ON,
        )

        res = _post(
            api,
            state["student_id"],
            state["course_id"],
            UNDERWATER_CREDIT_DELTA,
            UNDERWATER_POSTED_ON,
        )

        validate_error(res, errors.ERR_CREDIT_BALANCE_NEGATIVE)

    def test_the_refused_posting_leaves_no_residue_on_the_student(self, api, build):
        """PRD §3.6: "First, `cte_credits_earned` is rebuilt as the sum of `credit_delta` across every
        accepted posting for that student whose target course was in `status` `ACTIVE` at the time of posting,
        rounded half-up to two decimal places."
        PRD §3.6: "a posting whose delta would drive `cte_credits_earned` below zero is refused with
        `ERR_CREDIT_BALANCE_NEGATIVE`."

        Design: Difficulty/compensating_invariant/reversing_a_credit_posting_restores_the_student_and_the_cohort_ledger_exactly
        """
        state = _full_cohort(build)
        _post(
            api,
            state["student_id"],
            state["course_id"],
            REVERSAL_CREDIT_DELTA,
            REVERSAL_POSTED_ON,
        )
        before = _read_student(api, state["student_id"])

        _post(
            api,
            state["student_id"],
            state["course_id"],
            UNDERWATER_CREDIT_DELTA,
            UNDERWATER_POSTED_ON,
        )

        student = _read_student(api, state["student_id"])
        assert_credit_hours(
            student["cte_credits_earned"], ZERO_CREDIT_HOURS, "cte_credits_earned"
        )
        assert student["concentrator_status"] == k.CONCENTRATOR_PARTICIPANT
        assert_version_bumped_by(
            before["version"], student["version"], 0, "student version"
        )

    def test_reposting_the_credit_restores_the_concentrator_exactly(self, api, build):
        """PRD §3.6: "failing that, the student is a `CONCENTRATOR` when `cte_credits_earned` alone is at
        least 2.0 credit hours; failing that, the student is a `PARTICIPANT`. The credit comparison is
        inclusive — a balance of exactly 2.0 classifies as at least `CONCENTRATOR`, while 1.99 does not"

        Design: Difficulty/compensating_invariant/reversing_a_credit_posting_restores_the_student_and_the_cohort_ledger_exactly
        """
        state = _full_cohort(build)
        _post(
            api,
            state["student_id"],
            state["course_id"],
            REVERSAL_CREDIT_DELTA,
            REVERSAL_POSTED_ON,
        )

        _post(
            api,
            state["student_id"],
            state["course_id"],
            POSTING_CREDIT_HOURS,
            REPOST_POSTED_ON,
        )

        student = _read_student(api, state["student_id"])
        assert_credit_hours(
            student["cte_credits_earned"], POSTING_CREDIT_HOURS, "cte_credits_earned"
        )
        assert student["concentrator_status"] == k.CONCENTRATOR_CONCENTRATOR

    def test_the_restored_concentrator_restores_the_cohort_figures_exactly(self, api, build):
        """PRD §2.13: "Derived aggregates are never accumulated incrementally. The grant ledger, a program's
        three credit subtotals, an educator's verified hours roll-up, a committee's member counts, a
        credential's attainment count and an indicator's numerator and denominator are all recomputed from
        their current inputs whenever an input moves."
        PRD §3.8: "The raw percentage is null when `denominator_count` is zero; otherwise it is 100 multiplied
        by `numerator_count`, divided by `denominator_count`, rounded half-up to two decimal places."

        Design: Difficulty/compensating_invariant/reversing_a_credit_posting_restores_the_student_and_the_cohort_ledger_exactly
        """
        state = _full_cohort(build)
        _post(
            api,
            state["student_id"],
            state["course_id"],
            REVERSAL_CREDIT_DELTA,
            REVERSAL_POSTED_ON,
        )

        _post(
            api,
            state["student_id"],
            state["course_id"],
            POSTING_CREDIT_HOURS,
            REPOST_POSTED_ON,
        )

        indicator = _read_indicator(api, state["indicator_id"])
        assert_cohort_figures(indicator, DENOMINATOR_FULL, NUMERATOR_COUNT, False)
        assert_pct(
            indicator["preliminary_actual_pct"], FULL_COHORT_PCT, "preliminary_actual_pct"
        )
        assert_pct(indicator["met_threshold_pct"], MET_THRESHOLD_PCT, "met_threshold_pct")
