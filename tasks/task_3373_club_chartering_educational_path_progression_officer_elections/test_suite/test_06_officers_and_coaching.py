"""Officer elections, district training and the ranked coaching queue."""
from test_helpers import (
    ApiErrorId,
    approve_completion,
    close_dues_cycle,
    create_meeting,
    create_path,
    elect_officer,
    get_club,
    get_membership,
    get_success_data,
    get_term,
    hold_quorate_meeting,
    hold_meeting,
    log_completion,
    make_district_director_headers,
    nominate_officer,
    record_evaluation,
    setup_club_with_officer,
    setup_club_with_paid_members,
    setup_elected_officer,
    setup_judge_member,
    train_officer,
    validate_error,
)
from test_helpers.constants import MEETING_AT

OFFICER_OFFICES = ["PRESIDENT", "VP_EDUCATION", "VP_MEMBERSHIP", "VP_PUBLIC_RELATIONS"]


def _setup_distinguished_club() -> tuple:
    """20 paid members, three approved completions, four trained officers, one meeting."""
    club, memberships = setup_club_with_paid_members(20, prefix="o")
    officer_ms = memberships[0]
    evaluator_member_id = memberships[4]["member_id"]

    for index in range(3):
        path = create_path(memberships[index]["id"], memberships[index]["member_id"])
        completion = log_completion(
            path["id"],
            memberships[index]["member_id"],
            project_code=f"L1-PROJECT-{index}",
            level=1,
            evaluator_member_id=evaluator_member_id,
        )
        record_evaluation(completion["id"], evaluator_member_id)
        approve_completion(completion["id"], officer_ms["id"])

    terms = [
        nominate_officer(club["id"], officer_ms["id"], memberships[index]["member_id"], office)
        for index, office in enumerate(OFFICER_OFFICES)
    ]
    hold_quorate_meeting(club["id"], officer_ms["id"], [ms["member_id"] for ms in memberships[:6]])
    elected = [get_success_data(elect_officer(term["id"], officer_ms["id"]), 200) for term in terms]

    _, director_member_id = setup_judge_member(prefix="o-dir")
    for term in elected:
        get_success_data(train_officer(term["id"], director_member_id), 200)
    return get_club(club["id"]), memberships


def test_election_refused_without_a_quorate_meeting_after_nomination(api, whq_headers):
    """PRD §3.7: "The club must have held at least one meeting with `quorum_met` true
    whose `held_at` falls after this term's `nominated_at` — an election needs a quorum
    that postdates the nomination, and a missing or stale quorum produces
    `ERR_ELECTION_QUORUM_NOT_MET`."

    Design: Difficulty/cross_entity_state_dependency/officer_election_requires_held_quorum_meeting
    """
    club, membership, member_id = setup_club_with_officer()
    term = nominate_officer(club["id"], membership["id"], member_id, "PRESIDENT")
    create_meeting(club["id"], membership["id"], scheduled_at=MEETING_AT)

    response = elect_officer(term["id"], membership["id"])
    validate_error(response, ApiErrorId.ERR_ELECTION_QUORUM_NOT_MET)


def test_election_succeeds_once_a_quorate_meeting_is_held(api, whq_headers):
    """PRD §3.7: "A successful election stamps `elected_at` with the request timestamp
    and sets `training_due_at` to exactly 30 days after `elected_at`."
    PRD §3.7: "A member's `officer_role` mirrors the office they currently hold, derived from the `ELECTED` or `TRAINED` term standing at that club, and is `NONE` when they hold none."

    Design: Difficulty/cross_entity_state_dependency/officer_election_requires_held_quorum_meeting
    """
    club, membership, member_id = setup_club_with_officer()
    term = nominate_officer(club["id"], membership["id"], member_id, "PRESIDENT")
    meeting = create_meeting(club["id"], membership["id"], scheduled_at=MEETING_AT)
    hold_meeting(meeting["id"], membership["id"], [member_id])

    elected = get_success_data(elect_officer(term["id"], membership["id"]), 200)
    assert elected["status"] == "ELECTED"
    assert elected["elected_at"] is not None
    assert elected["training_due_at"] is not None
    assert get_membership(membership["id"])["officer_role"] == "PRESIDENT"


def test_recognition_points_with_four_trained_officers(api, whq_headers):
    """PRD §2.7: "A club's recognition points, `dcp_recognition_points`, are a separate ten-point aggregate assembled from four sources, and they are evaluated before the standing score and independently of it."
    PRD §2.7: "A club with at least 9 points is `PRESIDENT_DISTINGUISHED`; 7 or 8
    points is `SELECT_DISTINGUISHED`; 5 or 6 points is `DISTINGUISHED`; and fewer than
    5 points is `NONE`."

    Design: Difficulty/combinatorial_formula/dcp_points_nested_minmax_over_four_inputs
    """
    club, _ = _setup_distinguished_club()

    closed = close_dues_cycle(club["id"], "2027-01-01T00:00:00Z", "2027-01-01T00:00:00Z")
    assert closed["dcp_recognition_points"] == 7, (
        "education 3 + membership 2 + training 1 + admin 1, capped at 10"
    )
    assert closed["dcp_tier"] == "SELECT_DISTINGUISHED"


def test_standing_score_with_four_trained_officers(api, whq_headers):
    """PRD §2.7: "The dues component is the smaller of 30 and the whole-number part of
    thirty multiplied by `paid_member_count` and divided by twenty. The officer
    component is the smaller of 25 and the whole-number part of twenty-five multiplied
    by `officer_trained_count` and divided by four."

    Design: Difficulty/combinatorial_formula/dcp_points_nested_minmax_over_four_inputs
    """
    club, _ = _setup_distinguished_club()

    closed = close_dues_cycle(club["id"], "2027-01-01T00:00:00Z", "2027-01-01T00:00:00Z")
    assert closed["officer_trained_count"] == 4
    assert closed["paid_member_count"] == 20
    assert closed["good_standing_score"] == 82, (
        "30 dues + 25 officer + 15 education + 2 meeting + 10 recognition points"
    )


def test_recognition_points_use_the_cycle_open_snapshot(api, whq_headers):
    """PRD §2.7: "First, `dcp_recognition_points` is always evaluated before
    `good_standing_score`, and it uses the `cycle_open_standing` snapshot captured when
    the cycle opened rather than the live posture; the score is then computed from
    those points, and the score computed in a cycle never feeds back into that same
    cycle's recognition points."

    Design: Difficulty/combinatorial_formula/good_standing_circular_order_pinned_to_cycle_open_snapshot
    """
    club, _ = setup_club_with_paid_members(20, prefix="g")

    closed = close_dues_cycle(club["id"], "2027-01-01T00:00:00Z", "2027-01-01T00:00:00Z")
    assert closed["dcp_recognition_points"] == 3, (
        "education 0 + membership 2 + training 0 + admin 1 for the GOOD cycle-open snapshot"
    )
    assert closed["good_standing_score"] == 36, "30 dues + 6 points from 3 recognition points"


def test_low_scoring_organizing_club_keeps_its_charter_status(api, whq_headers):
    """PRD §3.2: "A club still in `ORGANIZING` keeps its `charter_status` through the
    close — a low score neither suspends nor revokes a club that has not yet been
    chartered."
    PRD §3.2: "`cycle_open_standing` becomes the `good_standing` derived in step three."

    Design: Difficulty/combinatorial_formula/good_standing_circular_order_pinned_to_cycle_open_snapshot
    """
    club, _ = setup_club_with_paid_members(20, prefix="g")

    closed = close_dues_cycle(club["id"], "2027-01-01T00:00:00Z", "2027-01-01T00:00:00Z")
    assert closed["good_standing"] == "NOT_IN_GOOD_STANDING", "a score of 36 is strictly below 60"
    assert closed["charter_status"] == "ORGANIZING", "an un-chartered club is never suspended or revoked"
    assert closed["cycle_open_standing"] == "NOT_IN_GOOD_STANDING", (
        "the snapshot for the cycle that follows is the posture derived in step three"
    )


def test_coaching_queue_with_no_candidates_is_not_found(api, whq_headers):
    """PRD §3.9: "Asking for the next club to coach when no club qualifies is refused
    with `ERR_NO_COACHING_CANDIDATES`."

    Design: Corner/calculations/coaching_queue_empty_pool_returns_not_found
    """
    club, membership, member_id = setup_club_with_officer()
    assert get_club(club["id"])["good_standing"] == "GOOD"

    response = api.get_coaching_queue(make_district_director_headers(member_id))
    validate_error(response, ApiErrorId.ERR_NO_COACHING_CANDIDATES)


def test_district_director_cannot_train_their_own_term(api, whq_headers):
    """PRD §2.1: "recording officer training requires that `X-User-ID` differs from the `member_id` of the term being trained, and completing a governance visit requires that `X-User-ID` equals that visit's `director_member_id`."

    Design: Corner/rbac/district_director_cannot_train_own_term
    """
    club, membership, member_id = setup_club_with_officer()
    term = setup_elected_officer(club["id"], membership["id"], member_id, "PRESIDENT")
    assert term["status"] == "ELECTED"

    response = train_officer(term["id"], member_id)
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED)

    after = get_term(term["id"])
    assert after["status"] == "ELECTED", "the refused training must not move the term"
    assert after["trained_at"] is None
