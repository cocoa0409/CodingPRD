"""Composed formulas: nested clamps, pinned rounding order and weighted sums.

Each test drives one multi-factor computation end to end and pins the exact
figure the program's own composition order produces.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_money,
    assert_obligation_identity,
    assert_one_decimal,
    assert_ratio,
)
from test_helpers.constants import (
    AGREEMENT_HOLD_IN,
    DEFAULT_CLOCK,
    EVAL_NOT_SELECTED,
    EVAL_SELECTED,
    PAYMENT_BASIS_SCHEDULED_FLIGHT_FLAT,
    RENEG_REQUESTED,
    RENEG_WITHDRAW,
    SERVICE_LEVEL_ENHANCED,
)
from test_helpers.test_users import ADMIN, OFFICER

NINETY_SEVEN = {
    "scheduled_departures": 97,
    "completed_departures": 90,
    "cancelled_carrier_departures": 3,
    "cancelled_weather_departures": 4,
    "seats_offered": 1700,
    "passengers_enplaned": 600,
}


def _award_past_cooling_off(api):
    """An ACTIVE 1,600,000.00 agreement with the clock past its cooling-off point."""
    award = fx.build_award(api, clock=DEFAULT_CLOCK)
    fx.publish_fuel_index(api, "2027-02", 3.1000)
    fx.publish_fuel_index(api, "2027-03", 1.0000)
    fx.set_clock(api, "2027-02-01T00:00:00Z")
    return award


def test_rising_fuel_index_passes_through_four_fifths_of_the_swing(api):
    """A fuel swing of 0.7000 per gallon justifies 80 percent of its annual cost.

    "`fuel_cost_delta_usd` is that per-gallon movement multiplied by the annual gallons, rounded half-up to cents, and `justified_delta_usd` is 80 percent of that annual fuel cost change, again rounded half-up to cents — the program passes through four fifths of a fuel swing, not all of it."

    Design: Difficulty/combinatorial_formula/fuel_passthrough_nested_cap_then_floor
    """
    award = _award_past_cooling_off(api)
    agreement = validate_success(api.get_service_agreement(award.agreement_id, ADMIN))
    assert_one_decimal(agreement["annual_block_hours"], 1872.0, "annual_block_hours")
    assert_ratio(
        agreement["baseline_fuel_index_usd"], 2.4000, "baseline_fuel_index_usd"
    )

    renegotiation = fx.file_fuel_renegotiation(api, award, "2027-02", 1750000.00)

    assert renegotiation["status"] == RENEG_REQUESTED
    assert renegotiation["revision_count"] == 0
    assert_ratio(
        renegotiation["current_fuel_index_usd"], 3.1000, "current_fuel_index_usd"
    )
    assert_money(renegotiation["fuel_cost_delta_usd"], 89107.20, "fuel_cost_delta_usd")
    assert_money(renegotiation["justified_delta_usd"], 71285.76, "justified_delta_usd")
    assert_money(
        renegotiation["ceiling_annual_subsidy_usd"],
        1671285.76,
        "ceiling_annual_subsidy_usd",
    )


def test_collapsing_fuel_index_is_clipped_by_the_five_percent_floor(api):
    """A justified cut of 142,571.52 is floored at five percent of the rate in force.

    "The floor is 5 percent of the rate in force taken negatively, also rounded half-up to cents: the result is replaced by whichever of the two is larger, so no renegotiation can cut a rate by more than five percent."

    Design: Difficulty/combinatorial_formula/fuel_passthrough_nested_cap_then_floor
    """
    award = _award_past_cooling_off(api)
    rising = fx.file_fuel_renegotiation(api, award, "2027-02", 1750000.00)
    validate_success(
        api.renegotiation_action(
            rising["id"],
            f.renegotiation_action_payload(
                RENEG_WITHDRAW, action_note="Refiling on the March index."
            ),
            award.carrier_headers,
        )
    )

    renegotiation = fx.file_fuel_renegotiation(api, award, "2027-03", 1560000.00)

    assert_ratio(
        renegotiation["current_fuel_index_usd"], 1.0000, "current_fuel_index_usd"
    )
    assert_money(renegotiation["fuel_cost_delta_usd"], -178214.40, "fuel_cost_delta_usd")
    assert_money(renegotiation["justified_delta_usd"], -142571.52, "justified_delta_usd")
    assert_money(
        renegotiation["ceiling_annual_subsidy_usd"],
        1520000.00,
        "ceiling_annual_subsidy_usd",
    )


def test_gross_subsidy_multiplies_the_cents_rounded_per_departure_rate(api):
    """A 97-departure month grosses 129,209.58, not the 129,209.62 of a late round.

    "Four such pinned orders exist and each is restated where it is used: the per-departure subsidy rate is rounded to cents *before* it multiplies any departure count; each of the three selection-score components is rounded to four decimals *before* the weighted sum is taken and the sum is then rounded again; the normalised load factor inside a quality score is *not* pre-rounded and the weighted sum is rounded exactly once at the end; and the pro-rated delta applied to an agreement's committed total on a rate acceptance is rounded to cents before it is added to that total, which is then rounded again."

    Design: Difficulty/combinatorial_formula/per_departure_rate_rounded_before_multiplication
    """
    award = fx.build_award(api, clock=DEFAULT_CLOCK)
    period = fx.reported_period(
        api, award.agreement_id, award.carrier_id, "2026-08", **NINETY_SEVEN
    )
    assert_ratio(
        period["period_completion_factor"], 0.9278, "period_completion_factor"
    )

    validate_success(
        api.certify_service_period(period["id"], f.certify_payload(), ADMIN)
    )
    payment = fx.payment_for_period(api, period["id"])

    assert_money(payment["monthly_entitlement_usd"], 133333.33, "monthly_entitlement_usd")
    assert_money(payment["per_departure_rate_usd"], 1374.57, "per_departure_rate_usd")
    assert payment["credited_departures"] == 94
    assert_money(payment["gross_subsidy_usd"], 129209.58, "gross_subsidy_usd")
    assert_money(
        payment["cancellation_adjustment_usd"], 1374.57, "cancellation_adjustment_usd"
    )
    assert_money(payment["withholding_pct"], 0.02, "withholding_pct")
    assert_money(
        payment["performance_withholding_usd"], 2556.70, "performance_withholding_usd"
    )
    assert_money(payment["net_payment_usd"], 125278.31, "net_payment_usd")


def test_preview_of_the_same_month_uses_the_identical_rounded_rate(api):
    """The preview of the 97-departure month resolves the same cents-rounded rate.

    "The per-departure rate is rounded to cents *before* it multiplies anything; summing first and rounding last would differ by cents and is not what this program pays."

    Design: Difficulty/combinatorial_formula/per_departure_rate_rounded_before_multiplication
    """
    award = fx.build_award(api, clock=DEFAULT_CLOCK)
    period = fx.reported_period(
        api, award.agreement_id, award.carrier_id, "2026-08", **NINETY_SEVEN
    )

    preview = validate_success(api.get_payment_preview(period["id"], ADMIN))

    assert_money(preview["per_departure_rate_usd"], 1374.57, "per_departure_rate_usd")
    assert preview["credited_departures"] == 94
    assert_money(
        preview["completed_flight_proration_net_usd"],
        125278.31,
        "completed_flight_proration_net_usd",
    )


def test_hold_in_premium_uses_the_band_of_the_pre_premium_net(api):
    """A pre-premium net of 115,096.03 earns the 0.05 band, not the 0.03 band.

    "When the agreement's `status` is `HOLD_IN` at certification, the program takes `net_payment_usd` as the base: a base of 120,000.00 dollars or more earns a premium rate of 0.03, a base of at least 100,000.00 dollars but under 120,000.00 earns 0.05, and a base below 100,000.00 earns 0.08."

    Design: Difficulty/combinatorial_formula/hold_in_premium_tier_keyed_on_pre_premium_net
    """
    award = fx.build_award(api, clock=DEFAULT_CLOCK)
    period = fx.reported_period(api, award.agreement_id, award.carrier_id, "2026-08")
    hold_in = fx.build_hold_in(api, award)
    assert hold_in["agreement"]["status"] == AGREEMENT_HOLD_IN

    validate_success(
        api.certify_service_period(period["id"], f.certify_payload(), ADMIN)
    )
    payment = fx.payment_for_period(api, period["id"])

    assert_money(payment["net_payment_usd"], 115096.03, "net_payment_usd")
    assert_money(payment["hold_in_premium_usd"], 5754.80, "hold_in_premium_usd")
    assert_money(payment["total_disbursement_usd"], 120850.83, "total_disbursement_usd")


def test_disbursed_hold_in_premium_stays_outside_the_obligation_identity(api):
    """The premium accumulates on its own field and never moves the obligation.

    "`hold_in_premium_paid_usd`, which accumulates the premiums paid while an agreement is in hold-in status, is deliberately outside that identity: hold-in premiums are extra cash that never disturbs the committed-obligation arithmetic."

    Design: Difficulty/combinatorial_formula/hold_in_premium_tier_keyed_on_pre_premium_net
    """
    award = fx.build_award(api, clock=DEFAULT_CLOCK)
    period = fx.reported_period(api, award.agreement_id, award.carrier_id, "2026-08")
    fx.build_hold_in(api, award)
    validate_success(
        api.certify_service_period(period["id"], f.certify_payload(), ADMIN)
    )
    payment = fx.payment_for_period(api, period["id"])
    fx.approve_payment(api, payment["id"])
    fx.disburse_payment(api, payment["id"])

    agreement = validate_success(api.get_service_agreement(award.agreement_id, ADMIN))

    assert_money(
        agreement["hold_in_premium_paid_usd"], 5754.80, "hold_in_premium_paid_usd"
    )
    assert_money(agreement["disbursed_to_date_usd"], 115096.03, "disbursed_to_date_usd")
    assert_money(
        agreement["obligated_remaining_usd"], 3084903.97, "obligated_remaining_usd"
    )
    assert_money(agreement["total_committed_usd"], 3200000.00, "total_committed_usd")
    assert_obligation_identity(agreement)


def _two_candidate_round(api):
    """Two submitted proposals on one closed solicitation, on different equipment."""
    ref = fx.make_reference_data(api, clock=DEFAULT_CLOCK)
    saab = validate_success(
        api.create_aircraft_type(f.larger_aircraft_type_payload(), ADMIN), 201
    )
    solicitation = fx.open_solicitation(api, ref.community_id)
    cheap_frequency = fx.submitted_proposal(
        api, solicitation["id"], ref.carrier_id, ref.aircraft_type_id
    )
    big_bid = fx.submitted_proposal(
        api,
        solicitation["id"],
        ref.second_carrier_id,
        saab["id"],
        service_level=SERVICE_LEVEL_ENHANCED,
        weekly_round_trips=14,
        seats_per_departure=30,
        annual_subsidy_request_usd=2900000.00,
        payment_basis=PAYMENT_BASIS_SCHEDULED_FLIGHT_FLAT,
    )
    solicitation = fx.close_solicitation(api, solicitation["id"])
    return ref, solicitation, cheap_frequency, big_bid


def test_service_clamp_erases_the_frequency_edge_when_no_preference_is_filed(api):
    """With no filing both candidates take 0.0000 preference points and 100 service.

    "When no rows exist at the current filing sequence, or when the current filing does not name this candidate at all, its preference points are 0.0000."

    Design: Difficulty/combinatorial_formula/selection_score_composed_from_prerounded_clamped_components
    """
    _ref, solicitation, cheap_frequency, big_bid = _two_candidate_round(api)

    assert cheap_frequency["projected_annual_passengers"] == 8892
    assert_money(
        cheap_frequency["subsidy_per_passenger_usd"], 179.94, "subsidy_per_passenger_usd"
    )
    assert big_bid["projected_annual_passengers"] == 16380
    assert_money(
        big_bid["subsidy_per_passenger_usd"], 177.05, "subsidy_per_passenger_usd"
    )

    ranking = validate_success(api.get_ranking(solicitation["id"], OFFICER))

    assert ranking["candidate_count"] == 2
    assert ranking["top_proposal_id"] == big_bid["id"]
    assert_ratio(ranking["top_composite_score"], 60.0000, "top_composite_score")
    assert ranking["ranked_proposal_ids"] == [big_bid["id"], cheap_frequency["id"]]
    assert ranking["excluded_proposal_ids"] == []


def test_preference_points_at_weight_forty_move_the_award_to_the_ranked_favourite(api):
    """The filing lifts the top-ranked candidate from 59.4379 to 99.4379 and wins it.

    "The `composite_score` is the weighted sum of those three rounded components — preference points weighted 0.40, subsidy points weighted 0.35, service points weighted 0.25 — with the sum itself rounded half-up to four decimal places."

    Design: Difficulty/combinatorial_formula/selection_score_composed_from_prerounded_clamped_components
    """
    ref, solicitation, cheap_frequency, big_bid = _two_candidate_round(api)
    fx.file_preferences(
        api, solicitation, [cheap_frequency["id"], big_bid["id"]]
    )

    ranking = validate_success(api.get_ranking(solicitation["id"], OFFICER))
    assert ranking["top_proposal_id"] == cheap_frequency["id"]
    assert_ratio(ranking["top_composite_score"], 99.4379, "top_composite_score")

    agreement = fx.issue_selection_order(api, solicitation["id"])

    winner = validate_success(api.get_proposal(cheap_frequency["id"], ADMIN))
    loser = validate_success(api.get_proposal(big_bid["id"], ADMIN))
    assert_ratio(winner["composite_score"], 99.4379, "composite_score")
    assert winner["evaluation_state"] == EVAL_SELECTED
    assert_ratio(loser["composite_score"], 80.0000, "composite_score")
    assert loser["evaluation_state"] == EVAL_NOT_SELECTED
    assert agreement["carrier_id"] == ref.carrier_id
    assert agreement["min_monthly_seats"] == 1976
