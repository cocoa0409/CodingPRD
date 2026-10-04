"""Priority pair validation conflicts: the first failing pipeline stage wins."""
from test_helpers import (
    COORD,
    QA,
    TC,
    ApiErrorId,
    close_audit_corrective,
    create_course_session_payload,
    create_scheduled_session,
    enroll_student,
    get_success_data,
    make_instructor_headers,
    open_audit,
    setup_teaching_scenario,
    start_session,
    validate_error,
    validate_success,
)


class TestStateBeatsBusinessSafetyOnSessionComplete:
    def test_cancelled_session_complete_reports_state_error_not_probation(self, api):
        """PRD §2.5: "Every mutating request passes through a validation
        pipeline whose checks run in a fixed order. A request that fails an
        earlier check is rejected immediately and never reaches a later check;
        the `error_id` returned is always the first failing rule."
        PRD §2.5: "6. **State preconditions.** ... State errors carry codes
        like `ERR_SESSION_NOT_IN_PROGRESS`."
        PRD §3.7: "the owning center must be `ACTIVE` (a `PROBATION` center
        rejects with `ERR_CENTER_ON_PROBATION` ...)."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_session_complete
        """
        ctx = setup_teaching_scenario()
        session = create_scheduled_session(ctx)
        enroll_student(session["id"])
        start_session(session["id"])
        # IN_PROGRESS -> CANCELLED (manual cancel), then drive the center to
        # PROBATION via a corrective-action audit close.
        validate_success(api.cancel_session(session["id"], COORD))
        audit = open_audit(ctx["center"]["id"])
        close_audit_corrective(audit["id"])
        center_now = validate_success(
            api.get_training_center(ctx["center"]["id"], QA))
        assert center_now["status"] == "PROBATION"

        resp = api.complete_session(
            session["id"], make_instructor_headers(ctx["lead"]["id"]))
        err = validate_error(resp, ApiErrorId.ERR_SESSION_NOT_IN_PROGRESS)
        assert err["error_id"] != ApiErrorId.ERR_CENTER_ON_PROBATION

        center_after = validate_success(
            api.get_training_center(ctx["center"]["id"], QA))
        assert center_after["status"] == "PROBATION"

    def test_completed_session_complete_reports_state_error(self, api):
        """PRD §3.7: "Completion is gated: the session must currently be
        `IN_PROGRESS` (otherwise `ERR_SESSION_NOT_IN_PROGRESS`)."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_session_complete
        """
        ctx = setup_teaching_scenario()
        session = create_scheduled_session(ctx)
        start_session(session["id"])
        lead_headers = make_instructor_headers(ctx["lead"]["id"])
        validate_success(api.complete_session(session["id"], lead_headers))
        resp = api.complete_session(session["id"], lead_headers)
        validate_error(resp, ApiErrorId.ERR_SESSION_NOT_IN_PROGRESS)


class TestBusinessSafetyBeatsReferentialOnSessionCreate:
    def test_suspended_site_reports_site_suspended_not_alignment(self, api):
        """PRD §2.5: "the `error_id` returned is always the first failing
        rule."
        PRD §3.4: "The center gate runs first. ... a `SUSPENDED` site rejects
        with `ERR_SITE_SUSPENDED`."
        PRD §3.4: "The referential gate runs last among the non-quota checks.
        ... an instructor who is certified but not aligned to this center
        rejects with `ERR_INSTRUCTOR_NOT_ALIGNED`."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_referential_on_session_create
        """
        # Full chain through certification but WITHOUT aligning the candidate;
        # the site is then suspended.
        ctx = setup_teaching_scenario()
        # Remove the candidate's alignment by ending it.
        alignments = get_success_data(api.list_center_alignments(
            ctx["center"]["id"], TC, params={"status": "ACTIVE"}))
        lead_alignment = [a for a in alignments
                          if a["instructor_id"] == ctx["lead"]["id"]][0]
        validate_success(api.end_alignment(lead_alignment["id"], TC))
        validate_success(api.suspend_site(ctx["site"]["id"], TC))

        payload = create_course_session_payload(
            ctx["center"]["id"], ctx["site"]["id"], ctx["lead"]["id"],
            ctx["guidelines_version"]["id"])
        resp = api.create_course_session(payload, COORD)
        err = validate_error(resp, ApiErrorId.ERR_SITE_SUSPENDED)
        assert err["error_id"] != ApiErrorId.ERR_INSTRUCTOR_NOT_ALIGNED

        sessions = get_success_data(api.list_center_sessions(
            ctx["center"]["id"], TC))
        assert sessions == []

    def test_unaligned_instructor_reports_referential_error_when_site_ok(self, api):
        """PRD §3.4: "The instructor referenced by `primary_instructor_id` must
        hold an `ACTIVE` `TCAlignment` to the center; an instructor who is
        certified but not aligned to this center rejects with
        `ERR_INSTRUCTOR_NOT_ALIGNED`."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_referential_on_session_create
        """
        ctx = setup_teaching_scenario()
        alignments = get_success_data(api.list_center_alignments(
            ctx["center"]["id"], TC, params={"status": "ACTIVE"}))
        lead_alignment = [a for a in alignments
                          if a["instructor_id"] == ctx["lead"]["id"]][0]
        validate_success(api.end_alignment(lead_alignment["id"], TC))

        payload = create_course_session_payload(
            ctx["center"]["id"], ctx["site"]["id"], ctx["lead"]["id"],
            ctx["guidelines_version"]["id"])
        resp = api.create_course_session(payload, COORD)
        validate_error(resp, ApiErrorId.ERR_INSTRUCTOR_NOT_ALIGNED)
