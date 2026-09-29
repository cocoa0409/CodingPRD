"""Non-linear state re-entry and multi-hop transitive cascades.

Queue A (difficulty index) translations for the ``non_linear_state_machine``
and ``transitive_cascade`` rules: a bid package that leaves ``SUBMITTED`` and
walks the whole arc again as round two, a lead whose ``hold_posture`` re-enters
``TENTATIVE`` through a replacement hold, and the two four-hop cascades fired
by one planner acceptance and one hotel-side withdrawal.
"""
from test_helpers import api_client, same_instant, validate_paginated
from test_helpers.assertions import (
    assert_fund_conservation_identity,
    assert_money_equals,
)
from test_helpers import fixtures as fx
from test_helpers.types import (
    BidPackageStatus,
    CommitmentStatus,
    EstimateVariant,
    FundPosture,
    HoldPosture,
    HoldRank,
    PlannerTier,
    ReleaseReason,
    SalesStage,
    SpaceHoldStatus,
)


# --- non_linear_state_machine ------------------------------------------------

def test_revision_request_returns_the_bid_to_draft_and_wipes_round_one_money(api):
    """SUBMITTED re-enters DRAFT as round two, clearing every round-one figure.

    PRD: "While `round_number` is below 3, the package returns from `SUBMITTED`
    to `DRAFT` with `round_number` incremented by one; `submitted_at` and
    `response_due_at` are cleared to null; and the entire incentive apparatus of
    the finished round is wiped -- `incentive_request_amount`,
    `approved_incentive_amount`, `admin_fee_amount`, `total_fund_charge_amount`,
    `tax_payback_ratio` and `incentive_requested_by_user_id` are all cleared to
    null" (PRD 3.8).
    PRD: "the fund's `committed_amount` falls by the previous
    `total_fund_charge_amount`, `uncommitted_amount` rises by the same amount and
    `posture` is re-derived" and "the lead's `sales_stage` moves back from
    `BIDDING` to `QUALIFIED`" (PRD 3.8).

    Design: Difficulty/non_linear_state_machine/bid_revision_returns_to_draft_then_reenters_submitted_as_round_two
    """
    scenario = fx.setup_bid_submitted()
    before = fx.read_bid(scenario["bid_id"])
    assert before["status"] == BidPackageStatus.SUBMITTED.value
    assert before["round_number"] == 1
    assert_money_equals(before["total_fund_charge_amount"], 12600.00, "round-1 charge")
    assert_money_equals(
        fx.read_fund(scenario["fund_id"])["uncommitted_amount"], 487400.00, "uncommitted"
    )

    reverted = fx.answer_bid(
        scenario["bid_id"], scenario["planner_id"], "REVISION_REQUESTED"
    )

    assert reverted["status"] == BidPackageStatus.DRAFT.value
    assert reverted["round_number"] == 2
    assert reverted["submitted_at"] is None
    assert reverted["response_due_at"] is None
    for cleared in (
        "incentive_request_amount",
        "approved_incentive_amount",
        "admin_fee_amount",
        "total_fund_charge_amount",
        "tax_payback_ratio",
        "incentive_requested_by_user_id",
    ):
        assert reverted[cleared] is None, f"{cleared} survived the revision"

    assert fx.read_opportunity(scenario["opportunity_id"])["sales_stage"] == (
        SalesStage.QUALIFIED.value
    )
    fund = fx.read_fund(scenario["fund_id"])
    assert_money_equals(fund["committed_amount"], 0.00, "committed_amount after decommit")
    assert_money_equals(fund["uncommitted_amount"], 500000.00, "uncommitted after decommit")
    assert fund["posture"] == FundPosture.OPEN.value
    assert_fund_conservation_identity(fund)


def test_the_same_bid_row_walks_the_whole_arc_again_as_round_two(api):
    """One package re-enters SUBMITTED with a second charge, not a second row.

    PRD: "The bureau may then re-request an incentive, re-approve it and
    re-submit -- the `QUALIFIED` to `BIDDING` to `QUALIFIED` loop may run up to
    three rounds in total" (PRD 3.8).
    PRD: "a `PROVISIONAL` economic impact estimate is created for the lead per
    Section 3.6, and from that fresh snapshot the package's
    `incentive_cap_amount` is computed" (PRD 3.7).
    PRD: "`committed_amount` rises by `total_charge_amount`,
    `uncommitted_amount` falls by the same amount" (PRD 3.7).

    Design: Difficulty/non_linear_state_machine/bid_revision_returns_to_draft_then_reenters_submitted_as_round_two
    """
    scenario = fx.setup_bid_submitted()
    bid_id = scenario["bid_id"]
    fx.answer_bid(bid_id, scenario["planner_id"], "REVISION_REQUESTED")

    pending = fx.ask_for_incentive(bid_id, 9_000.00)
    assert pending["status"] == BidPackageStatus.INCENTIVE_PENDING.value
    decision = fx.decide_incentive(
        bid_id, scenario["fund_id"], "APPROVED", 9_000.00,
        rationale="Round two approval at a smaller ask after the revision",
    )
    # 9000.00 sits in the 5% band: fee 450.00, total charge 9450.00.
    assert_money_equals(decision["admin_fee_amount"], 450.00, "round-2 admin fee")
    assert_money_equals(decision["total_charge_amount"], 9450.00, "round-2 total charge")

    resubmitted = fx.submit_bid(bid_id, "2027-05-01T00:00:00Z")
    assert resubmitted["status"] == BidPackageStatus.SUBMITTED.value
    assert resubmitted["round_number"] == 2
    assert same_instant(resubmitted["response_due_at"], "2027-05-01T00:00:00Z")
    assert fx.read_opportunity(scenario["opportunity_id"])["sales_stage"] == (
        SalesStage.BIDDING.value
    )

    # The revision reused the row: one package, and the round-1 charge is gone.
    rows, _meta = validate_paginated(
        api_client.list_bid_packages(fx.SALES, params={"opportunity_id": scenario["opportunity_id"]})
    )
    assert [row["id"] for row in rows] == [bid_id]
    fund = fx.read_fund(scenario["fund_id"])
    assert_money_equals(fund["committed_amount"], 9450.00, "committed_amount")
    assert_fund_conservation_identity(fund)
    # One automatic PROVISIONAL estimate per incentive request.
    provisional = fx.list_estimates(
        scenario["opportunity_id"], EstimateVariant.PROVISIONAL.value
    )
    assert len(provisional) == 2


def test_hold_posture_reenters_tentative_after_a_release(api):
    """The posture walks NONE, TENTATIVE, RELEASED and TENTATIVE again.

    PRD: "Creating a `FIRST`-rank hold moves the owning opportunity's
    `hold_posture` to `TENTATIVE` -- from `NONE` for a first-ever hold, or back
    up from `RELEASED` when the bureau re-holds space for a lead still in
    `QUALIFIED` or `BIDDING` after an earlier hold went away" (PRD 3.3).
    PRD: "A successful release sets the hold's status to `RELEASED` with
    `release_reason` `SCHEDULER_RELEASE`" (PRD 3.4).
    PRD: "the releasing opportunity's `hold_posture` becomes `RELEASED`, but only
    once no hold of that opportunity remains in status `HELD` or `CHALLENGED`"
    (PRD 3.4).

    Design: Difficulty/non_linear_state_machine/hold_posture_reenters_tentative_after_released_via_replacement_hold
    """
    scenario = fx.setup_lead()
    opportunity_id = scenario["opportunity_id"]
    assert fx.read_opportunity(opportunity_id)["hold_posture"] == HoldPosture.NONE.value

    first = fx.place_hold(opportunity_id, scenario["hall_id"])
    assert first["hold_rank"] == HoldRank.FIRST.value
    assert fx.read_opportunity(opportunity_id)["hold_posture"] == HoldPosture.TENTATIVE.value

    released = fx.release_hold(first["id"])
    assert released["status"] == SpaceHoldStatus.RELEASED.value
    assert released["release_reason"] == ReleaseReason.SCHEDULER_RELEASE.value
    assert fx.read_opportunity(opportunity_id)["hold_posture"] == HoldPosture.RELEASED.value

    fx.set_clock("2027-03-10T00:00:00Z")
    replacement = fx.place_hold(opportunity_id, scenario["hall_id"])

    assert replacement["status"] == SpaceHoldStatus.HELD.value
    assert fx.read_opportunity(opportunity_id)["hold_posture"] == HoldPosture.TENTATIVE.value
    # The lead re-entered TENTATIVE; the hold dimension did not cycle.
    assert replacement["id"] != first["id"]


def test_the_replacement_hold_is_a_new_first_rank_row_stamped_from_the_later_clock(api):
    """A released hold blocks nothing, so the replacement is FIRST with a fresh quarter.

    PRD: "Holds in `RELEASED` or `EXPIRED` never block anything" and "the hold is
    created in status `HELD`, with `hold_rank` set to `FIRST` when the blocking
    set was empty" (PRD 3.3).
    PRD: "A `FIRST`-rank hold has its `expires_at` stamped at 90 days after the
    current logical clock" (PRD 3.3).

    Design: Difficulty/non_linear_state_machine/hold_posture_reenters_tentative_after_released_via_replacement_hold
    """
    scenario = fx.setup_lead()
    opportunity_id = scenario["opportunity_id"]

    first = fx.place_hold(opportunity_id, scenario["hall_id"])
    # 2027-03-01 + 90 days.
    assert same_instant(first["expires_at"], "2027-05-30T00:00:00Z")
    fx.release_hold(first["id"])

    fx.set_clock("2027-03-10T00:00:00Z")
    replacement = fx.place_hold(opportunity_id, scenario["hall_id"])

    assert replacement["hold_rank"] == HoldRank.FIRST.value
    # 2027-03-10 + 90 days, not a copy of the released hold's expiry.
    assert same_instant(replacement["expires_at"], "2027-06-08T00:00:00Z")
    assert not same_instant(replacement["expires_at"], first["expires_at"])
    assert replacement["challenge_deadline"] is None
    assert replacement["release_reason"] is None

    # The old row is not revived, and both rows survive the sub-collection.
    stale = fx.read_hold(first["id"])
    assert stale["status"] == SpaceHoldStatus.RELEASED.value
    rows, _meta = validate_paginated(
        api_client.list_space_holds(fx.SCHEDULER, params={"opportunity_id": opportunity_id})
    )
    assert {row["id"] for row in rows} == {first["id"], replacement["id"]}


# --- transitive_cascade ------------------------------------------------------

def test_acceptance_cascades_through_bid_opportunity_hold_and_planner(api):
    """One planner-response call moves four entities and both score scopes.

    PRD: "Hop 1 moves the package from `SUBMITTED` to `ACCEPTED`. Hop 2: because
    the bid was accepted, the lead's `sales_stage` moves from `BIDDING` to
    `DEFINITE`, its `definite_at` is stamped from the logical clock, and its
    `definite_room_nights` is frozen at `committed_peak_rooms` multiplied by
    `event_nights`. Hop 3: because the lead became `DEFINITE`, its `FIRST`-rank
    space hold in status `HELD` or `CHALLENGED` is confirmed ... and the lead's
    `hold_posture` becomes `CONFIRMED`" (PRD 3.8).
    PRD: "the owning planner's `definite_count` and
    `lifetime_definite_room_nights` are re-derived and then
    `relationship_score_lifetime`, `relationship_score_rolling_24m` and `tier`
    are all recomputed per Section 3.1" (PRD 3.8).

    Design: Difficulty/transitive_cascade/bid_acceptance_cascades_four_hops_to_a_rival_opportunity_posture
    """
    scenario = fx.setup_bid_submitted()

    accepted = fx.answer_bid(scenario["bid_id"], scenario["planner_id"], "ACCEPTED")

    # Hop 1.
    assert accepted["status"] == BidPackageStatus.ACCEPTED.value
    # Hop 2.
    opportunity = fx.read_opportunity(scenario["opportunity_id"])
    assert opportunity["sales_stage"] == SalesStage.DEFINITE.value
    assert same_instant(opportunity["definite_at"], "2027-03-01T00:00:00Z")
    assert opportunity["definite_room_nights"] == 1800
    # Hop 3.
    hold = fx.read_hold(scenario["hold_id"])
    assert hold["status"] == SpaceHoldStatus.CONFIRMED.value
    assert hold["challenge_deadline"] is None
    assert hold["challenged_by_space_hold_id"] is None
    assert opportunity["hold_posture"] == HoldPosture.CONFIRMED.value
    assert fx.read_hall(scenario["hall_id"])["confirmed_hold_count"] == 1
    # The parallel planner-side hop.
    planner = fx.read_planner(scenario["planner_id"])
    assert planner["definite_count"] == 1
    assert planner["lifetime_definite_room_nights"] == 7800
    assert planner["relationship_score_lifetime"] == 51
    assert planner["relationship_score_rolling_24m"] == 15
    assert planner["tier"] == PlannerTier.TIER_B.value


RIVAL_LEAD = {
    "event_name": "Regional Robotics Summit",
    "arrival_date": "2028-04-16",
    "departure_date": "2028-04-18",
    "peak_rooms_requested": 500,
    "total_room_nights_requested": 800,
    "attendance_estimate": 5_000,
    "exhibit_sqft_requested": 100_000,
    "rate_ceiling_amount": 199.00,
}


def test_confirmation_supersedes_a_rival_second_rank_hold_on_the_same_hall(api):
    """The fourth hop reaches an opportunity the accepting planner never saw.

    PRD: "every other hold on the same hall in status `HELD` or `CHALLENGED`
    whose buffered window conflicts with the newly confirmed one moves to
    `RELEASED` with `release_reason` `SUPERSEDED_BY_CONFIRMED`, and each of those
    superseded leads has its `hold_posture` set to `RELEASED` once none of its own
    holds remains in `HELD` or `CHALLENGED`" (PRD 3.4).
    PRD: "A superseded sibling is always a `SECOND`-rank hold, and because bid
    submission requires an active hold, such a lead is never in `BIDDING` -- it
    stays `QUALIFIED`" (PRD 3.4).

    Design: Difficulty/transitive_cascade/bid_acceptance_cascades_four_hops_to_a_rival_opportunity_posture
    """
    scenario = fx.setup_bid_submitted()
    rival_planner = fx.register_planner(
        org_name="Regional Robotics Alliance", contact_email="events@rra.org"
    )
    rival_lead = fx.qualify_lead(
        fx.create_lead(rival_planner["id"], **dict(RIVAL_LEAD))["id"]
    )
    # 2028-04-14 pulled back by the hall's 48h buffer is 2028-04-12, strictly
    # earlier than the incumbent's 2028-04-13 move_out_end, so the windows
    # conflict and the newcomer queues as the second option.
    rival_hold = fx.place_hold(
        rival_lead["id"], scenario["hall_id"],
        move_in_start="2028-04-14T00:00:00Z", move_out_end="2028-04-18T00:00:00Z",
    )
    assert rival_hold["hold_rank"] == HoldRank.SECOND.value

    fx.answer_bid(scenario["bid_id"], scenario["planner_id"], "ACCEPTED")

    superseded = fx.read_hold(rival_hold["id"])
    assert superseded["status"] == SpaceHoldStatus.RELEASED.value
    assert superseded["release_reason"] == ReleaseReason.SUPERSEDED_BY_CONFIRMED.value
    rival_after = fx.read_opportunity(rival_lead["id"])
    assert rival_after["hold_posture"] == HoldPosture.RELEASED.value
    assert rival_after["sales_stage"] == SalesStage.QUALIFIED.value

    confirmed, _meta = validate_paginated(
        api_client.list_space_holds(
            fx.SCHEDULER,
            params={"center_hall_id": scenario["hall_id"],
                    "status": SpaceHoldStatus.CONFIRMED.value},
        )
    )
    assert [row["id"] for row in confirmed] == [scenario["hold_id"]]


def test_one_withdrawal_cascades_to_coverage_bid_rollback_and_fund_decommit(api):
    """A hotel-side exit drags the bid off the planner's desk and frees the money.

    PRD: "**Hop 2.** Because rooms have left the block, `rooms_peak_committed` and
    `committed_room_nights` on the commitment are both reset to 0, the property's
    `committed_peak_rooms` and `committed_room_nights` are recomputed, and the
    lead's `committed_peak_rooms`, `block_coverage_pct` and
    `cutoff_alignment_spread_days` are recomputed from the commitments that
    remain committed" (PRD 3.5).
    PRD: "**Hop 3.** If that recomputation drops `block_coverage_pct` below 85.00
    while a bid package of this lead is in status `SUBMITTED`, that bid package
    returns to `DRAFT` with its `round_number` incremented by one, its
    `submitted_at` and `response_due_at` cleared, and the lead's `sales_stage`
    moves back from `BIDDING` to `QUALIFIED`" (PRD 3.5).
    PRD: "**Hop 4.** Because that bid left `SUBMITTED`, its live fund charge is
    decommitted: the fund's `committed_amount` falls by the bid's
    `total_fund_charge_amount`, `uncommitted_amount` rises by the same amount, and
    `posture` is re-derived" (PRD 3.5).

    Design: Difficulty/transitive_cascade/single_withdrawal_cascades_coverage_bid_rollback_and_fund_decommit
    """
    scenario = fx.setup_bid_submitted()
    assert_money_equals(scenario["opportunity"]["block_coverage_pct"], 90.00, "coverage before")
    harborview = scenario["commitments"][0]

    withdrawn = fx.withdraw_block(harborview["id"], harborview["hotel_id"], "PROPERTY_SOLD_OUT")

    # Hop 1.
    assert withdrawn["status"] == CommitmentStatus.WITHDRAWN.value
    assert withdrawn["rooms_peak_committed"] == 0
    assert withdrawn["committed_room_nights"] == 0
    # Hop 2.
    hotel = fx.read_hotel(harborview["hotel_id"])
    assert hotel["committed_peak_rooms"] == 0
    assert hotel["committed_room_nights"] == 0
    opportunity = fx.read_opportunity(scenario["opportunity_id"])
    assert opportunity["committed_peak_rooms"] == 400
    assert_money_equals(opportunity["block_coverage_pct"], 40.00, "coverage after")
    # Hop 3.
    bid = fx.read_bid(scenario["bid_id"])
    assert bid["status"] == BidPackageStatus.DRAFT.value
    assert bid["round_number"] == 2
    assert bid["submitted_at"] is None
    assert bid["response_due_at"] is None
    assert opportunity["sales_stage"] == SalesStage.QUALIFIED.value
    # Hop 4.
    fund = fx.read_fund(scenario["fund_id"])
    assert_money_equals(fund["committed_amount"], 0.00, "fund committed_amount")
    assert_money_equals(fund["uncommitted_amount"], 500000.00, "fund uncommitted_amount")
    assert fund["posture"] == FundPosture.OPEN.value
    assert_fund_conservation_identity(fund)
    # Siblings are untouched by the cascade.
    for sibling in scenario["commitments"][1:]:
        assert fx.read_commitment(sibling["id"])["status"] == CommitmentStatus.COMMITTED.value


def test_a_withdrawal_that_leaves_coverage_at_the_floor_never_touches_the_bid(api):
    """The bid rollback is conditional on coverage falling below 85.00.

    PRD: "**Hop 3.** If that recomputation drops `block_coverage_pct` below 85.00
    while a bid package of this lead is in status `SUBMITTED`, that bid package
    returns to `DRAFT`" (PRD 3.5).
    PRD: "From `COMMITTED` ... `rooms_peak_committed` and `committed_room_nights`
    on the commitment are both reset to 0" (PRD 3.5).

    Design: Difficulty/transitive_cascade/single_withdrawal_cascades_coverage_bid_rollback_and_fund_decommit
    """
    # 500 + 400 + 100 = 1000 of 1000 peak rooms: coverage starts at 100.00.
    scenario = fx.setup_bid_submitted(
        allocations=((0, 500, 214.33, 30), (1, 400, 209.77, 30), (2, 100, 199.51, 30))
    )
    assert_money_equals(scenario["opportunity"]["block_coverage_pct"], 100.00, "coverage before")
    cityline = scenario["commitments"][2]

    fx.withdraw_block(cityline["id"], cityline["hotel_id"], "PROPERTY_SOLD_OUT")

    opportunity = fx.read_opportunity(scenario["opportunity_id"])
    assert opportunity["committed_peak_rooms"] == 900
    assert_money_equals(opportunity["block_coverage_pct"], 90.00, "coverage after")
    # Still at or above the 85.00 floor, so hops 3 and 4 do not fire.
    assert opportunity["sales_stage"] == SalesStage.BIDDING.value
    bid = fx.read_bid(scenario["bid_id"])
    assert bid["status"] == BidPackageStatus.SUBMITTED.value
    assert bid["round_number"] == 1
    assert bid["submitted_at"] is not None
    assert_money_equals(bid["total_fund_charge_amount"], 12600.00, "total_fund_charge_amount")
    fund = fx.read_fund(scenario["fund_id"])
    assert_money_equals(fund["committed_amount"], 12600.00, "fund committed_amount")
    assert_fund_conservation_identity(fund)
