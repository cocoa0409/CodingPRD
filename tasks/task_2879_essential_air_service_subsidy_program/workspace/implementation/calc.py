"""Every calculation rule of the program, with the pinned rounding orders of
PRD section 2.7 preserved exactly as written.
"""

from decimal import Decimal

import errors
from db import dec, floor_int, months_inclusive, q2, q4, store

# --- community_eligibility_assessment ------------------------------------
MIN_DISTANCE_FROM_HUB_MILES = Decimal("70")
CAP_EXEMPTION_DISTANCE_MILES = Decimal("210")
MIN_AVG_DAILY_ENPLANEMENTS = Decimal("10")
SUBSIDY_PER_PASSENGER_CAP_USD = Decimal("200.00")

# --- proposal_subsidy_per_passenger --------------------------------------
WEEKS_PER_YEAR = 52
ASSUMED_LOAD_FACTOR = Decimal("0.375")

# --- carrier_selection_ranking -------------------------------------------
WEIGHT_PREFERENCE = Decimal("0.40")
WEIGHT_SUBSIDY = Decimal("0.35")
WEIGHT_SERVICE = Decimal("0.25")

# --- subsidy_payment_amount ----------------------------------------------
WEATHER_CREDIT_ALLOWANCE_PCT = Decimal("5")
CARRIER_CANCEL_ALLOWANCE_PCT = Decimal("2")
CANCELLATION_PENALTY_RATE = Decimal("0.50")
ADJUSTMENT_CAP_PCT = Decimal("0.25")

# --- hold_in_premium -----------------------------------------------------
HOLD_IN_TIER_HIGH_USD = Decimal("120000.00")
HOLD_IN_TIER_MID_USD = Decimal("100000.00")

# --- carrier_completion_factor ------------------------------------------
TIER_COMPLIANT_MIN = Decimal("0.9500")
TIER_WATCH_MIN = Decimal("0.9000")

# --- carrier_performance_scoring ----------------------------------------
QUALITY_WEIGHT_COMPLETION = Decimal("0.60")
QUALITY_WEIGHT_SEATS = Decimal("0.30")
QUALITY_WEIGHT_LOAD = Decimal("0.10")
TARGET_LOAD_FACTOR = Decimal("0.375")

# --- renegotiated_annual_subsidy ----------------------------------------
FUEL_PASSTHROUGH_RATE = Decimal("0.80")
MAX_COST_INCREASE_PCT = Decimal("0.10")
MAX_ANNUAL_INCREASE_PCT = Decimal("0.15")
MAX_ANNUAL_DECREASE_PCT = Decimal("0.05")
REQUEST_FACIAL_CAP_MULTIPLE = Decimal("1.25")

# --- agreement / period constants ---------------------------------------
BLOCK_HOURS_PER_DEPARTURE = Decimal("1.5")
HOLD_IN_SOLICITATION_WINDOW_DAYS = 60
RENEGOTIATION_COOLING_OFF_DAYS = 180
CARRIER_REENTRY_BUFFER_DAYS = 14


# =========================================================================
# calculations.community_eligibility_assessment
# =========================================================================
def community_eligibility_assessment(community, waiver_requested):
    miles = dec(community["driving_miles_to_nearest_hub"])
    enplanements = community["enplanements_prior_year"]

    if miles < MIN_DISTANCE_FROM_HUB_MILES:
        distance_band = "TOO_CLOSE"
    elif miles < CAP_EXEMPTION_DISTANCE_MILES:
        distance_band = "CAPPED"
    else:
        distance_band = "UNCAPPED"

    avg_daily = q2(dec(enplanements) / Decimal("365"))

    if distance_band == "TOO_CLOSE":
        outcome = "INELIGIBLE_DISTANCE"
    elif avg_daily >= MIN_AVG_DAILY_ENPLANEMENTS:
        outcome = "ELIGIBLE"
    elif waiver_requested:
        outcome = "ELIGIBLE_WITH_WAIVER"
    else:
        outcome = "INELIGIBLE_ENPLANEMENTS"

    cap = SUBSIDY_PER_PASSENGER_CAP_USD if distance_band == "CAPPED" else None

    return {
        "driving_miles_at_determination": miles,
        "avg_daily_enplanements": avg_daily,
        "distance_band": distance_band,
        "subsidy_per_passenger_cap_usd": cap,
        "outcome": outcome,
    }


# =========================================================================
# calculations.proposal_subsidy_per_passenger
# =========================================================================
def proposal_pricing(weekly_round_trips, seats_per_departure, annual_request):
    projected = floor_int(
        dec(weekly_round_trips) * Decimal("2") * dec(seats_per_departure)
        * dec(WEEKS_PER_YEAR) * ASSUMED_LOAD_FACTOR
    )
    if projected <= 0:
        return 0, None
    per_passenger = q2(dec(annual_request) / dec(projected))
    return projected, per_passenger


# =========================================================================
# calculations.departure_count_reconciliation
# =========================================================================
def q4_completion(completed, scheduled):
    """A period's own completion factor, to four decimal places."""
    return q4(dec(completed) / dec(scheduled))


# =========================================================================
# calculations.carrier_selection_ranking
# =========================================================================
def candidate_set(solicitation):
    """Explicit eligibility filter of the ranking calculation."""
    candidates = []
    excluded = []
    rows = sorted(
        [p for p in store.proposals.values()
         if p["solicitation_id"] == solicitation["id"]],
        key=lambda r: (r["created_at"], r["_seq"]),
    )
    for proposal in rows:
        carrier = store.carriers.get(proposal["carrier_id"])
        if (proposal["submission_state"] == "SUBMITTED"
                and proposal["evaluation_state"] == "UNDER_EVALUATION"
                and carrier is not None
                and carrier["status"] in ("ACTIVE", "PROBATION")):
            candidates.append(proposal)
        else:
            excluded.append(proposal)
    return candidates, excluded


def _current_filing_rows(solicitation):
    sequence = solicitation["preference_filing_count"]
    if sequence <= 0:
        return []
    return [p for p in store.preferences.values()
            if p["solicitation_id"] == solicitation["id"]
            and p["filing_sequence"] == sequence]


def score_candidates(solicitation, community, candidates):
    """Returns {proposal_id: composite_score} plus the per-component detail."""
    scores = {}
    if not candidates:
        return scores
    best_spp = min(dec(p["subsidy_per_passenger_usd"]) for p in candidates)
    current = _current_filing_rows(solicitation)
    total_rows = len(current)
    rank_by_proposal = {row["proposal_id"]: row["rank"] for row in current}
    min_rt = dec(community["min_required_weekly_round_trips"])

    for proposal in candidates:
        own_spp = dec(proposal["subsidy_per_passenger_usd"])
        subsidy_points = q4(Decimal("100") * best_spp / own_spp)
        ratio = dec(proposal["weekly_round_trips"]) / min_rt
        if ratio > Decimal("1"):
            ratio = Decimal("1")
        service_points = q4(Decimal("100") * ratio)

        if total_rows == 0 or proposal["id"] not in rank_by_proposal:
            preference_points = Decimal("0.0000")
        else:
            rank = rank_by_proposal[proposal["id"]]
            preference_points = q4(
                Decimal("100") * dec(total_rows - rank + 1) / dec(total_rows)
            )

        composite = q4(
            WEIGHT_PREFERENCE * preference_points
            + WEIGHT_SUBSIDY * subsidy_points
            + WEIGHT_SERVICE * service_points
        )
        scores[proposal["id"]] = {
            "preference_points": preference_points,
            "subsidy_points": subsidy_points,
            "service_points": service_points,
            "composite_score": composite,
        }
    return scores


def rank_candidates(candidates, scores):
    """Sort by composite DESC, request ASC, round trips DESC, created_at ASC."""
    return sorted(
        candidates,
        key=lambda p: (
            -scores[p["id"]]["composite_score"],
            dec(p["annual_subsidy_request_usd"]),
            -dec(p["weekly_round_trips"]),
            p["created_at"],
            p["_seq"],
        ),
    )


# =========================================================================
# calculations.subsidy_payment_amount
# =========================================================================
def payment_amounts(annual_subsidy_usd, period, variant):
    scheduled = period["scheduled_departures"]
    completed = period["completed_departures"]
    cancelled_carrier = period["cancelled_carrier_departures"]
    cancelled_weather = period["cancelled_weather_departures"]

    monthly_entitlement = q2(dec(annual_subsidy_usd) / Decimal("12"))
    if scheduled >= 1:
        per_departure_rate = q2(monthly_entitlement / dec(scheduled))
    else:
        per_departure_rate = Decimal("0.00")

    if variant == "COMPLETED_FLIGHT_PRORATION":
        weather_allowance = floor_int(
            dec(scheduled) * WEATHER_CREDIT_ALLOWANCE_PCT / Decimal("100"))
        credited = completed + min(cancelled_weather, weather_allowance)
        gross = q2(per_departure_rate * dec(credited))
    else:
        credited = 0
        gross = q2(monthly_entitlement - per_departure_rate * dec(cancelled_carrier))

    carrier_allowance = floor_int(
        dec(scheduled) * CARRIER_CANCEL_ALLOWANCE_PCT / Decimal("100"))
    excess_carrier = cancelled_carrier - carrier_allowance
    if excess_carrier < 0:
        excess_carrier = 0
    adjustment = q2(per_departure_rate * dec(excess_carrier) * CANCELLATION_PENALTY_RATE)
    adjustment_cap = q2(monthly_entitlement * ADJUSTMENT_CAP_PCT)

    factor = period.get("period_completion_factor")
    factor = dec(factor) if factor is not None else Decimal("0")
    if factor >= Decimal("0.9500"):
        withholding_pct = Decimal("0.00")
    elif factor >= Decimal("0.9000"):
        withholding_pct = Decimal("0.02")
    elif factor >= Decimal("0.8500"):
        withholding_pct = Decimal("0.05")
    else:
        withholding_pct = Decimal("0.10")

    withholding = q2((gross - adjustment) * withholding_pct)
    net = q2(gross - adjustment - withholding)

    return {
        "variant_used": variant,
        "monthly_entitlement_usd": monthly_entitlement,
        "per_departure_rate_usd": per_departure_rate,
        "credited_departures": credited,
        "gross_subsidy_usd": gross,
        "cancellation_adjustment_usd": adjustment,
        "adjustment_cap_usd": adjustment_cap,
        "withholding_pct": withholding_pct,
        "performance_withholding_usd": withholding,
        "net_payment_usd": net,
    }


# =========================================================================
# calculations.hold_in_premium
# =========================================================================
def hold_in_premium(net_payment_usd):
    base = dec(net_payment_usd)
    if base >= HOLD_IN_TIER_HIGH_USD:
        rate = Decimal("0.03")
    elif base >= HOLD_IN_TIER_MID_USD:
        rate = Decimal("0.05")
    else:
        rate = Decimal("0.08")
    premium = q2(base * rate)
    return premium, q2(base + premium)


# =========================================================================
# calculations.carrier_completion_factor + carrier_performance_scoring
# =========================================================================
def review_periods(agreement_id, start_month, end_month):
    rows = [p for p in store.periods.values()
            if p["agreement_id"] == agreement_id
            and start_month <= p["period_month"] <= end_month
            and p["status"] in ("CERTIFIED", "PAID")]
    return sorted(rows, key=lambda r: (r["period_month"], r["_seq"]))


def review_figures(agreement, basis, start_month, end_month):
    periods = review_periods(agreement["id"], start_month, end_month)
    sum_scheduled = sum(p["scheduled_departures"] for p in periods)
    sum_completed = sum(p["completed_departures"] for p in periods)
    sum_weather = sum(p["cancelled_weather_departures"] for p in periods)
    sum_seats = sum(p["seats_offered"] for p in periods)
    sum_pax = sum(p["passengers_enplaned"] for p in periods)

    if sum_scheduled == 0:
        errors.fail(errors.ERR_NO_SCHEDULED_DEPARTURES,
                    "The review window contains no scheduled departures.")

    if basis == "STRICT":
        denominator = sum_scheduled
    else:
        denominator = sum_scheduled - sum_weather
        if denominator == 0:
            errors.fail(errors.ERR_NO_SCHEDULED_DEPARTURES,
                        "The adjusted completion-factor denominator is zero.")
    completion_factor = q4(dec(sum_completed) / dec(denominator))

    if completion_factor >= TIER_COMPLIANT_MIN:
        tier = "COMPLIANT"
    elif completion_factor >= TIER_WATCH_MIN:
        tier = "WATCH"
    else:
        tier = "DEFICIENT"

    months = months_inclusive(start_month, end_month)
    seat_denominator = dec(agreement["min_monthly_seats"]) * dec(months)
    if seat_denominator > 0:
        seat_ratio = dec(sum_seats) / seat_denominator
        if seat_ratio > Decimal("1"):
            seat_ratio = Decimal("1")
        seat_fulfillment = q4(seat_ratio)
    else:
        seat_fulfillment = Decimal("1.0000")

    if sum_seats > 0:
        load_factor = q4(dec(sum_pax) / dec(sum_seats))
    else:
        load_factor = Decimal("0.0000")

    normalized_load = load_factor / TARGET_LOAD_FACTOR
    if normalized_load > Decimal("1"):
        normalized_load = Decimal("1")

    quality_score = q2(Decimal("100") * (
        QUALITY_WEIGHT_COMPLETION * completion_factor
        + QUALITY_WEIGHT_SEATS * seat_fulfillment
        + QUALITY_WEIGHT_LOAD * normalized_load
    ))

    return {
        "months_in_window": months,
        "included_period_count": len(periods),
        "sum_scheduled_departures": sum_scheduled,
        "sum_completed_departures": sum_completed,
        "sum_cancelled_weather_departures": sum_weather,
        "sum_seats_offered": sum_seats,
        "sum_passengers_enplaned": sum_pax,
        "completion_factor": completion_factor,
        "seat_fulfillment": seat_fulfillment,
        "load_factor": load_factor,
        "quality_score": quality_score,
        "tier": tier,
    }


# =========================================================================
# calculations.renegotiated_annual_subsidy
# =========================================================================
def renegotiation_figures(agreement, trigger_type, fuel_index_month,
                          documented_cost_increase_pct):
    rate_in_force = dec(agreement["annual_subsidy_usd"])
    current_fuel_index = None
    fuel_cost_delta = None

    if trigger_type == "FUEL_INDEX":
        index_row = None
        for row in store.fuel_indices.values():
            if row["index_month"] == fuel_index_month:
                index_row = row
                break
        if index_row is None:
            errors.fail(errors.ERR_MISSING_FUEL_INDEX,
                        "No fuel index has been published for %s." % fuel_index_month)
        baseline = agreement.get("baseline_fuel_index_usd")
        if baseline is None:
            errors.fail(errors.ERR_MISSING_FUEL_INDEX,
                        "The agreement has no baseline fuel index.")
        current_fuel_index = dec(index_row["price_per_gallon_usd"])
        aircraft = _agreement_aircraft_type(agreement)
        burn = dec(aircraft["fuel_burn_gal_per_hour"]) if aircraft else Decimal("0")
        annual_gallons = q2(dec(agreement["annual_block_hours"]) * burn)
        per_gallon_delta = q4(current_fuel_index - dec(baseline))
        fuel_cost_delta = q2(per_gallon_delta * annual_gallons)
        justified_delta = q2(fuel_cost_delta * FUEL_PASSTHROUGH_RATE)
    else:
        pct = dec(documented_cost_increase_pct)
        if pct < Decimal("0"):
            pct = Decimal("0")
        if pct > MAX_COST_INCREASE_PCT:
            pct = MAX_COST_INCREASE_PCT
        justified_delta = q2(rate_in_force * pct)

    capped = min(justified_delta, q2(rate_in_force * MAX_ANNUAL_INCREASE_PCT))
    floored = max(capped, q2(-rate_in_force * MAX_ANNUAL_DECREASE_PCT))
    ceiling = q2(rate_in_force + floored)

    return {
        "current_fuel_index_usd": current_fuel_index,
        "fuel_cost_delta_usd": fuel_cost_delta,
        "justified_delta_usd": justified_delta,
        "ceiling_annual_subsidy_usd": ceiling,
    }


def _agreement_aircraft_type(agreement):
    proposal = store.proposals.get(agreement.get("proposal_id"))
    if proposal is None:
        return None
    return store.aircraft_types.get(proposal.get("aircraft_type_id"))


def facial_cap(agreement):
    return q2(dec(agreement["annual_subsidy_usd"]) * REQUEST_FACIAL_CAP_MULTIPLE)
