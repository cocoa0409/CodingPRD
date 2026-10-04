"""Non-linear state machine cycles: center probation loop and instructor
certification cycle."""
from test_helpers import (
    ADMIN,
    QA,
    TC,
    certify_candidate,
    close_audit_corrective,
    create_active_center,
    create_center_with_faculty,
    create_legacy_certified_instructor,
    create_monitoring_payload,
    get_success_data,
    make_faculty_headers,
    open_audit,
    validate_success,
)


class TestTrainingCenterProbationCycle:
    def test_corrective_close_then_reinstate_cycles_through_probation(self, api):
        """PRD §3.1: "Reinstatement from `PROBATION` returns the center to
        `ACTIVE`; reinstatement from `SUSPENDED` returns it to `PROBATION`, not
        directly to `ACTIVE`."
        PRD §3.8: "A corrective-action close additionally moves the target
        center from `ACTIVE` to `PROBATION` (stamping `probation_started_at`
        with the current clock)."

        Design: Difficulty/non_linear_state_machine/training_center_probation_cycle
        """
        center, faculty, site = create_active_center()
        audit = open_audit(center["id"])

        closed = validate_success(api.close_audit(
            audit["id"], {"outcome": "CORRECTIVE_ACTION"}, QA))
        assert closed["status"] == "CLOSED_CORRECTIVE"
        c = validate_success(api.get_training_center(center["id"], QA))
        assert c["status"] == "PROBATION"
        assert c["probation_started_at"] is not None

        reinstated1 = validate_success(
            api.reinstate_training_center(center["id"], ADMIN))
        assert reinstated1["status"] == "ACTIVE"

        suspended = validate_success(
            api.suspend_training_center(center["id"], QA))
        assert suspended["status"] == "SUSPENDED"

        reinstated2 = validate_success(
            api.reinstate_training_center(center["id"], QA))
        # Reinstate from SUSPENDED lands on PROBATION, not ACTIVE.
        assert reinstated2["status"] == "PROBATION"
        assert reinstated2["probation_started_at"] is not None

    def test_probation_stamps_then_clears_probation_started_at(self, api):
        """PRD §3.1: "When a center leaves `PROBATION` (reinstate to `ACTIVE`),
        its `probation_started_at` is cleared to null; when it enters
        `PROBATION` (either from `ACTIVE` via corrective-action audit close, or
        from `SUSPENDED` via reinstate), `probation_started_at` is stamped with
        the current clock."

        Design: Difficulty/non_linear_state_machine/training_center_probation_cycle
        """
        center, faculty, site = create_active_center()
        c0 = validate_success(api.get_training_center(center["id"], TC))
        assert c0["probation_started_at"] is None

        audit = open_audit(center["id"])
        close_audit_corrective(audit["id"])
        c1 = validate_success(api.get_training_center(center["id"], TC))
        assert c1["status"] == "PROBATION"
        assert c1["probation_started_at"] == "2026-09-01T00:00:00Z"

        validate_success(api.reinstate_training_center(center["id"], ADMIN))
        c2 = validate_success(api.get_training_center(center["id"], TC))
        assert c2["status"] == "ACTIVE"
        assert c2["probation_started_at"] is None


class TestInstructorCertificationCycle:
    def test_expiry_sweep_then_reset_reenters_candidate_pathway(self, api):
        """PRD §3.3: "If the window lapses without renewal, the next clock
        advance that takes the current time strictly past `renewal_due_at`
        moves the instructor from `CERTIFIED` to `EXPIRED`. An `EXPIRED`
        instructor re-enters the candidate pathway when a `TCAdmin` resets
        candidacy — the move from `EXPIRED` back to `CANDIDATE` requires the
        instructor to currently be in `EXPIRED` (otherwise
        `ERR_INSTRUCTOR_NOT_EXPIRED`)."

        Design: Difficulty/non_linear_state_machine/instructor_certification_cycle
        """
        center, faculty = create_center_with_faculty()
        cand = certify_candidate(center["id"], faculty["id"])
        assert cand["status"] == "CERTIFIED"
        assert cand["renewal_due_at"] == "2028-09-01T00:00:00Z"

        get_success_data(api.set_clock("2028-12-15T00:00:00Z", ADMIN))
        expired = validate_success(api.get_instructor(cand["id"], TC))
        assert expired["status"] == "EXPIRED"

        reset = validate_success(api.reset_candidacy(cand["id"], TC))
        assert reset["status"] == "CANDIDATE"

    def test_recertification_reuses_lifetime_evaluation_history(self, api):
        """PRD §3.3: "The reset does not erase history: `is_faculty` is
        unchanged, any `TCAlignment` rows are unchanged, and prior monitorings
        and teaching evaluations persist (which is why a candidate who was once
        certified can re-certify quickly — the evaluation floor counts lifetime
        rows)."
        PRD §3.2: "Successful certification sets `certified_since` to the
        current clock, sets `renewal_due_at` to twenty-four months after the
        current clock, and leaves `renewal_count` at its current value (zero
        for a first certification)."

        Design: Difficulty/non_linear_state_machine/instructor_certification_cycle
        """
        center, faculty = create_center_with_faculty()
        cand = certify_candidate(center["id"], faculty["id"])
        assert cand["status"] == "CERTIFIED"

        get_success_data(api.set_clock("2028-12-15T00:00:00Z", ADMIN))
        reset = validate_success(api.reset_candidacy(cand["id"], TC))
        assert reset["status"] == "CANDIDATE"

        # The original faculty was swept to EXPIRED by the same clock advance;
        # register a fresh legacy faculty at the new clock instant.
        faculty2 = create_legacy_certified_instructor(
            center["id"], is_faculty=True, full_name="Gina Faculty",
            email="gina@x.example")
        fac2 = make_faculty_headers(faculty2["id"])
        get_success_data(api.monitor_instructor(
            cand["id"],
            create_monitoring_payload(
                monitored_at="2028-12-20T00:00:00Z"),
            fac2))
        monitored = validate_success(api.get_instructor(cand["id"], TC))
        assert monitored["status"] == "MONITORED"

        # Prior evaluations persisted, so the >= 2 / avg >= 4.00 gate passes
        # with no new evaluations recorded.
        recertified = validate_success(api.certify_instructor(cand["id"], TC))
        assert recertified["status"] == "CERTIFIED"
        assert recertified["renewal_due_at"] == "2030-12-15T00:00:00Z"
