"""The voting window: who may cast, when, how often, and what a void releases."""

from test_helpers import (
    AFTER_VOTING_WINDOW,
    ApiErrorId,
    INSIDE_VOTING_WINDOW,
    LATER_INSIDE_VOTING_WINDOW,
    TEST_USERS,
    VOTING_CLOSES_AT,
    VOTING_OPENS_AT,
    assert_instant_equals,
    assert_pct,
    assert_vote,
    candidate_mark,
    create_vote_payload,
    make_student_voter_headers,
    open_polls,
    open_voting_payload,
    publish_round_one_ballot,
    read_ballot,
    read_ballot_line,
    read_election,
    read_vote,
    set_clock,
    setup_locked_unpublished_ballot,
    setup_open_polls_with_one_cast_ballot,
    setup_petitioning_election,
    setup_severe_case_inside_voting_window,
    setup_single_candidate_election,
    setup_two_elections_sharing_academic_year,
    uphold_case,
    validate_error,
    validate_paginated,
    validate_success,
)

COMMISSIONER = TEST_USERS["commissioner_headers"]
ADVISOR = TEST_USERS["advisor_headers"]


def _open_race(*, voter_overrides=None, office_overrides=None):
    """One approved candidacy, one voter and the polls open with the clock inside
    the window."""
    office = {"eligible_class_years": ["FRESHMAN", "SENIOR"]}
    office.update(office_overrides or {})
    scenario = setup_petitioning_election(
        offices=[office],
        candidates=[{"office": 0}],
        voters=[
            {
                "full_name": "Voter One",
                "class_year": "FRESHMAN",
                "gpa": 3.00,
                "credits_completed": 12,
                **(voter_overrides or {}),
            }
        ],
        approve=True,
    )
    publish_round_one_ballot(scenario)
    open_polls(scenario)
    scenario["candidacy"] = scenario["candidacies"][0]
    scenario["voter"] = scenario["voters"][0]
    return scenario


def test_the_server_derives_the_voter_the_round_and_the_cast_instant(api):
    """PRD §3.7: "A `StudentVoter` casts a **Vote** by naming the `ballot_id` and supplying
    `selections`, the array of marks. Everything else is derived by the server: the vote's
    `student_id` is taken from the acting `X-User-ID`, its `election_id` and `round` are
    copied from the ballot, `cast_at` is stamped from the logical clock, `status` begins at
    `CAST`, and `void_reason` is empty."
    PRD §3.7: "Each accepted vote recomputes the election's `ballots_cast_count` — the
    number of votes in `CAST` status for this election and its `current_round` — and its
    `turnout_pct`, which is one hundred multiplied by `ballots_cast_count` divided by
    `eligible_voter_count`, rounded half up to two decimal places, and is 0.00 whenever
    `eligible_voter_count` is zero."

    Design: Corner/entities/vote_student_and_round_are_derived_not_supplied
    """
    scenario = _open_race()
    voter = scenario["voter"]

    vote = validate_success(
        api.create_vote(
            create_vote_payload(
                scenario["ballot"]["id"],
                [candidate_mark(scenario["office"]["id"], scenario["candidacy"]["id"])],
            ),
            make_student_voter_headers(voter["id"]),
        ),
        201,
    )

    assert_vote(vote)
    assert vote["student_id"] == voter["id"], "the voter is the acting StudentVoter"
    assert vote["election_id"] == scenario["election"]["id"]
    assert vote["round"] == 1
    assert vote["status"] == "CAST"
    assert vote["void_reason"] is None
    assert_instant_equals(vote["cast_at"], INSIDE_VOTING_WINDOW, "Vote.cast_at")

    election = read_election(scenario["election"]["id"])
    assert election["ballots_cast_count"] == 1
    assert election["eligible_voter_count"] == 2
    assert_pct(election["turnout_pct"], 50.00, "turnout_pct")


def test_a_voter_carrying_a_disciplinary_hold_is_refused(api):
    """PRD §3.7: "The acting student must be `ENROLLED`, must have `disciplinary_hold`
    false, and must have a `class_year` that appears in the `eligible_class_years` of at
    least one office carried on the ballot being voted; failing any of these is
    `ERR_VOTER_INELIGIBLE`."
    PRD §3.7: "`eligible_voter_count` is set to the number of students who, at that
    instant, have `enrollment_status` equal to `ENROLLED`, have `disciplinary_hold` false,
    and whose `class_year` appears in the union of `eligible_class_years` taken across
    every office of this election."

    Design: Corner/validations/voter_on_disciplinary_hold_returns_voter_ineligible
    """
    scenario = _open_race(voter_overrides={"disciplinary_hold": True})

    validate_error(
        api.create_vote(
            create_vote_payload(
                scenario["ballot"]["id"],
                [candidate_mark(scenario["office"]["id"], scenario["candidacy"]["id"])],
            ),
            make_student_voter_headers(scenario["voter"]["id"]),
        ),
        ApiErrorId.ERR_VOTER_INELIGIBLE.value,
        403,
    )

    election = read_election(scenario["election"]["id"])
    assert election["eligible_voter_count"] == 1, (
        "the held student is outside the frozen electorate, got "
        f"{election['eligible_voter_count']}"
    )
    assert election["ballots_cast_count"] == 0
    _, meta = validate_paginated(
        api.list_votes(COMMISSIONER, params={"election_id": scenario["election"]["id"]})
    )
    assert meta["total_count"] == 0


def test_a_second_ballot_inside_the_open_window_is_refused(api):
    """PRD §3.7: "The student must not already hold a vote in `CAST` status for this same
    election and round — one vote per student per round, reported as `ERR_DUPLICATE_VOTE`."

    Design: Corner/validations/second_vote_inside_open_window_returns_duplicate_vote
    """
    scenario = setup_open_polls_with_one_cast_ballot()
    set_clock(LATER_INSIDE_VOTING_WINDOW)

    validate_error(
        api.create_vote(
            create_vote_payload(
                scenario["ballot"]["id"],
                [candidate_mark(scenario["office"]["id"], scenario["candidacy"]["id"])],
            ),
            make_student_voter_headers(scenario["voter"]["id"]),
        ),
        ApiErrorId.ERR_DUPLICATE_VOTE.value,
        409,
    )

    assert read_election(scenario["election"]["id"])["ballots_cast_count"] == 1
    _, meta = validate_paginated(
        api.list_votes(COMMISSIONER, params={"student_id": scenario["voter"]["id"]})
    )
    assert meta["total_count"] == 1, "the refused ballot was never written"


def test_a_mark_naming_a_voided_line_is_refused(api):
    """PRD §3.7: "Finally the marks themselves are inspected: every mark must resolve to a
    ballot line that is `ACTIVE` on the ballot being voted, no two marks may name the same
    `office_id` and no two may name the same `referendum_id`, and every referendum mark's
    `choice` must be one of the three permitted values; anything else is
    `ERR_INVALID_SELECTION`."

    Design: Corner/validations/vote_selection_naming_voided_line_returns_invalid_selection
    """
    scenario = setup_severe_case_inside_voting_window(
        office_overrides={"eligible_class_years": ["FRESHMAN", "JUNIOR", "SENIOR"]},
        voters=[{"full_name": "Voter One", "class_year": "FRESHMAN", "gpa": 3.00,
                 "credits_completed": 12}],
    )
    uphold_case(scenario["pending_case"])
    voter = scenario["voters"][0]
    assert read_ballot_line(scenario["second_line"]["id"])["status"] == "VOIDED"

    validate_error(
        api.create_vote(
            create_vote_payload(
                scenario["ballot"]["id"],
                [candidate_mark(
                    scenario["office"]["id"], scenario["second_candidacy"]["id"]
                )],
            ),
            make_student_voter_headers(voter["id"]),
        ),
        ApiErrorId.ERR_INVALID_SELECTION.value,
        422,
    )

    accepted = validate_success(
        api.create_vote(
            create_vote_payload(
                scenario["ballot"]["id"],
                [candidate_mark(
                    scenario["office"]["id"], scenario["first_candidacy"]["id"]
                )],
            ),
            make_student_voter_headers(voter["id"]),
        ),
        201,
    )
    assert accepted["status"] == "CAST"
    assert read_election(scenario["election"]["id"])["ballots_cast_count"] == 1


def test_voiding_a_cast_ballot_releases_the_one_vote_lock(api):
    """PRD §3.7: "A `FacultyAdvisor` may void a cast ballot, moving the vote
    `CAST → VOIDED` and recording the mandatory `void_reason`."
    PRD §3.7: "It recomputes `ballots_cast_count` and `turnout_pct`, and it releases the
    student's one-vote lock for that round: if the window is still open, that student may
    cast again."

    Design: Corner/state_machines/vote_void_releases_one_vote_lock_and_restores_turnout
    """
    scenario = setup_open_polls_with_one_cast_ballot()

    voided = validate_success(
        api.void_vote(
            scenario["vote"]["id"],
            {"void_reason": "Machine misread the paper ballot"},
            ADVISOR,
        )
    )
    assert voided["status"] == "VOIDED"

    after_void = read_election(scenario["election"]["id"])
    assert after_void["ballots_cast_count"] == 0
    assert_pct(after_void["turnout_pct"], 0.00, "turnout_pct after the void")

    recast = validate_success(
        api.create_vote(
            create_vote_payload(
                scenario["ballot"]["id"],
                [candidate_mark(scenario["office"]["id"], scenario["candidacy"]["id"])],
            ),
            make_student_voter_headers(scenario["voter"]["id"]),
        ),
        201,
    )
    assert recast["status"] == "CAST"
    assert read_vote(scenario["vote"]["id"])["status"] == "VOIDED"

    final = read_election(scenario["election"]["id"])
    assert final["ballots_cast_count"] == 1
    assert_pct(final["turnout_pct"], 50.00, "turnout_pct after the recast")
    _, meta = validate_paginated(
        api.list_votes(COMMISSIONER, params={"student_id": scenario["voter"]["id"]})
    )
    assert meta["total_count"] == 2, "the voided row is kept alongside the recast one"


def test_closing_the_polls_before_the_window_ends_is_refused(api):
    """PRD §3.7: "Closing the polls carries the election `VOTING_OPEN → VOTING_CLOSED` and
    requires the logical clock to have reached `voting_closes_at`."
    PRD §2.5: "The target row — or, for a child create, the parent row the new child hangs
    from — is in a state from which the requested operation is declared —
    `ERR_INVALID_STATE` (409). This covers every state-transition endpoint"

    Design: Corner/state_machines/close_voting_before_window_end_returns_invalid_state
    """
    scenario = setup_single_candidate_election(
        office_overrides={"eligible_class_years": ["SENIOR"]}
    )
    publish_round_one_ballot(scenario)
    open_polls(scenario)

    validate_error(
        api.close_voting(scenario["election"]["id"], COMMISSIONER),
        ApiErrorId.ERR_INVALID_STATE.value,
        409,
    )

    assert read_election(scenario["election"]["id"])["status"] == "VOTING_OPEN"
    assert read_ballot(scenario["ballot"]["id"])["status"] == "PUBLISHED"


# ─── Cross-entity state: the ballot decides whether a vote may exist ───────────

def test_a_vote_against_a_locked_but_unpublished_ballot_is_refused(api):
    """PRD §3.7: "Casting is guarded, in order, by five checks. The referenced ballot must
    be in `PUBLISHED`, or the state gate refuses the request."
    PRD §2.5: "The target row — or, for a child create, the parent row the new child hangs
    from — is in a state from which the requested operation is declared —
    `ERR_INVALID_STATE` (409). This covers every state-transition endpoint plus
    campaign-expense reporting (the referenced candidacy's `status` must not be
    `WITHDRAWN`, `DISQUALIFIED` or `VACATED`), petition-signature creation (same three
    excluded statuses), ballot-line creation (the ballot's `status` must be `DRAFT`) and
    vote casting (the ballot's `status` must be `PUBLISHED`)."

    Design: Difficulty/cross_entity_state_dependency/vote_rejected_while_ballot_locked_not_published
    """
    scenario = setup_locked_unpublished_ballot()

    validate_error(
        api.create_vote(
            create_vote_payload(
                scenario["ballot"]["id"],
                [candidate_mark(scenario["office"]["id"], scenario["candidacy"]["id"])],
            ),
            make_student_voter_headers(scenario["voter"]["id"]),
        ),
        ApiErrorId.ERR_INVALID_STATE.value,
        409,
    )


def test_the_refused_vote_writes_no_row_while_the_ballot_stays_locked(api):
    """PRD §3.6: "Publication is the last construction step. The transition
    `LOCKED → PUBLISHED` requires the election to be in `BALLOT_BUILDING` and the ballot's
    `round` to equal the election's `current_round`."
    PRD §3.7: "Each accepted vote recomputes the election's `ballots_cast_count` — the
    number of votes in `CAST` status for this election and its `current_round` — and its
    `turnout_pct`, which is one hundred multiplied by `ballots_cast_count` divided by
    `eligible_voter_count`, rounded half up to two decimal places, and is 0.00 whenever
    `eligible_voter_count` is zero."

    Design: Difficulty/cross_entity_state_dependency/vote_rejected_while_ballot_locked_not_published
    """
    scenario = setup_locked_unpublished_ballot()

    validate_error(
        api.create_vote(
            create_vote_payload(
                scenario["ballot"]["id"],
                [candidate_mark(scenario["office"]["id"], scenario["candidacy"]["id"])],
            ),
            make_student_voter_headers(scenario["voter"]["id"]),
        ),
        ApiErrorId.ERR_INVALID_STATE.value,
        409,
    )

    assert read_ballot(scenario["ballot"]["id"])["status"] == "LOCKED"
    election = read_election(scenario["election"]["id"])
    assert election["status"] == "BALLOT_BUILDING"
    assert election["ballots_cast_count"] == 0
    _, meta = validate_paginated(
        api.list_votes(COMMISSIONER, params={"ballot_id": scenario["ballot"]["id"]})
    )
    assert meta["total_count"] == 0


# ─── The rejection ladder inside the polling place ────────────────────────────

def test_a_vote_after_the_window_closes_reports_the_window_error(api):
    """PRD §2.5: "And vote casting runs the window check, then voter eligibility, then the
    one-vote rule, and only then the selection shape — so an ineligible student voting
    twice with a malformed selection sees `ERR_VOTER_INELIGIBLE`."
    PRD §3.7: "The logical clock must lie inside the half-open window running from
    `voting_opens_at` up to but not including `voting_closes_at`, and the election must be
    in `VOTING_OPEN`; otherwise the attempt is `ERR_VOTING_WINDOW_CLOSED`."

    Design: Difficulty/priority_pair_validation_conflict/closed_window_duplicate_vote_yields_window_error
    """
    scenario = setup_open_polls_with_one_cast_ballot()
    set_clock(AFTER_VOTING_WINDOW)

    response = api.create_vote(
        create_vote_payload(
            scenario["ballot"]["id"],
            [candidate_mark(scenario["office"]["id"], scenario["candidacy"]["id"])],
        ),
        make_student_voter_headers(scenario["voter"]["id"]),
    )

    validate_error(response, ApiErrorId.ERR_VOTING_WINDOW_CLOSED.value, 409)
    assert response.json()["data"]["error_id"] != ApiErrorId.ERR_DUPLICATE_VOTE.value, (
        "the temporal rule is reached before the one-vote rule"
    )


def test_the_late_second_ballot_leaves_the_turnout_counters_alone(api):
    """PRD §3.7: "The window itself is half-open — an instant equal to `voting_closes_at`
    is already outside it."
    PRD §3.7: "Each accepted vote recomputes the election's `ballots_cast_count` — the
    number of votes in `CAST` status for this election and its `current_round` — and its
    `turnout_pct`, which is one hundred multiplied by `ballots_cast_count` divided by
    `eligible_voter_count`, rounded half up to two decimal places, and is 0.00 whenever
    `eligible_voter_count` is zero."

    Design: Difficulty/priority_pair_validation_conflict/closed_window_duplicate_vote_yields_window_error
    """
    scenario = setup_open_polls_with_one_cast_ballot()
    set_clock(AFTER_VOTING_WINDOW)

    validate_error(
        api.create_vote(
            create_vote_payload(
                scenario["ballot"]["id"],
                [candidate_mark(scenario["office"]["id"], scenario["candidacy"]["id"])],
            ),
            make_student_voter_headers(scenario["voter"]["id"]),
        ),
        ApiErrorId.ERR_VOTING_WINDOW_CLOSED.value,
        409,
    )

    _, meta = validate_paginated(
        api.list_votes(COMMISSIONER, params={"student_id": scenario["voter"]["id"]})
    )
    assert meta["total_count"] == 1, "the late ballot was never written"
    election = read_election(scenario["election"]["id"])
    assert election["ballots_cast_count"] == 1
    assert election["status"] == "VOTING_OPEN", (
        "moving the clock fires no transition of its own"
    )


# ─── The academic-year polling calendar ───────────────────────────────────────

def test_a_window_that_straddles_another_election_is_refused(api):
    """PRD §2.10: "A proposed window collides with an existing election's window when the
    proposed opening instant is strictly before the existing closing instant **and** the
    existing opening instant is strictly before the proposed closing instant."
    PRD §3.7: "and the requested window must not collide with the window of any other
    election sharing the same `academic_year`, under the half-open geometry of Section
    2.10, with a collision reported as `ERR_VOTING_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/election_voting_window_half_open_adjacency_accepted_overlap_rejected
    """
    scenario = setup_two_elections_sharing_academic_year()
    second = scenario["second_election"]

    validate_error(
        api.open_voting(
            second["id"],
            open_voting_payload("2026-09-16T12:00:00Z", "2026-09-17T00:00:00Z", 1),
            COMMISSIONER,
        ),
        ApiErrorId.ERR_VOTING_WINDOW_OVERLAP.value,
        409,
    )

    refused = read_election(second["id"])
    assert refused["status"] == "BALLOT_PUBLISHED", (
        f"the refused act leaves the election unopened, got {refused['status']}"
    )
    assert refused["voting_opens_at"] is None
    assert refused["voting_closes_at"] is None


def test_a_window_opening_exactly_when_another_closes_is_accepted(api):
    """PRD §2.10: "Both comparisons are strict, so windows that merely touch at an
    endpoint — a proposal opening at the exact instant another closes, or closing at the
    exact instant another opens — do not collide and are accepted."
    PRD §2.10: "The candidate set is every other election sharing the same `academic_year`
    that already has a voting window set, regardless of that election's own `status`."

    Design: Difficulty/resource_temporal_overlap/election_voting_window_half_open_adjacency_accepted_overlap_rejected
    """
    scenario = setup_two_elections_sharing_academic_year()
    second = scenario["second_election"]

    validate_error(
        api.open_voting(
            second["id"],
            open_voting_payload("2026-09-16T12:00:00Z", "2026-09-17T00:00:00Z", 1),
            COMMISSIONER,
        ),
        ApiErrorId.ERR_VOTING_WINDOW_OVERLAP.value,
        409,
    )

    opened = validate_success(
        api.open_voting(
            second["id"],
            open_voting_payload(VOTING_CLOSES_AT, "2026-09-17T09:00:00Z", 1),
            COMMISSIONER,
        )
    )

    assert opened["status"] == "VOTING_OPEN", (
        f"adjacency at the endpoint is accepted, got {opened['status']}"
    )
    assert_instant_equals(opened["voting_opens_at"], VOTING_CLOSES_AT, "voting_opens_at")
    assert_instant_equals(
        opened["voting_closes_at"], "2026-09-17T09:00:00Z", "voting_closes_at"
    )
    first = read_election(scenario["first_election"]["id"])
    assert_instant_equals(
        first["voting_closes_at"], VOTING_CLOSES_AT, "the incumbent window's close"
    )
    assert_instant_equals(
        first["voting_opens_at"], VOTING_OPENS_AT, "the incumbent window's open"
    )
