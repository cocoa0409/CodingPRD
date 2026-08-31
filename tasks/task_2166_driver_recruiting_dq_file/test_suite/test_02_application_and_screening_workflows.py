"""Submission, the revision loop, third-party reports and the consent chain."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_dq_document,
    assert_dq_file,
    assert_screening_check,
    create_applicant,
    create_carrier,
    create_application,
    create_open_session,
    complete_negative_drug_test,
    fetch_dq_file,
    make_applicant_headers,
    make_recruiter_headers,
    make_safety_director_headers,
    open_clearinghouse_query,
    order_screening_check,
    pass_road_test,
    record_employment_segment,
    record_screening_check_result,
    reserve_seat,
    set_clock,
    setup_submitted_application,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

RECRUITER = TEST_USERS["recruiter_headers"]
DER = TEST_USERS["der_headers"]
SAFETY_DIRECTOR = TEST_USERS["safety_director_headers"]


def test_submission_mints_the_file_and_its_twelve_documents(api):
    """PRD §3.2: "On success the axis moves `DRAFT → SUBMITTED`, `submitted_at` is stamped
    with the current logical-clock instant, `recruiter_user_id` is set to the calling
    `X-User-ID` — the anchor for every segregation-of-duties check that follows — and the
    second axis moves `NOT_STARTED → IN_PROGRESS`."
    PRD §3.2: "Submission is also the sole producer of the qualification file and its
    documents: it creates the one-to-one file in `OPEN` status with `review_state` at
    `NOT_DUE`, `opened_on` set to the current logical-clock calendar date and `total_weight`
    at 33, then seeds twelve document rows, one per artifact type, all in `MISSING` status."
    PRD §3.2: "It immediately sets the `APPLICATION_FORM` document to `PRESENT` with
    `effective_on` at the current logical-clock date, then recomputes the file's
    `completeness_pct` and `deficiency_count`, recomputes `next_review_due_on` and
    `review_state`, and recomputes the application's `verified_coverage_days` and
    `gap_days_unexplained`."
    PRD §2.5: "On startup the clock reads exactly `2026-08-01T00:00:00Z`, and until it is
    explicitly moved the service must report that instant and must never fall back to the
    host machine's real time."

    Design: Corner/state_machines/submit_creates_dq_file_and_twelve_seeded_documents
    """
    carrier = create_carrier(dot_number="DOT-CORNER-1")
    applicant = create_applicant(carrier["id"])
    application = create_application(applicant["id"])

    submitted = validate_success(
        api.submit_application(application["id"], make_recruiter_headers("rec-001"))
    )

    assert submitted["screening_status"] == "SUBMITTED"
    assert submitted["qualification_status"] == "IN_PROGRESS"
    assert submitted["recruiter_user_id"] == "rec-001"
    assert submitted["submitted_at"] == "2026-08-01T00:00:00.000Z"

    files, meta = validate_paginated(
        api.list_dq_files(RECRUITER, params={"application_id": application["id"]})
    )
    assert meta["total_count"] == 1, "submission mints exactly one qualification file"
    dq_file = files[0]
    assert_dq_file(dq_file)
    assert dq_file["status"] == "OPEN"
    assert dq_file["review_state"] == "NOT_DUE"
    assert dq_file["total_weight"] == 33
    assert dq_file["opened_on"] == "2026-08-01"
    assert dq_file["next_review_due_on"] == "2027-08-01"
    assert dq_file["last_annual_review_at"] is None

    documents, doc_meta = validate_paginated(
        api.list_dq_documents(RECRUITER, params={"dq_file_id": dq_file["id"], "limit": 100})
    )
    assert doc_meta["total_count"] == 12, "twelve document rows, one per artifact type"
    present = [d for d in documents if d["status"] == "PRESENT"]
    assert len(present) == 1 and present[0]["doc_type"] == "APPLICATION_FORM"
    for document in documents:
        assert_dq_document(document)

    assert float(dq_file["completeness_pct"]) == 10.71
    assert dq_file["deficiency_count"] == 9


def test_submitting_an_already_submitted_application_is_refused(api):
    """PRD §3.2: "It is accepted only while `screening_status` is `DRAFT`, only while the
    owning carrier's `posture` is `OPEN` or `RESTRICTED` — a `FROZEN` office is refused with
    `ERR_CARRIER_POSTURE_BLOCKED` — and only while the applicant's `rehire_eligibility`
    reads `ELIGIBLE`, otherwise `ERR_REHIRE_INELIGIBLE`."
    PRD §2.9: "Then the generic state ladder: the target row must be in a declared origin
    state for the requested transition (`ERR_INVALID_STATE`, 409), and must not already sit
    in one of its terminal states (`ERR_ALREADY_TERMINAL`, 409)."

    Design: Corner/state_machines/submit_twice_returns_409_invalid_state
    """
    ctx = setup_submitted_application(
        carrier_overrides={"dot_number": "DOT-CORNER-1"}, recruiter_user_id="rec-001"
    )

    response = api.submit_application(
        ctx["application_id"], make_recruiter_headers("rec-002")
    )

    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)
    application = validate_success(
        api.get_driver_application(ctx["application_id"], RECRUITER)
    )
    assert application["recruiter_user_id"] == "rec-001", (
        "the rejected call must not overwrite the segregation-of-duties anchor"
    )
    _, meta = validate_paginated(
        api.list_dq_files(RECRUITER, params={"application_id": ctx["application_id"]})
    )
    assert meta["total_count"] == 1, "no second qualification file may be minted"


def test_first_screening_order_opens_in_ordered_and_advances_the_screening_axis(api):
    """PRD §3.4: "Orders open in `ORDERED`, and the very first order placed against a
    `SUBMITTED` application advances that application's `screening_status` from `SUBMITTED`
    to `SCREENING` as a system side effect."
    PRD §4: "Endpoints that mint a brand-new resource answer with HTTP 201; every other
    successful call — reads, state transitions, action endpoints and updates alike —
    answers with HTTP 200."

    Design: Corner/state_machines/screening_check_starts_in_ordered_state
    """
    ctx = setup_submitted_application(carrier_overrides={"dot_number": "DOT-CORNER-1"})

    response = api.create_screening_check(
        {"application_id": ctx["application_id"], "check_type": "PSP"}, RECRUITER
    )
    check = validate_success(response, 201)

    assert_screening_check(check)
    assert check["status"] == "ORDERED"

    application = validate_success(
        api.get_driver_application(ctx["application_id"], RECRUITER)
    )
    assert application["screening_status"] == "SCREENING"
    assert application["qualification_status"] == "IN_PROGRESS"


def test_adverse_final_inside_the_dispute_window_is_refused(api):
    """PRD §3.4: "Once the window has elapsed — the logical clock having reached or passed
    `pre_adverse_at` advanced by 5 days — the `SafetyDirector` may finalise with an
    `ADVERSE_FINAL` decision, moving the row `PRE_ADVERSE → ADVERSE_FINAL` and cascading the
    parent application's `screening_status` to `SCREEN_FAILED` with the reason token
    `ADVERSE_SCREENING`, which sets `qualification_status` to `DISQUALIFIED`, which archives
    the qualification file and cancels every reserved orientation enrollment of that
    application."
    PRD §2.9: "Then the generic state ladder: the target row must be in a declared origin
    state for the requested transition (`ERR_INVALID_STATE`, 409), and must not already sit
    in one of its terminal states (`ERR_ALREADY_TERMINAL`, 409)."

    Design: Corner/state_machines/adverse_final_inside_dispute_window_returns_409_invalid_state
    """
    ctx = setup_submitted_application(carrier_overrides={"dot_number": "DOT-CORNER-1"})
    check = order_screening_check(ctx["application_id"], "CRIMINAL")
    record_screening_check_result(
        check["id"], issued_on="2026-07-01", serious_violation_count=3
    )
    validate_success(
        api.adjudicate_screening_check(check["id"], {"decision": "PRE_ADVERSE"}, SAFETY_DIRECTOR)
    )
    set_clock("2026-08-05T23:59:00Z")

    response = api.adjudicate_screening_check(
        check["id"], {"decision": "ADVERSE_FINAL"}, SAFETY_DIRECTOR
    )

    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)
    assert validate_success(api.get_screening_check(check["id"], RECRUITER))["status"] == "PRE_ADVERSE"
    application = validate_success(
        api.get_driver_application(ctx["application_id"], RECRUITER)
    )
    assert application["screening_status"] == "SCREENING"


def test_adjudicating_a_finalised_adverse_check_is_refused_and_the_cascade_stands(api):
    """PRD §3.4: "Once the window has elapsed — the logical clock having reached or passed
    `pre_adverse_at` advanced by 5 days — the `SafetyDirector` may finalise with an
    `ADVERSE_FINAL` decision, moving the row `PRE_ADVERSE → ADVERSE_FINAL` and cascading the
    parent application's `screening_status` to `SCREEN_FAILED` with the reason token
    `ADVERSE_SCREENING`, which sets `qualification_status` to `DISQUALIFIED`, which archives
    the qualification file and cancels every reserved orientation enrollment of that
    application."
    PRD §2.9: "Then the generic state ladder: the target row must be in a declared origin
    state for the requested transition (`ERR_INVALID_STATE`, 409), and must not already sit
    in one of its terminal states (`ERR_ALREADY_TERMINAL`, 409)."

    Design: Corner/state_machines/adjudicate_on_adverse_final_returns_409_already_terminal
    """
    ctx = setup_submitted_application(carrier_overrides={"dot_number": "DOT-CORNER-1"})
    check = order_screening_check(ctx["application_id"], "CRIMINAL")
    record_screening_check_result(
        check["id"], issued_on="2026-07-01", serious_violation_count=3
    )
    validate_success(
        api.adjudicate_screening_check(check["id"], {"decision": "PRE_ADVERSE"}, SAFETY_DIRECTOR)
    )
    set_clock("2026-08-06T00:00:00Z")
    validate_success(
        api.adjudicate_screening_check(
            check["id"], {"decision": "ADVERSE_FINAL"}, SAFETY_DIRECTOR
        )
    )

    response = api.adjudicate_screening_check(
        check["id"], {"decision": "PASS"}, SAFETY_DIRECTOR
    )

    validate_error_is_one_of(
        response,
        [ApiErrorId.ERR_ALREADY_TERMINAL.value, ApiErrorId.ERR_INVALID_STATE.value],
    )
    assert response.status_code == 409
    assert validate_success(api.get_screening_check(check["id"], RECRUITER))["status"] == "ADVERSE_FINAL"

    application = validate_success(
        api.get_driver_application(ctx["application_id"], RECRUITER)
    )
    assert application["screening_status"] == "SCREEN_FAILED"
    assert application["qualification_status"] == "DISQUALIFIED"
    assert application["disqualifying_reason"] == "ADVERSE_SCREENING"
    assert fetch_dq_file(ctx["dq_file_id"])["status"] == "ARCHIVED"


def test_dispute_reopens_the_report_cycle_back_to_received(api):
    """PRD §3.4: "Inside that window — while the logical clock is strictly earlier than
    `pre_adverse_at` advanced by 5 days — the `Applicant` themselves, and only the applicant
    behind that check, may dispute it by supplying a `dispute_note`; the row moves
    `PRE_ADVERSE → DISPUTED` and `pre_adverse_at` is cleared back to null, reopening the
    cycle `RECEIVED → PRE_ADVERSE → DISPUTED → RECEIVED` for a corrected report."
    PRD §3.4: "It is accepted from `ORDERED` and, identically, from `DISPUTED` — a corrected
    report simply overwrites the earlier figures — and in both cases the row lands in
    `RECEIVED`."
    PRD §3.4: "For a `PSP` or `CRIMINAL` report the adjudication score is that raw sum
    rounded half up to two decimal places and nothing more — no experience credit, no
    multiplier — and it is informational only, never blocking a pass."

    Design: Corner/state_machines/screening_dispute_cycle_returns_check_to_received
    """
    ctx = setup_submitted_application(carrier_overrides={"dot_number": "DOT-CORNER-1"})
    check = order_screening_check(ctx["application_id"], "CRIMINAL")
    record_screening_check_result(
        check["id"], issued_on="2026-07-01", serious_violation_count=3
    )
    validate_success(
        api.adjudicate_screening_check(check["id"], {"decision": "PRE_ADVERSE"}, SAFETY_DIRECTOR)
    )

    disputed = validate_success(
        api.dispute_screening_check(
            check["id"],
            {"dispute_note": "records belong to another driver"},
            make_applicant_headers(ctx["applicant_id"]),
        )
    )
    assert disputed["status"] == "DISPUTED"
    assert disputed["pre_adverse_at"] is None

    corrected = validate_success(
        api.record_screening_result(
            check["id"],
            {
                "issued_on": "2026-07-20",
                "violation_points": 0,
                "serious_violation_count": 0,
                "crash_preventable_count": 0,
            },
            RECRUITER,
        )
    )
    assert corrected["status"] == "RECEIVED"
    assert corrected["issued_on"] == "2026-07-20"
    assert corrected["serious_violation_count"] == 0
    assert float(corrected["adjudication_score"]) == 0.00

    passed = validate_success(
        api.adjudicate_screening_check(check["id"], {"decision": "PASS"}, SAFETY_DIRECTOR)
    )
    assert passed["status"] == "ADJUDICATED_PASS"
    application = validate_success(
        api.get_driver_application(ctx["application_id"], RECRUITER)
    )
    assert application["screening_status"] == "SCREENING", (
        "one passed check does not clear the screening axis on its own"
    )


def test_resubmitting_information_outside_the_revision_loop_is_refused(api):
    """PRD §3.2: "The `Recruiter` closes the round by supplying a `response_note`, moving
    the axis `INFO_REQUESTED → SCREENING` and incrementing `revision_round` by one."
    PRD §2.9: "Then the generic state ladder: the target row must be in a declared origin
    state for the requested transition (`ERR_INVALID_STATE`, 409), and must not already sit
    in one of its terminal states (`ERR_ALREADY_TERMINAL`, 409)."

    Design: Corner/state_machines/resubmit_info_from_screening_returns_409_invalid_state
    """
    ctx = setup_submitted_application(carrier_overrides={"dot_number": "DOT-CORNER-1"})
    order_screening_check(ctx["application_id"], "MVR")

    response = api.resubmit_info(
        ctx["application_id"], {"response_note": "here you go"}, RECRUITER
    )

    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)
    application = validate_success(
        api.get_driver_application(ctx["application_id"], RECRUITER)
    )
    assert application["screening_status"] == "SCREENING"
    assert application["revision_round"] == 0


def test_revision_round_closes_only_on_resubmission(api):
    """PRD §3.2: "A `SafetyDirector` may push a screening application back for more
    information by supplying a `reason`; the axis moves `SCREENING → INFO_REQUESTED` and
    nothing else on the record changes — `disqualifying_reason` stays null."
    PRD §3.2: "The `Recruiter` closes the round by supplying a `response_note`, moving the
    axis `INFO_REQUESTED → SCREENING` and incrementing `revision_round` by one."

    Design: Corner/state_machines/request_info_then_resubmit_increments_revision_round
    """
    ctx = setup_submitted_application(carrier_overrides={"dot_number": "DOT-CORNER-1"})
    order_screening_check(ctx["application_id"], "MVR")

    after_request = validate_success(
        api.request_info(ctx["application_id"], {"reason": "ADDRESS_GAP"}, SAFETY_DIRECTOR)
    )
    assert after_request["screening_status"] == "INFO_REQUESTED"
    assert after_request["revision_round"] == 0
    assert after_request["disqualifying_reason"] is None
    assert after_request["qualification_status"] == "IN_PROGRESS"

    after_resubmit = validate_success(
        api.resubmit_info(
            ctx["application_id"], {"response_note": "gap explained"}, RECRUITER
        )
    )
    assert after_resubmit["screening_status"] == "SCREENING"
    assert after_resubmit["revision_round"] == 1
    assert after_resubmit["qualification_status"] == "IN_PROGRESS"


def test_marking_no_response_before_two_weeks_is_refused(api):
    """PRD §3.3: "Marking a segment as unanswered is accepted only from `REQUESTED` and only
    once the logical clock has reached or passed two weeks — 14 days — after
    `last_requested_at`."
    PRD §3.3: "Issuing the request moves the segment to `REQUESTED` from either `PENDING` or
    `NO_RESPONSE`, increments `request_round` by one and stamps `last_requested_at` with the
    current logical-clock instant; a segment whose parent application has already reached
    `SCREEN_FAILED` may not be chased further, and a re-request out of `NO_RESPONSE` is
    accepted only while `request_round` is strictly less than 3."
    PRD §2.9: "Then the generic state ladder: the target row must be in a declared origin
    state for the requested transition (`ERR_INVALID_STATE`, 409), and must not already sit
    in one of its terminal states (`ERR_ALREADY_TERMINAL`, 409)."

    Design: Corner/state_machines/mark_no_response_before_wait_period_returns_409_invalid_state
    """
    ctx = setup_submitted_application(carrier_overrides={"dot_number": "DOT-CORNER-1"})
    verification = record_employment_segment(
        ctx["application_id"], "Silver Spur Freight", "2022-01-01", "2024-09-01"
    )
    validate_success(api.send_verification_request(verification["id"], RECRUITER))
    set_clock("2026-08-14T23:00:00Z")

    response = api.mark_verification_no_response(verification["id"], RECRUITER)

    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)
    row = validate_success(api.get_employment_verification(verification["id"], RECRUITER))
    assert row["status"] == "REQUESTED"
    assert row["request_round"] == 1
    assert row["last_requested_at"] == "2026-08-01T00:00:00.000Z"


def test_consent_denial_fails_the_screening_axis_and_archives_the_file(api):
    """PRD §3.5: "A denial moves the row to the terminal `CONSENT_DENIED` and cascades the
    parent application's `screening_status` to `SCREEN_FAILED` with the reason token
    `CONSENT_REFUSED`, which sets `qualification_status` to `DISQUALIFIED`, which archives
    the qualification file and cancels the application's reserved enrollments."
    PRD §3.5: "Queries open in `CONSENT_PENDING` with `result` at `PENDING`,
    `consent_granted_at` and `consent_expires_on` both null, and `follow_up_full_query_id`
    null."

    Design: Corner/state_machines/consent_denied_cascades_application_to_screen_failed
    """
    ctx = setup_submitted_application(carrier_overrides={"dot_number": "DOT-CORNER-1"})
    query = open_clearinghouse_query(ctx["application_id"], "FULL")

    denied = validate_success(
        api.consent_decision(
            query["id"], {"decision": "DENY"}, make_applicant_headers(ctx["applicant_id"])
        )
    )

    assert denied["status"] == "CONSENT_DENIED"
    assert denied["consent_granted_at"] is None

    application = validate_success(
        api.get_driver_application(ctx["application_id"], RECRUITER)
    )
    assert application["screening_status"] == "SCREEN_FAILED"
    assert application["qualification_status"] == "DISQUALIFIED"
    assert application["disqualifying_reason"] == "CONSENT_REFUSED"
    assert fetch_dq_file(ctx["dq_file_id"])["status"] == "ARCHIVED"


def test_a_second_dilute_recollection_is_refused(api):
    """PRD §3.5: "Recording a collection supplies the `collected_at` instant and moves the
    order to `COLLECTED` from either `ORDERED` or `LAB_DILUTE`; the second of those is a
    recollection and is accepted only while `dilute_recollect_count` is strictly below the
    single permitted recollection, meaning a count of zero, and it increments that counter by
    one. A second dilute recollection is therefore refused with `ERR_INVALID_STATE`, closing
    the `COLLECTED → LAB_DILUTE → COLLECTED` loop after exactly one lap."

    Design: Corner/state_machines/drug_test_second_dilute_recollection_returns_409_invalid_state
    """
    ctx = setup_submitted_application(carrier_overrides={"dot_number": "DOT-CORNER-1"})
    order = validate_success(
        api.create_drug_test_order(
            {"application_id": ctx["application_id"], "test_type": "PRE_EMPLOYMENT"}, DER
        ),
        201,
    )
    validate_success(
        api.record_collection(order["id"], {"collected_at": "2026-08-01T09:00:00Z"}, DER)
    )
    validate_success(api.record_lab_result(order["id"], {"lab_result": "DILUTE"}, DER))
    validate_success(
        api.record_collection(order["id"], {"collected_at": "2026-08-03T09:00:00Z"}, DER)
    )
    validate_success(api.record_lab_result(order["id"], {"lab_result": "DILUTE"}, DER))

    response = api.record_collection(
        order["id"], {"collected_at": "2026-08-05T09:00:00Z"}, DER
    )

    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)
    row = validate_success(api.get_drug_test_order(order["id"], DER))
    assert row["status"] == "LAB_DILUTE"
    assert row["dilute_recollect_count"] == 1
    assert row["collected_at"] == "2026-08-03T09:00:00.000Z"


def test_opening_a_class_at_or_after_its_start_instant_is_refused(api):
    """PRD §3.6: "Opening the class for enrollment moves it `PLANNED → OPEN` and is accepted
    only while the logical clock is strictly earlier than `starts_at`; the move increments the
    session's `version` by one."
    PRD §3.6: "Classes open in `PLANNED` with `enrolled_count` at zero, and may be listed and
    narrowed by `carrier_id` or by `status`."
    PRD §2.9: "Then the generic state ladder: the target row must be in a declared origin
    state for the requested transition (`ERR_INVALID_STATE`, 409), and must not already sit in
    one of its terminal states (`ERR_ALREADY_TERMINAL`, 409)."

    Design: Corner/state_machines/session_open_after_start_time_returns_409_invalid_state
    """
    carrier = create_carrier(dot_number="DOT-CORNER-1")
    session = validate_success(
        api.create_orientation_session(
            {
                "carrier_id": carrier["id"],
                "starts_at": "2026-08-10T13:00:00Z",
                "ends_at": "2026-08-12T21:00:00Z",
                "capacity": 2,
                "location_code": "DAL-1",
            },
            RECRUITER,
        ),
        201,
    )
    set_clock("2026-08-10T13:00:00Z")

    response = api.open_orientation_session(session["id"], RECRUITER)

    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)
    row = validate_success(api.get_orientation_session(session["id"], RECRUITER))
    assert row["status"] == "PLANNED"
    assert row["enrolled_count"] == 0


def test_cancelling_a_reservation_returns_the_seat_and_bumps_the_session(api):
    """PRD §3.6: "Cancelling a reservation is a `Recruiter` action carrying a `reason`; it
    moves the enrollment `RESERVED → CANCELLED`, decrements the session's `enrolled_count` by
    one and increments the session's `version` by one."

    Design: Corner/state_machines/enrollment_cancel_releases_seat_and_bumps_session_version
    """
    ctx = setup_submitted_application(carrier_overrides={"dot_number": "DOT-CORNER-1"})
    complete_negative_drug_test(ctx["application_id"])
    pass_road_test(ctx["application_id"])
    session = create_open_session(ctx["carrier_id"])
    version_after_open = session["version"]
    enrollment = reserve_seat(session["id"], ctx["application_id"], version_after_open)

    cancelled = validate_success(
        api.cancel_orientation_enrollment(
            enrollment["id"], {"reason": "CANDIDATE_RESCHEDULED"}, RECRUITER
        )
    )

    assert cancelled["status"] == "CANCELLED"
    session_now = validate_success(api.get_orientation_session(session["id"], RECRUITER))
    assert session_now["enrolled_count"] == 0
    assert session_now["version"] == version_after_open + 2, (
        "the reservation and the cancellation each bump the session version by one"
    )
    application = validate_success(
        api.get_driver_application(ctx["application_id"], RECRUITER)
    )
    assert application["qualification_status"] == "ROAD_TEST_PASSED"


def test_completing_a_class_with_no_attendance_marks_the_seat_absent(api):
    """PRD §3.6: "The session moves `OPEN → COMPLETED`; every listed enrollment moves
    `RESERVED → ATTENDED` and every other still-reserved enrollment of the session moves
    `RESERVED → ABSENT`; the session's `version` increments by one."
    PRD §3.6: "An absence changes nothing on the application and does not release the seat."
    PRD §3.6: "The `enrolled_count` figure counts every enrollment of the session in
    `RESERVED`, `ATTENDED` or `ABSENT`, so an absent driver still occupies the seat they
    consumed; only a cancellation gives a seat back."

    Design: Corner/state_machines/session_complete_with_empty_attendance_marks_enrollment_absent
    """
    ctx = setup_submitted_application(carrier_overrides={"dot_number": "DOT-CORNER-1"})
    complete_negative_drug_test(ctx["application_id"])
    pass_road_test(ctx["application_id"])
    session = create_open_session(ctx["carrier_id"])
    enrollment = reserve_seat(session["id"], ctx["application_id"], session["version"])
    set_clock("2026-08-12T22:00:00Z")

    completed = validate_success(
        api.complete_orientation_session(
            session["id"], {"attended_enrollment_ids": []}, RECRUITER
        )
    )

    assert completed["status"] == "COMPLETED"
    assert completed["enrolled_count"] == 1
    row = validate_success(api.get_orientation_enrollment(enrollment["id"], RECRUITER))
    assert row["status"] == "ABSENT"
    application = validate_success(
        api.get_driver_application(ctx["application_id"], RECRUITER)
    )
    assert application["qualification_status"] == "ROAD_TEST_PASSED"


def test_rescheduling_a_failed_road_test_clears_every_score(api):
    """PRD §3.6: "The reschedule supplies a fresh `scheduled_at` and a fresh
    `examiner_user_id`, which replace the previous values; `attempt_number` increments by one,
    and `score_pretrip`, `score_skills`, `score_road` and `composite_score` are all cleared
    back to null."
    PRD §3.6: "A `FAILED` outcome moves the test `SCHEDULED → FAILED` and computes
    `composite_score` from the supplied sub-scores, but changes nothing on the application or
    the file."

    Design: Corner/state_machines/road_test_reschedule_resets_scores_and_increments_attempt
    """
    ctx = setup_submitted_application(carrier_overrides={"dot_number": "DOT-CORNER-1"})
    road_test = validate_success(
        api.create_road_test(
            {
                "application_id": ctx["application_id"],
                "examiner_user_id": "exam-501",
                "scheduled_at": "2026-08-05T14:00:00Z",
                "vehicle_class": "CLASS_A",
            },
            RECRUITER,
        ),
        201,
    )
    failed = validate_success(
        api.record_road_test_result(
            road_test["id"],
            {"outcome": "FAILED", "score_pretrip": 40, "score_skills": 40, "score_road": 40},
            make_safety_director_headers("exam-501"),
        )
    )
    assert float(failed["composite_score"]) == 40.0
    assert failed["status"] == "FAILED"
    assert failed["attempt_number"] == 1

    rescheduled = validate_success(
        api.reschedule_road_test(
            road_test["id"],
            {"scheduled_at": "2026-08-07T09:00:00Z", "examiner_user_id": "exam-509"},
            RECRUITER,
        )
    )

    assert rescheduled["status"] == "SCHEDULED"
    assert rescheduled["attempt_number"] == 2
    assert rescheduled["scheduled_at"] == "2026-08-07T09:00:00.000Z"
    assert rescheduled["examiner_user_id"] == "exam-509"
    assert rescheduled["score_pretrip"] is None
    assert rescheduled["score_skills"] is None
    assert rescheduled["score_road"] is None
    assert rescheduled["composite_score"] is None


def test_passing_an_mvr_files_the_matching_artifact_with_its_expiry(api):
    """PRD §3.4: "On success the row moves `RECEIVED → ADJUDICATED_PASS` and the corresponding
    artifact of the application's qualification file is filed automatically: an `MVR` check
    satisfies the `MVR_INITIAL` document, a `PSP` check satisfies the `PSP_REPORT` document,
    and a `CRIMINAL` check satisfies the `CRIMINAL_CHECK` document."
    PRD §3.4: "That document is set to `PRESENT` with `effective_on` equal to the check's
    `issued_on` and `expires_on` equal to the check's own `expires_on`; the file's
    `completeness_pct`, `deficiency_count` and status are recomputed, the file's `version`
    increments by one, and the application is re-evaluated for the `SCREENING →
    SCREEN_CLEARED` move."
    PRD §3.4: "For a motor vehicle record the service also computes `expires_on` as
    `issued_on` advanced by the carrier's `mvr_validity_days`; for a Pre-Employment Screening
    Program report and for a criminal check `expires_on` stays null."

    Design: Corner/state_machines/screening_pass_files_matching_dq_document_with_expiry
    """
    ctx = setup_submitted_application(carrier_overrides={"dot_number": "DOT-CORNER-1"})
    check = order_screening_check(ctx["application_id"], "MVR")
    record_screening_check_result(check["id"], issued_on="2026-07-01")

    passed = validate_success(
        api.adjudicate_screening_check(check["id"], {"decision": "PASS"}, SAFETY_DIRECTOR)
    )
    assert passed["status"] == "ADJUDICATED_PASS"

    documents, _ = validate_paginated(
        api.list_dq_documents(
            RECRUITER, params={"dq_file_id": ctx["dq_file_id"], "doc_type": "MVR_INITIAL"}
        )
    )
    document = documents[0]
    assert document["status"] == "PRESENT"
    assert document["effective_on"] == "2026-07-01"
    assert document["expires_on"] == "2027-07-01"

    dq_file = fetch_dq_file(ctx["dq_file_id"])
    assert float(dq_file["completeness_pct"]) == 21.43
    assert dq_file["deficiency_count"] == 8
    assert dq_file["status"] == "OPEN"


def test_a_disputed_response_reporting_a_violation_fails_the_application(api):
    """PRD §3.3: "A `DISPUTED` outcome moves the segment to `RESPONDED_DISPUTED`; it does not
    credit any coverage, and when `drug_alcohol_violation_reported` came back true it cascades
    the parent application's `screening_status` to `SCREEN_FAILED` with the reason token
    `PRIOR_DA_VIOLATION`, which in turn disqualifies the application, archives its file and
    cancels its reserved enrollments."
    PRD §3.3: "Recording a response is accepted only from `REQUESTED` and carries three
    fields: an `outcome` of either `VERIFIED` or `DISPUTED`, plus the booleans
    `safety_performance_history_received` and `drug_alcohol_violation_reported`, both of which
    are stored on the segment whichever branch is taken."
    PRD §3.3: "Segments in `PENDING`, `REQUESTED`, `NO_RESPONSE` or `RESPONDED_DISPUTED` are
    excluded by both accountings."

    Design: Corner/state_machines/employment_response_disputed_with_violation_cascades_screen_failed
    """
    ctx = setup_submitted_application(carrier_overrides={"dot_number": "DOT-CORNER-1"})
    verification = record_employment_segment(
        ctx["application_id"], "Silver Spur Freight", "2022-01-01", "2024-09-01"
    )
    validate_success(api.send_verification_request(verification["id"], RECRUITER))

    responded = validate_success(
        api.record_verification_response(
            verification["id"],
            {
                "outcome": "DISPUTED",
                "safety_performance_history_received": True,
                "drug_alcohol_violation_reported": True,
            },
            RECRUITER,
        )
    )

    assert responded["status"] == "RESPONDED_DISPUTED"
    assert responded["drug_alcohol_violation_reported"] is True

    application = validate_success(
        api.get_driver_application(ctx["application_id"], RECRUITER)
    )
    assert application["screening_status"] == "SCREEN_FAILED"
    assert application["qualification_status"] == "DISQUALIFIED"
    assert application["disqualifying_reason"] == "PRIOR_DA_VIOLATION"

    projected = validate_success(
        api.get_employment_coverage(
            ctx["application_id"],
            TEST_USERS["compliance_auditor_headers"],
            params={"variant": "good_faith_projected"},
        )
    )
    assert projected["verified_coverage_days"] == 0
    assert projected["merged_segment_count"] == 0
