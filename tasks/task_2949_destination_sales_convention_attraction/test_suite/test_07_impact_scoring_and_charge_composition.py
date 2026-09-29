"""Dual-variant valuations, relationship scoring and the pinned money order.

Queue A (difficulty index) translations for the ``dual_variant_calc`` and
``combinatorial_formula`` rules: the two economic-impact variants of one lead,
the two relationship-score scopes of one planner, the four-step incentive cap,
the per-commitment attrition rounding order and the gross-only fee band.
"""
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_economic_impact_estimate,
    assert_fund_conservation_identity,
    assert_incentive_decision,
    assert_money_equals,
    assert_pickup_record,
)
from test_helpers.types import (
    BidPackageStatus,
    EstimateVariant,
    PlannerTier,
    SalesStage,
)


# --- dual_variant_calc -------------------------------------------------------

def test_final_estimate_values_only_the_room_nights_actually_picked_up(api):
    """FINAL prices observed pickup at the rates actually charged.

    PRD: "Its `room_nights_basis` is the sum of `rooms_picked_up` across the
    eligible pickup records" and "its `lodging_spend_amount` is not the basis
    times a single rate but the sum, over those same eligible pickup records,
    of each record's `rooms_picked_up` multiplied by its own
    `rate_charged_amount` rounded to two decimals -- a per-night rounded
    product, then summed" (PRD 3.6).
    PRD: "the actual room nights are multiplied by an occupancy factor of 1.6
    persons per room and rounded half-up to a whole number of delegate
    person-nights, and `delegate_spend_amount` is that whole number multiplied
    by the same 285.00 dollars per person per day" (PRD 3.6).

    Design: Difficulty/dual_variant_calc/impact_provisional_vs_final_diverge_for_same_opportunity
    """
    scenario = fx.setup_definite_lead_with_pickup()

    final = fx.compute_estimate(scenario["opportunity_id"], EstimateVariant.FINAL.value)

    assert_economic_impact_estimate(final)
    assert final["variant"] == EstimateVariant.FINAL.value
    # 400 + 250 + 180 + 150 + 10 rooms picked up across the two event nights.
    assert final["room_nights_basis"] == 990
    # 85732.00 + 53582.50 + 37758.60 + 31465.50 + 1995.10
    assert_money_equals(final["lodging_spend_amount"], 210533.70, "FINAL lodging_spend_amount")
    # 990 * 1.6 = 1584 person-nights * 285.00
    assert_money_equals(final["delegate_spend_amount"], 451440.00, "FINAL delegate_spend_amount")
    # min(250000 confirmed hall sqft, 200000 requested) * 4.75
    assert_money_equals(final["exhibitor_spend_amount"], 950000.00, "FINAL exhibitor_spend_amount")
    assert_money_equals(final["direct_spend_amount"], 1611973.70, "FINAL direct_spend_amount")
    # 1611973.70 * 1.65 = 2659756.605 -> half-up
    assert_money_equals(final["total_impact_amount"], 2659756.61, "FINAL total_impact_amount")
    # 210533.70 * 0.15 = 31580.055 -> half-up
    assert_money_equals(final["lodging_tax_yield_amount"], 31580.06, "FINAL lodging_tax_yield_amount")


def test_provisional_and_final_estimates_of_one_lead_diverge(api):
    """The same lead yields two different valuations, claim versus observation.

    PRD: "Its `room_nights_basis` is the lead's `total_room_nights_requested`.
    Its `lodging_spend_amount` is that basis multiplied by the lead's
    `rate_ceiling_amount`, rounded to two decimals. Its
    `delegate_spend_amount` is the lead's `attendance_estimate` multiplied by
    `event_nights` and then by a delegate daily spend of 285.00 dollars per
    person per day" (PRD 3.6).
    PRD: "`total_impact_amount` is `direct_spend_amount` multiplied by an
    indirect-effects multiplier of 1.65 ... rounded half-up to two decimals"
    and "`lodging_tax_yield_amount` ... is `lodging_spend_amount` multiplied by
    the city's lodging tax rate of 0.15" (PRD 3.6).
    PRD: "Estimates of one lead are readable as a sub-collection, newest last,
    filterable by `variant`" (PRD 3.6).

    Design: Difficulty/dual_variant_calc/impact_provisional_vs_final_diverge_for_same_opportunity
    """
    scenario = fx.setup_definite_lead_with_pickup()
    opportunity_id = scenario["opportunity_id"]

    provisional = fx.list_estimates(opportunity_id, EstimateVariant.PROVISIONAL.value)[-1]
    final = fx.compute_estimate(opportunity_id, EstimateVariant.FINAL.value)

    # PROVISIONAL: 1800 * 219.00 lodging, 8000 delegates * 2 nights * 285.00,
    # 200000 sqft * 4.75 -> direct 5904200.00.
    assert provisional["room_nights_basis"] == 1800
    assert_money_equals(provisional["lodging_spend_amount"], 394200.00, "PROVISIONAL lodging")
    assert_money_equals(provisional["delegate_spend_amount"], 4560000.00, "PROVISIONAL delegate")
    assert_money_equals(provisional["exhibitor_spend_amount"], 950000.00, "PROVISIONAL exhibitor")
    assert_money_equals(provisional["direct_spend_amount"], 5904200.00, "PROVISIONAL direct")
    assert_money_equals(provisional["total_impact_amount"], 9741930.00, "PROVISIONAL total impact")
    assert_money_equals(provisional["lodging_tax_yield_amount"], 59130.00, "PROVISIONAL tax yield")

    # The two variants of one opportunity disagree by design.
    assert_money_equals(final["total_impact_amount"], 2659756.61, "FINAL total impact")
    assert final["total_impact_amount"] != provisional["total_impact_amount"]
    assert final["lodging_tax_yield_amount"] != provisional["lodging_tax_yield_amount"]

    # Both snapshots survive in the sub-collection, newest last.
    both = fx.list_estimates(opportunity_id)
    assert [row["variant"] for row in both][-1] == EstimateVariant.FINAL.value
    assert {row["id"] for row in both} >= {provisional["id"], final["id"]}


def test_migrated_counters_alone_earn_the_lifetime_score_and_tier(api):
    """At registration the legacy counters feed LIFETIME only, never ROLLING_24M.

    PRD: "every derived counter at zero ... except insofar as the migrated
    counters already feed the scores, and `tier` starts at `TIER_C` unless the
    migrated counters alone earn better" (PRD 3.1).
    PRD: "the raw score is twelve points for each definite convention in scope,
    plus one point for every full 500 room nights in scope with that room-night
    term capped at 40 points, minus five points for each lost lead in scope"
    (PRD 3.1).
    PRD: "In the `ROLLING_24M` scope ... the migrated legacy counters are
    excluded entirely" (PRD 3.1).

    Design: Difficulty/dual_variant_calc/planner_score_lifetime_vs_rolling_24m_diverge
    """
    fx.set_clock(fx.DEFAULT_CLOCK)
    planner = fx.register_planner(**fx.CANONICAL_PLANNER)

    # 12 * 2 legacy definites + floor(6000 / 500) = 24 + 12 = 36.
    assert planner["relationship_score_lifetime"] == 36
    assert planner["relationship_score_rolling_24m"] == 0
    assert planner["tier"] == PlannerTier.TIER_B.value
    # The derived counters themselves count live opportunities, of which there
    # are none yet; only the room-night total carries the migrated history.
    assert planner["definite_count"] == 0
    assert planner["lost_count"] == 0
    assert planner["lifetime_definite_room_nights"] == 6000


def test_lifetime_and_rolling_scores_diverge_on_the_same_stored_data(api):
    """One acceptance moves both scopes, to two different integers.

    PRD: "In the LIFETIME scope, stored in `relationship_score_lifetime`, the
    definite count is `legacy_definite_count` plus every opportunity of that
    planner in `DEFINITE` or `SERVICED` regardless of age; the room-night total
    is `legacy_definite_room_nights` plus the `definite_room_nights` of that
    same set" (PRD 3.1).
    PRD: "In the `ROLLING_24M` scope ... the migrated legacy counters are
    excluded entirely, only opportunities whose `definite_at` falls at or after
    the instant 730 days (two years) before the current logical clock are
    counted as definite" (PRD 3.1).
    PRD: "its `definite_room_nights` is frozen at `committed_peak_rooms`
    multiplied by `event_nights`" (PRD 3.8).
    PRD: "`definite_count` is the number of that planner's opportunities
    currently in `sales_stage` `DEFINITE` or `SERVICED`" (PRD 3.1).

    Design: Difficulty/dual_variant_calc/planner_score_lifetime_vs_rolling_24m_diverge
    """
    scenario = fx.setup_definite_lead()
    opportunity = scenario["opportunity"]
    planner = fx.read_planner(scenario["planner_id"])

    assert opportunity["sales_stage"] == SalesStage.DEFINITE.value
    # 900 committed peak rooms over 2 event nights.
    assert opportunity["definite_room_nights"] == 1800

    # LIFETIME: 12 * (2 legacy + 1) + floor((6000 + 1800) / 500) = 36 + 15.
    assert planner["lifetime_definite_room_nights"] == 7800
    assert planner["relationship_score_lifetime"] == 51
    # ROLLING_24M: legacy excluded, so 12 * 1 + floor(1800 / 500) = 12 + 3.
    assert planner["relationship_score_rolling_24m"] == 15
    assert planner["relationship_score_lifetime"] != planner["relationship_score_rolling_24m"]
    # Only the LIFETIME variant derives the tier: 51 >= 30.
    assert planner["tier"] == PlannerTier.TIER_B.value
    # The live-row counter sees exactly the one definite opportunity.
    assert planner["definite_count"] == 1


# --- combinatorial_formula ---------------------------------------------------

def test_incentive_cap_nests_band_ladder_yield_ceiling_and_coverage_factor(api):
    """All four cap steps compose in the pinned order onto 13304.25.

    PRD: "a marginal band ladder is walked over the lead's
    `total_room_nights_requested`: the first 5,000 requested room nights are
    worth 12.00 dollars each" (PRD 3.7).
    PRD: "a lodging-tax yield ceiling is computed from the newest `PROVISIONAL`
    estimate's `lodging_tax_yield_amount` multiplied by a rate keyed on the
    planner's `tier`: 0.35 for `TIER_A`, 0.25 for `TIER_B` and 0.15 for
    `TIER_C`, rounded half-up to two decimals" (PRD 3.7).
    PRD: "the smaller of those two ceilings is taken and multiplied by a
    coverage factor drawn from the lead's current `block_coverage_pct`: the
    factor is 1.00 when coverage is at least 95.00 percent, 0.90 when coverage
    is at least 85.00 percent but below 95.00, and 0.75 otherwise" (PRD 3.7).
    PRD: "That final clamp is skipped when the cap is computed at request time,
    because no fund has been named yet" (PRD 3.7).

    Design: Difficulty/combinatorial_formula/incentive_cap_nests_band_ladder_yield_ceiling_and_coverage_factor
    """
    scenario = fx.setup_bid_incentive_pending(incentive_request_amount=12_000.00)
    bid = scenario["bid"]
    planner = fx.read_planner(scenario["planner_id"])

    assert planner["tier"] == PlannerTier.TIER_B.value
    assert_money_equals(scenario["opportunity"]["block_coverage_pct"], 90.00, "block_coverage_pct")
    assert bid["status"] == BidPackageStatus.INCENTIVE_PENDING.value

    # Band ceiling 1800 * 12.00 = 21600.00; yield ceiling 59130.00 * 0.25 =
    # 14782.50; min * 0.90 coverage factor = 13304.25; no fund clamp yet.
    assert_money_equals(bid["incentive_cap_amount"], 13304.25, "incentive_cap_amount")
    provisional = fx.list_estimates(
        scenario["opportunity_id"], EstimateVariant.PROVISIONAL.value
    )
    assert len(provisional) == 1
    assert_money_equals(
        provisional[-1]["lodging_tax_yield_amount"], 59130.00, "auto PROVISIONAL tax yield"
    )


def test_a_request_above_the_cap_is_stored_without_enforcement(api):
    """The ceiling is computed but deliberately not enforced at request time.

    PRD: "The cap is deliberately **not** enforced at this point -- a sales
    manager may ask for more than the ceiling allows, and the request will reach
    the approver and be refused there" (PRD 3.7).
    PRD: "Both are stored, `incentive_requested_by_user_id` is set to the acting
    `X-User-ID`, and the package moves from `DRAFT` to `INCENTIVE_PENDING`"
    (PRD 3.7).

    Design: Difficulty/combinatorial_formula/incentive_cap_nests_band_ladder_yield_ceiling_and_coverage_factor
    """
    scenario = fx.setup_bid_incentive_pending(incentive_request_amount=20_000.00)
    bid = scenario["bid"]

    assert bid["status"] == BidPackageStatus.INCENTIVE_PENDING.value
    assert_money_equals(bid["incentive_request_amount"], 20_000.00, "incentive_request_amount")
    # The cap is derived from the lead and the estimate, never from the ask.
    assert_money_equals(bid["incentive_cap_amount"], 13304.25, "incentive_cap_amount")
    assert bid["incentive_request_amount"] > bid["incentive_cap_amount"]


def test_attrition_damages_are_rounded_per_commitment_before_summation(api):
    """Three half-cent damages round up individually, then add to 70156.14.

    PRD: "that commitment's `attrition_damages_amount` is the shortfall nights
    multiplied by the commitment's `rate_offered_amount` and then by a damage
    rate of 0.75 ... rounded half-up to two decimals" (PRD 3.9).
    PRD: "The rounding order is pinned: each commitment's damages are rounded to
    two decimals **first**, and the rounded per-commitment figures are then added
    together ... Summing raw products and rounding once at the end is wrong and
    can differ by cents" (PRD 3.9).
    PRD: "the allowance is 80 percent of its `committed_room_nights`, taking the
    floor to a whole number of nights; the shortfall, exposed as
    `attrition_shortfall_nights`, is that allowance less the commitment's
    `picked_up_room_nights`" (PRD 3.9).

    Design: Difficulty/combinatorial_formula/attrition_damages_rounded_per_commitment_then_summed
    """
    scenario = fx.setup_block_assembled()
    fx.report_pickups(scenario, fx.DEFAULT_PICKUPS[:4])
    cityline = scenario["commitments"][2]
    fx.file_pickup(cityline["id"], cityline["hotel_id"], "2028-04-10", 10, 199.51)

    harborview = fx.read_commitment(scenario["commitments"][0]["id"])
    bayside = fx.read_commitment(scenario["commitments"][1]["id"])
    cityline = fx.read_commitment(cityline["id"])
    opportunity = fx.read_opportunity(scenario["opportunity_id"])

    # allowance floor(0.8 * 1000) = 800 against 650 picked up.
    assert harborview["attrition_shortfall_nights"] == 150
    assert bayside["attrition_shortfall_nights"] == 150
    assert cityline["attrition_shortfall_nights"] == 150
    # 150 * 214.33 * 0.75 = 24112.125 -> 24112.13
    assert_money_equals(harborview["attrition_damages_amount"], 24112.13, "Harborview damages")
    # 150 * 209.77 * 0.75 = 23599.125 -> 23599.13
    assert_money_equals(bayside["attrition_damages_amount"], 23599.13, "Bayside damages")
    # 150 * 199.51 * 0.75 = 22444.875 -> 22444.88
    assert_money_equals(cityline["attrition_damages_amount"], 22444.88, "Cityline damages")

    settlement = opportunity["attrition_settlement_amount"]
    assert_money_equals(settlement, 70156.14, "attrition_settlement_amount")
    # Summing the raw products and rounding once would have produced 70156.13.
    assert abs(float(settlement) - 70156.13) > 0.005, (
        f"attrition_settlement_amount {settlement} was rounded after summation"
    )


def test_pickup_revenue_is_rounded_on_its_own_nightly_product(api):
    """Each nightly pickup row carries its own rounded revenue figure.

    PRD: "The server derives `room_night_revenue_amount` as `rooms_picked_up`
    multiplied by `rate_charged_amount`, rounded half-up to two decimals, then
    raises the commitment's `picked_up_room_nights` and the property's
    `pickup_room_nights` by the rooms reported, and recomputes the commitment's
    `attrition_shortfall_nights` and `attrition_damages_amount`" (PRD 3.5).

    Design: Difficulty/combinatorial_formula/attrition_damages_rounded_per_commitment_then_summed
    """
    scenario = fx.setup_block_assembled()
    fx.set_clock("2028-04-13T00:00:00Z")
    cityline = scenario["commitments"][2]

    record = fx.file_pickup(cityline["id"], cityline["hotel_id"], "2028-04-10", 10, 199.51)

    assert_pickup_record(record)
    assert_money_equals(record["room_night_revenue_amount"], 1995.10, "room_night_revenue_amount")
    commitment = fx.read_commitment(cityline["id"])
    assert commitment["picked_up_room_nights"] == 10
    # Only this property has reported, so only its damages are assessed:
    # floor(0.8 * 200) - 10 = 150 shortfall nights.
    assert commitment["attrition_shortfall_nights"] == 150
    assert_money_equals(commitment["attrition_damages_amount"], 22444.88, "Cityline damages")
    assert_money_equals(
        fx.read_opportunity(scenario["opportunity_id"])["attrition_settlement_amount"],
        22444.88,
        "attrition_settlement_amount",
    )


GME_2028 = {
    "event_name": "Global Manufacturing Expo 2028",
    "arrival_date": "2028-06-05",
    "departure_date": "2028-06-07",
    "peak_rooms_requested": 10_000,
    "total_room_nights_requested": 20_000,
    "attendance_estimate": 20_000,
    "exhibit_sqft_requested": 200_000,
    "rate_ceiling_amount": 219.00,
}


def _pending_bid_on_an_uncovered_lead(request_amount: float) -> dict:
    """A 20,000-room-night lead with nothing committed, awaiting a decision."""
    scenario = fx.setup_lead(opportunity_overrides=dict(GME_2028))
    bid = fx.open_bid(scenario["opportunity_id"])
    fx.ask_for_incentive(bid["id"], request_amount)
    scenario["bid_id"] = bid["id"]
    return scenario


def test_admin_fee_band_is_selected_on_the_gross_not_on_the_total_charge(api):
    """A 96000.00 gross keeps the 5% band even though the total clears 100000.00.

    PRD: "Select the administrative fee rate from **that gross figure only**:
    0.05 when the gross is below 100,000.00, 0.04 when the gross is at or above
    100,000.00 but below 250,000.00, and 0.03 when the gross is at or above
    250,000.00" (PRD 3.7).
    PRD: "The fee band is never re-derived from `total_charge_amount`, even when
    adding the fee pushes the total across a band boundary: a gross of
    96,000.00 attracts a fee of 4,800.00 for a total of 100,800.00, and the fee
    stays 4,800.00 -- it is emphatically not recomputed as 3,840.00" (PRD 3.7).
    PRD: "`tax_payback_ratio` is the newest `PROVISIONAL` estimate's
    `lodging_tax_yield_amount` divided by `total_charge_amount`, rounded half-up
    to two decimals" (PRD 3.7).

    Design: Difficulty/combinatorial_formula/admin_fee_band_selected_on_gross_not_on_total_charge
    """
    scenario = _pending_bid_on_an_uncovered_lead(96_000.00)

    decision = fx.decide_incentive(
        scenario["bid_id"], scenario["fund_id"], "APPROVED", 96_000.00,
        rationale="Large exhibit programme with a healthy projected tax payback",
    )

    assert_incentive_decision(decision)
    assert_money_equals(decision["admin_fee_amount"], 4800.00, "admin_fee_amount")
    assert_money_equals(decision["total_charge_amount"], 100800.00, "total_charge_amount")
    assert abs(float(decision["admin_fee_amount"]) - 3840.00) > 0.005, (
        "admin_fee_amount was re-derived from the total charge"
    )
    assert abs(float(decision["total_charge_amount"]) - 99840.00) > 0.005, (
        "total_charge_amount was built from a re-derived fee band"
    )
    # 657000.00 / 100800.00 = 6.5178... -> 6.52
    assert_money_equals(decision["tax_payback_ratio"], 6.52, "tax_payback_ratio")

    bid = fx.read_bid(scenario["bid_id"])
    assert bid["status"] == BidPackageStatus.APPROVED.value
    assert_money_equals(bid["total_fund_charge_amount"], 100800.00, "total_fund_charge_amount")


def test_incentive_cap_walks_all_three_marginal_bands_before_the_fund_clamp(api):
    """20,000 requested room nights cross both ladder edges, yielding 123187.50.

    PRD: "the first 5,000 requested room nights are worth 12.00 dollars each,
    the next 10,000 room nights -- those from the 5,001st through the 15,000th --
    are worth 8.00 dollars each, and every room night beyond the 15,000th is
    worth 5.00 dollars, with the three band contributions added and the total
    rounded half-up to two decimals to give the band ceiling" (PRD 3.7).
    PRD: "the factor is 1.00 when coverage is at least 95.00 percent, 0.90 when
    coverage is at least 85.00 percent but below 95.00, and 0.75 otherwise"
    (PRD 3.7).
    PRD: "`committed_amount` rises by `total_charge_amount`,
    `uncommitted_amount` falls by the same amount" (PRD 3.7).

    Design: Difficulty/combinatorial_formula/admin_fee_band_selected_on_gross_not_on_total_charge
    """
    scenario = _pending_bid_on_an_uncovered_lead(96_000.00)

    bid = fx.read_bid(scenario["bid_id"])
    # Band ceiling 5000*12 + 10000*8 + 5000*5 = 165000.00; yield ceiling
    # 657000.00 * 0.25 = 164250.00; nothing committed so the coverage factor is
    # 0.75 -> 123187.50.
    assert_money_equals(scenario["opportunity"]["block_coverage_pct"], 0.00, "block_coverage_pct")
    assert_money_equals(bid["incentive_cap_amount"], 123187.50, "incentive_cap_amount")

    fx.decide_incentive(
        scenario["bid_id"], scenario["fund_id"], "APPROVED", 96_000.00,
        rationale="Large exhibit programme with a healthy projected tax payback",
    )

    fund = fx.read_fund(scenario["fund_id"])
    assert_money_equals(fund["committed_amount"], 100800.00, "fund committed_amount")
    assert_money_equals(fund["uncommitted_amount"], 399200.00, "fund uncommitted_amount")
    assert_fund_conservation_identity(fund)
