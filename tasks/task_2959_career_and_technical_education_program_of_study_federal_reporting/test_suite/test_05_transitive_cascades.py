"""Cascade chains that reach four records deep from a single call.

Two chains run through this domain in opposite directions, and a third is driven
by recomputation rather than by state transitions. Each test below asserts one
link on the record that link actually lands on, so that a chain which stops
early is diagnosed at the link that failed to fire rather than at its far end.
"""

from test_helpers import (
    STOP_DRAFT,
    STOP_STATE_APPROVED,
    assert_cents,
    assert_cohort_figures,
    assert_credit_hours,
    assert_instant_equals,
    assert_pct,
    assert_version_bumped_by,
    f,
    k,
    users,
    validate_unpaginated,
)

# --- The approved-program scenario the sanction chain runs on ---------------
CIP_MAINTENANCE = "47.0303"
ALLOCATION_CENTS = 5000000
CONSUMABLE_UNIT_COST_CENTS = 100000

REPORTING_YEAR = 2027
COHORT_YEAR = 2026
BASELINE_PCT = 60.00
AGREED_LEVEL_PCT = 90.00
MET_THRESHOLD_PCT = 81.00
COHORT_ACTUAL_PCT = 40.00

FIRST_CLOSED_ON = "2027-09-30"
SECOND_CLOSED_ON = "2028-09-30"

PLAN_MILESTONE_DUE_DATES = ("2028-01-31", "2028-03-31", "2028-05-31")

# --- The draft-program scenario the recomputation chain runs on -------------
CIP_AGRIBUSINESS = "01.0101"
SECONDARY_COURSE_CODE = "AGB-1"
SECONDARY_CREDIT_HOURS = 4.0
CREDENTIAL_CODE = "AGB-CRT"
POSTING_CREDIT_HOURS = 2.0
FIRST_STATE_STUDENT_NUMBER = 100000001
FIFTH_STATE_STUDENT_ID = "100000005"

SMALL_AGREED_LEVEL_PCT = 44.44
SMALL_MET_THRESHOLD_PCT = 40.00
ACTUAL_PCT_BEFORE_FLIP = 25.00
ACTUAL_PCT_AFTER_FLIP = 20.00
DENOMINATOR_BEFORE_FLIP = 4
DENOMINATOR_AFTER_FLIP = 5
NUMERATOR_COUNT = 1

FLIP_POSTED_ON = "2026-07-16"


def _sanction_setup(build, with_certified_line: bool = False):
    """A state-approved program with a cohort, an award and an agreed indicator.

    The cohort is five students holding two credit hours each, two of them with a
    verified attainment, which fixes the raw performance figure at 40.00 against
    a negotiated level of 90.00.
    """
    program = build.program(
        CIP_MAINTENANCE,
        stop_at=STOP_STATE_APPROVED,
        cluster=k.CLUSTER_ADVANCED_MANUFACTURING,
        title="Industrial Maintenance",
    )
    build.cohort(
        program,
        5,
        verified_count=2,
        credit_delta=POSTING_CREDIT_HOURS,
        cohort_year=COHORT_YEAR,
    )
    grant = build.grant(fiscal_year=REPORTING_YEAR, allocation_cents=ALLOCATION_CENTS)
    requested = build.expenditure(
        grant.grant_id,
        program.program_id,
        k.CATEGORY_CONSUMABLE,
        CONSUMABLE_UNIT_COST_CENTS,
    )
    certified_id = None
    if with_certified_line:
        second = build.expenditure(
            grant.grant_id,
            program.program_id,
            k.CATEGORY_CONSUMABLE,
            CONSUMABLE_UNIT_COST_CENTS,
            service_period_start="2026-11-01",
            service_period_end="2026-11-30",
        )
        certified_id = build.certify(second["id"])["id"]
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
        "grant_id": grant.grant_id,
        "requested_expenditure_id": requested["id"],
        "certified_expenditure_id": certified_id,
        "indicator_id": indicator["id"],
    }


def _recovery_setup(build):
    """The suspended end state of the downward chain, plus a submitted plan."""
    state = _sanction_setup(build)
    build.miss_twice(
        state["indicator_id"],
        first_closed_on=FIRST_CLOSED_ON,
        second_closed_on=SECOND_CLOSED_ON,
    )
    plan = build.draft_plan(
        state["indicator_id"],
        milestones=f.three_milestones(due_dates=PLAN_MILESTONE_DUE_DATES),
    )
    build.submit_plan(plan["id"])
    state["plan_id"] = plan["id"]
    return state


def _cohort_flip_setup(build):
    """Four concentrators, one participant, and an indicator over that cohort."""
    program = build.program(
        CIP_AGRIBUSINESS,
        stop_at=STOP_DRAFT,
        cluster=k.CLUSTER_AGRICULTURE,
        title="Agribusiness Systems",
    )
    course = build.add_course(
        program.program_id,
        f.secondary_course(
            SECONDARY_COURSE_CODE, 1, SECONDARY_CREDIT_HOURS, status=k.COURSE_ACTIVE
        ),
    )
    credential = build.add_credential(
        program.program_id, CREDENTIAL_CODE, tier=k.TIER_NATIONAL, exam_required=False
    )
    concentrators = []
    for index in range(DENOMINATOR_BEFORE_FLIP):
        student = build.enroll(
            program.program_id,
            str(FIRST_STATE_STUDENT_NUMBER + index),
            cohort_year=COHORT_YEAR,
        )
        student = build.post_credit(student["id"], course["id"], POSTING_CREDIT_HOURS)
        concentrators.append(student)
    build.attain(concentrators[0]["id"], credential["id"], exam_score=f.UNSET)
    participant = build.enroll(
        program.program_id, FIFTH_STATE_STUDENT_ID, cohort_year=COHORT_YEAR
    )
    indicator = build.agreed_indicator(
        program.program_id,
        k.INDICATOR_4S1_CREDENTIAL,
        SMALL_AGREED_LEVEL_PCT,
        reporting_year=REPORTING_YEAR,
        baseline_pct=BASELINE_PCT,
        cohort_year=COHORT_YEAR,
    )
    return {
        "program_id": program.program_id,
        "course_id": course["id"],
        "participant_id": participant["id"],
        "indicator_id": indicator["id"],
    }


def _close_year(api, indicator_id, closed_on):
    """Close one reporting year as the state and return the indicator row."""
    return validate_unpaginated(
        api.close_reporting_year(
            indicator_id, f.close_year_payload(closed_on), users.headers(users.REVIEWER)
        )
    )


def _read_program(api, program_id):
    return validate_unpaginated(
        api.get_program(program_id, users.headers(users.DIRECTOR))
    )


def _read_indicator(api, indicator_id):
    return validate_unpaginated(
        api.get_indicator(indicator_id, users.headers(users.REVIEWER))
    )


def _read_expenditure(api, expenditure_id):
    return validate_unpaginated(
        api.get_expenditure(expenditure_id, users.headers(users.FISCAL_OFFICER))
    )


def _read_grant(api, grant_id):
    return validate_unpaginated(
        api.get_grant(grant_id, users.headers(users.FISCAL_OFFICER))
    )


class TestSanctionCascadeFromYearClose:
    """The downward chain: miss count, escalation, suspension, blocked charges."""

    def test_first_missed_year_counts_the_miss_without_escalating(self, api, build):
        """PRD §3.8: "When `denominator_count` is at least 5 and `actual_pct` is strictly below
        `met_threshold_pct`, the indicator is scored `NOT_MET` and `consecutive_miss_count` increases by 1;
        from `NOT_MET` this is a self-loop that re-enters `NOT_MET` for a second consecutive miss."
        PRD §3.8: "The increment of `consecutive_miss_count` is cascade link 1, and it is that increment
        reaching the miss tolerance of 2 — not the close itself — that fires link 2: the indicator escalates
        `NOT_MET → IMPROVEMENT_REQUIRED`."
        PRD §2.13: "Each link fires only because its predecessor fired — a link whose own precondition is
        unmet stops the chain without failing the request that started it."

        Design: Difficulty/transitive_cascade/close_reporting_year_cascades_miss_count_to_program_suspension_and_expenditure_block
        """
        state = _sanction_setup(build)

        closed = _close_year(api, state["indicator_id"], FIRST_CLOSED_ON)

        assert_pct(closed["met_threshold_pct"], MET_THRESHOLD_PCT, "met_threshold_pct")
        assert_pct(closed["actual_pct"], COHORT_ACTUAL_PCT, "actual_pct")
        assert closed["status"] == k.PI_NOT_MET
        assert closed["consecutive_miss_count"] == 1
        program = _read_program(api, state["program_id"])
        assert program["approval_status"] == k.APPROVAL_STATE_APPROVED
        charge = _read_expenditure(api, state["requested_expenditure_id"])
        assert charge["status"] == k.EXP_REQUESTED

    def test_second_missed_year_carries_the_counter_to_the_miss_tolerance(self, api, build):
        """PRD §3.8: "When `denominator_count` is at least 5 and `actual_pct` is strictly below
        `met_threshold_pct`, the indicator is scored `NOT_MET` and `consecutive_miss_count` increases by 1;
        from `NOT_MET` this is a self-loop that re-enters `NOT_MET` for a second consecutive miss."
        PRD §3.8: "The close writes `actual_pct` from the final variant, stores `closed_on`, increments the
        indicator's `version`, and then takes exactly one of three branches."

        Design: Difficulty/transitive_cascade/close_reporting_year_cascades_miss_count_to_program_suspension_and_expenditure_block
        """
        state = _sanction_setup(build)
        _close_year(api, state["indicator_id"], FIRST_CLOSED_ON)

        closed = _close_year(api, state["indicator_id"], SECOND_CLOSED_ON)

        assert closed["consecutive_miss_count"] == 2
        assert_pct(closed["actual_pct"], COHORT_ACTUAL_PCT, "actual_pct")
        assert closed["closed_on"] == SECOND_CLOSED_ON

    def test_reaching_the_miss_tolerance_escalates_the_indicator(self, api, build):
        """PRD §3.8: "The increment of `consecutive_miss_count` is cascade link 1, and it is that increment
        reaching the miss tolerance of 2 — not the close itself — that fires link 2: the indicator escalates
        `NOT_MET → IMPROVEMENT_REQUIRED`."

        Design: Difficulty/transitive_cascade/close_reporting_year_cascades_miss_count_to_program_suspension_and_expenditure_block
        """
        state = _sanction_setup(build)
        _close_year(api, state["indicator_id"], FIRST_CLOSED_ON)

        closed = _close_year(api, state["indicator_id"], SECOND_CLOSED_ON)

        assert closed["status"] == k.PI_IMPROVEMENT_REQUIRED
        assert _read_indicator(api, state["indicator_id"])["status"] == k.PI_IMPROVEMENT_REQUIRED

    def test_escalation_suspends_the_approved_program_of_study(self, api, build):
        """PRD §3.8: "Link 2 in turn fires link 3, which suspends the program: a program of study in
        `approval_status` `STATE_APPROVED` moves `STATE_APPROVED → SUSPENDED`, has
        `federal_reporting_eligible` set to false, appends the finding code `PERF_SUSPENSION` to
        `open_finding_codes`, and has its `version` incremented."

        Design: Difficulty/transitive_cascade/close_reporting_year_cascades_miss_count_to_program_suspension_and_expenditure_block
        """
        state = _sanction_setup(build)
        _close_year(api, state["indicator_id"], FIRST_CLOSED_ON)

        _close_year(api, state["indicator_id"], SECOND_CLOSED_ON)

        program = _read_program(api, state["program_id"])
        assert program["approval_status"] == k.APPROVAL_SUSPENDED
        assert program["federal_reporting_eligible"] is False
        assert program["open_finding_codes"] == [k.FINDING_PERF_SUSPENSION]

    def test_suspension_increments_the_program_version_it_did_not_request(self, api, build):
        """PRD §2.4: "`version` is an integer that begins at 1 on creation and increments by exactly 1 on
        every mutation of that record, including mutations the record did not itself request — a cascade
        that changes a program's approval status increments that program's `version` just as an explicit
        call would."
        PRD §3.8: "Link 2 in turn fires link 3, which suspends the program: a program of study in
        `approval_status` `STATE_APPROVED` moves `STATE_APPROVED → SUSPENDED`, has
        `federal_reporting_eligible` set to false, appends the finding code `PERF_SUSPENSION` to
        `open_finding_codes`, and has its `version` incremented."

        Design: Difficulty/transitive_cascade/close_reporting_year_cascades_miss_count_to_program_suspension_and_expenditure_block
        """
        state = _sanction_setup(build)
        _close_year(api, state["indicator_id"], FIRST_CLOSED_ON)
        before = _read_program(api, state["program_id"])["version"]

        _close_year(api, state["indicator_id"], SECOND_CLOSED_ON)

        after = _read_program(api, state["program_id"])["version"]
        assert_version_bumped_by(before, after, 1, "program version")

    def test_suspension_blocks_the_programs_outstanding_charge(self, api, build):
        """PRD §3.8: "And that suspension fires link 4: every expenditure charged to that program whose
        `status` is `REQUESTED` moves `REQUESTED → BLOCKED`, each with its own `version` increment."

        Design: Difficulty/transitive_cascade/close_reporting_year_cascades_miss_count_to_program_suspension_and_expenditure_block
        """
        state = _sanction_setup(build)
        _close_year(api, state["indicator_id"], FIRST_CLOSED_ON)
        before = _read_expenditure(api, state["requested_expenditure_id"])["version"]

        _close_year(api, state["indicator_id"], SECOND_CLOSED_ON)

        charge = _read_expenditure(api, state["requested_expenditure_id"])
        assert charge["status"] == k.EXP_BLOCKED
        assert_version_bumped_by(before, charge["version"], 1, "expenditure version")

    def test_certified_charges_survive_the_suspension_untouched(self, api, build):
        """PRD §3.8: "And that suspension fires link 4: every expenditure charged to that program whose
        `status` is `REQUESTED` moves `REQUESTED → BLOCKED`, each with its own `version` increment.
        Certified, obligated, disallowed and voided lines are untouched."

        Design: Difficulty/transitive_cascade/close_reporting_year_cascades_miss_count_to_program_suspension_and_expenditure_block
        """
        state = _sanction_setup(build, with_certified_line=True)
        _close_year(api, state["indicator_id"], FIRST_CLOSED_ON)
        before = _read_expenditure(api, state["certified_expenditure_id"])

        _close_year(api, state["indicator_id"], SECOND_CLOSED_ON)

        after = _read_expenditure(api, state["certified_expenditure_id"])
        assert after["status"] == k.EXP_CERTIFIED
        assert_cents(after["approved_cents"], before["approved_cents"], "approved_cents")
        assert_version_bumped_by(before["version"], after["version"], 0, "expenditure version")
        assert _read_expenditure(api, state["requested_expenditure_id"])["status"] == k.EXP_BLOCKED

    def test_blocking_a_charge_leaves_the_award_ledger_where_it_stood(self, api, build):
        """PRD §3.7: "Step one computes `direct_obligated_cents` as the sum of `approved_cents` over the
        award's expenditures whose `status` is `CERTIFIED` or `OBLIGATED`; `REQUESTED`, `BLOCKED`,
        `DISALLOWED` and `VOIDED` rows are excluded, which is exactly what makes a void an exact
        compensation."

        Design: Difficulty/transitive_cascade/close_reporting_year_cascades_miss_count_to_program_suspension_and_expenditure_block
        """
        state = _sanction_setup(build)
        _close_year(api, state["indicator_id"], FIRST_CLOSED_ON)

        _close_year(api, state["indicator_id"], SECOND_CLOSED_ON)

        assert _read_expenditure(api, state["requested_expenditure_id"])["status"] == k.EXP_BLOCKED
        grant = _read_grant(api, state["grant_id"])
        assert_cents(grant["direct_obligated_cents"], 0, "direct_obligated_cents")
        assert_cents(grant["remaining_cents"], ALLOCATION_CENTS, "remaining_cents")


class TestImprovementPlanRecoveryCascade:
    """The upward chain: acceptance, monitoring, reinstatement, unblocked charges."""

    def test_acceptance_stamps_the_plan_at_the_logical_clock_instant(self, api, build):
        """PRD §3.9: "The plan moves `SUBMITTED → ACCEPTED`, `accepted_at` is set to the current logical
        clock instant, and the chain runs."
        PRD §2.5: "Before any client sets it, that clock reads exactly `2026-08-01T00:00:00Z`, and it never
        falls back to real wall-clock time."

        Design: Difficulty/transitive_cascade/accept_improvement_plan_cascades_monitoring_reinstatement_and_expenditure_unblock
        """
        state = _recovery_setup(build)

        accepted = validate_unpaginated(
            api.accept_plan(
                state["plan_id"],
                f.plan_accept_payload(acceptance_note="Plan is responsive."),
                users.headers(users.REVIEWER),
            )
        )

        assert accepted["status"] == k.PLAN_ACCEPTED
        assert_instant_equals(accepted["accepted_at"], k.CLOCK_EPOCH_ISO, "accepted_at")

    def test_acceptance_moves_the_indicator_into_monitoring_with_the_counter_reset(self, api, build):
        """PRD §3.9: "Link 2: the parent indicator moves `IMPROVEMENT_REQUIRED → MONITORING` with
        `consecutive_miss_count` reset to 0."

        Design: Difficulty/transitive_cascade/accept_improvement_plan_cascades_monitoring_reinstatement_and_expenditure_unblock
        """
        state = _recovery_setup(build)
        before = _read_indicator(api, state["indicator_id"])
        assert before["status"] == k.PI_IMPROVEMENT_REQUIRED
        assert before["consecutive_miss_count"] == 2

        build.accept_plan(state["plan_id"])

        indicator = _read_indicator(api, state["indicator_id"])
        assert indicator["status"] == k.PI_MONITORING
        assert indicator["consecutive_miss_count"] == 0

    def test_the_counter_reset_returns_the_program_to_changes_requested(self, api, build):
        """PRD §3.9: "Link 3, caused by that reset: the indicator's program of study moves
        `SUSPENDED → CHANGES_REQUESTED` and appends `PERF_IMPROVEMENT_ACCEPTED` to its
        `open_finding_codes`."

        Design: Difficulty/transitive_cascade/accept_improvement_plan_cascades_monitoring_reinstatement_and_expenditure_unblock
        """
        state = _recovery_setup(build)
        before = _read_program(api, state["program_id"])
        assert before["approval_status"] == k.APPROVAL_SUSPENDED

        build.accept_plan(state["plan_id"])

        program = _read_program(api, state["program_id"])
        assert program["approval_status"] == k.APPROVAL_CHANGES_REQUESTED
        assert_version_bumped_by(before["version"], program["version"], 1, "program version")

    def test_recovery_appends_its_finding_code_to_the_suspension_finding(self, api, build):
        """PRD §3.9: "Link 3, caused by that reset: the indicator's program of study moves
        `SUSPENDED → CHANGES_REQUESTED` and appends `PERF_IMPROVEMENT_ACCEPTED` to its
        `open_finding_codes`."
        PRD §3.8: "Link 2 in turn fires link 3, which suspends the program: a program of study in
        `approval_status` `STATE_APPROVED` moves `STATE_APPROVED → SUSPENDED`, has
        `federal_reporting_eligible` set to false, appends the finding code `PERF_SUSPENSION` to
        `open_finding_codes`, and has its `version` incremented."

        Design: Difficulty/transitive_cascade/accept_improvement_plan_cascades_monitoring_reinstatement_and_expenditure_unblock
        """
        state = _recovery_setup(build)

        build.accept_plan(state["plan_id"])

        program = _read_program(api, state["program_id"])
        assert program["open_finding_codes"] == [
            k.FINDING_PERF_SUSPENSION,
            k.FINDING_PERF_IMPROVEMENT_ACCEPTED,
        ]

    def test_recovery_does_not_restore_federal_reporting_eligibility(self, api, build):
        """PRD §3.9: "Note that the program lands in `CHANGES_REQUESTED` rather than back in
        `STATE_APPROVED`: recovery restores the district's ability to spend and to resubmit, but state
        approval must be earned again through the submission cycle of §3.4, and
        `federal_reporting_eligible` stays false until it is."

        Design: Difficulty/transitive_cascade/accept_improvement_plan_cascades_monitoring_reinstatement_and_expenditure_unblock
        """
        state = _recovery_setup(build)

        build.accept_plan(state["plan_id"])

        program = _read_program(api, state["program_id"])
        assert program["approval_status"] == k.APPROVAL_CHANGES_REQUESTED
        assert program["federal_reporting_eligible"] is False

    def test_the_un_suspension_returns_the_blocked_charge_to_requested(self, api, build):
        """PRD §3.9: "Link 4, caused by that un-suspension: every expenditure charged to that program whose
        `status` is `BLOCKED` returns `BLOCKED → REQUESTED`, freeing it to be certified again. Every entity
        the chain touches has its `version` incremented."

        Design: Difficulty/transitive_cascade/accept_improvement_plan_cascades_monitoring_reinstatement_and_expenditure_unblock
        """
        state = _recovery_setup(build)
        before = _read_expenditure(api, state["requested_expenditure_id"])
        assert before["status"] == k.EXP_BLOCKED

        build.accept_plan(state["plan_id"])

        charge = _read_expenditure(api, state["requested_expenditure_id"])
        assert charge["status"] == k.EXP_REQUESTED
        assert_version_bumped_by(before["version"], charge["version"], 1, "expenditure version")


class TestCreditPostingCohortCascade:
    """One credit posting reclassifies a student and re-scores the whole cohort."""

    def test_a_cohort_of_four_concentrators_sits_below_the_federal_minimum(self, api, build):
        """PRD §3.8: "`denominator_count` is the number of students whose program matches the indicator's
        program, whose `cohort_year` matches the indicator's `cohort_year`, and whose `concentrator_status`
        is `CONCENTRATOR` or `COMPLETER`; a `PARTICIPANT` counts in neither the numerator nor the
        denominator. `numerator_count` is the number of those same students whose
        `verified_qualifying_attainment_count` is at least 1. `small_cohort_flag` is true exactly when
        `denominator_count` is below the federal minimum cohort size of 5."

        Design: Difficulty/transitive_cascade/credit_posting_cascades_concentrator_flip_to_cohort_size_and_preliminary_actual
        """
        state = _cohort_flip_setup(build)

        indicator = _read_indicator(api, state["indicator_id"])

        assert_cohort_figures(
            indicator, DENOMINATOR_BEFORE_FLIP, NUMERATOR_COUNT, True
        )

    def test_the_small_cohort_still_projects_its_raw_percentage(self, api, build):
        """PRD §3.8: "The raw percentage is null when `denominator_count` is zero; otherwise it is 100
        multiplied by `numerator_count`, divided by `denominator_count`, rounded half-up to two decimal
        places."
        PRD §3.8: "The `PRELIMINARY_UNADJUSTED` variant ignores `small_cohort_flag` completely: it publishes
        the raw percentage as `preliminary_actual_pct` and sets `preliminary_status_projection` to `MET` when
        the raw percentage is at least `met_threshold_pct`, to `NOT_MET` when it is strictly below, and to
        `UNDEFINED` whenever either the raw percentage or `met_threshold_pct` is null."

        Design: Difficulty/transitive_cascade/credit_posting_cascades_concentrator_flip_to_cohort_size_and_preliminary_actual
        """
        state = _cohort_flip_setup(build)

        indicator = _read_indicator(api, state["indicator_id"])

        assert_pct(indicator["met_threshold_pct"], SMALL_MET_THRESHOLD_PCT, "met_threshold_pct")
        assert_pct(
            indicator["preliminary_actual_pct"],
            ACTUAL_PCT_BEFORE_FLIP,
            "preliminary_actual_pct",
        )
        assert indicator["preliminary_status_projection"] == k.PROJECTION_NOT_MET

    def test_two_credit_hours_flip_the_fifth_student_to_concentrator(self, api, build):
        """PRD §3.6: "Third, `concentrator_status` is decided by a three-way ladder evaluated top to bottom:
        the student is a `COMPLETER` when `cte_credits_earned` is at least 2.0 credit hours **and**
        `exited_on` is non-null **and** `verified_qualifying_attainment_count` is at least 1; failing that,
        the student is a `CONCENTRATOR` when `cte_credits_earned` alone is at least 2.0 credit hours; failing
        that, the student is a `PARTICIPANT`. The credit comparison is inclusive — a balance of exactly 2.0
        classifies as at least `CONCENTRATOR`, while 1.99 does not"

        Design: Difficulty/transitive_cascade/credit_posting_cascades_concentrator_flip_to_cohort_size_and_preliminary_actual
        """
        state = _cohort_flip_setup(build)

        student = validate_unpaginated(
            api.post_credit(
                state["participant_id"],
                f.credit_posting_payload(
                    state["course_id"], POSTING_CREDIT_HOURS, FLIP_POSTED_ON
                ),
                users.headers(users.REGISTRAR),
            )
        )

        assert_credit_hours(student["cte_credits_earned"], 2.00, "cte_credits_earned")
        assert student["concentrator_status"] == k.CONCENTRATOR_CONCENTRATOR

    def test_the_flip_carries_the_fifth_student_into_the_denominator(self, api, build):
        """PRD §3.6: "Every credit posting also propagates into accountability, refreshing
        `denominator_count`, `small_cohort_flag`, `preliminary_actual_pct` and
        `preliminary_status_projection` on each performance indicator of the student's program whose
        `cohort_year` matches, and increments the student's `version`."
        PRD §3.8: "`numerator_count` is the number of those same students whose
        `verified_qualifying_attainment_count` is at least 1."

        Design: Difficulty/transitive_cascade/credit_posting_cascades_concentrator_flip_to_cohort_size_and_preliminary_actual
        """
        state = _cohort_flip_setup(build)

        build.post_credit(
            state["participant_id"],
            state["course_id"],
            POSTING_CREDIT_HOURS,
            posted_on=FLIP_POSTED_ON,
        )

        indicator = _read_indicator(api, state["indicator_id"])
        assert indicator["denominator_count"] == DENOMINATOR_AFTER_FLIP
        assert indicator["numerator_count"] == NUMERATOR_COUNT

    def test_the_fifth_concentrator_clears_the_small_cohort_flag(self, api, build):
        """PRD §3.8: "`small_cohort_flag` is true exactly when `denominator_count` is below the federal
        minimum cohort size of 5."

        Design: Difficulty/transitive_cascade/credit_posting_cascades_concentrator_flip_to_cohort_size_and_preliminary_actual
        """
        state = _cohort_flip_setup(build)
        assert _read_indicator(api, state["indicator_id"])["small_cohort_flag"] is True

        build.post_credit(
            state["participant_id"],
            state["course_id"],
            POSTING_CREDIT_HOURS,
            posted_on=FLIP_POSTED_ON,
        )

        indicator = _read_indicator(api, state["indicator_id"])
        assert indicator["small_cohort_flag"] is False

    def test_the_widened_denominator_lowers_the_preliminary_percentage(self, api, build):
        """PRD §3.8: "The raw percentage is null when `denominator_count` is zero; otherwise it is 100
        multiplied by `numerator_count`, divided by `denominator_count`, rounded half-up to two decimal
        places."
        PRD §3.8: "This variant is recomputed on every read of the indicator and on every cascade that
        changes any cohort member's `concentrator_status`, and it never suppresses anything."

        Design: Difficulty/transitive_cascade/credit_posting_cascades_concentrator_flip_to_cohort_size_and_preliminary_actual
        """
        state = _cohort_flip_setup(build)

        build.post_credit(
            state["participant_id"],
            state["course_id"],
            POSTING_CREDIT_HOURS,
            posted_on=FLIP_POSTED_ON,
        )

        indicator = _read_indicator(api, state["indicator_id"])
        assert_pct(
            indicator["preliminary_actual_pct"],
            ACTUAL_PCT_AFTER_FLIP,
            "preliminary_actual_pct",
        )
        assert indicator["preliminary_status_projection"] == k.PROJECTION_NOT_MET
