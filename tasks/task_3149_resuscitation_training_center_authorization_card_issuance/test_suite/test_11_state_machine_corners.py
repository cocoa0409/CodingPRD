"""Corner coverage: state machine transitions — terminal lockouts, invalid
transitions, idempotency, initial states."""
from test_helpers import (
    ADMIN,
    QA,
    TC,
    ApiErrorId,
    create_active_center,
    create_center_with_faculty,
    create_finding,
    create_instructor_payload,
    create_scheduled_session,
    create_teaching_evaluation_payload,
    enroll_student,
    get_success_data,
    make_faculty_headers,
    open_audit,
    setup_completed_session_with_cards,
    setup_teaching_scenario,
    suspend_center,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)
from test_helpers.factories import create_guidelines_version_payload


class TestRevokedCenterTerminal:
    def test_revoked_center_is_terminal_and_rejects_reinstate(self, api):
        """PRD §3.1: "Revoking a `SUSPENDED` center is terminal and
        irreversible: every site that is not already `DECOMMISSIONED` becomes
        `DECOMMISSIONED`, every `ACTIVE` alignment becomes `ENDED`, and every
        remaining `SCHEDULED` session of the center is cancelled with
        `cancel_reason` set to `CENTER_SUSPENDED`, with `ENROLLED` roster
        entries on those sessions cancelled in turn."
        PRD §5: `ERR_CENTER_REVOKED` 409 Conflict.

        Design: Corner/state_machines/revoked_center_is_terminal_and_rejects_reinstate
        """
        center, faculty, site = create_active_center()
        suspend_center(center["id"])
        revoked = validate_success(
            api.revoke_training_center(center["id"], ADMIN))
        assert revoked["status"] == "REVOKED"

        resp = api.reinstate_training_center(center["id"], ADMIN)
        # PRD declares revocation terminal and irreversible and lists
        # ERR_CENTER_REVOKED in the error catalog, but does not pin the
        # specific error_id a reinstate attempt on a REVOKED center returns;
        # a state-precondition rejection (ERR_CENTER_NOT_ACTIVE) is an
        # equally faithful reading.
        validate_error_is_one_of(resp, [
            ApiErrorId.ERR_CENTER_REVOKED,
            ApiErrorId.ERR_CENTER_NOT_ACTIVE,
        ])
        still = validate_success(api.get_training_center(center["id"], TC))
        assert still["status"] == "REVOKED"


class TestCertifyFromCandidate:
    def test_certify_from_candidate_returns_not_monitored(self, api):
        """PRD §3.2: "Certification requires the instructor to currently be in
        `MONITORED` status (otherwise `ERR_INSTRUCTOR_NOT_MONITORED`)."

        Design: Corner/state_machines/certify_from_candidate_returns_not_monitored
        """
        center, faculty = create_center_with_faculty()
        cand = get_success_data(api.create_instructor(
            create_instructor_payload(center["id"]), ADMIN))
        fac = make_faculty_headers(faculty["id"])
        # Two evaluations but NO monitoring — the state gate must fire first.
        get_success_data(api.create_teaching_evaluation(
            cand["id"], create_teaching_evaluation_payload(
                score=5, notes="Strong lecture."), fac))
        get_success_data(api.create_teaching_evaluation(
            cand["id"], create_teaching_evaluation_payload(
                score=5, notes="Strong skills station."), fac))

        resp = api.certify_instructor(cand["id"], TC)
        err = validate_error(resp, ApiErrorId.ERR_INSTRUCTOR_NOT_MONITORED)
        assert err["error_id"] != ApiErrorId.ERR_EVALUATION_AVERAGE_BELOW_THRESHOLD
        still = validate_success(api.get_instructor(cand["id"], TC))
        assert still["status"] == "CANDIDATE"


class TestRosterEntryInitialState:
    def test_roster_entry_starts_enrolled_with_remediation_unused(self, api):
        """PRD §3.6: "Enrollment creates a `RosterEntry` — its
        `course_session_id` is taken from the path — in `ENROLLED` status with
        `remediation_used` initially `false`."

        Design: Corner/state_machines/roster_entry_starts_enrolled_with_remediation_unused
        """
        ctx = setup_teaching_scenario()
        session = create_scheduled_session(ctx)
        entry = enroll_student(session["id"])
        assert entry["status"] == "ENROLLED"
        assert entry["remediation_used"] is False


class TestCardRevokeNotIdempotent:
    def test_card_second_revoke_fails_not_active(self, api):
        """PRD §3.7: "A `QAAuditor` or `NationalAdmin` may revoke it, which
        requires the card to currently be `ACTIVE` (otherwise
        `ERR_CARD_NOT_ACTIVE`) and moves it to terminal `REVOKED`, decrementing
        the issuing center's `active_card_count` by 1 without touching
        `cards_issued_count`."

        Design: Corner/state_machines/card_second_revoke_fails_not_active
        """
        built = setup_completed_session_with_cards(num_students=1)
        card = built["cards"][0]
        center_id = built["center"]["id"]

        first = validate_success(api.revoke_card(card["id"], QA))
        assert first["status"] == "REVOKED"

        resp = api.revoke_card(card["id"], QA)
        validate_error(resp, ApiErrorId.ERR_CARD_NOT_ACTIVE)

        center = validate_success(api.get_training_center(center_id, QA))
        # Decremented exactly once.
        assert center["active_card_count"] == 0
        assert center["cards_issued_count"] == 1


class TestAuditCloseCriticalLockout:
    def test_critical_finding_then_clean_close_is_rejected(self, api):
        """PRD §3.8: "Closing with `outcome` set to `CLEAN` moves the audit to
        `CLOSED_CLEAN` and is only permitted when no finding on the audit has
        `severity` `CRITICAL` — otherwise
        `ERR_AUDIT_HAS_OPEN_CRITICAL_FINDINGS`. Closing with `outcome` set to
        `CORRECTIVE_ACTION` moves the audit to `CLOSED_CORRECTIVE` and has no
        critical-finding restriction."
        PRD §3.8: "a center that is already `SUSPENDED` remains `SUSPENDED` —
        the close does not demote it further."

        Design: Corner/state_machines/critical_finding_then_clean_close_is_rejected
        """
        center, faculty, site = create_active_center()
        audit = open_audit(center["id"])
        create_finding(audit["id"], severity="MINOR",
                       description="Sign-in sheet gaps.")
        # The CRITICAL finding suspends the center on append.
        create_finding(audit["id"], severity="CRITICAL",
                       description="Unmonitored instructor teaching.")

        resp = api.close_audit(audit["id"], {"outcome": "CLEAN"}, QA)
        validate_error(resp, ApiErrorId.ERR_AUDIT_HAS_OPEN_CRITICAL_FINDINGS)

        closed = validate_success(
            api.close_audit(audit["id"], {"outcome": "CORRECTIVE_ACTION"}, QA))
        assert closed["status"] == "CLOSED_CORRECTIVE"

        center_now = validate_success(api.get_training_center(center["id"], QA))
        assert center_now["status"] == "SUSPENDED"


class TestGuidelinesActivationTerminalLockout:
    def test_guidelines_activation_terminal_lockout(self, api):
        """PRD §3.9: "A `NationalAdmin` activates a `DRAFT` version; attempting
        to activate a version that is already `ACTIVE` or already `SUPERSEDED`
        is rejected with `ERR_GUIDELINES_VERSION_CONFLICT`."

        Design: Corner/state_machines/guidelines_activation_terminal_lockout
        """
        from test_helpers import set_clock_start
        set_clock_start()
        gv1 = get_success_data(api.create_guidelines_version(
            create_guidelines_version_payload(code="G2025"), ADMIN))
        get_success_data(api.activate_guidelines_version(gv1["id"], ADMIN))
        gv2 = get_success_data(api.create_guidelines_version(
            create_guidelines_version_payload(
                code="G2030", title="2030 AHA Guidelines",
                published_at="2030-10-01T00:00:00Z",
                transition_deadline_at="2027-03-01T00:00:00Z"), ADMIN))
        get_success_data(api.activate_guidelines_version(gv2["id"], ADMIN))

        resp = api.activate_guidelines_version(gv1["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_GUIDELINES_VERSION_CONFLICT)
        v1 = validate_success(api.get_guidelines_version(gv1["id"], ADMIN))
        v2 = validate_success(api.get_guidelines_version(gv2["id"], ADMIN))
        assert v1["status"] == "SUPERSEDED"
        assert v2["status"] == "ACTIVE"
