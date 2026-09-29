"""Who may call what: the exclusive writes each role keeps to itself, the two header
rules in front of every request, the reads all eight roles share, and the two
identity rules that turn on the calling user rather than the role.
"""
import pytest
from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.test_users import (
    APPEAL_REVIEWER_USER_ID,
    GRADER_USER_ID,
    READER_HEADERS_BY_ROLE,
    UNDECLARED_ROLE,
    headers_with_empty_user_id,
    make_official_headers,
    make_role_headers,
)


# ─── Each role's exclusive writes ──────────────────────

@pytest.fixture
def played_game_with_a_booth():
    """A PLAYED one-official game with Dan's assignment COMPLETED, plus a registered
    replay booth, so every cross-role attempt below is otherwise well-formed."""
    ctx = fx.played_solo_game()
    ctx["station"] = fx.register_station()
    return ctx


def test_each_role_is_refused_the_other_roles_exclusive_write(
    played_game_with_a_booth,
):
    """Five well-formed writes aimed at the wrong endpoint for the caller's role are
    all refused on the header alone — including the pool report whose cited grade
    does not even exist, which still reports the role failure rather than a
    not-found.

    PRD §2.1: "If `X-User-Role` is not one of the eight declared role names below, or
    if it is a declared role that is not authorized for the endpoint being called,
    the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/cross_role_writes_are_rejected_with_unauthorized
    """
    game_id = played_game_with_a_booth["game"]["id"]
    official_id = played_game_with_a_booth["official"]["id"]
    program_id = played_game_with_a_booth["program"]["id"]

    attempts = [
        api_client.create_play_grade(
            f.play_grade_payload(
                game_id, official_id, "Q1-P05", "HOLDING", "CORRECT", "LOW"
            ),
            fx.SCHEDULER,
        ),
        api_client.create_crew_assignment(
            f.crew_assignment_payload(
                game_id, official_id, "REFEREE", played_game_with_a_booth["game"]["version"]
            ),
            fx.GRADER,
        ),
        api_client.create_replay_review(
            f.replay_review_payload(
                game_id,
                played_game_with_a_booth["station"]["id"],
                play_ref="Q1-P05",
                category="TURNOVER",
            ),
            fx.TRAINING,
        ),
        api_client.create_pool_report(
            f.pool_report_payload(
                game_id, game_id, body="Wrong role attempting a public statement."
            ),
            fx.DIRECTOR,
        ),
        api_client.create_official(
            f.official_payload(
                program_id,
                full_name="Sneaky Hire",
                position="UMPIRE",
                seasons_experience=3,
                home_market_code="PHI",
            ),
            fx.COMMUNICATIONS,
        ),
    ]

    for response in attempts:
        validate_error(response, "ERR_UNAUTHORIZED", 403)


def test_none_of_those_refusals_left_a_trace(played_game_with_a_booth):
    """After the five refusals the game still holds its single assignment, and no
    grade, review or report was written.

    PRD §2.9: "`X-User-Role` names one of the eight declared roles and that role is
    authorized for the target endpoint, else `ERR_UNAUTHORIZED` (403)."

    Design: Corner/rbac/cross_role_writes_are_rejected_with_unauthorized
    """
    game_id = played_game_with_a_booth["game"]["id"]

    validate_error(
        api_client.create_play_grade(
            f.play_grade_payload(
                game_id,
                played_game_with_a_booth["official"]["id"],
                "Q1-P05",
                "HOLDING",
                "CORRECT",
                "LOW",
            ),
            fx.SCHEDULER,
        ),
        "ERR_UNAUTHORIZED",
        403,
    )
    validate_error(
        api_client.create_pool_report(
            f.pool_report_payload(
                game_id, game_id, body="Wrong role attempting a public statement."
            ),
            fx.DIRECTOR,
        ),
        "ERR_UNAUTHORIZED",
        403,
    )

    assignments, assignment_meta = validate_paginated(
        api_client.list_crew_assignments(fx.DIRECTOR, {"game_id": game_id})
    )
    grades, grade_meta = validate_paginated(
        api_client.list_play_grades(fx.GRADER, {"game_id": game_id})
    )
    reviews, review_meta = validate_paginated(
        api_client.list_replay_reviews(fx.REPLAY, {"game_id": game_id})
    )
    reports, report_meta = validate_paginated(
        api_client.list_pool_reports(fx.COMMUNICATIONS, {"game_id": game_id})
    )

    assert assignment_meta["total_count"] == 1
    assert assignments[0]["id"] == played_game_with_a_booth["assignment"]["id"]
    assert grades == [] and grade_meta["total_count"] == 0
    assert reviews == [] and review_meta["total_count"] == 0
    assert reports == [] and report_meta["total_count"] == 0


# ─── The two header rules ──────────────────────────────

@pytest.fixture
def one_registered_candidate():
    """An OPEN program holding Dan Ruiz as a CANDIDATE, so an authenticated read
    would return data."""
    program = fx.create_open_program()
    return {"program": program, "official": fx.register_official(program["id"])}


def test_an_empty_identity_is_unauthenticated_and_outranks_the_role_check(
    one_registered_candidate,
):
    """An empty `X-User-ID` is treated as missing rather than as an anonymous caller,
    an undeclared role name is a role failure, and a request that is wrong on both
    counts reports the authentication failure.

    PRD §2.1: "If either header is absent or empty, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_or_undeclared_identity_headers_are_rejected
    """
    validate_error(
        api_client.list_officials(headers_with_empty_user_id("OfficiatingDirector")),
        "ERR_UNAUTHENTICATED",
        401,
    )
    validate_error(
        api_client.list_officials(make_role_headers("intern-1", UNDECLARED_ROLE)),
        "ERR_UNAUTHORIZED",
        403,
    )
    validate_error(
        api_client.list_officials(headers_with_empty_user_id(UNDECLARED_ROLE)),
        "ERR_UNAUTHENTICATED",
        401,
    )


def test_the_same_rules_guard_a_write_and_the_official_bound_read(
    one_registered_candidate,
):
    """A training record filed without an identity is refused and writes nothing,
    while the same official's own read succeeds once both headers are present.

    PRD §2.1: "When `X-User-Role` is `Official`, `X-User-ID` is the `id` of the acting
    Official row; ownership checks on any resource that references an Official compare
    the resource's official reference to `X-User-ID`."

    Design: Corner/rbac/missing_or_undeclared_identity_headers_are_rejected
    """
    official_id = one_registered_candidate["official"]["id"]

    validate_error(
        api_client.create_training_record(
            official_id,
            f.rules_clinic_payload("CL-NOAUTH"),
            headers_with_empty_user_id("TrainingCoordinator"),
        ),
        "ERR_UNAUTHENTICATED",
        401,
    )

    rows, meta = validate_paginated(
        api_client.list_training_records(official_id, fx.TRAINING)
    )

    assert rows == []
    assert meta["total_count"] == 0
    assert (
        fx.read_official(official_id, make_official_headers(official_id))["status"]
        == "CANDIDATE"
    )


# ─── No hierarchy above the exclusive write ────────────

def test_the_director_cannot_file_training_and_the_coordinator_cannot_hire(
    one_registered_candidate,
):
    """Seniority is not authority here: the director who owns the program lifecycle
    is refused the training record, and the coordinator who owns training is refused
    the registration.

    PRD §2.1: "A `TrainingCoordinator` runs rules clinics, physical standards testing
    and preseason exams, and records the results that gate assignability."

    Design: Corner/rbac/training_records_are_the_training_coordinators_alone
    """
    validate_error(
        api_client.create_training_record(
            one_registered_candidate["official"]["id"],
            f.rules_exam_payload(91.00, "EX-DIR"),
            fx.DIRECTOR,
        ),
        "ERR_UNAUTHORIZED",
        403,
    )
    validate_error(
        api_client.create_official(
            f.official_payload(
                one_registered_candidate["program"]["id"],
                full_name="Coordinator Hire",
                position="REFEREE",
                seasons_experience=5,
                home_market_code="PHI",
            ),
            fx.TRAINING,
        ),
        "ERR_UNAUTHORIZED",
        403,
    )


def test_the_identical_payload_succeeds_for_the_coordinator_and_reads_are_shared(
    one_registered_candidate,
):
    """The same exam the director was refused is accepted from the coordinator and
    passes the exam floor, and the director may read it back — the only row there is,
    since the refused attempt wrote nothing.

    PRD §2.1: "An `OfficiatingDirector` runs the department: season configuration and
    closure, official registration, game scheduling and the game lifecycle, committee
    decisions on advancement, the replay station registry, and the entire discipline
    and remediation surface."

    Design: Corner/rbac/training_records_are_the_training_coordinators_alone
    """
    official_id = one_registered_candidate["official"]["id"]

    validate_error(
        api_client.create_training_record(
            official_id, f.rules_exam_payload(91.00, "EX-DIR"), fx.DIRECTOR
        ),
        "ERR_UNAUTHORIZED",
        403,
    )
    accepted = fx.add_training_record(
        official_id, f.rules_exam_payload(91.00, "EX-TC")
    )
    rows, meta = validate_paginated(
        api_client.list_training_records(official_id, fx.DIRECTOR)
    )

    assert accepted["passed"] is True
    assert meta["total_count"] == 1
    assert rows[0]["id"] == accepted["id"]
    assert rows[0]["session_code"] == "EX-TC"


# ─── The reads every role shares ───────────────────────

def test_all_eight_roles_read_the_same_officials_list(one_registered_candidate):
    """Every declared role, the entity-backed `Official` included, gets the identical
    single-row page back from the same filtered read.

    PRD §4: "In the Authorized Role(s) column, "Any" means all eight declared
    roles."

    Design: Corner/rbac/every_declared_role_may_read_the_officials_list
    """
    official_id = one_registered_candidate["official"]["id"]
    program_id = one_registered_candidate["program"]["id"]

    assert len(READER_HEADERS_BY_ROLE) == 8

    for role, reader_headers in READER_HEADERS_BY_ROLE.items():
        headers = (
            make_official_headers(official_id) if role == "Official" else reader_headers
        )
        rows, meta = validate_paginated(
            api_client.list_officials(headers, {"season_program_id": program_id})
        )

        assert meta["total_count"] == 1, f"{role} saw {meta['total_count']} rows"
        assert rows[0]["id"] == official_id, f"{role} saw a different projection"
        assert rows[0]["full_name"] == "Dan Ruiz"
        assert rows[0]["status"] == "CANDIDATE"


# ─── Segregation of duties is per user ─────────────────

@pytest.fixture
def appeal_against_a_grade_this_supervisor_authored():
    """Dan's appeal against the POSTED grade that the grading supervisor
    sup-grader-1 authored and posted."""
    ctx = fx.posted_grade_for_appeal()
    ctx["appeal"] = fx.file_appeal(ctx["grade"]["id"], ctx["official"]["id"])
    return ctx


def test_the_author_of_the_grade_may_not_take_the_appeal_under_review(
    appeal_against_a_grade_this_supervisor_authored,
):
    """The grade records its author, that same user is refused the review, and a
    different supervisor in the very same role takes it under review.

    PRD §2.1: "Those three recorded identifiers exist so that the
    segregation-of-duties rule can be enforced: a `GradingSupervisor` whose
    `X-User-ID` equals the `graded_by_user_id` of the graded play may neither take the
    appeal under review nor decide it, and both attempts are rejected with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/rbac/the_grader_may_not_review_or_decide_the_appeal
    """
    appeal_id = appeal_against_a_grade_this_supervisor_authored["appeal"]["id"]
    grade = fx.read_grade(appeal_against_a_grade_this_supervisor_authored["grade"]["id"])

    assert grade["graded_by_user_id"] == GRADER_USER_ID

    validate_error(
        api_client.start_appeal_review(appeal_id, fx.GRADER),
        "ERR_SEGREGATION_OF_DUTIES",
        403,
    )

    under_review = fx.start_appeal_review(appeal_id)

    assert under_review["status"] == "UNDER_REVIEW"


def test_the_author_may_not_decide_it_either_but_his_colleague_may(
    appeal_against_a_grade_this_supervisor_authored,
):
    """The same refusal guards the decision, the second supervisor's UPHELD decision
    is recorded against his own identifier, and upholding leaves the grade's code and
    error points exactly as they were.

    PRD §3.7: "**`UPHELD`** leaves `grade_code` and `error_points` exactly as they
    were; the season-record recompute still runs, and simply produces the same
    numbers."

    Design: Corner/rbac/the_grader_may_not_review_or_decide_the_appeal
    """
    appeal_id = appeal_against_a_grade_this_supervisor_authored["appeal"]["id"]
    fx.start_appeal_review(appeal_id)

    validate_error(
        api_client.decide_grade_appeal(
            appeal_id,
            {"outcome": "UPHELD", "decision_note": "self-review attempt"},
            fx.GRADER,
        ),
        "ERR_SEGREGATION_OF_DUTIES",
        403,
    )

    decided = fx.decide_appeal(
        appeal_id, "UPHELD", decision_note="the call stands on tape"
    )
    grade = fx.read_grade(appeal_against_a_grade_this_supervisor_authored["grade"]["id"])

    assert decided["status"] == "UPHELD"
    assert decided["decided_by_user_id"] == APPEAL_REVIEWER_USER_ID
    assert grade["appeal_state"] == "APPEAL_RESOLVED"
    assert grade["grade_code"] == "MISSED_CALL"
    assert grade["error_points"] == 0.75


# ─── Ownership guards the withdrawal too ───────────────

@pytest.fixture
def dans_appeal_and_an_unrelated_official():
    """Dan's SUBMITTED appeal, which has left him two credits, and Rita Vance, an
    official with no relationship to the graded play."""
    ctx = fx.posted_grade_for_appeal()
    ctx["other_official"] = fx.register_referee(ctx["program"]["id"], cleared=False)
    ctx["appeal"] = fx.file_appeal(ctx["grade"]["id"], ctx["official"]["id"])
    return ctx


def test_another_official_cannot_withdraw_the_appeal(
    dans_appeal_and_an_unrelated_official,
):
    """Rita is a legitimate `Official`, but the appealed grade is not hers, so her
    withdrawal is refused and the appeal is untouched.

    PRD §2.1: "Concretely, when an `Official` files or withdraws a grade appeal, the
    server compares `X-User-ID` to the `official_id` of the appealed play grade, and
    rejects a mismatch with `ERR_NOT_GRADE_OWNER` (HTTP 403)."

    Design: Corner/rbac/another_official_cannot_withdraw_someone_elses_appeal
    """
    appeal_id = dans_appeal_and_an_unrelated_official["appeal"]["id"]

    validate_error(
        api_client.withdraw_grade_appeal(
            appeal_id,
            make_official_headers(
                dans_appeal_and_an_unrelated_official["other_official"]["id"]
            ),
        ),
        "ERR_NOT_GRADE_OWNER",
        403,
    )

    assert fx.read_appeal(appeal_id, fx.GRADER)["status"] == "SUBMITTED"
    assert (
        fx.read_official(dans_appeal_and_an_unrelated_official["official"]["id"])[
            "appeal_credits_remaining"
        ]
        == 2
    )


def test_the_owner_withdraws_it_and_gets_the_credit_back(
    dans_appeal_and_an_unrelated_official,
):
    """Dan's own withdrawal succeeds, releases the grade from its pending appeal and
    restores his third credit.

    PRD §3.7: "Withdrawing an appeal credits one back, because a withdrawn appeal
    leaves the consuming set."

    Design: Corner/rbac/another_official_cannot_withdraw_someone_elses_appeal
    """
    official_id = dans_appeal_and_an_unrelated_official["official"]["id"]

    withdrawn = fx.withdraw_appeal(
        dans_appeal_and_an_unrelated_official["appeal"]["id"], official_id
    )
    grade = fx.read_grade(dans_appeal_and_an_unrelated_official["grade"]["id"])

    assert withdrawn["status"] == "WITHDRAWN"
    assert grade["appeal_state"] == "NOT_APPEALED"
    assert fx.read_official(official_id)["appeal_credits_remaining"] == 3
