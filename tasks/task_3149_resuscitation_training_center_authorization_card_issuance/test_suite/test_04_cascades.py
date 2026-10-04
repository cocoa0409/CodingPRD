"""Transitive cascades: guidelines transition sweep and CRITICAL-finding
center suspension."""
from test_helpers import (
    ADMIN,
    COORD,
    QA,
    create_guidelines_version_payload,
    create_scheduled_session,
    enroll_student,
    get_success_data,
    open_audit,
    setup_teaching_scenario,
    validate_success,
)


class TestGuidelinesActivationCancelsLegacySessions:
    def test_activation_supersedes_and_sweeps_past_deadline_sessions(self, api):
        """PRD §3.9: "Activation supersedes the previously `ACTIVE` version (if
        any), moving it to `SUPERSEDED`, and runs the transition sweep against
        the just-superseded version: every `CourseSession` whose
        `guidelines_version_id` references the superseded version, whose
        `status` is `SCHEDULED`, and whose `start_at` is strictly after the new
        version's `transition_deadline_at` is cancelled with `cancel_reason`
        set to `GUIDELINES_TRANSITION`, and its `ENROLLED` roster entries are
        cancelled in turn with `seats_available` recomputing to `capacity`."

        Design: Difficulty/transitive_cascade/guidelines_activation_cancels_legacy_sessions
        """
        ctx = setup_teaching_scenario()
        gv_old = ctx["guidelines_version"]

        s1 = create_scheduled_session(
            ctx, start_at="2027-04-01T14:00:00Z", end_at="2027-04-01T18:00:00Z")
        e1 = enroll_student(s1["id"], "Sam Student", "sam@x.example")
        s2 = create_scheduled_session(
            ctx, start_at="2027-02-01T14:00:00Z", end_at="2027-02-01T18:00:00Z")
        e2 = enroll_student(s2["id"], "Rita Rescuer", "rita@x.example")

        gv_new = get_success_data(api.create_guidelines_version(
            create_guidelines_version_payload(
                code="G2030", title="2030 AHA Guidelines",
                published_at="2030-10-01T00:00:00Z",
                transition_deadline_at="2027-03-01T00:00:00Z"), ADMIN))
        activated = validate_success(
            api.activate_guidelines_version(gv_new["id"], ADMIN))
        assert activated["status"] == "ACTIVE"

        old_now = validate_success(
            api.get_guidelines_version(gv_old["id"], ADMIN))
        assert old_now["status"] == "SUPERSEDED"

        # Hop 2: session past the deadline is cancelled.
        s1_now = validate_success(api.get_course_session(s1["id"], COORD))
        assert s1_now["status"] == "CANCELLED"
        assert s1_now["cancel_reason"] == "GUIDELINES_TRANSITION"
        # Hop 4: the seat is released back to capacity.
        assert s1_now["seats_available"] == 6
        # Hop 3: its ENROLLED roster entry is cancelled.
        e1_now = validate_success(api.get_roster_entry(e1["id"], COORD))
        assert e1_now["status"] == "CANCELLED"

        # The before-deadline session survives, flagged LEGACY.
        s2_now = validate_success(api.get_course_session(s2["id"], COORD))
        assert s2_now["status"] == "SCHEDULED"
        assert s2_now["curriculum_flag"] == "LEGACY"
        e2_now = validate_success(api.get_roster_entry(e2["id"], COORD))
        assert e2_now["status"] == "ENROLLED"

    def test_session_at_exact_deadline_survives_strict_greater_sweep(self, api):
        """PRD §3.9: "The boundary is strict-greater: a session whose
        `start_at` equals the deadline exactly survives the sweep."
        PRD §3.9: "Sessions in `IN_PROGRESS`, `COMPLETED`, or `CANCELLED` are
        untouched by the sweep."

        Design: Difficulty/transitive_cascade/guidelines_activation_cancels_legacy_sessions
        """
        ctx = setup_teaching_scenario()
        # Session starting exactly at the incoming version's deadline.
        s = create_scheduled_session(
            ctx, start_at="2027-03-01T00:00:00Z", end_at="2027-03-01T04:00:00Z")
        gv_new = get_success_data(api.create_guidelines_version(
            create_guidelines_version_payload(
                code="G2030", title="2030 AHA Guidelines",
                published_at="2030-10-01T00:00:00Z",
                transition_deadline_at="2027-03-01T00:00:00Z"), ADMIN))
        validate_success(api.activate_guidelines_version(gv_new["id"], ADMIN))

        s_now = validate_success(api.get_course_session(s["id"], COORD))
        assert s_now["status"] == "SCHEDULED"
        assert s_now["curriculum_flag"] == "LEGACY"


class TestCriticalFindingSuspendsCenterCascade:
    def test_critical_finding_suspends_center_site_session_roster(self, api):
        """PRD §3.8: "A `CRITICAL` finding does more than deduct points: the
        moment it is appended, the target center — whether `ACTIVE` or
        `PROBATION` — moves to `SUSPENDED`, and the full center-suspension
        cascade of §3.1 fires: every `ALIGNED` site of the center moves to
        `SUSPENDED`, every `SCHEDULED` session at those sites is cancelled with
        `cancel_reason` set to `CENTER_SUSPENDED`, every `ENROLLED` roster
        entry on those sessions is cancelled, and each affected session's
        `seats_available` recomputes to `capacity`."

        Design: Difficulty/transitive_cascade/critical_finding_suspends_center_cascade
        """
        ctx = setup_teaching_scenario()
        session = create_scheduled_session(ctx)
        entry = enroll_student(session["id"])
        audit = open_audit(ctx["center"]["id"])

        finding = validate_success(
            api.create_audit_finding(
                audit["id"],
                {"severity": "CRITICAL",
                 "description": "Cards issued without skills testing records."},
                QA),
            expected_status=201)
        assert finding["deduction_points"] == 40

        center_now = validate_success(
            api.get_training_center(ctx["center"]["id"], QA))
        assert center_now["status"] == "SUSPENDED"

        site_now = validate_success(api.get_site(ctx["site"]["id"], QA))
        assert site_now["status"] == "SUSPENDED"

        session_now = validate_success(
            api.get_course_session(session["id"], COORD))
        assert session_now["status"] == "CANCELLED"
        assert session_now["cancel_reason"] == "CENTER_SUSPENDED"
        assert session_now["seats_available"] == 6

        entry_now = validate_success(api.get_roster_entry(entry["id"], COORD))
        assert entry_now["status"] == "CANCELLED"

    def test_critical_finding_deducts_40_and_updates_compliance_score(self, api):
        """PRD §3.8: "Each finding's `deduction_points` is computed as the
        severity's base points — 1.25 for `OBSERVATION`, 4.5 for `MINOR`, 12.5
        for `MAJOR`, and 40 for `CRITICAL` — multiplied by 1.5 when
        `is_repeat_offense` is true and by 1.0 otherwise."
        PRD §3.8: "the moment it is appended, the target center — whether
        `ACTIVE` or `PROBATION` — moves to `SUSPENDED`."

        Design: Difficulty/transitive_cascade/critical_finding_suspends_center_cascade
        """
        ctx = setup_teaching_scenario()
        audit = open_audit(ctx["center"]["id"])
        finding = validate_success(
            api.create_audit_finding(
                audit["id"],
                {"severity": "CRITICAL",
                 "description": "Unmonitored instructor teaching."}, QA),
            expected_status=201)
        assert finding["deduction_points"] == 40

        audit_now = validate_success(api.get_quality_audit(audit["id"], QA))
        assert audit_now["compliance_score"] == 60

        center_now = validate_success(
            api.get_training_center(ctx["center"]["id"], QA))
        assert center_now["status"] == "SUSPENDED"
