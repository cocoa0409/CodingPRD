"""Corner queue — VEE transcript review and module progression gates.

PRD §3.4 (VEE review states, grade floor, topic uniqueness) and PRD §3.5
(sequence gate, retake cooldown, capstone gate).
"""
from test_helpers import (
    ACADEMIC_REVIEWER,
    ApiErrorId,
    CAPSTONE_PASSING_SCORE,
    CLOCK_COOLDOWN_BLOCKED,
    CLOCK_COOLDOWN_EXACT,
    DEFAULT_COOLDOWN_DAYS,
    MODULE_CAP_CODE,
    MODULE_CAP_TITLE,
    MODULE_M1_CODE,
    MODULE_M1_TITLE,
    MODULE_PASSING_SCORE,
    NON_EXISTENT_UUID,
    REGISTRAR,
    SUBMIT_SCORE_FAIL,
    SUBMIT_SCORE_PASS,
    TRACK_QFI,
    VEE_GRADE_BELOW,
    VEE_GRADE_BOUNDARY,
    VEE_GRADE_REJECT_FIRST,
    VEE_GRADE_RESUBMIT,
    attempt_and_submit,
    create_module_attempt_payload,
    create_vee_submission_payload,
    get_enrollment,
    get_success_data,
    make_candidate,
    make_candidate_headers,
    make_module,
    review_vee_submission_payload,
    set_clock,
    setup_associate,
    setup_enrollment,
    validate_error,
    validate_success,
)


def test_vee_resubmission_after_rejection(api):
    """PRD §3.4: "Only a `SUBMITTED` submission is reviewable — a review
    attempted on an already-decided submission is rejected with
    `ERR_VEE_NOT_REVIEWABLE`."
    PRD §3.4: "Rejection is terminal for that record; the resubmission path is
    simply to file a fresh submission for the same topic."

    Design: Corner/state_machines/vee_resubmission_after_rejection
    """
    candidate = make_candidate(api)
    headers = make_candidate_headers(candidate["id"])
    sub1 = validate_success(api.create_vee_submission(
        create_vee_submission_payload(topic="ECONOMICS", grade_points=VEE_GRADE_REJECT_FIRST),
        headers), 201)
    rejected = validate_success(api.review_vee_submission(
        sub1["id"], review_vee_submission_payload("REJECT", reviewer_note="course not equivalent"),
        ACADEMIC_REVIEWER))
    assert rejected["status"] == "REJECTED"

    resp = api.review_vee_submission(sub1["id"], {"decision": "APPROVE"}, ACADEMIC_REVIEWER)
    validate_error(resp, ApiErrorId.ERR_VEE_NOT_REVIEWABLE)

    sub2 = validate_success(api.create_vee_submission(
        create_vee_submission_payload(topic="ECONOMICS", course_title="EC101R",
                                      grade_points=VEE_GRADE_RESUBMIT),
        headers), 201)
    assert sub2["status"] == "SUBMITTED"
    approved = validate_success(api.review_vee_submission(
        sub2["id"], review_vee_submission_payload("APPROVE", reviewer_note="syllabus matches"),
        ACADEMIC_REVIEWER))
    assert approved["status"] == "APPROVED"


def test_vee_topic_credited_blocks_duplicate(api):
    """PRD §3.4: "The society credits a topic at most once: when an `APPROVED`
    submission already exists for the same candidate and topic, a fresh
    submission is rejected with `ERR_VEE_TOPIC_ALREADY_CREDITED`."

    Design: Corner/state_machines/vee_topic_credited_blocks_duplicate
    """
    candidate = make_candidate(api)
    headers = make_candidate_headers(candidate["id"])
    sub = validate_success(api.create_vee_submission(
        create_vee_submission_payload(topic="ECONOMICS"), headers), 201)
    validate_success(api.review_vee_submission(
        sub["id"], review_vee_submission_payload("APPROVE"), ACADEMIC_REVIEWER))

    resp = api.create_vee_submission(
        create_vee_submission_payload(topic="ECONOMICS", university="Other University",
                                      course_title="EC201", grade_points=3.9),
        headers)
    validate_error(resp, ApiErrorId.ERR_VEE_TOPIC_ALREADY_CREDITED)

    other = validate_success(api.create_vee_submission(
        create_vee_submission_payload(topic="CORPORATE_FINANCE", university="Other University",
                                      course_title="FN201", grade_points=3.9),
        headers), 201)
    assert other["topic"] == "CORPORATE_FINANCE"


def test_vee_grade_threshold_boundary(api):
    """PRD §3.4: "an approve decision on a submission whose `grade_points` is
    below 2.7 is rejected with `ERR_VEE_GRADE_BELOW_THRESHOLD`, while a grade
    of exactly 2.70 approves."

    Design: Corner/state_machines/vee_grade_threshold_boundary
    """
    candidate = make_candidate(api)
    headers = make_candidate_headers(candidate["id"])
    sub_low = validate_success(api.create_vee_submission(
        create_vee_submission_payload(topic="ECONOMICS", grade_points=VEE_GRADE_BELOW),
        headers), 201)
    sub_edge = validate_success(api.create_vee_submission(
        create_vee_submission_payload(topic="CORPORATE_FINANCE", grade_points=VEE_GRADE_BOUNDARY),
        headers), 201)

    resp = api.review_vee_submission(sub_low["id"], {"decision": "APPROVE"}, ACADEMIC_REVIEWER)
    validate_error(resp, ApiErrorId.ERR_VEE_GRADE_BELOW_THRESHOLD)

    approved = validate_success(api.review_vee_submission(
        sub_edge["id"], review_vee_submission_payload("APPROVE"), ACADEMIC_REVIEWER))
    assert approved["status"] == "APPROVED"

    rows = get_success_data(api.list_candidate_vee_submissions(candidate["id"], REGISTRAR))
    low_row = [r for r in rows if r["id"] == sub_low["id"]][0]
    assert low_row["status"] == "SUBMITTED"


def test_module_sequence_gate(api):
    """PRD §3.5: "a non-capstone module at sequence position k beyond the
    first requires a `PASSED` attempt on the module at sequence position k−1
    of the same track under the same enrollment; either violation is rejected
    with `ERR_MODULE_SEQUENCE_LOCKED`."
    PRD §2.8: "Foreign keys supplied in a request body (such as `exam_id`,
    `syllabus_version_id`, `prerequisite_exam_id`, `exam_window_id`,
    `module_id`, `track_enrollment_id`, or `course_session_id`) are likewise
    resolved to existing resources, each failure producing the not-found error
    of the referenced resource type."

    Design: Corner/state_machines/module_sequence_gate
    """
    candidate = setup_associate(api)["candidate"]
    ctx = setup_enrollment(api, candidate)
    enrollment, modules = ctx["enrollment"], ctx["modules"]
    module1, module2 = modules[0], modules[1]
    headers = make_candidate_headers(candidate["id"])

    resp_nf = api.create_module_attempt(
        create_module_attempt_payload(enrollment["id"], NON_EXISTENT_UUID), headers)
    validate_error(resp_nf, ApiErrorId.ERR_MODULE_NOT_FOUND)

    resp_seq = api.create_module_attempt(
        create_module_attempt_payload(enrollment["id"], module2["id"]), headers)
    validate_error(resp_seq, ApiErrorId.ERR_MODULE_SEQUENCE_LOCKED)

    attempt_and_submit(api, candidate, enrollment, module1, score=SUBMIT_SCORE_PASS)
    attempt2 = validate_success(api.create_module_attempt(
        create_module_attempt_payload(enrollment["id"], module2["id"]), headers), 201)
    assert attempt2["status"] == "IN_PROGRESS"
    assert attempt2["attempt_number"] == 1


def test_module_cooldown_boundary_exactly_14_days(api):
    """PRD §3.5: "a new attempt on a module is blocked while a `FAILED`
    attempt on the same module under the same enrollment has a `submitted_at`
    plus the module's `cooldown_days` lying strictly later than the current
    logical clock — reaching that moment exactly is enough, and the retake is
    allowed — and a blocked retake is rejected with
    `ERR_MODULE_COOLDOWN_ACTIVE`."

    Design: Corner/state_machines/module_cooldown_boundary_exactly_14_days
    """
    candidate = setup_associate(api)["candidate"]
    enrollment = setup_enrollment(api, candidate, with_modules=False)["enrollment"]
    module = make_module(api, module_code=MODULE_M1_CODE, track_code=TRACK_QFI,
                         sequence_index=1, title=MODULE_M1_TITLE,
                         passing_score=MODULE_PASSING_SCORE,
                         cooldown_days=DEFAULT_COOLDOWN_DAYS)
    headers = make_candidate_headers(candidate["id"])
    failed = attempt_and_submit(api, candidate, enrollment, module, score=SUBMIT_SCORE_FAIL)
    assert failed["status"] == "FAILED"
    assert failed["submitted_at"].startswith("2026-10-13")

    # 13 days after the FAILED submit: cooldown still active.
    set_clock(api, CLOCK_COOLDOWN_BLOCKED)
    resp = api.create_module_attempt(
        create_module_attempt_payload(enrollment["id"], module["id"]), headers)
    validate_error(resp, ApiErrorId.ERR_MODULE_COOLDOWN_ACTIVE)

    # Exactly submitted_at + 14 days: the strict-later boundary allows it.
    set_clock(api, CLOCK_COOLDOWN_EXACT)
    retake = validate_success(api.create_module_attempt(
        create_module_attempt_payload(enrollment["id"], module["id"]), headers), 201)
    assert retake["attempt_number"] == 2
    assert retake["status"] == "IN_PROGRESS"


def test_capstone_locked_until_eligible(api):
    """PRD §3.5: "A capstone module additionally requires the enrollment to
    have reached `CAPSTONE_ELIGIBLE`."
    PRD §3.5: "When every non-capstone module of the track has been passed, the
    enrollment transitions `ENROLLED` → `CAPSTONE_ELIGIBLE`."

    Design: Corner/state_machines/capstone_locked_until_eligible
    """
    candidate = setup_associate(api)["candidate"]
    enrollment = setup_enrollment(api, candidate, with_modules=False)["enrollment"]
    module1 = make_module(api, module_code=MODULE_M1_CODE, track_code=TRACK_QFI,
                          sequence_index=1, title=MODULE_M1_TITLE,
                          passing_score=MODULE_PASSING_SCORE)
    capstone = make_module(api, module_code=MODULE_CAP_CODE, track_code=TRACK_QFI,
                           sequence_index=2, title=MODULE_CAP_TITLE, is_capstone=True,
                           passing_score=CAPSTONE_PASSING_SCORE)
    headers = make_candidate_headers(candidate["id"])

    resp = api.create_module_attempt(
        create_module_attempt_payload(enrollment["id"], capstone["id"]), headers)
    validate_error(resp, ApiErrorId.ERR_MODULE_SEQUENCE_LOCKED)

    attempt_and_submit(api, candidate, enrollment, module1, score=SUBMIT_SCORE_PASS)
    enrollment = get_enrollment(api, candidate)
    assert enrollment["status"] == "CAPSTONE_ELIGIBLE"

    cap_attempt = validate_success(api.create_module_attempt(
        create_module_attempt_payload(enrollment["id"], capstone["id"]), headers), 201)
    assert cap_attempt["status"] == "IN_PROGRESS"
