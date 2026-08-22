"""The case-review panel: balloting, the tally, the closing bars and the three
disjoint outcome branches."""
from test_helpers import (
    ApiErrorId,
    assert_case_review,
    assert_case_review_vote,
    assert_seat_ledger,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_a_ballot_before_voting_opens_is_refused(api):
    """PRD §3.9: "Ballots may only be cast, and the panel may only be closed, while it is in `VOTING`; either request against a panel in any other state answers `ERR_CASE_REVIEW_NOT_VOTING` with HTTP 409 at priority 13."

    Design: Corner/errors/ballot_before_voting_opens_returns_case_review_not_voting
    """
    ctx = fixtures.setup_active_placement()
    panel = fixtures.convene_panel(ctx, trigger_reason="REINJURY", quorum_required=3)

    resp = api.cast_case_review_vote(
        panel["id"],
        {"ballot": "CONTINUE", "expected_case_review_version": panel["version"]},
        fixtures.NURSE,
    )

    validate_error(resp, ApiErrorId.ERR_CASE_REVIEW_NOT_VOTING, 409)
    still = validate_success(api.get_case_review(panel["id"], fixtures.NURSE))
    assert still["vote_count"] == 0


def test_the_placement_creator_may_not_cast_a_ballot(api):
    """PRD §3.9: "The segregation-of-duties bar of priority 7 applies here: a principal whose `X-User-ID` equals the placement's `created_by_user_id` may not vote at all, and the attempt answers `ERR_SEGREGATION_OF_DUTIES` with HTTP 403."
    PRD §2.1: "First, a panel ballot may not be cast by the principal whose `X-User-ID` equals the `created_by_user_id` of the placement under review — whoever proposed the assignment does not get a vote on whether it survives."

    Design: Corner/validations/placement_creator_cannot_cast_a_panel_ballot
    """
    ctx = fixtures.setup_active_placement()
    fixtures.convene_panel(ctx, trigger_reason="COMPLIANCE_CRITICAL", quorum_required=3)
    fixtures.open_voting(ctx)
    version = fixtures.current_case_review_version(ctx["case_review_id"])

    resp = api.cast_case_review_vote(
        ctx["case_review_id"],
        {"ballot": "CONTINUE", "expected_case_review_version": version,
         "rationale": "Own placement"},
        fixtures.COORD,
    )

    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)
    panel = validate_success(api.get_case_review(ctx["case_review_id"], fixtures.NURSE))
    assert panel["vote_count"] == 0


def test_a_stale_panel_version_rejects_the_second_ballot(api):
    """PRD §2.7: "Casting a ballot on a case-review panel requires `expected_case_review_version`, carrying the client's last observed `version` of that `CaseReview`. A mismatch with the panel's current `version` is rejected with `ERR_STALE_CASE_REVIEW_VERSION` and HTTP 412."
    PRD §3.9: "Casting recomputes the panel tally and raises the panel's `version` by 1."

    Design: Corner/cross_cutting_layers/stale_case_review_version_rejects_a_second_ballot
    """
    ctx = fixtures.setup_active_placement()
    fixtures.convene_panel(ctx, trigger_reason="REINJURY", quorum_required=3)
    opened = fixtures.open_voting(ctx)
    stale_version = opened["version"]
    fixtures.cast_vote(ctx, "CONTINUE", fixtures.NURSE,
                       expected_case_review_version=stale_version, rationale="First ballot")

    resp = api.cast_case_review_vote(
        ctx["case_review_id"],
        {"ballot": "TERMINATE", "expected_case_review_version": stale_version,
         "rationale": "Stale view"},
        fixtures.ADJUSTER,
    )

    validate_error(resp, ApiErrorId.ERR_STALE_CASE_REVIEW_VERSION, 412)
    panel = validate_success(api.get_case_review(ctx["case_review_id"], fixtures.NURSE))
    assert panel["vote_count"] == 1
    assert panel["continue_votes"] == 1


def test_a_members_second_ballot_supersedes_their_first(api):
    """PRD §3.9: "New ballots land with `vote_status` `COUNTED`. A member may change their mind: casting a second ballot flips that same member's prior `COUNTED` row to `SUPERSEDED`, so each member contributes at most one counted ballot."
    PRD §3.9: "Recomputed on every ballot and again at closing, the tally considers only rows whose `vote_status` is `COUNTED`; `SUPERSEDED` rows are excluded from every count."

    Design: Corner/cross_cutting_layers/revote_by_the_same_member_supersedes_the_prior_ballot
    """
    ctx = fixtures.setup_active_placement()
    fixtures.convene_panel(ctx, trigger_reason="REINJURY", quorum_required=3)
    opened = fixtures.open_voting(ctx)
    first = fixtures.cast_vote(ctx, "CONTINUE", fixtures.NURSE,
                               expected_case_review_version=opened["version"],
                               rationale="Initial view")

    second = fixtures.cast_vote(ctx, "TERMINATE", fixtures.NURSE, rationale="Revised view")

    assert_case_review_vote(second)
    assert second["vote_status"] == "COUNTED"
    votes, _ = validate_paginated(
        api.list_case_review_votes(ctx["case_review_id"], fixtures.NURSE)
    )
    assert len(votes) == 2, "both rows remain on the ledger"
    superseded = next(v for v in votes if v["id"] == first["id"])
    assert superseded["vote_status"] == "SUPERSEDED"
    panel = validate_success(api.get_case_review(ctx["case_review_id"], fixtures.NURSE))
    assert panel["vote_count"] == 1
    assert panel["continue_votes"] == 0
    assert panel["terminate_votes"] == 1


def test_closing_below_quorum_is_refused(api):
    """PRD §3.9: "Closing is performed by a nurse or administrator and requires four things at once: the panel must be in `VOTING`; its `vote_count` must be at least its `quorum_required`, or the request answers `ERR_QUORUM_NOT_MET` with HTTP 409 at priority 34"

    Design: Corner/validations/close_below_quorum_is_rejected
    """
    ctx = fixtures.setup_voting_panel(ballots=("CONTINUE", "CONTINUE"), quorum_required=3)

    resp = api.close_case_review(ctx["case_review_id"], fixtures.ADMIN)

    validate_error(resp, ApiErrorId.ERR_QUORUM_NOT_MET, 409)
    panel = validate_success(api.get_case_review(ctx["case_review_id"], fixtures.NURSE))
    assert panel["vote_count"] == 2
    assert panel["review_status"] == "VOTING"


def test_a_tied_tally_resolves_to_the_most_conservative_ballot(api):
    """PRD §3.9: "The `winning_ballot` is the option attaining the greatest of those three counts; when two or three of them tie at that greatest count, the more conservative option wins, with `TERMINATE` beating `MODIFY` and `MODIFY` beating `CONTINUE`. The `decision_ratio` is that greatest count divided by `vote_count`, rounded half up to four decimal places."
    PRD §3.9: "its `decision_ratio` must be at least the majority bar of 0.6600, or the request answers `ERR_MAJORITY_NOT_REACHED` with HTTP 409 at priority 35 — a ratio exactly equal to 0.6600 passes"

    Design: Corner/calculations/case_review_tie_breaks_to_the_most_conservative_ballot
    """
    ctx = fixtures.setup_voting_panel(
        ballots=("CONTINUE", "CONTINUE", "TERMINATE", "TERMINATE"), quorum_required=3
    )

    panel = validate_success(api.get_case_review(ctx["case_review_id"], fixtures.NURSE))
    assert_case_review(panel)
    assert panel["vote_count"] == 4
    assert panel["continue_votes"] == 2
    assert panel["terminate_votes"] == 2
    assert panel["winning_ballot"] == "TERMINATE"
    assert panel["decision_ratio"] == 0.5

    resp = api.close_case_review(ctx["case_review_id"], fixtures.ADMIN)

    validate_error(resp, ApiErrorId.ERR_MAJORITY_NOT_REACHED, 409)
    still = validate_success(api.get_case_review(ctx["case_review_id"], fixtures.NURSE))
    assert still["review_status"] == "VOTING"


def test_two_of_three_clears_the_majority_bar_and_closes_on_continue(api):
    """PRD §3.9: "A `CONTINUE` win moves the panel `VOTING → DECIDED_CONTINUE` and, when the placement is sitting on hold, returns it `PROGRESSION_HOLD → ACTIVE`; nothing about the schedule changes."
    PRD §3.9: "its `decision_ratio` must be at least the majority bar of 0.6600, or the request answers `ERR_MAJORITY_NOT_REACHED` with HTTP 409 at priority 35 — a ratio exactly equal to 0.6600 passes"

    Design: Corner/calculations/case_review_two_of_three_ratio_meets_majority_exactly
    """
    ctx = fixtures.setup_voting_panel(ballots=("CONTINUE", "CONTINUE", "MODIFY"))

    closed = validate_success(
        api.close_case_review(ctx["case_review_id"], fixtures.NURSE2)
    )

    assert closed["decision_ratio"] == 0.6667
    assert closed["winning_ballot"] == "CONTINUE"
    assert closed["review_status"] == "DECIDED_CONTINUE"
    placement = validate_success(api.get_placement(ctx["placement_id"], fixtures.COORD))
    assert placement["placement_status"] == "ACTIVE"
    claim = validate_success(api.get_claim(ctx["claim_id"], fixtures.COORD))
    assert claim["rtw_posture"] == "OPEN"


def test_a_member_who_voted_may_not_close_the_panel(api):
    """PRD §2.1: "Second, a panel may not be closed by a principal whose `X-User-ID` appears as the `voter_user_id` of any `COUNTED` ballot on that panel."
    PRD §3.9: "the closing principal's `X-User-ID` must not be the `voter_user_id` of any counted ballot on the panel, or the request answers `ERR_SEGREGATION_OF_DUTIES`. Every close stamps `closed_by_user_id`, recomputes the claim's `rtw_posture`, and raises the panel's `version` by 1."

    Design: Corner/validations/panel_voter_cannot_close_the_same_panel
    """
    ctx = fixtures.setup_voting_panel(ballots=("CONTINUE", "CONTINUE", "CONTINUE"))

    refused = api.close_case_review(ctx["case_review_id"], fixtures.NURSE)
    validate_error(refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)

    closed = validate_success(api.close_case_review(ctx["case_review_id"], fixtures.NURSE2))
    assert closed["review_status"] == "DECIDED_CONTINUE"
    assert closed["closed_by_user_id"] == "nurse-2"


def test_a_terminate_win_ends_the_assignment_and_releases_the_seat(api):
    """PRD §3.9: "A `TERMINATE` win moves the panel `VOTING → DECIDED_TERMINATE` and ends the assignment: the placement moves to `TERMINATED_EARLY` with `ended_on` set to the clock's calendar date, the job's `filled_seats` drops by 1, every live directive of the placement flips to `SUPERSEDED`, `benefit_continuation_status` becomes `LAPSED`, and the claim's `cumulative_transitional_days` and `rtw_posture` are recomputed."

    Design: Corner/state_machines/case_review_terminate_branch_ends_placement_and_releases_seat
    """
    ctx = fixtures.setup_active_placement()
    fixtures.set_clock("2026-08-10T00:00:00Z")
    fixtures.setup_voting_panel(
        ctx=ctx, ballots=("TERMINATE", "TERMINATE", "TERMINATE"), quorum_required=3
    )

    closed = validate_success(api.close_case_review(ctx["case_review_id"], fixtures.ADMIN))

    assert closed["review_status"] == "DECIDED_TERMINATE"
    assert closed["vote_count"] == 3
    assert closed["decision_ratio"] == 1.0
    assert closed["winning_ballot"] == "TERMINATE"
    placement = validate_success(api.get_placement(ctx["placement_id"], fixtures.COORD))
    assert placement["placement_status"] == "TERMINATED_EARLY"
    assert placement["ended_on"] == "2026-08-10"
    assert placement["benefit_continuation_status"] == "LAPSED"
    job = validate_success(api.get_transitional_job(ctx["job_id"], fixtures.COORD))
    assert_seat_ledger(job, 0)


def test_a_modify_win_halves_the_schedule_and_forks_a_follow_up_review(api):
    """PRD §3.9: "A `MODIFY` win moves the panel `VOTING → DECIDED_MODIFY` and leaves `placement_status` exactly where it is, but cuts the workload: the placement's `scheduled_hours_per_day` becomes the greater of 1 and the current `scheduled_hours_per_day` multiplied by one half and rounded down to a whole number, after which the placement's `match_score`, `projected_weekly_cost_cents` and `SURVEILLANCE` `reinjury_risk_score` are all recomputed, and a follow-up review is forked with `review_status` `SCHEDULED`, `step_index` one greater than the greatest `step_index` among that placement's existing reviews, and a `due_date` 14 days after the logical clock's calendar date."

    Design: Corner/state_machines/case_review_modify_branch_halves_schedule_and_forks_followup_review
    """
    ctx = fixtures.setup_active_placement()
    fixtures.set_clock("2026-08-10T00:00:00Z")
    fixtures.setup_voting_panel(
        ctx=ctx, ballots=("MODIFY", "MODIFY", "MODIFY"), quorum_required=3,
        trigger_reason="REINJURY",
    )

    closed = validate_success(api.close_case_review(ctx["case_review_id"], fixtures.NURSE2))

    assert closed["review_status"] == "DECIDED_MODIFY"
    assert closed["winning_ballot"] == "MODIFY"
    placement = validate_success(api.get_placement(ctx["placement_id"], fixtures.COORD))
    assert placement["placement_status"] == "ACTIVE", "the lifecycle dimension does not move"
    assert placement["scheduled_hours_per_day"] == 2, "4 hours halved and floored"
    assert placement["current_progression_review_id"] is not None
    reviews, _ = validate_paginated(
        api.list_placement_progression_reviews(
            ctx["placement_id"], fixtures.COORD, params={"review_status": "SCHEDULED"}
        )
    )
    assert len(reviews) == 2
    assert reviews[1]["step_index"] == 2
    assert reviews[1]["due_date"] == "2026-08-24", (
        "14 days after the logical clock's 2026-08-10 calendar date"
    )
