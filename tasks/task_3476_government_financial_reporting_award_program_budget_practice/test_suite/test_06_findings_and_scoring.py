"""Review findings: the pinned per-criterion rounding order, the live
provisional score, exact checklist-coverage validation, finding immutability,
and the depth-3 finding cascade into DECISION_READY (PRD §3.5, §3.6, §2.5).
"""

import pytest

from test_helpers import (
    ApiErrorId,
    AWARDS_DIRECTOR,
    assert_review_finding,
    file_finding,
    finding_payload,
    make_reviewer_headers,
    refresh_cycle,
    refresh_reviewer,
    refresh_submission,
    scores_for_criteria,
    setup_submission_with_review_round,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_finding_score_per_line_rounding_order(api):
    """PRD §3.5: "The finding's `weighted_score` follows a pinned rounding
    order: each criterion's `score` is multiplied by its pinned checklist
    `weight`, each per-criterion contribution is rounded half-up to 2 decimal
    places first, and those rounded contributions are then summed exactly.
    Consider a checklist whose two criteria each carry weight 0.5 and a
    finding scoring them 10.01 and 20.01: rounding each contribution first
    yields 5.01 and 10.01, which sum to 15.02. Summing the raw products first
    and rounding once would yield 15.01 — that order is deliberately not
    used."

    Design: Difficulty/combinatorial_formula/finding_score_per_line_rounding_order
    """
    bundle = setup_submission_with_review_round(api, num_reviewers=1)
    assignment = bundle["assignments"][0]
    criteria = bundle["checklist"]["criteria"]

    resp = api.submit_review_finding(
        assignment["id"],
        finding_payload(scores_for_criteria(criteria, [10.01, 20.01]), comments=[]),
        headers=make_reviewer_headers(assignment["reviewer_id"]),
    )
    finding = validate_success(resp, 201)
    assert_review_finding(finding)
    assert finding["weighted_score"] == pytest.approx(15.02, abs=1e-9), (
        "per-criterion rounding first: 5.01 + 10.01 = 15.02"
    )
    assert finding["weighted_score"] != pytest.approx(15.01, abs=1e-9), (
        "the sum-then-round order (15.01) is deliberately not used"
    )

    submitted = validate_success(
        api.get_review_assignment(assignment["id"], headers=AWARDS_DIRECTOR)
    )
    assert submitted["status"] == "SUBMITTED"


def test_provisional_score_partial_mean_after_two_findings(api):
    """PRD §3.6: "While a round is in flight, the submission's
    `provisional_score` tracks the mean of the current appeal round's
    submitted findings — the average of their `weighted_score` values, rounded
    half-up to 2 decimal places — and reads null whenever the round has no
    findings yet."

    Design: Corner/calculations/provisional_score_partial_mean_after_two_findings
    """
    bundle = setup_submission_with_review_round(api)
    submission_id = bundle["submission"]["id"]
    assignments = bundle["assignments"]
    criteria = bundle["checklist"]["criteria"]

    before = refresh_submission(api, submission_id)
    assert before["provisional_score"] is None

    file_finding(api, assignments[0], scores_for_criteria(criteria, [90, 80]))
    file_finding(api, assignments[1], scores_for_criteria(criteria, [88, 84]))

    after = refresh_submission(api, submission_id)
    # mean of weighted scores 85.00 and 86.00.
    assert after["provisional_score"] == pytest.approx(85.50, abs=1e-9)
    assert after["status"] == "UNDER_REVIEW", "quorum of three not yet reached"
    assert after["final_score"] is None


def test_finding_criterion_set_must_match_pinned_checklist(api):
    """PRD §3.5: "must cover exactly the criteria of the submission's pinned
    checklist: a code the checklist does not declare is rejected with
    `ERR_UNKNOWN_CRITERION`, and a declared criterion left unscored is
    rejected with `ERR_CRITERION_SET_INCOMPLETE`."

    Design: Corner/validations/finding_criterion_set_must_match_pinned_checklist
    """
    bundle = setup_submission_with_review_round(api, num_reviewers=1)
    assignment = bundle["assignments"][0]
    headers = make_reviewer_headers(assignment["reviewer_id"])

    # An undeclared code (with every declared code also scored) — only the
    # unknown-criterion rule can fire.
    unknown = api.submit_review_finding(
        assignment["id"],
        finding_payload(
            scores_for_criteria(
                bundle["checklist"]["criteria"], [90, 80]
            )
            + [{"criterion_code": "X1", "score": 50}],
            comments=[],
        ),
        headers=headers,
    )
    validate_error(unknown, ApiErrorId.ERR_UNKNOWN_CRITERION)

    # A declared criterion left unscored — only the completeness rule fires.
    incomplete = api.submit_review_finding(
        assignment["id"],
        finding_payload([{"criterion_code": "C1", "score": 90}], comments=[]),
        headers=headers,
    )
    validate_error(incomplete, ApiErrorId.ERR_CRITERION_SET_INCOMPLETE)

    # The failed attempts did not consume the assignment: the corrected
    # finding succeeds (90 * 0.5 + 80 * 0.5 = 85.00).
    corrected = validate_success(
        api.submit_review_finding(
            assignment["id"],
            finding_payload(
                scores_for_criteria(bundle["checklist"]["criteria"], [90, 80]),
                comments=[],
            ),
            headers=headers,
        ),
        201,
    )
    assert corrected["weighted_score"] == pytest.approx(85.00, abs=1e-9)


def test_review_finding_immutable_second_finding_rejected(api):
    """PRD §2.5: "The review finding is the sole exception: it is an immutable
    record created once and never modified, so it carries only `id` and
    `created_at` — both `updated_at` and `version` are absent from it."
    PRD §3.5: "Filing a finding is the round's productive act. The reviewer
    must own an `ACCEPTED` assignment and still be `ELIGIBLE`, under the same
    ownership, state, and eligibility errors as acceptance."

    Design: Corner/entities/review_finding_immutable_second_finding_rejected
    """
    bundle = setup_submission_with_review_round(api, num_reviewers=1)
    assignment = bundle["assignments"][0]
    criteria = bundle["checklist"]["criteria"]
    headers = make_reviewer_headers(assignment["reviewer_id"])

    first = file_finding(api, assignment, scores_for_criteria(criteria, [90, 80]))
    assert first["weighted_score"] == pytest.approx(85.00, abs=1e-9)

    second = api.submit_review_finding(
        assignment["id"],
        finding_payload(scores_for_criteria(criteria, [50, 50]), comments=[]),
        headers=headers,
    )
    validate_error(second, ApiErrorId.ERR_ASSIGNMENT_STATE_INVALID)

    rows, meta = validate_paginated(
        api.list_review_findings(
            headers=AWARDS_DIRECTOR, params={"assignment_id": assignment["id"]}
        )
    )
    assert meta["total_count"] == 1 and len(rows) == 1
    assert_review_finding(rows[0])
    assert rows[0]["weighted_score"] == pytest.approx(85.00, abs=1e-9), (
        "the original finding is unchanged"
    )


def test_finding_submit_depth3_cascade(api):
    """PRD §3.5: "A filed finding ripples outward in a fixed cascade. The
    assignment moves from `ACCEPTED` to `SUBMITTED`; the reviewer's
    `open_assignment_count` decrements and `completed_review_count`
    increments; the submission's `provisional_score` and
    `major_deficiency_total` are recomputed over the current round's findings;
    and when the finding is the round's third, the submission advances from
    `UNDER_REVIEW` to `DECISION_READY` and the cycle's `decision_ready_count`
    increments."

    Design: Difficulty/transitive_cascade/finding_submit_depth3_cascade
    """
    bundle = setup_submission_with_review_round(api)
    submission_id = bundle["submission"]["id"]
    assignments = bundle["assignments"]
    criteria = bundle["checklist"]["criteria"]

    f1 = file_finding(api, assignments[0], scores_for_criteria(criteria, [90, 80]))
    f2 = file_finding(api, assignments[1], scores_for_criteria(criteria, [88, 84]))
    f3 = file_finding(api, assignments[2], scores_for_criteria(criteria, [92, 76]))

    # Link 1: per-finding weighted scores and the filing reviewer's counters.
    assert f1["weighted_score"] == pytest.approx(85.00, abs=1e-9)
    assert f2["weighted_score"] == pytest.approx(86.00, abs=1e-9)
    assert f3["weighted_score"] == pytest.approx(84.00, abs=1e-9)
    third_reviewer = refresh_reviewer(api, assignments[2]["reviewer_id"])
    assert third_reviewer["open_assignment_count"] == 0
    assert third_reviewer["completed_review_count"] == 1

    # Link 2: the submission flips to DECISION_READY only via the third
    # finding, with the recomputed provisional score (mean of 85/86/84).
    submission = refresh_submission(api, submission_id)
    assert submission["status"] == "DECISION_READY"
    assert submission["provisional_score"] == pytest.approx(85.00, abs=1e-9)

    # Link 3: the cycle counter moved as a consequence of the submission flip.
    cycle = refresh_cycle(api, bundle["cycle"]["id"])
    assert cycle["decision_ready_count"] == 1
