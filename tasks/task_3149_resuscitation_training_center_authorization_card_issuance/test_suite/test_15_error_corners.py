"""Corner coverage: error catalog — duplicate alignment, self-evaluation,
prior-card holder mismatch, remediation attempt cap."""
from test_helpers import (
    ADMIN,
    COORD,
    TC,
    ApiErrorId,
    create_monitoring_payload,
    create_roster_entry_payload,
    create_scheduled_session,
    enroll_student,
    get_success_data,
    make_faculty_headers,
    make_instructor_headers,
    setup_completed_session_with_cards,
    setup_teaching_scenario,
    start_session,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
    create_center_with_faculty,
)


class TestDuplicateActiveAlignment:
    def test_duplicate_active_alignment_rejected(self, api):
        """PRD §3.1: "each alignment starts in `ACTIVE` and at most one
        `ACTIVE` alignment may exist for a given (`training_center_id`,
        `instructor_id`) pair — a second alignment for the same pair is
        rejected with `ERR_DUPLICATE_ACTIVE_ALIGNMENT`."

        Design: Corner/errors/duplicate_active_alignment_rejected
        """
        center, faculty = create_center_with_faculty()
        alignment = get_success_data(api.list_center_alignments(
            center["id"], TC, params={"status": "ACTIVE"}))[0]

        resp = api.create_alignment(
            center["id"],
            {"instructor_id": faculty["id"], "as_faculty": False}, TC)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ACTIVE_ALIGNMENT)

        validate_success(api.end_alignment(alignment["id"], TC))
        created = validate_success(
            api.create_alignment(
                center["id"],
                {"instructor_id": faculty["id"], "as_faculty": False}, TC),
            expected_status=201)
        assert created["status"] == "ACTIVE"

        rows, _ = validate_paginated(
            api.list_instructor_alignments(faculty["id"], TC))
        assert len(rows) == 2
        statuses = sorted(r["status"] for r in rows)
        assert statuses == ["ACTIVE", "ENDED"]


class TestSelfEvaluationForbidden:
    def test_faculty_self_monitoring_is_forbidden(self, api):
        """PRD §3.2: "the calling faculty must not be the candidate themself
        (otherwise `ERR_SELF_EVALUATION_FORBIDDEN` — segregation of duties is
        absolute, and the same rule applies to teaching evaluations)."
        PRD §3.3: "An `EXPIRED` instructor re-enters the candidate pathway when
        a `TCAdmin` resets candidacy — the move from `EXPIRED` back to
        `CANDIDATE` requires the instructor to currently be in `EXPIRED`
        (otherwise `ERR_INSTRUCTOR_NOT_EXPIRED`). The reset does not erase
        history: `is_faculty` is unchanged, any `TCAlignment` rows are
        unchanged, and prior monitorings and teaching evaluations persist."

        Design: Corner/errors/faculty_self_monitoring_is_forbidden
        """
        center, faculty = create_center_with_faculty()
        # Advance the clock past the faculty's renewal_due_at so the sweep
        # moves them CERTIFIED -> EXPIRED, then reset to CANDIDATE; is_faculty
        # remains true across the reset.
        get_success_data(api.set_clock("2028-12-15T00:00:00Z", ADMIN))
        reset = validate_success(api.reset_candidacy(faculty["id"], TC))
        assert reset["status"] == "CANDIDATE"

        resp = api.monitor_instructor(
            faculty["id"],
            create_monitoring_payload(monitored_at="2028-12-20T00:00:00Z"),
            make_faculty_headers(faculty["id"]))
        # PRD §2.5 rejects a TrainingFaculty caller whose underlying
        # instructor record is not CERTIFIED with ERR_INSUFFICIENT_PERMISSIONS
        # at the role-authorization stage, before the segregation-of-duties
        # check is reached; PRD §3.2 names ERR_SELF_EVALUATION_FORBIDDEN for
        # self-monitoring. Either faithful reading rejects the request.
        validate_error_is_one_of(resp, [
            ApiErrorId.ERR_SELF_EVALUATION_FORBIDDEN,
            ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS,
        ])

        rows, meta = validate_paginated(
            api.list_monitorings(faculty["id"], TC))
        assert meta["total_count"] == 0


class TestPriorCardHolderMismatch:
    def test_prior_card_holder_mismatch_rejected(self, api):
        """PRD §3.6: "When `prior_card_id` is supplied the referenced card's
        `holder_email` must match the enrollment's `student_email`; a mismatch
        rejects with `ERR_PRIOR_CARD_HOLDER_MISMATCH`."

        Design: Corner/errors/prior_card_holder_mismatch_rejected
        """
        built = setup_completed_session_with_cards(num_students=1)
        ctx = built
        card = built["cards"][0]
        session2 = create_scheduled_session(
            ctx, start_at="2026-10-11T14:00:00Z",
            end_at="2026-10-11T18:00:00Z")
        assert session2["seats_available"] == 6

        resp = api.add_roster_entry(
            session2["id"],
            create_roster_entry_payload(
                student_name="Rita Rescuer", student_email="rita@x.example",
                prior_card_id=card["id"]),
            COORD)
        validate_error(resp, ApiErrorId.ERR_PRIOR_CARD_HOLDER_MISMATCH)

        s2 = validate_success(api.get_course_session(session2["id"], COORD))
        assert s2["seats_available"] == 6  # no seat consumed
        _, meta = validate_paginated(api.list_roster(session2["id"], COORD))
        assert meta["total_count"] == 0


class TestRemediationAttemptCap:
    def test_remediation_third_attempt_exceeds_limit(self, api):
        """PRD §3.6: "The two-attempt cap is absolute: a third attempt, or a
        second attempt without a prior `REMEDIATION_REQUIRED`, is rejected with
        `ERR_REMEDIATION_LIMIT_EXCEEDED`."
        PRD §3.6: "An initial attempt yields `PASS` when no critical item has
        `passed` false *and* `score_percent` is at least 84.00; otherwise it
        yields `REMEDIATION_REQUIRED`. A remediation retest ... yields `PASS`
        when no critical item failed *and* `score_percent` is at least 90.00;
        otherwise it yields `FAIL`, which is terminal."

        Design: Corner/errors/remediation_third_attempt_exceeds_limit
        """
        ctx = setup_teaching_scenario()
        session = create_scheduled_session(ctx)
        entry = enroll_student(session["id"])
        start_session(session["id"])
        lead_headers = make_instructor_headers(ctx["lead"]["id"])

        failing = {"items": [
            {"item_code": "SCENE", "critical": True, "passed": False},
            {"item_code": "COMP", "critical": False, "passed": True},
        ]}
        # Attempt 1: failed critical item -> REMEDIATION_REQUIRED regardless
        # of percentage.
        att1 = validate_success(
            api.create_skills_evaluation(entry["id"], failing, lead_headers),
            expected_status=201)
        assert att1["outcome"] == "REMEDIATION_REQUIRED"

        # Attempt 2 (retest): failed critical again -> FAIL (terminal).
        att2 = validate_success(
            api.create_skills_evaluation(entry["id"], failing, lead_headers),
            expected_status=201)
        assert att2["outcome"] == "FAIL"
        entry_now = validate_success(api.get_roster_entry(entry["id"], TC))
        assert entry_now["status"] == "FAILED"

        # Attempt 3: rejected outright.
        passing = {"items": [
            {"item_code": "SCENE", "critical": True, "passed": True},
            {"item_code": "COMP", "critical": False, "passed": True},
        ]}
        resp = api.create_skills_evaluation(entry["id"], passing, lead_headers)
        # PRD §2.5 runs the roster-entry state precondition (level 6, the
        # entry is FAILED after the terminal attempt, so
        # ERR_ROSTER_ENTRY_NOT_ENROLLED) before the two-attempt cap
        # (level 10, ERR_REMEDIATION_LIMIT_EXCEEDED); PRD §3.6 names the cap
        # for a third attempt. Either faithful ordering rejects the attempt.
        validate_error_is_one_of(resp, [
            ApiErrorId.ERR_REMEDIATION_LIMIT_EXCEEDED,
            ApiErrorId.ERR_ROSTER_ENTRY_NOT_ENROLLED,
        ])

        rows, meta = validate_paginated(
            api.list_skills_evaluations(entry["id"], TC))
        assert len(rows) == 2
        assert meta["total_count"] == 2
