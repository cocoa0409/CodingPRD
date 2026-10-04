"""Corner queue — the written project assessment grading workflow.

Fork/join consensus, segregation of duties, and the capstone-stage gate
(PRD §3.6).
"""
from test_helpers import (
    ApiErrorId,
    GRADER_1_ID,
    GRADER_2_ID,
    GRADER_3_ID,
    GRADER_4_ID,
    PROJECT_FINAL_CONSENSUS,
    PROJECT_FINAL_MEDIAN,
    PROJECT_SCORE_G1,
    PROJECT_SCORE_G2,
    PROJECT_SPLIT_G1,
    PROJECT_SPLIT_G2,
    PROJECT_SPLIT_RESOLVER,
    PROJECT_TITLE,
    create_project_assessment_payload,
    get_success_data,
    grade_project_payload,
    make_grader_headers,
    setup_associate,
    setup_capstone_eligible,
    setup_enrollment,
    validate_error,
    validate_success,
    make_candidate_headers,
)


def test_project_split_resolved_by_third_grader_median(api):
    """PRD §3.6: "when they differ by more than ten points the assessment
    forks to `SPLIT` with both scores recorded and no final score yet. A
    `SPLIT` assessment is resolved by a third grade from a grader distinct
    from both prior graders, moving it to `DECIDED` with `final_score` equal
    to the median of the three scores."
    PRD §3.6: "once `DECIDED` it is terminal and further grades are rejected
    with `ERR_PROJECT_NOT_GRADABLE`."

    Design: Corner/state_machines/project_split_resolved_by_third_grader_median
    """
    ctx = setup_capstone_eligible(api)
    candidate, enrollment = ctx["candidate"], ctx["enrollment"]
    project = validate_success(api.create_project_assessment(
        create_project_assessment_payload(enrollment["id"], title=PROJECT_TITLE),
        make_candidate_headers(candidate["id"])), 201)
    assert project["status"] == "SUBMITTED"

    first = get_success_data(api.grade_project_assessment(
        project["id"], grade_project_payload(PROJECT_SPLIT_G1),
        make_grader_headers(GRADER_1_ID)))
    assert first["status"] == "IN_REVIEW"

    second = get_success_data(api.grade_project_assessment(
        project["id"], grade_project_payload(PROJECT_SPLIT_G2),
        make_grader_headers(GRADER_2_ID)))
    # |85 - 60| = 25 > 10: the fork branch records scores, no final yet.
    assert second["status"] == "SPLIT"
    assert second["final_score"] is None

    resolved = get_success_data(api.grade_project_assessment(
        project["id"], grade_project_payload(PROJECT_SPLIT_RESOLVER),
        make_grader_headers(GRADER_3_ID)))
    assert resolved["status"] == "DECIDED"
    # median(85, 60, 72) == 72; 72 >= 70 passes.
    assert resolved["final_score"] == PROJECT_FINAL_MEDIAN
    assert resolved["result"] == "PASS"

    resp = api.grade_project_assessment(
        project["id"], grade_project_payload(90), make_grader_headers(GRADER_4_ID))
    validate_error(resp, ApiErrorId.ERR_PROJECT_NOT_GRADABLE)


def test_project_grader_segregation_enforced(api):
    """PRD §3.6: "The workflow is a fork-and-join over at most three grades,
    governed throughout by segregation of duties: the acting grader's
    `X-User-ID` must not already appear in the assessment's `grader_ids`, and
    a repeat grading by the same grader is rejected with
    `ERR_GRADER_CONFLICT`."
    PRD §3.6: "when the two scores differ by at most ten points — the
    consensus tolerance — the assessment joins to `DECIDED` and its
    `final_score` is the mean of the two grades rounded half-up to a whole
    point."

    Design: Corner/state_machines/project_grader_segregation_enforced
    """
    ctx = setup_capstone_eligible(api)
    candidate, enrollment = ctx["candidate"], ctx["enrollment"]
    project = validate_success(api.create_project_assessment(
        create_project_assessment_payload(enrollment["id"], title=PROJECT_TITLE),
        make_candidate_headers(candidate["id"])), 201)

    get_success_data(api.grade_project_assessment(
        project["id"], grade_project_payload(PROJECT_SCORE_G1),
        make_grader_headers(GRADER_1_ID)))
    resp = api.grade_project_assessment(
        project["id"], grade_project_payload(90), make_grader_headers(GRADER_1_ID))
    validate_error(resp, ApiErrorId.ERR_GRADER_CONFLICT)

    decided = get_success_data(api.grade_project_assessment(
        project["id"], grade_project_payload(PROJECT_SCORE_G2),
        make_grader_headers(GRADER_2_ID)))
    assert decided["status"] == "DECIDED"
    # round_half_up((80 + 74) / 2, 0) == 77; 77 >= 70 passes.
    assert decided["final_score"] == PROJECT_FINAL_CONSENSUS
    assert decided["result"] == "PASS"
    assert decided["grader_ids"] == [GRADER_1_ID, GRADER_2_ID]


def test_project_requires_capstone_eligible(api):
    """PRD §3.6: "Submission requires the candidate to be `ACTIVE` and the
    enrollment to be `CAPSTONE_ELIGIBLE` or `COMPLETED`; a submission under an
    enrollment in any earlier state is rejected with
    `ERR_PROJECT_REQUIRES_CAPSTONE`."

    Design: Corner/state_machines/project_requires_capstone_eligible
    """
    candidate = setup_associate(api)["candidate"]
    enrollment = setup_enrollment(api, candidate)["enrollment"]
    assert enrollment["status"] == "ENROLLED"
    resp = api.create_project_assessment(
        create_project_assessment_payload(enrollment["id"], title="Too Early Project"),
        make_candidate_headers(candidate["id"]))
    validate_error(resp, ApiErrorId.ERR_PROJECT_REQUIRES_CAPSTONE)
