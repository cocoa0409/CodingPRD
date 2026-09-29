"""Error reachability: every refusal in this module is reached through the API.

Each test drives the system to the exact state the refusal describes and probes
one refusal, so that a missing gate names itself rather than hiding behind a
neighbouring one.
"""

from test_helpers import (
    NON_EXISTENT_UUID,
    STOP_COMMITTEE_REVIEW,
    STOP_STATE_APPROVED,
    assert_alignment_index,
    assert_cents,
    assert_credit_hours,
    assert_error_envelope,
    assert_ledger,
    assert_pct,
    assert_quorum_figures,
    errors,
    f,
    k,
    validate_error,
    validate_unpaginated,
)

CLNA_MEETING_INSTANTS = ("2026-08-04T14:00:00.000Z", "2026-08-05T14:00:00.000Z")
SECOND_ENDORSEMENT_INSTANT = "2026-08-12T15:00:00.000Z"


class TestNotFoundReachability:
    """Every collection prefix answers its own not-found code."""

    def test_an_unknown_sequence_course_is_not_found(self, api, director_headers):
        """PRD §2.6: "Each collection prefix has its own not-found code"

        PRD §2.6: "`/cte/sequence-courses/{id}` yields `ERR_COURSE_NOT_FOUND`"

        PRD §2.6: "Every one of these is HTTP 404."

        Design: Corner/errors/every_remaining_not_found_error_is_reachable_through_its_own_read_endpoint
        """
        response = api.get_course(NON_EXISTENT_UUID, director_headers)

        validate_error(response, errors.ERR_COURSE_NOT_FOUND)
        assert_error_envelope(response)

    def test_an_unknown_credential_attainment_is_not_found(
        self, api, registrar_headers
    ):
        """PRD §2.6: "Each collection prefix has its own not-found code"

        PRD §2.6: "`/cte/credential-attainments/{id}` yields `ERR_ATTAINMENT_NOT_FOUND`"

        PRD §2.6: "Every one of these is HTTP 404."

        Design: Corner/errors/every_remaining_not_found_error_is_reachable_through_its_own_read_endpoint
        """
        response = api.get_attainment(NON_EXISTENT_UUID, registrar_headers)

        validate_error(response, errors.ERR_ATTAINMENT_NOT_FOUND)
        assert_error_envelope(response)

    def test_an_unknown_committee_member_is_not_found(self, api, director_headers):
        """PRD §2.6: "Each collection prefix has its own not-found code"

        PRD §2.6: "`/cte/committee-members/{id}` yields `ERR_MEMBER_NOT_FOUND`"

        PRD §2.6: "Every one of these is HTTP 404."

        Design: Corner/errors/every_remaining_not_found_error_is_reachable_through_its_own_read_endpoint
        """
        response = api.get_member(NON_EXISTENT_UUID, director_headers)

        validate_error(response, errors.ERR_MEMBER_NOT_FOUND)
        assert_error_envelope(response)

    def test_an_unknown_committee_meeting_is_not_found(self, api, director_headers):
        """PRD §2.6: "Each collection prefix has its own not-found code"

        PRD §2.6: "`/cte/committee-meetings/{id}` yields `ERR_MEETING_NOT_FOUND`"

        PRD §2.6: "Every one of these is HTTP 404."

        Design: Corner/errors/every_remaining_not_found_error_is_reachable_through_its_own_read_endpoint
        """
        response = api.get_meeting(NON_EXISTENT_UUID, director_headers)

        validate_error(response, errors.ERR_MEETING_NOT_FOUND)
        assert_error_envelope(response)

    def test_an_unknown_expenditure_is_not_found(self, api, fiscal_headers):
        """PRD §2.6: "Each collection prefix has its own not-found code"

        PRD §2.6: "`/cte/expenditures/{id}` yields `ERR_EXPENDITURE_NOT_FOUND`"

        PRD §2.6: "Every one of these is HTTP 404."

        Design: Corner/errors/every_remaining_not_found_error_is_reachable_through_its_own_read_endpoint
        """
        response = api.get_expenditure(NON_EXISTENT_UUID, fiscal_headers)

        validate_error(response, errors.ERR_EXPENDITURE_NOT_FOUND)
        assert_error_envelope(response)

    def test_an_unknown_improvement_plan_is_not_found(self, api, fiscal_headers):
        """PRD §2.6: "Each collection prefix has its own not-found code"

        PRD §2.6: "`/cte/improvement-plans/{id}` yields `ERR_PLAN_NOT_FOUND`"

        PRD §2.6: "Every one of these is HTTP 404."

        Design: Corner/errors/every_remaining_not_found_error_is_reachable_through_its_own_read_endpoint
        """
        response = api.get_plan(NON_EXISTENT_UUID, fiscal_headers)

        validate_error(response, errors.ERR_PLAN_NOT_FOUND)
        assert_error_envelope(response)

    def test_an_unknown_educator_is_not_found(self, api, reviewer_headers):
        """PRD §2.6: "Each collection prefix has its own not-found code"

        PRD §2.6: "`/cte/educators/{id}` yields `ERR_EDUCATOR_NOT_FOUND`"

        PRD §2.6: "Every one of these is HTTP 404."

        Design: Corner/errors/every_remaining_not_found_error_is_reachable_through_its_own_read_endpoint
        """
        response = api.get_educator(NON_EXISTENT_UUID, reviewer_headers)

        validate_error(response, errors.ERR_EDUCATOR_NOT_FOUND)
        assert_error_envelope(response)


def _shell_awaiting_its_needs_assessment(build):
    """A draft program with an active committee and its stakeholder minutes on file."""
    program = build.create_program("14.1001", title="Electrical Engineering Technology")
    committee_row = build.charter_committee(program["id"])
    committee = build.seat_roster(committee_row["id"])
    for instant in CLNA_MEETING_INSTANTS:
        build.quorate_meeting(committee, k.AGENDA_CLNA_STAKEHOLDER, instant)
    return program["id"], committee


def _shell_with_certified_needs_assessment(build):
    program_id, committee = _shell_awaiting_its_needs_assessment(build)
    build.certify_clna(program_id)
    return program_id, committee


def _add_secondary_opener(build, program_id):
    return build.add_course(
        program_id, f.secondary_course("SEC-1", 1, 4.0, status=k.COURSE_ACTIVE)
    )["id"]


def _add_postsecondary_capstone(build, program_id, prerequisite_id):
    return build.add_course(
        program_id,
        f.postsecondary_course(
            "PSE-9",
            2,
            3.0,
            3.0,
            True,
            status=k.COURSE_ACTIVE,
            prerequisite_course_id=prerequisite_id,
        ),
    )["id"]


class TestSubmitGateOrder:
    """The six submission preconditions surface one at a time, in their order."""

    def test_a_program_whose_needs_assessment_is_not_certified_cannot_submit(
        self, api, build, director_headers
    ):
        """PRD §3.4: "The six preconditions, in the order their failures surface: the program's needs assessment must have been certified at least once, so `clna_phase` must be `CERTIFIED` or `EXPIRED` (otherwise `ERR_CLNA_NOT_CERTIFIED`); that certification must still be live, so the logical clock's date must not be past `clna_expires_on` (otherwise `ERR_CLNA_EXPIRED`); the sequence must be complete, meaning at least one course with `status` `ACTIVE` and `segment` `SECONDARY` **and** at least one course with `status` `ACTIVE` and `segment` `POSTSECONDARY` exist on the program (otherwise `ERR_SEQUENCE_INCOMPLETE`); the approved credential list must hold at least one credential (otherwise `ERR_CREDENTIAL_LIST_EMPTY`); and at least one educator on the program must be in `status` `ELIGIBLE` after the lazy credential-lapse re-evaluation described in §2.12 has run (otherwise `ERR_NO_ELIGIBLE_INSTRUCTOR`)."

        Design: Corner/errors/submit_gates_are_reachable_in_their_declared_priority_order
        """
        program_id, _ = _shell_awaiting_its_needs_assessment(build)

        validate_error(
            api.submit_program(program_id, f.submit_payload(), director_headers),
            errors.ERR_CLNA_NOT_CERTIFIED,
        )

    def test_a_program_with_no_courses_at_all_cannot_submit(
        self, api, build, director_headers
    ):
        """PRD §3.4: "the sequence must be complete, meaning at least one course with `status` `ACTIVE` and `segment` `SECONDARY` **and** at least one course with `status` `ACTIVE` and `segment` `POSTSECONDARY` exist on the program (otherwise `ERR_SEQUENCE_INCOMPLETE`)"

        Design: Corner/errors/submit_gates_are_reachable_in_their_declared_priority_order
        """
        program_id, _ = _shell_with_certified_needs_assessment(build)

        validate_error(
            api.submit_program(program_id, f.submit_payload(), director_headers),
            errors.ERR_SEQUENCE_INCOMPLETE,
        )

    def test_a_secondary_only_sequence_cannot_submit(
        self, api, build, director_headers
    ):
        """PRD §3.4: "the sequence must be complete, meaning at least one course with `status` `ACTIVE` and `segment` `SECONDARY` **and** at least one course with `status` `ACTIVE` and `segment` `POSTSECONDARY` exist on the program (otherwise `ERR_SEQUENCE_INCOMPLETE`)"

        Design: Corner/errors/submit_gates_are_reachable_in_their_declared_priority_order
        """
        program_id, _ = _shell_with_certified_needs_assessment(build)
        _add_secondary_opener(build, program_id)

        validate_error(
            api.submit_program(program_id, f.submit_payload(), director_headers),
            errors.ERR_SEQUENCE_INCOMPLETE,
        )

    def test_a_complete_sequence_with_no_credential_cannot_submit(
        self, api, build, director_headers
    ):
        """PRD §3.4: "the approved credential list must hold at least one credential (otherwise `ERR_CREDENTIAL_LIST_EMPTY`)"

        Design: Corner/errors/submit_gates_are_reachable_in_their_declared_priority_order
        """
        program_id, _ = _shell_with_certified_needs_assessment(build)
        opener_id = _add_secondary_opener(build, program_id)
        _add_postsecondary_capstone(build, program_id, opener_id)

        validate_error(
            api.submit_program(program_id, f.submit_payload(), director_headers),
            errors.ERR_CREDENTIAL_LIST_EMPTY,
        )

    def test_a_credentialled_program_with_no_eligible_instructor_cannot_submit(
        self, api, build, director_headers
    ):
        """PRD §3.4: "at least one educator on the program must be in `status` `ELIGIBLE` after the lazy credential-lapse re-evaluation described in §2.12 has run (otherwise `ERR_NO_ELIGIBLE_INSTRUCTOR`)"

        Design: Corner/errors/submit_gates_are_reachable_in_their_declared_priority_order
        """
        program_id, _ = _shell_with_certified_needs_assessment(build)
        opener_id = _add_secondary_opener(build, program_id)
        _add_postsecondary_capstone(build, program_id, opener_id)
        build.add_credential(program_id, "CRED-1")

        validate_error(
            api.submit_program(program_id, f.submit_payload(), director_headers),
            errors.ERR_NO_ELIGIBLE_INSTRUCTOR,
        )

    def test_verifying_the_full_industry_claim_makes_the_instructor_eligible(
        self, api, build, reviewer_headers
    ):
        """PRD §3.5: "The `INDUSTRY_EXPERIENCE` route demands 4,000 verified hours — two full years at a 2,000-hour work year — before the instructor is certifiable."

        PRD §3.5: "When the post-tranche total reaches the route's floor and the logical clock's date is on or before `credential_expires_on`, the educator moves `PROVISIONAL → ELIGIBLE`."

        Design: Corner/errors/submit_gates_are_reachable_in_their_declared_priority_order
        """
        program_id, _ = _shell_with_certified_needs_assessment(build)
        educator = build.add_educator(program_id, claimed_industry_hours=4200)

        verified = validate_unpaginated(
            api.verify_industry_hours(
                educator["id"],
                f.verification_payload(4200, k.SOURCE_EMPLOYER_LETTER),
                reviewer_headers,
            ),
            200,
        )

        assert verified["verified_industry_hours"] == 4200
        assert verified["status"] == k.EDUCATOR_ELIGIBLE

    def test_a_packet_that_clears_every_precondition_is_submitted(
        self, api, build, director_headers
    ):
        """PRD §3.4: "The six preconditions, in the order their failures surface: the program's needs assessment must have been certified at least once, so `clna_phase` must be `CERTIFIED` or `EXPIRED` (otherwise `ERR_CLNA_NOT_CERTIFIED`); that certification must still be live, so the logical clock's date must not be past `clna_expires_on` (otherwise `ERR_CLNA_EXPIRED`); the sequence must be complete, meaning at least one course with `status` `ACTIVE` and `segment` `SECONDARY` **and** at least one course with `status` `ACTIVE` and `segment` `POSTSECONDARY` exist on the program (otherwise `ERR_SEQUENCE_INCOMPLETE`); the approved credential list must hold at least one credential (otherwise `ERR_CREDENTIAL_LIST_EMPTY`); and at least one educator on the program must be in `status` `ELIGIBLE` after the lazy credential-lapse re-evaluation described in §2.12 has run (otherwise `ERR_NO_ELIGIBLE_INSTRUCTOR`)."

        PRD §3.4: "An accepted submission increments `approval_round` by 1 — the counter is the district's audit trail of how many times the packet has gone up — writes the supplied `narrative_url` onto the program, clears `open_finding_codes` back to an empty list"

        Design: Corner/errors/submit_gates_are_reachable_in_their_declared_priority_order
        """
        program_id, _ = _shell_with_certified_needs_assessment(build)
        opener_id = _add_secondary_opener(build, program_id)
        _add_postsecondary_capstone(build, program_id, opener_id)
        build.add_credential(program_id, "CRED-1")
        educator = build.add_educator(program_id, claimed_industry_hours=4200)
        build.verify_hours(educator["id"], 4200)

        submitted = validate_unpaginated(
            api.submit_program(program_id, f.submit_payload(), director_headers), 200
        )

        assert submitted["approval_status"] == k.APPROVAL_SUBMITTED
        assert submitted["approval_round"] == 1

    def test_submission_records_the_narrative_and_the_provisional_index(
        self, api, build, director_headers
    ):
        """PRD §3.4: "An accepted submission increments `approval_round` by 1 — the counter is the district's audit trail of how many times the packet has gone up — writes the supplied `narrative_url` onto the program, clears `open_finding_codes` back to an empty list, and recomputes the alignment index under the `PROVISIONAL_LOCAL` variant, writing `alignment_index`, setting `alignment_index_variant` to `PROVISIONAL_LOCAL`, and refreshing `secondary_credit_total`, `postsecondary_credit_total` and `articulated_credit_total`."

        Design: Corner/errors/submit_gates_are_reachable_in_their_declared_priority_order
        """
        program_id, _ = _shell_with_certified_needs_assessment(build)
        opener_id = _add_secondary_opener(build, program_id)
        _add_postsecondary_capstone(build, program_id, opener_id)
        build.add_credential(program_id, "CRED-1")
        educator = build.add_educator(program_id, claimed_industry_hours=4200)
        build.verify_hours(educator["id"], 4200)

        submitted = validate_unpaginated(
            api.submit_program(program_id, f.submit_payload(), director_headers), 200
        )

        assert submitted["narrative_url"] == "https://district.example/narrative.pdf"
        assert submitted["open_finding_codes"] == []
        assert submitted["alignment_index_variant"] == k.ALIGNMENT_VARIANT_PROVISIONAL_LOCAL
        assert_alignment_index(submitted["alignment_index"], 1.0)


ENDORSEMENT_INSTANT = "2026-08-10T15:00:00.000Z"


def _program_with_a_withdrawn_endorsement(build):
    """A program under committee review whose endorsement minutes now fail the vote."""
    scenario = build.program("51.0801", stop_at=STOP_COMMITTEE_REVIEW)
    build.file_minutes(
        scenario.endorsement_meeting_id,
        scenario.committee.chair_member_id,
        ENDORSEMENT_INSTANT,
        scenario.member_ids,
        1,
        2,
        amendment_reason="The recorded tally transposed the endorsement vote",
    )
    return scenario


class TestStateApprovalEndorsementGate:
    """State approval needs a passing endorsement on file, not merely a quorate one."""

    def test_amending_the_minutes_to_a_losing_vote_withdraws_the_endorsement(
        self, api, build, director_headers
    ):
        """PRD §3.3: "A filing that carries a non-null `amendment_reason` moves the meeting `FINALIZED → AMENDED`, recording the reason, overwriting `attendee_member_ids`, `vote_yes`, `vote_no` and `minutes_url`, and recomputing `quorum_met` and `endorsement_passed` on the amended figures — the amended attendance must itself satisfy quorum."

        PRD §3.3: "`endorsement_passed` is a stricter reading of the same figures: it is true only when `quorum_met` is true, `vote_yes` is strictly greater than `vote_no`, and `vote_yes` plus `vote_no` is no greater than `eligible_attendee_count`. A tied vote does not endorse."

        Design: Corner/errors/state_approval_without_passing_endorsement_minutes_is_rejected
        """
        scenario = _program_with_a_withdrawn_endorsement(build)

        meeting = validate_unpaginated(
            api.get_meeting(scenario.endorsement_meeting_id, director_headers)
        )

        assert meeting["minutes_status"] == k.MINUTES_AMENDED
        assert_quorum_figures(meeting, 3, 2, True, False)

    def test_state_approval_without_a_passing_endorsement_is_refused(
        self, api, build, reviewer_headers
    ):
        """PRD §3.4: "A committee endorsement must be on file: some meeting on the program's `ACTIVE` advisory committee must have `agenda_kind` `POS_ENDORSEMENT`, `minutes_status` of `FINALIZED` or `AMENDED`, and `endorsement_passed` true, or the request fails with `ERR_COMMITTEE_ENDORSEMENT_MISSING`."

        Design: Corner/errors/state_approval_without_passing_endorsement_minutes_is_rejected
        """
        scenario = _program_with_a_withdrawn_endorsement(build)

        validate_error(
            api.state_approve(
                scenario.program_id, f.state_approve_payload(), reviewer_headers
            ),
            errors.ERR_COMMITTEE_ENDORSEMENT_MISSING,
        )

    def test_the_refused_program_stays_under_committee_review(
        self, api, build, director_headers, reviewer_headers
    ):
        """PRD §3.4: "A committee endorsement must be on file: some meeting on the program's `ACTIVE` advisory committee must have `agenda_kind` `POS_ENDORSEMENT`, `minutes_status` of `FINALIZED` or `AMENDED`, and `endorsement_passed` true, or the request fails with `ERR_COMMITTEE_ENDORSEMENT_MISSING`."

        PRD §3.4: "It sets `federal_reporting_eligible` to true — this flag is true exactly while `approval_status` is `STATE_APPROVED`, and it is what determines whether the program appears in the federal Perkins submission."

        Design: Corner/errors/state_approval_without_passing_endorsement_minutes_is_rejected
        """
        scenario = _program_with_a_withdrawn_endorsement(build)
        validate_error(
            api.state_approve(
                scenario.program_id, f.state_approve_payload(), reviewer_headers
            ),
            errors.ERR_COMMITTEE_ENDORSEMENT_MISSING,
        )

        program = validate_unpaginated(
            api.get_program(scenario.program_id, director_headers)
        )
        assert program["approval_status"] == k.APPROVAL_COMMITTEE_REVIEW
        assert program["federal_reporting_eligible"] is False

    def test_a_second_endorsement_meeting_files_a_passing_vote(
        self, api, build, director_headers
    ):
        """PRD §3.3: "One filing has a reach beyond its own record. When the meeting's `agenda_kind` is `POS_ENDORSEMENT`, the recomputed `endorsement_passed` is true, and the owning committee's program of study is sitting in `approval_status` `SUBMITTED`, that program transitions `SUBMITTED → COMMITTEE_REVIEW` and its `version` increments as well. The committee must be the program's `ACTIVE` committee for this to fire. A program not in `SUBMITTED` at that moment is simply left alone — the minutes still finalize successfully."

        Design: Corner/errors/state_approval_without_passing_endorsement_minutes_is_rejected
        """
        scenario = _program_with_a_withdrawn_endorsement(build)

        replacement = build.quorate_meeting(
            scenario.committee, k.AGENDA_POS_ENDORSEMENT, SECOND_ENDORSEMENT_INSTANT
        )

        meeting = validate_unpaginated(
            api.get_meeting(replacement["id"], director_headers)
        )
        assert meeting["minutes_status"] == k.MINUTES_FINALIZED
        assert_quorum_figures(meeting, 3, 2, True, True)

    def test_a_passing_endorsement_unlocks_state_approval(
        self, api, build, reviewer_headers
    ):
        """PRD §3.4: "A committee endorsement must be on file: some meeting on the program's `ACTIVE` advisory committee must have `agenda_kind` `POS_ENDORSEMENT`, `minutes_status` of `FINALIZED` or `AMENDED`, and `endorsement_passed` true, or the request fails with `ERR_COMMITTEE_ENDORSEMENT_MISSING`."

        PRD §3.4: "State approval then does four things. It overwrites `alignment_index` with the `FEDERAL_CERTIFIED` result, sets `alignment_index_variant` to `FEDERAL_CERTIFIED`, and overwrites all three credit subtotals with that variant's sums. It sets `federal_reporting_eligible` to true — this flag is true exactly while `approval_status` is `STATE_APPROVED`, and it is what determines whether the program appears in the federal Perkins submission."

        Design: Corner/errors/state_approval_without_passing_endorsement_minutes_is_rejected
        """
        scenario = _program_with_a_withdrawn_endorsement(build)
        build.quorate_meeting(
            scenario.committee, k.AGENDA_POS_ENDORSEMENT, SECOND_ENDORSEMENT_INSTANT
        )

        approved = validate_unpaginated(
            api.state_approve(
                scenario.program_id, f.state_approve_payload(), reviewer_headers
            ),
            200,
        )

        assert approved["approval_status"] == k.APPROVAL_STATE_APPROVED
        assert approved["federal_reporting_eligible"] is True
        assert approved["alignment_index_variant"] == k.ALIGNMENT_VARIANT_FEDERAL_CERTIFIED
        assert_alignment_index(approved["alignment_index"], 1.0)

    def test_the_amended_meeting_keeps_its_failed_vote_on_the_record(
        self, api, build, director_headers, reviewer_headers
    ):
        """PRD §3.4: "A committee endorsement must be on file: some meeting on the program's `ACTIVE` advisory committee must have `agenda_kind` `POS_ENDORSEMENT`, `minutes_status` of `FINALIZED` or `AMENDED`, and `endorsement_passed` true, or the request fails with `ERR_COMMITTEE_ENDORSEMENT_MISSING`."

        PRD §3.3: "`AMENDED` admits nothing further, and an amendment filed against a meeting still in `SCHEDULED` is refused; both are `ERR_INVALID_MEETING_STATE`."

        Design: Corner/errors/state_approval_without_passing_endorsement_minutes_is_rejected
        """
        scenario = _program_with_a_withdrawn_endorsement(build)
        build.quorate_meeting(
            scenario.committee, k.AGENDA_POS_ENDORSEMENT, SECOND_ENDORSEMENT_INSTANT
        )
        build.state_approve(scenario.program_id)

        meeting = validate_unpaginated(
            api.get_meeting(scenario.endorsement_meeting_id, director_headers)
        )
        assert meeting["minutes_status"] == k.MINUTES_AMENDED
        assert meeting["endorsement_passed"] is False


def _draft_program_with_an_unverified_instructor(build):
    """A draft program carrying one ACTIVE and one DRAFT course, an unverified
    industry-route instructor and one freshly enrolled student."""
    program = build.create_program(
        "47.0201",
        title="HVAC Technology",
        cluster=k.CLUSTER_CONSTRUCTION,
        labor_market_data_asof="2026-03-01",
    )
    active = build.add_course(
        program["id"],
        f.secondary_course("HVA-1", 1, 4.0, title="Refrigeration Fundamentals"),
    )
    draft = build.add_course(
        program["id"],
        f.secondary_course(
            "HVA-2", 2, 2.0, title="Heat Pump Service", status=k.COURSE_DRAFT
        ),
    )
    educator = build.add_educator(
        program["id"],
        full_name="Omar Vale",
        certification_route=k.ROUTE_INDUSTRY_EXPERIENCE,
        claimed_industry_hours=4200,
    )
    student = build.enroll(program["id"], "200000001")
    return {
        "program_id": program["id"],
        "active_course_id": active["id"],
        "draft_course_id": draft["id"],
        "educator_id": educator["id"],
        "student_id": student["id"],
    }


class TestIndustryHourAndCourseStatusGates:
    """The accumulating hour ceiling and the course-status gate on postings."""

    def test_a_tranche_beyond_the_claimed_total_is_refused(self, api, build, reviewer_headers):
        """PRD §3.5: "Each tranche must be worth at least 1 hour, and the running total after it may not exceed what the instructor claimed — `verified_industry_hours` plus the new `verified_hours` must stay within `claimed_industry_hours`, and a breach of either bound is `ERR_INDUSTRY_HOURS_EXCEED_CLAIM`."

        Design: Corner/errors/industry_hour_and_course_status_gates_are_reachable
        """
        world = _draft_program_with_an_unverified_instructor(build)

        validate_error(
            api.verify_industry_hours(
                world["educator_id"],
                f.verification_payload(5000, k.SOURCE_EMPLOYER_LETTER),
                reviewer_headers,
            ),
            errors.ERR_INDUSTRY_HOURS_EXCEED_CLAIM,
        )

    def test_a_zero_hour_tranche_is_refused(self, api, build, reviewer_headers):
        """PRD §3.5: "Each tranche must be worth at least 1 hour, and the running total after it may not exceed what the instructor claimed — `verified_industry_hours` plus the new `verified_hours` must stay within `claimed_industry_hours`, and a breach of either bound is `ERR_INDUSTRY_HOURS_EXCEED_CLAIM`."

        Design: Corner/errors/industry_hour_and_course_status_gates_are_reachable
        """
        world = _draft_program_with_an_unverified_instructor(build)

        validate_error(
            api.verify_industry_hours(
                world["educator_id"],
                f.verification_payload(0, k.SOURCE_EMPLOYER_LETTER),
                reviewer_headers,
            ),
            errors.ERR_INDUSTRY_HOURS_EXCEED_CLAIM,
        )

    def test_a_partial_tranche_accumulates_and_leaves_the_instructor_provisional(
        self, api, build, reviewer_headers
    ):
        """PRD §3.5: "An accepted tranche adds `verified_hours` to `verified_industry_hours` and increments the educator's `version`."

        PRD §3.5: "The `INDUSTRY_EXPERIENCE` route demands 4,000 verified hours — two full years at a 2,000-hour work year — before the instructor is certifiable."

        PRD §3.5: "When the total is still below the floor, the educator loops `PROVISIONAL → PROVISIONAL` — the hours accumulate, the `version` still increments, and the request succeeds; partial verification is progress, not failure."

        Design: Corner/errors/industry_hour_and_course_status_gates_are_reachable
        """
        world = _draft_program_with_an_unverified_instructor(build)

        educator = validate_unpaginated(
            api.verify_industry_hours(
                world["educator_id"],
                f.verification_payload(3999, k.SOURCE_EMPLOYER_LETTER),
                reviewer_headers,
            ),
            200,
        )

        assert educator["verified_industry_hours"] == 3999
        assert educator["status"] == k.EDUCATOR_PROVISIONAL

    def test_a_tranche_that_would_overshoot_the_claim_by_one_hour_is_refused(
        self, api, build, reviewer_headers
    ):
        """PRD §3.5: "Each tranche must be worth at least 1 hour, and the running total after it may not exceed what the instructor claimed — `verified_industry_hours` plus the new `verified_hours` must stay within `claimed_industry_hours`, and a breach of either bound is `ERR_INDUSTRY_HOURS_EXCEED_CLAIM`."

        Design: Corner/errors/industry_hour_and_course_status_gates_are_reachable
        """
        world = _draft_program_with_an_unverified_instructor(build)
        build.verify_hours(world["educator_id"], 3999)

        validate_error(
            api.verify_industry_hours(
                world["educator_id"],
                f.verification_payload(202, k.SOURCE_PAYROLL_RECORD),
                reviewer_headers,
            ),
            errors.ERR_INDUSTRY_HOURS_EXCEED_CLAIM,
        )

    def test_the_refused_tranche_leaves_the_verified_total_untouched(
        self, api, build, reviewer_headers
    ):
        """PRD §3.5: "`verified_industry_hours` plus the new `verified_hours` must stay within `claimed_industry_hours`, and a breach of either bound is `ERR_INDUSTRY_HOURS_EXCEED_CLAIM`. An accepted tranche adds `verified_hours` to `verified_industry_hours` and increments the educator's `version`."

        Design: Corner/errors/industry_hour_and_course_status_gates_are_reachable
        """
        world = _draft_program_with_an_unverified_instructor(build)
        build.verify_hours(world["educator_id"], 3999)
        validate_error(
            api.verify_industry_hours(
                world["educator_id"],
                f.verification_payload(202, k.SOURCE_PAYROLL_RECORD),
                reviewer_headers,
            ),
            errors.ERR_INDUSTRY_HOURS_EXCEED_CLAIM,
        )

        educator = validate_unpaginated(
            api.get_educator(world["educator_id"], reviewer_headers)
        )
        assert educator["verified_industry_hours"] == 3999
        assert educator["status"] == k.EDUCATOR_PROVISIONAL

    def test_a_tranche_landing_exactly_on_the_claim_confers_eligibility(
        self, api, build, reviewer_headers
    ):
        """PRD §3.5: "Whether that tranche confers eligibility depends entirely on the route's hour floor, evaluated against the total *after* the tranche is applied. The `INDUSTRY_EXPERIENCE` route demands 4,000 verified hours — two full years at a 2,000-hour work year — before the instructor is certifiable."

        PRD §3.5: "When the post-tranche total reaches the route's floor and the logical clock's date is on or before `credential_expires_on`, the educator moves `PROVISIONAL → ELIGIBLE`."

        Design: Corner/errors/industry_hour_and_course_status_gates_are_reachable
        """
        world = _draft_program_with_an_unverified_instructor(build)
        build.verify_hours(world["educator_id"], 3999)

        educator = validate_unpaginated(
            api.verify_industry_hours(
                world["educator_id"],
                f.verification_payload(201, k.SOURCE_PAYROLL_RECORD),
                reviewer_headers,
            ),
            200,
        )

        assert educator["verified_industry_hours"] == 4200
        assert educator["status"] == k.EDUCATOR_ELIGIBLE

    def test_credits_posted_against_a_draft_course_are_refused(
        self, api, build, registrar_headers
    ):
        """PRD §3.6: "The target course must belong to the student's own program and must be in `status` `ACTIVE`; a course from another program or a course in `DRAFT` or `RETIRED` is refused with `ERR_COURSE_NOT_ACTIVE`."

        Design: Corner/errors/industry_hour_and_course_status_gates_are_reachable
        """
        world = _draft_program_with_an_unverified_instructor(build)

        validate_error(
            api.post_credit(
                world["student_id"],
                f.credit_posting_payload(world["draft_course_id"], 2.0, "2026-07-15"),
                registrar_headers,
            ),
            errors.ERR_COURSE_NOT_ACTIVE,
        )

    def test_the_identical_posting_against_the_active_course_is_accepted(
        self, api, build, registrar_headers
    ):
        """PRD §3.6: "The target course must belong to the student's own program and must be in `status` `ACTIVE`; a course from another program or a course in `DRAFT` or `RETIRED` is refused with `ERR_COURSE_NOT_ACTIVE`."

        PRD §3.6: "failing that, the student is a `CONCENTRATOR` when `cte_credits_earned` alone is at least 2.0 credit hours"

        Design: Corner/errors/industry_hour_and_course_status_gates_are_reachable
        """
        world = _draft_program_with_an_unverified_instructor(build)
        build.post_credit(world["student_id"], world["active_course_id"], 2.0)

        student = validate_unpaginated(
            api.get_student(world["student_id"], registrar_headers)
        )
        assert_credit_hours(student["cte_credits_earned"], 2.0)
        assert student["concentrator_status"] == k.CONCENTRATOR_CONCENTRATOR


PD_LINE_CENTS = (100000, 92000, 500, 400)


def _award_with_four_professional_development_lines(build):
    """A state-approved program and a 100000-cent award carrying four requested
    professional-development lines of 100000, 92000, 500 and 400 cents."""
    scenario = build.program(
        "01.0101",
        stop_at=STOP_STATE_APPROVED,
        title="Agribusiness Systems",
        cluster=k.CLUSTER_AGRICULTURE,
    )
    award = build.grant(fiscal_year=2027, allocation_cents=100000)
    lines = [
        build.expenditure(
            award.grant_id,
            scenario.program_id,
            k.CATEGORY_PROFESSIONAL_DEVELOPMENT,
            cents,
        )
        for cents in PD_LINE_CENTS
    ]
    return scenario, award, lines


class TestGrantCapacityIsTheLastCheck:
    """Capacity is judged on the ledger recomputed with the candidate line."""

    def test_a_line_for_the_whole_allocation_overdraws_the_award(
        self, api, build, fiscal_headers
    ):
        """PRD §3.7: "Finally, and last of all the checks in the entire system, the award's `remaining_cents` recomputed with this line included must be at least zero; an overdraw is `ERR_GRANT_FUNDS_EXCEEDED`."

        PRD §3.7: "Step four sets `obligated_cents` to `direct_obligated_cents` plus `indirect_pool_cents`. Step five sets `remaining_cents` to `allocation_cents` minus `obligated_cents`."

        Design: Corner/errors/grant_capacity_counts_the_indirect_pool_and_is_the_last_business_check
        """
        _scenario, _award, lines = _award_with_four_professional_development_lines(build)

        validate_error(
            api.certify_allowability(
                lines[0]["id"], f.certification_payload(k.DECISION_CERTIFY), fiscal_headers
            ),
            errors.ERR_GRANT_FUNDS_EXCEEDED,
        )

    def test_the_overdraw_refusal_leaves_the_ledger_at_its_opening_figures(
        self, api, build, fiscal_headers
    ):
        """PRD §3.7: "A new award opens in `status` `OPEN` with `direct_obligated_cents`, `indirect_pool_cents`, `obligated_cents` and `admin_obligated_cents` all 0, `remaining_cents` equal to the full `allocation_cents`, `indirect_rate` at the tier that applies to a direct total of zero, and `admin_cap_cents` set to the allocation multiplied by five percent, rounded half-up to whole cents."

        PRD §3.7: "Step one computes `direct_obligated_cents` as the sum of `approved_cents` over the award's expenditures whose `status` is `CERTIFIED` or `OBLIGATED`; `REQUESTED`, `BLOCKED`, `DISALLOWED` and `VOIDED` rows are excluded, which is exactly what makes a void an exact compensation."

        Design: Corner/errors/grant_capacity_counts_the_indirect_pool_and_is_the_last_business_check
        """
        _scenario, award, lines = _award_with_four_professional_development_lines(build)
        validate_error(
            api.certify_allowability(
                lines[0]["id"], f.certification_payload(k.DECISION_CERTIFY), fiscal_headers
            ),
            errors.ERR_GRANT_FUNDS_EXCEEDED,
        )

        ledger = validate_unpaginated(api.get_grant(award.grant_id, fiscal_headers))
        assert_ledger(ledger, 0, k.INDIRECT_RATE_LOW, 0, 0, 100000, 0)

    def test_the_overdrawing_line_is_left_in_requested(self, api, build, fiscal_headers):
        """PRD §3.7: "A `CERTIFY` decision moves the expenditure `REQUESTED → CERTIFIED` and must clear a full stack of federal gates."

        PRD §3.7: "Finally, and last of all the checks in the entire system, the award's `remaining_cents` recomputed with this line included must be at least zero; an overdraw is `ERR_GRANT_FUNDS_EXCEEDED`."

        Design: Corner/errors/grant_capacity_counts_the_indirect_pool_and_is_the_last_business_check
        """
        _scenario, _award, lines = _award_with_four_professional_development_lines(build)
        validate_error(
            api.certify_allowability(
                lines[0]["id"], f.certification_payload(k.DECISION_CERTIFY), fiscal_headers
            ),
            errors.ERR_GRANT_FUNDS_EXCEEDED,
        )

        line = validate_unpaginated(api.get_expenditure(lines[0]["id"], fiscal_headers))
        assert line["status"] == k.EXP_REQUESTED

    def test_a_fitting_line_certifies_and_the_ledger_carries_the_indirect_pool(
        self, api, build, fiscal_headers
    ):
        """PRD §3.7: "`PROFESSIONAL_DEVELOPMENT` is reimbursed in full at a share of 1.0000."

        PRD §3.7: "Step two selects `indirect_rate` by a tier lookup keyed **only** on that direct total: a direct total below 5,000,000 cents (fifty thousand dollars) takes the rate 0.0812; a direct total below 20,000,000 cents (two hundred thousand dollars) takes 0.0650; anything at or above 20,000,000 cents takes 0.0500. The lookup is never keyed on `obligated_cents` or `remaining_cents`, even though `obligated_cents` contains the pool this rate produces — that circularity is precisely the mistake the pinning forbids. Step three computes `indirect_pool_cents` as the direct total multiplied by `indirect_rate`, rounded half-up to whole cents, computed from scratch rather than incremented against its previous value. Step four sets `obligated_cents` to `direct_obligated_cents` plus `indirect_pool_cents`. Step five sets `remaining_cents` to `allocation_cents` minus `obligated_cents`."

        Design: Corner/errors/grant_capacity_counts_the_indirect_pool_and_is_the_last_business_check
        """
        _scenario, award, lines = _award_with_four_professional_development_lines(build)

        certified = validate_unpaginated(
            api.certify_allowability(
                lines[1]["id"], f.certification_payload(k.DECISION_CERTIFY), fiscal_headers
            ),
            200,
        )
        assert certified["status"] == k.EXP_CERTIFIED
        assert_cents(certified["approved_cents"], 92000, "approved_cents")

        ledger = validate_unpaginated(api.get_grant(award.grant_id, fiscal_headers))
        assert_ledger(ledger, 92000, k.INDIRECT_RATE_LOW, 7470, 99470, 530, 0)

    def test_a_line_below_the_reported_remaining_is_still_refused(
        self, api, build, fiscal_headers
    ):
        """PRD §3.7: "Finally, and last of all the checks in the entire system, the award's `remaining_cents` recomputed with this line included must be at least zero; an overdraw is `ERR_GRANT_FUNDS_EXCEEDED`."

        PRD §3.7: "Step three computes `indirect_pool_cents` as the direct total multiplied by `indirect_rate`, rounded half-up to whole cents, computed from scratch rather than incremented against its previous value. Step four sets `obligated_cents` to `direct_obligated_cents` plus `indirect_pool_cents`. Step five sets `remaining_cents` to `allocation_cents` minus `obligated_cents`."

        Design: Corner/errors/grant_capacity_counts_the_indirect_pool_and_is_the_last_business_check
        """
        _scenario, _award, lines = _award_with_four_professional_development_lines(build)
        build.certify(lines[1]["id"])

        validate_error(
            api.certify_allowability(
                lines[2]["id"], f.certification_payload(k.DECISION_CERTIFY), fiscal_headers
            ),
            errors.ERR_GRANT_FUNDS_EXCEEDED,
        )

    def test_that_refusal_changes_neither_the_ledger_nor_the_line(
        self, api, build, fiscal_headers
    ):
        """PRD §3.7: "Step one computes `direct_obligated_cents` as the sum of `approved_cents` over the award's expenditures whose `status` is `CERTIFIED` or `OBLIGATED`; `REQUESTED`, `BLOCKED`, `DISALLOWED` and `VOIDED` rows are excluded, which is exactly what makes a void an exact compensation."

        PRD §3.7: "Finally, and last of all the checks in the entire system, the award's `remaining_cents` recomputed with this line included must be at least zero; an overdraw is `ERR_GRANT_FUNDS_EXCEEDED`."

        Design: Corner/errors/grant_capacity_counts_the_indirect_pool_and_is_the_last_business_check
        """
        _scenario, award, lines = _award_with_four_professional_development_lines(build)
        build.certify(lines[1]["id"])
        validate_error(
            api.certify_allowability(
                lines[2]["id"], f.certification_payload(k.DECISION_CERTIFY), fiscal_headers
            ),
            errors.ERR_GRANT_FUNDS_EXCEEDED,
        )

        ledger = validate_unpaginated(api.get_grant(award.grant_id, fiscal_headers))
        assert_ledger(ledger, 92000, k.INDIRECT_RATE_LOW, 7470, 99470, 530, 0)
        line = validate_unpaginated(api.get_expenditure(lines[2]["id"], fiscal_headers))
        assert line["status"] == k.EXP_REQUESTED

    def test_a_smaller_line_fits_once_the_pool_growth_is_counted(
        self, api, build, fiscal_headers
    ):
        """PRD §3.7: "The approved amount of a line is its `gross_cents` multiplied by its `federal_share_pct`, rounded half-up to whole cents — and that rounding happens **here, once, per expenditure line**. The award ledger then sums those already-rounded integers."

        PRD §3.7: "Step three computes `indirect_pool_cents` as the direct total multiplied by `indirect_rate`, rounded half-up to whole cents, computed from scratch rather than incremented against its previous value. Step four sets `obligated_cents` to `direct_obligated_cents` plus `indirect_pool_cents`. Step five sets `remaining_cents` to `allocation_cents` minus `obligated_cents`."

        Design: Corner/errors/grant_capacity_counts_the_indirect_pool_and_is_the_last_business_check
        """
        _scenario, award, lines = _award_with_four_professional_development_lines(build)
        build.certify(lines[1]["id"])

        validate_unpaginated(
            api.certify_allowability(
                lines[3]["id"], f.certification_payload(k.DECISION_CERTIFY), fiscal_headers
            ),
            200,
        )

        ledger = validate_unpaginated(api.get_grant(award.grant_id, fiscal_headers))
        assert_ledger(ledger, 92400, k.INDIRECT_RATE_LOW, 7503, 99903, 97, 0)

    def test_the_administrative_sub_ledger_stays_empty_under_its_five_percent_cap(
        self, api, build, fiscal_headers
    ):
        """PRD §3.7: "Step six rebuilds the administrative sub-ledger with the same input-set discipline: `admin_obligated_cents` is the sum of `approved_cents` over the award's expenditures whose `category` is `ADMINISTRATION` and whose `status` is `CERTIFIED` or `OBLIGATED`, and `admin_cap_cents` is `allocation_cents` multiplied by five percent, rounded half-up to whole cents."

        Design: Corner/errors/grant_capacity_counts_the_indirect_pool_and_is_the_last_business_check
        """
        _scenario, award, lines = _award_with_four_professional_development_lines(build)
        build.certify(lines[1]["id"])
        build.certify(lines[3]["id"])

        ledger = validate_unpaginated(api.get_grant(award.grant_id, fiscal_headers))
        assert_cents(ledger["admin_cap_cents"], 5000, "admin_cap_cents")
        assert_cents(ledger["admin_obligated_cents"], 0, "admin_obligated_cents")


def _suspended_program_after_two_missed_years(build):
    """A state-approved program driven into suspension by two consecutive misses,
    carrying one requested charge and a five-student cohort of which two are verified."""
    scenario = build.program(
        "26.0101",
        stop_at=STOP_STATE_APPROVED,
        title="Biotechnology",
        cluster=k.CLUSTER_HEALTH_SCIENCE,
    )
    award = build.grant(fiscal_year=2027, allocation_cents=5000000)
    charge = build.expenditure(
        award.grant_id, scenario.program_id, k.CATEGORY_CONSUMABLE, 100000
    )
    students = build.cohort(scenario, 5, verified_count=2)
    indicator = build.agreed_indicator(
        scenario.program_id, k.INDICATOR_4S1_CREDENTIAL, 90.0
    )
    build.miss_twice(indicator["id"])
    return scenario, charge, students, indicator


class TestSuspensionBlocksRegistrarWrites:
    """Suspension freezes postings and exits without freezing the whole program."""

    def test_the_second_miss_suspends_the_program_and_files_the_finding(
        self, api, build, reviewer_headers
    ):
        """PRD §3.8: "Link 2 in turn fires link 3, which suspends the program: a program of study in `approval_status` `STATE_APPROVED` moves `STATE_APPROVED → SUSPENDED`, has `federal_reporting_eligible` set to false, appends the finding code `PERF_SUSPENSION` to `open_finding_codes`, and has its `version` incremented."

        Design: Corner/errors/credit_postings_and_exits_are_blocked_while_the_program_is_suspended
        """
        scenario, _charge, _students, _indicator = _suspended_program_after_two_missed_years(
            build
        )

        program = validate_unpaginated(
            api.get_program(scenario.program_id, reviewer_headers)
        )
        assert program["approval_status"] == k.APPROVAL_SUSPENDED
        assert program["federal_reporting_eligible"] is False
        assert k.FINDING_PERF_SUSPENSION in program["open_finding_codes"]

    def test_the_indicator_records_two_misses_and_the_cohort_percentage(
        self, api, build, reviewer_headers
    ):
        """PRD §3.8: "`numerator_count` is the number of those same students whose `verified_qualifying_attainment_count` is at least 1. `small_cohort_flag` is true exactly when `denominator_count` is below the federal minimum cohort size of 5. The raw percentage is null when `denominator_count` is zero; otherwise it is 100 multiplied by `numerator_count`, divided by `denominator_count`, rounded half-up to two decimal places."

        PRD §3.8: "The increment of `consecutive_miss_count` is cascade link 1, and it is that increment reaching the miss tolerance of 2 — not the close itself — that fires link 2: the indicator escalates `NOT_MET → IMPROVEMENT_REQUIRED`."

        Design: Corner/errors/credit_postings_and_exits_are_blocked_while_the_program_is_suspended
        """
        _scenario, _charge, _students, indicator = _suspended_program_after_two_missed_years(
            build
        )

        row = validate_unpaginated(api.get_indicator(indicator["id"], reviewer_headers))
        assert row["status"] == k.PI_IMPROVEMENT_REQUIRED
        assert row["consecutive_miss_count"] == 2
        assert_pct(row["actual_pct"], 40.00)

    def test_the_requested_charge_is_blocked_by_the_suspension(
        self, api, build, fiscal_headers
    ):
        """PRD §3.8: "And that suspension fires link 4: every expenditure charged to that program whose `status` is `REQUESTED` moves `REQUESTED → BLOCKED`, each with its own `version` increment. Certified, obligated, disallowed and voided lines are untouched."

        Design: Corner/errors/credit_postings_and_exits_are_blocked_while_the_program_is_suspended
        """
        _scenario, charge, _students, _indicator = _suspended_program_after_two_missed_years(
            build
        )

        line = validate_unpaginated(api.get_expenditure(charge["id"], fiscal_headers))
        assert line["status"] == k.EXP_BLOCKED

    def test_a_credit_posting_into_a_suspended_program_is_refused(
        self, api, build, registrar_headers
    ):
        """PRD §3.6: "Both registrar write operations, posting credits and recording an exit, are additionally blocked outright while the student's program of study sits in `approval_status` `SUSPENDED`; the refusal is `ERR_CREDIT_POSTING_BLOCKED`, and it is evaluated before the course and balance checks."

        Design: Corner/errors/credit_postings_and_exits_are_blocked_while_the_program_is_suspended
        """
        scenario, _charge, students, _indicator = _suspended_program_after_two_missed_years(
            build
        )

        validate_error(
            api.post_credit(
                students[0]["id"],
                f.credit_posting_payload(scenario.secondary_course_id, 1.0, "2026-07-20"),
                registrar_headers,
            ),
            errors.ERR_CREDIT_POSTING_BLOCKED,
        )

    def test_an_exit_from_a_suspended_program_is_refused_with_the_same_code(
        self, api, build, registrar_headers
    ):
        """PRD §3.6: "Both registrar write operations, posting credits and recording an exit, are additionally blocked outright while the student's program of study sits in `approval_status` `SUSPENDED`; the refusal is `ERR_CREDIT_POSTING_BLOCKED`, and it is evaluated before the course and balance checks."

        Design: Corner/errors/credit_postings_and_exits_are_blocked_while_the_program_is_suspended
        """
        _scenario, _charge, students, _indicator = _suspended_program_after_two_missed_years(
            build
        )

        validate_error(
            api.exit_student(
                students[0]["id"],
                f.exit_payload("2026-07-31", k.EXIT_WITHDREW),
                registrar_headers,
            ),
            errors.ERR_CREDIT_POSTING_BLOCKED,
        )

    def test_the_refused_student_record_is_left_exactly_as_it_was(
        self, api, build, registrar_headers
    ):
        """PRD §3.6: "Both registrar write operations, posting credits and recording an exit, are additionally blocked outright while the student's program of study sits in `approval_status` `SUSPENDED`; the refusal is `ERR_CREDIT_POSTING_BLOCKED`, and it is evaluated before the course and balance checks."

        PRD §3.6: "Until an exit is recorded the student is treated as still enrolled and `exited_on` stays null."

        Design: Corner/errors/credit_postings_and_exits_are_blocked_while_the_program_is_suspended
        """
        scenario, _charge, students, _indicator = _suspended_program_after_two_missed_years(
            build
        )
        validate_error(
            api.post_credit(
                students[0]["id"],
                f.credit_posting_payload(scenario.secondary_course_id, 1.0, "2026-07-20"),
                registrar_headers,
            ),
            errors.ERR_CREDIT_POSTING_BLOCKED,
        )
        validate_error(
            api.exit_student(
                students[0]["id"],
                f.exit_payload("2026-07-31", k.EXIT_WITHDREW),
                registrar_headers,
            ),
            errors.ERR_CREDIT_POSTING_BLOCKED,
        )

        student = validate_unpaginated(
            api.get_student(students[0]["id"], registrar_headers)
        )
        assert_credit_hours(student["cte_credits_earned"], 2.0)
        assert student["exited_on"] is None
        assert student["concentrator_status"] == k.CONCENTRATOR_CONCENTRATOR

    def test_an_attainment_in_the_same_suspended_program_still_succeeds(
        self, api, build, registrar_headers
    ):
        """PRD §3.6: "Both registrar write operations, posting credits and recording an exit, are additionally blocked outright while the student's program of study sits in `approval_status` `SUSPENDED`; the refusal is `ERR_CREDIT_POSTING_BLOCKED`, and it is evaluated before the course and balance checks."

        PRD §3.6: "Whether an attainment counts for federal purposes is a conjunction of two facts, and the server records the answer on the row as `counted_for_indicator`: it is true only when the attainment's `verification_status` is `VERIFIED` **and** the referenced credential's `counts_toward_indicator` is true."

        Design: Corner/errors/credit_postings_and_exits_are_blocked_while_the_program_is_suspended
        """
        scenario, _charge, students, _indicator = _suspended_program_after_two_missed_years(
            build
        )

        attainment = validate_unpaginated(
            api.create_attainment(
                students[2]["id"],
                f.attainment_payload(
                    scenario.credential_id,
                    "2026-07-25",
                    k.VERIFICATION_VERIFIED,
                    exam_score=88.50,
                ),
                registrar_headers,
            ),
            201,
        )

        assert attainment["verification_status"] == k.VERIFICATION_VERIFIED
        assert attainment["counted_for_indicator"] is True
