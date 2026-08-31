"""Depth coverage: which rung wins a dual failure, and the exact numeric edges."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_second_applicant,
    create_application,
    fetch_applicant,
    fetch_dq_document,
    fetch_dq_file,
    file_dq_document,
    make_compliance_auditor_headers,
    make_safety_director_headers,
    order_screening_check,
    record_screening_check_result,
    set_clock,
    setup_submitted_application,
    submit_application,
    validate_error,
    validate_success,
)

RECRUITER = TEST_USERS["recruiter_headers"]
SAFETY_DIRECTOR = TEST_USERS["safety_director_headers"]
AUDITOR = TEST_USERS["compliance_auditor_headers"]


def _archived_file_that_is_not_yet_due(dot_number: str):
    """A disqualified application whose file is ARCHIVED while its clock says NOT_DUE."""
    ctx = setup_submitted_application(
        carrier_overrides={"dot_number": dot_number}, recruiter_user_id="rec-001"
    )
    from test_helpers import api_client

    validate_success(
        api_client.disqualify_application(
            ctx["application_id"], {"reason": "WITHDREW_BY_CANDIDATE"}, SAFETY_DIRECTOR
        )
    )
    return ctx


def _overdue_file_without_any_screening_check(dot_number: str):
    """A file that is OVERDUE and has no motor vehicle record at all."""
    ctx = setup_submitted_application(
        carrier_overrides={"dot_number": dot_number}, recruiter_user_id="rec-001"
    )
    set_clock("2027-09-01T00:00:00Z")
    return ctx


def _exhausted_road_test_against_a_busy_examiner(dot_number: str):
    """Examiner exam-501 holds a SCHEDULED slot; a second test has used all three attempts."""
    ctx = setup_submitted_application(carrier_overrides={"dot_number": dot_number})
    from test_helpers import api_client

    blocker_applicant = add_second_applicant(ctx["carrier_id"], index=2)
    blocker_application = create_application(blocker_applicant["id"], position_type="LOCAL")
    submit_application(blocker_application["id"], "rec-001")
    blocking_test = validate_success(
        api_client.create_road_test(
            {
                "application_id": blocker_application["id"],
                "examiner_user_id": "exam-501",
                "scheduled_at": "2026-08-05T14:00:00Z",
                "vehicle_class": "CLASS_A",
            },
            RECRUITER,
        ),
        201,
    )
    examiner = make_safety_director_headers("exam-501")
    road_test = validate_success(
        api_client.create_road_test(
            {
                "application_id": ctx["application_id"],
                "examiner_user_id": "exam-501",
                "scheduled_at": "2026-08-06T09:00:00Z",
                "vehicle_class": "CLASS_A",
            },
            RECRUITER,
        ),
        201,
    )
    for scores, next_slot in (
        ((40, 40, 40), "2026-08-06T13:00:00Z"),
        ((45, 45, 45), "2026-08-06T17:00:00Z"),
    ):
        validate_success(
            api_client.record_road_test_result(
                road_test["id"],
                {
                    "outcome": "FAILED",
                    "score_pretrip": scores[0],
                    "score_skills": scores[1],
                    "score_road": scores[2],
                },
                examiner,
            )
        )
        validate_success(
            api_client.reschedule_road_test(
                road_test["id"],
                {"scheduled_at": next_slot, "examiner_user_id": "exam-501"},
                RECRUITER,
            )
        )
    validate_success(
        api_client.record_road_test_result(
            road_test["id"],
            {"outcome": "FAILED", "score_pretrip": 50, "score_skills": 50, "score_road": 50},
            examiner,
        )
    )
    ctx["road_test"] = road_test
    ctx["blocking_test"] = blocking_test
    return ctx


def _two_applications_scored_either_side_of_the_threshold(dot_number: str):
    """One MVR scoring exactly at the carrier's threshold, one scoring just below."""
    ctx = setup_submitted_application(
        carrier_overrides={
            "dot_number": dot_number,
            "safety_rating": "CONDITIONAL",
            "mvr_point_threshold": 7,
        },
        applicant_overrides={"experience_months": 24},
    )
    other_applicant = add_second_applicant(
        ctx["carrier_id"], index=2, full_name="Mo Diaz", email="mo.diaz@example.com"
    )
    other_application = create_application(other_applicant["id"], position_type="LOCAL")
    submit_application(other_application["id"], "rec-001")

    at_threshold = order_screening_check(ctx["application_id"], "MVR")
    record_screening_check_result(
        at_threshold["id"],
        issued_on="2026-07-01",
        violation_points=5,
        serious_violation_count=1,
    )
    below_threshold = order_screening_check(other_application["id"], "MVR")
    record_screening_check_result(
        below_threshold["id"],
        issued_on="2026-07-01",
        violation_points=4,
        serious_violation_count=1,
    )
    ctx["at_threshold_check"] = at_threshold
    ctx["below_threshold_check"] = below_threshold
    return ctx


def _application_with_a_certificate_expiring_on_the_first_of_october(dot_number: str):
    ctx = setup_submitted_application(carrier_overrides={"dot_number": dot_number})
    ctx["medical_cert_document"] = file_dq_document(
        ctx["dq_file_id"],
        "MEDICAL_CERT",
        status="PRESENT",
        effective_on="2026-07-15",
        expires_on="2026-10-01",
        source_ref="NRCME-889201",
    )
    return ctx


# ─── priority_pair_validation_conflict ────────────────────────────────────────

def test_an_archived_file_reports_invalid_state_rather_than_review_not_due(api):
    """PRD §3.7: "The file must not be `ARCHIVED`, which is enforced on the completeness axis
    and reports `ERR_INVALID_STATE`."
    PRD §2.9: "One nuance of the generic state rung deserves calling out. On the annual-review
    certification and on its revocation, that rung governs only the file's completeness-posture
    axis — any posture other than archived passes it. The review-clock axis is owned by its own
    rung further down and always surfaces as `ERR_REVIEW_NOT_DUE`, never as `ERR_INVALID_STATE`."
    PRD §3.7: "And the file's `review_state` must be `DUE` or `OVERDUE` — an early review is
    refused with `ERR_REVIEW_NOT_DUE`, never with `ERR_INVALID_STATE`, because the review-clock
    axis is owned by its own rung of the ladder in §2.9 and sits below the three checks just
    named."

    Design: Difficulty/priority_pair_validation_conflict/annual_review_state_error_beats_review_not_due
    """
    ctx = _archived_file_that_is_not_yet_due("DOT-2166-L")

    response = api.annual_review(
        ctx["dq_file_id"],
        {"certification_note": "routine"},
        make_compliance_auditor_headers("aud-900"),
    )

    assert response.status_code == 409
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_the_archived_file_is_left_uncertified_and_still_not_due(api):
    """PRD §3.2: "the one-to-one qualification file moves to `ARCHIVED` and its `version`
    increments by one"
    PRD §3.7: "The `review_state` reads `NOT_DUE` while the current logical-clock date is
    strictly earlier than `next_review_due_on`; it reads `DUE` from `next_review_due_on` through
    the end of grace inclusive — a file whose grace end equals the clock date is still `DUE` —
    and it reads `OVERDUE` from the day after that."
    PRD §3.7: "On success the review clock returns to `NOT_DUE`, `last_annual_review_at` is
    stamped with the current logical-clock instant and `certified_by_user_id` with the acting
    `X-User-ID`; the `MVR_ANNUAL` and `ANNUAL_REVIEW_CERT` documents both become `PRESENT` with
    `effective_on` at the current logical-clock date; `next_review_due_on` is recomputed as the
    calendar date of `last_annual_review_at` advanced by the carrier's
    `annual_review_interval_days`; `completeness_pct` and `deficiency_count` are recomputed; and
    the file's `version` increments by one."

    Design: Difficulty/priority_pair_validation_conflict/annual_review_state_error_beats_review_not_due
    """
    ctx = _archived_file_that_is_not_yet_due("DOT-2166-L")

    api.annual_review(
        ctx["dq_file_id"],
        {"certification_note": "routine"},
        make_compliance_auditor_headers("aud-900"),
    )

    dq_file = fetch_dq_file(ctx["dq_file_id"])
    assert dq_file["status"] == "ARCHIVED"
    assert dq_file["review_state"] == "NOT_DUE"
    assert dq_file["last_annual_review_at"] is None
    assert dq_file["certified_by_user_id"] is None


def test_the_auditor_identity_check_outranks_the_motor_vehicle_record_check(api):
    """PRD §2.10: "A `ComplianceAuditor` may not certify, nor revoke the certification of, a
    qualification file whose application was submitted by that same `X-User-ID`; the file records
    the submitter as `recruiter_user_id`, and equality between that value and the acting
    `X-User-ID` is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409)."
    PRD §3.7: "Four conditions guard it, and their relative order matters. The file must not be
    `ARCHIVED`, which is enforced on the completeness axis and reports `ERR_INVALID_STATE`. The
    auditor's `X-User-ID` must differ from the `recruiter_user_id` on the linked application,
    reporting `ERR_SEGREGATION_OF_DUTIES`. The application must have a motor vehicle record check
    in `ADJUDICATED_PASS` whose `expires_on` is on or after the current logical-clock date,
    reporting `ERR_MVR_EXPIRED`."

    Design: Difficulty/priority_pair_validation_conflict/annual_review_segregation_beats_missing_current_mvr
    """
    ctx = _overdue_file_without_any_screening_check("DOT-2166-M")

    response = api.annual_review(
        ctx["dq_file_id"],
        {"certification_note": "self-certified"},
        make_compliance_auditor_headers("rec-001"),
    )

    assert response.status_code == 409
    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 409)


def test_the_self_certification_attempt_leaves_the_overdue_file_uncertified(api):
    """PRD §3.7: "The `review_state` reads `NOT_DUE` while the current logical-clock date is
    strictly earlier than `next_review_due_on`; it reads `DUE` from `next_review_due_on` through
    the end of grace inclusive — a file whose grace end equals the clock date is still `DUE` — and
    it reads `OVERDUE` from the day after that."
    PRD §3.7: "On success the review clock returns to `NOT_DUE`, `last_annual_review_at` is
    stamped with the current logical-clock instant and `certified_by_user_id` with the acting
    `X-User-ID`; the `MVR_ANNUAL` and `ANNUAL_REVIEW_CERT` documents both become `PRESENT` with
    `effective_on` at the current logical-clock date; `next_review_due_on` is recomputed as the
    calendar date of `last_annual_review_at` advanced by the carrier's
    `annual_review_interval_days`; `completeness_pct` and `deficiency_count` are recomputed; and
    the file's `version` increments by one."

    Design: Difficulty/priority_pair_validation_conflict/annual_review_segregation_beats_missing_current_mvr
    """
    ctx = _overdue_file_without_any_screening_check("DOT-2166-M")

    api.annual_review(
        ctx["dq_file_id"],
        {"certification_note": "self-certified"},
        make_compliance_auditor_headers("rec-001"),
    )

    dq_file = fetch_dq_file(ctx["dq_file_id"])
    assert dq_file["review_state"] == "OVERDUE"
    assert dq_file["certified_by_user_id"] is None


def test_the_examiner_slot_rung_outranks_the_attempt_ceiling(api):
    """PRD §2.9: "Then the interval-ordering rung reporting `ERR_VALIDATION` at 422, followed by
    orientation overlap (`ERR_ORIENTATION_OVERLAP`), examiner slot conflict
    (`ERR_EXAMINER_SLOT_CONFLICT`), session capacity (`ERR_SESSION_AT_CAPACITY`) and road-test
    attempt exhaustion (`ERR_ROAD_TEST_ATTEMPTS_EXHAUSTED`)."
    PRD §3.6: "A new or rescheduled test is refused with `ERR_EXAMINER_SLOT_CONFLICT` when its
    closed slot intersects the identically-constructed closed slot of any other road test that is
    still `SCHEDULED` and carries the same `examiner_user_id` — because the interval is closed,
    two slots that merely touch endpoint-to-endpoint already collide."
    PRD §3.6: "A reschedule is accepted only while `attempt_number` is strictly below three
    attempts; a test already sitting at its third attempt reports
    `ERR_ROAD_TEST_ATTEMPTS_EXHAUSTED`."

    Design: Difficulty/priority_pair_validation_conflict/reschedule_slot_conflict_beats_attempts_exhausted
    """
    ctx = _exhausted_road_test_against_a_busy_examiner("DOT-2166-N")

    response = api.reschedule_road_test(
        ctx["road_test"]["id"],
        {"scheduled_at": "2026-08-05T15:00:00Z", "examiner_user_id": "exam-501"},
        RECRUITER,
    )

    assert response.status_code == 409
    validate_error(response, ApiErrorId.ERR_EXAMINER_SLOT_CONFLICT.value, 409)


def test_the_refused_reschedule_leaves_both_road_tests_where_they_were(api):
    """PRD §3.6: "The reschedule supplies a fresh `scheduled_at` and a fresh `examiner_user_id`,
    which replace the previous values; `attempt_number` increments by one, and `score_pretrip`,
    `score_skills`, `score_road` and `composite_score` are all cleared back to null."
    PRD §3.6: "Each booking consumes three hours of examiner time: the slot runs from
    `scheduled_at` to `scheduled_at` advanced by 180 minutes, and that interval is **closed at
    both ends**."

    Design: Difficulty/priority_pair_validation_conflict/reschedule_slot_conflict_beats_attempts_exhausted
    """
    ctx = _exhausted_road_test_against_a_busy_examiner("DOT-2166-N")

    api.reschedule_road_test(
        ctx["road_test"]["id"],
        {"scheduled_at": "2026-08-05T15:00:00Z", "examiner_user_id": "exam-501"},
        RECRUITER,
    )

    road_test = validate_success(api.get_road_test(ctx["road_test"]["id"], RECRUITER))
    assert road_test["attempt_number"] == 3
    assert road_test["status"] == "FAILED"
    assert road_test["scheduled_at"] == "2026-08-06T17:00:00.000Z"

    blocker = validate_success(api.get_road_test(ctx["blocking_test"]["id"], RECRUITER))
    assert blocker["status"] == "SCHEDULED"


# ─── boundary_precision_check ─────────────────────────────────────────────────

def test_a_score_exactly_at_the_threshold_is_disqualifying(api):
    """PRD §3.4: "A `PASS` decision is accepted only from `RECEIVED`, and for a motor vehicle
    record only when the `adjudication_score` is strictly below the carrier's
    `mvr_point_threshold` — a score exactly equal to the threshold is disqualifying and reports
    `ERR_MVR_POINTS_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/mvr_score_exactly_at_threshold_is_disqualifying
    """
    ctx = _two_applications_scored_either_side_of_the_threshold("DOT-2166-O")

    response = api.adjudicate_screening_check(
        ctx["at_threshold_check"]["id"], {"decision": "PASS"}, SAFETY_DIRECTOR
    )

    assert response.status_code == 409
    validate_error(response, ApiErrorId.ERR_MVR_POINTS_EXCEEDED.value, 409)
    check = validate_success(
        api.get_screening_check(ctx["at_threshold_check"]["id"], RECRUITER)
    )
    assert float(check["adjudication_score"]) == 7.50
    assert check["status"] == "RECEIVED", "the refused decision leaves the row untouched"


def test_a_score_just_below_the_threshold_passes(api):
    """PRD §3.4: "A `PASS` decision is accepted only from `RECEIVED`, and for a motor vehicle
    record only when the `adjudication_score` is strictly below the carrier's
    `mvr_point_threshold` — a score exactly equal to the threshold is disqualifying and reports
    `ERR_MVR_POINTS_EXCEEDED`."
    PRD §3.4: "On success the row moves `RECEIVED → ADJUDICATED_PASS` and the corresponding
    artifact of the application's qualification file is filed automatically: an `MVR` check
    satisfies the `MVR_INITIAL` document, a `PSP` check satisfies the `PSP_REPORT` document, and
    a `CRIMINAL` check satisfies the `CRIMINAL_CHECK` document."

    Design: Difficulty/boundary_precision_check/mvr_score_exactly_at_threshold_is_disqualifying
    """
    ctx = _two_applications_scored_either_side_of_the_threshold("DOT-2166-O")

    passed = validate_success(
        api.adjudicate_screening_check(
            ctx["below_threshold_check"]["id"], {"decision": "PASS"}, SAFETY_DIRECTOR
        )
    )

    assert float(passed["adjudication_score"]) == 6.25
    assert passed["status"] == "ADJUDICATED_PASS"


def test_an_application_with_no_segments_reports_a_full_unexplained_gap(api):
    """PRD §3.3: "Coverage itself is an interval-merge computation over a three-year lookback
    window of exactly 1,095 days."
    PRD §3.3: "The `verified_coverage_days` figure is the total number of days spanned by the
    merged runs, and `gap_days_unexplained` is 1,095 minus that figure."
    PRD §3.3: "That read answers with the `variant` it applied, the resulting
    `verified_coverage_days` and `gap_days_unexplained`, and a `merged_segment_count` giving the
    number of runs left after merging."

    Design: Difficulty/boundary_precision_check/employment_coverage_empty_set_yields_zero_days_and_full_gap
    """
    ctx = setup_submitted_application(carrier_overrides={"dot_number": "DOT-2166-P"})

    strict = validate_success(
        api.get_employment_coverage(
            ctx["application_id"], AUDITOR, params={"variant": "strict_verified"}
        )
    )

    assert strict["verified_coverage_days"] == 0
    assert strict["gap_days_unexplained"] == 1095
    assert strict["merged_segment_count"] == 0


def test_the_projected_accounting_of_an_empty_set_is_equally_empty(api):
    """PRD §3.3: "The projected accounting, named `good_faith_projected`, admits segments in
    `RESPONDED_VERIFIED` and `GOOD_FAITH_DOCUMENTED` alike, so an employer that never answered
    three documented requests still counts as covered; identical rows therefore yield a larger
    coverage and a smaller gap under the projected accounting than under the strict one."
    PRD §3.3: "The `verified_coverage_days` figure is the total number of days spanned by the
    merged runs, and `gap_days_unexplained` is 1,095 minus that figure."

    Design: Difficulty/boundary_precision_check/employment_coverage_empty_set_yields_zero_days_and_full_gap
    """
    ctx = setup_submitted_application(carrier_overrides={"dot_number": "DOT-2166-P"})

    projected = validate_success(
        api.get_employment_coverage(
            ctx["application_id"], AUDITOR, params={"variant": "good_faith_projected"}
        )
    )

    assert projected["verified_coverage_days"] == 0
    assert projected["gap_days_unexplained"] == 1095
    assert projected["merged_segment_count"] == 0

    application = validate_success(
        api.get_driver_application(ctx["application_id"], RECRUITER)
    )
    assert application["verified_coverage_days"] == 0
    assert application["gap_days_unexplained"] == 1095


def test_the_last_grace_day_still_reads_expired_grace(api):
    """PRD §3.7: "The band reads `NONE` when the countdown is greater than 60 days; `WATCH` when
    it is greater than 15 days and at most 60 days; `IMMINENT` when it is between 0 and 15 days
    inclusive, meaning the expiry has not yet passed; `EXPIRED_GRACE` when the expiry has passed
    but the number of days since it passed is at most the carrier's `medical_cert_grace_days`; and
    `DOWNGRADED` in every remaining case."
    PRD §3.7: "Otherwise the governing certificate is the candidate with the greatest
    `expires_on`, ties broken by the greatest `created_at` and never by identifier; its
    `expires_on` is copied into `governing_medical_cert_expires_on`."

    Design: Difficulty/boundary_precision_check/medical_cert_grace_day_boundary_expired_grace_then_downgraded
    """
    ctx = _application_with_a_certificate_expiring_on_the_first_of_october("DOT-2166-Q")
    set_clock("2026-10-16T00:00:00Z")

    applicant = fetch_applicant(ctx["applicant_id"])

    assert applicant["cdl_downgrade_risk"] == "EXPIRED_GRACE", (
        "exactly fifteen days past expiry is still inside the grace window"
    )
    assert applicant["governing_medical_cert_expires_on"] == "2026-10-01"


def test_one_day_past_the_grace_window_reads_downgraded(api):
    """PRD §3.7: "The band reads `NONE` when the countdown is greater than 60 days; `WATCH` when
    it is greater than 15 days and at most 60 days; `IMMINENT` when it is between 0 and 15 days
    inclusive, meaning the expiry has not yet passed; `EXPIRED_GRACE` when the expiry has passed
    but the number of days since it passed is at most the carrier's `medical_cert_grace_days`; and
    `DOWNGRADED` in every remaining case."
    PRD §3.7: "The band is recomputed whenever a document is written by hand, whenever the logical
    clock advances, and on every read of the applicant."

    Design: Difficulty/boundary_precision_check/medical_cert_grace_day_boundary_expired_grace_then_downgraded
    """
    ctx = _application_with_a_certificate_expiring_on_the_first_of_october("DOT-2166-Q")
    set_clock("2026-10-17T00:00:00Z")

    applicant = fetch_applicant(ctx["applicant_id"])
    document = fetch_dq_document(ctx["dq_file_id"], "MEDICAL_CERT")

    assert applicant["cdl_downgrade_risk"] == "DOWNGRADED"
    assert document["status"] == "PRESENT", (
        "the risk band is derived; the document row itself is never rewritten"
    )
