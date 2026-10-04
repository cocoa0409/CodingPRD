"""Dealer compliance posture: the late-trade tally, the WATCH threshold,
the PENDING-subscription rejection cascade, and the compensating cancel
adjustments (PRD section 3.5)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    cancel_trade,
    create_dealer_org,
    create_late_trades,
    create_subscription,
    create_trade,
    read_organization,
    read_subscription,
    set_clock,
    setup_org_at_watch,
    validate_error,
)

LICENSING = TEST_USERS["licensing_officer_headers"]


def test_fifth_late_trade_flips_posture_and_rejects_pending_subscription(api):
    """PRD section 3.5: "The organization's `compliance_posture` becomes
    `WATCH` when that count reaches five — the fifth late trade inside the
    window trips the threshold, boundary inclusive" and "Whenever a
    recomputation moves an organization from `CLEAR` to `WATCH`, every data
    subscription licensed to that organization and still in `PENDING`
    status transitions to `REJECTED`."

    Design: Difficulty/transitive_cascade/late_trade_watch_posture_subscription_cascade
    """
    org = create_dealer_org(api, org_code="BD-401", name="Dealer Cascade")
    subscription = create_subscription(
        api, org["id"], product_code="TRADE_REALTIME",
        subscriber_principal="sub-d-1", license_scope="INTERNAL", seats=3,
    )
    set_clock(api, "2026-09-01T09:00:00Z")
    create_late_trades(api, org["id"], 4, clock_to="2026-09-01T09:00:00Z", gap_seconds=3600)

    midway = read_organization(api, org["id"])
    assert midway["late_report_count"] == 4
    assert midway["compliance_posture"] == "CLEAR", "four late trades must stay CLEAR"

    fifth = create_trade(
        api, org["id"], trade_type="INTER_DEALER", par_amount=1000000,
        price=100.0, executed_at="2026-09-01T08:00:00Z",
    )
    assert fifth["late_flag"] is True

    after = read_organization(api, org["id"])
    assert after["late_report_count"] == 5
    assert after["compliance_posture"] == "WATCH", (
        f"the fifth late trade must flip posture to WATCH, got {after['compliance_posture']!r}"
    )
    assert read_subscription(api, subscription["id"])["status"] == "REJECTED"


def test_posture_recovery_never_resurrects_rejected_subscription(api):
    """PRD section 3.5: "`REJECTED` is terminal and is never resurrected:
    if the tally later improves and the posture returns to `CLEAR`,
    rejected subscriptions stay rejected, and the licensee must re-apply.
    A recovery from `WATCH` to `CLEAR` carries no side effects at all."

    Design: Difficulty/transitive_cascade/late_trade_watch_posture_subscription_cascade
    """
    org, subscription, trades = setup_org_at_watch(api)
    assert read_organization(api, org["id"])["compliance_posture"] == "WATCH"
    assert read_subscription(api, subscription["id"])["status"] == "REJECTED"

    cancel_trade(api, trades[0]["id"], org["id"])
    recovered = read_organization(api, org["id"])
    assert recovered["late_report_count"] == 4
    assert recovered["compliance_posture"] == "CLEAR", (
        "cancelling a late trade must relax the tally and return posture to CLEAR"
    )
    assert read_subscription(api, subscription["id"])["status"] == "REJECTED", (
        "the rejected subscription must stay REJECTED after the posture recovers"
    )


def test_trade_cancel_conserves_published_par_total(api):
    """PRD section 3.5: "Cancellation moves the trade from `DISSEMINATED`
    to the terminal `CANCELLED` state and runs the compensating adjustments
    — the organization's `published_par_total` decreases by the cancelled
    trade's `published_par`". With the capped publication of section 3.5
    ("`published_par` is the smaller of `par_amount` and 5,000,000
    dollars"), cancelling the capped trade returns the total to exactly
    its pre-publish value.

    Design: Difficulty/compensating_invariant/trade_cancel_conserves_published_par_total
    """
    org = create_dealer_org(api, org_code="BD-1001", name="Dealer Eleven")
    set_clock(api, "2026-09-01T12:00:00Z")
    create_trade(api, org["id"], trade_type="CUSTOMER_BUY", par_amount=2000000,
                 price=100.0, executed_at="2026-09-01T11:50:00Z")
    capped = create_trade(api, org["id"], trade_type="CUSTOMER_BUY", par_amount=6000000,
                          price=100.0, executed_at="2026-09-01T11:50:00Z")
    assert capped["published_par"] == 5000000

    midway = read_organization(api, org["id"])
    assert midway["published_par_total"] == 7000000

    cancelled = cancel_trade(api, capped["id"], org["id"])
    assert cancelled["status"] == "CANCELLED"

    after = read_organization(api, org["id"])
    assert after["published_par_total"] == 2000000, (
        "the capped publication must leave no residue after its compensating "
        f"cancel: expected 2000000, got {after['published_par_total']}"
    )


def test_cancelling_a_late_trade_compensates_tally_posture_and_par(api):
    """PRD section 3.5: "the late tally and posture are recomputed, since a
    cancelled late trade leaves the thirty-day window tally. That
    recomputation may relax the posture from `WATCH` back to `CLEAR`" and
    "the organization's `published_par_total` decreases by the cancelled
    trade's `published_par`".

    Design: Difficulty/compensating_invariant/trade_cancel_conserves_published_par_total
    """
    org, _, trades = setup_org_at_watch(api, with_pending_subscription=False)
    before = read_organization(api, org["id"])
    assert before["compliance_posture"] == "WATCH"
    expected_par = before["published_par_total"] - trades[0]["published_par"]

    cancel_trade(api, trades[0]["id"], org["id"])

    after = read_organization(api, org["id"])
    assert after["late_report_count"] == 4
    assert after["compliance_posture"] == "CLEAR"
    assert after["published_par_total"] == expected_par, (
        "the par total must fall by exactly the cancelled trade's published_par: "
        f"expected {expected_par}, got {after['published_par_total']}"
    )


def test_late_tally_counts_only_late_trades_inside_the_trailing_window(api):
    """PRD section 3.5: "Its `late_report_count` is recomputed as the
    number of the organization's trade reports that are late, still
    `DISSEMINATED`, and whose `reported_at` falls inside the trailing
    thirty-day window — a half-open window in which a report received
    exactly thirty days ago is excluded, while anything younger counts."
    And: "The tally is recomputed on every trade creation, every trade
    cancellation, and every epoch pass of §2.4."

    Design: Corner/calculations/late_tally_counts_only_late_and_decays_outside_window
    """
    org = create_dealer_org(api, org_code="BD-2002", name="Dealer Tally")
    set_clock(api, "2026-09-01T12:00:00Z")
    create_trade(api, org["id"], trade_type="INTER_DEALER", par_amount=100000,
                 price=100.0, executed_at="2026-09-01T11:55:00Z")  # timely: 300 s
    create_trade(api, org["id"], trade_type="INTER_DEALER", par_amount=100000,
                 price=100.0, executed_at="2026-09-01T08:00:00Z")  # late: 14400 s

    now = read_organization(api, org["id"])
    assert now["late_report_count"] == 1, "only the late trade counts"
    assert now["compliance_posture"] == "CLEAR"

    # Slide the window past the late trade's receipt instant (2026-09-01T12:00:00Z).
    set_clock(api, "2026-10-02T12:00:01Z")
    later = read_organization(api, org["id"])
    assert later["late_report_count"] == 0, (
        "once the trailing 30-day window slides past the late report it drops out"
    )
    assert later["compliance_posture"] == "CLEAR"


def test_rejected_subscription_accepts_no_further_transitions(api):
    """PRD section 3.7: "Both `TERMINATED` and `REJECTED` are terminal" and
    "Any advance attempted on a terminal subscription is
    `ERR_INVALID_STATE`"; "rejection is reserved for the compliance cascade
    of §3.5, which is the sole path into `REJECTED`".

    Design: Corner/state_machines/rejected_subscription_transition_returns_invalid_state
    """
    org, subscription, _ = setup_org_at_watch(api, product_code="TRADE_HISTORICAL")
    assert read_subscription(api, subscription["id"])["status"] == "REJECTED"

    resp = api.transition_data_subscription(subscription["id"], {"to_state": "ACTIVE"}, LICENSING)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
