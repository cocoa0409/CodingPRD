"""Corner coverage: calculation boundaries — equipment ceil tiers and the
90-day renewal window."""
from test_helpers import (
    ADMIN,
    COORD,
    TC,
    ApiErrorId,
    create_course_session_payload,
    get_success_data,
    setup_renewal_ready_instructor,
    setup_teaching_scenario,
    validate_error,
    validate_success,
)


class TestEquipmentManikinCeilBoundary:
    def test_equipment_manikin_ceil_boundary(self, api):
        """PRD §3.5: "For a `CLASSROOM` session the required number of manikins
        is the session's `capacity` divided by 3, rounded up."
        PRD §3.5: "failure of any one rejects the create with
        `ERR_EQUIPMENT_RATIO_VIOLATION`."

        Design: Corner/calculations/equipment_manikin_ceil_boundary
        """
        ctx = setup_teaching_scenario()

        # ceil(3/3) == 1 manikin suffices at capacity 3.
        s3 = validate_success(
            api.create_course_session(
                create_course_session_payload(
                    ctx["center"]["id"], ctx["site"]["id"], ctx["lead"]["id"],
                    ctx["guidelines_version"]["id"],
                    capacity=3, manikin_count=1, aed_trainer_count=1,
                    start_at="2026-10-10T14:00:00Z",
                    end_at="2026-10-10T16:00:00Z"), COORD),
            expected_status=201)
        assert s3["capacity"] == 3

        # ceil(4/3) == 2 required; 1 manikin -> 422.
        resp = api.create_course_session(
            create_course_session_payload(
                ctx["center"]["id"], ctx["site"]["id"], ctx["lead"]["id"],
                ctx["guidelines_version"]["id"],
                capacity=4, manikin_count=1, aed_trainer_count=1,
                start_at="2026-10-11T14:00:00Z",
                end_at="2026-10-11T16:00:00Z"), COORD)
        validate_error(resp, ApiErrorId.ERR_EQUIPMENT_RATIO_VIOLATION)

        # 2 manikins at capacity 4 -> 201.
        s4 = validate_success(
            api.create_course_session(
                create_course_session_payload(
                    ctx["center"]["id"], ctx["site"]["id"], ctx["lead"]["id"],
                    ctx["guidelines_version"]["id"],
                    capacity=4, manikin_count=2, aed_trainer_count=1,
                    start_at="2026-10-11T14:00:00Z",
                    end_at="2026-10-11T16:00:00Z"), COORD),
            expected_status=201)
        assert s4["capacity"] == 4


class TestRenewalEarlyWindowBoundary:
    def test_renewal_early_window_boundary(self, api):
        """PRD §3.3: "The renewal window must be open: the current clock must
        be on or after ninety days before `renewal_due_at`, and on or before
        `renewal_due_at` itself. Both boundaries are inclusive — a renewal
        submitted at the exact `renewal_due_at` instant still succeeds, and a
        renewal submitted ninety days before the due instant also succeeds.
        Outside that window the renewal is rejected with
        `ERR_RENEWAL_WINDOW_CLOSED`."
        PRD §3.3: "Renewal extends `renewal_due_at` by a further twenty-four
        months from the current clock and increments `renewal_count` by 1."

        Design: Corner/calculations/renewal_early_window_boundary
        """
        # Legacy-certified at 2026-09-01 -> renewal_due_at 2028-09-01T00:00:00Z.
        ctx = setup_renewal_ready_instructor(num_completed_sessions=2)
        lead_id = ctx["lead"]["id"]

        # Clock 2028-06-02: 91 days before the due instant -> window closed.
        get_success_data(api.set_clock("2028-06-02T00:00:00Z", ADMIN))
        resp = api.renew_instructor(lead_id, TC)
        validate_error(resp, ApiErrorId.ERR_RENEWAL_WINDOW_CLOSED)

        # Clock 2028-06-03: exactly 90 days before due -> inclusive, succeeds.
        get_success_data(api.set_clock("2028-06-03T00:00:00Z", ADMIN))
        renewed = validate_success(api.renew_instructor(lead_id, TC))
        assert renewed["renewal_due_at"] == "2030-06-03T00:00:00Z"
        assert renewed["renewal_count"] == 1
