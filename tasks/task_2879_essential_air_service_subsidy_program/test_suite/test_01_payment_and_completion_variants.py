"""The two dual-variant computations: payment basis and review basis.

Identical operating data settles at two different amounts depending on the
agreement's `payment_basis`, and the identical two certified months read as two
different compliance tiers depending on the review `basis`.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import fixtures as fx
from test_helpers import factories as f
from test_helpers.assertions import (
    assert_append_only_row,
    assert_money,
    assert_ratio,
    assert_score,
)
from test_helpers.constants import (
    BASIS_ADJUSTED,
    BASIS_STRICT,
    CARRIER_ACTIVE,
    DEFAULT_CLOCK,
    ENFORCEMENT_NONE,
    PAYMENT_BASIS_COMPLETED_FLIGHT_PRORATION,
    PAYMENT_BASIS_SCHEDULED_FLIGHT_FLAT,
    PERIOD_CERTIFIED,
    REVIEW_COMPLIANT,
    REVIEW_WATCH,
)
from test_helpers.test_users import ADMIN, ADMIN_REVIEWER

SEPTEMBER = {
    "scheduled_departures": 104,
    "completed_departures": 100,
    "cancelled_carrier_departures": 2,
    "cancelled_weather_departures": 2,
    "seats_offered": 1900,
    "passengers_enplaned": 700,
}


def test_payment_preview_reports_both_variant_nets_and_their_divergence(api):
    """The read-only preview prices the same month under both payment bases.

    "The preview answers with the net amount the month would pay under each of the two bases — `completed_flight_proration_net_usd` and `scheduled_flight_flat_net_usd` — together with the `variant_in_effect` for this agreement, the `divergence_usd` between the two figures, the `per_departure_rate_usd` the month resolves to, and the `credited_departures` the proration basis would credit."

    Design: Difficulty/dual_variant_calc/payment_variant_divergence_on_identical_period_data
    """
    award = fx.build_award(api, clock=DEFAULT_CLOCK)
    period = fx.reported_period(api, award.agreement_id, award.carrier_id, "2026-08")

    preview = validate_success(api.get_payment_preview(period["id"], ADMIN))

    assert preview["variant_in_effect"] == PAYMENT_BASIS_COMPLETED_FLIGHT_PRORATION
    assert_money(preview["per_departure_rate_usd"], 1282.05, "per_departure_rate_usd")
    assert preview["credited_departures"] == 96
    assert_money(
        preview["completed_flight_proration_net_usd"],
        115096.03,
        "completed_flight_proration_net_usd",
    )
    assert_money(
        preview["scheduled_flight_flat_net_usd"],
        118750.00,
        "scheduled_flight_flat_net_usd",
    )
    assert_money(preview["divergence_usd"], 3653.97, "divergence_usd")


def test_proration_basis_credits_the_weather_allowance_and_pays_115096_03(api):
    """Certifying a proration-basis month pays for flown plus allowed departures.

    "Under `COMPLETED_FLIGHT_PRORATION` the program pays per departure actually flown, with a limited credit for excusable weather cancellations: the weather allowance is 5 percent of the month's scheduled departures with the fractional part discarded, `credited_departures` is the completed departures plus the smaller of the weather cancellations and that allowance, and the gross is the per-departure rate multiplied by the credited departures, rounded half-up to cents."

    Design: Difficulty/dual_variant_calc/payment_variant_divergence_on_identical_period_data
    """
    award = fx.build_award(api, clock=DEFAULT_CLOCK)
    period = fx.reported_period(api, award.agreement_id, award.carrier_id, "2026-08")

    certified = validate_success(
        api.certify_service_period(period["id"], f.certify_payload(), ADMIN)
    )
    assert certified["status"] == PERIOD_CERTIFIED

    payment = fx.payment_for_period(api, period["id"])
    assert payment["variant_used"] == PAYMENT_BASIS_COMPLETED_FLIGHT_PRORATION
    assert payment["credited_departures"] == 96
    assert_money(payment["monthly_entitlement_usd"], 133333.33, "monthly_entitlement_usd")
    assert_money(payment["per_departure_rate_usd"], 1282.05, "per_departure_rate_usd")
    assert_money(payment["gross_subsidy_usd"], 123076.80, "gross_subsidy_usd")
    assert_money(
        payment["cancellation_adjustment_usd"], 1923.08, "cancellation_adjustment_usd"
    )
    assert_money(payment["withholding_pct"], 0.05, "withholding_pct")
    assert_money(
        payment["performance_withholding_usd"], 6057.69, "performance_withholding_usd"
    )
    assert_money(payment["net_payment_usd"], 115096.03, "net_payment_usd")
    assert_money(payment["hold_in_premium_usd"], 0.00, "hold_in_premium_usd")
    assert_money(payment["total_disbursement_usd"], 115096.03, "total_disbursement_usd")


def test_flat_basis_pays_118750_00_on_the_same_reported_month(api):
    """The flat basis pays the whole entitlement less carrier cancellations only.

    "Under `SCHEDULED_FLIGHT_FLAT` the program pays the whole monthly entitlement less the per-departure rate for each carrier-controllable cancellation, rounded half-up to cents; weather cancellations are paid in full and the weather allowance is irrelevant, and `credited_departures` is recorded as 0."

    Design: Difficulty/dual_variant_calc/payment_variant_divergence_on_identical_period_data
    """
    award = fx.build_award(
        api,
        clock=DEFAULT_CLOCK,
        proposal_overrides={"payment_basis": PAYMENT_BASIS_SCHEDULED_FLIGHT_FLAT},
    )
    period = fx.reported_period(api, award.agreement_id, award.carrier_id, "2026-08")

    validate_success(
        api.certify_service_period(period["id"], f.certify_payload(), ADMIN)
    )

    payment = fx.payment_for_period(api, period["id"])
    assert payment["variant_used"] == PAYMENT_BASIS_SCHEDULED_FLIGHT_FLAT
    assert payment["credited_departures"] == 0
    assert_money(payment["gross_subsidy_usd"], 126923.08, "gross_subsidy_usd")
    assert_money(
        payment["cancellation_adjustment_usd"], 1923.08, "cancellation_adjustment_usd"
    )
    assert_money(
        payment["performance_withholding_usd"], 6250.00, "performance_withholding_usd"
    )
    assert_money(payment["net_payment_usd"], 118750.00, "net_payment_usd")


def test_strict_basis_charges_weather_and_marks_the_carrier_on_watch(api):
    """Two settled months read 0.9183 and WATCH when weather is charged.

    "Under `STRICT`, `completion_factor` is the summed completed departures divided by the summed scheduled departures, rounded half-up to four decimal places — weather cancellations are charged against the carrier."

    Design: Difficulty/dual_variant_calc/completion_factor_basis_flips_carrier_tier
    """
    award = fx.build_award(api, clock=DEFAULT_CLOCK)
    fx.certified_month(api, award.agreement_id, award.carrier_id, "2026-08")
    fx.certified_month(
        api, award.agreement_id, award.carrier_id, "2026-09", **SEPTEMBER
    )

    review = validate_success(
        api.create_performance_review(
            f.performance_review_payload(
                award.agreement_id, "2026-08", "2026-09", basis=BASIS_STRICT
            ),
            ADMIN_REVIEWER,
        ),
        201,
    )

    assert_append_only_row(review)
    assert review["basis"] == BASIS_STRICT
    assert review["months_in_window"] == 2
    assert review["included_period_count"] == 2
    assert review["sum_scheduled_departures"] == 208
    assert review["sum_completed_departures"] == 191
    assert review["sum_cancelled_weather_departures"] == 10
    assert_ratio(review["completion_factor"], 0.9183, "completion_factor")
    assert review["tier"] == REVIEW_WATCH
    assert_ratio(review["seat_fulfillment"], 0.9183, "seat_fulfillment")
    assert_ratio(review["load_factor"], 0.3637, "load_factor")
    assert_score(review["quality_score"], 92.35)
    assert review["action_taken"] == ENFORCEMENT_NONE

    carrier = validate_success(api.get_carrier(award.carrier_id, ADMIN))
    assert carrier["latest_performance_tier"] == REVIEW_WATCH
    assert carrier["consecutive_watch_count"] == 1
    assert carrier["status"] == CARRIER_ACTIVE


def test_adjusted_basis_excuses_weather_and_lifts_the_carrier_to_compliant(api):
    """The same two months read 0.9646 and COMPLIANT once weather is excused.

    "Under `ADJUSTED`, the denominator is the summed scheduled departures less the summed weather cancellations, and `completion_factor` is the summed completed departures divided by that reduced denominator, again rounded half-up to four decimal places; if that reduced denominator comes out at zero, the review is likewise refused with `ERR_NO_SCHEDULED_DEPARTURES`."

    Design: Difficulty/dual_variant_calc/completion_factor_basis_flips_carrier_tier
    """
    award = fx.build_award(api, clock=DEFAULT_CLOCK)
    fx.certified_month(api, award.agreement_id, award.carrier_id, "2026-08")
    fx.certified_month(
        api, award.agreement_id, award.carrier_id, "2026-09", **SEPTEMBER
    )
    validate_success(
        api.create_performance_review(
            f.performance_review_payload(
                award.agreement_id, "2026-08", "2026-09", basis=BASIS_STRICT
            ),
            ADMIN_REVIEWER,
        ),
        201,
    )

    review = validate_success(
        api.create_performance_review(
            f.performance_review_payload(
                award.agreement_id, "2026-08", "2026-09", basis=BASIS_ADJUSTED
            ),
            ADMIN_REVIEWER,
        ),
        201,
    )

    assert review["basis"] == BASIS_ADJUSTED
    assert review["included_period_count"] == 2
    assert_ratio(review["completion_factor"], 0.9646, "completion_factor")
    assert review["tier"] == REVIEW_COMPLIANT
    assert_score(review["quality_score"], 95.12)
    assert review["action_taken"] == ENFORCEMENT_NONE

    carrier = validate_success(api.get_carrier(award.carrier_id, ADMIN))
    assert carrier["latest_performance_tier"] == REVIEW_COMPLIANT
    assert carrier["consecutive_watch_count"] == 0
    assert carrier["status"] == CARRIER_ACTIVE
