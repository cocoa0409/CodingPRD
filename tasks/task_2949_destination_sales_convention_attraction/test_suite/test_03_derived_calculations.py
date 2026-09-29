"""Derived calculations: impact rounding, attrition, citywide rollups, fee bands,
promotion selection, relationship scores and board-report windows.

Every test in this module translates exactly one instance of the
``calculations`` section of the corner design index.  Each figure asserted here
was re-derived from the PRD's own formulas and its round-half-up discipline
(Section 2.5) before being written down.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    CANONICAL_OPPORTUNITY,
    DEFAULT_PICKUPS,
    TEST_USERS,
    add_committed_block,
    answer_bid,
    api_client,
    ask_for_incentive,
    assert_board_report,
    assert_economic_impact_estimate,
    assert_incentive_decision,
    assert_meeting_planner,
    assert_money_equals,
    assert_opportunity,
    assert_room_block_commitment,
    assert_space_hold,
    attach_letters,
    create_board_report_payload,
    create_lead,
    create_report,
    DEFAULT_ALLOCATIONS,
    decide_incentive,
    estimate_payload,
    fund_version,
    incentive_decision_payload,
    invite_hotel,
    is_valid_uuid,
    lose_lead,
    make_incentive_approver_headers,
    offer_block,
    open_bid,
    post_receipt,
    place_hold,
    qualify_lead,
    read_commitment,
    read_fund,
    read_hold,
    read_opportunity,
    read_planner,
    register_hall,
    register_planner,
    release_hold,
    same_instant,
    set_clock,
    setup_bid_approved,
    setup_definite_lead,
    setup_definite_lead_with_pickup,
    setup_inventory,
    setup_lead,
    submit_bid,
    submit_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["bureau_admin_headers"]
SALES = TEST_USERS["sales_manager_headers"]
SCHEDULER = TEST_USERS["center_scheduler_headers"]
APPROVER = TEST_USERS["incentive_approver_headers"]
ANALYST = TEST_USERS["board_analyst_headers"]

PCT_TOLERANCE = 0.005


# --- economic impact estimate arithmetic -------------------------------------

HALF_CENT_OPPORTUNITY = {
    "event_name": "Half Cent Colloquium",
    "arrival_date": "2028-04-10",
    "departure_date": "2028-04-12",
    "peak_rooms_requested": 5,
    "total_room_nights_requested": 10,
    "attendance_estimate": 1,
    "exhibit_sqft_requested": 1000,
    "rate_ceiling_amount": 100.01,
}


def test_impact_components_round_half_up_before_the_indirect_multiplier():
    """A PROVISIONAL estimate rounds each component half-up first, then feeds the
    already-rounded direct spend through the 1.65 multiplier and the 0.15 tax rate.

    PRD: "Component-level rounding precedes summation. Where a total is defined as the sum of named components -- the three spend components of an economic impact estimate, or the per-commitment damages of an attrition settlement -- each component is rounded to two decimals *first* and the rounded components are then added." (PRD S2.5)
    PRD: "`total_impact_amount` is `direct_spend_amount` multiplied by an indirect-effects multiplier of 1.65 ... rounded half-up to two decimals. And `lodging_tax_yield_amount`, the single most consequential number in this document, is `lodging_spend_amount` multiplied by the city's lodging tax rate of 0.15, rounded half-up to two decimals" (PRD S3.6)

    Design: Corner/calculations/impact_components_round_half_up_before_the_indirect_multiplier
    """
    scenario = setup_lead(
        clock="2026-08-01T00:00:00Z", opportunity_overrides=HALF_CENT_OPPORTUNITY
    )

    response = api_client.create_economic_impact_estimate(
        estimate_payload(scenario["opportunity_id"], "PROVISIONAL"), ANALYST
    )
    estimate = validate_success(response, expected_status=201)
    assert_economic_impact_estimate(estimate)

    assert estimate["variant"] == "PROVISIONAL"
    assert estimate["room_nights_basis"] == 10, (
        "PROVISIONAL room_nights_basis is the lead's total_room_nights_requested"
    )
    # 10 room nights * 100.01 rate ceiling
    assert_money_equals(estimate["lodging_spend_amount"], 1000.10, "lodging_spend_amount")
    # 1 delegate * 2 event nights * 285.00
    assert_money_equals(estimate["delegate_spend_amount"], 570.00, "delegate_spend_amount")
    # 1000 sqft * 4.75
    assert_money_equals(estimate["exhibitor_spend_amount"], 4750.00, "exhibitor_spend_amount")
    # the three already-rounded components summed
    assert_money_equals(estimate["direct_spend_amount"], 6320.10, "direct_spend_amount")
    # 6320.10 * 1.65 == 10428.165 -> half up -> 10428.17, never 10428.16
    assert_money_equals(estimate["total_impact_amount"], 10428.17, "total_impact_amount")
    # 1000.10 * 0.15 == 150.015 -> half up -> 150.02, never 150.01
    assert_money_equals(estimate["lodging_tax_yield_amount"], 150.02, "lodging_tax_yield_amount")
    assert same_instant(estimate["computed_at"], "2026-08-01T00:00:00Z"), (
        f"computed_at is stamped from the logical clock, got {estimate['computed_at']!r}"
    )


def test_final_variant_without_any_pickup_is_not_available():
    """A FINAL estimate on a lead with no pickup record anywhere is refused 422 while
    the PROVISIONAL variant computes from the same row, and the refusal stores nothing.

    PRD: "Because a `FINAL` estimate is meaningless before any pickup has been reported, requesting one while the lead has no pickup record on any commitment in `COMMITTED` or `RELEASED` is refused with `ERR_ESTIMATE_VARIANT_NOT_AVAILABLE` and HTTP 422." (PRD S3.6)

    Design: Corner/calculations/final_variant_without_any_pickup_returns_estimate_variant_not_available
    """
    scenario = setup_lead(
        clock="2026-08-01T00:00:00Z", opportunity_overrides=HALF_CENT_OPPORTUNITY
    )
    opportunity_id = scenario["opportunity_id"]

    final_response = api_client.create_economic_impact_estimate(
        estimate_payload(opportunity_id, "FINAL"), SALES
    )
    validate_error(
        final_response,
        ApiErrorId.ERR_ESTIMATE_VARIANT_NOT_AVAILABLE.value,
        expected_status=422,
    )

    provisional_response = api_client.create_economic_impact_estimate(
        estimate_payload(opportunity_id, "PROVISIONAL"), SALES
    )
    provisional = validate_success(provisional_response, expected_status=201)
    assert is_valid_uuid(provisional["id"])
    assert provisional["variant"] == "PROVISIONAL"

    listed, meta = validate_paginated(
        api_client.list_opportunity_estimates(
            opportunity_id, ANALYST, params={"variant": "FINAL"}
        )
    )
    assert meta["total_count"] == 0, (
        f"the rejected FINAL request must store nothing, got {meta['total_count']} rows"
    )
    assert listed == []


# --- attrition settlement ----------------------------------------------------

def test_attrition_skips_commitments_with_no_pickup_at_all():
    """A committed property that filed no pickup row is skipped entirely rather than
    charged its full 80 percent allowance, and the settlement adds the rounded
    per-commitment damages of the two properties that did report.

    PRD: "Only commitments in status `COMMITTED` or `RELEASED` participate; commitments in `INVITED`, `OFFERED` or `WITHDRAWN` contribute 0.00, and a commitment with no pickup record at all is skipped entirely rather than assessed -- no shortfall is charged before any pickup has been reported" (PRD S3.9)
    PRD: "the allowance is 80 percent of its `committed_room_nights`, taking the floor to a whole number of nights; the shortfall, exposed as `attrition_shortfall_nights`, is that allowance less the commitment's `picked_up_room_nights` ... multiplied by the commitment's `rate_offered_amount` and then by a damage rate of 0.75 ... rounded half-up to two decimals" (PRD S3.9)

    Design: Corner/calculations/attrition_skips_commitments_that_reported_no_pickup_at_all
    """
    # The canonical definite chain, minus the Cityline pickup row.
    scenario = setup_definite_lead_with_pickup(pickups=DEFAULT_PICKUPS[:4])
    harborview, bayside, cityline = scenario["commitments"]

    _, cityline_meta = validate_paginated(
        api_client.list_pickup_records(cityline["id"], SALES)
    )
    assert cityline_meta["total_count"] == 0, (
        "the Cityline commitment must carry no pickup record at all"
    )

    first = read_commitment(harborview["id"])
    assert_room_block_commitment(first)
    assert first["committed_room_nights"] == 1000, "500 peak rooms * 2 event nights"
    assert first["picked_up_room_nights"] == 650, "400 + 250 rooms reported"
    # floor(1000 * 0.80) == 800 allowance, less 650 picked up
    assert first["attrition_shortfall_nights"] == 150
    # 150 * 214.33 * 0.75 == 24112.125 -> half up -> 24112.13
    assert_money_equals(first["attrition_damages_amount"], 24112.13, "Harborview damages")

    second = read_commitment(bayside["id"])
    assert second["committed_room_nights"] == 600, "300 peak rooms * 2 event nights"
    assert second["picked_up_room_nights"] == 330, "180 + 150 rooms reported"
    # floor(600 * 0.80) == 480 allowance, less 330 picked up
    assert second["attrition_shortfall_nights"] == 150
    # 150 * 209.77 * 0.75 == 23599.125 -> half up -> 23599.13
    assert_money_equals(second["attrition_damages_amount"], 23599.13, "Bayside damages")

    third = read_commitment(cityline["id"])
    assert third["committed_room_nights"] == 200, "100 peak rooms * 2 event nights"
    assert third["picked_up_room_nights"] == 0
    assert third["attrition_shortfall_nights"] == 0, (
        "no pickup record means no assessment, not a full 160-night shortfall"
    )
    assert_money_equals(third["attrition_damages_amount"], 0.00, "Cityline damages")

    opportunity = read_opportunity(scenario["opportunity_id"])
    assert_opportunity(opportunity)
    # 24112.13 + 23599.13, with the unreported property contributing nothing
    assert_money_equals(
        opportunity["attrition_settlement_amount"], 47711.26, "attrition_settlement_amount"
    )


# --- citywide block rollup ---------------------------------------------------

def test_citywide_rollup_counts_committed_rows_only():
    """An OFFERED commitment is invisible to the lead's citywide peak, coverage,
    cutoff and spread figures; committing it moves all four in one hop.

    PRD: "Finally the lead's citywide figures are re-derived from its commitments in status `COMMITTED` only, with commitments in `INVITED`, `OFFERED`, `WITHDRAWN` and `RELEASED` all excluded: `committed_peak_rooms` on the opportunity is the sum of `rooms_peak_committed`; `block_coverage_pct` is that committed peak multiplied by 100 and divided by `peak_rooms_requested`, rounded half-up to two decimals; `citywide_cutoff_days_before_arrival` is the **largest** `cutoff_days_before_arrival` among the committed properties ... and `cutoff_alignment_spread_days` is the largest such value minus the smallest" (PRD S3.5)
    PRD: "A successful offer stores the three fields, derives `cutoff_date` as the lead's `arrival_date` less `cutoff_days_before_arrival` days" (PRD S3.5)

    Design: Corner/calculations/citywide_coverage_and_cutoff_spread_count_committed_rows_only
    """
    scenario = setup_lead(clock="2026-08-01T00:00:00Z")
    opportunity_id = scenario["opportunity_id"]
    harborview, bayside, cityline = scenario["hotels"]

    add_committed_block(opportunity_id, harborview["id"], 500, 214.33, 30)
    add_committed_block(opportunity_id, bayside["id"], 300, 209.77, 31)
    offered = invite_hotel(opportunity_id, cityline["id"], 200)
    offer_block(offered["id"], cityline["id"], 200, 199.51, 45)

    before = read_opportunity(opportunity_id)
    assert before["committed_peak_rooms"] == 800, "500 + 300; the OFFERED 200 is excluded"
    assert float(before["block_coverage_pct"]) == pytest.approx(80.00, abs=PCT_TOLERANCE), (
        f"800 * 100 / 1000 == 80.00, got {before['block_coverage_pct']}"
    )
    assert before["citywide_cutoff_days_before_arrival"] == 31, "max(30, 31)"
    assert before["cutoff_alignment_spread_days"] == 1, "31 - 30"

    committed = validate_success(
        api_client.commit_room_block_commitment(offered["id"], SALES)
    )
    assert committed["status"] == "COMMITTED"
    assert committed["rooms_peak_committed"] == 200, (
        "landing exactly on the property's committable_rooms is allowed"
    )
    assert committed["cutoff_date"] == "2028-02-25", (
        f"arrival 2028-04-10 less 45 days, got {committed['cutoff_date']!r}"
    )

    after = read_opportunity(opportunity_id)
    assert after["committed_peak_rooms"] == 1000, "500 + 300 + 200"
    assert float(after["block_coverage_pct"]) == pytest.approx(100.00, abs=PCT_TOLERANCE), (
        f"1000 * 100 / 1000 == 100.00, got {after['block_coverage_pct']}"
    )
    assert after["citywide_cutoff_days_before_arrival"] == 45, "max(30, 31, 45)"
    assert after["cutoff_alignment_spread_days"] == 15, "45 - 30"


def test_cutoff_spread_from_the_committed_rollup_blocks_submission():
    """A citywide block whose committed properties release rooms 15 days apart clears
    the coverage floor but fails the cutoff-alignment gate at submission.

    PRD: "And the lead's `cutoff_alignment_spread_days` must be at most 2, or the submission fails with `ERR_CUTOFF_MISALIGNED`; a block whose properties release unsold rooms more than two days apart cannot be advertised with a single citywide cutoff." (PRD S3.8)

    Design: Corner/calculations/citywide_coverage_and_cutoff_spread_count_committed_rows_only
    """
    scenario = setup_bid_approved(
        clock="2026-08-01T00:00:00Z",
        allocations=((0, 500, 214.33, 30), (1, 300, 209.77, 31), (2, 200, 199.51, 45)),
    )
    opportunity = read_opportunity(scenario["opportunity_id"])
    assert float(opportunity["block_coverage_pct"]) == pytest.approx(
        100.00, abs=PCT_TOLERANCE
    ), "coverage is fully assembled, so only the cutoff gate can fail"
    assert opportunity["cutoff_alignment_spread_days"] == 15

    response = api_client.submit_bid_package(
        scenario["bid_id"], submit_payload("2026-09-01T00:00:00Z"), SALES
    )
    validate_error(response, ApiErrorId.ERR_CUTOFF_MISALIGNED.value, expected_status=422)


# --- administrative fee bands and the incentive cap --------------------------

TIER_A_PLANNER = {
    "org_name": "Tier A Federation",
    "contact_email": "chair@tiera.org",
    "legacy_definite_count": 4,
    "legacy_definite_room_nights": 6000,
}

BAND_BOUNDARY_OPPORTUNITY = {
    "arrival_date": "2028-04-10",
    "departure_date": "2028-04-22",
    "peak_rooms_requested": 1000,
    "total_room_nights_requested": 12000,
    "attendance_estimate": 8000,
    "exhibit_sqft_requested": 200_000,
    "rate_ceiling_amount": 200.00,
}


def _fully_covered_lead(planner_id, hotel_id, event_name):
    """A QUALIFIED 12-night lead whose 1000-room peak is covered by one property."""
    payload = dict(BAND_BOUNDARY_OPPORTUNITY, event_name=event_name)
    opportunity = create_lead(planner_id, **payload)
    qualify_lead(opportunity["id"])
    add_committed_block(opportunity["id"], hotel_id, 1000, 200.00, 30)
    return read_opportunity(opportunity["id"])


def test_fee_band_ceiling_is_exclusive_at_one_hundred_thousand():
    """The 5 percent band ends strictly below 100,000.00, so a gross of exactly
    100,000.00 attracts 4 percent and costs the fund 999.99 less in total than a gross
    of 99,999.99 does.

    PRD: "Select the administrative fee rate from **that gross figure only**: 0.05 when the gross is below 100,000.00, 0.04 when the gross is at or above 100,000.00 but below 250,000.00, and 0.03 when the gross is at or above 250,000.00. The `admin_fee_amount` is the gross multiplied by that rate, rounded half-up to two decimals, and `total_charge_amount` is the gross plus that fee." (PRD S3.7)
    PRD: "Finally `tax_payback_ratio` is the newest `PROVISIONAL` estimate's `lodging_tax_yield_amount` divided by `total_charge_amount`, rounded half-up to two decimals." (PRD S3.7)

    Design: Corner/calculations/fee_band_ceiling_is_exclusive_so_one_extra_cent_of_gross_costs_less
    """
    scenario = setup_inventory(
        clock="2026-08-01T00:00:00Z",
        planner_overrides=TIER_A_PLANNER,
        hotel_specs=(("Harborview Grand", 1200, 2), ("Bayside Suites", 1200, 4)),
    )
    planner = read_planner(scenario["planner_id"])
    assert_meeting_planner(planner)
    # 4 legacy definites * 12 + min(40, floor(6000 / 500)) == 48 + 12 == 60
    assert planner["relationship_score_lifetime"] == 60
    assert planner["tier"] == "TIER_A", "the TIER_A floor of 60 is inclusive"

    fund_id = scenario["fund_id"]
    lead_x = _fully_covered_lead(
        scenario["planner_id"], scenario["hotels"][0]["id"], "Band Edge X"
    )
    lead_y = _fully_covered_lead(
        scenario["planner_id"], scenario["hotels"][1]["id"], "Band Edge Y"
    )
    for lead in (lead_x, lead_y):
        assert float(lead["block_coverage_pct"]) == pytest.approx(
            100.00, abs=PCT_TOLERANCE
        ), "coverage 100.00 pins the coverage factor at 1.00"

    bid_x = open_bid(lead_x["id"])
    bid_y = open_bid(lead_y["id"])
    request_x = ask_for_incentive(bid_x["id"], 99_999.99)
    request_y = ask_for_incentive(bid_y["id"], 100_000.00)
    # band ceiling 5000 * 12.00 + 7000 * 8.00 == 116000.00, below the TIER_A yield
    # ceiling of 360000.00 * 0.35 == 126000.00, times a coverage factor of 1.00
    assert_money_equals(request_x["incentive_cap_amount"], 116_000.00, "cap on X")
    assert_money_equals(request_y["incentive_cap_amount"], 116_000.00, "cap on Y")

    decision_x = validate_success(
        api_client.create_incentive_decision(
            bid_x["id"],
            incentive_decision_payload(
                fund_id, "APPROVED", 99_999.99, fund_version(fund_id)
            ),
            make_incentive_approver_headers("approver-01"),
        ),
        expected_status=201,
    )
    assert_incentive_decision(decision_x)
    # 99999.99 * 0.05 == 4999.9995 -> half up -> 5000.00
    assert_money_equals(decision_x["admin_fee_amount"], 5000.00, "fee on X")
    assert_money_equals(decision_x["total_charge_amount"], 104_999.99, "charge on X")
    # 360000.00 / 104999.99 == 3.4285... -> 3.43
    assert_money_equals(decision_x["tax_payback_ratio"], 3.43, "payback on X")

    mid_fund = read_fund(fund_id)
    assert_money_equals(mid_fund["committed_amount"], 104_999.99, "committed after X")

    decision_y = validate_success(
        api_client.create_incentive_decision(
            bid_y["id"],
            incentive_decision_payload(
                fund_id, "APPROVED", 100_000.00, fund_version(fund_id)
            ),
            make_incentive_approver_headers("approver-01"),
        ),
        expected_status=201,
    )
    # a gross of exactly 100000.00 is NOT in band 1: 100000.00 * 0.04 == 4000.00
    assert_money_equals(decision_y["admin_fee_amount"], 4000.00, "fee on Y")
    assert_money_equals(decision_y["total_charge_amount"], 104_000.00, "charge on Y")
    # 360000.00 / 104000.00 == 3.4615... -> 3.46
    assert_money_equals(decision_y["tax_payback_ratio"], 3.46, "payback on Y")
    assert float(decision_y["total_charge_amount"]) < float(
        decision_x["total_charge_amount"]
    ), "the fee ladder is deliberately non-monotonic at the band boundary"

    end_fund = read_fund(fund_id)
    assert_money_equals(end_fund["committed_amount"], 208_999.99, "committed after Y")
    assert_money_equals(end_fund["uncommitted_amount"], 291_000.01, "uncommitted after Y")
    assert end_fund["posture"] == "OPEN", (
        "291000.01 is far above ten percent of the 500000.00 budget"
    )


# --- promotion selection -----------------------------------------------------

# The incumbent FIRST hold spans a long window that both challengers conflict with;
# the two challenger windows sit at opposite ends of it so that they conflict with the
# incumbent but NOT with each other.  That keeps each challenger's blocking set at a
# single hold, which is what the PRD requires for a SECOND rank to be granted at all.
_INCUMBENT_WINDOW = ("2028-04-08T00:00:00Z", "2028-04-20T00:00:00Z")
_HEAD_WINDOW = ("2028-04-06T00:00:00Z", "2028-04-09T00:00:00Z")
_TAIL_WINDOW = ("2028-04-18T00:00:00Z", "2028-04-22T00:00:00Z")

TWIN_PEAK_ROOMS = 700


def _twin_second_holds(first_window, second_window):
    """One FIRST hold plus two equal-peak SECOND holds created at distinct clocks.

    The hold on ``first_window`` is created at 2026-08-01, the hold on
    ``second_window`` a day later, so ``created_at`` ascending is unambiguous.
    """
    set_clock("2026-08-01T00:00:00Z")
    planner = register_planner()
    hall = register_hall(name="Grand Hall A", turnaround_hours=48)

    incumbent = create_lead(
        planner["id"], **dict(CANONICAL_OPPORTUNITY, event_name="Incumbent Congress")
    )
    qualify_lead(incumbent["id"])
    incumbent_hold = place_hold(
        incumbent["id"],
        hall["id"],
        move_in_start=_INCUMBENT_WINDOW[0],
        move_out_end=_INCUMBENT_WINDOW[1],
    )

    def _challenger(name, window):
        lead = create_lead(
            planner["id"],
            **dict(
                CANONICAL_OPPORTUNITY,
                event_name=name,
                peak_rooms_requested=TWIN_PEAK_ROOMS,
                total_room_nights_requested=1200,
                attendance_estimate=6000,
                exhibit_sqft_requested=150_000,
                rate_ceiling_amount=209.00,
            ),
        )
        qualify_lead(lead["id"])
        hold = place_hold(
            lead["id"], hall["id"], move_in_start=window[0], move_out_end=window[1]
        )
        return {"opportunity_id": lead["id"], "hold": hold}

    earlier = _challenger("Twin Bid Earlier", first_window)
    set_clock("2026-08-02T00:00:00Z")
    later = _challenger("Twin Bid Later", second_window)
    return {
        "hall": hall,
        "incumbent_hold_id": incumbent_hold["id"],
        "earlier": earlier,
        "later": later,
    }


def _assert_promotion_outcome(scenario):
    """Release the incumbent and check that the earlier-created SECOND hold won."""
    released = release_hold(scenario["incumbent_hold_id"])
    assert released["status"] == "RELEASED"
    assert released["release_reason"] == "SCHEDULER_RELEASE"

    winner = read_hold(scenario["earlier"]["hold"]["id"])
    assert_space_hold(winner)
    assert winner["hold_rank"] == "FIRST", (
        "on a tie in peak_rooms_requested the earlier created_at is promoted"
    )
    assert winner["status"] == "HELD"
    assert same_instant(winner["expires_at"], "2026-09-01T00:00:00Z"), (
        "a promoted hold is re-stamped at 30 days after the release clock "
        f"(2026-08-02), got {winner['expires_at']!r}"
    )
    assert read_opportunity(scenario["earlier"]["opportunity_id"])["hold_posture"] == (
        "TENTATIVE"
    )

    loser = read_hold(scenario["later"]["hold"]["id"])
    assert loser["hold_rank"] == "SECOND", "exactly one hold is promoted per vacated window"
    assert loser["status"] == "HELD"
    assert read_opportunity(scenario["later"]["opportunity_id"])["hold_posture"] == "NONE", (
        "being somebody's backup was never a tentative booking"
    )


def test_promotion_tie_on_peak_rooms_is_broken_by_the_earlier_created_hold():
    """Two waiting SECOND holds whose opportunities request the identical 700 peak
    rooms are separated by created_at ascending: the earlier hold is promoted.

    PRD: "Otherwise the winner is chosen by sorting the candidates by the `peak_rooms_requested` of their opportunity in descending order, breaking ties by the hold's own `created_at` in ascending order, and taking the first -- the biggest piece of business wins, and among equals the one that queued earliest wins. The resource identifier is never a tiebreaker." (PRD S3.4)
    PRD: "The winner's `hold_rank` becomes `FIRST`, its `expires_at` is re-stamped at 30 days after the current logical clock, and its opportunity's `hold_posture` becomes `TENTATIVE`. Exactly one hold is promoted per vacated window." (PRD S3.4)

    Design: Corner/calculations/promotion_tie_on_peak_rooms_is_broken_by_the_earlier_created_hold
    """
    scenario = _twin_second_holds(_HEAD_WINDOW, _TAIL_WINDOW)
    assert scenario["earlier"]["hold"]["hold_rank"] == "SECOND"
    assert scenario["later"]["hold"]["hold_rank"] == "SECOND"
    _assert_promotion_outcome(scenario)


def test_promotion_tie_break_follows_creation_order_when_the_windows_are_swapped():
    """Swapping only which of the two equal-peak challengers is created first swaps the
    promotion winner, proving created_at drives the tie-break and the hold id does not.

    PRD: "breaking ties by the hold's own `created_at` in ascending order, and taking the first -- the biggest piece of business wins, and among equals the one that queued earliest wins. The resource identifier is never a tiebreaker." (PRD S3.4)

    Design: Corner/calculations/promotion_tie_on_peak_rooms_is_broken_by_the_earlier_created_hold
    """
    scenario = _twin_second_holds(_TAIL_WINDOW, _HEAD_WINDOW)
    assert scenario["earlier"]["hold"]["hold_rank"] == "SECOND"
    assert scenario["later"]["hold"]["hold_rank"] == "SECOND"
    _assert_promotion_outcome(scenario)


# --- relationship scores and tier --------------------------------------------

def test_planner_score_falls_through_the_tier_b_floor_as_losses_accumulate():
    """Each loss subtracts five points from both score scopes: a lifetime 36 drops to
    31 (still TIER_B, whose floor of 30 is inclusive) and then to 26 / TIER_C, while the
    rolling scope -- which never sees the legacy counters -- clamps at 0 instead of
    going negative.

    PRD: "Within a scope, the raw score is twelve points for each definite convention in scope, plus one point for every full 500 room nights in scope with that room-night term capped at 40 points, minus five points for each lost lead in scope. ... the whole raw score is then clamped into the range 0 to 100 inclusive -- a planner with more losses than wins scores 0 rather than a negative number" (PRD S3.1)
    PRD: "Only the LIFETIME variant derives the planner's `tier`: `TIER_A` when `relationship_score_lifetime` is at least 60, `TIER_B` when it is at least 30, and `TIER_C` otherwise." (PRD S3.1)

    Design: Corner/calculations/planner_score_falls_through_the_tier_b_floor_as_losses_accumulate
    """
    set_clock("2026-08-01T00:00:00Z")
    planner = register_planner(legacy_definite_count=2, legacy_definite_room_nights=6000)
    planner_id = planner["id"]
    # 2 * 12 + min(40, floor(6000 / 500)) == 24 + 12 == 36
    assert planner["relationship_score_lifetime"] == 36
    assert planner["relationship_score_rolling_24m"] == 0, (
        "the rolling scope excludes the migrated legacy counters entirely"
    )
    assert planner["tier"] == "TIER_B"

    first = create_lead(
        planner_id, **dict(CANONICAL_OPPORTUNITY, event_name="First Loss 2028")
    )
    qualify_lead(first["id"])
    second = create_lead(
        planner_id,
        **dict(
            CANONICAL_OPPORTUNITY,
            event_name="Second Loss 2028",
            arrival_date="2028-06-10",
            departure_date="2028-06-12",
            peak_rooms_requested=400,
            total_room_nights_requested=600,
            attendance_estimate=3000,
            exhibit_sqft_requested=40_000,
            rate_ceiling_amount=199.00,
        ),
    )
    qualify_lead(second["id"])

    lose_lead(first["id"], "RATE_TOO_HIGH")
    after_one = read_planner(planner_id)
    assert_meeting_planner(after_one)
    assert after_one["lost_count"] == 1
    # 24 legacy definite points + 12 room-night points - 5 for the loss
    assert after_one["relationship_score_lifetime"] == 31
    assert after_one["tier"] == "TIER_B", "31 is still at or above the TIER_B floor of 30"
    assert after_one["relationship_score_rolling_24m"] == 0, (
        "0 - 5 clamps to 0, never to -5"
    )

    lose_lead(second["id"], "DATES_UNAVAILABLE")
    after_two = read_planner(planner_id)
    assert after_two["lost_count"] == 2
    assert after_two["relationship_score_lifetime"] == 26
    assert after_two["tier"] == "TIER_C", "26 falls below the TIER_B floor of 30"
    assert after_two["relationship_score_rolling_24m"] == 0
    assert same_instant(after_two["last_touch_at"], "2026-08-01T00:00:00Z"), (
        "the planner was touched by lead creation and qualification at the pinned clock"
    )

    in_tier_c, _ = validate_paginated(
        api_client.list_meeting_planners(ADMIN, params={"tier": "TIER_C"})
    )
    assert planner_id in [row["id"] for row in in_tier_c]
    in_tier_b, _ = validate_paginated(
        api_client.list_meeting_planners(ADMIN, params={"tier": "TIER_B"})
    )
    assert planner_id not in [row["id"] for row in in_tier_b]


# --- board report windows ----------------------------------------------------

# Two definite conventions for the same planner against the same fund.  Their
# occupied nights (April vs June 2028) are disjoint, so the properties never
# contend for the same room and the two hold windows never buffer-conflict on
# the shared hall -- the only thing that separates the two chains for reporting
# purposes is the logical clock they were driven at.
SECOND_CHAIN_OPPORTUNITY = {
    "event_name": "CDA Summer Congress 2028",
    "arrival_date": "2028-06-10",
    "departure_date": "2028-06-12",
}
SECOND_CHAIN_HOLD = {
    "move_in_start": "2028-06-08T00:00:00Z",
    "move_out_end": "2028-06-13T00:00:00Z",
}


def _second_definite_chain(scenario, clock, response_due_at,
                           incentive_request_amount=12_000.00):
    """Drive a second lead of the SAME planner to DEFINITE, entirely at ``clock``."""
    set_clock(clock)
    opportunity = create_lead(
        scenario["planner_id"],
        **dict(CANONICAL_OPPORTUNITY, **SECOND_CHAIN_OPPORTUNITY),
    )
    opportunity_id = opportunity["id"]
    qualify_lead(opportunity_id)
    place_hold(opportunity_id, scenario["hall_id"], **SECOND_CHAIN_HOLD)
    for (hotel_index, rooms, rate, cutoff_days) in DEFAULT_ALLOCATIONS:
        add_committed_block(
            opportunity_id, scenario["hotels"][hotel_index]["id"], rooms, rate, cutoff_days
        )
    bid = open_bid(opportunity_id)
    attach_letters(bid["id"])
    ask_for_incentive(bid["id"], incentive_request_amount)
    decision = decide_incentive(
        bid["id"], scenario["fund_id"], "APPROVED", incentive_request_amount
    )
    submit_bid(bid["id"], response_due_at)
    answer_bid(bid["id"], scenario["planner_id"], "ACCEPTED")
    return {"opportunity_id": opportunity_id, "decision": decision}


def test_board_report_window_is_half_open_on_definite_at():
    """A convention whose `definite_at` equals `period_start` is counted while one whose
    `definite_at` equals the exclusive `period_end` is not, and the complementary window
    picks up exactly the convention the first window shut out.

    PRD: "The window is half-open and interpreted at midnight UTC on each boundary: a row counts when its governing instant falls at or after `period_start` at `00:00:00.000Z` and strictly before `period_end` at `00:00:00.000Z`." (PRD S3.9)
    PRD: "Room-night production is keyed on `definite_at`: `definite_opportunity_count` is the number of opportunities in `sales_stage` `DEFINITE` or `SERVICED` whose `definite_at` falls in the window, and `definite_room_nights` is the sum of `definite_room_nights` over that same set." (PRD S3.9)

    Design: Corner/calculations/board_report_window_is_half_open_on_definite_at
    """
    january = setup_definite_lead(
        clock="2027-01-01T00:00:00Z", response_due_at="2027-02-01T00:00:00Z"
    )
    assert same_instant(january["opportunity"]["definite_at"], "2027-01-01T00:00:00Z")
    # committed_peak_rooms 900 * 2 event nights
    assert january["opportunity"]["definite_room_nights"] == 1800
    post_receipt(january["fund_id"], 20_000.00, "2027-01-01T00:00:00Z")

    july = _second_definite_chain(
        january, clock="2027-07-01T00:00:00Z", response_due_at="2027-08-01T00:00:00Z"
    )
    july_opportunity = read_opportunity(july["opportunity_id"])
    assert same_instant(july_opportunity["definite_at"], "2027-07-01T00:00:00Z")
    assert july_opportunity["definite_room_nights"] == 1800
    post_receipt(january["fund_id"], 30_000.00, "2027-07-01T00:00:00Z")

    # 12,000.00 gross under the 100,000.00 band boundary -> 0.05 fee -> 600.00
    for decision in (january["decision"], july["decision"]):
        assert_incentive_decision(decision)
        assert_money_equals(decision["admin_fee_amount"], 600.00, "admin_fee_amount")
        assert_money_equals(decision["total_charge_amount"], 12_600.00, "total_charge_amount")

    set_clock("2027-06-01T00:00:00Z")
    first = create_report("2027-01-01", "2027-07-01")
    assert_board_report(first)
    assert first["status"] == "DRAFT"
    assert first["definite_opportunity_count"] == 1, (
        "the July convention's definite_at equals the exclusive period_end"
    )
    assert first["definite_room_nights"] == 1800
    assert_money_equals(
        first["incentive_spend_committed_amount"], 12_600.00,
        "incentive_spend_committed_amount",
    )
    assert_money_equals(
        first["lodging_tax_recognized_amount"], 20_000.00, "lodging_tax_recognized_amount"
    )
    assert_money_equals(first["attrition_recovered_amount"], 0.00, "attrition_recovered_amount")
    # 12,600.00 / 1,800 room nights
    assert_money_equals(
        first["cost_per_definite_room_night"], 7.00, "cost_per_definite_room_night"
    )
    assert first["lost_opportunity_count"] == 0
    assert first["lost_room_nights_by_reason"] == {}

    set_clock("2027-09-01T00:00:00Z")
    second = create_report("2027-07-01", "2028-01-01")
    assert_board_report(second)
    assert second["definite_opportunity_count"] == 1, (
        "the inclusive lower bound admits the convention the first window excluded"
    )
    assert second["definite_room_nights"] == 1800
    assert_money_equals(
        second["incentive_spend_committed_amount"], 12_600.00,
        "incentive_spend_committed_amount",
    )
    assert_money_equals(
        second["lodging_tax_recognized_amount"], 30_000.00, "lodging_tax_recognized_amount"
    )
    assert_money_equals(
        second["cost_per_definite_room_night"], 7.00, "cost_per_definite_room_night"
    )


def test_board_report_cost_per_night_is_null_not_zero_on_an_empty_window():
    """A report over a window that produced nothing still succeeds, and its headline
    efficiency figure is reported as null rather than as 0.00, with the by-reason lost
    map an empty object rather than a map of zeroes.

    PRD: "And the headline efficiency figure, `cost_per_definite_room_night`, is `incentive_spend_committed_amount` divided by `definite_room_nights`, rounded half-up to two decimals -- except when `definite_room_nights` is 0, in which case it is reported as null rather than as 0.00." (PRD S3.9)
    PRD: "`lost_room_nights_by_reason` is a map from each `lost_reason` to the summed `total_room_nights_requested` of the in-window lost opportunities carrying that reason, with any reason whose total would be zero omitted from the map entirely rather than reported as 0." (PRD S3.9)

    Design: Corner/calculations/board_report_cost_per_night_is_null_not_zero_on_an_empty_window
    """
    set_clock("2026-04-01T00:00:00Z")

    response = api_client.create_board_report(
        create_board_report_payload("2026-01-01", "2026-07-01"), ANALYST
    )
    report = validate_success(response, expected_status=201)
    assert_board_report(report)

    assert report["status"] == "DRAFT"
    assert report["period_start"] == "2026-01-01"
    assert report["period_end"] == "2026-07-01"
    assert report["definite_opportunity_count"] == 0
    assert report["definite_room_nights"] == 0
    assert report["cost_per_definite_room_night"] is None, (
        "a zero room-night denominator yields null, never 0.00, and never a 500"
    )
    assert report["lost_opportunity_count"] == 0
    assert report["lost_room_nights_by_reason"] == {}
    assert_money_equals(
        report["incentive_spend_committed_amount"], 0.00, "incentive_spend_committed_amount"
    )
    assert_money_equals(
        report["lodging_tax_recognized_amount"], 0.00, "lodging_tax_recognized_amount"
    )
    assert_money_equals(report["attrition_recovered_amount"], 0.00, "attrition_recovered_amount")


LOST_LEAD_SPECS = (
    ("CDA Spring Forum 2028", "2028-04-10", "2028-04-12", 1800, "RATE_TOO_HIGH"),
    ("CDA Regional Clinic 2028", "2028-05-10", "2028-05-12", 400, "RATE_TOO_HIGH"),
    ("CDA Summer Congress 2028", "2028-06-10", "2028-06-12", 600, "DATES_UNAVAILABLE"),
)


def test_board_report_buckets_lost_room_nights_by_reason():
    """Lost business is bucketed by `lost_reason` and summed on requested room nights, so
    two leads lost for the same reason collapse into one entry, and reasons with no
    in-window losses are absent from the map rather than present with a zero.

    PRD: "Lost business is keyed on `updated_at`: `lost_opportunity_count` is the number of opportunities in `sales_stage` `LOST` whose `updated_at` falls in the window, and `lost_room_nights_by_reason` is a map from each `lost_reason` to the summed `total_room_nights_requested` of the in-window lost opportunities carrying that reason, with any reason whose total would be zero omitted from the map entirely rather than reported as 0." (PRD S3.9)

    Design: Corner/calculations/board_report_buckets_lost_room_nights_by_reason
    """
    scenario = setup_inventory(clock="2026-08-01T00:00:00Z")
    for (event_name, arrival, departure, room_nights, reason) in LOST_LEAD_SPECS:
        lead = create_lead(
            scenario["planner_id"],
            **dict(
                CANONICAL_OPPORTUNITY,
                event_name=event_name,
                arrival_date=arrival,
                departure_date=departure,
                total_room_nights_requested=room_nights,
            ),
        )
        qualify_lead(lead["id"])
        lost = lose_lead(lead["id"], reason)
        assert_opportunity(lost)
        assert lost["sales_stage"] == "LOST"
        assert lost["lost_reason"] == reason

    report = create_report("2026-08-01", "2026-09-01")
    assert_board_report(report)
    assert report["lost_opportunity_count"] == 3
    # 1800 + 400 collapse into one RATE_TOO_HIGH bucket; the other five declared
    # reasons produced nothing and are therefore absent, not present as 0.
    assert report["lost_room_nights_by_reason"] == {
        "RATE_TOO_HIGH": 2200,
        "DATES_UNAVAILABLE": 600,
    }, f"unexpected by-reason breakdown {report['lost_room_nights_by_reason']!r}"
    assert report["definite_opportunity_count"] == 0
    assert report["definite_room_nights"] == 0
    assert report["cost_per_definite_room_night"] is None

    set_clock("2026-09-15T00:00:00Z")
    later = create_report("2026-09-01", "2026-10-01")
    assert later["lost_opportunity_count"] == 0
    assert later["lost_room_nights_by_reason"] == {}, (
        "the losses were stamped in August and must not leak into the September window"
    )
