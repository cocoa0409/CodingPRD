"""Consent order lifecycle: withdrawal/reproposal cycle, finalization gate,
comment posting, expiry, monitoring-window adjacency, and 404s."""
from test_helpers import (
    ApiErrorId,
    CLOCK_EPOCH_ISO,
    TEST_USERS,
    UNKNOWN_UUID,
    add_days_iso,
    advance_clock,
    advance_investigation_to_state,
    api_client,
    consent_order_transition_payload,
    create_comment_payload,
    create_company,
    create_investigation,
    draft_consent_order,
    finalize_consent_order,
    get_investigation,
    get_latest_comment_period,
    get_order,
    get_success_data,
    parse_iso,
    post_comment,
    propose_consent_order,
    reset_clock_to_epoch,
    setup_monitored_order,
    setup_proposed_order,
    start_monitoring,
    transition_order,
    validate_error,
    validate_success,
    withdraw_consent_order,
    assert_comment_period,
)

_ADMIN = TEST_USERS["platform_admin_headers"]
_ATTORNEY = TEST_USERS["staff_attorney_headers"]
_COMMISSIONER = TEST_USERS["commissioner_headers"]


def test_consent_order_get_with_unknown_id_returns_404():
    """PRD section 2.9: "The full not-found vocabulary is:
    `ERR_SUBJECT_COMPANY_NOT_FOUND`, `ERR_INVESTIGATION_NOT_FOUND`,
    `ERR_CID_NOT_FOUND`, `ERR_CONSENT_ORDER_NOT_FOUND`,
    `ERR_COMMENT_PERIOD_NOT_FOUND`, `ERR_COMPLIANCE_REPORT_NOT_FOUND`,
    `ERR_VIOLATION_PENALTY_NOT_FOUND`, `ERR_JUDGMENT_NOT_FOUND`,
    `ERR_REDRESS_FUND_NOT_FOUND`, `ERR_CLAIMANT_NOT_FOUND`,
    `ERR_CLAIM_NOT_FOUND`, and `ERR_REFUND_CHECK_NOT_FOUND` — all HTTP 404."

    Design: Corner/entities/consent_order_get_with_unknown_id_returns_404
    """
    reset_clock_to_epoch()
    resp = api_client.get_consent_order(UNKNOWN_UUID, _COMMISSIONER)
    error_data = validate_error(resp, ApiErrorId.ERR_CONSENT_ORDER_NOT_FOUND)
    assert isinstance(error_data["message"], str) and error_data["message"].strip()


def test_consent_order_withdrawal_and_reproposal_cycle():
    """PRD section 3.3: "A `StaffAttorney` may withdraw an order from
    `IN_PUBLIC_COMMENT` back to `DRAFT` (again under
    `expected_consent_order_version`): the order's `OPEN` comment period is
    voided to `VOIDED`, `proposal_round` increments by 1, and the order's
    `version` increments."
    PRD section 3.3: "The withdrawal-and-reproposal cycle may repeat — each
    reproposal opens a fresh period stamped with the new round".
    PRD section 3.3: "the parent investigation bubbles from `SETTLED` to
    `CLOSED_ORDER_ENTERED`".

    Design: Difficulty/non_linear_state_machine/consent_order_withdrawal_and_reproposal_cycle
    """
    bundle = setup_proposed_order(
        monetary_relief_cents=2_000_000,
        conduct_prohibitions=["NO_HIDDEN_FEES"],
    )
    order_id = bundle["order"]["id"]
    inv_id = bundle["investigation"]["id"]
    period_1_id = bundle["comment_period"]["id"]

    post_comment(
        period_1_id,
        author_email="watcher@public.org",
        body="The conduct prohibitions are too narrow.",
    )
    withdraw_consent_order(order_id)
    propose_consent_order(order_id)

    # Round-2 period opened at the epoch closes exactly 30 days later.
    advance_clock("2026-10-01T00:00:00Z")
    finalized = transition_order(order_id, "FINAL")
    assert finalized["status"] == "FINAL"
    assert finalized["proposal_round"] == 2
    assert parse_iso(finalized["finalized_at"]) == parse_iso("2026-10-01T00:00:00Z")

    periods = get_success_data(api_client.list_comment_periods(order_id, _ATTORNEY))
    assert len(periods) == 2
    assert periods[0]["round"] == 1 and periods[0]["status"] == "VOIDED"
    assert periods[1]["round"] == 2 and periods[1]["status"] == "CLOSED"

    investigation = get_investigation(inv_id)
    assert investigation["status"] == "CLOSED_ORDER_ENTERED"


def test_finalize_requires_latest_comment_period_closed():
    """PRD section 3.3: "moving from `IN_PUBLIC_COMMENT` to `FINAL` requires
    the order's latest comment period — the one with the highest `round` — to
    be `CLOSED`; if it is still `OPEN`, the transition fails with
    `ERR_COMMENT_PERIOD_OPEN`."
    PRD section 2.5: "Any public comment period still `OPEN` whose `closes_at`
    instant has been reached or passed transitions to `CLOSED`."

    Design: Difficulty/cross_entity_state_dependency/finalize_requires_latest_comment_period_closed
    """
    bundle = setup_proposed_order(
        monetary_relief_cents=2_000_000,
        conduct_prohibitions=["NO_HIDDEN_FEES"],
    )
    order_id = bundle["order"]["id"]
    inv_id = bundle["investigation"]["id"]
    order_v2 = bundle["order"]["version"]

    # Clock still at the epoch: the round-1 period is OPEN.
    blocked = api_client.transition_consent_order(
        order_id,
        consent_order_transition_payload("FINAL", order_v2),
        _COMMISSIONER,
    )
    validate_error(blocked, ApiErrorId.ERR_COMMENT_PERIOD_OPEN)
    order_after = get_order(order_id)
    assert order_after["status"] == "IN_PUBLIC_COMMENT"
    assert order_after["version"] == order_v2, "rejected attempt must not advance the version"

    # The sweep closes the period at exactly closes_at (>= semantics).
    period = get_latest_comment_period(order_id)
    advance_clock(period["closes_at"])
    period_after = get_latest_comment_period(order_id)
    assert period_after["status"] == "CLOSED"

    finalized = validate_success(
        api_client.transition_consent_order(
            order_id,
            consent_order_transition_payload("FINAL", order_v2),
            _COMMISSIONER,
        ),
        200,
    )
    assert finalized["status"] == "FINAL"
    assert parse_iso(finalized["finalized_at"]) == parse_iso(period["closes_at"])
    assert get_investigation(inv_id)["status"] == "CLOSED_ORDER_ENTERED"


def test_comment_posting_appends_entry_and_increments_count():
    """PRD section 3.3: "Each filing appends an entry — `author_email`, `body`,
    and the logical filing time `submitted_at` — to the period's append-only
    `comments` array, grows `comment_count` by one, and increments the period's
    `version`."
    PRD section 3.3: "its `closes_at` falls exactly 30 days later."

    Design: Corner/endpoints/comment_posting_appends_entry_and_increments_count
    """
    bundle = setup_proposed_order()
    period_id = bundle["comment_period"]["id"]

    resp = api_client.post_comment(
        period_id,
        create_comment_payload(
            author_email="watcher@public.org", body="Support the order as drafted."
        ),
        _ADMIN,
    )
    period = validate_success(resp, 201)
    assert_comment_period(period)
    assert period["comment_count"] == 1
    assert period["comments"][0]["author_email"] == "watcher@public.org"
    assert period["comments"][0]["body"] == "Support the order as drafted."
    assert parse_iso(period["comments"][0]["submitted_at"]) == parse_iso(CLOCK_EPOCH_ISO), (
        "submitted_at must come from the logical clock (still at the epoch)"
    )
    assert period["status"] == "OPEN"
    assert parse_iso(period["closes_at"]) == parse_iso(add_days_iso(CLOCK_EPOCH_ISO, 30))


def test_comment_posted_to_closed_period_rejected():
    """PRD section 2.5: "At exactly `closes_at` the period is already closed —
    the open interval is half-open on its closing boundary — and further
    comments are rejected from that instant onward."
    PRD section 3.3: "a comment filed against a period that is `CLOSED` — or
    `VOIDED`, after a withdrawal — fails with `ERR_COMMENT_PERIOD_CLOSED`."

    Design: Corner/validations/comment_posted_to_closed_period_rejected
    """
    bundle = setup_proposed_order()
    order_id = bundle["order"]["id"]
    period_id = bundle["comment_period"]["id"]

    advance_clock("2026-10-01T00:00:00Z")
    resp = api_client.post_comment(
        period_id,
        create_comment_payload(
            author_email="late@public.org", body="Commenting at the close instant."
        ),
        _ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_COMMENT_PERIOD_CLOSED)

    periods = get_success_data(api_client.list_comment_periods(order_id, _ATTORNEY))
    assert periods[0]["status"] == "CLOSED"
    assert periods[0]["comment_count"] == 0


def test_consent_order_expired_is_terminal_and_rejects_further_transitions():
    """PRD section 2.5: "Any consent order in `IN_MONITORING` transitions to
    `EXPIRED` only once the clock is strictly later than the order's
    `monitoring_ends_at`."
    PRD section 3.3: "`EXPIRED` and `TERMINATED` are the order's terminal
    states".

    Design: Corner/state_machines/consent_order_expired_is_terminal_and_rejects_further_transitions
    """
    bundle = setup_monitored_order(monitoring_term_years=1)
    order_id = bundle["order"]["id"]
    # Monitoring opened 2026-10-01 with a 1-year term: ends 2027-10-01.
    advance_clock("2027-10-02T00:00:00Z")

    expired = get_order(order_id)
    assert expired["status"] == "EXPIRED", (
        f"sweep must expire the order once strictly past monitoring_ends_at, got {expired['status']}"
    )

    resp = api_client.transition_consent_order(
        order_id,
        consent_order_transition_payload("TERMINATED", expired["version"]),
        _COMMISSIONER,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    assert get_order(order_id)["status"] == "EXPIRED"


def test_monitoring_term_half_open_adjacency_allowed_but_overlap_rejected():
    """PRD section 3.4: "if another consent order of the same
    `subject_company_id` is already `IN_MONITORING` and its half-open window —
    from its `monitoring_started_at` up to but not including its
    `monitoring_ends_at` — overlaps the new window from now up to but not
    including now plus `monitoring_term_years` years, the transition is
    rejected with `ERR_MONITORING_TERM_OVERLAP`. Because both windows are
    half-open, adjacency is not overlap: one term ending at the exact instant
    another begins is permitted."
    PRD section 2.5: "At exactly `monitoring_ends_at` the order remains
    `IN_MONITORING`; expiry requires the clock to move past the boundary."

    Design: Difficulty/resource_temporal_overlap/monitoring_term_half_open_adjacency_allowed_but_overlap_rejected
    """
    reset_clock_to_epoch()
    company = create_company()
    inv1 = create_investigation(company["id"], origin="REFERRAL", summary="Deceptive billing")
    inv2 = create_investigation(company["id"], origin="COMPLAINT", summary="Fake discount scheme")
    advance_investigation_to_state(inv1["id"], "NEGOTIATING")
    advance_investigation_to_state(inv2["id"], "NEGOTIATING")
    order1 = draft_consent_order(
        inv1["id"],
        monetary_relief_cents=1_000_000,
        monitoring_term_years=1,
        conduct_prohibitions=["NO_HIDDEN_FEES"],
    )
    order2 = draft_consent_order(
        inv2["id"],
        monetary_relief_cents=1_000_000,
        monitoring_term_years=1,
        conduct_prohibitions=["NO_FAKE_DISCOUNTS"],
    )
    propose_consent_order(order1["id"])
    propose_consent_order(order2["id"])
    finalize_consent_order(order1["id"])  # clock -> 2026-10-01 for both periods
    finalize_consent_order(order2["id"])
    monitored1 = start_monitoring(order1["id"])
    assert parse_iso(monitored1["monitoring_started_at"]) == parse_iso("2026-10-01T00:00:00Z")
    assert parse_iso(monitored1["monitoring_ends_at"]) == parse_iso("2027-10-01T00:00:00Z")

    # Genuine overlap: order2's window would start inside order1's window.
    advance_clock("2027-09-15T00:00:00Z")
    order2_version = get_order(order2["id"])["version"]
    overlap = api_client.transition_consent_order(
        order2["id"],
        consent_order_transition_payload("IN_MONITORING", order2_version),
        _COMMISSIONER,
    )
    validate_error(overlap, ApiErrorId.ERR_MONITORING_TERM_OVERLAP)

    # Adjacency at the exact end instant: order1 still IN_MONITORING (strictly-
    # past expiry), yet order2 may start — half-open windows do not overlap.
    advance_clock("2027-10-01T00:00:00Z")
    assert get_order(order1["id"])["status"] == "IN_MONITORING"
    order2_version = get_order(order2["id"])["version"]
    monitored2 = validate_success(
        api_client.transition_consent_order(
            order2["id"],
            consent_order_transition_payload("IN_MONITORING", order2_version),
            _COMMISSIONER,
        ),
        200,
    )
    assert monitored2["status"] == "IN_MONITORING"
    assert parse_iso(monitored2["monitoring_started_at"]) == parse_iso("2027-10-01T00:00:00Z")

    advance_clock("2027-10-02T00:00:00Z")
    assert get_order(order1["id"])["status"] == "EXPIRED"
