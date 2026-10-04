"""Committee ballots, integrity bars, alternates, and the tally.

Covers the even-count median conservatism rule, the quorum floor, the
recusal/alternate pool conservation invariant, the append-only shape of a
recorded ballot, and the vote-integrity and duplication rejections
(PRD sections 2.5, 2.10 and 3.3).
"""

from datetime import datetime, timezone

from test_helpers import (
    CHAIR_HEADERS,
    ApiErrorId,
    assert_session_pool_invariant,
    cast_vote,
    cast_votes,
    close_session,
    get_engagement,
    get_ratings_for_engagement,
    get_session,
    make_committee_member_headers,
    open_session,
    run_committee,
    schedule_session,
    setup_committee_ready_engagement,
    validate_error,
    validate_paginated,
    validate_success,
    vote_payload,
)


def _instant(value):
    """Parse an ISO 8601 UTC timestamp for representation-agnostic equality."""
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(
        timezone.utc
    )


def _open_standard_session(api, ctx, voter_ids=None):
    session = schedule_session(api, ctx["engagement"], voter_ids=voter_ids)
    return open_session(api, session, open_at="2026-09-02T10:30:00Z")


def test_committee_median_even_split_conservatism(api):
    """PRD section 3.3: "With at least 3 votes, the tally sorts the cast
    notches by their positions on the seven-step scale and takes the median —
    and when the vote count is even, the worse of the two middle notches, the
    one nearer `CCC`, is chosen."
    PRD section 3.3: "A median inside the band completes the session
    `IN_SESSION` → `COMPLETED` and records the median as the session's
    `outcome_notch`".

    Design: Difficulty/combinatorial_formula/committee_median_even_split_conservatism
    """
    ctx = setup_committee_ready_engagement(api)  # indicative A
    session = _open_standard_session(api, ctx)
    cast_vote(
        api, session["id"], "voter-1",
        recusal_reason="prior advisory engagement with issuer",
    )
    cast_votes(
        api,
        session["id"],
        [("voter-2", "AAA"), ("voter-3", "A"), ("voter-4", "BBB"),
         ("voter-5", "BB")],
    )
    closed = close_session(api, session)
    # Sorted scale positions [0,2,3,4]; count 4 picks index 4//2 == 2 -> BBB.
    assert closed["status"] == "COMPLETED"
    assert closed["outcome_notch"] == "BBB"
    assert closed["adjourn_reason"] is None
    after = get_session(api, session["id"])
    assert after["eligible_voter_count"] == 4, "one recusal shrinks the pool"
    rating = get_ratings_for_engagement(api, ctx["engagement"]["id"])[0]
    assert rating["notch"] == "BBB", (
        "BBB sits exactly one notch from indicative A — inside the band"
    )


def test_quorum_exactly_three_votes_completes(api):
    """PRD section 3.3: "Fewer than 3 cast votes is a failed quorum" and
    "With at least 3 votes, the tally sorts the cast notches by their
    positions on the seven-step scale and takes the median".
    PRD section 3.3: "A new `Rating` is created in `ASSIGNED` with its `notch`
    set to the session's `outcome_notch`, `surveillance_posture` initialized
    to `CURRENT`, `assigned_at` stamped from the clock, and `notch_history`
    opened with a single entry whose cause is `COMMITTEE_ASSIGNMENT`."

    Design: Difficulty/boundary_precision_check/quorum_exactly_three_votes_completes
    """
    ctx = setup_committee_ready_engagement(api)  # indicative A
    outcome = run_committee(api, ctx["engagement"])
    session = outcome["session"]
    rating = outcome["rating"]
    assert session["status"] == "COMPLETED", (
        "exactly 3 votes meet the quorum floor"
    )
    assert session["outcome_notch"] == "A"  # median of A, A, BBB
    assert session["adjourn_reason"] is None
    assert rating["notch"] == "A"
    assert rating["status"] == "ASSIGNED"
    assert _instant(rating["assigned_at"]) == _instant("2026-09-02T10:30:00Z")
    votes, meta = validate_paginated(
        api.list_votes(session["id"], headers=CHAIR_HEADERS)
    )
    assert meta["total_count"] == 3, "voter-4 and voter-5 hold no vote rows"


def test_quorum_two_votes_adjourns(api):
    """PRD section 3.3: "Fewer than 3 cast votes is a failed quorum: the
    session adjourns `IN_SESSION` → `ADJOURNED` with `adjourn_reason`
    `QUORUM_NOT_MET`."
    PRD section 3.3: "An adjourned session, by contrast, leaves the engagement
    `COMMITTEE_READY`".

    Design: Corner/state_machines/quorum_two_votes_adjourns
    """
    ctx = setup_committee_ready_engagement(api)
    session = _open_standard_session(api, ctx)
    cast_votes(api, session["id"], [("voter-1", "A"), ("voter-2", "A")])
    closed = close_session(api, session)
    assert closed["status"] == "ADJOURNED"
    assert closed["adjourn_reason"] == "QUORUM_NOT_MET"
    assert closed["outcome_notch"] is None
    assert get_ratings_for_engagement(api, ctx["engagement"]["id"]) == []
    assert get_engagement(api, ctx["engagement"]["id"])["status"] == (
        "COMMITTEE_READY"
    )


def test_recusal_alternate_pool_conservation(api):
    """PRD section 3.3: "A successful appointment appends to
    `appointed_alternate_ids`, recomputes `eligible_voter_count` as 5 minus
    the number of recused voters plus the number of appointed alternates, and
    increments the session's `version`."

    Design: Difficulty/compensating_invariant/recusal_alternate_pool_conservation
    """
    ctx = setup_committee_ready_engagement(api)  # indicative A
    session = _open_standard_session(api, ctx)
    cast_vote(
        api, session["id"], "voter-1", recusal_reason="conflict of interest"
    )
    after_recusal = get_session(api, session["id"])
    assert after_recusal["eligible_voter_count"] == 4, "5 - 1 recused + 0"
    assert_session_pool_invariant(after_recusal)

    resp = api.appoint_alternate(
        session["id"],
        {"recused_voter_id": "voter-1", "alternate_voter_id": "voter-6"},
        headers=CHAIR_HEADERS,
    )
    validate_success(resp, 200)
    after_alternate = get_session(api, session["id"])
    assert after_alternate["eligible_voter_count"] == 5, "5 - 1 + 1 restored"
    assert_session_pool_invariant(after_alternate)

    cast_votes(
        api,
        session["id"],
        [("voter-2", "A"), ("voter-3", "A"), ("voter-4", "BBB"),
         ("voter-6", "BBB")],
    )
    closed = close_session(api, session)
    assert closed["status"] == "COMPLETED"
    # Even-count median of A, A, BBB, BBB picks the worse middle: BBB.
    assert closed["outcome_notch"] == "BBB"
    assert_session_pool_invariant(get_session(api, session["id"]))


def test_committee_vote_immutable_common_fields_absent(api):
    """PRD section 2.5: "Two resources are deliberately lighter: a
    `CommitteeVote` and an `IssuerNotification` each carry only `id` and
    `created_at` — both `updated_at` and `version` are absent from them,
    because neither is ever modified after it is recorded."
    PRD section 4: "casting a ballot ... answer `201 Created`".

    Design: Corner/entities/committee_vote_immutable_common_fields_absent
    """
    ctx = setup_committee_ready_engagement(api)
    session = _open_standard_session(api, ctx)
    resp = api.cast_vote(
        session["id"],
        vote_payload("voter-1", notch_vote="A"),
        headers=make_committee_member_headers("voter-1"),
    )
    data = validate_success(resp, 201)
    assert data["kind"] == "VOTE"
    assert data["notch_vote"] == "A"
    assert "version" not in data, "a ballot carries no version field"
    assert "updated_at" not in data, "a ballot carries no updated_at field"

    # The only re-mutation pathway — a second ballot from the same voter —
    # is itself rejected, leaving the record immutable in practice.
    dup = api.cast_vote(
        session["id"],
        vote_payload("voter-1", notch_vote="BBB"),
        headers=make_committee_member_headers("voter-1"),
    )
    validate_error(dup, ApiErrorId.ERR_DUPLICATE_COMMITTEE_VOTE)


def test_vote_with_both_notch_and_recusal_rejected(api):
    """PRD section 3.3: "Each ballot takes exactly one of two forms: a
    `notch_vote` carrying one of the seven notches, or a `recusal_reason`
    text; supplying both or neither is `ERR_VOTE_KIND_AMBIGUOUS`".

    Design: Corner/validations/vote_with_both_notch_and_recusal_rejected
    """
    ctx = setup_committee_ready_engagement(api)
    session = _open_standard_session(api, ctx)
    resp = api.cast_vote(
        session["id"],
        {"voter_id": "voter-1", "notch_vote": "A", "recusal_reason": "hedging"},
        headers=make_committee_member_headers("voter-1"),
    )
    validate_error(resp, ApiErrorId.ERR_VOTE_KIND_AMBIGUOUS)
    votes, _meta = validate_paginated(
        api.list_votes(session["id"], headers=CHAIR_HEADERS)
    )
    assert votes == []


def test_duplicate_vote_rejected(api):
    """PRD section 3.3: "Any second ballot, whether vote or recusal, from the
    same voter in the same session is `ERR_DUPLICATE_COMMITTEE_VOTE`."

    Design: Corner/validations/duplicate_vote_rejected
    """
    ctx = setup_committee_ready_engagement(api)
    session = _open_standard_session(api, ctx)
    cast_vote(api, session["id"], "voter-1", notch="A")
    resp = api.cast_vote(
        session["id"],
        vote_payload("voter-1", notch_vote="BBB"),
        headers=make_committee_member_headers("voter-1"),
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_COMMITTEE_VOTE)
    votes, _meta = validate_paginated(
        api.list_votes(session["id"], headers=CHAIR_HEADERS)
    )
    assert len(votes) == 1
    assert votes[0]["notch_vote"] == "A", "the recorded ballot is unmutated"


def test_voter_not_in_pool_rejected(api):
    """PRD section 3.3: "The ballot's `voter_id` must equal the caller's
    `X-User-ID` and must belong to the session pool — the original
    `voter_ids` plus any `appointed_alternate_ids` — or the vote is rejected
    with `ERR_VOTER_NOT_ELIGIBLE`."

    Design: Corner/validations/voter_not_in_pool_rejected
    """
    ctx = setup_committee_ready_engagement(api)
    session = _open_standard_session(api, ctx)
    resp = api.cast_vote(
        session["id"],
        vote_payload("voter-99", notch_vote="A"),
        headers=make_committee_member_headers("voter-99"),
    )
    validate_error(resp, ApiErrorId.ERR_VOTER_NOT_ELIGIBLE)
    votes, _meta = validate_paginated(
        api.list_votes(session["id"], headers=CHAIR_HEADERS)
    )
    assert votes == []


def test_lead_analyst_first_vote_forbidden_sod(api):
    """PRD section 3.3: "a `voter_id` equal to the engagement's
    `assigned_analyst_id` may not vote at all — `ERR_ANALYST_VOTE_FORBIDDEN`,
    the segregation-of-duties bar".

    Design: Corner/rbac/lead_analyst_first_vote_forbidden_sod
    """
    # The default analyst (analyst-1) authors the scorecard and is recorded
    # as the engagement's assigned_analyst_id.
    ctx = setup_committee_ready_engagement(api)
    session = _open_standard_session(
        api,
        ctx,
        voter_ids=["analyst-1", "voter-2", "voter-3", "voter-4", "voter-5"],
    )
    resp = api.cast_vote(
        session["id"],
        vote_payload("analyst-1", notch_vote="A"),
        headers=make_committee_member_headers("analyst-1"),
    )
    validate_error(resp, ApiErrorId.ERR_ANALYST_VOTE_FORBIDDEN)
    votes, _meta = validate_paginated(
        api.list_votes(session["id"], headers=CHAIR_HEADERS)
    )
    assert votes == [], "no ballot is recorded for the barred analyst"


def test_recused_vote_safety_beats_duplicate_constraint(api):
    """PRD section 2.10: "the server evaluates its checks in a fixed priority
    order and reports the earliest failure: the lower-numbered check always
    wins over a higher-numbered one."
    PRD section 2.10: "Eighth, vote integrity and segregation of duties — the
    barred analyst, recused voters, and pool membership — failing as
    `ERR_ANALYST_VOTE_FORBIDDEN`, `ERR_RECUSED_VOTER_VOTE_FORBIDDEN`, or
    `ERR_VOTER_NOT_ELIGIBLE`." (tenth covers one ballot per voter per session
    as `ERR_DUPLICATE_COMMITTEE_VOTE`)
    PRD section 3.3: "a voter who has recorded a recusal in the session may
    not later cast a vote in it, failing as
    `ERR_RECUSED_VOTER_VOTE_FORBIDDEN`."

    Design: Difficulty/priority_pair_validation_conflict/recused_vote_safety_beats_duplicate_constraint
    """
    ctx = setup_committee_ready_engagement(api)
    session = _open_standard_session(api, ctx)
    cast_vote(
        api, session["id"], "voter-1", recusal_reason="conflict of interest"
    )
    resp = api.cast_vote(
        session["id"],
        vote_payload("voter-1", notch_vote="A"),
        headers=make_committee_member_headers("voter-1"),
    )
    # Both the priority-8 recusal bar and the priority-10 duplicate rule are
    # violated; the safety error must be the one reported.
    validate_error(resp, ApiErrorId.ERR_RECUSED_VOTER_VOTE_FORBIDDEN)
    assert resp.json()["data"]["error_id"] != "ERR_DUPLICATE_COMMITTEE_VOTE"
    votes, _meta = validate_paginated(
        api.list_votes(session["id"], headers=CHAIR_HEADERS)
    )
    assert len(votes) == 1
    assert votes[0]["voter_id"] == "voter-1"
    assert votes[0]["kind"] == "RECUSAL"


def test_alternate_for_non_recused_voter_rejected(api):
    """PRD section 3.3: "the appointment is rejected with
    `ERR_ALTERNATE_NOT_PERMITTED` unless the named voter has a recorded
    recusal in this session, the alternate is not already in the pool and not
    among the recused, and the session is not yet terminal."

    Design: Corner/errors/alternate_for_non_recused_voter_rejected
    """
    ctx = setup_committee_ready_engagement(api)
    session = _open_standard_session(api, ctx)
    resp = api.appoint_alternate(
        session["id"],
        {"recused_voter_id": "voter-1", "alternate_voter_id": "voter-6"},
        headers=CHAIR_HEADERS,
    )
    validate_error(resp, ApiErrorId.ERR_ALTERNATE_NOT_PERMITTED)
    current = get_session(api, session["id"])
    assert current["appointed_alternate_ids"] == []
    assert current["eligible_voter_count"] == 5
