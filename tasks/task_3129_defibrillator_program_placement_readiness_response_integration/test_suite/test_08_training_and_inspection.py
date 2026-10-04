"""Training and inspection temporal rules: capacity boundary, certification
max-accumulation across abutting sessions, and the inspection window's
closed upper bound.

Design: Difficulty/boundary_precision_check/training_session_capacity_zero_remaining_boundary,
        Difficulty/resource_temporal_overlap/training_session_no_overlap_with_completed_session_certification_window,
        Difficulty/resource_temporal_overlap/inspection_window_hard_close_at_plus_seven_days,
        Difficulty/priority_pair_validation_conflict/business_temporal_vs_business_referential_inspection_window,
        Corner/calculations/certification_extension_handles_null_certified_through.
"""

from test_helpers import (
    ApiErrorId,
    create_campus,
    create_device,
    create_device_model,
    create_inspection_payload,
    create_responder,
    create_training_session_payload,
    get_success_data,
    make_inspector_headers,
    set_clock,
    setup_campus_zone_cabinet_device,
    validate_error,
    validate_error_is_one_of,
    validate_success,
    TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
PM = TEST_USERS["program_manager_headers"]


def _make_session(api, campus_id, instructor_id, starts_at, ends_at,
                  capacity=5, months=24):
    return get_success_data(
        api.create_training_session(
            create_training_session_payload(
                campus_id, instructor_id,
                starts_at=starts_at, ends_at=ends_at,
                capacity=capacity, certification_months_granted=months,
            ),
            PM,
        )
    )


class TestTrainingCapacityBoundary:

    def test_enroll_up_to_capacity_then_full(self, api):
        """PRD: "Enrollment is only possible before the session starts — an
        attempt at or after `starts_at` is rejected with
        `ERR_SESSION_ALREADY_STARTED` — and only while seats remain; enrolling
        beyond the session's `capacity` is rejected with `ERR_TRAINING_FULL`."

        Design: Difficulty/boundary_precision_check/training_session_capacity_zero_remaining_boundary
        """
        set_clock("2026-09-01T00:00:00Z")
        campus = create_campus()
        md = create_responder(campus["id"], responder_role="MEDICAL_DIRECTOR",
                              full_name="MD", badge_number="MD-12")
        r1 = create_responder(campus["id"], full_name="R1", badge_number="R-12a")
        r2 = create_responder(campus["id"], full_name="R2", badge_number="R-12b")
        session = _make_session(api, campus["id"], md["id"],
                                starts_at="2026-10-01T00:00:00Z",
                                ends_at="2026-10-01T04:00:00Z",
                                capacity=1)

        # Enroll to exactly capacity: 0 < 1, succeeds.
        validate_success(
            api.enroll_training_session(session["id"],
                                        {"responder_id": r1["id"]}, PM)
        )
        # Next enroll exceeds capacity.
        res = api.enroll_training_session(session["id"],
                                          {"responder_id": r2["id"]}, PM)
        validate_error(res, ApiErrorId.ERR_TRAINING_FULL, expected_status=409)

    def test_capacity_two_allows_exactly_two_enrollments(self, api):
        """PRD: "only while seats remain; enrolling beyond the session's
        `capacity` is rejected with `ERR_TRAINING_FULL`."

        Design: Difficulty/boundary_precision_check/training_session_capacity_zero_remaining_boundary
        """
        set_clock("2026-09-01T00:00:00Z")
        campus = create_campus()
        md = create_responder(campus["id"], responder_role="MEDICAL_DIRECTOR",
                              full_name="MD", badge_number="MD-12B")
        responders = [
            create_responder(campus["id"], full_name=f"R{i}",
                             badge_number=f"R-12B-{i}")
            for i in range(3)
        ]
        session = _make_session(api, campus["id"], md["id"],
                                starts_at="2026-10-01T00:00:00Z",
                                ends_at="2026-10-01T04:00:00Z",
                                capacity=2)
        validate_success(api.enroll_training_session(
            session["id"], {"responder_id": responders[0]["id"]}, PM))
        validate_success(api.enroll_training_session(
            session["id"], {"responder_id": responders[1]["id"]}, PM))
        res = api.enroll_training_session(
            session["id"], {"responder_id": responders[2]["id"]}, PM)
        validate_error(res, ApiErrorId.ERR_TRAINING_FULL, expected_status=409)


class TestCertificationMaxAccumulation:

    def test_abutting_sessions_do_not_double_count(self, api):
        """PRD: "the base is the later of the responder's current
        `certified_through` and the session's `ends_at` — or simply the
        session's `ends_at` when the responder has never been certified and
        `certified_through` is null — and the new `certified_through` is that
        base advanced by the session's `certification_months_granted` calendar
        months".

        Design: Difficulty/resource_temporal_overlap/training_session_no_overlap_with_completed_session_certification_window
        """
        set_clock("2026-07-15T00:00:00Z")
        campus = create_campus()
        md = create_responder(campus["id"], responder_role="MEDICAL_DIRECTOR",
                              full_name="MD", badge_number="MD-16")
        responder = create_responder(campus["id"], full_name="R",
                                     badge_number="R-16")

        s1 = _make_session(api, campus["id"], md["id"],
                           starts_at="2026-08-01T00:00:00Z",
                           ends_at="2026-08-01T04:00:00Z", months=24)
        # S2 abuts S1: S2.starts_at == S1.ends_at.
        s2 = _make_session(api, campus["id"], md["id"],
                           starts_at="2026-08-01T04:00:00Z",
                           ends_at="2026-08-01T08:00:00Z", months=12)
        api.enroll_training_session(s1["id"], {"responder_id": responder["id"]}, PM)
        api.enroll_training_session(s2["id"], {"responder_id": responder["id"]}, PM)

        set_clock("2026-08-01T05:00:00Z")
        validate_success(
            api.complete_training_session(s1["id"],
                                          {"attendee_ids": [responder["id"]]}, PM)
        )
        after_s1 = get_success_data(api.get_responder(responder["id"], PM))
        # base = max(null, 2026-08-01T04) -> +24mo = 2028-08-01T04:00:00Z.
        assert after_s1["certified_through"] == "2028-08-01T04:00:00Z"

        set_clock("2026-08-01T09:00:00Z")
        validate_success(
            api.complete_training_session(s2["id"],
                                          {"attendee_ids": [responder["id"]]}, PM)
        )
        after_s2 = get_success_data(api.get_responder(responder["id"], PM))
        # base = max(2028-08-01T04, 2026-08-01T08) = 2028-08-01T04 -> +12mo.
        assert after_s2["certified_through"] == "2029-08-01T04:00:00Z"

    def test_second_session_uses_max_not_its_own_ends_at(self, api):
        """PRD: "the base is the later of the responder's current
        `certified_through` and the session's `ends_at`".

        Design: Difficulty/resource_temporal_overlap/training_session_no_overlap_with_completed_session_certification_window
        """
        set_clock("2026-07-15T00:00:00Z")
        campus = create_campus()
        md = create_responder(campus["id"], responder_role="MEDICAL_DIRECTOR",
                              full_name="MD", badge_number="MD-16B")
        responder = create_responder(campus["id"], full_name="R",
                                     badge_number="R-16B")

        s1 = _make_session(api, campus["id"], md["id"],
                           starts_at="2026-08-01T00:00:00Z",
                           ends_at="2026-08-01T04:00:00Z", months=24)
        # S2 ends EARLIER in calendar time than S1's certification horizon:
        # ends_at 2026-08-10, but S1 already certified through 2028-08-01.
        s2 = _make_session(api, campus["id"], md["id"],
                           starts_at="2026-08-09T00:00:00Z",
                           ends_at="2026-08-10T00:00:00Z", months=6)
        api.enroll_training_session(s1["id"], {"responder_id": responder["id"]}, PM)
        api.enroll_training_session(s2["id"], {"responder_id": responder["id"]}, PM)

        set_clock("2026-08-02T00:00:00Z")
        validate_success(
            api.complete_training_session(s1["id"],
                                          {"attendee_ids": [responder["id"]]}, PM)
        )
        set_clock("2026-08-11T00:00:00Z")
        validate_success(
            api.complete_training_session(s2["id"],
                                          {"attendee_ids": [responder["id"]]}, PM)
        )
        after = get_success_data(api.get_responder(responder["id"], PM))
        # max(2028-08-01T04, 2026-08-10) = 2028-08-01T04 -> +6mo = 2029-02-01T04.
        assert after["certified_through"] == "2029-02-01T04:00:00Z"


class TestCertificationNullBase:

    def test_never_certified_responder_base_is_session_ends_at(self, api):
        """PRD: "or simply the session's `ends_at` when the responder has never
        been certified and `certified_through` is null — and the new
        `certified_through` is that base advanced by the session's
        `certification_months_granted` calendar months".

        Design: Corner/calculations/certification_extension_handles_null_certified_through
        """
        set_clock("2026-07-01T00:00:00Z")
        campus = create_campus()
        md = create_responder(campus["id"], responder_role="MEDICAL_DIRECTOR",
                              full_name="MD", badge_number="MD-CE")
        responder = create_responder(campus["id"], full_name="R",
                                     badge_number="R-CE")
        assert responder["certified_through"] is None

        session = _make_session(api, campus["id"], md["id"],
                                starts_at="2026-08-15T09:00:00Z",
                                ends_at="2026-08-15T13:00:00Z", months=12)
        api.enroll_training_session(session["id"],
                                    {"responder_id": responder["id"]}, PM)
        set_clock("2026-08-15T14:00:00Z")
        validate_success(
            api.complete_training_session(session["id"],
                                          {"attendee_ids": [responder["id"]]}, PM)
        )
        after = get_success_data(api.get_responder(responder["id"], PM))
        # base = 2026-08-15T13:00:00Z -> +12mo = 2027-08-15T13:00:00Z.
        assert after["certified_through"] == "2027-08-15T13:00:00Z"


class TestInspectionWindowBoundary:

    def test_submit_at_exactly_plus_seven_days_succeeds(self, api):
        """PRD: "no later than seven days after `scheduled_for`; the
        submission's `completed_at` must fall within that closed window, and a
        submission attempted after it is rejected with
        `ERR_INSPECTION_OVERDUE`."

        Design: Difficulty/resource_temporal_overlap/inspection_window_hard_close_at_plus_seven_days
        """
        _, _, _, device, _ = setup_campus_zone_cabinet_device(
            serial_number="SN-015"
        )
        inspector = create_responder(
            device["campus_id"], responder_role="INSPECTOR",
            full_name="Insp", badge_number="IN-15",
        )
        headers = make_inspector_headers(inspector["id"])
        insp = get_success_data(
            api.create_inspection(
                create_inspection_payload(device["id"], inspector["id"],
                                          scheduled_for="2026-09-01T00:00:00Z"),
                headers,
            )
        )
        set_clock("2026-09-08T00:00:00Z")
        submitted = validate_success(
            api.submit_inspection(
                insp["id"],
                {"checklist_items": [{"item_code": "PADS_OK",
                                      "result": "PASS"}]},
                headers,
            )
        )
        assert submitted["outcome"] == "PASS"

    def test_submit_after_plus_seven_days_rejected(self, api):
        """PRD: "no later than seven days after `scheduled_for`; the
        submission's `completed_at` must fall within that closed window, and a
        submission attempted after it is rejected with
        `ERR_INSPECTION_OVERDUE`."

        Design: Difficulty/resource_temporal_overlap/inspection_window_hard_close_at_plus_seven_days
        """
        _, _, _, device, _ = setup_campus_zone_cabinet_device(
            serial_number="SN-015B"
        )
        inspector = create_responder(
            device["campus_id"], responder_role="INSPECTOR",
            full_name="Insp", badge_number="IN-15B",
        )
        headers = make_inspector_headers(inspector["id"])
        insp = get_success_data(
            api.create_inspection(
                create_inspection_payload(device["id"], inspector["id"],
                                          scheduled_for="2026-09-01T00:00:01Z"),
                headers,
            )
        )
        # 2026-09-08T00:00:02Z is one second past scheduled_for + 7 days.
        set_clock("2026-09-08T00:00:02Z")
        res = api.submit_inspection(
            insp["id"],
            {"checklist_items": [{"item_code": "PADS_OK", "result": "PASS"}]},
            headers,
        )
        # PRD names ERR_INSPECTION_OVERDUE for this rejection; the catalogue
        # also carries ERR_TEMPORAL_WINDOW_VIOLATION for window violations.
        validate_error_is_one_of(
            res,
            [ApiErrorId.ERR_INSPECTION_OVERDUE,
             ApiErrorId.ERR_TEMPORAL_WINDOW_VIOLATION],
        )
        assert res.status_code in (409, 422)


class TestInspectionTemporalVsReferential:

    def test_late_submit_by_other_campus_inspector_reports_temporal_error(self, api):
        """PRD: "When a single request could fail several rules, the failure
        reported is determined by a fixed evaluation order. ... then responder
        certification (`ERR_RESPONDER_NOT_CERTIFIED`), then temporal windows
        (`ERR_TEMPORAL_WINDOW_VIOLATION`), then cross-reference compatibility
        (`ERR_INCOMPATIBLE_REFERENCE`)". PRD: "a submission attempted after it
        is rejected with `ERR_INSPECTION_OVERDUE`."

        Design: Difficulty/priority_pair_validation_conflict/business_temporal_vs_business_referential_inspection_window
        """
        set_clock("2026-09-01T00:00:00Z")
        model = create_device_model()
        campus_a = create_campus(name="C-A")
        campus_b = create_campus(name="C-B")
        device = create_device(campus_a["id"], model["id"],
                               serial_number="SN-010")
        inspector_b = create_responder(
            campus_b["id"], responder_role="INSPECTOR",
            full_name="Insp B", badge_number="IN-B",
        )
        headers_b = make_inspector_headers(inspector_b["id"])
        insp = get_success_data(
            api.create_inspection(
                create_inspection_payload(device["id"], inspector_b["id"],
                                          scheduled_for="2026-09-01T00:00:00Z"),
                headers_b,
            )
        )
        # Submit eight days later: past the seven-day closed window.
        set_clock("2026-09-09T00:00:00Z")
        res = api.submit_inspection(
            insp["id"],
            {"checklist_items": [{"item_code": "PADS_OK", "result": "PASS"}]},
            headers_b,
        )
        # The temporal rule outranks cross-reference compatibility in the
        # fixed evaluation order. PRD names ERR_INSPECTION_OVERDUE for a late
        # submission and orders ERR_TEMPORAL_WINDOW_VIOLATION before
        # ERR_INCOMPATIBLE_REFERENCE; accept either window error, never the
        # referential one.
        actual = validate_error_is_one_of(
            res,
            [ApiErrorId.ERR_INSPECTION_OVERDUE,
             ApiErrorId.ERR_TEMPORAL_WINDOW_VIOLATION],
        )
        assert actual != ApiErrorId.ERR_INCOMPATIBLE_REFERENCE

    def test_in_window_submit_by_other_campus_inspector_is_not_temporal_error(self, api):
        """PRD: "Submission is only valid once the window has opened —
        `scheduled_for` must be at or before the current time — and no later
        than seven days after `scheduled_for`". A submission inside the window
        must not be rejected on temporal grounds.

        Design: Difficulty/priority_pair_validation_conflict/business_temporal_vs_business_referential_inspection_window
        """
        set_clock("2026-09-01T00:00:00Z")
        model = create_device_model()
        campus_a = create_campus(name="C-A2")
        campus_b = create_campus(name="C-B2")
        device = create_device(campus_a["id"], model["id"],
                               serial_number="SN-010B")
        inspector_b = create_responder(
            campus_b["id"], responder_role="INSPECTOR",
            full_name="Insp B", badge_number="IN-B2",
        )
        headers_b = make_inspector_headers(inspector_b["id"])
        insp = get_success_data(
            api.create_inspection(
                create_inspection_payload(device["id"], inspector_b["id"],
                                          scheduled_for="2026-09-01T00:00:00Z"),
                headers_b,
            )
        )
        set_clock("2026-09-02T00:00:00Z")
        res = api.submit_inspection(
            insp["id"],
            {"checklist_items": [{"item_code": "PADS_OK", "result": "PASS"}]},
            headers_b,
        )
        # Inside the window: never a temporal rejection, regardless of whether
        # the server additionally enforces campus scoping on the inspector.
        if res.status_code >= 400:
            body = res.json()
            assert body["data"]["error_id"] not in (
                "ERR_INSPECTION_OVERDUE",
                "ERR_TEMPORAL_WINDOW_VIOLATION",
            ), f"In-window submission must not fail on temporal grounds: {body}"
