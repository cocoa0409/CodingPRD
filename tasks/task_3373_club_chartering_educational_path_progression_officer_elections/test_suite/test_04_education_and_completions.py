"""Education path levels, the requirement table and the completion review lifecycle."""
from test_helpers import (
    ApiErrorId,
    approve_completion,
    close_dues_cycle,
    create_organizing_club,
    create_path,
    enroll_membership,
    get_club,
    get_completion,
    get_membership,
    get_path,
    list_paths_for_membership,
    log_completion,
    make_member_headers,
    membership_version,
    path_version,
    record_evaluation,
    review_completion,
    setup_club_with_paid_members,
    setup_member_with_path,
    setup_path_at_level_2_with_level_2_completion,
    setup_path_with_approved_level_1,
    validate_error,
    validate_success,
)
from test_helpers.constants import FIRST_CYCLE_CLOSE_AT, SECOND_CYCLE_OPENED_AT


def _setup_evaluated_level_1_completion() -> tuple:
    """Club + two paid members + LEVEL_1 path holding one EVALUATED speech completion."""
    club, memberships = setup_club_with_paid_members(2, prefix="e")
    officer_ms, evaluator_ms = memberships[0], memberships[1]
    path = create_path(officer_ms["id"], officer_ms["member_id"])
    completion = log_completion(
        path["id"],
        officer_ms["member_id"],
        evaluator_member_id=evaluator_ms["member_id"],
    )
    completion = record_evaluation(completion["id"], evaluator_ms["member_id"])
    return club, officer_ms, path, completion


def _setup_member_with_two_logged_completions() -> tuple:
    """Club + one paid member whose LEVEL_1 path holds two LOGGED completions."""
    club, membership, member_id, path = setup_member_with_path()
    log_completion(path["id"], member_id, project_code="L1-ICE-BREAKER", level=1, speech_minutes=6)
    log_completion(path["id"], member_id, project_code="L1-WRITING-A-SPEECH", level=1, speech_minutes=5)
    return club, membership, member_id, get_path(path["id"])


def _setup_lapsed_member_with_empty_path() -> tuple:
    """Club + one member who paid cycle 0, holds an empty LEVEL_1 path, and lapsed."""
    club = create_organizing_club()
    membership = enroll_membership(club["id"], full_name="Ada Lovelace", email="ada@example.org", pay_dues=True)
    path = create_path(membership["id"], membership["member_id"])
    close_dues_cycle(club["id"], FIRST_CYCLE_CLOSE_AT, FIRST_CYCLE_CLOSE_AT)
    close_dues_cycle(club["id"], SECOND_CYCLE_OPENED_AT, SECOND_CYCLE_OPENED_AT)
    return club, membership, path


def test_level_1_requirement_advances_the_path_to_level_2(api, whq_headers):
    """PRD §3.4: "To leave `LEVEL_1` a path needs at least 2 approved speeches and at
    least 2 approved projects at that level."
    PRD §3.4: "On a successful advance the level moves up exactly one step — `LEVEL_1` to `LEVEL_2` and so on — and `LEVEL_5` becomes `COMPLETED`."

    Design: Difficulty/non_linear_state_machine/education_path_level_advance_and_revert_cycle
    """
    _, membership, member_id, path, _, _ = setup_path_with_approved_level_1()
    assert path["approved_speeches_at_level"] == 2
    assert path["approved_projects_at_level"] == 2

    advanced = validate_success(
        api.advance_level(
            path["id"],
            {"expected_education_path_version": path_version(path["id"])},
            make_member_headers(member_id),
        ),
        200,
    )
    assert advanced["level"] == "LEVEL_2", "the advance moves the path up exactly one step"
    assert advanced["last_advanced_at"] is not None
    assert advanced["version"] > path["version"], "the advance is a mutation of the path"


def test_returned_level_2_completion_reverts_the_path_to_level_1(api, whq_headers):
    """PRD §3.5: "when the returned completion's level equals the path's current level,
    the path itself drops by one step — `LEVEL_2` back to `LEVEL_1`, `LEVEL_3` back to
    `LEVEL_2`, `LEVEL_4` back to `LEVEL_3`, or `LEVEL_5` back to `LEVEL_4` — with
    `level_started_at` reset to the request timestamp."

    Design: Difficulty/non_linear_state_machine/education_path_level_advance_and_revert_cycle
    """
    _, membership, member_id, path, completion, _ = setup_path_at_level_2_with_level_2_completion()
    assert path["level"] == "LEVEL_2", "setup: the path advanced past LEVEL_1"
    assert completion["status"] == "APPROVED"

    returned = validate_success(
        review_completion(
            completion["id"],
            membership["id"],
            "RETURN",
            "Evaluation rubric was not attached to the LEVEL_2 submission",
        ),
        200,
    )
    assert returned["status"] == "RETURNED"
    assert returned["counts_for_level_advancement"] is False

    reverted = get_path(path["id"])
    assert reverted["level"] == "LEVEL_1", "the returned LEVEL_2 completion drops the path one step"
    assert reverted["approved_projects_at_level"] == 2, "the two LEVEL_1 completions now match the level"
    assert reverted["approved_speeches_at_level"] == 2


def test_return_review_recounts_club_level_completions(api, whq_headers):
    """PRD §2.6: "`approved_level_completions_this_cycle` (approved completions at
    this club in the current cycle whose level equals the member's current path
    level)".

    Design: Difficulty/transitive_cascade/return_review_reverts_level_and_recomputes_club_score
    """
    club, membership, member_id, path, completion, _ = setup_path_at_level_2_with_level_2_completion()
    assert get_club(club["id"])["approved_level_completions_this_cycle"] == 1, (
        "only the LEVEL_2 completion matches the path's current level"
    )

    review_completion(
        completion["id"], membership["id"], "RETURN", "Evaluation rubric was not attached"
    )
    assert get_club(club["id"])["approved_level_completions_this_cycle"] == 2, (
        "the revert makes the two LEVEL_1 completions the ones that match"
    )


def test_return_review_recomputes_the_club_good_standing_score(api, whq_headers):
    """PRD §2.7: "The education component is the smaller of 20 and the whole-number
    part of twenty multiplied by `approved_level_completions_this_cycle` and divided
    by four."
    PRD §3.5: "the club's `approved_level_completions_this_cycle`,
    `dcp_recognition_points` and `good_standing_score` are all recomputed."
    PRD §2.6: "Posture is never supplied by a caller and is never flipped by an
    ordinary in-cycle mutation. ... Outside those two situations a club keeps
    whatever posture it was last assigned, even while its score changes
    underneath it."

    Design: Difficulty/transitive_cascade/return_review_reverts_level_and_recomputes_club_score
    """
    club, membership, member_id, path, completion, _ = setup_path_at_level_2_with_level_2_completion()
    before = get_club(club["id"])
    assert before["paid_member_count"] == 1, "the paid roster is the single dues component"
    assert before["approved_level_completions_this_cycle"] == 1
    assert before["good_standing_score"] == 12, "1 dues + 5 education + 6 recognition points"

    review_completion(
        completion["id"], membership["id"], "RETURN", "Evaluation rubric was not attached"
    )
    after = get_club(club["id"])
    assert after["approved_level_completions_this_cycle"] == 2
    assert after["good_standing_score"] == 17, "1 dues + 10 education + 6 recognition points"
    assert after["good_standing"] == "GOOD", (
        "posture only moves at close-cycle, so the score change leaves it where it was"
    )


def test_level_requirement_is_checked_before_the_membership_is(api, whq_headers):
    """PRD §2.10: "Checks are evaluated in a fixed order, and the first check that
    fails determines the response."
    PRD §2.10: "Eleventh, the level requirement table must be satisfied for
    advancement, otherwise `ERR_LEVEL_REQUIREMENTS_NOT_MET`."
    PRD §3.4: "A path that does not meet the requirement for its current level is
    refused with `ERR_LEVEL_REQUIREMENTS_NOT_MET`."

    Design: Difficulty/priority_pair_validation_conflict/level_requirement_check_beats_membership_paid_check
    """
    _, membership, path = _setup_lapsed_member_with_empty_path()
    assert get_membership(membership["id"])["status"] == "LAPSED", "setup: the membership is lapsed"

    response = api.advance_level(
        path["id"],
        {"expected_education_path_version": path_version(path["id"])},
        make_member_headers(membership["member_id"]),
    )
    validate_error(response, ApiErrorId.ERR_LEVEL_REQUIREMENTS_NOT_MET)


def test_failed_level_requirement_leaves_the_level_unchanged(api, whq_headers):
    """PRD §3.4: "A path that does not meet the requirement for its current level is
    refused with `ERR_LEVEL_REQUIREMENTS_NOT_MET`."

    Design: Difficulty/priority_pair_validation_conflict/level_requirement_check_beats_membership_paid_check
    """
    _, membership, path = _setup_lapsed_member_with_empty_path()

    api.advance_level(
        path["id"],
        {"expected_education_path_version": path_version(path["id"])},
        make_member_headers(membership["member_id"]),
    )
    assert get_path(path["id"])["level"] == "LEVEL_1", "a refused advance must not move the level"


def test_approval_raises_the_path_and_club_approved_counters(api, whq_headers):
    """PRD §3.5: "Approval is the moment a completion starts counting.
    `counts_for_level_advancement` becomes true when the completion's level equals the
    path's current level, and the member's `total_speeches_delivered` and
    `highest_level_completed`, the path's two approved counters, and the club's
    `approved_level_completions_this_cycle`, `dcp_recognition_points` and
    `good_standing_score` are all recomputed."

    Design: Difficulty/compensating_invariant/approve_and_return_conserve_path_and_club_counters
    """
    club, officer_ms, path, completion = _setup_evaluated_level_1_completion()
    assert get_path(path["id"])["approved_projects_at_level"] == 0, "before the pair"
    assert get_club(club["id"])["approved_level_completions_this_cycle"] == 0

    approved = approve_completion(completion["id"], officer_ms["id"])
    assert approved["status"] == "APPROVED"
    assert approved["counts_for_level_advancement"] is True

    assert get_path(path["id"])["approved_projects_at_level"] == 1, "after the approval"
    assert get_club(club["id"])["approved_level_completions_this_cycle"] == 1


def test_returning_an_approved_completion_restores_the_counters(api, whq_headers):
    """PRD §3.5: "It clears `counts_for_level_advancement` to false."
    PRD §3.5: "That reversion is itself a mutation of everything the level was supporting: the path's approved counters, the member's `total_speeches_delivered` and `highest_level_completed`, and the club's `approved_level_completions_this_cycle`, `dcp_recognition_points` and `good_standing_score` are all recomputed, and every contest entry belonging to that member through that club is disqualified."

    Design: Difficulty/compensating_invariant/approve_and_return_conserve_path_and_club_counters
    """
    club, officer_ms, path, completion = _setup_evaluated_level_1_completion()
    approve_completion(completion["id"], officer_ms["id"])
    assert get_path(path["id"])["approved_projects_at_level"] == 1

    returned = validate_success(
        review_completion(completion["id"], officer_ms["id"], "RETURN", "Evaluation rubric was not attached"),
        200,
    )
    assert returned["status"] == "RETURNED"
    assert returned["counts_for_level_advancement"] is False
    assert get_path(path["id"])["approved_projects_at_level"] == 0, "the counter returns to its pre-pair value"
    assert get_club(club["id"])["approved_level_completions_this_cycle"] == 0
    assert get_path(path["id"])["level"] == "LEVEL_1", (
        "LEVEL_1 has no revert transition, so the level stays put"
    )


def test_evaluating_an_approved_completion_is_an_invalid_state(api, whq_headers):
    """PRD §3.5: "The completion must be in `LOGGED` or `RETURNED` status, otherwise
    the request is refused with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/evaluation_on_approved_completion_returns_invalid_state
    """
    club, officer_ms, path, completion = _setup_evaluated_level_1_completion()
    approved = approve_completion(completion["id"], officer_ms["id"])
    assert approved["status"] == "APPROVED"
    approved_count = get_path(path["id"])["approved_projects_at_level"]

    response = api.record_evaluation(
        completion["id"],
        {"evaluation_summary": "Second opinion"},
        make_member_headers(completion["evaluator_member_id"]),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE)
    assert get_completion(completion["id"])["status"] == "APPROVED"
    assert get_path(path["id"])["approved_projects_at_level"] == approved_count, (
        "no derived counter may move on a refused evaluation"
    )


def test_logged_completions_do_not_satisfy_the_level_requirement(api, whq_headers):
    """PRD §3.4: "Its `approved_speeches_at_level` counts approved completions on that
    path whose level equals the path's current level and whose `project_kind` is
    `SPEECH`; its `approved_projects_at_level` counts every approved completion on that
    path whose level equals the current level, whatever the kind."
    PRD §3.4: "A path that does not meet the requirement for its current level is
    refused with `ERR_LEVEL_REQUIREMENTS_NOT_MET`."

    Design: Corner/calculations/level_requirements_count_only_approved_completions
    """
    club, membership, member_id, path = _setup_member_with_two_logged_completions()

    assert get_path(path["id"])["approved_projects_at_level"] == 0, (
        "two LOGGED completions are not approved completions"
    )

    response = api.advance_level(
        path["id"],
        {"expected_education_path_version": path_version(path["id"])},
        make_member_headers(member_id),
    )
    validate_error(response, ApiErrorId.ERR_LEVEL_REQUIREMENTS_NOT_MET)
    assert get_path(path["id"])["level"] == "LEVEL_1"


def test_second_enrollment_in_the_same_path_code_is_refused(api, whq_headers):
    """PRD §3.4: "A membership may hold only one path per `path_code`; if it already
    holds one for that code in status `ACTIVE` or `SUSPENDED`, the request is refused
    with `ERR_DUPLICATE_PATH_ENROLLMENT`."

    Design: Corner/validations/duplicate_path_enrollment_rejected
    """
    club, membership, member_id, path = _setup_member_with_two_logged_completions()

    response = api.create_education_path(
        {
            "membership_id": membership["id"],
            "path_code": "DYNAMIC_LEADERSHIP",
            "expected_membership_version": membership_version(membership["id"]),
        },
        make_member_headers(member_id),
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_PATH_ENROLLMENT)
    assert len(list_paths_for_membership(membership["id"])) == 1, (
        "exactly one EducationPath may exist for the membership"
    )


def test_member_cannot_evaluate_their_own_project(api, whq_headers):
    """PRD §3.5: "If the payload names an `evaluator_member_id` equal to the member the
    completion belongs to, the log is refused with `ERR_EVALUATOR_CONFLICT` — a member
    does not evaluate their own project."

    Design: Corner/validations/self_evaluation_rejected
    """
    club, membership, member_id, path = _setup_member_with_two_logged_completions()

    response = api.create_project_completion(
        {
            "path_id": path["id"],
            "project_code": "L1-RESEARCHING-AND-PRESENTING",
            "project_kind": "SPEECH",
            "level": 1,
            "speech_minutes": 6,
            "delivered_at": "2026-09-11T18:30:00Z",
            "evaluator_member_id": member_id,
            "expected_education_path_version": path_version(path["id"]),
        },
        make_member_headers(member_id),
    )
    validate_error(response, ApiErrorId.ERR_EVALUATOR_CONFLICT)
    assert get_path(path["id"])["approved_projects_at_level"] == 0, (
        "the refused log must not create a completion on the path"
    )
