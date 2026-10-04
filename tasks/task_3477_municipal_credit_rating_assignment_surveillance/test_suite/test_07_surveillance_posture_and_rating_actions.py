"""Surveillance disclosure, posture derivation, and rating actions.

Covers the annual obligation roll, the strict sweep threshold at the due
instant, the parallel publication/posture axes, the posture gates on
AFFIRM/UPGRADE, the adjacent-notch rule, immediate consistency, rating
action OCC, and the double-submission guard (PRD sections 2.2, 2.6, 3.5).
"""

from datetime import datetime, timezone

from test_helpers import (
    OFFICER_HEADERS,
    ApiErrorId,
    advance_clock,
    get_obligations,
    get_rating,
    issuer_headers,
    post_rating_action,
    rating_action_payload,
    setup_published_rating,
    submit_obligation,
    validate_error,
    validate_success,
)


def _instant(value):
    """Parse an ISO 8601 UTC timestamp for representation-agnostic equality."""
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(
        timezone.utc
    )


def test_rating_parallel_axes_independence(api):
    """PRD section 3.5: "Each published rating carries a **surveillance
    posture**, a parallel state axis that evolves independently of the
    publication axis. The posture derives from the rating's obligations in
    open states: it is `DELINQUENT` when any obligation is `DELINQUENT`;
    otherwise `GRACE` when any obligation is `OVERDUE`; otherwise `CURRENT`."
    PRD section 3.5: "Each submission while the rating is `PUBLISHED` then
    creates the next annual period: `period_index` increments by one,
    `fiscal_year_end` advances by exactly one calendar year, and `due_at` is
    again set 210 days out."

    Design: Difficulty/non_linear_state_machine/rating_parallel_axes_independence
    """
    ctx = setup_published_rating(api)  # published 2026-09-08, notch A
    rating = ctx["rating"]
    obligation = ctx["obligations"][0]

    # One day past due_at (2028-01-26): the obligation flips OVERDUE.
    advance_clock(api, "2028-01-27T00:00:00Z")
    mid = get_rating(api, rating["id"])
    assert mid["status"] == "PUBLISHED"
    assert mid["surveillance_posture"] == "GRACE", (
        "the posture axis moved while the publication axis stayed put"
    )

    cured = submit_obligation(api, obligation, ctx["issuer"])
    assert cured["status"] == "SUBMITTED_LATE"
    end = get_rating(api, rating["id"])
    assert end["status"] == "PUBLISHED"
    assert end["surveillance_posture"] == "CURRENT", (
        "the posture axis recovered; the publication axis never moved"
    )

    obligations = get_obligations(api, rating["id"])
    assert len(obligations) == 2
    nxt = obligations[1]
    assert nxt["period_index"] == 2
    assert _instant(nxt["fiscal_year_end"]) == _instant("2028-06-30T00:00:00Z")
    assert _instant(nxt["due_at"]) == _instant("2029-01-26T00:00:00Z")


def test_next_obligation_period_rolls_forward_annually(api):
    """PRD section 3.5: "An obligation still `PENDING`, submitted at or before
    its `due_at`, becomes `SUBMITTED_ON_TIME`."
    PRD section 3.5: "Each submission while the rating is `PUBLISHED` then
    creates the next annual period: `period_index` increments by one,
    `fiscal_year_end` advances by exactly one calendar year, and `due_at` is
    again set 210 days out."

    Design: Corner/calculations/next_obligation_period_rolls_forward_annually
    """
    ctx = setup_published_rating(api)
    rating = ctx["rating"]
    obligation = ctx["obligations"][0]

    advance_clock(api, "2027-07-15T00:00:00Z")  # after FYE, before due_at
    submitted = submit_obligation(api, obligation, ctx["issuer"])
    assert submitted["status"] == "SUBMITTED_ON_TIME"

    obligations = get_obligations(api, rating["id"])
    assert len(obligations) == 2
    nxt = obligations[1]
    assert nxt["period_index"] == 2
    assert _instant(nxt["fiscal_year_end"]) == _instant("2028-06-30T00:00:00Z")
    assert _instant(nxt["due_at"]) == _instant("2029-01-26T00:00:00Z")
    assert nxt["status"] == "PENDING"
    assert get_rating(api, rating["id"])["surveillance_posture"] == "CURRENT"


def test_obligation_still_pending_at_exact_due_instant(api):
    """PRD section 3.5: "Every sweep comparison is strict: when the clock
    stands exactly at `due_at`, the obligation remains `PENDING`."

    Design: Corner/calculations/obligation_still_pending_at_exact_due_instant
    """
    ctx = setup_published_rating(api)
    rating = ctx["rating"]
    obligation = ctx["obligations"][0]

    advance_clock(api, "2028-01-26T00:00:00Z")  # exactly == due_at
    current = validate_success(
        api.get_obligation(obligation["id"], headers=OFFICER_HEADERS), 200
    )
    assert current["status"] == "PENDING", "the flip requires clock > due_at"
    assert get_rating(api, rating["id"])["surveillance_posture"] == "CURRENT"


def test_upgrade_in_grace_posture_rejected(api):
    """PRD section 3.5: "`AFFIRM` keeps the current notch and is permitted
    while the posture is `CURRENT` or `GRACE`; against a `DELINQUENT` posture
    it fails with `ERR_AFFIRM_BLOCKED_BY_POSTURE`. `UPGRADE` is stricter,
    requiring a `CURRENT` posture and failing otherwise with
    `ERR_UPGRADE_BLOCKED_BY_POSTURE`."

    Design: Corner/errors/upgrade_in_grace_posture_rejected
    """
    ctx = setup_published_rating(api)  # notch A
    rating = ctx["rating"]
    advance_clock(api, "2028-01-27T00:00:00Z")  # obligation OVERDUE -> GRACE
    version = get_rating(api, rating["id"])["version"]

    upgrade = api.post_rating_action(
        rating["id"],
        rating_action_payload(
            "UPGRADE", version, new_notch="AA",
            rationale="upgrade attempt in grace",
        ),
        headers=OFFICER_HEADERS,
    )
    validate_error(upgrade, ApiErrorId.ERR_UPGRADE_BLOCKED_BY_POSTURE)

    affirmed = post_rating_action(
        api, rating, "AFFIRM",
        expected_rating_version=version,
        rationale="affirmation permitted in grace",
    )
    assert affirmed["notch"] == "A"
    assert affirmed["version"] == version + 1


def test_affirm_blocked_when_posture_delinquent(api):
    """PRD section 3.5: "`AFFIRM` keeps the current notch and is permitted
    while the posture is `CURRENT` or `GRACE`; against a `DELINQUENT` posture
    it fails with `ERR_AFFIRM_BLOCKED_BY_POSTURE`."
    PRD section 3.5: "`UPGRADE` and `DOWNGRADE` each move the notch exactly
    one step on the seven-step scale — one step better or one step worse — and
    any other `new_notch` is rejected with `ERR_NOTCH_STEP_INVALID`."

    Design: Difficulty/cross_entity_state_dependency/affirm_blocked_when_posture_delinquent
    """
    ctx = setup_published_rating(api)  # notch A
    rating = ctx["rating"]
    # 2028-02-26 is more than 30 days past due_at 2028-01-26: DELINQUENT.
    advance_clock(api, "2028-02-26T00:00:00Z")
    state = get_rating(api, rating["id"])
    assert state["surveillance_posture"] == "DELINQUENT"
    version = state["version"]

    affirm = api.post_rating_action(
        rating["id"],
        rating_action_payload(
            "AFFIRM", version, rationale="annual surveillance affirm"
        ),
        headers=OFFICER_HEADERS,
    )
    validate_error(affirm, ApiErrorId.ERR_AFFIRM_BLOCKED_BY_POSTURE)

    downgraded = post_rating_action(
        api, rating, "DOWNGRADE",
        expected_rating_version=version,
        new_notch="BBB",
        rationale="non-disclosure downgrade",
    )
    assert downgraded["notch"] == "BBB", "exactly one step worse"
    assert downgraded["version"] == version + 1
    assert downgraded["status"] == "PUBLISHED", (
        "the gate is action-specific, not a blanket lock"
    )


def test_notch_step_two_away_rejected(api):
    """PRD section 3.5: "`UPGRADE` and `DOWNGRADE` each move the notch exactly
    one step on the seven-step scale — one step better or one step worse — and
    any other `new_notch` is rejected with `ERR_NOTCH_STEP_INVALID`."

    Design: Corner/errors/notch_step_two_away_rejected
    """
    ctx = setup_published_rating(api)  # notch A, posture CURRENT
    rating = ctx["rating"]
    version = get_rating(api, rating["id"])["version"]
    resp = api.post_rating_action(
        rating["id"],
        rating_action_payload(
            "DOWNGRADE", version, new_notch="BB",
            rationale="two-step jump attempt",
        ),
        headers=OFFICER_HEADERS,
    )
    validate_error(resp, ApiErrorId.ERR_NOTCH_STEP_INVALID)
    current = get_rating(api, rating["id"])
    assert current["notch"] == "A"
    assert current["version"] == version


def test_rating_action_response_reflects_mutation_immediately(api):
    """PRD section 2.2: "Unless otherwise noted, operations that create or
    modify a resource will return the created or updated resource object in
    the data field."
    PRD section 3.5: "A successful affirmation, upgrade, or downgrade leaves
    the rating `PUBLISHED`, appends a `notch_history` entry whose cause is
    `SURVEILLANCE_ACTION`, logs a `RATING_ACTION` notification, and increments
    the rating's `version`."

    Design: Corner/consistency_model/rating_action_response_reflects_mutation_immediately
    """
    ctx = setup_published_rating(api)  # notch A
    rating = ctx["rating"]
    version = get_rating(api, rating["id"])["version"]
    resp = api.post_rating_action(
        rating["id"],
        rating_action_payload(
            "DOWNGRADE", version, new_notch="BBB", new_outlook="NEGATIVE",
            rationale="budgetary deterioration",
        ),
        headers=OFFICER_HEADERS,
    )
    data = validate_success(resp, 200)
    assert data["notch"] == "BBB"
    assert data["outlook"] == "NEGATIVE"
    assert data["version"] == version + 1

    reread = get_rating(api, rating["id"])
    assert reread["notch"] == "BBB", "no read-your-write lag"
    assert reread["version"] == version + 1
    last = reread["notch_history"][-1]
    assert last["notch"] == "BBB"
    assert last["cause"] == "SURVEILLANCE_ACTION"


def test_occ_stale_rating_version_on_action_rejected(api):
    """PRD section 2.6: "Posting a surveillance rating action (the
    rating-actions endpoint, `POST /muni/ratings/{id}/actions`) requires
    `expected_rating_version` holding the rating's `version` as the client
    last observed it, because each action supersedes the rating's previously
    published state as the basis for the next. A mismatch with the rating's
    current `version` is rejected with `ERR_STALE_RATING_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_rating_version_on_action_rejected
    """
    ctx = setup_published_rating(api)  # notch A
    rating = ctx["rating"]
    version = get_rating(api, rating["id"])["version"]

    downgrade = api.post_rating_action(
        rating["id"],
        rating_action_payload(
            "DOWNGRADE", version, new_notch="BBB", rationale="first action wins"
        ),
        headers=OFFICER_HEADERS,
    )
    data = validate_success(downgrade, 200)
    assert data["notch"] == "BBB"
    assert data["version"] == version + 1

    replay = api.post_rating_action(
        rating["id"],
        rating_action_payload("AFFIRM", version, rationale="stale replay"),
        headers=OFFICER_HEADERS,
    )
    validate_error(replay, ApiErrorId.ERR_STALE_RATING_VERSION)
    final = get_rating(api, rating["id"])
    assert final["notch"] == "BBB", "only the first action landed"
    assert final["version"] == version + 1


def test_double_submit_obligation_rejected(api):
    """PRD section 3.5: "An obligation already resting in `SUBMITTED_ON_TIME`
    or `SUBMITTED_LATE` accepts no further submission, refusing with
    `ERR_OBLIGATION_STATE_INVALID`."

    Design: Corner/errors/double_submit_obligation_rejected
    """
    ctx = setup_published_rating(api)
    obligation = ctx["obligations"][0]
    advance_clock(api, "2027-07-15T00:00:00Z")
    submitted = submit_obligation(api, obligation, ctx["issuer"])
    assert submitted["status"] == "SUBMITTED_ON_TIME"

    # A second submission by the owning issuer must be refused.
    resp = api.submit_obligation(
        obligation["id"], headers=issuer_headers(ctx["issuer"])
    )
    validate_error(resp, ApiErrorId.ERR_OBLIGATION_STATE_INVALID)
    current = validate_success(
        api.get_obligation(obligation["id"], headers=OFFICER_HEADERS), 200
    )
    assert current["status"] == "SUBMITTED_ON_TIME"
    assert current["submitted_at"] == submitted["submitted_at"]
