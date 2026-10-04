"""Branch training sessions, enrollment capacity, and certification."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS,
    create_project, create_session, create_staff, enroll, set_clock,
    create_training_session_payload, create_staff_payload,
)

TRAINER = TEST_USERS["trainer_headers"]


class TestSessionWindows:
    def test_start_window_and_complete_window_boundaries(self, api):
        """PRD §3.9: "Starting a session (`SCHEDULED → IN_PROGRESS`) requires
        the clock to be at or after `scheduled_start` and strictly before
        `scheduled_end`."
        PRD §3.9: "Completing a session (`IN_PROGRESS → COMPLETED`) requires
        the clock to be at or past `scheduled_end` and **no** enrollment left
        in `RESERVED`"

        Design: Corner/validations/training_start_before_window_and_late_complete_blocked
        """
        project = create_project()
        sess = create_session(project["id"])
        set_clock("2026-09-02T08:59:59Z")
        resp = api.start_training_session(sess["id"], TRAINER)
        validate_error(resp, ApiErrorId.ERR_OUTSIDE_WINDOW)
        set_clock("2026-09-02T09:00:00Z")
        started = get_success_data(api.start_training_session(sess["id"], TRAINER))
        assert started["status"] == "IN_PROGRESS"
        resp2 = api.complete_training_session(sess["id"], TRAINER)
        validate_error(resp2, ApiErrorId.ERR_OUTSIDE_WINDOW)
        set_clock("2026-09-02T12:00:00Z")
        done = get_success_data(api.complete_training_session(sess["id"], TRAINER))
        assert done["status"] == "COMPLETED"


class TestBranchOverlap:
    def test_half_open_overlap_and_adjacency(self, api):
        """PRD §3.9: "Two sessions covering the same `branch_name` may not
        overlap in time — the interval from `scheduled_start` to
        `scheduled_end` is treated as half-open, so a session whose start
        exactly equals another session's end is allowed — and a genuinely
        overlapping, non-`CANCELLED` session causes rejection with
        `ERR_SESSION_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/branch_session_half_open_overlap
        """
        project = create_project()
        create_session(
            project["id"], scheduled_start="2026-09-02T10:00:00Z",
            scheduled_end="2026-09-02T12:00:00Z", capacity=5,
        )
        s0 = create_session(
            project["id"], scheduled_start="2026-09-03T11:00:00Z",
            scheduled_end="2026-09-03T13:00:00Z", capacity=5,
        )
        get_success_data(api.cancel_training_session(s0["id"], TRAINER))
        resp = api.create_training_session(
            create_training_session_payload(
                project["id"], scheduled_start="2026-09-02T11:00:00Z",
                scheduled_end="2026-09-02T13:00:00Z", capacity=5,
            ),
            TRAINER,
        )
        validate_error(resp, ApiErrorId.ERR_SESSION_OVERLAP)
        adjacent = get_success_data(
            api.create_training_session(
                create_training_session_payload(
                    project["id"], scheduled_start="2026-09-02T12:00:00Z",
                    scheduled_end="2026-09-02T14:00:00Z", capacity=5,
                ),
                TRAINER,
            ),
            201,
        )
        assert adjacent["status"] == "SCHEDULED"

    def test_cancelled_session_does_not_block_new_session(self, api):
        """PRD §3.9: "Two sessions covering the same `branch_name` may not
        overlap in time — the interval from `scheduled_start` to
        `scheduled_end` is treated as half-open, so a session whose start
        exactly equals another session's end is allowed — and a genuinely
        overlapping, non-`CANCELLED` session causes rejection with
        `ERR_SESSION_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/branch_session_half_open_overlap
        """
        project = create_project()
        s0 = create_session(
            project["id"], scheduled_start="2026-09-02T10:00:00Z",
            scheduled_end="2026-09-02T12:00:00Z", capacity=5,
        )
        get_success_data(api.cancel_training_session(s0["id"], TRAINER))
        replacement = get_success_data(
            api.create_training_session(
                create_training_session_payload(
                    project["id"], scheduled_start="2026-09-02T10:00:00Z",
                    scheduled_end="2026-09-02T12:00:00Z", capacity=5,
                ),
                TRAINER,
            ),
            201,
        )
        assert replacement["status"] == "SCHEDULED"


class TestEnrollmentCapacity:
    def test_capacity_full_rejects_second_enrollment(self, api):
        """PRD §3.9: "Enrollment respects the session's capacity — enrolling
        beyond `capacity` violates `ERR_INVARIANT_VIOLATION` — and the same
        staff member may not be enrolled twice in the same session, likewise an
        invariant violation."

        Design: Difficulty/boundary_precision_check/session_enrollment_capacity_full_rejects
        """
        project = create_project()
        sess = create_session(project["id"], capacity=1)
        e1 = create_staff(project["id"], employee_code="E1")
        e2 = create_staff(project["id"], employee_code="E2", full_name="Teller Two")
        enr1 = enroll(sess["id"], e1["id"])
        assert enr1["state"] == "RESERVED"
        resp = api.create_enrollment(
            {"session_id": sess["id"], "employee_id": e2["id"]}, TRAINER
        )
        validate_error(resp, ApiErrorId.ERR_INVARIANT_VIOLATION)
        sess_row = get_success_data(api.get_training_session(sess["id"], TRAINER))
        assert sess_row["reserved_count"] == 1

    def test_capacity_full_fires_exactly_at_reserved_equals_capacity(self, api):
        """PRD §3.9: "Enrollment respects the session's capacity — enrolling
        beyond `capacity` violates `ERR_INVARIANT_VIOLATION`"

        Design: Difficulty/boundary_precision_check/session_enrollment_capacity_full_rejects
        """
        project = create_project()
        sess = create_session(project["id"], capacity=2)
        staff = [
            create_staff(project["id"], employee_code=f"E{i}", full_name=f"Teller {i}")
            for i in range(1, 4)
        ]
        enroll(sess["id"], staff[0]["id"])
        enroll(sess["id"], staff[1]["id"])
        resp = api.create_enrollment(
            {"session_id": sess["id"], "employee_id": staff[2]["id"]}, TRAINER
        )
        validate_error(resp, ApiErrorId.ERR_INVARIANT_VIOLATION)

    def test_duplicate_employee_enrollment_is_invariant_violation(self, api):
        """PRD §3.9: "the same staff member may not be enrolled twice in the
        same session, likewise an invariant violation."

        Design: Corner/validations/enrollment_duplicate_employee_returns_invariant_violation
        """
        project = create_project()
        sess = create_session(project["id"], capacity=5)
        e1 = create_staff(project["id"], employee_code="E1")
        enroll(sess["id"], e1["id"])
        resp = api.create_enrollment(
            {"session_id": sess["id"], "employee_id": e1["id"]}, TRAINER
        )
        validate_error(resp, ApiErrorId.ERR_INVARIANT_VIOLATION)


class TestEnrollmentShape:
    def test_enrollment_carries_only_id_and_created_at(self, api):
        """PRD §2.5: "**enrollments** and **cutover plan/task records** (the
        cutover plan and its tasks) carry only `id` and `created_at`; both
        `updated_at` and `version` are absent on those resources, and no
        endpoint targeting them participates in optimistic concurrency."

        Design: Corner/entities/enrollment_has_no_update_endpoint_and_no_version_field
        """
        project = create_project()
        sess = create_session(project["id"], capacity=3)
        e1 = create_staff(project["id"], employee_code="E1")
        enroll(sess["id"], e1["id"])
        rows, meta = validate_paginated(
            api.list_enrollments(TRAINER, params={"session_id": sess["id"]})
        )
        assert len(rows) == 1
        row = rows[0]
        assert row["id"]
        assert row["created_at"]
        assert "version" not in row
        assert "updated_at" not in row


class TestAttendSessionGate:
    def test_attend_requires_session_in_progress(self, api):
        """PRD §3.9: "While the session is in progress, the trainer marks each
        `RESERVED` enrollment as attended or no-show."

        Design: Difficulty/cross_entity_state_dependency/enrollment_attend_requires_session_in_progress
        """
        project = create_project()
        sess = create_session(project["id"], capacity=2)
        e1 = create_staff(project["id"], employee_code="E1")
        enr = enroll(sess["id"], e1["id"])
        set_clock("2026-09-02T09:30:00Z")
        resp = api.attend_enrollment(enr["id"], TRAINER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        get_success_data(api.start_training_session(sess["id"], TRAINER))
        attended = get_success_data(api.attend_enrollment(enr["id"], TRAINER))
        assert attended["state"] == "ATTENDED"

    def test_attend_after_start_moves_reserved_to_attended(self, api):
        """PRD §3.9: "Marking attended (`RESERVED → ATTENDED`) moves one from
        `reserved_count` to `attended_count`"

        Design: Difficulty/cross_entity_state_dependency/enrollment_attend_requires_session_in_progress
        """
        project = create_project()
        sess = create_session(project["id"], capacity=2)
        e1 = create_staff(project["id"], employee_code="E1")
        enr = enroll(sess["id"], e1["id"])
        set_clock("2026-09-02T10:00:00Z")
        get_success_data(api.start_training_session(sess["id"], TRAINER))
        get_success_data(api.attend_enrollment(enr["id"], TRAINER))
        sess_row = get_success_data(api.get_training_session(sess["id"], TRAINER))
        assert sess_row["reserved_count"] == 0
        assert sess_row["attended_count"] == 1


class TestSessionCancelCascade:
    def test_cancel_cascades_reserved_enrollments(self, api):
        """PRD §3.9: "Cancelling a session (`SCHEDULED → CANCELLED`) cascades
        every `RESERVED` enrollment to `CANCELLED` and recomputes
        `reserved_count`"

        Design: Corner/state_machines/session_cancel_cascades_reserved_enrollments
        """
        project = create_project()
        sess = create_session(project["id"], capacity=3)
        e1 = create_staff(project["id"], employee_code="E1", full_name="One")
        e2 = create_staff(project["id"], employee_code="E2", full_name="Two")
        enroll(sess["id"], e1["id"])
        enroll(sess["id"], e2["id"])
        cancelled = get_success_data(api.cancel_training_session(sess["id"], TRAINER))
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["reserved_count"] == 0
        rows, _meta = validate_paginated(
            api.list_enrollments(TRAINER, params={"session_id": sess["id"]})
        )
        assert sorted(r["state"] for r in rows) == ["CANCELLED", "CANCELLED"]


class TestCertification:
    def test_certification_fires_at_session_completion_not_attend(self, api):
        """PRD §3.9: "it then recomputes both counts from the enrollments and
        fires the certification cascade: every staff member holding at least
        one `ATTENDED` enrollment in that session has `parallel_ops_certified`
        set true. Certification is granted at session completion, never at
        attend time."

        Design: Corner/state_machines/enrollment_attend_then_session_complete_certifies_staff
        """
        project = create_project()
        sess = create_session(project["id"], capacity=2)
        e1 = create_staff(project["id"], employee_code="E1")
        enr = enroll(sess["id"], e1["id"])
        set_clock("2026-09-02T10:00:00Z")
        get_success_data(api.start_training_session(sess["id"], TRAINER))
        get_success_data(api.attend_enrollment(enr["id"], TRAINER))
        mid = get_success_data(api.get_staff(e1["id"], TRAINER))
        assert mid["parallel_ops_certified"] is False
        set_clock("2026-09-02T12:00:00Z")
        get_success_data(api.complete_training_session(sess["id"], TRAINER))
        done = get_success_data(api.get_staff(e1["id"], TRAINER))
        assert done["parallel_ops_certified"] is True
