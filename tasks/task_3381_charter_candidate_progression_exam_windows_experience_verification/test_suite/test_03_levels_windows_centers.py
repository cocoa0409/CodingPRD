"""Exam levels, curriculum cycles, windows and test centers: uniqueness rules,
the annual supersede cascade, and role authorization on configuration
endpoints."""
from test_helpers import (
    ApiErrorId,
    create_appointment_payload,
    create_curriculum_cycle,
    create_curriculum_cycle_payload,
    create_exam_level,
    create_exam_window_payload,
    list_appointments,
    list_curriculum_cycles,
    list_exam_windows,
    set_logical_clock,
    setup_bookable_context,
    validate_error,
    validate_success,
)

CLOCK = "2027-01-05T00:00:00Z"


class TestLevelsWindowsCenters:
    def test_duplicate_exam_level_rejected(self, api, program_admin_headers):
        """PRD §3.2: "Each **exam level** carries a `level_code` of `LEVEL_I`,
        `LEVEL_II` or `LEVEL_III` — unique per program, with duplicates rejected
        as `ERR_DUPLICATE_EXAM_LEVEL`"

        Design: Corner/errors/c_duplicate_exam_level_rejected
        """
        set_logical_clock(CLOCK)
        create_exam_level()
        resp = api.create_exam_level(
            {
                "level_code": "LEVEL_I",
                "mps_scaled_score": 650,
                "max_attempts": 4,
                "early_fee_cents": 90000,
                "standard_fee_cents": 120000,
            },
            program_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_EXAM_LEVEL)
        assert resp.status_code == 409

    def test_curriculum_supersede_archives_prior_and_rejects_duplicate_year(
        self, api, program_admin_headers
    ):
        """PRD §3.2: "Publishing a **curriculum cycle** for a level records a
        `cycle_year` (unique within that level, else
        `ERR_DUPLICATE_CURRICULUM_YEAR`), an `effective_from` instant marking
        the inclusive start of the cycle's effectiveness, an `effective_to`
        instant marking the exclusive end — which must lie strictly after the
        start — and a `content_version` edition label."
        PRD §3.2: "When a cycle with a newer `cycle_year` is published for the
        same level, the previously published cycle of that level is
        automatically archived — `PUBLISHED` to `ARCHIVED` — and every
        enrollment's `curriculum_access_cycle_ids` is recomputed, dropping the
        archived cycle from all access lists."

        Design: Corner/cross_cutting_layers/c_curriculum_supersede_archives_prior_and_rejects_duplicate_year
        """
        set_logical_clock(CLOCK)
        level = create_exam_level()
        cycle_2027 = create_curriculum_cycle(level["id"])
        assert cycle_2027["status"] == "PUBLISHED"
        cycle_2028 = create_curriculum_cycle(
            level["id"],
            cycle_year=2028,
            effective_from="2028-01-01T00:00:00Z",
            effective_to="2029-01-01T00:00:00Z",
            content_version="L1-2028",
        )
        assert cycle_2028["status"] == "PUBLISHED"
        resp = api.create_curriculum_cycle(
            level["id"],
            create_curriculum_cycle_payload(
                cycle_year=2028,
                effective_from="2028-01-01T00:00:00Z",
                effective_to="2029-01-01T00:00:00Z",
                content_version="L1-2028-bis",
            ),
            program_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_CURRICULUM_YEAR)
        assert resp.status_code == 409
        rows = list_curriculum_cycles(params={"exam_level_id": level["id"]})
        assert len(rows) == 2
        by_year = {row["cycle_year"]: row for row in rows}
        assert by_year[2027]["status"] == "ARCHIVED"
        assert by_year[2028]["status"] == "PUBLISHED"

    def test_role_denied_before_payload_shape(self, api, proctor_headers):
        """PRD §2.6: "Every request passes through a fixed validation pipeline,
        and the **first** failing check wins — its error is the one returned,
        and later checks are never consulted for that request."
        PRD §2.1: "A request whose role is not listed among the roles authorized
        for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP
        403)."

        Design: Corner/validations/c_role_denied_before_payload_shape
        """
        set_logical_clock(CLOCK)
        create_exam_level()
        resp = api.create_exam_window({}, proctor_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        assert resp.status_code == 403

    def test_proctor_cannot_create_window(self, api, proctor_headers):
        """PRD §2.1: "A request whose role is not listed among the roles
        authorized for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE`
        (HTTP 403)."

        Design: Corner/rbac/c_proctor_cannot_create_window
        """
        set_logical_clock(CLOCK)
        level = create_exam_level()
        resp = api.create_exam_window(
            create_exam_window_payload(level["id"]), proctor_headers
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        assert resp.status_code == 403
        assert list_exam_windows(params={"exam_level_id": level["id"]}) == []

    def test_booking_into_cancelled_window_rejected(self, api, program_admin_headers):
        """PRD §3.3: "The enrollment must be `ENROLLED`
        (`ERR_ENROLLMENT_NOT_ENROLLED`); the window must be `OPEN`
        (`ERR_WINDOW_NOT_OPEN`); the logical clock must be no later than the
        window's `scheduling_deadline_at` (`ERR_WINDOW_SCHEDULING_CLOSED`)."

        Design: Corner/errors/c_booking_into_cancelled_window_rejected
        """
        context = setup_bookable_context()
        resp = api.cancel_exam_window(context["window"]["id"], program_admin_headers)
        validate_success(resp, 200)
        book = api.create_appointment(
            create_appointment_payload(
                context["enrollment"]["id"],
                context["window"]["id"],
                context["center"]["id"],
            ),
            context["candidate_headers"],
        )
        validate_error(book, ApiErrorId.ERR_WINDOW_NOT_OPEN)
        assert book.status_code == 409
        assert list_appointments(params={"exam_window_id": context["window"]["id"]}) == []
