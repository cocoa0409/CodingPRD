"""Cross-cutting complexity layers and the consistency model.

Optimistic-concurrency guards on the two shared parents (``Opportunity.version``
and ``IncentiveFund.version``), the fan-out of a lost bidding opportunity, the
coexistence of the two economic-impact variants, the marginal incentive band
ladder, and the read-your-writes visibility of every cascaded field.

Every test pins the logical clock first and builds all of its own preconditions.
"""
from test_helpers import (
    ApiErrorId,
    BidPackageStatus,
    CommitmentStatus,
    EstimateVariant,
    FundPosture,
    HoldPosture,
    LostReason,
    PlannerResponse,
    PlannerTier,
    ReleaseReason,
    SalesStage,
    SpaceHoldStatus,
    WithdrawReason,
    api_client,
    assert_fund_conservation_identity,
    assert_money_equals,
    estimate_payload,
    fixtures,
    incentive_decision_payload,
    make_incentive_approver_headers,
    make_meeting_planner_headers,
    same_instant,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import INCENTIVE_APPROVER_USER_ID


def _band_ladder_scenario():
    """A TIER_A planner with three fully covered leads that differ only in
    ``total_room_nights_requested`` (5000 / 5001 / 15001).

    Metro Tower holds 4000 committable rooms, so all three 1000-room blocks may
    be committed on the same two nights (3000 <= 4000).  Each lead's
    ``rate_ceiling_amount`` of 400.00 keeps the TIER_A lodging-tax yield ceiling
    far above the band ceiling, so the band ladder is the binding term.
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    planner = fixtures.register_planner(
        org_name="Metro Health Congress",
        contact_email="bids@metrohealthcongress.org",
        legacy_definite_count=4,
        legacy_definite_room_nights=10000,
    )
    hotel = fixtures.register_hotel(
        name="Metro Tower", committable_rooms=4000, walk_distance_blocks=1
    )
    fund = fixtures.open_fund()
    leads = {}
    for nights in (5000, 5001, 15001):
        opportunity = fixtures.create_lead(
            planner["id"],
            event_name=f"Ladder Congress {nights}",
            peak_rooms_requested=1000,
            total_room_nights_requested=nights,
            rate_ceiling_amount=400.00,
        )
        fixtures.qualify_lead(opportunity["id"])
        fixtures.add_committed_block(opportunity["id"], hotel["id"], 1000, 300.00, 30)
        bid = fixtures.open_bid(opportunity["id"])
        leads[nights] = {"opportunity_id": opportunity["id"], "bid_id": bid["id"]}
    return {"planner_id": planner["id"], "hotel_id": hotel["id"],
            "fund_id": fund["id"], "leads": leads}


def test_bid_package_create_rejects_a_stale_opportunity_version(sales_manager_headers):
    """A rival hotel's invitation bumps the opportunity version, so preparing the
    bid from the earlier read is 412 and creates nothing; the retry succeeds and
    itself bumps the guarded version.

    PRD: "Every block invitation, commit, withdrawal and sales-stage change bumps that opportunity's `version`, so a client preparing a bid from a stale read would price the package against a citywide block that no longer exists. If `expected_opportunity_version` does not equal the opportunity's current `version`, the create is rejected with `ERR_STALE_OPPORTUNITY_VERSION` and HTTP 412." (PRD S2.6)
    PRD: "The new package is born in status `DRAFT` with `round_number` 1 and `prepared_by_user_id` set to the acting `X-User-ID`, and it increments the lead's `version` by one." (PRD S3.7)

    Design: Corner/cross_cutting_complexity_layers/bid_package_create_rejects_a_stale_opportunity_version
    """
    scenario = fixtures.setup_lead(clock="2027-03-01T00:00:00Z")
    opportunity_id = scenario["opportunity_id"]
    rival_hotel = scenario["hotels"][1]

    v_read = fixtures.opportunity_version(opportunity_id)

    # An unrelated write on the same parent: a rival property is invited into
    # the citywide block.  It changes no field the bid reads directly.
    fixtures.invite_hotel(opportunity_id, rival_hotel["id"], rooms_peak_invited=400)
    v_fresh = fixtures.opportunity_version(opportunity_id)
    assert v_fresh == v_read + 1, (
        f"the invitation must bump Opportunity.version once: {v_read} -> {v_fresh}"
    )

    stale = api_client.create_bid_package(
        {"opportunity_id": opportunity_id, "expected_opportunity_version": v_read},
        sales_manager_headers,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_OPPORTUNITY_VERSION.value, 412)

    _packages, meta = validate_paginated(
        api_client.list_bid_packages(
            sales_manager_headers, params={"opportunity_id": opportunity_id}
        )
    )
    assert meta["total_count"] == 0, "the rejected create must have stored no BidPackage"

    retry = api_client.create_bid_package(
        {"opportunity_id": opportunity_id, "expected_opportunity_version": v_fresh},
        sales_manager_headers,
    )
    bid = validate_success(retry, expected_status=201)
    assert bid["round_number"] == 1
    assert bid["status"] == BidPackageStatus.DRAFT.value
    assert bid["opportunity_id"] == opportunity_id

    v_after_bid = fixtures.opportunity_version(opportunity_id)
    assert v_after_bid == v_fresh + 1, (
        "every OCC-guarded write also increments the guarded version: "
        f"{v_fresh} -> {v_after_bid}"
    )


def test_commitment_invite_rejects_a_stale_opportunity_version_after_a_stage_change(
    sales_manager_headers,
):
    """A version read while the lead was still LEAD is stale the moment qualify
    runs, so the invitation is 412 on the version check even though the stage
    precondition is by then satisfied.

    PRD: "**Inviting a hotel into the citywide block** (`POST /room-block-commitments`) likewise requires `expected_opportunity_version` matching the target opportunity's current `version`, and a mismatch is rejected with `ERR_STALE_OPPORTUNITY_VERSION` and HTTP 412." (PRD S2.6)
    PRD: "A successful qualification produces three side effects beyond the stage change: the owning planner's `engagement_status` is set to `ENGAGED`, that planner's `last_touch_at` is refreshed from the logical clock, and the opportunity's `version` is incremented by one." (PRD S3.2)

    Design: Corner/cross_cutting_complexity_layers/commitment_invite_rejects_a_stale_opportunity_version_after_a_stage_change
    """
    scenario = fixtures.setup_lead(clock="2026-08-01T00:00:00Z", qualify=False)
    opportunity_id = scenario["opportunity_id"]
    hotel = scenario["hotels"][0]

    v_lead = scenario["opportunity"]["version"]
    assert v_lead == 1, "a freshly recorded row starts at version 1"
    assert scenario["opportunity"]["sales_stage"] == SalesStage.LEAD.value

    qualified = fixtures.qualify_lead(opportunity_id)
    assert qualified["sales_stage"] == SalesStage.QUALIFIED.value
    v_qualified = qualified["version"]
    assert v_qualified == v_lead + 1, (
        f"qualify increments the opportunity version once: {v_lead} -> {v_qualified}"
    )

    stale = api_client.create_room_block_commitment(
        {
            "opportunity_id": opportunity_id,
            "hotel_id": hotel["id"],
            "rooms_peak_invited": 500,
            "expected_opportunity_version": v_lead,
        },
        sales_manager_headers,
    )
    # The stage is QUALIFIED by now, so the version check - not the stage check -
    # is what refuses the invitation.
    validate_error(stale, ApiErrorId.ERR_STALE_OPPORTUNITY_VERSION.value, 412)

    retry = api_client.create_room_block_commitment(
        {
            "opportunity_id": opportunity_id,
            "hotel_id": hotel["id"],
            "rooms_peak_invited": 500,
            "expected_opportunity_version": v_qualified,
        },
        sales_manager_headers,
    )
    commitment = validate_success(retry, expected_status=201)
    assert commitment["status"] == CommitmentStatus.INVITED.value
    assert commitment["offer_round"] == 0

    v_after_invite = fixtures.opportunity_version(opportunity_id)
    assert v_after_invite == v_qualified + 1, (
        f"creating the commitment bumps the opportunity version: {v_qualified} -> {v_after_invite}"
    )

    _rows, meta = validate_paginated(
        api_client.list_room_block_commitments(
            sales_manager_headers, params={"opportunity_id": opportunity_id}
        )
    )
    assert meta["total_count"] == 1, "the 412 must have created no commitment"


def test_incentive_decision_rejects_a_fund_version_invalidated_by_a_receipt():
    """A lodging-tax receipt bumps the fund's version (and its budget), so the
    approver's earlier token is stale and the decision is 412; the retry against
    the refreshed version charges the fund exactly once.

    PRD: "Decisions on other bid packages, posted lodging-tax receipts and every decommit all bump the fund's `version`, so a decision quoting an outdated fund version is rejected with `ERR_STALE_FUND_VERSION` and HTTP 412 rather than charged against a balance that has already moved." (PRD S2.6)
    PRD: "Posting a receipt raises both `lodging_tax_receipts_total` and `budget_amount` by the receipt `amount`, recomputes `uncommitted_amount` from the conservation identity, re-derives `posture`, and bumps the fund's `version` by one" (PRD S3.1)

    Design: Corner/cross_cutting_complexity_layers/incentive_decision_rejects_a_fund_version_invalidated_by_a_receipt
    """
    scenario = fixtures.setup_bid_incentive_pending()
    bid_id = scenario["bid_id"]
    fund_id = scenario["fund_id"]
    approver = make_incentive_approver_headers(INCENTIVE_APPROVER_USER_ID)

    fund_read = fixtures.read_fund(fund_id)
    v_read = fund_read["version"]
    assert_money_equals(fund_read["uncommitted_amount"], 500_000.00, "uncommitted before receipt")

    fixtures.post_receipt(fund_id, 20_000.00, "2027-03-01T00:00:00Z")

    stale = api_client.create_incentive_decision(
        bid_id,
        incentive_decision_payload(fund_id, "APPROVED", 12_000.00, v_read),
        approver,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_FUND_VERSION.value, 412)

    mid = fixtures.read_fund(fund_id)
    v_fresh = mid["version"]
    assert v_fresh == v_read + 1, (
        f"the receipt bumps the fund version once: {v_read} -> {v_fresh}"
    )
    assert_money_equals(mid["lodging_tax_receipts_total"], 20_000.00, "receipts total")
    assert_money_equals(mid["budget_amount"], 520_000.00, "budget after receipt")
    assert_money_equals(mid["uncommitted_amount"], 520_000.00, "uncommitted after receipt")
    assert_money_equals(mid["committed_amount"], 0.00, "committed after the refused decision")

    retry = api_client.create_incentive_decision(
        bid_id,
        incentive_decision_payload(fund_id, "APPROVED", 12_000.00, v_fresh),
        approver,
    )
    decision = validate_success(retry, expected_status=201)
    assert_money_equals(decision["approved_amount"], 12_000.00, "approved_amount")
    assert_money_equals(decision["admin_fee_amount"], 600.00, "admin_fee_amount")
    assert_money_equals(decision["total_charge_amount"], 12_600.00, "total_charge_amount")

    final = fixtures.read_fund(fund_id)
    assert final["version"] == v_fresh + 1, (
        f"charging the fund bumps its version once: {v_fresh} -> {final['version']}"
    )
    assert_money_equals(final["committed_amount"], 12_600.00, "committed after the charge")
    assert_money_equals(final["uncommitted_amount"], 507_400.00, "uncommitted after the charge")
    assert_money_equals(final["budget_amount"], 520_000.00, "budget after the charge")
    assert_fund_conservation_identity(final)

    _rows, meta = validate_paginated(
        api_client.list_bid_incentive_decisions(bid_id, approver)
    )
    assert meta["total_count"] == 1, "the 412 must have stored no decision"


def test_losing_a_bidding_opportunity_fans_out_to_five_dependent_records_at_once(
    sales_manager_headers, center_scheduler_headers,
):
    """One lose call answers with the lead already LOST and RELEASED at zero
    coverage, and in the same request releases the hold, withdraws all three
    blocks and declines the live bid.

    PRD: "The stage moves to `LOST`, the reason is stored, and the lead's `version` is incremented by one. When the lead was in `BIDDING`, the live package - whatever its status among `DRAFT`, `INCENTIVE_PENDING`, `APPROVED` and `SUBMITTED` - is moved to `DECLINED` with its `decline_reason` mapped from the lead's `lost_reason`: `RATE_TOO_HIGH`, `INSUFFICIENT_INCENTIVE` and `LOST_TO_COMPETITOR` map through unchanged" (PRD S3.8)
    PRD: "Every space hold of the lead in status `HELD` or `CHALLENGED` is released with `release_reason` `OPPORTUNITY_LOST` ... Every room block commitment of the lead in status `INVITED`, `OFFERED` or `COMMITTED` is withdrawn with `withdraw_reason` `OPPORTUNITY_LOST` ... And the lead's `hold_posture` becomes `RELEASED` once no non-terminal hold of its own remains." (PRD S3.8)

    Design: Corner/cross_cutting_complexity_layers/losing_a_bidding_opportunity_fans_out_to_five_dependent_records_at_once
    """
    scenario = fixtures.setup_bid_submitted()
    opportunity_id = scenario["opportunity_id"]

    lost = validate_success(
        api_client.lose_opportunity(
            opportunity_id,
            {"lost_reason": LostReason.LOST_TO_COMPETITOR.value},
            sales_manager_headers,
        )
    )
    # The lose response itself already carries every recomputed aggregate.
    assert lost["sales_stage"] == SalesStage.LOST.value
    assert lost["lost_reason"] == LostReason.LOST_TO_COMPETITOR.value
    assert lost["hold_posture"] == HoldPosture.RELEASED.value
    assert lost["committed_peak_rooms"] == 0
    assert float(lost["block_coverage_pct"]) == 0.00, (
        f"coverage is re-derived from the committed set: {lost['block_coverage_pct']}"
    )

    hold = validate_success(
        api_client.get_space_hold(scenario["hold_id"], center_scheduler_headers)
    )
    assert hold["status"] == SpaceHoldStatus.RELEASED.value
    assert hold["release_reason"] == ReleaseReason.OPPORTUNITY_LOST.value

    rows, meta = validate_paginated(
        api_client.list_room_block_commitments(
            sales_manager_headers, params={"opportunity_id": opportunity_id}
        )
    )
    assert meta["total_count"] == 3, "all three properties leave the block at once"
    for row in rows:
        assert row["withdraw_reason"] == WithdrawReason.OPPORTUNITY_LOST.value, (
            f"commitment {row['id']} must carry withdraw_reason OPPORTUNITY_LOST"
        )

    bid = fixtures.read_bid(scenario["bid_id"])
    assert bid["status"] == BidPackageStatus.DECLINED.value
    assert bid["decline_reason"] == LostReason.LOST_TO_COMPETITOR.value


def test_losing_a_bidding_opportunity_reverses_the_fund_charge_and_hotel_counters(
    sales_manager_headers,
):
    """The decommit returns committed_amount to exactly its pre-charge value and
    the properties' room counters are reversed rather than merely stopped, while
    the planner's lost_count rises.

    PRD: "Any live fund charge is decommitted: the fund's `committed_amount` falls by the package's `total_fund_charge_amount`, `uncommitted_amount` rises by the same amount, and `posture` is re-derived." (PRD S3.8)
    PRD: "`definite_count` is the number of that planner's opportunities currently in `sales_stage` `DEFINITE` or `SERVICED`. `lost_count` is the number currently in `LOST`." (PRD S3.1)

    Design: Corner/cross_cutting_complexity_layers/losing_a_bidding_opportunity_fans_out_to_five_dependent_records_at_once
    """
    scenario = fixtures.setup_bid_submitted()
    opportunity_id = scenario["opportunity_id"]
    harborview_id = scenario["hotels"][0]["id"]

    fund_before = fixtures.read_fund(scenario["fund_id"])
    assert_money_equals(fund_before["committed_amount"], 12_600.00, "committed before the loss")
    assert_money_equals(fund_before["uncommitted_amount"], 487_400.00, "uncommitted before the loss")

    hotel_before = fixtures.read_hotel(harborview_id)
    assert hotel_before["committed_peak_rooms"] == 500
    assert hotel_before["committed_room_nights"] == 1000, (
        "500 rooms over the two occupied nights"
    )

    validate_success(
        api_client.lose_opportunity(
            opportunity_id,
            {"lost_reason": LostReason.LOST_TO_COMPETITOR.value},
            sales_manager_headers,
        )
    )

    fund_after = fixtures.read_fund(scenario["fund_id"])
    assert_money_equals(fund_after["committed_amount"], 0.00, "committed after the decommit")
    assert_money_equals(fund_after["uncommitted_amount"], 500_000.00, "uncommitted after the decommit")
    assert_money_equals(fund_after["disbursed_amount"], 0.00, "disbursed after the decommit")
    assert fund_after["posture"] == FundPosture.OPEN.value
    assert_fund_conservation_identity(fund_after)

    hotel_after = fixtures.read_hotel(harborview_id)
    assert hotel_after["committed_peak_rooms"] == 0, "the hotel counters are reversed"
    assert hotel_after["committed_room_nights"] == 0, "the hotel counters are reversed"

    planner = fixtures.read_planner(scenario["planner_id"])
    assert planner["lost_count"] == 1
    assert planner["definite_count"] == 0, (
        "definite_count counts only opportunities currently DEFINITE or SERVICED"
    )


def test_a_final_estimate_prices_the_observed_pickup_not_the_requested_block(
    board_analyst_headers,
):
    """The FINAL variant's basis is the reported pickup (990) against the
    PROVISIONAL's requested 1800, and its lodging spend is the sum of per-night
    rounded products rather than one blended rate.

    PRD: "Its `room_nights_basis` is the sum of `rooms_picked_up` across the eligible pickup records - those belonging to commitments of this lead in status `COMMITTED` or `RELEASED`" (PRD S3.6)
    PRD: "Its `lodging_spend_amount` is not the basis times a single rate but the sum, over those same eligible pickup records, of each record's `rooms_picked_up` multiplied by its own `rate_charged_amount` rounded to two decimals - a per-night rounded product, then summed." (PRD S3.6)

    Design: Corner/cross_cutting_complexity_layers/a_final_estimate_never_retro_prices_the_charge_taken_from_the_provisional
    """
    scenario = fixtures.setup_definite_lead_with_pickup()
    opportunity_id = scenario["opportunity_id"]

    provisional, prov_meta = validate_paginated(
        api_client.list_opportunity_estimates(
            opportunity_id,
            board_analyst_headers,
            params={"variant": EstimateVariant.PROVISIONAL.value},
        )
    )
    assert prov_meta["total_count"] == 1
    assert provisional[0]["room_nights_basis"] == 1800, "the requested citywide total"
    assert_money_equals(
        provisional[0]["lodging_tax_yield_amount"], 59_130.00, "provisional yield"
    )

    final = validate_success(
        api_client.create_economic_impact_estimate(
            estimate_payload(opportunity_id, EstimateVariant.FINAL.value),
            board_analyst_headers,
        ),
        expected_status=201,
    )
    assert final["variant"] == EstimateVariant.FINAL.value
    assert final["room_nights_basis"] == 990, (
        "400 + 250 + 180 + 150 + 10 rooms actually picked up"
    )
    assert_money_equals(final["lodging_spend_amount"], 210_533.70, "final lodging spend")
    assert_money_equals(
        final["lodging_tax_yield_amount"], 31_580.06, "final yield (0.15 * 210533.70)"
    )


def test_a_final_estimate_never_retro_prices_the_charge_taken_from_the_provisional(
    board_analyst_headers,
):
    """Producing a FINAL estimate posts no ledger delta and leaves the bid's fee,
    total charge and payback ratio exactly as the PROVISIONAL snapshot priced
    them, with both snapshots still listed under their own variant.

    PRD: "Each estimate is an immutable snapshot carrying `id`, `created_at` and a `computed_at` stamped from the logical clock, with no `updated_at` and no `version`. Estimates of one lead are readable as a sub-collection, newest last, filterable by `variant`." (PRD S3.6)
    PRD: "Finally `tax_payback_ratio` is the newest `PROVISIONAL` estimate's `lodging_tax_yield_amount` divided by `total_charge_amount`, rounded half-up to two decimals." (PRD S3.7)

    Design: Corner/cross_cutting_complexity_layers/a_final_estimate_never_retro_prices_the_charge_taken_from_the_provisional
    """
    scenario = fixtures.setup_definite_lead_with_pickup()
    opportunity_id = scenario["opportunity_id"]
    bid_id = scenario["bid_id"]

    before = fixtures.read_bid(bid_id)
    assert_money_equals(before["admin_fee_amount"], 600.00, "admin fee before")
    assert_money_equals(before["total_fund_charge_amount"], 12_600.00, "charge before")
    assert_money_equals(before["tax_payback_ratio"], 4.69, "payback before")

    validate_success(
        api_client.create_economic_impact_estimate(
            estimate_payload(opportunity_id, EstimateVariant.FINAL.value),
            board_analyst_headers,
        ),
        expected_status=201,
    )

    after = fixtures.read_bid(bid_id)
    assert_money_equals(after["admin_fee_amount"], 600.00, "admin fee after")
    assert_money_equals(after["total_fund_charge_amount"], 12_600.00, "charge after")
    assert_money_equals(after["tax_payback_ratio"], 4.69, "payback after")

    fund = fixtures.read_fund(scenario["fund_id"])
    assert_money_equals(fund["committed_amount"], 12_600.00, "committed after the FINAL")
    assert_money_equals(fund["uncommitted_amount"], 487_400.00, "uncommitted after the FINAL")
    assert_fund_conservation_identity(fund)

    rows, meta = validate_paginated(
        api_client.list_opportunity_estimates(opportunity_id, board_analyst_headers)
    )
    assert meta["total_count"] == 2, "the two variants coexist"
    assert rows[0]["variant"] == EstimateVariant.PROVISIONAL.value, (
        "the sub-collection is newest last, so the PROVISIONAL snapshot comes first"
    )
    for variant in (EstimateVariant.PROVISIONAL.value, EstimateVariant.FINAL.value):
        _one, one_meta = validate_paginated(
            api_client.list_opportunity_estimates(
                opportunity_id, board_analyst_headers, params={"variant": variant}
            )
        )
        assert one_meta["total_count"] == 1, f"exactly one {variant} row"


def test_the_incentive_band_ladder_is_marginal_at_exactly_five_thousand_nights(
    board_analyst_headers,
):
    """At exactly 5000 requested room nights the band ceiling is 60000.00; the
    5001st night adds only 8.00, and a 15001-night event steps down to 5.00.

    PRD: "First, a marginal band ladder is walked over the lead's `total_room_nights_requested`: the first 5,000 requested room nights are worth 12.00 dollars each, the next 10,000 room nights - those from the 5,001st through the 15,000th - are worth 8.00 dollars each, and every room night beyond the 15,000th is worth 5.00 dollars, with the three band contributions added and the total rounded half-up to two decimals to give the band ceiling." (PRD S3.7)
    PRD: "Third, the smaller of those two ceilings is taken and multiplied by a coverage factor drawn from the lead's current `block_coverage_pct`: the factor is 1.00 when coverage is at least 95.00 percent" (PRD S3.7)

    Design: Corner/cross_cutting_complexity_layers/the_incentive_band_ladder_is_marginal_at_exactly_five_thousand_nights
    """
    scenario = _band_ladder_scenario()
    leads = scenario["leads"]

    planner = fixtures.read_planner(scenario["planner_id"])
    assert planner["relationship_score_lifetime"] == 68, (
        "4 legacy definites * 12 + min(40, floor(10000 / 500)) == 48 + 20"
    )
    assert planner["tier"] == PlannerTier.TIER_A.value

    caps = {}
    for nights, requested in ((5000, 60_000.00), (5001, 60_008.00), (15001, 140_005.00)):
        requested_bid = fixtures.ask_for_incentive(leads[nights]["bid_id"], requested)
        caps[nights] = requested_bid["incentive_cap_amount"]

    assert_money_equals(caps[5000], 60_000.00, "cap at 5000 nights (5000 * 12.00)")
    assert_money_equals(
        caps[5001], 60_008.00,
        "cap at 5001 nights: 8.00 more than the 5000-night cap, not 40008.00",
    )
    assert_money_equals(
        caps[15001], 140_005.00,
        "cap at 15001 nights (5000 * 12.00 + 10000 * 8.00 + 1 * 5.00)",
    )

    # The TIER_A lodging-tax yield ceiling for the 5001-night lead is
    # 0.35 * 300060.00 == 105021.00, far above 60008.00, so the band ladder was
    # the binding term in every one of the three caps.
    estimates, meta = validate_paginated(
        api_client.list_opportunity_estimates(
            leads[5001]["opportunity_id"],
            board_analyst_headers,
            params={"variant": EstimateVariant.PROVISIONAL.value},
        )
    )
    assert meta["total_count"] == 1
    assert_money_equals(
        estimates[0]["lodging_tax_yield_amount"], 300_060.00,
        "0.15 * 5001 * 400.00",
    )


def test_the_commit_response_already_carries_every_cascaded_field(sales_manager_headers):
    """The commit answers with the frozen room figures and the cutoff date
    already materialised, and the very next read of the lead already shows the
    recomputed citywide coverage and spread.

    PRD: "Whenever a primary record changes, every aggregate downstream of it is recomputed in the same request, before the response is written." (PRD S2.9)
    PRD: "A successful commit freezes `rooms_peak_committed` at the value of `rooms_peak_offered` and sets `committed_room_nights` to `rooms_peak_committed` multiplied by the lead's `event_nights`." (PRD S3.5)

    Design: Corner/consistency_model/every_cascaded_field_is_already_correct_in_the_triggering_response
    """
    scenario = fixtures.setup_lead(clock="2027-03-01T00:00:00Z")
    opportunity_id = scenario["opportunity_id"]
    harborview, bayside, cityline = scenario["hotels"]

    fixtures.add_committed_block(opportunity_id, bayside["id"], 300, 209.77, 30)
    fixtures.add_committed_block(opportunity_id, cityline["id"], 100, 199.51, 30)
    harborview_commitment = fixtures.invite_hotel(
        opportunity_id, harborview["id"], rooms_peak_invited=500
    )
    fixtures.offer_block(harborview_commitment["id"], harborview["id"], 500, 214.33, 30)

    before = fixtures.read_opportunity(opportunity_id)
    assert before["committed_peak_rooms"] == 400
    assert float(before["block_coverage_pct"]) == 40.00, (
        f"400 of 1000 requested peak rooms: {before['block_coverage_pct']}"
    )

    committed = validate_success(
        api_client.commit_room_block_commitment(
            harborview_commitment["id"], sales_manager_headers
        )
    )
    assert committed["status"] == CommitmentStatus.COMMITTED.value
    assert committed["rooms_peak_committed"] == 500
    assert committed["committed_room_nights"] == 1000, "500 rooms * 2 event nights"
    assert committed["cutoff_date"] == "2028-03-11", (
        "arrival 2028-04-10 less the 30-day cutoff"
    )

    after = fixtures.read_opportunity(opportunity_id)
    assert after["committed_peak_rooms"] == 900
    assert float(after["block_coverage_pct"]) == 90.00, (
        f"900 of 1000 requested peak rooms: {after['block_coverage_pct']}"
    )
    assert after["cutoff_alignment_spread_days"] == 0, "all three cutoffs are 30 days"
    assert after["citywide_cutoff_days_before_arrival"] == 30


def test_the_acceptance_cascade_is_fully_visible_on_the_first_read_after_it(
    sales_manager_headers, board_analyst_headers, center_scheduler_headers,
):
    """The four-hop acceptance already reports DEFINITE, CONFIRMED, the frozen
    definite room nights and definite_at on the very first read, and repeating
    the read changes nothing.

    PRD: "Hop 2: because the bid was accepted, the lead's `sales_stage` moves from `BIDDING` to `DEFINITE`, its `definite_at` is stamped from the logical clock, and its `definite_room_nights` is frozen at `committed_peak_rooms` multiplied by `event_nights`" (PRD S3.8)
    PRD: "Hop 3: because the lead became `DEFINITE`, its `FIRST`-rank space hold in status `HELD` or `CHALLENGED` is confirmed exactly as described at the end of Section 3.4, and the lead's `hold_posture` becomes `CONFIRMED`" (PRD S3.8)

    Design: Corner/consistency_model/every_cascaded_field_is_already_correct_in_the_triggering_response
    """
    scenario = fixtures.setup_bid_submitted()
    opportunity_id = scenario["opportunity_id"]

    accepted = validate_success(
        api_client.planner_response(
            scenario["bid_id"],
            {"response": PlannerResponse.ACCEPTED.value},
            make_meeting_planner_headers(scenario["planner_id"]),
        )
    )
    assert accepted["status"] == BidPackageStatus.ACCEPTED.value
    assert accepted["planner_response"] == PlannerResponse.ACCEPTED.value

    first = validate_success(
        api_client.get_opportunity(opportunity_id, sales_manager_headers)
    )
    assert first["sales_stage"] == SalesStage.DEFINITE.value
    assert first["hold_posture"] == HoldPosture.CONFIRMED.value
    assert first["definite_room_nights"] == 1800, "900 committed peak rooms * 2 nights"
    assert same_instant(first["definite_at"], "2027-03-01T00:00:00Z"), (
        f"definite_at is stamped from the logical clock, got {first['definite_at']!r}"
    )

    second = validate_success(
        api_client.get_opportunity(opportunity_id, board_analyst_headers)
    )
    assert second == first, (
        "repeating the read must return identical data - nothing settles later"
    )

    hold = validate_success(
        api_client.get_space_hold(scenario["hold_id"], center_scheduler_headers)
    )
    assert hold["status"] == SpaceHoldStatus.CONFIRMED.value

    hall = fixtures.read_hall(scenario["hall_id"])
    assert hall["confirmed_hold_count"] == 1, (
        "the hall's confirmed-hold counter moves in the same instant"
    )
