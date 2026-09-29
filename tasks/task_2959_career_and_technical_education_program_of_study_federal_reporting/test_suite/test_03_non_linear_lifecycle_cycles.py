"""Cyclic lifecycles: the program approval revision loop and the plan revision loop.

Two records in this domain re-enter a state they have already left. A program of
study walks back into ``SUBMITTED`` through ``CHANGES_REQUESTED`` while the
independent needs-assessment axis on the very same row stays put, and an
improvement plan loops ``SUBMITTED -> RETURNED -> SUBMITTED`` until a counter,
rather than an actor's choice, diverts it into a terminal rejection.
"""

from test_helpers import (
    STOP_CLNA_CERTIFIED,
    STOP_COMMITTEE_REVIEW,
    STOP_STATE_APPROVED,
    STOP_SUBMITTED,
    assert_instant_equals,
    errors,
    f,
    k,
    validate_error,
    validate_unpaginated,
)

# --- Scenario data ---------------------------------------------------------
HVAC_CIP = "47.0201"
CULINARY_CIP = "12.0503"

ENDORSEMENT_INSTANT = "2026-08-10T15:00:00.000Z"

ROUND_ONE_NARRATIVE = "https://district.example/pos/47-0201/r1.pdf"
ROUND_TWO_NARRATIVE = "https://district.example/pos/47-0201/r2.pdf"

STATE_FINDINGS = ["ALIGN-02", "BUDGET-07"]
FINDING_NOTE = "Articulation evidence incomplete."

FIRST_RETURN_REASON = "Milestones lack measurable targets."
SECOND_RETURN_REASON = "Budget narrative missing."
THIRD_RETURN_REASON = "Still non-responsive."

CLNA_EXPIRY_TWO_YEARS_ON = "2028-07-31"

FIRST_CLOSE_ON = "2027-09-30"
SECOND_CLOSE_ON = "2028-09-30"


def _hvac_program(build, stop_at):
    """Author the HVAC pathway up to the named stop point."""
    return build.program(
        HVAC_CIP,
        stop_at=stop_at,
        title="HVAC Technology",
        cluster=k.CLUSTER_CONSTRUCTION,
    )


def _plan_awaiting_state_review(build):
    """A suspended program, an escalated indicator and a drafted plan on it.

    Five concentrators form the denominator and two of them hold verified
    attainments of the program's national credential, so the cohort scores
    40.00 against an agreed level of 90.00 and misses twice in a row.
    """
    scenario = build.program(
        CULINARY_CIP,
        stop_at=STOP_STATE_APPROVED,
        title="Culinary Arts",
        cluster=k.CLUSTER_AGRICULTURE,
    )
    build.cohort(scenario, size=5, verified_count=2)
    indicator = build.agreed_indicator(
        scenario.program_id,
        k.INDICATOR_4S1_CREDENTIAL,
        90.00,
        baseline_pct=60.00,
    )
    build.miss_twice(
        indicator["id"],
        first_closed_on=FIRST_CLOSE_ON,
        second_closed_on=SECOND_CLOSE_ON,
    )
    plan = build.draft_plan(indicator["id"])
    return scenario, indicator["id"], plan["id"]


def _returned_twice(build, plan_id):
    """Drive the plan through its first two returns, leaving it in RETURNED."""
    build.submit_plan(plan_id)
    build.return_plan(plan_id, FIRST_RETURN_REASON)
    build.submit_plan(plan_id)
    build.return_plan(plan_id, SECOND_RETURN_REASON)


class TestProgramApprovalRevisionCycle:
    """The approval axis re-enters SUBMITTED while the CLNA axis stands still."""

    def test_first_submission_counts_as_approval_round_one(
        self, api, build, director_headers
    ):
        """PRD §3.4: "A `CteDirector` submits by supplying a `narrative_url` linking the narrative packet, and the program moves `DRAFT → SUBMITTED` on a first attempt or `CHANGES_REQUESTED → SUBMITTED` on any resubmission after a state finding."

        PRD §3.4: "An accepted submission increments `approval_round` by 1 — the counter is the district's audit trail of how many times the packet has gone up — writes the supplied `narrative_url` onto the program, clears `open_finding_codes` back to an empty list, and recomputes the alignment index under the `PROVISIONAL_LOCAL` variant, writing `alignment_index`, setting `alignment_index_variant` to `PROVISIONAL_LOCAL`, and refreshing `secondary_credit_total`, `postsecondary_credit_total` and `articulated_credit_total`."

        Design: Difficulty/non_linear_state_machine/program_approval_revision_cycle_with_independent_clna_axis
        """
        scenario = _hvac_program(build, STOP_CLNA_CERTIFIED)

        response = api.submit_program(
            scenario.program_id,
            f.submit_payload(ROUND_ONE_NARRATIVE),
            director_headers,
        )

        program = validate_unpaginated(response, 200)
        assert program["approval_status"] == k.APPROVAL_SUBMITTED
        assert program["approval_round"] == 1
        assert program["narrative_url"] == ROUND_ONE_NARRATIVE

    def test_passing_endorsement_minutes_carry_a_submitted_program_into_review(
        self, api, build, director_headers
    ):
        """PRD §3.3: "When the meeting's `agenda_kind` is `POS_ENDORSEMENT`, the recomputed `endorsement_passed` is true, and the owning committee's program of study is sitting in `approval_status` `SUBMITTED`, that program transitions `SUBMITTED → COMMITTEE_REVIEW` and its `version` increments as well."

        Design: Difficulty/non_linear_state_machine/program_approval_revision_cycle_with_independent_clna_axis
        """
        scenario = _hvac_program(build, STOP_SUBMITTED)
        before = validate_unpaginated(
            api.get_program(scenario.program_id, director_headers), 200
        )
        assert before["approval_status"] == k.APPROVAL_SUBMITTED

        build.quorate_meeting(
            scenario.committee, k.AGENDA_POS_ENDORSEMENT, ENDORSEMENT_INSTANT
        )

        program = validate_unpaginated(
            api.get_program(scenario.program_id, director_headers), 200
        )
        assert program["approval_status"] == k.APPROVAL_COMMITTEE_REVIEW

    def test_state_findings_replace_the_open_finding_code_list(
        self, api, build, reviewer_headers
    ):
        """PRD §3.4: "Returning it moves `COMMITTEE_REVIEW → CHANGES_REQUESTED` and requires a `finding_codes` list, optionally accompanied by a `note`; the supplied list **replaces** `open_finding_codes` wholesale, and the program's `version` increments."

        Design: Difficulty/non_linear_state_machine/program_approval_revision_cycle_with_independent_clna_axis
        """
        scenario = _hvac_program(build, STOP_COMMITTEE_REVIEW)

        response = api.request_changes(
            scenario.program_id,
            f.request_changes_payload(STATE_FINDINGS, note=FINDING_NOTE),
            reviewer_headers,
        )

        program = validate_unpaginated(response, 200)
        assert program["approval_status"] == k.APPROVAL_CHANGES_REQUESTED
        assert program["open_finding_codes"] == STATE_FINDINGS

    def test_resubmission_after_findings_reaches_approval_round_two(
        self, api, build, director_headers
    ):
        """PRD §3.4: "An accepted submission increments `approval_round` by 1 — the counter is the district's audit trail of how many times the packet has gone up — writes the supplied `narrative_url` onto the program, clears `open_finding_codes` back to an empty list, and recomputes the alignment index under the `PROVISIONAL_LOCAL` variant, writing `alignment_index`, setting `alignment_index_variant` to `PROVISIONAL_LOCAL`, and refreshing `secondary_credit_total`, `postsecondary_credit_total` and `articulated_credit_total`."

        PRD §3.4: "The district then works the findings and resubmits, which clears the list again — this is the revision cycle, and it may repeat without limit."

        Design: Difficulty/non_linear_state_machine/program_approval_revision_cycle_with_independent_clna_axis
        """
        scenario = _hvac_program(build, STOP_COMMITTEE_REVIEW)
        build.request_changes(scenario.program_id, STATE_FINDINGS, note=FINDING_NOTE)

        response = api.submit_program(
            scenario.program_id,
            f.submit_payload(ROUND_TWO_NARRATIVE),
            director_headers,
        )

        program = validate_unpaginated(response, 200)
        assert program["approval_status"] == k.APPROVAL_SUBMITTED
        assert program["approval_round"] == 2
        assert program["open_finding_codes"] == []
        assert program["narrative_url"] == ROUND_TWO_NARRATIVE

    def test_the_needs_assessment_axis_is_untouched_by_the_revision_cycle(
        self, build, api, director_headers
    ):
        """PRD §2.8: "A `ProgramOfStudy` has an `approval_status` that walks `DRAFT`, `SUBMITTED`, `COMMITTEE_REVIEW`, `CHANGES_REQUESTED`, `STATE_APPROVED` and `SUSPENDED`, and — entirely independently, on the same row — a `clna_phase` that walks `NOT_STARTED`, `DATA_COLLECTION`, `STAKEHOLDER_CONSULTATION`, `GAP_ANALYSIS`, `CERTIFIED` and `EXPIRED`. Neither axis constrains the other's shape: a program may sit in `STATE_APPROVED` while its `clna_phase` moves from `CERTIFIED` to `EXPIRED`, and it may sit in `DRAFT` while its `clna_phase` reaches `CERTIFIED`."

        PRD §3.2: "On success the server writes `clna_certified_by_user_id` from the acting `X-User-ID`, sets `clna_certified_on` to the logical clock's current date, and sets `clna_expires_on` to that date plus 730 days — a certified needs assessment is good for two years and not a day more."

        PRD §2.5: "Before any client sets it, that clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back to real wall-clock time."

        Design: Difficulty/non_linear_state_machine/program_approval_revision_cycle_with_independent_clna_axis
        """
        scenario = _hvac_program(build, STOP_COMMITTEE_REVIEW)
        build.request_changes(scenario.program_id, STATE_FINDINGS, note=FINDING_NOTE)
        build.submit(scenario.program_id, narrative_url=ROUND_TWO_NARRATIVE)

        program = validate_unpaginated(
            api.get_program(scenario.program_id, director_headers), 200
        )
        assert program["approval_status"] == k.APPROVAL_SUBMITTED
        assert program["clna_phase"] == k.CLNA_CERTIFIED
        assert program["clna_certified_on"] == k.CLOCK_EPOCH_DATE
        assert program["clna_expires_on"] == CLNA_EXPIRY_TWO_YEARS_ON


class TestImprovementPlanRevisionCycle:
    """The plan loops through RETURNED until a counter ends the loop for it."""

    def test_a_drafted_plan_opens_at_revision_round_zero(
        self, api, build, director_headers
    ):
        """PRD §3.9: "The new plan lands in `status` `DRAFT` with `revision_round` 0, `milestone_count` set to the number of elements in `milestones`, an empty `return_reasons` list, and `submitted_at` and `accepted_at` both null."

        Design: Difficulty/non_linear_state_machine/improvement_plan_return_resubmit_cycle_terminates_in_rejected_final
        """
        _scenario, _indicator_id, plan_id = _plan_awaiting_state_review(build)

        plan = validate_unpaginated(api.get_plan(plan_id, director_headers), 200)

        assert plan["status"] == k.PLAN_DRAFT
        assert plan["revision_round"] == 0
        assert plan["milestone_count"] == 3
        assert plan["return_reasons"] == []
        assert plan["submitted_at"] is None
        assert plan["accepted_at"] is None

    def test_the_first_return_sends_the_plan_back_for_revision(
        self, api, build, reviewer_headers
    ):
        """PRD §3.9: "A `StateComplianceReviewer` rules on a submitted plan. Returning it carries a `return_reason`, appends that reason to the append-only `return_reasons` list, and increments `revision_round` by 1 — and the branch is chosen on the **incremented** value against the three-round revision budget. While the incremented `revision_round` is strictly below 3 the plan moves `SUBMITTED → RETURNED` and the district may revise and resubmit; this is the revision cycle, and since the counter starts at 0, the first and second returns take this branch."

        Design: Difficulty/non_linear_state_machine/improvement_plan_return_resubmit_cycle_terminates_in_rejected_final
        """
        _scenario, _indicator_id, plan_id = _plan_awaiting_state_review(build)
        build.submit_plan(plan_id)

        response = api.return_plan(
            plan_id, f.plan_return_payload(FIRST_RETURN_REASON), reviewer_headers
        )

        plan = validate_unpaginated(response, 200)
        assert plan["status"] == k.PLAN_RETURNED
        assert plan["revision_round"] == 1
        assert plan["return_reasons"] == [FIRST_RETURN_REASON]

    def test_a_returned_plan_may_be_resubmitted(self, api, build, director_headers):
        """PRD §3.9: "Submitting a plan — optionally with a `submission_note` — moves it `DRAFT → SUBMITTED` on the first attempt and `RETURNED → SUBMITTED` on any revision, sets `submitted_at` to the current logical clock instant, and increments the plan's `version`."

        PRD §2.5: "Before any client sets it, that clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back to real wall-clock time."

        Design: Difficulty/non_linear_state_machine/improvement_plan_return_resubmit_cycle_terminates_in_rejected_final
        """
        _scenario, _indicator_id, plan_id = _plan_awaiting_state_review(build)
        build.submit_plan(plan_id)
        build.return_plan(plan_id, FIRST_RETURN_REASON)

        response = api.submit_plan(
            plan_id, f.plan_submit_payload(submission_note="Revision 2."), director_headers
        )

        plan = validate_unpaginated(response, 200)
        assert plan["status"] == k.PLAN_SUBMITTED
        assert plan["revision_round"] == 1
        assert_instant_equals(plan["submitted_at"], k.CLOCK_EPOCH_ISO, "submitted_at")

    def test_the_second_return_keeps_the_plan_inside_the_revision_cycle(
        self, api, build, reviewer_headers
    ):
        """PRD §3.9: "A `StateComplianceReviewer` rules on a submitted plan. Returning it carries a `return_reason`, appends that reason to the append-only `return_reasons` list, and increments `revision_round` by 1 — and the branch is chosen on the **incremented** value against the three-round revision budget. While the incremented `revision_round` is strictly below 3 the plan moves `SUBMITTED → RETURNED` and the district may revise and resubmit; this is the revision cycle, and since the counter starts at 0, the first and second returns take this branch."

        Design: Difficulty/non_linear_state_machine/improvement_plan_return_resubmit_cycle_terminates_in_rejected_final
        """
        _scenario, _indicator_id, plan_id = _plan_awaiting_state_review(build)
        build.submit_plan(plan_id)
        build.return_plan(plan_id, FIRST_RETURN_REASON)
        build.submit_plan(plan_id)

        response = api.return_plan(
            plan_id, f.plan_return_payload(SECOND_RETURN_REASON), reviewer_headers
        )

        plan = validate_unpaginated(response, 200)
        assert plan["status"] == k.PLAN_RETURNED
        assert plan["revision_round"] == 2

    def test_the_third_return_terminates_the_loop_in_rejected_final(
        self, api, build, reviewer_headers
    ):
        """PRD §3.9: "When the incremented `revision_round` equals exactly 3 — that is, on the third return — the sibling branch fires instead and the loop terminates: the plan moves `SUBMITTED → REJECTED_FINAL`, its parent indicator moves `IMPROVEMENT_REQUIRED → SANCTIONED`, and the indicator's program of study stays `SUSPENDED` while `PERF_SANCTION` is appended to its `open_finding_codes`."

        Design: Difficulty/non_linear_state_machine/improvement_plan_return_resubmit_cycle_terminates_in_rejected_final
        """
        _scenario, _indicator_id, plan_id = _plan_awaiting_state_review(build)
        _returned_twice(build, plan_id)
        build.submit_plan(plan_id)

        response = api.return_plan(
            plan_id, f.plan_return_payload(THIRD_RETURN_REASON), reviewer_headers
        )

        plan = validate_unpaginated(response, 200)
        assert plan["status"] == k.PLAN_REJECTED_FINAL
        assert plan["revision_round"] == 3

    def test_each_return_appends_its_reason_in_filing_order(
        self, api, build, director_headers
    ):
        """PRD §3.9: "A `StateComplianceReviewer` rules on a submitted plan. Returning it carries a `return_reason`, appends that reason to the append-only `return_reasons` list, and increments `revision_round` by 1 — and the branch is chosen on the **incremented** value against the three-round revision budget."

        PRD §3.9: "Both branches record the `return_reason` and increment the plan's `version`; only the terminal branch reaches beyond the plan."

        Design: Difficulty/non_linear_state_machine/improvement_plan_return_resubmit_cycle_terminates_in_rejected_final
        """
        _scenario, _indicator_id, plan_id = _plan_awaiting_state_review(build)
        _returned_twice(build, plan_id)
        build.submit_plan(plan_id)
        build.return_plan(plan_id, THIRD_RETURN_REASON)

        plan = validate_unpaginated(api.get_plan(plan_id, director_headers), 200)

        assert plan["return_reasons"] == [
            FIRST_RETURN_REASON,
            SECOND_RETURN_REASON,
            THIRD_RETURN_REASON,
        ]

    def test_the_final_rejection_sanctions_the_parent_indicator(
        self, api, build, reviewer_headers
    ):
        """PRD §3.9: "When the incremented `revision_round` equals exactly 3 — that is, on the third return — the sibling branch fires instead and the loop terminates: the plan moves `SUBMITTED → REJECTED_FINAL`, its parent indicator moves `IMPROVEMENT_REQUIRED → SANCTIONED`, and the indicator's program of study stays `SUSPENDED` while `PERF_SANCTION` is appended to its `open_finding_codes`."

        Design: Difficulty/non_linear_state_machine/improvement_plan_return_resubmit_cycle_terminates_in_rejected_final
        """
        _scenario, indicator_id, plan_id = _plan_awaiting_state_review(build)
        _returned_twice(build, plan_id)
        build.submit_plan(plan_id)
        build.return_plan(plan_id, THIRD_RETURN_REASON)

        indicator = validate_unpaginated(
            api.get_indicator(indicator_id, reviewer_headers), 200
        )
        assert indicator["status"] == k.PI_SANCTIONED

    def test_the_final_rejection_leaves_the_program_suspended_under_two_findings(
        self, api, build, director_headers
    ):
        """PRD §3.8: "The increment of `consecutive_miss_count` is cascade link 1, and it is that increment reaching the miss tolerance of 2 — not the close itself — that fires link 2: the indicator escalates `NOT_MET → IMPROVEMENT_REQUIRED`. Link 2 in turn fires link 3, which suspends the program: a program of study in `approval_status` `STATE_APPROVED` moves `STATE_APPROVED → SUSPENDED`, has `federal_reporting_eligible` set to false, appends the finding code `PERF_SUSPENSION` to `open_finding_codes`, and has its `version` incremented."

        PRD §3.9: "When the incremented `revision_round` equals exactly 3 — that is, on the third return — the sibling branch fires instead and the loop terminates: the plan moves `SUBMITTED → REJECTED_FINAL`, its parent indicator moves `IMPROVEMENT_REQUIRED → SANCTIONED`, and the indicator's program of study stays `SUSPENDED` while `PERF_SANCTION` is appended to its `open_finding_codes`."

        Design: Difficulty/non_linear_state_machine/improvement_plan_return_resubmit_cycle_terminates_in_rejected_final
        """
        scenario, _indicator_id, plan_id = _plan_awaiting_state_review(build)
        _returned_twice(build, plan_id)
        build.submit_plan(plan_id)
        build.return_plan(plan_id, THIRD_RETURN_REASON)

        program = validate_unpaginated(
            api.get_program(scenario.program_id, director_headers), 200
        )
        assert program["approval_status"] == k.APPROVAL_SUSPENDED
        assert program["federal_reporting_eligible"] is False
        assert program["open_finding_codes"] == [
            k.FINDING_PERF_SUSPENSION,
            k.FINDING_PERF_SANCTION,
        ]

    def test_a_finally_rejected_plan_admits_no_further_submission(
        self, api, build, director_headers
    ):
        """PRD §2.8: "The other lifecycles are: `Expenditure.status` over `REQUESTED`, `CERTIFIED`, `OBLIGATED`, `DISALLOWED`, `VOIDED` and `BLOCKED`, with `DISALLOWED` and `VOIDED` terminal; `PerformanceIndicator.status` over `PROPOSED`, `NEGOTIATING`, `AGREED`, `ARBITRATED`, `MET`, `NOT_MET`, `NOT_SCORED`, `IMPROVEMENT_REQUIRED`, `MONITORING` and `SANCTIONED`, with `MET`, `NOT_SCORED` and `SANCTIONED` terminal; `ImprovementPlan.status` over `DRAFT`, `SUBMITTED`, `RETURNED`, `ACCEPTED` and `REJECTED_FINAL`, with `ACCEPTED` and `REJECTED_FINAL` terminal"

        PRD §2.8: "Writes against a terminal state fall under the same codes — an attempt to certify a `DISALLOWED` or `VOIDED` expenditure, to act on a `MET`, `NOT_SCORED` or `SANCTIONED` indicator, to touch an `ACCEPTED` or `REJECTED_FINAL` plan, to file minutes against an already-`AMENDED` meeting, to file an amendment against a still-`SCHEDULED` meeting, or to verify hours for a `LAPSED` educator are all refused here."

        Design: Difficulty/non_linear_state_machine/improvement_plan_return_resubmit_cycle_terminates_in_rejected_final
        """
        _scenario, _indicator_id, plan_id = _plan_awaiting_state_review(build)
        _returned_twice(build, plan_id)
        build.submit_plan(plan_id)
        build.return_plan(plan_id, THIRD_RETURN_REASON)

        response = api.submit_plan(
            plan_id, f.plan_submit_payload(submission_note="Revision 4."), director_headers
        )

        validate_error(response, errors.ERR_INVALID_PLAN_STATE)
