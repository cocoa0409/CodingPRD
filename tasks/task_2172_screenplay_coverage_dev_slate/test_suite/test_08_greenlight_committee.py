"""The greenlight committee: weighted ballots, the tally ladder and the veto."""

from test_helpers import (
    ADMIN,
    ApiErrorId,
    assert_committee_vote,
    assert_greenlight_review,
    cast_vote,
    convene_review,
    fetch_member,
    fetch_project,
    fetch_property,
    fetch_review,
    make_committee_member_headers,
    patch_member,
    seat_committee,
    set_clock,
    setup_development_pipeline,
    setup_review_in_voting,
    validate_error,
    validate_paginated,
    validate_success,
)

FOUR_SEAT_COMMITTEE = (
    {"display_name": "M1 Chair", "vote_weight_bps": 3000, "veto_power": False},
    {"display_name": "M2 Marketing", "vote_weight_bps": 3000, "veto_power": False},
    {"display_name": "M3 Finance", "vote_weight_bps": 3000, "veto_power": False},
    {"display_name": "M4 Physical Production", "vote_weight_bps": 1000,
     "veto_power": False},
)

THREE_SEAT_COMMITTEE = (
    {"display_name": "M1 Chair", "vote_weight_bps": 3000, "veto_power": False},
    {"display_name": "M2 Marketing", "vote_weight_bps": 3000, "veto_power": False},
    {"display_name": "M3 Finance", "vote_weight_bps": 4000, "veto_power": False},
)


# ==========================================================================
# The fork-join close and its veto branch
# ==========================================================================


def _vetoed_review():
    set_clock("2026-09-01T00:00:00Z")
    committee = (
        {"display_name": "M1 Chair", "vote_weight_bps": 3000, "veto_power": False},
        {"display_name": "M2 Marketing", "vote_weight_bps": 3000, "veto_power": False},
        {"display_name": "M3 Finance", "vote_weight_bps": 3000, "veto_power": True},
        {"display_name": "M4 Physical Production", "vote_weight_bps": 1000,
         "veto_power": False},
    )
    return setup_review_in_voting(
        committee_specs=committee,
        ballots=((0, "APPROVE"), (1, "APPROVE"), (3, "APPROVE"), (2, "VETO")),
        genre="DRAMA",
        title="Sparrow Detail",
    )


def test_a_binding_veto_declines_the_review_despite_a_seventy_percent_approval(api):
    """PRD 3.9: "**Two:** if `veto_cast` is true, the review resolves `VOTING →
    DECLINED`."
    PRD 3.9: "And `veto_cast` is true when at least one ballot carries `VETO` from a
    member whose `veto_power` was true at the time that ballot was cast."
    PRD 3.9: "`approval_pct` is one hundred multiplied by `approve_weight_bps`,
    divided by `decisive_weight_bps`, rounded half up to two decimal places — except
    that when `decisive_weight_bps` is zero it is 0.00 rather than a division by zero."

    Design: Difficulty/non_linear_state_machine/greenlight_fork_join_veto_branch_declines_despite_majority
    """
    ctx = _vetoed_review()

    resp = api.close_review(
        ctx["review"]["id"], {"decision_note": "Vetoed by finance."}, ADMIN
    )
    data = validate_success(resp, 200)
    assert_greenlight_review(data)

    assert data["status"] == "DECLINED"
    assert data["eligible_weight_bps"] == 10000
    assert data["cast_weight_bps"] == 10000
    assert data["decisive_weight_bps"] == 10000
    assert data["approve_weight_bps"] == 7000
    assert data["quorum_pct"] == 100.00
    assert data["approval_pct"] == 70.00
    assert data["veto_cast"] is True


def test_the_declined_branch_leaves_the_project_and_property_untouched(api):
    """PRD 3.9: "A `DECLINED` or `DEFERRED` outcome leaves the project's two axes
    exactly as they were. A `PASSED` outcome does not: the project's
    `development_status` moves to `GREENLIT` from whichever of `DRAFT_DELIVERED` or
    `POLISH_DELIVERED` it held, the property's `tracking_tier` is forced to `PRIORITY`
    regardless of what it was before, and every tracking board entry on that property
    still in `LIVE` status becomes `ARCHIVED`."

    Design: Difficulty/non_linear_state_machine/greenlight_fork_join_veto_branch_declines_despite_majority
    """
    ctx = _vetoed_review()
    validate_success(
        api.close_review(
            ctx["review"]["id"], {"decision_note": "Vetoed by finance."}, ADMIN
        )
    )

    assert fetch_project(ctx["project"]["id"])["development_status"] == "DRAFT_DELIVERED"
    assert fetch_property(ctx["property"]["id"])["tracking_tier"] == "NONE"


def _review_at_the_approval_floor():
    set_clock("2026-09-01T00:00:00Z")
    return setup_review_in_voting(
        committee_specs=FOUR_SEAT_COMMITTEE,
        ballots=((0, "APPROVE"), (1, "APPROVE"), (2, "DECLINE"), (3, "ABSTAIN")),
        genre="COMEDY",
        title="Committee of Four",
    )


def test_approval_percentage_of_exactly_sixty_six_point_six_seven_passes(api):
    """PRD 3.9: "**Four:** if `approval_pct` is at or above 66.67, the bound being
    inclusive, the review resolves `VOTING → PASSED`."
    PRD 3.9: "`decisive_weight_bps` is `cast_weight_bps` less the summed weight of the
    `ABSTAIN` ballots."

    Design: Difficulty/boundary_precision_check/greenlight_approval_pct_inclusive_at_sixty_six_point_six_seven
    """
    ctx = _review_at_the_approval_floor()

    resp = api.close_review(
        ctx["review"]["id"], {"decision_note": "Carried at the floor."}, ADMIN
    )
    data = validate_success(resp, 200)

    assert data["cast_weight_bps"] == 10000
    assert data["decisive_weight_bps"] == 9000, (
        "the 1000 bps abstention leaves the denominator but stays in the quorum"
    )
    assert data["approve_weight_bps"] == 6000
    assert data["quorum_pct"] == 100.00
    assert data["approval_pct"] == 66.67
    assert data["status"] == "PASSED"
    assert data["veto_cast"] is False


def test_a_passed_review_greenlights_the_project_and_forces_priority(api):
    """PRD 3.9: "A `DECLINED` or `DEFERRED` outcome leaves the project's two axes
    exactly as they were. A `PASSED` outcome does not: the project's
    `development_status` moves to `GREENLIT` from whichever of `DRAFT_DELIVERED` or
    `POLISH_DELIVERED` it held, the property's `tracking_tier` is forced to `PRIORITY`
    regardless of what it was before, and every tracking board entry on that property
    still in `LIVE` status becomes `ARCHIVED`."

    Design: Difficulty/boundary_precision_check/greenlight_approval_pct_inclusive_at_sixty_six_point_six_seven
    """
    ctx = _review_at_the_approval_floor()
    validate_success(
        api.close_review(
            ctx["review"]["id"], {"decision_note": "Carried at the floor."}, ADMIN
        )
    )

    assert fetch_project(ctx["project"]["id"])["development_status"] == "GREENLIT"
    assert fetch_property(ctx["property"]["id"])["tracking_tier"] == "PRIORITY"


def test_all_abstain_ballots_defer_the_review(api):
    """PRD 3.9: "**Three:** if `decisive_weight_bps` is zero — meaning every ballot
    cast was an `ABSTAIN` — the review resolves `VOTING → DEFERRED`."
    PRD 3.9: "`quorum_pct` is one hundred multiplied by `cast_weight_bps`, divided by
    the frozen `eligible_weight_bps`, rounded half up to two decimal places."

    Design: Corner/calculations/greenlight_all_abstain_yields_deferred_with_zero_decisive_weight
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_review_in_voting(
        committee_specs=FOUR_SEAT_COMMITTEE,
        ballots=((0, "ABSTAIN"), (1, "ABSTAIN"), (2, "ABSTAIN"), (3, "ABSTAIN")),
        genre="DRAMA",
        title="No Opinion",
    )

    resp = api.close_review(
        ctx["review"]["id"], {"decision_note": "No decisive ballots."}, ADMIN
    )
    data = validate_success(resp, 200)

    assert data["status"] == "DEFERRED"
    assert data["cast_weight_bps"] == 10000
    assert data["decisive_weight_bps"] == 0
    assert data["approve_weight_bps"] == 0
    assert data["quorum_pct"] == 100.00
    assert data["approval_pct"] == 0.00

    assert fetch_project(ctx["project"]["id"])["development_status"] == "DRAFT_DELIVERED"
    assert fetch_property(ctx["property"]["id"])["tracking_tier"] == "NONE"


def test_close_below_quorum_is_refused_and_the_review_stays_voting(api):
    """PRD 3.9: "**One:** if `quorum_pct` is below 60.00, the close is *refused* with
    `ERR_QUORUM_NOT_MET` and the review stays in `VOTING` — this is the only branch
    that is an error rather than an outcome, and it leaves the ballot open for more
    members to vote."
    PRD 3.9: "`cast_weight_bps` is the sum across all ballots regardless of value."

    Design: Corner/validations/close_review_below_quorum_returns_quorum_not_met_and_stays_voting
    """
    set_clock("2026-09-01T00:00:00Z")
    thin_room = (
        {"display_name": "M1 Chair", "vote_weight_bps": 3000, "veto_power": False},
        {"display_name": "M2 Marketing", "vote_weight_bps": 2999, "veto_power": False},
        {"display_name": "M3 Finance", "vote_weight_bps": 3000, "veto_power": False},
        {"display_name": "M4 Physical Production", "vote_weight_bps": 1001,
         "veto_power": False},
    )
    ctx = setup_review_in_voting(
        committee_specs=thin_room,
        ballots=((0, "APPROVE"), (1, "APPROVE")),
        genre="DRAMA",
        title="Thin Room",
    )

    resp = api.close_review(ctx["review"]["id"], {}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_QUORUM_NOT_MET, 409)

    review = fetch_review(ctx["review"]["id"])
    assert review["status"] == "VOTING"
    assert review["eligible_weight_bps"] == 10000
    assert review["cast_weight_bps"] == 5999
    assert fetch_project(ctx["project"]["id"])["development_status"] == "DRAFT_DELIVERED"


# ==========================================================================
# Guards on opening the ballot and on casting one
# ==========================================================================


def _open_review_on_an_unexercised_option():
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_development_pipeline(
        genre="SCIFI",
        title="Optioned Only",
        exercise=False,
        attach=True,
        pay_commencement=True,
        deliver_first_draft=True,
    )
    ctx["members"] = seat_committee(THREE_SEAT_COMMITTEE)
    ctx["review"] = convene_review(ctx["project"]["id"])
    return ctx


def test_open_voting_is_refused_while_the_rights_axis_is_only_optioned(api):
    """PRD 3.9: "Three preconditions hold: the project's `rights_status` must be
    `OWNED`, or the request is refused with `ERR_RIGHTS_NOT_OWNED`; the project's
    `development_status` must be either `DRAFT_DELIVERED` or `POLISH_DELIVERED`; and
    at least three committee seats must be `ACTIVE`, or the request is refused with
    `ERR_COMMITTEE_TOO_SMALL`."
    PRD 3.9: "Opening the ballot freezes `eligible_weight_bps` as the summed
    `vote_weight_bps` of the currently `ACTIVE` seats; that snapshot never moves again,
    no matter who is seated or unseated afterwards."

    Design: Difficulty/cross_entity_state_dependency/greenlight_open_voting_gated_by_project_rights_axis
    """
    ctx = _open_review_on_an_unexercised_option()

    resp = api.open_voting(ctx["review"]["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_RIGHTS_NOT_OWNED, 409)

    review = fetch_review(ctx["review"]["id"])
    assert review["status"] == "OPEN"
    assert review["eligible_weight_bps"] == 0, (
        "the weight snapshot is only frozen once voting actually opens"
    )


def test_rights_gate_does_not_disturb_the_development_axis_or_the_ready_flag(api):
    """PRD 3.6: "The `greenlight_ready` flag is a convenience derived from both axes
    at once: it is true exactly when `rights_status` is `OWNED` and
    `development_status` is either `DRAFT_DELIVERED` or `POLISH_DELIVERED`, and false
    otherwise."
    PRD 2.6: "Opening greenlight voting requires the project's `rights_status` to
    equal `OWNED`, or `ERR_RIGHTS_NOT_OWNED` (409)."

    Design: Difficulty/cross_entity_state_dependency/greenlight_open_voting_gated_by_project_rights_axis
    """
    ctx = _open_review_on_an_unexercised_option()

    resp = api.open_voting(ctx["review"]["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_RIGHTS_NOT_OWNED, 409)

    project = fetch_project(ctx["project"]["id"])
    assert project["rights_status"] == "OPTIONED"
    assert project["development_status"] == "DRAFT_DELIVERED"
    assert project["greenlight_ready"] is False


def test_open_voting_with_only_two_active_seats_returns_committee_too_small(api):
    """PRD 3.9: "Three preconditions hold: the project's `rights_status` must be
    `OWNED`, or the request is refused with `ERR_RIGHTS_NOT_OWNED`; the project's
    `development_status` must be either `DRAFT_DELIVERED` or `POLISH_DELIVERED`; and
    at least three committee seats must be `ACTIVE`, or the request is refused with
    `ERR_COMMITTEE_TOO_SMALL`."
    PRD 3.9: "A seat's `status` defaults to `ACTIVE` and may otherwise be `INACTIVE`;
    only `ACTIVE` seats are counted into a review's eligible weight."

    Design: Corner/errors/open_voting_with_two_active_members_returns_committee_too_small
    """
    set_clock("2026-09-01T00:00:00Z")
    from test_helpers import setup_owned_draft_delivered_project

    ctx = setup_owned_draft_delivered_project(genre="DRAMA", title="Quorum Short")
    members = seat_committee(
        (
            {"display_name": "M1 Chair", "vote_weight_bps": 4000, "veto_power": False},
            {"display_name": "M2 Marketing", "vote_weight_bps": 3000, "veto_power": False},
            {"display_name": "M3 Finance", "vote_weight_bps": 3000, "veto_power": False},
        )
    )
    patch_member(members[2]["id"], status="INACTIVE")
    review = convene_review(ctx["project"]["id"])

    resp = api.open_voting(review["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_COMMITTEE_TOO_SMALL, 409)

    stored = fetch_review(review["id"])
    assert stored["status"] == "OPEN"
    assert stored["eligible_weight_bps"] == 0
    assert fetch_member(members[2]["id"])["status"] == "INACTIVE"


def test_duplicate_ballot_from_the_same_member_is_refused(api):
    """PRD 3.9: "Three checks guard a ballot: the review must be in `VOTING`; the
    member must not already have a ballot on this review, or the request is refused
    with `ERR_DUPLICATE_VOTE`; the member's seat must be `ACTIVE`; and the member's
    `exec_user_id` must differ from the project's `owning_exec_user_id`."
    PRD 3.9: "Casting a ballot leaves the review in `VOTING` — this is a self-loop —
    and refreshes the running tallies."

    Design: Corner/errors/duplicate_ballot_from_same_member_returns_duplicate_vote
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_review_in_voting(
        committee_specs=THREE_SEAT_COMMITTEE,
        ballots=((0, "APPROVE"),),
        genre="DRAMA",
        title="One Ballot Each",
    )

    resp = api.cast_vote(
        ctx["review"]["id"],
        {"vote_value": "DECLINE"},
        make_committee_member_headers(ctx["members"][0]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_VOTE, 409)

    review = fetch_review(ctx["review"]["id"])
    assert review["cast_weight_bps"] == 3000
    assert review["approve_weight_bps"] == 3000
    assert review["eligible_weight_bps"] == 10000
    assert review["status"] == "VOTING"

    _, meta = validate_paginated(api.list_review_votes(ctx["review"]["id"], ADMIN))
    assert meta["total_count"] == 1


def test_committee_member_who_owns_the_project_cannot_vote(api):
    """PRD 2.9: "And a voting committee member's `exec_user_id` must differ from the
    `owning_exec_user_id` recorded on the project under review — a development
    executive who also holds a committee seat is barred from voting on their own
    project."
    PRD 3.9: "The ballot records the `review_id`, the `member_id` taken from the acting
    member's `X-User-ID`, and a `weight_bps_snapshot` frozen from that member's
    `vote_weight_bps` at the instant of casting."

    Design: Corner/rbac/committee_member_who_owns_the_project_cannot_vote
    """
    set_clock("2026-09-01T00:00:00Z")
    conflicted_committee = (
        {"display_name": "M1 Chair", "vote_weight_bps": 3000, "veto_power": False},
        {"display_name": "M2 Owning Exec", "vote_weight_bps": 3000,
         "veto_power": False, "exec_user_id": "exec-alpha"},
        {"display_name": "M3 Finance", "vote_weight_bps": 4000, "veto_power": False},
    )
    ctx = setup_review_in_voting(
        committee_specs=conflicted_committee,
        ballots=((0, "APPROVE"),),
        genre="DRAMA",
        title="Own Project Ballot",
    )

    resp = api.cast_vote(
        ctx["review"]["id"],
        {"vote_value": "APPROVE"},
        make_committee_member_headers(ctx["members"][1]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)

    assert fetch_project(ctx["project"]["id"])["owning_exec_user_id"] == "exec-alpha"
    assert fetch_member(ctx["members"][1]["id"])["exec_user_id"] == "exec-alpha"

    review = fetch_review(ctx["review"]["id"])
    assert review["cast_weight_bps"] == 3000
    assert review["eligible_weight_bps"] == 10000

    _, blocked_meta = validate_paginated(
        api.list_member_votes(ctx["members"][1]["id"], ADMIN)
    )
    assert blocked_meta["total_count"] == 0
    accepted_rows, accepted_meta = validate_paginated(
        api.list_member_votes(ctx["members"][0]["id"], ADMIN)
    )
    assert accepted_meta["total_count"] == 1
    assert_committee_vote(accepted_rows[0])
    assert accepted_rows[0]["weight_bps_snapshot"] == 3000
