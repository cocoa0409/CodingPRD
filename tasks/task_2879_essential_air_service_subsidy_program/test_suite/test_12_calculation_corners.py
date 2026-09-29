"""Corner cases in the program's arithmetic.

Boundary values, tiered rates, declared percentage constants, input-set
filtering and the round-half-up rounding mode.
"""

from prd_bench_local_runner.testing import (
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.assertions import (
    assert_money,
    assert_obligation_identity,
    assert_one_decimal,
    assert_period_balanced,
    assert_ratio,
    assert_score,
)
from test_helpers.constants import (
    AGREEMENT_ACTIVE,
    BASIS_STRICT,
    CARRIER_ACTIVE,
    COMMUNITY_ELIGIBLE,
    COMMUNITY_INELIGIBLE,
    DEFAULT_CLOCK,
    DISTANCE_BAND_CAPPED,
    ENFORCEMENT_NONE,
    OUTCOME_ELIGIBLE,
    OUTCOME_ELIGIBLE_WITH_WAIVER,
    OUTCOME_INELIGIBLE_ENPLANEMENTS,
    PAYMENT_BASIS_COMPLETED_FLIGHT_PRORATION,
    PERIOD_CERTIFIED,
    PERIOD_REPORTED,
    REVIEW_WATCH,
    SUBSIDY_PER_PASSENGER_CAP_USD,
    WITHHOLDING_PCT_LOW,
    WITHHOLDING_PCT_MID,
    WITHHOLDING_PCT_NONE,
    WITHHOLDING_PCT_SEVERE,
)
from test_helpers.test_users import ADMIN, ADMIN_REVIEWER, ANALYST


# ─── calculations / enplanement_floor_at_the_rounded_boundary ─────────

def test_enplanement_floor_reads_the_two_decimal_rounded_average(api: ApiClient):
    """One extra prior-year boarding crosses the daily enplanement floor.

    "The determination records `avg_daily_enplanements`, the community's `enplanements_prior_year` divided by 365 and rounded half-up to two decimal places."

    Design: Corner/calculations/enplanement_floor_at_the_rounded_boundary
    """
    fx.set_clock(api, DEFAULT_CLOCK)

    low = validate_success(
        api.create_community(
            f.community_payload(code="HYS", name="Hays",
                                driving_miles_to_nearest_hub=165.0,
                                enplanements_prior_year=3648),
            ADMIN,
        ),
        201,
    )
    at_floor = validate_success(
        api.create_community(
            f.community_payload(code="DDC", name="Dodge City",
                                driving_miles_to_nearest_hub=165.0,
                                enplanements_prior_year=3649),
            ADMIN,
        ),
        201,
    )

    low_det = validate_success(
        api.create_eligibility_determination(
            low["id"], f.determination_payload(waiver_requested=False), ANALYST
        ),
        201,
    )
    at_floor_det = validate_success(
        api.create_eligibility_determination(
            at_floor["id"], f.determination_payload(waiver_requested=False), ANALYST
        ),
        201,
    )

    # 3648 / 365 == 9.99452... which rounds to 9.99 and misses the floor of 10.
    assert_money(low_det["avg_daily_enplanements"], 9.99,
                 "avg_daily_enplanements")
    assert low_det["outcome"] == OUTCOME_INELIGIBLE_ENPLANEMENTS
    assert_one_decimal(low_det["driving_miles_at_determination"], 165.0,
                       "driving_miles_at_determination")

    # 3649 / 365 == 9.99726... which rounds up to exactly 10.00 and clears it.
    assert_money(at_floor_det["avg_daily_enplanements"], 10.00,
                 "avg_daily_enplanements")
    assert at_floor_det["outcome"] == OUTCOME_ELIGIBLE

    low_row = validate_success(api.get_community(low["id"], ADMIN))
    at_floor_row = validate_success(api.get_community(at_floor["id"], ADMIN))
    assert low_row["status"] == COMMUNITY_INELIGIBLE
    assert low_row["latest_determination_outcome"] == OUTCOME_INELIGIBLE_ENPLANEMENTS
    assert at_floor_row["status"] == COMMUNITY_ELIGIBLE
    assert at_floor_row["latest_determination_outcome"] == OUTCOME_ELIGIBLE


def test_waiver_branch_changes_the_outcome_but_not_the_band_or_the_cap(api: ApiClient):
    """A sub-floor community with a waiver request becomes eligible with a waiver.

    "If it is below 10 but this filing set `waiver_requested` to true, the outcome is `ELIGIBLE_WITH_WAIVER`."

    Design: Corner/calculations/enplanement_floor_at_the_rounded_boundary
    """
    fx.set_clock(api, DEFAULT_CLOCK)

    community = validate_success(
        api.create_community(
            f.community_payload(code="GDV", name="Glendive", state_code="MT",
                                driving_miles_to_nearest_hub=165.0,
                                enplanements_prior_year=3648),
            ADMIN,
        ),
        201,
    )
    determination = validate_success(
        api.create_eligibility_determination(
            community["id"], f.determination_payload(waiver_requested=True), ANALYST
        ),
        201,
    )

    assert_money(determination["avg_daily_enplanements"], 9.99,
                 "avg_daily_enplanements")
    assert determination["outcome"] == OUTCOME_ELIGIBLE_WITH_WAIVER
    # The enplanement branch never touches the distance band or the ceiling.
    assert determination["distance_band"] == DISTANCE_BAND_CAPPED
    assert_money(determination["subsidy_per_passenger_cap_usd"],
                 SUBSIDY_PER_PASSENGER_CAP_USD, "subsidy_per_passenger_cap_usd")

    row = validate_success(api.get_community(community["id"], ADMIN))
    assert row["status"] == COMMUNITY_ELIGIBLE
    assert row["latest_determination_outcome"] == OUTCOME_ELIGIBLE_WITH_WAIVER
    assert row["distance_band"] == DISTANCE_BAND_CAPPED
    assert_money(row["subsidy_per_passenger_cap_usd"],
                 SUBSIDY_PER_PASSENGER_CAP_USD, "subsidy_per_passenger_cap_usd")


# ─── calculations / withholding_tier_boundaries_across_four_months ────

def _certified_payment(api: ApiClient, period_id: str):
    """Certify one reported month and return (period, payment)."""
    fx.certify_period(api, period_id)
    period = validate_success(api.get_service_period(period_id, ADMIN))
    payment = fx.payment_for_period(api, period_id)
    return period, payment


def test_completion_factor_at_0_9500_withholds_nothing(api: ApiClient):
    """A month landing exactly on the top tier boundary suffers no withholding.

    "A completion factor of 0.9500 or better withholds nothing, so `withholding_pct` is 0.00; a factor from 0.9000 up to but not including 0.9500 withholds 0.02; a factor from 0.8500 up to but not including 0.9000 withholds 0.05; anything below 0.8500 withholds 0.10."

    Design: Corner/calculations/withholding_tier_boundaries_across_four_months
    """
    award = fx.build_award(api, clock=DEFAULT_CLOCK)
    period = fx.reported_period(
        api, award.agreement_id, award.carrier_id, "2026-08",
        scheduled_departures=100, completed_departures=95,
        cancelled_carrier_departures=0, cancelled_weather_departures=5,
        seats_offered=1900, passengers_enplaned=700,
    )
    assert_period_balanced(period)

    period, payment = _certified_payment(api, period["id"])

    assert_ratio(period["period_completion_factor"], 0.9500,
                 "period_completion_factor")
    # 1600000.00 / 12 == 133333.33 and 133333.33 / 100 == 1333.33.
    assert_money(payment["monthly_entitlement_usd"], 133333.33,
                 "monthly_entitlement_usd")
    assert_money(payment["per_departure_rate_usd"], 1333.33,
                 "per_departure_rate_usd")
    # All 5 weather cancellations sit inside the floor(100 * 5 / 100) == 5 allowance.
    assert payment["credited_departures"] == 100
    assert_money(payment["gross_subsidy_usd"], 133333.00, "gross_subsidy_usd")
    assert_money(payment["cancellation_adjustment_usd"], 0.00,
                 "cancellation_adjustment_usd")
    assert_ratio(payment["withholding_pct"], WITHHOLDING_PCT_NONE,
                 "withholding_pct")
    assert_money(payment["performance_withholding_usd"], 0.00,
                 "performance_withholding_usd")
    assert_money(payment["net_payment_usd"], 133333.00, "net_payment_usd")
    assert payment["variant_used"] == PAYMENT_BASIS_COMPLETED_FLIGHT_PRORATION


def test_completion_factor_at_0_9000_withholds_two_percent(api: ApiClient):
    """A month landing exactly on the second tier boundary withholds 0.02.

    "`performance_withholding_usd` is the gross subsidy less the cancellation adjustment, multiplied by that rate and rounded half-up to cents."

    Design: Corner/calculations/withholding_tier_boundaries_across_four_months
    """
    award = fx.build_award(api, clock=DEFAULT_CLOCK)
    fx.reported_period(
        api, award.agreement_id, award.carrier_id, "2026-08",
        scheduled_departures=100, completed_departures=95,
        cancelled_carrier_departures=0, cancelled_weather_departures=5,
        seats_offered=1900, passengers_enplaned=700,
    )
    september = fx.reported_period(
        api, award.agreement_id, award.carrier_id, "2026-09",
        scheduled_departures=100, completed_departures=90,
        cancelled_carrier_departures=0, cancelled_weather_departures=10,
        seats_offered=1900, passengers_enplaned=700,
    )

    period, payment = _certified_payment(api, september["id"])

    assert_ratio(period["period_completion_factor"], 0.9000,
                 "period_completion_factor")
    assert_money(payment["per_departure_rate_usd"], 1333.33,
                 "per_departure_rate_usd")
    # Only 5 of the 10 weather cancellations are credited.
    assert payment["credited_departures"] == 95
    assert_money(payment["gross_subsidy_usd"], 126666.35, "gross_subsidy_usd")
    assert_ratio(payment["withholding_pct"], WITHHOLDING_PCT_MID,
                 "withholding_pct")
    assert_money(payment["performance_withholding_usd"], 2533.33,
                 "performance_withholding_usd")
    assert_money(payment["net_payment_usd"], 124133.02, "net_payment_usd")


def test_lower_withholding_tiers_apply_at_0_8500_and_below(api: ApiClient):
    """The third tier boundary withholds 0.05 and anything under it withholds 0.10.

    "A completion factor of 0.9500 or better withholds nothing, so `withholding_pct` is 0.00; a factor from 0.9000 up to but not including 0.9500 withholds 0.02; a factor from 0.8500 up to but not including 0.9000 withholds 0.05; anything below 0.8500 withholds 0.10."

    Design: Corner/calculations/withholding_tier_boundaries_across_four_months
    """
    award = fx.build_award(api, clock=DEFAULT_CLOCK)
    fx.reported_period(
        api, award.agreement_id, award.carrier_id, "2026-08",
        scheduled_departures=100, completed_departures=95,
        cancelled_carrier_departures=0, cancelled_weather_departures=5,
        seats_offered=1900, passengers_enplaned=700,
    )
    fx.reported_period(
        api, award.agreement_id, award.carrier_id, "2026-09",
        scheduled_departures=100, completed_departures=90,
        cancelled_carrier_departures=0, cancelled_weather_departures=10,
        seats_offered=1900, passengers_enplaned=700,
    )
    october = fx.reported_period(
        api, award.agreement_id, award.carrier_id, "2026-10",
        scheduled_departures=100, completed_departures=85,
        cancelled_carrier_departures=0, cancelled_weather_departures=15,
        seats_offered=1900, passengers_enplaned=700,
    )
    oct_period, oct_payment = _certified_payment(api, october["id"])

    assert_ratio(oct_period["period_completion_factor"], 0.8500,
                 "period_completion_factor")
    assert oct_payment["credited_departures"] == 90
    assert_money(oct_payment["gross_subsidy_usd"], 119999.70,
                 "gross_subsidy_usd")
    assert_ratio(oct_payment["withholding_pct"], WITHHOLDING_PCT_LOW,
                 "withholding_pct")
    assert_money(oct_payment["performance_withholding_usd"], 5999.99,
                 "performance_withholding_usd")
    assert_money(oct_payment["net_payment_usd"], 113999.71, "net_payment_usd")

    november = fx.reported_period(
        api, award.agreement_id, award.carrier_id, "2026-11",
        scheduled_departures=100, completed_departures=84,
        cancelled_carrier_departures=0, cancelled_weather_departures=16,
        seats_offered=1900, passengers_enplaned=700,
    )
    nov_period, nov_payment = _certified_payment(api, november["id"])

    assert_ratio(nov_period["period_completion_factor"], 0.8400,
                 "period_completion_factor")
    assert nov_payment["credited_departures"] == 89
    assert_money(nov_payment["gross_subsidy_usd"], 118666.37,
                 "gross_subsidy_usd")
    assert_ratio(nov_payment["withholding_pct"], WITHHOLDING_PCT_SEVERE,
                 "withholding_pct")
    assert_money(nov_payment["performance_withholding_usd"], 11866.64,
                 "performance_withholding_usd")
    assert_money(nov_payment["net_payment_usd"], 106799.73, "net_payment_usd")

    # Nothing was disbursed, so the obligation ledger has not moved at all.
    agreement = award.reload()
    assert_money(agreement["obligated_remaining_usd"], 3200000.00,
                 "obligated_remaining_usd")
    assert_money(agreement["disbursed_to_date_usd"], 0.00,
                 "disbursed_to_date_usd")
    assert_obligation_identity(agreement)


# ─── calculations / allowances_use_the_declared_percentage_constants ──

def test_weather_and_carrier_allowances_use_five_and_two_percent(api: ApiClient):
    """Ten weather cancellations are fully credited while ten carrier ones are not.

    "Under `COMPLETED_FLIGHT_PRORATION` the program pays per departure actually flown, with a limited credit for excusable weather cancellations: the weather allowance is 5 percent of the month's scheduled departures with the fractional part discarded, `credited_departures` is the completed departures plus the smaller of the weather cancellations and that allowance, and the gross is the per-departure rate multiplied by the credited departures, rounded half-up to cents."

    Design: Corner/calculations/allowances_use_the_declared_percentage_constants
    """
    award = fx.build_award(api, clock=DEFAULT_CLOCK)
    period = fx.reported_period(
        api, award.agreement_id, award.carrier_id, "2026-08",
        scheduled_departures=200, completed_departures=180,
        cancelled_carrier_departures=10, cancelled_weather_departures=10,
        seats_offered=3800, passengers_enplaned=1400,
    )
    assert_period_balanced(period)

    period, payment = _certified_payment(api, period["id"])

    assert_ratio(period["period_completion_factor"], 0.9000,
                 "period_completion_factor")
    assert_money(payment["monthly_entitlement_usd"], 133333.33,
                 "monthly_entitlement_usd")
    # 133333.33 / 200 == 666.666... which rounds half-up to 666.67.
    assert_money(payment["per_departure_rate_usd"], 666.67,
                 "per_departure_rate_usd")
    # The weather allowance is floor(200 * 0.05) == 10, so all 10 are credited.
    assert payment["credited_departures"] == 190
    assert_money(payment["gross_subsidy_usd"], 126667.30, "gross_subsidy_usd")
    # The carrier allowance is floor(200 * 0.02) == 4, leaving 6 chargeable.
    assert_money(payment["cancellation_adjustment_usd"], 2000.01,
                 "cancellation_adjustment_usd")
    assert_ratio(payment["withholding_pct"], WITHHOLDING_PCT_MID,
                 "withholding_pct")
    assert_money(payment["performance_withholding_usd"], 2493.35,
                 "performance_withholding_usd")
    assert_money(payment["net_payment_usd"], 122173.94, "net_payment_usd")
    assert_money(payment["hold_in_premium_usd"], 0.00, "hold_in_premium_usd")
    assert_money(payment["total_disbursement_usd"], 122173.94,
                 "total_disbursement_usd")


def test_payment_preview_shows_the_allowance_arithmetic_without_persisting(api: ApiClient):
    """The preview reproduces the allowance figures and writes nothing.

    "Nothing is persisted; no payment is created and no state moves."

    Design: Corner/calculations/allowances_use_the_declared_percentage_constants
    """
    award = fx.build_award(api, clock=DEFAULT_CLOCK)
    period = fx.reported_period(
        api, award.agreement_id, award.carrier_id, "2026-08",
        scheduled_departures=200, completed_departures=180,
        cancelled_carrier_departures=10, cancelled_weather_departures=10,
        seats_offered=3800, passengers_enplaned=1400,
    )

    preview = validate_success(api.get_payment_preview(period["id"], ADMIN))

    assert preview["variant_in_effect"] == PAYMENT_BASIS_COMPLETED_FLIGHT_PRORATION
    assert_money(preview["per_departure_rate_usd"], 666.67,
                 "per_departure_rate_usd")
    assert preview["credited_departures"] == 190
    assert_money(preview["completed_flight_proration_net_usd"], 122173.94,
                 "completed_flight_proration_net_usd")

    unchanged = validate_success(api.get_service_period(period["id"], ADMIN))
    assert unchanged["status"] == PERIOD_REPORTED
    rows, meta = validate_paginated(api.list_subsidy_payments(ADMIN))
    assert rows == []
    assert meta["total_count"] == 0


# ─── calculations / review_reads_only_certified_and_paid_periods ──────

def _review_window(api: ApiClient):
    """Two certified months around one month left reported, plus the review."""
    award = fx.build_award(api, clock=DEFAULT_CLOCK)
    fx.certified_month(
        api, award.agreement_id, award.carrier_id, "2026-08",
        scheduled_departures=100, completed_departures=93,
        cancelled_carrier_departures=0, cancelled_weather_departures=7,
        seats_offered=1900, passengers_enplaned=700,
    )
    # This month is reported but never certified, so the review must skip it.
    fx.reported_period(
        api, award.agreement_id, award.carrier_id, "2026-09",
        scheduled_departures=100, completed_departures=50,
        cancelled_carrier_departures=0, cancelled_weather_departures=50,
        seats_offered=900, passengers_enplaned=100,
    )
    fx.certified_month(
        api, award.agreement_id, award.carrier_id, "2026-10",
        scheduled_departures=100, completed_departures=92,
        cancelled_carrier_departures=0, cancelled_weather_departures=8,
        seats_offered=1900, passengers_enplaned=700,
    )
    review = validate_success(
        api.create_performance_review(
            f.performance_review_payload(
                award.agreement_id, "2026-08", "2026-10", basis=BASIS_STRICT
            ),
            ADMIN_REVIEWER,
        ),
        201,
    )
    return award, review


def test_review_basis_excludes_a_month_left_reported(api: ApiClient):
    """A reported month inside the window contributes nothing to the totals.

    "A month is included when it belongs to the reviewed agreement, its `period_month` falls inside the window with both bounds inclusive, and its `status` is `CERTIFIED` or `PAID`; `included_period_count` records how many qualified."

    Design: Corner/calculations/review_reads_only_certified_and_paid_periods
    """
    award, review = _review_window(api)

    assert review["basis"] == BASIS_STRICT
    assert review["months_in_window"] == 3
    assert review["included_period_count"] == 2
    assert review["sum_scheduled_departures"] == 200
    assert review["sum_completed_departures"] == 185
    assert review["sum_cancelled_weather_departures"] == 15
    assert review["sum_seats_offered"] == 3800
    assert review["sum_passengers_enplaned"] == 1400
    # 185 / 200 == 0.9250 under STRICT, which lands in the WATCH band.
    assert_ratio(review["completion_factor"], 0.9250, "completion_factor")
    assert review["tier"] == REVIEW_WATCH


def test_review_quality_score_spans_the_whole_window(api: ApiClient):
    """The seat floor is measured across all three months, not just the included two.

    "`quality_score` is one hundred multiplied by the sum of the completion factor weighted 0.60, the seat fulfilment weighted 0.30, and the normalised load weighted 0.10, with the whole expression rounded half-up to two decimal places exactly once at the end."

    Design: Corner/calculations/review_reads_only_certified_and_paid_periods
    """
    award, review = _review_window(api)

    agreement = award.reload()
    # 12 round trips * 2 * 19 seats * 52 / 12 == 1976 with the fraction dropped.
    assert agreement["min_monthly_seats"] == 1976
    # 3800 / (1976 * 3) == 0.641025... which rounds to 0.6410.
    assert_ratio(review["seat_fulfillment"], 0.6410, "seat_fulfillment")
    # 1400 / 3800 == 0.368421... which rounds to 0.3684.
    assert_ratio(review["load_factor"], 0.3684, "load_factor")
    assert_score(review["quality_score"], 84.55, "quality_score")
    assert review["action_taken"] == ENFORCEMENT_NONE
    assert review["reviewed_by_user_id"] == ADMIN_REVIEWER["X-User-ID"]

    carrier = validate_success(api.get_carrier(award.carrier_id, ADMIN))
    assert carrier["status"] == CARRIER_ACTIVE
    assert carrier["consecutive_watch_count"] == 1
    assert_ratio(carrier["latest_completion_factor"], 0.9250,
                 "latest_completion_factor")
    assert_score(carrier["latest_quality_score"], 84.55, "latest_quality_score")
    assert carrier["latest_performance_tier"] == REVIEW_WATCH


# ─── calculations / half_up_rounding_is_visible_at_the_half_cent ──────

def test_half_up_rounding_prices_the_bid_per_passenger(api: ApiClient):
    """An odd-cent annual request still rounds the per-passenger price half-up.

    "Dividing `annual_subsidy_request_usd` by that projected count and rounding half-up to two decimal places gives `subsidy_per_passenger_usd`, the number a community's per-passenger ceiling will be compared against."

    Design: Corner/calculations/half_up_rounding_is_visible_at_the_half_cent
    """
    ref = fx.make_reference_data(api, clock=DEFAULT_CLOCK)
    # 6200 / 365 == 16.9863... which rounds to 16.99.
    assert_money(ref.determination["avg_daily_enplanements"], 16.99,
                 "avg_daily_enplanements")

    solicitation = fx.open_solicitation(api, ref.community_id)
    proposal = fx.submitted_proposal(
        api, solicitation["id"], ref.carrier_id, ref.aircraft_type_id,
        annual_subsidy_request_usd=1200000.06, term_months=12,
    )

    # 12 * 2 * 19 * 52 * 0.375 == 8892.0 exactly.
    assert proposal["projected_annual_passengers"] == 8892
    # 1200000.06 / 8892 == 134.95277... which rounds to 134.95.
    assert_money(proposal["subsidy_per_passenger_usd"], 134.95,
                 "subsidy_per_passenger_usd")


def test_monthly_entitlement_rounds_the_half_cent_upward(api: ApiClient):
    """An annual rate of 1,200,000.06 divides into a monthly half-cent that rounds up.

    "Money in this program is carried to two decimal places and every monetary rounding is round-half-up."

    Design: Corner/calculations/half_up_rounding_is_visible_at_the_half_cent
    """
    award = fx.build_award(
        api, clock=DEFAULT_CLOCK,
        proposal_overrides={"annual_subsidy_request_usd": 1200000.06,
                            "term_months": 12},
    )
    agreement = award.agreement
    assert agreement["status"] == AGREEMENT_ACTIVE
    assert_money(agreement["annual_subsidy_usd"], 1200000.06,
                 "annual_subsidy_usd")
    # 1200000.06 * 12 / 12 == 1200000.06.
    assert_money(agreement["total_committed_usd"], 1200000.06,
                 "total_committed_usd")

    period = fx.reported_period(
        api, award.agreement_id, award.carrier_id, "2026-08",
        scheduled_departures=100, completed_departures=100,
        cancelled_carrier_departures=0, cancelled_weather_departures=0,
        seats_offered=1900, passengers_enplaned=700,
    )
    period, payment = _certified_payment(api, period["id"])

    assert period["status"] == PERIOD_CERTIFIED
    # 1200000.06 / 12 == 100000.005, which rounds up rather than to even.
    assert_money(payment["monthly_entitlement_usd"], 100000.01,
                 "monthly_entitlement_usd")
    # 100000.01 / 100 == 1000.0001, which rounds down to 1000.00.
    assert_money(payment["per_departure_rate_usd"], 1000.00,
                 "per_departure_rate_usd")
    assert payment["credited_departures"] == 100
    assert_money(payment["gross_subsidy_usd"], 100000.00, "gross_subsidy_usd")
    assert_ratio(payment["withholding_pct"], WITHHOLDING_PCT_NONE,
                 "withholding_pct")
    assert_money(payment["net_payment_usd"], 100000.00, "net_payment_usd")
