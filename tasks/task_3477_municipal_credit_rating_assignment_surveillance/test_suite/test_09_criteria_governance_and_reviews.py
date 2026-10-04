"""Criteria activation fan-out and the portfolio review pipeline.

Covers the activation cascade (supersede, review-item fan-out,
review_pending, issuer notification, pin retention), the review-item
lifecycle and its state guards, the 90-day escalation checkpoint with its
strict boundary, and the escalated-review scheduling block (PRD sections
2.10, 3.3 and 3.6).
"""

from datetime import datetime, timezone

from test_helpers import (
    CHAIR_HEADERS,
    OFFICER_HEADERS,
    ApiErrorId,
    advance_clock,
    begin_review,
    create_criteria_version,
    get_rating,
    get_review_items,
    iso_add_days,
    notification_events,
    get_notifications,
    rating_action_payload,
    review_complete_payload,
    schedule_session,
    session_payload,
    setup_committee_ready_engagement,
    setup_published_rating,
    setup_with_escalated_review,
    setup_with_pending_review,
    validate_error,
    validate_paginated,
    validate_success,
)


def _instant(value):
    """Parse an ISO 8601 UTC timestamp for representation-agnostic equality."""
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(
        timezone.utc
    )


def test_criteria_activation_portfolio_cascade(api):
    """PRD section 3.6: "At most one version is `ACTIVE` per
    jurisdiction-and-credit segment: the activation supersedes the segment's
    prior `ACTIVE` version, moving it to the terminal `SUPERSEDED` state."
    PRD section 3.6: "for each one creates a `CriteriaReviewItem` in `PENDING`
    whose `criteria_version_id` names the newly activated version, whose
    `due_at` is 90 days after that version's `activated_at`, sets the rating's
    `review_pending` true, and logs a `REVIEW_OPENED` notification to the
    rating's issuer."
    PRD section 3.6: "Sessions and scorecards keep their pinned versions
    regardless — activation never re-points work already scheduled or scored."

    Design: Difficulty/transitive_cascade/criteria_activation_portfolio_cascade
    """
    ctx = setup_published_rating(api)  # published 2026-09-08, pinned cv
    pinned = ctx["criteria_version"]

    successor = create_criteria_version(
        api,
        version_label="GO-2026.2",
        w_economy=0.25,
        w_management=0.15,
        w_budgetary_performance=0.20,
        w_flexibility=0.15,
        w_liquidity=0.10,
        w_debt_profile=0.15,
    )
    activated = validate_success(
        api.activate_criteria_version(successor["id"], headers=OFFICER_HEADERS),
        200,
    )
    assert activated["status"] == "ACTIVE"

    prior = validate_success(
        api.get_criteria_version(pinned["id"], headers=OFFICER_HEADERS), 200
    )
    assert prior["status"] == "SUPERSEDED"

    items, meta = validate_paginated(
        api.list_review_items(
            headers=OFFICER_HEADERS,
            params={"criteria_version_id": successor["id"]},
        )
    )
    assert meta["total_count"] == 1
    item = items[0]
    assert item["criteria_version_id"] == successor["id"]
    assert item["rating_id"] == ctx["rating"]["id"]
    assert item["status"] == "PENDING"
    # activated_at 2026-09-08T00:00:00Z + 90 days.
    assert _instant(item["due_at"]) == _instant("2026-12-07T00:00:00Z")

    rating = get_rating(api, ctx["rating"]["id"])
    assert rating["review_pending"] is True
    assert rating["criteria_version_id"] == pinned["id"], (
        "the rating's pin survives the activation"
    )

    log = get_notifications(api, ctx["issuer"]["id"])
    opened = [
        entry for entry in log
        if entry["event_type"] == "REVIEW_OPENED"
        and entry["reference_id"] == item["id"]
    ]
    assert opened, "the fan-out logs REVIEW_OPENED referencing the item"


def test_review_item_begin_complete_happy_path(api):
    """PRD section 3.6: "Beginning a review moves an item `PENDING` →
    `IN_REVIEW`, or `ESCALATED` → `IN_REVIEW`" and "`NO_ACTION` closes the
    item `IN_REVIEW` → `COMPLETED_NO_ACTION`."
    PRD section 3.6: "Either completion stamps `completed_at` from the clock,
    recomputes the rating's `review_pending` — true while any of its items
    remains `PENDING`, `IN_REVIEW`, or `ESCALATED` — logs a
    `REVIEW_COMPLETED` notification, and increments the item's `version`."

    Design: Corner/state_machines/review_item_begin_complete_happy_path
    """
    ctx = setup_with_pending_review(api)
    item = ctx["review_item"]

    begun = begin_review(api, item)
    assert begun["status"] == "IN_REVIEW"

    resp = api.complete_review_item(
        item["id"],
        review_complete_payload(
            "NO_ACTION", rationale="rating affirmed under new criteria"
        ),
        headers=OFFICER_HEADERS,
    )
    completed = validate_success(resp, 200)
    assert completed["status"] == "COMPLETED_NO_ACTION"

    rating = get_rating(api, ctx["rating"]["id"])
    assert rating["review_pending"] is False
    assert rating["notch"] == "A", "a no-action completion moves nothing"

    events = notification_events(get_notifications(api, ctx["issuer"]["id"]))
    assert "REVIEW_COMPLETED" in events


def test_review_item_escalates_after_90_days(api):
    """PRD section 3.6: "Meanwhile the clock sweep escalates any `PENDING`
    item whose `due_at` is strictly behind the clock to `ESCALATED` — items
    already `IN_REVIEW` are exempt from escalation".

    Design: Corner/cross_cutting_complexity_layers/review_item_escalates_after_90_days
    """
    ctx = setup_with_pending_review(api)
    item = ctx["review_item"]

    advance_clock(api, item["due_at"])  # exactly at the deadline
    at_due = validate_success(
        api.get_review_item(item["id"], headers=OFFICER_HEADERS), 200
    )
    assert at_due["status"] == "PENDING", "the escalation rule is strict >"

    advance_clock(api, iso_add_days(item["due_at"], 1))
    past_due = validate_success(
        api.get_review_item(item["id"], headers=OFFICER_HEADERS), 200
    )
    assert past_due["status"] == "ESCALATED"

    rating = get_rating(api, ctx["rating"]["id"])
    assert rating["review_pending"] is True


def test_review_complete_rating_action_without_notch_rejected(api):
    """PRD section 3.6: "`RATING_ACTION` additionally requires a `new_notch` —
    without one the completion fails with
    `ERR_REVIEW_OUTCOME_NOTCH_REQUIRED`".

    Design: Corner/errors/review_complete_rating_action_without_notch_rejected
    """
    ctx = setup_with_pending_review(api)
    item = begin_review(api, ctx["review_item"])
    resp = api.complete_review_item(
        item["id"],
        review_complete_payload("RATING_ACTION", rationale="missing the notch"),
        headers=OFFICER_HEADERS,
    )
    validate_error(resp, ApiErrorId.ERR_REVIEW_OUTCOME_NOTCH_REQUIRED)
    current = validate_success(
        api.get_review_item(item["id"], headers=OFFICER_HEADERS), 200
    )
    assert current["status"] == "IN_REVIEW"
    assert get_rating(api, ctx["rating"]["id"])["notch"] == "A"


def test_complete_pending_review_item_rejected(api):
    """PRD section 3.6: "Completing a review requires the item to be
    `IN_REVIEW`" and "beginning from any other state fails with
    `ERR_REVIEW_ITEM_STATE_INVALID`" — the same state guard covers complete.

    Design: Corner/errors/complete_pending_review_item_rejected
    """
    ctx = setup_with_pending_review(api)
    item = ctx["review_item"]
    assert item["status"] == "PENDING"
    resp = api.complete_review_item(
        item["id"],
        review_complete_payload("NO_ACTION", rationale="skipped begin"),
        headers=OFFICER_HEADERS,
    )
    validate_error(resp, ApiErrorId.ERR_REVIEW_ITEM_STATE_INVALID)
    current = validate_success(
        api.get_review_item(item["id"], headers=OFFICER_HEADERS), 200
    )
    assert current["status"] == "PENDING"


def test_action_blocked_while_review_pending(api):
    """PRD section 3.5: "An action is permitted only while the rating is
    `PUBLISHED`, failing otherwise with `ERR_RATING_STATE_INVALID`, and only
    while `review_pending` is false: a rating with any criteria review item in
    `PENDING`, `IN_REVIEW`, or `ESCALATED` refuses actions with
    `ERR_REVIEW_PENDING`."

    Design: Corner/errors/action_blocked_while_review_pending
    """
    ctx = setup_with_pending_review(api)
    rating = get_rating(api, ctx["rating"]["id"])
    assert rating["review_pending"] is True
    resp = api.post_rating_action(
        rating["id"],
        rating_action_payload(
            "AFFIRM", rating["version"],
            rationale="attempt during open review",
        ),
        headers=OFFICER_HEADERS,
    )
    validate_error(resp, ApiErrorId.ERR_REVIEW_PENDING)
    after = get_rating(api, rating["id"])
    assert after["notch"] == "A"
    item = validate_success(
        api.get_review_item(ctx["review_item"]["id"], headers=OFFICER_HEADERS),
        200,
    )
    assert item["status"] == "PENDING"


def test_escalated_review_blocks_committee_scheduling(api):
    """PRD section 3.3: "Scheduling is additionally blocked while any rating
    belonging to the engagement's issuer carries a criteria review item in
    `ESCALATED` — an unresolved escalation anywhere in the issuer's portfolio
    freezes new committee work with
    `ERR_ESCALATED_REVIEW_BLOCKS_SCHEDULING`."

    Design: Difficulty/cross_entity_state_dependency/escalated_review_blocks_committee_scheduling
    """
    ctx = setup_with_escalated_review(api)  # clock now past the item's due_at
    escalated = ctx["review_item"]
    assert escalated["status"] == "ESCALATED"

    # A second engagement of the same issuer reaches COMMITTEE_READY under
    # the now-ACTIVE successor criteria — every same-entity precondition
    # passes; only the sibling rating's escalation can block scheduling.
    ctx2 = setup_committee_ready_engagement(
        api,
        issuer=ctx["issuer"],
        criteria_version=ctx["successor_criteria"],
    )
    assert escalated["rating_id"] == ctx["rating"]["id"]
    assert ctx2["engagement"]["id"] != ctx["engagement"]["id"]
    assert ctx2["engagement"]["status"] == "COMMITTEE_READY"

    resp = api.schedule_session(
        ctx2["engagement"]["id"],
        session_payload(
            start_at="2026-12-09T10:00:00Z", end_at="2026-12-09T12:00:00Z"
        ),
        headers=CHAIR_HEADERS,
    )
    validate_error(resp, ApiErrorId.ERR_ESCALATED_REVIEW_BLOCKS_SCHEDULING)
