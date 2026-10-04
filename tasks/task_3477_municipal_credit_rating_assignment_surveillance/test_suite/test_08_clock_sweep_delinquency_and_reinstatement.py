"""The time-driven sweep, the delinquency cascade, and reinstatement.

Covers the pinned sweep evaluation order (obligation flips, then
non-disclosure withdrawal, then posture recomputation excluding the
withdrawn), the hop-by-hop escalation across clock advances, the late-cure
path out of DEFAULTED, the delinquent-issuer solicitation gate, and the
reinstatement gates and effects (PRD sections 3.1 and 3.5).
"""

from datetime import datetime, timezone

from test_helpers import (
    ADMIN_HEADERS,
    OFFICER_HEADERS,
    ApiErrorId,
    advance_clock,
    assert_notification_order,
    create_engagement_unsolicited,
    cure_defaulted_obligation,
    engagement_payload,
    get_issuer,
    get_notifications,
    get_obligations,
    get_rating,
    issuer_headers,
    notification_events,
    setup_published_rating,
    setup_withdrawn_non_disclosure,
    submit_obligation,
    validate_error,
    validate_success,
    withdraw_rating,
)


def _instant(value):
    """Parse an ISO 8601 UTC timestamp for representation-agnostic equality."""
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(
        timezone.utc
    )


def test_nondisclosure_sweep_evaluation_order_pinned(api):
    """PRD section 3.5: "A single clock jump walks one obligation through as
    many flips as its thresholds allow, in that order, within the same sweep.
    Second, for every obligation that flipped to `DEFAULTED`, the sweep
    withdraws its rating: the rating moves `PUBLISHED` → `WITHDRAWN` with
    `withdraw_reason` `NON_DISCLOSURE`, `withdrawn_at` stamped from the clock,
    the current notch frozen into `notch_at_withdrawal`, and a
    `RATING_WITHDRAWN` notification logged after the delinquency notification.
    Third, postures are recomputed for ratings still `PUBLISHED`; ratings
    withdrawn in the same sweep are excluded, keeping their frozen
    `DELINQUENT` posture."

    Design: Difficulty/combinatorial_formula/nondisclosure_sweep_evaluation_order_pinned
    """
    ctx = setup_published_rating(api)  # obligation due 2028-01-26
    rating = ctx["rating"]
    obligation = ctx["obligations"][0]

    # One jump past all three thresholds (+30d 2028-02-25, +60d 2028-03-26).
    advance_clock(api, "2028-03-27T00:00:00Z")

    ob = validate_success(
        api.get_obligation(obligation["id"], headers=OFFICER_HEADERS), 200
    )
    assert ob["status"] == "DEFAULTED"

    current = get_rating(api, rating["id"])
    assert current["status"] == "WITHDRAWN"
    assert current["withdraw_reason"] == "NON_DISCLOSURE"
    assert _instant(current["withdrawn_at"]) == _instant("2028-03-27T00:00:00Z")
    assert current["surveillance_posture"] == "DELINQUENT", (
        "frozen: step three of the sweep excludes ratings withdrawn in step "
        "two, so the posture is not recomputed to CURRENT"
    )
    assert get_issuer(api, ctx["issuer"]["id"])["delinquent_flag"] is True

    log = get_notifications(api, ctx["issuer"]["id"])
    assert_notification_order(
        log, ["OBLIGATION_DELINQUENT", "RATING_WITHDRAWN"]
    )


def test_clock_delinquency_stepwise_cascade(api):
    """PRD section 3.5: "a `PENDING` obligation whose `due_at` is strictly
    behind the clock flips to `OVERDUE`; an `OVERDUE` obligation more than 30
    days past its `due_at` flips to `DELINQUENT` and logs an
    `OBLIGATION_DELINQUENT` notification; a `DELINQUENT` obligation more than
    60 days past its `due_at` flips to `DEFAULTED` and sets the issuer's
    `delinquent_flag` true — a flag the intermediate `DELINQUENT` hop does not
    touch."

    Design: Difficulty/transitive_cascade/clock_delinquency_stepwise_cascade
    """
    ctx = setup_published_rating(api)  # obligation due 2028-01-26
    rating = ctx["rating"]
    obligation = ctx["obligations"][0]

    # Hop 1: strictly past due_at, within the 30-day grace.
    advance_clock(api, "2028-01-27T00:00:00Z")
    ob = validate_success(
        api.get_obligation(obligation["id"], headers=OFFICER_HEADERS), 200
    )
    assert ob["status"] == "OVERDUE"
    hop1 = get_rating(api, rating["id"])
    assert hop1["status"] == "PUBLISHED"
    assert hop1["surveillance_posture"] == "GRACE"

    # Hop 2: strictly past due_at + 30 days (2028-02-25).
    advance_clock(api, "2028-02-26T00:00:00Z")
    ob = validate_success(
        api.get_obligation(obligation["id"], headers=OFFICER_HEADERS), 200
    )
    assert ob["status"] == "DELINQUENT"
    hop2 = get_rating(api, rating["id"])
    assert hop2["status"] == "PUBLISHED"
    assert hop2["surveillance_posture"] == "DELINQUENT"
    assert "OBLIGATION_DELINQUENT" in notification_events(
        get_notifications(api, ctx["issuer"]["id"])
    )

    # Hop 3: strictly past due_at + 60 days (2028-03-26).
    advance_clock(api, "2028-03-27T00:00:00Z")
    ob = validate_success(
        api.get_obligation(obligation["id"], headers=OFFICER_HEADERS), 200
    )
    assert ob["status"] == "DEFAULTED"
    hop3 = get_rating(api, rating["id"])
    assert hop3["status"] == "WITHDRAWN"
    assert hop3["withdraw_reason"] == "NON_DISCLOSURE"
    assert get_issuer(api, ctx["issuer"]["id"])["delinquent_flag"] is True
    assert_notification_order(
        get_notifications(api, ctx["issuer"]["id"]),
        ["OBLIGATION_DELINQUENT", "RATING_WITHDRAWN"],
    )


def test_obligation_submit_from_defaulted_becomes_submitted_late(api):
    """PRD section 3.5: "Even a `DEFAULTED` obligation can be cured late, and
    that late cure is what makes reinstatement possible."
    PRD section 3.5: "while the rating is `WITHDRAWN`, no new period is
    created."
    PRD section 3.5: "The issuer's `delinquent_flag` stays true while any
    obligation of any of the issuer's ratings sits in `DEFAULTED`, and it
    clears once all such obligations have been cured to `SUBMITTED_LATE`."

    Design: Corner/state_machines/obligation_submit_from_defaulted_becomes_submitted_late
    """
    ctx = setup_withdrawn_non_disclosure(api)
    obligation = ctx["obligations"][0]
    assert obligation["status"] == "DEFAULTED"

    cured = submit_obligation(api, obligation, ctx["issuer"])
    assert cured["status"] == "SUBMITTED_LATE"

    assert get_issuer(api, ctx["issuer"]["id"])["delinquent_flag"] is False
    assert get_rating(api, ctx["rating"]["id"])["status"] == "WITHDRAWN", (
        "curing the obligation does not itself reinstate the rating"
    )
    obligations = get_obligations(api, ctx["rating"]["id"])
    assert len(obligations) == 1, "no next period while WITHDRAWN"


def test_delinquent_issuer_new_engagement_rejected(api):
    """PRD section 3.1: "One structural guard applies at creation: a
    `SOLICITED` engagement may not be opened while the issuer's
    `delinquent_flag` is set — the attempt is rejected with
    `ERR_ISSUER_DELINQUENT`."

    Design: Corner/errors/delinquent_issuer_new_engagement_rejected
    """
    ctx = setup_withdrawn_non_disclosure(api)
    issuer = get_issuer(api, ctx["issuer"]["id"])
    assert issuer["delinquent_flag"] is True

    resp = api.create_engagement(
        engagement_payload(issuer["id"]), headers=issuer_headers(issuer)
    )
    validate_error(resp, ApiErrorId.ERR_ISSUER_DELINQUENT)

    # The gate is solicitation-scoped: the agency's own initiative still opens.
    unsolicited = create_engagement_unsolicited(api, issuer)
    assert unsolicited["status"] == "INFORMATION_GATHERING"


def test_rating_withdraw_then_reinstate_restores_notch(api):
    """PRD section 3.5: "A successful reinstatement restores `notch` from
    `notch_at_withdrawal`, recomputes the posture to `CURRENT`, schedules the
    next annual disclosure period when no obligation of the rating remains in
    an open state (`PENDING`, `OVERDUE`, `DELINQUENT`, or `DEFAULTED`) — the
    new period's `period_index` continuing from the last — appends a
    `notch_history` entry whose cause is `REINSTATEMENT`, logs a
    `RATING_REINSTATED` notification, and increments the rating's `version`."

    Design: Corner/state_machines/rating_withdraw_then_reinstate_restores_notch
    """
    ctx = setup_withdrawn_non_disclosure(api)  # notch A at withdrawal
    cure_defaulted_obligation(api, ctx)

    resp = api.reinstate_rating(ctx["rating"]["id"], headers=OFFICER_HEADERS)
    data = validate_success(resp, 200)
    assert data["status"] == "PUBLISHED"
    assert data["notch"] == "A", "the notch frozen at withdrawal is restored"
    assert data["surveillance_posture"] == "CURRENT"
    last = data["notch_history"][-1]
    assert last["cause"] == "REINSTATEMENT"
    assert last["notch"] == "A"

    obligations = get_obligations(api, ctx["rating"]["id"])
    assert len(obligations) == 2, "the annual obligation chain resumes"
    nxt = obligations[1]
    assert nxt["period_index"] == 2
    assert _instant(nxt["fiscal_year_end"]) == _instant("2028-06-30T00:00:00Z")

    events = notification_events(get_notifications(api, ctx["issuer"]["id"]))
    assert "RATING_REINSTATED" in events


def test_reinstate_after_window_rejected(api):
    """PRD section 3.5: "The clock must stand no later than 180 days after
    `withdrawn_at`; later attempts fail with `ERR_REINSTATE_WINDOW_EXPIRED`."

    Design: Corner/errors/reinstate_after_window_rejected
    """
    ctx = setup_withdrawn_non_disclosure(api)  # withdrawn_at 2028-03-27
    cure_defaulted_obligation(api, ctx)
    # withdrawn_at + 180 days is 2028-09-23; one day later is out of window.
    advance_clock(api, "2028-09-24T00:00:00Z")
    resp = api.reinstate_rating(ctx["rating"]["id"], headers=OFFICER_HEADERS)
    validate_error(resp, ApiErrorId.ERR_REINSTATE_WINDOW_EXPIRED)
    assert get_rating(api, ctx["rating"]["id"])["status"] == "WITHDRAWN"


def test_reinstate_issuer_request_withdrawal_rejected(api):
    """PRD section 3.5: "Reinstatement, performed by a `SurveillanceOfficer`,
    returns a rating from `WITHDRAWN` to `PUBLISHED` — but only for
    non-disclosure withdrawals: any other `withdraw_reason` is rejected with
    `ERR_REINSTATE_NOT_PERMITTED`".

    Design: Corner/errors/reinstate_issuer_request_withdrawal_rejected
    """
    ctx = setup_published_rating(api)  # notch A
    advance_clock(api, "2026-09-20T00:00:00Z")
    withdrawn = withdraw_rating(api, ctx["rating"], "ISSUER_REQUEST")
    assert withdrawn["status"] == "WITHDRAWN"

    resp = api.reinstate_rating(ctx["rating"]["id"], headers=OFFICER_HEADERS)
    validate_error(resp, ApiErrorId.ERR_REINSTATE_NOT_PERMITTED)
    current = get_rating(api, ctx["rating"]["id"])
    assert current["status"] == "WITHDRAWN"
    assert current["notch_at_withdrawal"] == "A"


def test_reinstate_with_unresolved_obligations_rejected(api):
    """PRD section 3.5: "And every disclosure obligation of the rating must be
    resolved — each in `SUBMITTED_ON_TIME` or `SUBMITTED_LATE` — or the
    reinstatement fails with `ERR_UNRESOLVED_OBLIGATIONS`."

    Design: Corner/errors/reinstate_with_unresolved_obligations_rejected
    """
    ctx = setup_withdrawn_non_disclosure(api)  # obligation still DEFAULTED
    advance_clock(api, "2028-03-28T00:00:00Z")  # inside the 180-day window
    resp = api.reinstate_rating(ctx["rating"]["id"], headers=OFFICER_HEADERS)
    validate_error(resp, ApiErrorId.ERR_UNRESOLVED_OBLIGATIONS)
    assert get_rating(api, ctx["rating"]["id"])["status"] == "WITHDRAWN"
