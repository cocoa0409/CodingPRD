"""Campus meetings and the career program (PRD §3.8)."""
import pytest

from test_helpers import (
    ApiErrorId,
    MISSING_UUID,
    TEST_USERS,
    accept_offer,
    api_client,
    assert_cohort_meeting,
    assert_internship,
    create_cohort_meeting_payload,
    create_internship_payload,
    create_offer,
    create_selected_nominee,
    get_cohort,
    get_scholar,
    get_scholar_for_nominee,
    internship_transition_payload,
    make_faculty_mentor_headers,
    scholar_lifecycle,
    setup_cohort_foundation,
    setup_matriculated_cohort,
    validate_error,
    validate_paginated,
    validate_success,
)

_ADMIN = TEST_USERS["program_admin_headers"]
_DIRECTOR = TEST_USERS["career_director_headers"]


class TestMeetingShapeRules:
    def test_meeting_request_shape_rules(self, api):
        """PRD §3.8: "The `scholar_id` is required when the `kind` is
        `INDIVIDUAL` and must be null or absent when the `kind` is `COHORT`;
        either violation is a request-shape error rejected with
        `ERR_INVALID_REQUEST`."
        PRD §3.8: "The `ends_at` must be strictly after the `starts_at`,
        otherwise `ERR_INVALID_REQUEST`."

        Design: Corner/validations/meeting_request_shape_rules
        """
        ctx = setup_cohort_foundation(cohort_size=3)  # FORMING cohort + mentor
        headers = make_faculty_mentor_headers(ctx["mentor"]["id"])

        no_scholar = api.create_cohort_meeting(
            create_cohort_meeting_payload(
                ctx["cohort"]["id"], "INDIVIDUAL",
                "2027-09-10T10:00:00Z", "2027-09-10T11:00:00Z",
            ),
            headers,
        )
        validate_error(no_scholar, ApiErrorId.ERR_INVALID_REQUEST)

        stray_scholar = api.create_cohort_meeting(
            create_cohort_meeting_payload(
                ctx["cohort"]["id"], "COHORT",
                "2027-09-10T10:00:00Z", "2027-09-10T11:00:00Z",
                scholar_id=MISSING_UUID, include_scholar_id=True,
            ),
            headers,
        )
        validate_error(stray_scholar, ApiErrorId.ERR_INVALID_REQUEST)

        inverted = api.create_cohort_meeting(
            create_cohort_meeting_payload(
                ctx["cohort"]["id"], "COHORT",
                "2027-09-10T11:00:00Z", "2027-09-10T10:00:00Z",
            ),
            headers,
        )
        validate_error(inverted, ApiErrorId.ERR_INVALID_REQUEST)


class TestMeetingCohortState:
    def test_meeting_on_forming_cohort_rejected(self, api):
        """PRD §3.8: "The cohort must be `MATRICULATED` — logging against a
        cohort in any other status is rejected with `ERR_INVALID_STATE`".

        Design: Corner/validations/meeting_on_forming_cohort_rejected
        """
        ctx = setup_cohort_foundation(cohort_size=3)
        resp = api.create_cohort_meeting(
            create_cohort_meeting_payload(
                ctx["cohort"]["id"], "COHORT",
                "2027-09-10T10:00:00Z", "2027-09-10T11:00:00Z",
            ),
            make_faculty_mentor_headers(ctx["mentor"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_cohort(ctx["cohort"]["id"])["meetings_held_count"] == 0


class TestMentorBufferRule:
    def _setup_matriculated_cohort_for_meetings(self):
        """MATRICULATED cohort (all scholars withdrawn by the training gate —
        the meeting gate reads only cohort status)."""
        return setup_matriculated_cohort(trained_count=0)

    def test_meeting_inside_buffer_window_conflicts(self, api):
        """PRD §3.8: "A mentor's calendar observes a 15-minute buffer rule: a
        new meeting conflicts with an existing meeting of the same mentor
        exactly when the new meeting's `starts_at` falls before the existing
        meeting's `ends_at` plus fifteen minutes, and the existing meeting's
        `starts_at` falls before the new meeting's `ends_at` plus fifteen
        minutes. Such a conflict is rejected with
        `ERR_MENTOR_SCHEDULE_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/mentor_meeting_buffer_conflict
        """
        ctx = self._setup_matriculated_cohort_for_meetings()
        headers = make_faculty_mentor_headers(ctx["mentor"]["id"])

        first = api.create_cohort_meeting(
            create_cohort_meeting_payload(
                ctx["cohort"]["id"], "COHORT",
                "2027-09-10T10:00:00Z", "2027-09-10T11:00:00Z",
            ),
            headers,
        )
        m1 = validate_success(first, 201)
        assert_cohort_meeting(m1)

        inside_buffer = api.create_cohort_meeting(
            create_cohort_meeting_payload(
                ctx["cohort"]["id"], "COHORT",
                "2027-09-10T11:10:00Z", "2027-09-10T12:00:00Z",
            ),
            headers,
        )
        validate_error(inside_buffer, ApiErrorId.ERR_MENTOR_SCHEDULE_CONFLICT)

    def test_meeting_exactly_one_buffer_width_after_is_legal(self, api):
        """PRD §3.8: "a new meeting conflicts with an existing meeting of the
        same mentor exactly when the new meeting's `starts_at` falls before the
        existing meeting's `ends_at` plus fifteen minutes".
        PRD §3.8: "Every successfully logged meeting raises the cohort's
        `meetings_held_count` by one."

        Design: Difficulty/resource_temporal_overlap/mentor_meeting_buffer_conflict
        """
        ctx = self._setup_matriculated_cohort_for_meetings()
        headers = make_faculty_mentor_headers(ctx["mentor"]["id"])

        validate_success(
            api.create_cohort_meeting(
                create_cohort_meeting_payload(
                    ctx["cohort"]["id"], "COHORT",
                    "2027-09-10T10:00:00Z", "2027-09-10T11:00:00Z",
                ),
                headers,
            ),
            201,
        )
        # 11:15 is NOT before 11:00 + 15 minutes, so the buffer is satisfied.
        edge = api.create_cohort_meeting(
            create_cohort_meeting_payload(
                ctx["cohort"]["id"], "COHORT",
                "2027-09-10T11:15:00Z", "2027-09-10T12:00:00Z",
            ),
            headers,
        )
        validate_success(edge, 201)
        assert get_cohort(ctx["cohort"]["id"])["meetings_held_count"] == 2


class TestInternshipShape:
    def test_internship_inverted_dates_rejected(self, api):
        """PRD §3.8: "an `ends_on` earlier than the `starts_on` is rejected
        with `ERR_INVALID_REQUEST`."

        Design: Corner/validations/internship_inverted_dates_rejected
        """
        ctx = setup_cohort_foundation(cohort_size=3)
        nominee = create_selected_nominee(ctx["program"], ctx["partner"], "Nom One")
        offer = create_offer(nominee["id"], ctx["cohort"]["id"])
        accept_offer(offer)
        scholar = get_scholar_for_nominee(nominee["id"])

        resp = api.create_internship(
            create_internship_payload(scholar["id"], "Acme Corp", "2028-06-30", "2028-01-10"),
            _DIRECTOR,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        internships, meta = validate_paginated(
            api.list_scholar_internships(scholar["id"], _ADMIN)
        )
        assert meta["total_count"] == 0 and internships == []


class TestInternshipOverlapRule:
    def _setup_eligible_scholar(self):
        """One MATRICULATED scholar in GOOD_STANDING."""
        ctx = setup_matriculated_cohort(trained_count=1)
        return ctx, ctx["scholars"][0]

    def test_shared_boundary_date_conflicts(self, api):
        """PRD §3.8: "a conflict exists exactly when the new `starts_on` is on
        or before the existing internship's `ends_on` and the existing
        `starts_on` is on or before the new `ends_on`. Because both intervals
        are inclusive, sharing a boundary date is itself a conflict. An
        overlapping proposal is rejected with `ERR_INTERNSHIP_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/internship_inclusive_boundary_overlap
        """
        _ctx, scholar = self._setup_eligible_scholar()
        first = api.create_internship(
            create_internship_payload(scholar["id"], "Acme Corp", "2028-01-10", "2028-06-30"),
            _DIRECTOR,
        )
        i1 = validate_success(first, 201)
        assert_internship(i1)
        assert i1["status"] == "PROPOSED"

        boundary = api.create_internship(
            create_internship_payload(scholar["id"], "Beta LLC", "2028-06-30", "2028-08-31"),
            _DIRECTOR,
        )
        validate_error(boundary, ApiErrorId.ERR_INTERNSHIP_OVERLAP)

        day_after = api.create_internship(
            create_internship_payload(scholar["id"], "Beta LLC", "2028-07-01", "2028-08-31"),
            _DIRECTOR,
        )
        validate_success(day_after, 201)

    def test_terminated_internship_frees_the_calendar(self, api):
        """PRD §3.8: "A `TERMINATED` internship stops occupying the scholar's
        calendar — the overlap rule ignores it from then on."

        Design: Difficulty/resource_temporal_overlap/internship_inclusive_boundary_overlap
        """
        _ctx, scholar = self._setup_eligible_scholar()
        i1 = validate_success(
            api.create_internship(
                create_internship_payload(
                    scholar["id"], "Acme Corp", "2028-01-10", "2028-06-30"
                ),
                _DIRECTOR,
            ),
            201,
        )
        validate_success(
            api.transition_internship(
                i1["id"], internship_transition_payload("TERMINATED"), _DIRECTOR
            )
        )
        reuse = api.create_internship(
            create_internship_payload(scholar["id"], "Gamma Inc", "2028-03-01", "2028-04-01"),
            _DIRECTOR,
        )
        reused = validate_success(reuse, 201)
        assert reused["status"] == "PROPOSED", (
            "inside the terminated internship's old range is now free"
        )


class TestInternshipEligibilityGate:
    def _setup_probation_scholar(self):
        """MATRICULATED scholar whose standing is then moved to PROBATION."""
        ctx = setup_matriculated_cohort(trained_count=1)
        scholar = ctx["scholars"][0]
        assert scholar["enrollment_status"] == "MATRICULATED"
        scholar_lifecycle(scholar["id"], to_standing="PROBATION")
        return ctx, scholar

    def test_probation_standing_blocks_internship_create(self, api):
        """PRD §3.8: "Eligibility is gated at proposal time: the scholar's
        `enrollment_status` must be `MATRICULATED` or `RETAINED` and the
        scholar's `standing` must be `GOOD_STANDING`, otherwise the proposal
        is rejected with `ERR_SCHOLAR_NOT_ELIGIBLE`."

        Design: Difficulty/cross_entity_state_dependency/internship_blocked_by_scholar_standing
        """
        _ctx, scholar = self._setup_probation_scholar()
        resp = api.create_internship(
            create_internship_payload(scholar["id"], "Acme Corp", "2028-01-10", "2028-06-30"),
            _DIRECTOR,
        )
        validate_error(resp, ApiErrorId.ERR_SCHOLAR_NOT_ELIGIBLE)
        assert resp.status_code == 409, (
            "enrollment MATRICULATED passes one axis; standing PROBATION fails the other"
        )

    def test_blocked_internship_leaves_no_record(self, api):
        """PRD §3.8: "the scholar's `enrollment_status` must be
        `MATRICULATED` or `RETAINED` and the scholar's `standing` must be
        `GOOD_STANDING`, otherwise the proposal is rejected with
        `ERR_SCHOLAR_NOT_ELIGIBLE`."

        Design: Difficulty/cross_entity_state_dependency/internship_blocked_by_scholar_standing
        """
        _ctx, scholar = self._setup_probation_scholar()
        resp = api.create_internship(
            create_internship_payload(scholar["id"], "Acme Corp", "2028-01-10", "2028-06-30"),
            _DIRECTOR,
        )
        validate_error(resp, ApiErrorId.ERR_SCHOLAR_NOT_ELIGIBLE)
        internships, meta = validate_paginated(
            api.list_scholar_internships(scholar["id"], _ADMIN)
        )
        assert meta["total_count"] == 0, "no internship exists afterwards"
        assert get_scholar(scholar["id"])["standing"] == "PROBATION"
