"""Boundary and precision probes: distance bands, the per-passenger cap and
zero departure denominators."""

from prd_bench_local_runner.testing import (
    validate_success,
    validate_error,
)

from test_helpers import api_errors as E
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.assertions import (
    assert_append_only_row,
    assert_departure_identity,
    assert_money,
    assert_period_balanced,
    assert_ratio,
)
from test_helpers.constants import (
    BASIS_ADJUSTED,
    BASIS_STRICT,
    COMMUNITY_ELIGIBLE,
    COMMUNITY_INELIGIBLE,
    DEFAULT_CLOCK,
    DISTANCE_BAND_CAPPED,
    DISTANCE_BAND_TOO_CLOSE,
    DISTANCE_BAND_UNCAPPED,
    ENFORCEMENT_SUSPEND_HOLD_IN,
    OUTCOME_ELIGIBLE,
    OUTCOME_INELIGIBLE_DISTANCE,
    PERIOD_OPEN,
    PERIOD_REPORTED,
    PROPOSAL_DRAFT,
    PROPOSAL_SUBMIT,
    PROPOSAL_SUBMITTED,
    EVAL_NOT_EVALUATED,
    REVIEW_DEFICIENT,
    SUBSIDY_PER_PASSENGER_CAP_USD,
)
from test_helpers.test_users import ADMIN, ADMIN_REVIEWER, ANALYST


# ─── cap_exemption_distance_threshold_is_inclusive ────────────────────

def test_community_exactly_seventy_miles_from_a_hub_is_capped(api: ApiClient):
    """A community exactly 70.0 road miles out lands in the CAPPED band and takes the 200.00 ceiling.

    "Both boundaries are inclusive on the upper side of the comparison — a community exactly 70.0 miles out is `CAPPED`, and one exactly 210.0 miles out is `UNCAPPED`."

    Design: Difficulty/boundary_precision_check/cap_exemption_distance_threshold_is_inclusive
    """
    fx.set_clock(api, DEFAULT_CLOCK)
    community = validate_success(
        api.create_community(
            f.community_payload(
                code="EDG",
                name="Edge Town",
                driving_miles_to_nearest_hub=70.0,
                enplanements_prior_year=6200,
            ),
            ADMIN,
        ),
        201,
    )

    determination = validate_success(
        api.create_eligibility_determination(
            community["id"], f.determination_payload(), ANALYST
        ),
        201,
    )
    assert_append_only_row(determination)
    assert determination["distance_band"] == DISTANCE_BAND_CAPPED
    assert determination["outcome"] == OUTCOME_ELIGIBLE
    assert_money(
        determination["subsidy_per_passenger_cap_usd"],
        SUBSIDY_PER_PASSENGER_CAP_USD,
        "subsidy_per_passenger_cap_usd",
    )
    assert_money(determination["avg_daily_enplanements"], 16.99, "avg_daily_enplanements")

    reread = validate_success(api.get_community(community["id"], ADMIN))
    assert reread["status"] == COMMUNITY_ELIGIBLE
    assert reread["distance_band"] == DISTANCE_BAND_CAPPED
    assert_money(
        reread["subsidy_per_passenger_cap_usd"],
        SUBSIDY_PER_PASSENGER_CAP_USD,
        "community subsidy_per_passenger_cap_usd",
    )


def test_community_just_under_seventy_miles_from_a_hub_is_too_close(api: ApiClient):
    """At 69.9 road miles the community is TOO_CLOSE, fails on distance and records no ceiling.

    "If the band is `TOO_CLOSE` the outcome is `INELIGIBLE_DISTANCE`, and the enplanement figure is never consulted — a community too close to a hub is never reported as failing on traffic."

    Design: Difficulty/boundary_precision_check/cap_exemption_distance_threshold_is_inclusive
    """
    fx.set_clock(api, DEFAULT_CLOCK)
    community = validate_success(
        api.create_community(
            f.community_payload(
                code="NER",
                name="Near Town",
                driving_miles_to_nearest_hub=69.9,
                enplanements_prior_year=6200,
            ),
            ADMIN,
        ),
        201,
    )

    determination = validate_success(
        api.create_eligibility_determination(
            community["id"], f.determination_payload(), ANALYST
        ),
        201,
    )
    assert determination["distance_band"] == DISTANCE_BAND_TOO_CLOSE
    assert determination["outcome"] == OUTCOME_INELIGIBLE_DISTANCE
    assert determination.get("subsidy_per_passenger_cap_usd") is None

    reread = validate_success(api.get_community(community["id"], ADMIN))
    assert reread["status"] == COMMUNITY_INELIGIBLE
    assert reread["distance_band"] == DISTANCE_BAND_TOO_CLOSE


def test_cap_exemption_bound_at_two_hundred_ten_miles_is_inclusive(api: ApiClient):
    """209.9 miles still carries the per-passenger ceiling while exactly 210.0 miles is exempt from it.

    "A determination in the `CAPPED` band records a `subsidy_per_passenger_cap_usd` of 200.00; a determination in the `TOO_CLOSE` or `UNCAPPED` band records no cap at all."

    Design: Difficulty/boundary_precision_check/cap_exemption_distance_threshold_is_inclusive
    """
    fx.set_clock(api, DEFAULT_CLOCK)
    inside = validate_success(
        api.create_community(
            f.community_payload(
                code="FAR",
                name="Far Town",
                state_code="MT",
                driving_miles_to_nearest_hub=209.9,
                enplanements_prior_year=6200,
            ),
            ADMIN,
        ),
        201,
    )
    exempt = validate_success(
        api.create_community(
            f.community_payload(
                code="RMT",
                name="Remote Town",
                state_code="MT",
                driving_miles_to_nearest_hub=210.0,
                enplanements_prior_year=6200,
            ),
            ADMIN,
        ),
        201,
    )

    inside_determination = validate_success(
        api.create_eligibility_determination(
            inside["id"], f.determination_payload(), ANALYST
        ),
        201,
    )
    assert inside_determination["distance_band"] == DISTANCE_BAND_CAPPED
    assert_money(
        inside_determination["subsidy_per_passenger_cap_usd"],
        SUBSIDY_PER_PASSENGER_CAP_USD,
        "209.9 mile subsidy_per_passenger_cap_usd",
    )

    exempt_determination = validate_success(
        api.create_eligibility_determination(
            exempt["id"], f.determination_payload(), ANALYST
        ),
        201,
    )
    assert exempt_determination["distance_band"] == DISTANCE_BAND_UNCAPPED
    assert exempt_determination["outcome"] == OUTCOME_ELIGIBLE
    assert exempt_determination.get("subsidy_per_passenger_cap_usd") is None

    exempt_community = validate_success(api.get_community(exempt["id"], ADMIN))
    assert exempt_community["distance_band"] == DISTANCE_BAND_UNCAPPED
    assert exempt_community.get("subsidy_per_passenger_cap_usd") is None


# ─── per_passenger_cap_compared_after_rounding_to_cents ───────────────

def test_subsidy_per_passenger_exactly_equal_to_the_cap_submits(api: ApiClient):
    """A request of 1,778,400.00 over 8,892 projected passengers prices at exactly 200.00 and submits.

    "The program projects annual traffic as the weekly round trips multiplied by two — each round trip is two departures — multiplied by the seats offered on each departure, multiplied by 52 weeks in the year, multiplied by an assumed load factor of 0.375, with any fractional passenger discarded: the result is `projected_annual_passengers`."

    Design: Difficulty/boundary_precision_check/per_passenger_cap_compared_after_rounding_to_cents
    """
    ref = fx.make_reference_data(api, clock=DEFAULT_CLOCK)
    solicitation = fx.open_solicitation(api, ref.community_id)

    proposal = fx.draft_proposal(
        api,
        solicitation["id"],
        ref.carrier_id,
        ref.aircraft_type_id,
        annual_subsidy_request_usd=1778400.00,
    )
    assert proposal["projected_annual_passengers"] == 8892
    assert_money(
        proposal["subsidy_per_passenger_usd"], 200.00, "subsidy_per_passenger_usd"
    )
    assert proposal["submission_state"] == PROPOSAL_DRAFT

    submitted = validate_success(
        api.proposal_action(
            proposal["id"], f.proposal_action_payload(PROPOSAL_SUBMIT), ref.carrier_headers
        )
    )
    assert submitted["submission_state"] == PROPOSAL_SUBMITTED
    assert submitted["evaluation_state"] == EVAL_NOT_EVALUATED


def test_subsidy_per_passenger_rounding_down_onto_the_cap_submits(api: ApiClient):
    """1,778,444.00 over 8,892 passengers rounds to exactly 200.00 at the cent, so the cap gate lets it through.

    "Dividing `annual_subsidy_request_usd` by that projected count and rounding half-up to two decimal places gives `subsidy_per_passenger_usd`, the number a community's per-passenger ceiling will be compared against."

    Design: Difficulty/boundary_precision_check/per_passenger_cap_compared_after_rounding_to_cents
    """
    ref = fx.make_reference_data(api, clock=DEFAULT_CLOCK)
    solicitation = fx.open_solicitation(api, ref.community_id)

    proposal = fx.draft_proposal(
        api,
        solicitation["id"],
        ref.carrier_id,
        ref.aircraft_type_id,
        annual_subsidy_request_usd=1778444.00,
    )
    assert proposal["projected_annual_passengers"] == 8892
    assert_money(
        proposal["subsidy_per_passenger_usd"], 200.00, "subsidy_per_passenger_usd"
    )

    submitted = validate_success(
        api.proposal_action(
            proposal["id"], f.proposal_action_payload(PROPOSAL_SUBMIT), ref.carrier_headers
        )
    )
    assert submitted["submission_state"] == PROPOSAL_SUBMITTED


def test_subsidy_per_passenger_rounding_up_past_the_cap_is_refused(api: ApiClient):
    """One dollar more rounds the per-passenger price up to 200.01 and the submission is refused.

    "Finally the per-passenger price is re-derived at submission time, so that a community's cap is applied to the figures actually on the proposal: when the community's `subsidy_per_passenger_cap_usd` is set, the proposal's `subsidy_per_passenger_usd` must not exceed it, and a value exactly equal to the cap is accepted while anything above it is refused with `ERR_SUBSIDY_PER_PASSENGER_CAP_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/per_passenger_cap_compared_after_rounding_to_cents
    """
    ref = fx.make_reference_data(api, clock=DEFAULT_CLOCK)
    solicitation = fx.open_solicitation(api, ref.community_id)

    proposal = fx.draft_proposal(
        api,
        solicitation["id"],
        ref.carrier_id,
        ref.aircraft_type_id,
        annual_subsidy_request_usd=1778445.00,
    )
    assert proposal["projected_annual_passengers"] == 8892
    assert_money(
        proposal["subsidy_per_passenger_usd"], 200.01, "subsidy_per_passenger_usd"
    )

    response = api.proposal_action(
        proposal["id"], f.proposal_action_payload(PROPOSAL_SUBMIT), ref.carrier_headers
    )
    validate_error(response, E.ERR_SUBSIDY_PER_PASSENGER_CAP_EXCEEDED, 422)

    reread = validate_success(api.get_proposal(proposal["id"], ADMIN))
    assert reread["submission_state"] == PROPOSAL_DRAFT
    assert reread["evaluation_state"] == EVAL_NOT_EVALUATED


# ─── zero_denominator_boundary_on_departure_counts ────────────────────

def test_monthly_report_with_zero_scheduled_departures_is_refused(api: ApiClient):
    """A month that scheduled nothing at all cannot be reported even though its counts balance.

    "The month must have had at least one scheduled departure; a `scheduled_departures` of 0 is refused with `ERR_NO_SCHEDULED_DEPARTURES`."

    Design: Difficulty/boundary_precision_check/zero_denominator_boundary_on_departure_counts
    """
    award = fx.build_award(api, clock=DEFAULT_CLOCK)
    period = fx.open_period(api, award.agreement_id, "2026-08")

    response = api.report_service_period(
        period["id"],
        f.report_payload(
            scheduled_departures=0,
            completed_departures=0,
            cancelled_carrier_departures=0,
            cancelled_weather_departures=0,
            seats_offered=0,
            passengers_enplaned=0,
        ),
        award.carrier_headers,
    )
    validate_error(response, E.ERR_NO_SCHEDULED_DEPARTURES, 422)

    reread = validate_success(api.get_service_period(period["id"], ADMIN))
    assert reread["status"] == PERIOD_OPEN
    assert reread["scheduled_departures"] == 0

    agreement = validate_success(api.get_service_agreement(award.agreement_id, ADMIN))
    assert agreement["cumulative_scheduled_departures"] == 0


def test_monthly_report_with_one_scheduled_departure_is_accepted(api: ApiClient):
    """A single scheduled departure is enough of a denominator, and the month reports a completion factor of 1.0000.

    "An accepted report moves the period `OPEN → REPORTED`, writes its `period_completion_factor` as the completed departures divided by the scheduled departures rounded half-up to four decimal places, and adds the month's four departure counts into the agreement's four cumulative counters."

    Design: Difficulty/boundary_precision_check/zero_denominator_boundary_on_departure_counts
    """
    award = fx.build_award(api, clock=DEFAULT_CLOCK)
    period = fx.open_period(api, award.agreement_id, "2026-08")

    reported = validate_success(
        api.report_service_period(
            period["id"],
            f.report_payload(
                scheduled_departures=1,
                completed_departures=1,
                cancelled_carrier_departures=0,
                cancelled_weather_departures=0,
                seats_offered=19,
                passengers_enplaned=7,
            ),
            award.carrier_headers,
        )
    )
    assert reported["status"] == PERIOD_REPORTED
    assert_period_balanced(reported)
    assert_ratio(reported["period_completion_factor"], 1.0000, "period_completion_factor")

    agreement = validate_success(api.get_service_agreement(award.agreement_id, ADMIN))
    assert agreement["cumulative_scheduled_departures"] == 1
    assert agreement["cumulative_completed_departures"] == 1
    assert_departure_identity(agreement)


def test_adjusted_review_denominator_of_zero_is_refused_while_strict_computes(api: ApiClient):
    """A wholly weather-cancelled month collapses the ADJUSTED denominator to zero, yet STRICT still divides by the scheduled total.

    "Under `ADJUSTED`, the denominator is the summed scheduled departures less the summed weather cancellations, and `completion_factor` is the summed completed departures divided by that reduced denominator, again rounded half-up to four decimal places; if that reduced denominator comes out at zero, the review is likewise refused with `ERR_NO_SCHEDULED_DEPARTURES`."

    Design: Difficulty/boundary_precision_check/zero_denominator_boundary_on_departure_counts
    """
    award = fx.build_award(api, clock=DEFAULT_CLOCK)
    period = fx.reported_period(
        api,
        award.agreement_id,
        award.carrier_id,
        "2026-08",
        scheduled_departures=6,
        completed_departures=0,
        cancelled_carrier_departures=0,
        cancelled_weather_departures=6,
        seats_offered=114,
        passengers_enplaned=0,
    )
    assert_ratio(period["period_completion_factor"], 0.0000, "period_completion_factor")
    fx.certify_period(api, period["id"])

    refused = api.create_performance_review(
        f.performance_review_payload(
            award.agreement_id, "2026-08", "2026-08", basis=BASIS_ADJUSTED
        ),
        ADMIN_REVIEWER,
    )
    validate_error(refused, E.ERR_NO_SCHEDULED_DEPARTURES, 422)

    strict = validate_success(
        api.create_performance_review(
            f.performance_review_payload(
                award.agreement_id, "2026-08", "2026-08", basis=BASIS_STRICT
            ),
            ADMIN_REVIEWER,
        ),
        201,
    )
    assert strict["basis"] == BASIS_STRICT
    assert strict["months_in_window"] == 1
    assert strict["included_period_count"] == 1
    assert strict["sum_scheduled_departures"] == 6
    assert strict["sum_cancelled_weather_departures"] == 6
    assert_ratio(strict["completion_factor"], 0.0000, "completion_factor")
    assert strict["tier"] == REVIEW_DEFICIENT
    assert strict["action_taken"] == ENFORCEMENT_SUSPEND_HOLD_IN
