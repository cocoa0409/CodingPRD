"""Depth tests: transitive cascade chains from different triggers."""
from test_helpers import (
    AGENCY_OPERATOR,
    ATTRACTION_HOST,
    CLUB_CARD_SPECIALIST,
    DEAL_DESK_CLERK,
    EVENTS_COORDINATOR,
    FINANCE_ADMIN,
    PLATFORM_ADMIN,
    SERVICE_TECHNICIAN,
    STORE_MANAGER,
    create_member,
    create_open_attraction,
    get_success_data,
    setup_delivered_deal,
)


# ===========================================================================
# settle_cascade_to_tier_donation_and_application  (queue A / transitive_cascade)
# ===========================================================================

def _post_settle_world(api):
    """A SETTLED deal on a bright member, plus an aquarium ready for guests."""
    ctx = setup_delivered_deal(api)
    store = ctx["store"]
    member = ctx["member"]

    attraction = create_open_attraction(api, store["id"], attraction_type="AQUARIUM",
                                        capacity_units=20, dwell_cost_minutes=30)
    guest = create_member(api, store["id"], email="m_gs@x.com",
                          full_name="Gus Shore")
    application = get_success_data(
        api.create_club_card_application(
            store["id"],
            {
                "member_id": member["id"],
                "card_product": "REWARDS",
                "donation_match_bps": 2000,
                "underwriter_user_id": "uw_2201",
            },
            CLUB_CARD_SPECIALIST,
        ),
        201,
    )

    settled = get_success_data(
        api.settle_deal(
            ctx["deal"]["id"],
            {"expected_deal_version": ctx["deal"]["version"]},
            FINANCE_ADMIN,
        ),
        200,
    )
    refreshed = get_success_data(api.get_member(member["id"], PLATFORM_ADMIN), 200)
    offering = get_success_data(
        api.create_event_offering(
            store["id"],
            {
                "offering_kind": "FREE_DEMO",
                "title": "Dock Walk",
                "starts_at_utc": "2026-10-02T10:00:00Z",
                "ends_at_utc": "2026-10-02T11:00:00Z",
                "registration_cap": 0,
                "attraction_id": attraction["id"],
            },
            EVENTS_COORDINATOR,
        ),
        201,
    )
    get_success_data(api.publish_event_offering(offering["id"], EVENTS_COORDINATOR), 200)
    return ctx, settled, refreshed, attraction, guest, application


def test_settlement_awards_club_points_and_lifts_the_lifetime_total(api):
    """PRD §3.4: "Settlement moves the stage from `DELIVERED` to `SETTLED`,
    creates an award event carrying the points computed by the settlement award
    calculation, replays the member's point ledger and re-derives their tier and
    redeemable balance, and evaluates the conservation donation match."

    Design: Difficulty/transitive_cascade/settle_cascade_to_tier_donation_and_application
    """
    ctx, settled, refreshed, attraction, guest, application = _post_settle_world(api)
    assert settled["deal_stage"] == "SETTLED", (
        f"settlement is the final commercial act, got {settled['deal_stage']}"
    )
    assert settled["points_awarded"] == 1346, (
        "an 11220000-cent contract price lands in the twelve-basis-point band, so "
        f"the award is 1346 points; got {settled['points_awarded']}"
    )
    assert refreshed["points_lifetime_earned"] == 1346, (
        "the settle hop is what raised the member's lifetime total; got "
        f"{refreshed['points_lifetime_earned']}"
    )
    assert refreshed["club_tier"] == "BASE", (
        "1346 lifetime points sit below the 8000-point SILVER threshold, so the "
        f"tier boundary has not flipped yet; got {refreshed['club_tier']}"
    )


def test_a_settlement_award_feeds_no_conservation_match_and_converts_no_pending_card(api):
    """PRD §2.8.1: "Only redemption events count toward the match base, and only
    for members whose `donation_opt_in` is true and whose club card is `ACTIVE`;
    awards, adjustments and reversals are excluded."
    PRD §3.8: "Posting any event replays the member's entire ledger through the
    point replay, re-derives their tier and redeemable balance, and evaluates the
    conservation match on redemptions."

    Design: Difficulty/transitive_cascade/settle_cascade_to_tier_donation_and_application
    """
    ctx, settled, refreshed, attraction, guest, application = _post_settle_world(api)
    assert refreshed["conservation_match_cents"] == 0, (
        "a settlement awards points and only a redemption feeds the conservation "
        f"match; got {refreshed['conservation_match_cents']}"
    )
    assert refreshed["redeemable_points"] == 1346, (
        "a BASE member has no retention floor, so the whole balance is "
        f"redeemable; got {refreshed['redeemable_points']}"
    )
    assert refreshed["club_card_status"] == "NONE", (
        "the pending application is reported on the member but not yet "
        f"converted; got {refreshed['club_card_status']}"
    )
    application_row = get_success_data(
        api.get_club_card_application(application["id"], CLUB_CARD_SPECIALIST), 200
    )
    assert application_row["status"] == "PENDING"
    assert application_row["credit_limit_cents"] == 0, (
        "the application begins with its credit limit at zero and the settle call "
        f"mints no redemption capacity; got {application_row['credit_limit_cents']}"
    )


def test_the_post_settlement_session_confirms_and_the_dwell_summary_stays_permissive(api):
    """PRD §3.1: "a party whose slot begins exactly when another's ends is
    adjacent rather than overlapping and is permitted."
    PRD §2.8.1: "A band multiplier is selected from the party size, applied per
    band to the whole party rather than marginally: three when the party is ten
    or more, two when it is at least five but under ten, and one below five."

    Design: Difficulty/transitive_cascade/settle_cascade_to_tier_donation_and_application
    """
    ctx, settled, refreshed, attraction, guest, application = _post_settle_world(api)

    session = get_success_data(
        api.create_session(
            ctx["store"]["id"],
            {
                "attraction_id": attraction["id"],
                "member_id": guest["id"],
                "session_kind": "GENERAL_ADMISSION",
                "party_size": 8,
                "slot_start_utc": "2026-11-01T10:00:00Z",
                "slot_end_utc": "2026-11-01T11:00:00Z",
            },
            ATTRACTION_HOST,
        ),
        201,
    )
    assert session["status"] == "CONFIRMED", (
        "the posture recompute the settle hop forced produced a permissive "
        f"result rather than a gate; got {session['status']}"
    )
    summary = get_success_data(api.get_dwell_summary(ctx["store"]["id"], STORE_MANAGER), 200)
    assert summary["attraction_posture"] == "OPEN"
    assert summary["dwell_committed_minutes"] == 15 + session["dwell_charge_minutes"], (
        "15 from the published free demo plus the guest party's own charge; got "
        f"{summary['dwell_committed_minutes']}"
    )


def test_the_settlement_points_are_banded_on_the_contract_price_not_the_list_value(api):
    """PRD §2.8.1: "The award price is the deal's `contract_price_cents` under
    the default settlement path."
    PRD §2.8.1: "twelve basis points when it is at least five million but below
    fifteen million cents."
    PRD §2.8.1: "The rate band applies to the whole price rather than marginally."

    Design: Difficulty/transitive_cascade/settle_cascade_to_tier_donation_and_application
    """
    ctx, settled, refreshed, attraction, guest, application = _post_settle_world(api)
    contract_price = settled["contract_price_cents"]
    assert 5_000_000 <= contract_price < 15_000_000, (
        f"the deal sits in the mid band, got {contract_price}"
    )
    assert settled["points_awarded"] == round(contract_price * 12 / 100_000), (
        "the band rate applies to the whole price and is rounded once; expected "
        f"{round(contract_price * 12 / 100_000)}, got {settled['points_awarded']}"
    )
    assert settled["points_awarded"] < 20_000, "the award is capped at twenty thousand points"


# ===========================================================================
# reject_cascade_and_cancel_cascade_from_different_triggers  (queue A / transitive_cascade)
# ===========================================================================

def _rejection_and_cancellation_world(api):
    """A delivered deal with an events workshop already carrying a confirmed party."""
    ctx = setup_delivered_deal(api)
    store = ctx["store"]
    member = ctx["member"]

    attraction = create_open_attraction(api, store["id"], attraction_type="ARCHERY_RANGE",
                                        capacity_units=12, dwell_cost_minutes=45)
    offering = get_success_data(
        api.create_event_offering(
            store["id"],
            {
                "offering_kind": "KIDS_WORKSHOP",
                "title": "Knot Tying for Kids",
                "starts_at_utc": "2026-10-05T10:00:00Z",
                "ends_at_utc": "2026-10-05T11:00:00Z",
                "registration_cap": 10,
                "attraction_id": attraction["id"],
            },
            EVENTS_COORDINATOR,
        ),
        201,
    )
    get_success_data(api.publish_event_offering(offering["id"], EVENTS_COORDINATOR), 200)
    registration = get_success_data(
        api.create_event_registration(store["id"], offering["id"],
                                      {"member_id": member["id"], "seats": 2},
                                      EVENTS_COORDINATOR),
        201,
    )
    get_success_data(
        api.confirm_event_registration(offering["id"], registration["id"],
                                       EVENTS_COORDINATOR),
        200,
    )
    return ctx, attraction, offering, registration


def test_agency_rejection_walks_filing_to_deal_to_hull_to_work_order(api):
    """PRD §3.5: "The hull's `status` moves from `SOLD` back to `DEAL_PENDING`,
    which re-opens the unit's rigging work: the work order whose `boat_unit_id`
    is this unit, whose `order_kind` is `RIGGING` and whose `status` is
    `DELIVERED` is returned to `COMPLETED`."

    Design: Difficulty/transitive_cascade/reject_cascade_and_cancel_cascade_from_different_triggers
    """
    ctx, attraction, offering, registration = _rejection_and_cancellation_world(api)

    filing = get_success_data(
        api.reject_title_filing(
            ctx["filing_id"],
            {"rejection_reason": "HIN does not match the agency record"},
            AGENCY_OPERATOR,
        ),
        200,
    )
    assert filing["status"] == "REJECTED"

    reverted = get_success_data(api.get_deal(ctx["deal"]["id"], DEAL_DESK_CLERK), 200)
    assert reverted["deal_stage"] == "CONTRACTED", (
        f"the cyclic revert fired on a still-live deal; got {reverted['deal_stage']}"
    )
    assert reverted["deal_stage"] != "SETTLED"

    order = get_success_data(
        api.get_service_order(ctx["service_order"]["id"], SERVICE_TECHNICIAN), 200
    )
    assert order["status"] == "COMPLETED", (
        "the rigging order is pulled back out of DELIVERED by the unit status "
        f"change; got {order['status']}"
    )
    assert reverted["rigging_status"] == "SCHEDULED", (
        f"the deal regressed after the reject call; got {reverted['rigging_status']}"
    )


def test_offering_cancellation_cascades_registrations_and_credits_two_hundred_fifty_points(api):
    """PRD §3.3: "When an entire offering is cancelled, the cascade is total:
    every registration still in `REGISTERED`, `CONFIRMED` or `WAITLISTED` moves
    to `CANCELLED`, each of those registrations grants its member the same two
    hundred fifty points where it covered two or more seats, the offering's
    confirmed count is rewound to zero, and the offering's dwell charge is
    released back to the store budget."

    Design: Difficulty/transitive_cascade/reject_cascade_and_cancel_cascade_from_different_triggers
    """
    ctx, attraction, offering, registration = _rejection_and_cancellation_world(api)
    before = get_success_data(api.get_member(ctx["member"]["id"], PLATFORM_ADMIN), 200)

    get_success_data(api.cancel_event_offering(offering["id"], EVENTS_COORDINATOR), 200)

    cancelled_offering = get_success_data(
        api.get_event_offering(offering["id"], EVENTS_COORDINATOR), 200
    )
    assert cancelled_offering["status"] == "CANCELLED"
    assert cancelled_offering["confirmed_count"] == 0, (
        "the confirmed count is rewound to zero; got "
        f"{cancelled_offering['confirmed_count']}"
    )

    cancelled_registration = get_success_data(
        api.get_event_registration(registration["id"], EVENTS_COORDINATOR), 200
    )
    assert cancelled_registration["status"] == "CANCELLED"
    assert cancelled_registration["seats"] == 2

    after = get_success_data(api.get_member(ctx["member"]["id"], PLATFORM_ADMIN), 200)
    assert after["points_balance"] == before["points_balance"] + 250, (
        "a two-seat confirmation grants 250 consolation points on cancellation; "
        f"expected {before['points_balance'] + 250}, got {after['points_balance']}"
    )