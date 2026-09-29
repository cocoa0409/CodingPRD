"""Endpoint behaviour: partial amendment, declared side effects, filters and paging.

Each test reaches its starting state through the public API only and then probes
exactly one observable consequence, so a regression names itself.
"""

from test_helpers import (
    STOP_STATE_APPROVED,
    assert_cents,
    assert_credit_hours,
    assert_credit_totals,
    assert_instant_equals,
    assert_ledger,
    assert_same_ids,
    assert_version_bumped_by,
    errors,
    f,
    ids_of,
    k,
    validate_error,
    validate_paginated,
    validate_unpaginated,
)

PATCHED_TITLE = "Mechatronics And Robotics Pathway"


def _patchable_program(build):
    """A draft program with an active opener and a draft follow-on course."""
    program = build.create_program(
        "15.1302",
        title="Mechatronics Pathway",
        cluster=k.CLUSTER_ADVANCED_MANUFACTURING,
        labor_market_data_asof="2026-03-01",
    )
    opener = build.add_course(
        program["id"], f.secondary_course("SEC-1", 1, 4.0, status=k.COURSE_ACTIVE)
    )
    follow_on = build.add_course(
        program["id"],
        f.secondary_course(
            "DFT-2",
            2,
            2.0,
            status=k.COURSE_DRAFT,
            prerequisite_course_id=opener["id"],
        ),
    )
    return program["id"], opener["id"], follow_on["id"]


class TestPartialAmendment:
    """PATCH carries a subset of fields and touches nothing else."""

    def test_amending_only_the_title_rewrites_only_the_title(
        self, api, build, director_headers
    ):
        """PRD §4: "Amend the descriptive attributes of a program of study while it is not state-approved."

        PRD §3.1: "Descriptive attributes remain amendable while the program has not yet been approved. A director may revise any of `title`, `cluster` or `labor_market_data_asof` on a program whose `approval_status` is anything other than `STATE_APPROVED`; the amendment increments the program's `version`."

        Design: Corner/endpoints/patch_endpoints_update_only_the_supplied_fields_and_bump_the_version
        """
        program_id, _, _ = _patchable_program(build)

        amended = validate_unpaginated(
            api.patch_program(
                program_id, f.program_patch(title=PATCHED_TITLE), director_headers
            ),
            200,
        )

        assert amended["title"] == PATCHED_TITLE
        assert amended["cluster"] == k.CLUSTER_ADVANCED_MANUFACTURING
        assert amended["labor_market_data_asof"] == "2026-03-01"
        assert amended["cip_code"] == "15.1302"

    def test_amending_a_program_increments_its_version_by_one(
        self, api, build, director_headers
    ):
        """PRD §3.1: "A director may revise any of `title`, `cluster` or `labor_market_data_asof` on a program whose `approval_status` is anything other than `STATE_APPROVED`; the amendment increments the program's `version`."

        PRD §2.4: "`version` is an integer that begins at 1 on creation and increments by exactly 1 on every mutation of that record"

        Design: Corner/endpoints/patch_endpoints_update_only_the_supplied_fields_and_bump_the_version
        """
        program_id, _, _ = _patchable_program(build)
        before = validate_unpaginated(api.get_program(program_id, director_headers))

        amended = validate_unpaginated(
            api.patch_program(
                program_id, f.program_patch(title=PATCHED_TITLE), director_headers
            ),
            200,
        )

        assert_version_bumped_by(before["version"], amended["version"], 1)

    def test_revising_a_course_applies_the_two_supplied_fields(
        self, api, build, director_headers
    ):
        """PRD §3.1: "Revising a course accepts any subset of `status`, `credit_hours`, `articulated_credit_hours`, `articulation_verified`, `prerequisite_course_id` and `position`, and is subject to the same two prerequisite rules."

        Design: Corner/endpoints/patch_endpoints_update_only_the_supplied_fields_and_bump_the_version
        """
        _, _, follow_on_id = _patchable_program(build)

        revised = validate_unpaginated(
            api.patch_course(
                follow_on_id,
                f.course_patch(status=k.COURSE_ACTIVE, credit_hours=3.0),
                director_headers,
            ),
            200,
        )

        assert revised["status"] == k.COURSE_ACTIVE
        assert_credit_hours(revised["credit_hours"], 3.0)

    def test_revising_a_course_leaves_the_fields_it_did_not_name_alone(
        self, api, build, director_headers
    ):
        """PRD §3.1: "Revising a course accepts any subset of `status`, `credit_hours`, `articulated_credit_hours`, `articulation_verified`, `prerequisite_course_id` and `position`, and is subject to the same two prerequisite rules."

        PRD §3.1: "Optionally the payload sets `articulated_credit_hours` — the portion of the course's credit that articulates to the postsecondary partner, which defaults to 0 and may be neither negative nor greater than `credit_hours`"

        Design: Corner/endpoints/patch_endpoints_update_only_the_supplied_fields_and_bump_the_version
        """
        _, opener_id, follow_on_id = _patchable_program(build)

        revised = validate_unpaginated(
            api.patch_course(
                follow_on_id,
                f.course_patch(status=k.COURSE_ACTIVE, credit_hours=3.0),
                director_headers,
            ),
            200,
        )

        assert revised["code"] == "DFT-2"
        assert revised["position"] == 2
        assert_credit_hours(revised["articulated_credit_hours"], 0)
        assert revised["articulation_verified"] is False
        assert revised["prerequisite_course_id"] == opener_id

    def test_a_revised_course_keeps_its_prerequisite_hop_count(
        self, api, build, director_headers
    ):
        """PRD §3.1: "The server computes `depth_from_root`, the number of prerequisite hops from the course back to a course whose `prerequisite_course_id` is null, by walking the chain; a course that opens the sequence has `depth_from_root` 0."

        PRD §3.1: "A revision recomputes `depth_from_root` not only for the revised course but for every course that transitively depends on it"

        Design: Corner/endpoints/patch_endpoints_update_only_the_supplied_fields_and_bump_the_version
        """
        _, _, follow_on_id = _patchable_program(build)

        revised = validate_unpaginated(
            api.patch_course(
                follow_on_id,
                f.course_patch(status=k.COURSE_ACTIVE, credit_hours=3.0),
                director_headers,
            ),
            200,
        )

        assert revised["depth_from_root"] == 1

    def test_revising_a_course_increments_the_parent_program_version(
        self, api, build, director_headers
    ):
        """PRD §3.1: "A revision recomputes `depth_from_root` not only for the revised course but for every course that transitively depends on it, then rebuilds the parent program's three credit subtotals and its `alignment_index` and `alignment_index_variant`, and increments the `version` of both the course and the parent program."

        Design: Corner/endpoints/patch_endpoints_update_only_the_supplied_fields_and_bump_the_version
        """
        program_id, _, follow_on_id = _patchable_program(build)
        before = validate_unpaginated(api.get_program(program_id, director_headers))

        validate_unpaginated(
            api.patch_course(
                follow_on_id,
                f.course_patch(status=k.COURSE_ACTIVE, credit_hours=3.0),
                director_headers,
            ),
            200,
        )

        after = validate_unpaginated(api.get_program(program_id, director_headers))
        assert_version_bumped_by(before["version"], after["version"], 1)

    def test_revising_a_course_rebuilds_the_parent_credit_subtotals(
        self, api, build, director_headers
    ):
        """PRD §3.1: "A revision recomputes `depth_from_root` not only for the revised course but for every course that transitively depends on it, then rebuilds the parent program's three credit subtotals and its `alignment_index` and `alignment_index_variant`, and increments the `version` of both the course and the parent program."

        PRD §3.1: "Those three sums are what get stored as `secondary_credit_total`, `postsecondary_credit_total` and `articulated_credit_total`."

        Design: Corner/endpoints/patch_endpoints_update_only_the_supplied_fields_and_bump_the_version
        """
        program_id, _, follow_on_id = _patchable_program(build)

        validate_unpaginated(
            api.patch_course(
                follow_on_id,
                f.course_patch(status=k.COURSE_ACTIVE, credit_hours=3.0),
                director_headers,
            ),
            200,
        )

        program = validate_unpaginated(api.get_program(program_id, director_headers))
        assert_credit_totals(program, 7.0, 0, 0)

    def test_the_activated_course_joins_the_status_filtered_sequence_read(
        self, api, build, director_headers
    ):
        """PRD §3.1: "Revising a course accepts any subset of `status`, `credit_hours`, `articulated_credit_hours`, `articulation_verified`, `prerequisite_course_id` and `position`, and is subject to the same two prerequisite rules."

        PRD §4: "sequence courses by `segment` or `status`"

        Design: Corner/endpoints/patch_endpoints_update_only_the_supplied_fields_and_bump_the_version
        """
        program_id, opener_id, follow_on_id = _patchable_program(build)

        validate_unpaginated(
            api.patch_course(
                follow_on_id,
                f.course_patch(status=k.COURSE_ACTIVE, credit_hours=3.0),
                director_headers,
            ),
            200,
        )

        rows, meta = validate_paginated(
            api.list_program_courses(
                program_id, director_headers, f.page(status=k.COURSE_ACTIVE)
            )
        )
        assert meta["total_count"] == 2
        assert_same_ids(rows, [opener_id, follow_on_id])


def _approved_program_with_a_certified_charge(build):
    """A state-approved program, a funded award and one certified consumable line."""
    scenario = build.program("51.3801", stop_at=STOP_STATE_APPROVED)
    grant = build.grant()
    charge = build.certified_expenditure(
        grant.grant_id, scenario.program_id, k.CATEGORY_CONSUMABLE, 100000
    )
    return scenario, grant, charge


def _concentrator(build, scenario):
    """One student carrying two credit hours and one verified attainment."""
    student = build.enroll(scenario.program_id, "100000001")
    build.post_credit(student["id"], scenario.secondary_course_id, 2.0)
    build.attain(student["id"], scenario.credential_id)
    return student["id"]


class TestDeclaredSideEffects:
    """An exit reclassifies the student; an obligation leaves the ledger alone."""

    def test_an_exit_carries_a_credentialled_concentrator_to_completer(
        self, api, build, registrar_headers
    ):
        """PRD §3.6: "`concentrator_status` is decided by a three-way ladder evaluated top to bottom: the student is a `COMPLETER` when `cte_credits_earned` is at least 2.0 credit hours **and** `exited_on` is non-null **and** `verified_qualifying_attainment_count` is at least 1; failing that, the student is a `CONCENTRATOR` when `cte_credits_earned` alone is at least 2.0 credit hours; failing that, the student is a `PARTICIPANT`."

        Design: Corner/endpoints/student_exit_and_expenditure_obligation_apply_their_declared_side_effects
        """
        scenario, _, _ = _approved_program_with_a_certified_charge(build)
        student_id = _concentrator(build, scenario)

        validate_unpaginated(
            api.exit_student(
                student_id,
                f.exit_payload("2026-07-31", k.EXIT_GRADUATED),
                registrar_headers,
            ),
            200,
        )

        student = validate_unpaginated(api.get_student(student_id, registrar_headers))
        assert student["concentrator_status"] == k.CONCENTRATOR_COMPLETER

    def test_an_exit_records_the_date_and_the_federal_exit_reason(
        self, api, build, registrar_headers
    ):
        """PRD §3.6: "Recording an exit supplies an `exited_on` date and an `exit_reason` of `GRADUATED`, `TRANSFERRED` or `WITHDREW`. Until an exit is recorded the student is treated as still enrolled and `exited_on` stays null."

        Design: Corner/endpoints/student_exit_and_expenditure_obligation_apply_their_declared_side_effects
        """
        scenario, _, _ = _approved_program_with_a_certified_charge(build)
        student_id = _concentrator(build, scenario)
        before = validate_unpaginated(api.get_student(student_id, registrar_headers))
        assert before["exited_on"] is None

        validate_unpaginated(
            api.exit_student(
                student_id,
                f.exit_payload("2026-07-31", k.EXIT_GRADUATED),
                registrar_headers,
            ),
            200,
        )

        student = validate_unpaginated(api.get_student(student_id, registrar_headers))
        assert student["exited_on"] == "2026-07-31"
        assert student["exit_reason"] == k.EXIT_GRADUATED

    def test_an_exit_leaves_the_credit_balance_and_attainment_count_as_they_were(
        self, api, build, registrar_headers
    ):
        """PRD §3.6: "First, `cte_credits_earned` is rebuilt as the sum of `credit_delta` across every accepted posting for that student whose target course was in `status` `ACTIVE` at the time of posting, rounded half-up to two decimal places. Second, `verified_qualifying_attainment_count` is rebuilt as the number of that student's attainment records whose `counted_for_indicator` is true."

        Design: Corner/endpoints/student_exit_and_expenditure_obligation_apply_their_declared_side_effects
        """
        scenario, _, _ = _approved_program_with_a_certified_charge(build)
        student_id = _concentrator(build, scenario)

        validate_unpaginated(
            api.exit_student(
                student_id,
                f.exit_payload("2026-07-31", k.EXIT_GRADUATED),
                registrar_headers,
            ),
            200,
        )

        student = validate_unpaginated(api.get_student(student_id, registrar_headers))
        assert_credit_hours(student["cte_credits_earned"], 2.0)
        assert student["verified_qualifying_attainment_count"] == 1

    def test_obligation_records_the_purchase_order_and_advances_the_line(
        self, api, build, fiscal_headers
    ):
        """PRD §3.7: "Obligating a certified line records the purchase order. The request carries an `obligation_reference`, the expenditure moves `CERTIFIED → OBLIGATED`, and the logical clock's date must still be on or before the award's `obligation_window_end` or the call fails with `ERR_GRANT_WINDOW_CLOSED`."

        Design: Corner/endpoints/student_exit_and_expenditure_obligation_apply_their_declared_side_effects
        """
        _, _, charge = _approved_program_with_a_certified_charge(build)
        assert charge["status"] == k.EXP_CERTIFIED

        obligated = validate_unpaginated(
            api.obligate_expenditure(
                charge["id"], f.obligate_payload("PO-2026-0001"), fiscal_headers
            ),
            200,
        )

        assert obligated["status"] == k.EXP_OBLIGATED
        assert obligated["obligation_reference"] == "PO-2026-0001"

    def test_obligation_does_not_reprice_the_line(self, api, build, fiscal_headers):
        """PRD §3.7: "Obligation increments only the expenditure's `version`; because both `CERTIFIED` and `OBLIGATED` rows are countable, the ledger totals do not move."

        Design: Corner/endpoints/student_exit_and_expenditure_obligation_apply_their_declared_side_effects
        """
        _, _, charge = _approved_program_with_a_certified_charge(build)
        assert_cents(charge["approved_cents"], 85000, "approved_cents")

        obligated = validate_unpaginated(
            api.obligate_expenditure(
                charge["id"], f.obligate_payload("PO-2026-0001"), fiscal_headers
            ),
            200,
        )

        assert_cents(obligated["approved_cents"], 85000, "approved_cents")
        assert_version_bumped_by(charge["version"], obligated["version"], 1)

    def test_obligation_leaves_every_ledger_figure_untouched(
        self, api, build, fiscal_headers
    ):
        """PRD §3.7: "Obligation increments only the expenditure's `version`; because both `CERTIFIED` and `OBLIGATED` rows are countable, the ledger totals do not move."

        PRD §3.7: "Step one computes `direct_obligated_cents` as the sum of `approved_cents` over the award's expenditures whose `status` is `CERTIFIED` or `OBLIGATED`; `REQUESTED`, `BLOCKED`, `DISALLOWED` and `VOIDED` rows are excluded, which is exactly what makes a void an exact compensation."

        Design: Corner/endpoints/student_exit_and_expenditure_obligation_apply_their_declared_side_effects
        """
        _, grant, charge = _approved_program_with_a_certified_charge(build)

        validate_unpaginated(
            api.obligate_expenditure(
                charge["id"], f.obligate_payload("PO-2026-0001"), fiscal_headers
            ),
            200,
        )

        award = validate_unpaginated(api.get_grant(grant.grant_id, fiscal_headers))
        assert_ledger(award, 85000, 0.0812, 6902, 91902, 4908098, 0)


def _two_milestones():
    return [
        f.milestone("Retool the fabrication lab", "2026-10-01"),
        f.milestone("Recruit an industry mentor", "2026-11-01"),
    ]


def _escalated_indicator_with_two_charges(build):
    """An escalated indicator, one certified charge and one blocked charge."""
    scenario = build.program("12.0503", stop_at=STOP_STATE_APPROVED)
    grant = build.grant()
    funded = build.certified_expenditure(
        grant.grant_id, scenario.program_id, k.CATEGORY_CONSUMABLE, 100000
    )
    build.cohort(scenario, 5, verified_count=2)
    indicator = build.agreed_indicator(
        scenario.program_id, k.INDICATOR_4S1_CREDENTIAL, 90.0
    )
    pending = build.expenditure(
        grant.grant_id, scenario.program_id, k.CATEGORY_CONSUMABLE, 50000
    )
    build.miss_twice(indicator["id"])
    return indicator["id"], funded["id"], pending["id"]


class TestImprovementPlanFundingLink:
    """A plan's funding pointer is validated at both ends, at draft and at submit."""

    def test_a_blocked_funding_line_cannot_finance_a_plan(
        self, api, build, director_headers
    ):
        """PRD §3.9: "Funding, when claimed, must be real: a non-null `funding_expenditure_id` must point at an expenditure whose `status` is `CERTIFIED` or `OBLIGATED` and which is charged to the same program of study as the plan's indicator. A pointer to a merely requested, blocked, disallowed or voided line, or to a line charged to a different program, is refused with `ERR_PLAN_FUNDING_INVALID`."

        Design: Corner/endpoints/improvement_plan_links_to_its_funding_expenditure_and_both_ends_are_validated
        """
        indicator_id, _, blocked_id = _escalated_indicator_with_two_charges(build)

        validate_error(
            api.draft_plan(
                indicator_id,
                f.plan_payload(f.three_milestones(), funding_expenditure_id=blocked_id),
                director_headers,
            ),
            errors.ERR_PLAN_FUNDING_INVALID,
        )

    def test_a_drafted_plan_records_its_milestone_count_and_funding_line(
        self, api, build, director_headers
    ):
        """PRD §3.9: "The new plan lands in `status` `DRAFT` with `revision_round` 0, `milestone_count` set to the number of elements in `milestones`, an empty `return_reasons` list, and `submitted_at` and `accepted_at` both null."

        Design: Corner/endpoints/improvement_plan_links_to_its_funding_expenditure_and_both_ends_are_validated
        """
        indicator_id, funded_id, _ = _escalated_indicator_with_two_charges(build)

        plan = validate_unpaginated(
            api.draft_plan(
                indicator_id,
                f.plan_payload(_two_milestones(), funding_expenditure_id=funded_id),
                director_headers,
            ),
            201,
        )

        assert plan["status"] == k.PLAN_DRAFT
        assert plan["milestone_count"] == 2
        assert plan["funding_expenditure_id"] == funded_id
        assert plan["submitted_at"] is None
        assert plan["accepted_at"] is None

    def test_a_two_milestone_plan_is_refused_at_submit(
        self, api, build, director_headers
    ):
        """PRD §3.9: "Substance is checked at submit time: `milestone_count` must be at least 3, and a thinner plan is refused with `ERR_MILESTONES_INSUFFICIENT`."

        Design: Corner/endpoints/improvement_plan_links_to_its_funding_expenditure_and_both_ends_are_validated
        """
        indicator_id, funded_id, _ = _escalated_indicator_with_two_charges(build)
        thin = build.draft_plan(
            indicator_id, _two_milestones(), funding_expenditure_id=funded_id
        )

        validate_error(
            api.submit_plan(thin["id"], f.plan_submit_payload(), director_headers),
            errors.ERR_MILESTONES_INSUFFICIENT,
        )

    def test_a_three_milestone_plan_counts_all_three_milestones(
        self, api, build, director_headers
    ):
        """PRD §3.9: "The new plan lands in `status` `DRAFT` with `revision_round` 0, `milestone_count` set to the number of elements in `milestones`, an empty `return_reasons` list, and `submitted_at` and `accepted_at` both null."

        Design: Corner/endpoints/improvement_plan_links_to_its_funding_expenditure_and_both_ends_are_validated
        """
        indicator_id, funded_id, _ = _escalated_indicator_with_two_charges(build)

        plan = validate_unpaginated(
            api.draft_plan(
                indicator_id,
                f.plan_payload(f.three_milestones(), funding_expenditure_id=funded_id),
                director_headers,
            ),
            201,
        )

        assert plan["milestone_count"] == 3
        assert plan["status"] == k.PLAN_DRAFT
        assert plan["return_reasons"] == []

    def test_submitting_stamps_the_clock_instant_and_leaves_the_revision_counter_at_zero(
        self, api, build, director_headers
    ):
        """PRD §3.9: "Submitting a plan — optionally with a `submission_note` — moves it `DRAFT → SUBMITTED` on the first attempt and `RETURNED → SUBMITTED` on any revision, sets `submitted_at` to the current logical clock instant, and increments the plan's `version`."

        PRD §2.5: "Before any client sets it, that clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back to real wall-clock time."

        Design: Corner/endpoints/improvement_plan_links_to_its_funding_expenditure_and_both_ends_are_validated
        """
        indicator_id, funded_id, _ = _escalated_indicator_with_two_charges(build)
        plan = build.draft_plan(
            indicator_id, f.three_milestones(), funding_expenditure_id=funded_id
        )

        submitted = validate_unpaginated(
            api.submit_plan(plan["id"], f.plan_submit_payload(), director_headers), 200
        )

        assert submitted["status"] == k.PLAN_SUBMITTED
        assert submitted["revision_round"] == 0
        assert_instant_equals(submitted["submitted_at"], k.CLOCK_EPOCH_ISO)

    def test_a_submitted_plan_cannot_be_submitted_again(
        self, api, build, director_headers
    ):
        """PRD §3.9: "Submitting a plan — optionally with a `submission_note` — moves it `DRAFT → SUBMITTED` on the first attempt and `RETURNED → SUBMITTED` on any revision, sets `submitted_at` to the current logical clock instant, and increments the plan's `version`."

        PRD §2.8: "When an action endpoint asks a record to make a transition its current state does not declare, the request is refused at priority 9 with the code belonging to that axis: `ERR_INVALID_APPROVAL_TRANSITION` for `approval_status`, `ERR_INVALID_CLNA_PHASE_TRANSITION` for `clna_phase` (including a requested `to_phase` that is not the declared successor of the current phase), `ERR_INVALID_EXPENDITURE_STATE` for `Expenditure.status`, `ERR_INVALID_INDICATOR_STATE` for `PerformanceIndicator.status`, `ERR_INVALID_PLAN_STATE` for `ImprovementPlan.status`, `ERR_INVALID_MEETING_STATE` for `CommitteeMeeting.minutes_status`, and `ERR_INVALID_EDUCATOR_STATE` for `Educator.status`."

        Design: Corner/endpoints/improvement_plan_links_to_its_funding_expenditure_and_both_ends_are_validated
        """
        indicator_id, funded_id, _ = _escalated_indicator_with_two_charges(build)
        plan = build.draft_plan(
            indicator_id, f.three_milestones(), funding_expenditure_id=funded_id
        )
        build.submit_plan(plan["id"])

        validate_error(
            api.submit_plan(plan["id"], f.plan_submit_payload(), director_headers),
            errors.ERR_INVALID_PLAN_STATE,
        )

    def test_acceptance_stamps_the_acceptance_instant(
        self, api, build, reviewer_headers
    ):
        """PRD §3.9: "The plan moves `SUBMITTED → ACCEPTED`, `accepted_at` is set to the current logical clock instant, and the chain runs."

        PRD §2.5: "Before any client sets it, that clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back to real wall-clock time."

        Design: Corner/endpoints/improvement_plan_links_to_its_funding_expenditure_and_both_ends_are_validated
        """
        indicator_id, funded_id, _ = _escalated_indicator_with_two_charges(build)
        plan = build.draft_plan(
            indicator_id, f.three_milestones(), funding_expenditure_id=funded_id
        )
        build.submit_plan(plan["id"])

        accepted = validate_unpaginated(
            api.accept_plan(plan["id"], f.plan_accept_payload(), reviewer_headers), 200
        )

        assert accepted["status"] == k.PLAN_ACCEPTED
        assert_instant_equals(accepted["accepted_at"], k.CLOCK_EPOCH_ISO)

    def test_acceptance_returns_the_parent_indicator_to_monitoring(
        self, api, build, reviewer_headers
    ):
        """PRD §3.9: "Link 2: the parent indicator moves `IMPROVEMENT_REQUIRED → MONITORING` with `consecutive_miss_count` reset to 0."

        Design: Corner/endpoints/improvement_plan_links_to_its_funding_expenditure_and_both_ends_are_validated
        """
        indicator_id, funded_id, _ = _escalated_indicator_with_two_charges(build)
        plan = build.draft_plan(
            indicator_id, f.three_milestones(), funding_expenditure_id=funded_id
        )
        build.submit_plan(plan["id"])
        build.accept_plan(plan["id"])

        indicator = validate_unpaginated(
            api.get_indicator(indicator_id, reviewer_headers)
        )
        assert indicator["status"] == k.PI_MONITORING
        assert indicator["consecutive_miss_count"] == 0

    def test_the_sibling_draft_plan_is_left_alone(self, api, build, director_headers):
        """PRD §3.9: "The new plan lands in `status` `DRAFT` with `revision_round` 0, `milestone_count` set to the number of elements in `milestones`, an empty `return_reasons` list, and `submitted_at` and `accepted_at` both null."

        Design: Corner/endpoints/improvement_plan_links_to_its_funding_expenditure_and_both_ends_are_validated
        """
        indicator_id, funded_id, _ = _escalated_indicator_with_two_charges(build)
        funded_plan = build.draft_plan(
            indicator_id, f.three_milestones(), funding_expenditure_id=funded_id
        )
        sibling = build.draft_plan(indicator_id, _two_milestones())
        build.submit_plan(funded_plan["id"])
        build.accept_plan(funded_plan["id"])

        untouched = validate_unpaginated(
            api.get_plan(sibling["id"], director_headers)
        )
        assert untouched["status"] == k.PLAN_DRAFT
        assert untouched["revision_round"] == 0
        assert untouched["funding_expenditure_id"] is None

    def test_plans_can_be_filtered_by_their_parent_indicator(
        self, api, build, director_headers
    ):
        """PRD §4: "Collection reads accept the `limit` and `offset` parameters of §2.3 plus the filters named in their descriptions"

        PRD §4: "improvement plans by `performance_indicator_id` or `funding_expenditure_id`"

        Design: Corner/endpoints/improvement_plan_links_to_its_funding_expenditure_and_both_ends_are_validated
        """
        indicator_id, funded_id, _ = _escalated_indicator_with_two_charges(build)
        funded_plan = build.draft_plan(
            indicator_id, f.three_milestones(), funding_expenditure_id=funded_id
        )
        sibling = build.draft_plan(indicator_id, _two_milestones())

        rows, meta = validate_paginated(
            api.list_plans(
                director_headers, f.page(performance_indicator_id=indicator_id)
            )
        )

        assert meta["total_count"] == 2
        assert sorted(ids_of(rows)) == sorted([funded_plan["id"], sibling["id"]])


def _branching_sequence(build):
    """A four-course sequence that forks at the opener: A -> B -> C and A -> E."""
    program = build.create_program("47.0303", title="Industrial Maintenance")
    opener = build.add_course(
        program["id"], f.secondary_course("CRS-A", 1, 4.0, status=k.COURSE_ACTIVE)
    )
    middle = build.add_course(
        program["id"],
        f.secondary_course(
            "CRS-B", 2, 3.0, status=k.COURSE_ACTIVE, prerequisite_course_id=opener["id"]
        ),
    )
    capstone = build.add_course(
        program["id"],
        f.postsecondary_course(
            "CRS-C",
            3,
            3.0,
            3.0,
            True,
            status=k.COURSE_ACTIVE,
            prerequisite_course_id=middle["id"],
        ),
    )
    branch = build.add_course(
        program["id"],
        f.secondary_course(
            "CRS-E", 4, 2.0, status=k.COURSE_ACTIVE, prerequisite_course_id=opener["id"]
        ),
    )
    return opener["id"], middle["id"], capstone["id"], branch["id"]


class TestPrerequisiteDependents:
    """The dependents read answers the courses naming this course as prerequisite."""

    def test_every_course_reports_its_hop_count_back_to_the_opener(
        self, api, build, director_headers
    ):
        """PRD §3.1: "The server computes `depth_from_root`, the number of prerequisite hops from the course back to a course whose `prerequisite_course_id` is null, by walking the chain; a course that opens the sequence has `depth_from_root` 0."

        Design: Corner/endpoints/dependents_read_returns_the_transitive_prerequisite_closure
        """
        opener_id, middle_id, capstone_id, branch_id = _branching_sequence(build)

        depths = {
            course_id: validate_unpaginated(
                api.get_course(course_id, director_headers)
            )["depth_from_root"]
            for course_id in (opener_id, middle_id, capstone_id, branch_id)
        }

        assert depths[opener_id] == 0
        assert depths[middle_id] == 1
        assert depths[capstone_id] == 2
        assert depths[branch_id] == 1

    def test_the_opener_reports_both_courses_that_name_it_as_prerequisite(
        self, api, build, director_headers
    ):
        """PRD §4: "List the sequence courses that name this course as their prerequisite."

        PRD §2.3: "`total_count` is the number of records matching the filter before the page window is applied, and `has_more` is true exactly when records remain beyond the current window."

        Design: Corner/endpoints/dependents_read_returns_the_transitive_prerequisite_closure
        """
        opener_id, middle_id, _, branch_id = _branching_sequence(build)

        rows, meta = validate_paginated(
            api.list_course_dependents(opener_id, director_headers)
        )

        assert meta["total_count"] == 2
        assert meta["has_more"] is False
        assert_same_ids(rows, [middle_id, branch_id])

    def test_a_mid_chain_course_reports_only_its_own_successor(
        self, api, build, director_headers
    ):
        """PRD §4: "List the sequence courses that name this course as their prerequisite."

        Design: Corner/endpoints/dependents_read_returns_the_transitive_prerequisite_closure
        """
        _, middle_id, capstone_id, _ = _branching_sequence(build)

        rows, meta = validate_paginated(
            api.list_course_dependents(middle_id, director_headers)
        )

        assert meta["total_count"] == 1
        assert_same_ids(rows, [capstone_id])

    def test_a_leaf_course_reports_no_dependents(self, api, build, director_headers):
        """PRD §4: "List the sequence courses that name this course as their prerequisite."

        Design: Corner/endpoints/dependents_read_returns_the_transitive_prerequisite_closure
        """
        _, _, capstone_id, branch_id = _branching_sequence(build)

        for leaf_id in (capstone_id, branch_id):
            rows, meta = validate_paginated(
                api.list_course_dependents(leaf_id, director_headers)
            )
            assert rows == []
            assert meta["total_count"] == 0
            assert meta["has_more"] is False

    def test_the_dependents_read_windows_its_rows(self, api, build, director_headers):
        """PRD §2.3: "List responses populate all four pagination fields in `meta`: `limit` and `offset` echo the values in force for the page, `total_count` is the number of records matching the filter before the page window is applied, and `has_more` is true exactly when records remain beyond the current window."

        Design: Corner/endpoints/dependents_read_returns_the_transitive_prerequisite_closure
        """
        opener_id, _, _, _ = _branching_sequence(build)

        rows, meta = validate_paginated(
            api.list_course_dependents(opener_id, director_headers, f.page(limit=1))
        )

        assert len(rows) == 1
        assert meta["limit"] == 1
        assert meta["offset"] == 0
        assert meta["total_count"] == 2
        assert meta["has_more"] is True


def _filterable_district(build):
    """A fully authored program, a 2027 award and one agreed 2027 indicator."""
    scenario = build.program("11.0801", stop_at=STOP_STATE_APPROVED)
    grant = build.grant(fiscal_year=2027)
    indicator = build.agreed_indicator(
        scenario.program_id, k.INDICATOR_4S1_CREDENTIAL, 90.0, reporting_year=2027
    )
    return scenario, grant, indicator


class TestDeclaredCollectionFilters:
    """Every filter the endpoint catalogue declares selects and deselects rows."""

    def test_credentials_are_filtered_by_tier(self, api, build, director_headers):
        """PRD §4: "Collection reads accept the `limit` and `offset` parameters of §2.3 plus the filters named in their descriptions"

        PRD §4: "credentials by `tier`"

        Design: Corner/endpoints/collection_reads_expose_every_declared_filter_and_paginate
        """
        scenario, _, _ = _filterable_district(build)

        selected, selected_meta = validate_paginated(
            api.list_program_credentials(
                scenario.program_id, director_headers, f.page(tier=k.TIER_NATIONAL)
            )
        )
        _, empty_meta = validate_paginated(
            api.list_program_credentials(
                scenario.program_id, director_headers, f.page(tier=k.TIER_LOCAL)
            )
        )

        assert selected_meta["total_count"] == 1
        assert_same_ids(selected, [scenario.credential_id])
        assert empty_meta["total_count"] == 0

    def test_one_credential_reads_back_with_its_federal_counting_flag(
        self, api, build, director_headers
    ):
        """PRD §3.1: "The server sets `counts_toward_indicator` to true when the `tier` is `STATE_RECOGNIZED` or `NATIONAL`, and to false when the `tier` is `LOCAL` — locally recognised credentials are legitimate to award but never enter a federal performance numerator."

        PRD §4: "Retrieve one industry-recognized credential definition."

        Design: Corner/endpoints/collection_reads_expose_every_declared_filter_and_paginate
        """
        scenario, _, _ = _filterable_district(build)

        credential = validate_unpaginated(
            api.get_credential(scenario.credential_id, director_headers)
        )

        assert credential["code"] == "CRED-1"
        assert credential["tier"] == k.TIER_NATIONAL
        assert credential["counts_toward_indicator"] is True

    def test_committees_are_filtered_by_status(self, api, build, director_headers):
        """PRD §4: "committees, members, meetings, expenditures, indicators, plans and educators by `status`"

        PRD §3.3: "The committee then flips `FORMING → ACTIVE` the moment all three conditions hold at once: `active_member_count` is at least `quorum_min_members`, `employer_member_count` is at least `employer_seat_min`, and `chair_member_id` is non-null."

        Design: Corner/endpoints/collection_reads_expose_every_declared_filter_and_paginate
        """
        scenario, _, _ = _filterable_district(build)

        selected, selected_meta = validate_paginated(
            api.list_program_committees(
                scenario.program_id, director_headers, f.page(status=k.COMMITTEE_ACTIVE)
            )
        )
        _, empty_meta = validate_paginated(
            api.list_program_committees(
                scenario.program_id,
                director_headers,
                f.page(status=k.COMMITTEE_FORMING),
            )
        )

        assert selected_meta["total_count"] == 1
        assert_same_ids(selected, [scenario.committee_id])
        assert empty_meta["total_count"] == 0

    def test_committee_members_are_filtered_by_sector(
        self, api, build, director_headers
    ):
        """PRD §4: "additionally members by `sector`"

        PRD §3.3: "`employer_member_count` becomes the number of those whose `sector` is also `EMPLOYER`"

        Design: Corner/endpoints/collection_reads_expose_every_declared_filter_and_paginate
        """
        scenario, _, _ = _filterable_district(build)

        _, employer_meta = validate_paginated(
            api.list_committee_members(
                scenario.committee_id, director_headers, f.page(sector=k.SECTOR_EMPLOYER)
            )
        )
        _, labor_meta = validate_paginated(
            api.list_committee_members(
                scenario.committee_id, director_headers, f.page(sector=k.SECTOR_LABOR)
            )
        )

        assert employer_meta["total_count"] == 2
        assert labor_meta["total_count"] == 0

    def test_committee_meetings_are_filtered_by_agenda_kind(
        self, api, build, director_headers
    ):
        """PRD §4: "meetings by `agenda_kind` or `minutes_status`"

        PRD §3.3: "Scheduling one requires an `agenda_kind` of `CLNA_STAKEHOLDER`, `POS_ENDORSEMENT` or `EQUIPMENT_REVIEW` — each purpose unlocks a different downstream gate — and a `scheduled_for` instant."

        Design: Corner/endpoints/collection_reads_expose_every_declared_filter_and_paginate
        """
        scenario, _, _ = _filterable_district(build)

        stakeholder, stakeholder_meta = validate_paginated(
            api.list_committee_meetings(
                scenario.committee_id,
                director_headers,
                f.page(agenda_kind=k.AGENDA_CLNA_STAKEHOLDER),
            )
        )
        _, equipment_meta = validate_paginated(
            api.list_committee_meetings(
                scenario.committee_id,
                director_headers,
                f.page(agenda_kind=k.AGENDA_EQUIPMENT_REVIEW),
            )
        )

        assert stakeholder_meta["total_count"] == 2
        assert_same_ids(stakeholder, scenario.clna_meeting_ids)
        assert equipment_meta["total_count"] == 0

    def test_committee_meetings_are_filtered_by_minutes_status(
        self, api, build, director_headers
    ):
        """PRD §4: "meetings by `agenda_kind` or `minutes_status`"

        PRD §3.3: "A filing without an `amendment_reason` moves the meeting `SCHEDULED → FINALIZED`, writing `held_at`, `attendee_member_ids`, `vote_yes`, `vote_no` and `minutes_url` from the request and recomputing `eligible_attendee_count`, `employer_attendee_count`, `quorum_met` and `endorsement_passed`."

        Design: Corner/endpoints/collection_reads_expose_every_declared_filter_and_paginate
        """
        scenario, _, _ = _filterable_district(build)

        _, finalized_meta = validate_paginated(
            api.list_committee_meetings(
                scenario.committee_id,
                director_headers,
                f.page(minutes_status=k.MINUTES_FINALIZED),
            )
        )
        _, scheduled_meta = validate_paginated(
            api.list_committee_meetings(
                scenario.committee_id,
                director_headers,
                f.page(minutes_status=k.MINUTES_SCHEDULED),
            )
        )

        assert finalized_meta["total_count"] == 3
        assert scheduled_meta["total_count"] == 0

    def test_educators_are_filtered_by_status(self, api, build, reviewer_headers):
        """PRD §4: "committees, members, meetings, expenditures, indicators, plans and educators by `status`"

        PRD §3.5: "When the post-tranche total reaches the route's floor and the logical clock's date is on or before `credential_expires_on`, the educator moves `PROVISIONAL → ELIGIBLE`."

        Design: Corner/endpoints/collection_reads_expose_every_declared_filter_and_paginate
        """
        scenario, _, _ = _filterable_district(build)

        eligible, eligible_meta = validate_paginated(
            api.list_program_educators(
                scenario.program_id,
                reviewer_headers,
                f.page(status=k.EDUCATOR_ELIGIBLE),
            )
        )
        _, lapsed_meta = validate_paginated(
            api.list_program_educators(
                scenario.program_id, reviewer_headers, f.page(status=k.EDUCATOR_LAPSED)
            )
        )

        assert eligible_meta["total_count"] == 1
        assert_same_ids(eligible, [scenario.educator_id])
        assert lapsed_meta["total_count"] == 0

    def test_educators_are_filtered_by_certification_route(
        self, api, build, reviewer_headers
    ):
        """PRD §4: "educators by `certification_route`"

        PRD §3.5: "The `INDUSTRY_EXPERIENCE` route demands 4,000 verified hours — two full years at a 2,000-hour work year — before the instructor is certifiable."

        Design: Corner/endpoints/collection_reads_expose_every_declared_filter_and_paginate
        """
        scenario, _, _ = _filterable_district(build)

        industry, industry_meta = validate_paginated(
            api.list_program_educators(
                scenario.program_id,
                reviewer_headers,
                f.page(certification_route=k.ROUTE_INDUSTRY_EXPERIENCE),
            )
        )
        _, traditional_meta = validate_paginated(
            api.list_program_educators(
                scenario.program_id,
                reviewer_headers,
                f.page(certification_route=k.ROUTE_TRADITIONAL),
            )
        )

        assert industry_meta["total_count"] == 1
        assert_same_ids(industry, [scenario.educator_id])
        assert traditional_meta["total_count"] == 0

    def test_indicators_are_filtered_by_reporting_year(
        self, api, build, reviewer_headers
    ):
        """PRD §4: "indicators by `reporting_year`"

        Design: Corner/endpoints/collection_reads_expose_every_declared_filter_and_paginate
        """
        scenario, _, indicator = _filterable_district(build)

        selected, selected_meta = validate_paginated(
            api.list_program_indicators(
                scenario.program_id, reviewer_headers, f.page(reporting_year=2027)
            )
        )
        _, empty_meta = validate_paginated(
            api.list_program_indicators(
                scenario.program_id, reviewer_headers, f.page(reporting_year=2026)
            )
        )

        assert selected_meta["total_count"] == 1
        assert_same_ids(selected, [indicator["id"]])
        assert empty_meta["total_count"] == 0

    def test_indicators_are_filtered_by_status(self, api, build, reviewer_headers):
        """PRD §4: "committees, members, meetings, expenditures, indicators, plans and educators by `status`"

        PRD §3.8: "Accepting the standing offer moves `NEGOTIATING → AGREED` and may carry an `acceptance_note`."

        Design: Corner/endpoints/collection_reads_expose_every_declared_filter_and_paginate
        """
        scenario, _, indicator = _filterable_district(build)

        agreed, agreed_meta = validate_paginated(
            api.list_program_indicators(
                scenario.program_id, reviewer_headers, f.page(status=k.PI_AGREED)
            )
        )
        _, proposed_meta = validate_paginated(
            api.list_program_indicators(
                scenario.program_id, reviewer_headers, f.page(status=k.PI_PROPOSED)
            )
        )

        assert agreed_meta["total_count"] == 1
        assert_same_ids(agreed, [indicator["id"]])
        assert proposed_meta["total_count"] == 0

    def test_grant_awards_are_filtered_by_fiscal_year(self, api, build, fiscal_headers):
        """PRD §4: "grant awards by `fiscal_year`"

        Design: Corner/endpoints/collection_reads_expose_every_declared_filter_and_paginate
        """
        _, grant, _ = _filterable_district(build)

        selected, selected_meta = validate_paginated(
            api.list_grants(fiscal_headers, f.page(fiscal_year=2027))
        )
        _, empty_meta = validate_paginated(
            api.list_grants(fiscal_headers, f.page(fiscal_year=2028))
        )

        assert selected_meta["total_count"] == 1
        assert_same_ids(selected, [grant.grant_id])
        assert empty_meta["total_count"] == 0

    def test_a_collection_read_windows_its_rows_and_counts_the_whole_match(
        self, api, build, director_headers
    ):
        """PRD §2.3: "List responses populate all four pagination fields in `meta`: `limit` and `offset` echo the values in force for the page, `total_count` is the number of records matching the filter before the page window is applied, and `has_more` is true exactly when records remain beyond the current window."

        Design: Corner/endpoints/collection_reads_expose_every_declared_filter_and_paginate
        """
        scenario, _, _ = _filterable_district(build)

        rows, meta = validate_paginated(
            api.list_committee_members(
                scenario.committee_id, director_headers, f.page(limit=2)
            )
        )

        assert len(rows) == 2
        assert meta["limit"] == 2
        assert meta["offset"] == 0
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
