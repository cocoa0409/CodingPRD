"""Publication gating and the pre-publication appeal process.

Covers the publish side-effect bundle, the strict 120-hour publish window,
the inclusive appeal deadline, the new-information rule, the one-appeal
limit, the appeal-pending publish block, terminal appeal decisions, the
state-beats-temporal priority pair, and the upheld-appeal re-deliberation
cycle (PRD sections 2.10, 3.4 and 3.5).
"""

from datetime import datetime, timezone

from test_helpers import (
    ADMIN_HEADERS,
    ANALYST_HEADERS,
    CHAIR_HEADERS,
    DOC_AUDIT_FY,
    DOC_EPA_LITIGATION_REPORT,
    DOC_PENSION_VALUATION,
    ApiErrorId,
    accept_terms,
    advance_clock,
    appeal_payload,
    assert_notification_order,
    cast_votes,
    close_session,
    create_engagement_solicited,
    create_issuer,
    decide_appeal,
    file_appeal,
    get_engagement,
    get_obligations,
    get_rating,
    get_ratings_for_engagement,
    iso_add_hours,
    iso_add_seconds,
    issuer_headers,
    next_session_window,
    open_session,
    publish_payload,
    publish_rating,
    run_committee,
    schedule_session,
    setup_active_criteria,
    setup_assigned_rating,
    setup_published_rating,
    submit_document,
    submit_required_documents,
    submit_scorecard,
    validate_error,
    validate_paginated,
    validate_success,
)


def _instant(value):
    """Parse an ISO 8601 UTC timestamp for representation-agnostic equality."""
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(
        timezone.utc
    )


def test_publish_sets_fields_and_creates_first_obligation(api):
    """PRD section 3.4: "On success the rating moves `ASSIGNED` → `PUBLISHED`
    with `published_at` stamped from the clock, the engagement moves to its
    own terminal `PUBLISHED` state — its lifecycle ends while surveillance
    continues on the rating — the first annual disclosure obligation is
    created per the schedule in §3.5, a `RATING_PUBLISHED` notification is
    logged, and the rating's `version` increments."
    PRD section 3.5: "The first obligation, `period_index` 1, takes as its
    `fiscal_year_end` the first occurrence of the issuer's `fiscal_year_end`
    month-day — anchored at 00:00:00Z — that falls strictly after
    `published_at`" and "Its `due_at` is 210 days after that
    `fiscal_year_end`."

    Design: Corner/endpoints/publish_sets_fields_and_creates_first_obligation
    """
    ctx = setup_assigned_rating(api)
    published = publish_rating(
        api, ctx["rating"], publish_at="2026-09-08T00:00:00Z"
    )
    assert published["status"] == "PUBLISHED"
    assert published["outlook"] == "STABLE"
    assert published["rationale"] == "Stable credit profile"
    assert _instant(published["published_at"]) == _instant("2026-09-08T00:00:00Z")

    engagement = get_engagement(api, ctx["engagement"]["id"])
    assert engagement["status"] == "PUBLISHED"

    obligations = get_obligations(api, published["id"])
    assert len(obligations) == 1
    first = obligations[0]
    assert first["period_index"] == 1
    # 06-30 in the publication year is not strictly after 2026-09-08, so the
    # schedule rolls forward one calendar year; +210 days lands 2028-01-26.
    assert _instant(first["fiscal_year_end"]) == _instant("2027-06-30T00:00:00Z")
    assert _instant(first["due_at"]) == _instant("2028-01-26T00:00:00Z")
    assert first["status"] == "PENDING"

    notifications = api.list_issuer_notifications(
        ctx["issuer"]["id"], headers=ADMIN_HEADERS
    )
    log, _meta = validate_paginated(notifications)
    assert_notification_order(log, ["RATING_ASSIGNED", "RATING_PUBLISHED"])


def test_publish_before_appeal_window_elapsed_rejected(api):
    """PRD section 3.4: "the clock must stand strictly later than 120 hours
    after `assigned_at` — a publish attempted at or before the mark fails with
    `ERR_PUBLISH_WINDOW_NOT_ELAPSED`".

    Design: Corner/errors/publish_before_appeal_window_elapsed_rejected
    """
    ctx = setup_assigned_rating(api)
    rating = ctx["rating"]

    advance_clock(api, iso_add_hours(rating["assigned_at"], 120))
    early = api.publish_rating(
        rating["id"],
        publish_payload(rationale="boundary attempt"),
        headers=ANALYST_HEADERS,
    )
    validate_error(early, ApiErrorId.ERR_PUBLISH_WINDOW_NOT_ELAPSED)

    advance_clock(api, iso_add_seconds(rating["assigned_at"], 120 * 3600 + 1))
    resp = api.publish_rating(
        rating["id"],
        publish_payload(rationale="one second past the window"),
        headers=ANALYST_HEADERS,
    )
    data = validate_success(resp, 200)
    assert data["status"] == "PUBLISHED"


def test_appeal_after_window_rejected(api):
    """PRD section 3.4: "a filing at exactly the 120-hour mark is still
    admitted, while anything later is rejected with
    `ERR_APPEAL_WINDOW_CLOSED`; a filing against a rating in any other state
    fails with `ERR_RATING_STATE_INVALID`."

    Design: Corner/errors/appeal_after_window_rejected
    """
    ctx = setup_assigned_rating(api)
    rating = ctx["rating"]
    advance_clock(api, iso_add_seconds(rating["assigned_at"], 120 * 3600 + 1))
    resp = api.file_appeal(
        rating["id"],
        appeal_payload([DOC_PENSION_VALUATION]),
        headers=issuer_headers(ctx["issuer"]),
    )
    # The rating is still ASSIGNED, so only the temporal rule can fire.
    validate_error(resp, ApiErrorId.ERR_APPEAL_WINDOW_CLOSED)
    appeals, _meta = validate_paginated(
        api.list_appeals(rating["id"], headers=ADMIN_HEADERS)
    )
    assert appeals == []


def test_appeal_without_new_information_rejected(api):
    """PRD section 3.4: "`new_information_codes` must be a non-empty list of
    registered document codes, and every code must be disjoint from the
    engagement's `received_document_codes` — an empty list, an unknown code,
    or any code the committee already saw is rejected with
    `ERR_NO_NEW_INFORMATION`."

    Design: Corner/validations/appeal_without_new_information_rejected
    """
    issuer = create_issuer(api)
    setup_active_criteria(api)
    engagement = create_engagement_solicited(api, issuer)
    engagement = accept_terms(api, engagement, issuer)
    # Receive AUDIT_FY explicitly so the appeal below cites a code the
    # committee provably saw, whatever else the required set contains.
    engagement = submit_document(
        api, engagement["id"], DOC_AUDIT_FY, issuer_headers(issuer)
    )
    engagement = submit_required_documents(api, engagement)
    submit_scorecard(api, engagement)
    engagement = get_engagement(api, engagement["id"])
    assert DOC_AUDIT_FY in engagement["received_document_codes"]

    outcome = run_committee(api, engagement)
    rating = outcome["rating"]
    resp = api.file_appeal(
        rating["id"],
        appeal_payload([DOC_AUDIT_FY]),
        headers=issuer_headers(issuer),
    )
    validate_error(resp, ApiErrorId.ERR_NO_NEW_INFORMATION)
    appeals, _meta = validate_paginated(
        api.list_appeals(rating["id"], headers=ADMIN_HEADERS)
    )
    assert appeals == []


def test_second_appeal_rejected(api):
    """PRD section 3.4: "Each rating carries at most one appeal; a second
    filing is rejected with `ERR_APPEAL_ALREADY_EXISTS`."

    Design: Corner/errors/second_appeal_rejected
    """
    ctx = setup_assigned_rating(api)
    rating = ctx["rating"]
    file_appeal(api, rating, ctx["issuer"], [DOC_PENSION_VALUATION])
    resp = api.file_appeal(
        rating["id"],
        appeal_payload([DOC_EPA_LITIGATION_REPORT]),
        headers=issuer_headers(ctx["issuer"]),
    )
    validate_error(resp, ApiErrorId.ERR_APPEAL_ALREADY_EXISTS)
    appeals, meta = validate_paginated(
        api.list_appeals(rating["id"], headers=ADMIN_HEADERS)
    )
    assert len(appeals) == 1 and meta["total_count"] == 1


def test_publish_blocked_while_appeal_pending(api):
    """PRD section 3.4: "the clock must stand strictly later than 120 hours
    after `assigned_at` — a publish attempted at or before the mark fails with
    `ERR_PUBLISH_WINDOW_NOT_ELAPSED` — and no `FILED` appeal may exist for the
    rating, on pain of `ERR_APPEAL_PENDING`."

    Design: Corner/errors/publish_blocked_while_appeal_pending
    """
    ctx = setup_assigned_rating(api)
    rating = ctx["rating"]
    file_appeal(api, rating, ctx["issuer"], [DOC_PENSION_VALUATION])
    advance_clock(api, "2026-09-08T00:00:00Z")  # past the 120-hour window
    resp = api.publish_rating(
        rating["id"],
        publish_payload(rationale="attempt with pending appeal"),
        headers=ANALYST_HEADERS,
    )
    validate_error(resp, ApiErrorId.ERR_APPEAL_PENDING)
    assert get_rating(api, rating["id"])["status"] == "ASSIGNED"
    assert get_engagement(api, ctx["engagement"]["id"])["status"] == (
        "RATING_ASSIGNED"
    )


def test_appeal_decide_twice_rejected(api):
    """PRD section 3.4: "A denied appeal leaves the rating `ASSIGNED`, logs
    `APPEAL_DENIED`, and clears the way to publication once the window has
    elapsed. Deciding an appeal that is no longer `FILED` is rejected with
    `ERR_APPEAL_STATE_INVALID`."

    Design: Corner/state_machines/appeal_decide_twice_rejected
    """
    ctx = setup_assigned_rating(api)
    rating = ctx["rating"]
    appeal = file_appeal(api, rating, ctx["issuer"], [DOC_PENSION_VALUATION])
    decide_appeal(
        api, appeal, decision="DENIED", rationale="information not material"
    )
    resp = api.decide_appeal(
        appeal["id"],
        {"decision": "UPHELD", "rationale": "second thoughts"},
        headers=CHAIR_HEADERS,
    )
    validate_error(resp, ApiErrorId.ERR_APPEAL_STATE_INVALID)
    current = validate_success(
        api.get_appeal(appeal["id"], headers=ADMIN_HEADERS), 200
    )
    assert current["status"] == "DENIED"
    assert get_rating(api, rating["id"])["status"] == "ASSIGNED"


def test_appeal_state_precondition_beats_window_temporal(api):
    """PRD section 2.10: "A single request can fail several checks at once, so
    the server evaluates its checks in a fixed priority order and reports the
    earliest failure: the lower-numbered check always wins over a
    higher-numbered one." — state permission (sixth) precedes the temporal
    windows (ninth).
    PRD section 3.4: "a filing against a rating in any other state fails with
    `ERR_RATING_STATE_INVALID`."

    Design: Difficulty/priority_pair_validation_conflict/appeal_state_precondition_beats_window_temporal
    """
    ctx = setup_published_rating(api)
    rating = ctx["rating"]
    advance_clock(api, "2026-10-01T00:00:00Z")  # window long gone as well
    resp = api.file_appeal(
        rating["id"],
        appeal_payload([DOC_PENSION_VALUATION]),
        headers=issuer_headers(ctx["issuer"]),
    )
    # Both the state rule (rating PUBLISHED) and the temporal rule (window
    # closed) are violated; priority six must beat priority nine.
    validate_error(resp, ApiErrorId.ERR_RATING_STATE_INVALID)
    assert resp.json()["data"]["error_id"] != "ERR_APPEAL_WINDOW_CLOSED"
    appeals, _meta = validate_paginated(
        api.list_appeals(rating["id"], headers=ADMIN_HEADERS)
    )
    assert appeals == []


def test_engagement_appeal_re_deliberation_cycle(api):
    """PRD section 3.4: "An upheld appeal is decisive: the rating moves
    `ASSIGNED` → `REMANDED`, a terminal state, the engagement returns
    `RATING_ASSIGNED` → `COMMITTEE_READY` to re-deliberate in light of the new
    information — the analyst may supersede the scorecard and the chair may
    convene a fresh committee — and an `APPEAL_UPHELD` notification is
    logged."
    PRD section 3.3: "a new session on the same engagement must respect a
    24-hour cooling-off ... though a gap of exactly 24 hours is allowed".

    Design: Difficulty/non_linear_state_machine/engagement_appeal_re_deliberation_cycle
    """
    ctx = setup_assigned_rating(api)  # outcome A, window 09-02 10:00-12:00
    rating = ctx["rating"]
    appeal = file_appeal(api, rating, ctx["issuer"], [DOC_PENSION_VALUATION])
    decide_appeal(
        api, appeal, decision="UPHELD",
        rationale="Pension valuation is material new information",
    )

    remanded = get_rating(api, rating["id"])
    assert remanded["status"] == "REMANDED", "the appealed rating dies terminal"
    engagement = get_engagement(api, ctx["engagement"]["id"])
    assert engagement["status"] == "COMMITTEE_READY", (
        "the engagement cycles back for re-deliberation"
    )

    # The second session starts exactly 24h after the first session's end.
    start_at, end_at = next_session_window(ctx["session"])
    assert start_at == "2026-09-03T12:00:00Z"
    session2 = schedule_session(
        api, engagement, start_at=start_at, end_at=end_at
    )
    session2 = open_session(api, session2, open_at="2026-09-03T12:30:00Z")
    cast_votes(
        api, session2["id"],
        [("voter-1", "BBB"), ("voter-2", "BBB"), ("voter-3", "BBB")],
    )
    closed = close_session(api, session2)
    assert closed["status"] == "COMPLETED"

    assert get_engagement(api, engagement["id"])["status"] == "RATING_ASSIGNED"
    ratings = get_ratings_for_engagement(api, engagement["id"])
    assert len(ratings) == 2, "the cycle creates a new Rating"
    assert ratings[0]["id"] == rating["id"]
    assert ratings[0]["status"] == "REMANDED", "the remanded rating stays dead"
    assert ratings[1]["notch"] == "BBB"
    assert ratings[1]["status"] == "ASSIGNED"
