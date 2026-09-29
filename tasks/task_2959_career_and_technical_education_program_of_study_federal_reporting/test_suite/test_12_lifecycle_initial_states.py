"""The state every freshly created record reports before anything acts on it.

Each test below creates exactly one record through the public API and reads back
the initial state, counters and null fields the specification declares for it.
The runner restarts the server before every individual test, so each starts
against an empty database with the logical clock at 2026-08-01T00:00:00Z.
"""

from test_helpers import (
    assert_cents,
    assert_credit_hours,
    assert_credit_totals,
    assert_ledger,
    assert_rate,
    assert_version,
    f,
    k,
    users,
    validate_unpaginated,
)


class TestProgramAuthoringInitialStates:
    """A program of study and the records a director hangs underneath it."""

    def test_a_new_program_of_study_opens_in_draft_with_its_needs_assessment_not_started(
        self, api, director_headers
    ):
        """PRD §3.1: "On creation the new program lands in `approval_status` `DRAFT` and `clna_phase` `NOT_STARTED`, its `version` is 1, its `authored_by_user_id` is set to the acting `X-User-ID`, its `alignment_index` and `alignment_index_variant` are both null, its `narrative_url` is null, its `open_finding_codes` list is empty, its `federal_reporting_eligible` flag is false, its `approval_round` is 0, its `clna_certified_by_user_id`, `clna_certified_on` and `clna_expires_on` are all null, and `secondary_credit_total`, `postsecondary_credit_total` and `articulated_credit_total` are all 0."

        Design: Corner/state_machines/every_new_row_starts_in_its_declared_initial_state
        """
        program = validate_unpaginated(
            api.create_program(
                f.program_payload("51.0801", title="Medical Assisting"),
                director_headers,
            ),
            201,
        )

        assert program["approval_status"] == k.APPROVAL_DRAFT
        assert program["clna_phase"] == k.CLNA_NOT_STARTED
        assert_version(program, 1)
        assert program["authored_by_user_id"] == users.DIRECTOR.user_id
        assert program["alignment_index"] is None
        assert program["alignment_index_variant"] is None
        assert program["narrative_url"] is None
        assert program["open_finding_codes"] == []
        assert program["federal_reporting_eligible"] is False
        assert program["approval_round"] == 0
        assert program["clna_certified_by_user_id"] is None
        assert program["clna_certified_on"] is None
        assert program["clna_expires_on"] is None
        assert_credit_totals(program, 0, 0, 0)

    def test_a_new_sequence_course_defaults_to_draft_at_the_root_of_the_sequence(
        self, api, build, director_headers
    ):
        """PRD §3.1: "Optionally the payload sets `articulated_credit_hours` — the portion of the course's credit that articulates to the postsecondary partner, which defaults to 0 and may be neither negative nor greater than `credit_hours` — an `articulation_verified` flag that defaults to false and turns true only once the postsecondary partner has countersigned the articulation agreement, a `prerequisite_course_id` naming an earlier course, and a `status` that defaults to `DRAFT` and may be set to `ACTIVE` or `RETIRED`. The server computes `depth_from_root`, the number of prerequisite hops from the course back to a course whose `prerequisite_course_id` is null, by walking the chain; a course that opens the sequence has `depth_from_root` 0."

        Design: Corner/state_machines/every_new_row_starts_in_its_declared_initial_state
        """
        program = build.create_program("51.0801")

        course = validate_unpaginated(
            api.create_course(
                program["id"],
                f.course_payload(
                    code="MED-1",
                    title="Medical Assisting I",
                    segment=k.SEGMENT_SECONDARY,
                    position=1,
                    credit_hours=4.0,
                ),
                director_headers,
            ),
            201,
        )

        assert course["status"] == k.COURSE_DRAFT
        assert_credit_hours(course["articulated_credit_hours"], 0)
        assert course["articulation_verified"] is False
        assert course["prerequisite_course_id"] is None
        assert course["depth_from_root"] == 0
        assert_version(course, 1)

    def test_a_newly_assigned_educator_is_provisional_with_no_verified_hours(
        self, api, build, director_headers
    ):
        """PRD §3.5: "A `CteDirector` assigns an educator to a program with a `full_name`, a `certification_route` of `TRADITIONAL`, `INDUSTRY_EXPERIENCE` or `ALTERNATIVE`, a `claimed_industry_hours` figure of zero or more stating how much industry work the instructor asserts, and a `credential_expires_on` date on which the teaching credential lapses. The educator lands in `status` `PROVISIONAL` with `verified_industry_hours` 0, and the assignment increments the parent program's `version`."

        Design: Corner/state_machines/every_new_row_starts_in_its_declared_initial_state
        """
        program = build.create_program("51.0801")

        educator = validate_unpaginated(
            api.assign_educator(
                program["id"],
                f.educator_payload(
                    "Dana Ruiz",
                    k.ROUTE_INDUSTRY_EXPERIENCE,
                    4200,
                    credential_expires_on="2029-06-30",
                ),
                director_headers,
            ),
            201,
        )

        assert educator["status"] == k.EDUCATOR_PROVISIONAL
        assert educator["verified_industry_hours"] == 0
        assert educator["certification_route"] == k.ROUTE_INDUSTRY_EXPERIENCE
        assert_version(educator, 1)


class TestRegistrarAndAccountabilityInitialStates:
    """The records the registrar and the state open against a program."""

    def test_a_newly_enrolled_student_is_a_participant_with_nothing_earned_yet(
        self, api, build, registrar_headers
    ):
        """PRD §3.6: "The new student begins with `cte_credits_earned` 0, `verified_qualifying_attainment_count` 0, `concentrator_status` `PARTICIPANT`, and `exited_on` and `exit_reason` both null."

        Design: Corner/state_machines/every_new_row_starts_in_its_declared_initial_state
        """
        program = build.create_program("51.0801")

        student = validate_unpaginated(
            api.enroll_student(
                program["id"],
                f.student_payload("100000001", 2026),
                registrar_headers,
            ),
            201,
        )

        assert_credit_hours(student["cte_credits_earned"], 0)
        assert student["verified_qualifying_attainment_count"] == 0
        assert student["concentrator_status"] == k.CONCENTRATOR_PARTICIPANT
        assert student["exited_on"] is None
        assert student["exit_reason"] is None
        assert_version(student, 1)

    def test_a_newly_opened_performance_indicator_is_proposed_at_round_zero(
        self, api, build, reviewer_headers
    ):
        """PRD §3.8: "The indicator opens in `status` `PROPOSED` with `negotiation_round` 0, `negotiated_level_pct`, `last_offer_pct`, `last_offer_by_user_id`, `last_offer_by_role`, `met_threshold_pct`, `actual_pct` and `closed_on` all null, and `consecutive_miss_count` 0."

        Design: Corner/state_machines/every_new_row_starts_in_its_declared_initial_state
        """
        program = build.create_program("51.0801")

        indicator = validate_unpaginated(
            api.open_indicator(
                program["id"],
                f.indicator_payload(k.INDICATOR_4S1_CREDENTIAL, 2027, 60.0, 2026),
                reviewer_headers,
            ),
            201,
        )

        assert indicator["status"] == k.PI_PROPOSED
        assert indicator["negotiation_round"] == 0
        for name in (
            "negotiated_level_pct",
            "last_offer_pct",
            "last_offer_by_user_id",
            "last_offer_by_role",
            "met_threshold_pct",
            "actual_pct",
            "closed_on",
        ):
            assert indicator[name] is None, f"{name} must open null, got {indicator[name]!r}"
        assert indicator["consecutive_miss_count"] == 0
        assert_version(indicator, 1)


class TestAdvisoryCommitteeInitialStates:
    """A chartered committee, its first seat and its first meeting."""

    def test_a_newly_chartered_committee_is_forming_with_an_empty_roster(
        self, api, build, director_headers
    ):
        """PRD §3.3: "A newly chartered committee starts in `status` `FORMING` with `active_member_count` 0, `employer_member_count` 0 and `chair_member_id` null, and its creation increments the parent program's `version`."

        Design: Corner/state_machines/every_new_row_starts_in_its_declared_initial_state
        """
        program = build.create_program("51.0801")

        committee = validate_unpaginated(
            api.charter_committee(
                program["id"],
                f.committee_payload(
                    program["version"],
                    name="Medical Assisting Advisory Committee",
                    quorum_min_members=3,
                    employer_seat_min=2,
                ),
                director_headers,
            ),
            201,
        )

        assert committee["status"] == k.COMMITTEE_FORMING
        assert committee["active_member_count"] == 0
        assert committee["employer_member_count"] == 0
        assert committee["chair_member_id"] is None
        assert_version(committee, 1)

    def test_a_newly_seated_member_holds_an_active_seat(self, api, build, director_headers):
        """PRD §3.3: "A member's `status` begins as `ACTIVE` and becomes `EXPIRED` once the logical clock's date reaches `term_end_on`; the term is inclusive of `term_start_on` and exclusive of `term_end_on`."

        Design: Corner/state_machines/every_new_row_starts_in_its_declared_initial_state
        """
        program = build.create_program("51.0801")
        committee = build.charter_committee(program["id"])

        member = validate_unpaginated(
            api.seat_member(
                committee["id"],
                f.member_payload(
                    "Rosa Vega",
                    k.SECTOR_EMPLOYER,
                    "EMP-1",
                    term_start_on="2026-01-01",
                    term_end_on="2027-12-31",
                    is_chair=True,
                ),
                director_headers,
            ),
            201,
        )

        assert member["status"] == k.MEMBER_ACTIVE
        assert member["is_chair"] is True
        assert_version(member, 1)

    def test_a_newly_scheduled_meeting_is_scheduled_and_carries_no_quorum(
        self, api, build, director_headers
    ):
        """PRD §3.3: "The new meeting begins with `minutes_status` `SCHEDULED`, an empty `attendee_member_ids` list, `vote_yes` and `vote_no` both at 0, `quorum_met` and `endorsement_passed` both false, and `held_at`, `minutes_url` and `amendment_reason` all null; scheduling increments the owning committee's `version`."

        Design: Corner/state_machines/every_new_row_starts_in_its_declared_initial_state
        """
        program = build.create_program("51.0801")
        committee_row = build.charter_committee(program["id"])
        committee = build.seat_roster(committee_row["id"])

        meeting = validate_unpaginated(
            api.schedule_meeting(
                committee.committee_id,
                f.meeting_payload(k.AGENDA_CLNA_STAKEHOLDER, "2026-08-04T14:00:00.000Z"),
                users.chair_headers(committee.chair_member_id),
            ),
            201,
        )

        assert meeting["minutes_status"] == k.MINUTES_SCHEDULED
        assert meeting["attendee_member_ids"] == []
        assert meeting["vote_yes"] == 0
        assert meeting["vote_no"] == 0
        assert meeting["quorum_met"] is False
        assert meeting["endorsement_passed"] is False
        assert meeting["held_at"] is None
        assert meeting["minutes_url"] is None
        assert meeting["amendment_reason"] is None
        assert_version(meeting, 1)

    def test_the_committee_leaves_forming_only_when_one_seating_satisfies_all_three_conditions(
        self, api, build, director_headers
    ):
        """PRD §3.3: "Each successful seating rebuilds the committee's derived counts. `active_member_count` becomes the number of that committee's members whose `status` is `ACTIVE`, `employer_member_count` becomes the number of those whose `sector` is also `EMPLOYER`, and `chair_member_id` becomes the `id` of the single `ACTIVE` member whose `is_chair` is true (staying null while no such member exists). The committee then flips `FORMING → ACTIVE` the moment all three conditions hold at once: `active_member_count` is at least `quorum_min_members`, `employer_member_count` is at least `employer_seat_min`, and `chair_member_id` is non-null."

        Design: Corner/state_machines/every_new_row_starts_in_its_declared_initial_state
        """
        program = build.create_program("51.0801")
        committee_row = build.charter_committee(
            program["id"], quorum_min_members=3, employer_seat_min=2
        )
        committee_id = committee_row["id"]

        chair = build.seat_member(
            committee_id, "Rosa Vega", k.SECTOR_EMPLOYER, "EMP-1", is_chair=True
        )
        after_first = validate_unpaginated(api.get_committee(committee_id, director_headers))
        assert after_first["status"] == k.COMMITTEE_FORMING
        assert after_first["active_member_count"] == 1
        assert after_first["employer_member_count"] == 1
        assert after_first["chair_member_id"] == chair["id"]

        build.seat_member(committee_id, "Ken Ade", k.SECTOR_EMPLOYER, "EMP-2")
        after_second = validate_unpaginated(api.get_committee(committee_id, director_headers))
        assert after_second["status"] == k.COMMITTEE_FORMING
        assert after_second["active_member_count"] == 2
        assert after_second["employer_member_count"] == 2

        build.seat_member(committee_id, "Iris Lund", k.SECTOR_POSTSECONDARY, "PSE-1")
        after_third = validate_unpaginated(api.get_committee(committee_id, director_headers))
        assert after_third["status"] == k.COMMITTEE_ACTIVE
        assert after_third["active_member_count"] == 3
        assert after_third["employer_member_count"] == 2
        assert after_third["chair_member_id"] == chair["id"]


class TestGrantLedgerInitialStates:
    """A recorded award and the first charge filed against it."""

    def test_a_new_grant_award_opens_inside_its_window_on_a_zeroed_ledger(
        self, api, fiscal_headers
    ):
        """PRD §3.7: "A new award opens in `status` `OPEN` with `direct_obligated_cents`, `indirect_pool_cents`, `obligated_cents` and `admin_obligated_cents` all 0, `remaining_cents` equal to the full `allocation_cents`, `indirect_rate` at the tier that applies to a direct total of zero, and `admin_cap_cents` set to the allocation multiplied by five percent, rounded half-up to whole cents. The award's `status` reads `OPEN` while the logical clock's date lies within the inclusive window and `CLOSED` once that date passes `obligation_window_end`."

        PRD §3.7: "Step two selects `indirect_rate` by a tier lookup keyed **only** on that direct total: a direct total below 5,000,000 cents (fifty thousand dollars) takes the rate 0.0812; a direct total below 20,000,000 cents (two hundred thousand dollars) takes 0.0650; anything at or above 20,000,000 cents takes 0.0500."

        Design: Corner/state_machines/every_new_row_starts_in_its_declared_initial_state
        """
        grant = validate_unpaginated(
            api.create_grant(
                f.grant_payload(
                    2027,
                    5000000,
                    obligation_window_start="2026-07-01",
                    obligation_window_end="2027-06-30",
                ),
                fiscal_headers,
            ),
            201,
        )

        assert grant["status"] == k.GRANT_OPEN
        assert_ledger(
            grant,
            direct_cents=0,
            indirect_rate=k.INDIRECT_RATE_LOW,
            pool_cents=0,
            obligated_cents=0,
            remaining_cents=5000000,
            admin_obligated_cents=0,
        )
        assert_cents(grant["admin_cap_cents"], 250000, "admin_cap_cents")
        assert_version(grant, 1)

    def test_a_newly_requested_expenditure_is_requested_with_no_approved_amount_yet(
        self, api, build, director_headers
    ):
        """PRD §3.7: "The stored row takes its `grant_award_id` from the addressed award, records `requested_by_user_id` from the acting `X-User-ID`, opens in `status` `REQUESTED`, computes `gross_cents` as `unit_cost_cents` multiplied by `quantity`, sets `federal_share_pct` from the category table below, leaves `approved_cents` null until certification, leaves `certified_by_user_id`, `finding_code`, `obligation_reference` and `void_reason` null, and increments the award's `version`."

        PRD §3.7: "`EQUIPMENT`, `CONSUMABLE` and `ADMINISTRATION` are each reimbursed at a share of 0.8500."

        Design: Corner/state_machines/every_new_row_starts_in_its_declared_initial_state
        """
        program = build.create_program("51.0801")
        grant = build.grant()

        expenditure = validate_unpaginated(
            api.request_expenditure(
                grant.grant_id,
                f.expenditure_payload(
                    program["id"],
                    k.CATEGORY_CONSUMABLE,
                    100000,
                    1,
                    grant.version,
                    description="Clinic consumables",
                ),
                director_headers,
            ),
            201,
        )

        assert expenditure["grant_award_id"] == grant.grant_id
        assert expenditure["requested_by_user_id"] == users.DIRECTOR.user_id
        assert expenditure["status"] == k.EXP_REQUESTED
        assert_cents(expenditure["gross_cents"], 100000, "gross_cents")
        assert_rate(
            expenditure["federal_share_pct"],
            k.FEDERAL_SHARE_BY_CATEGORY[k.CATEGORY_CONSUMABLE],
            "federal_share_pct",
        )
        assert expenditure["approved_cents"] is None
        assert expenditure["certified_by_user_id"] is None
        assert expenditure["finding_code"] is None
        assert expenditure["obligation_reference"] is None
        assert expenditure["void_reason"] is None
        assert_version(expenditure, 1)
