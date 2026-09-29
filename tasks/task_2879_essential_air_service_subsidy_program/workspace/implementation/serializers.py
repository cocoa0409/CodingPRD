"""Response projections for the fourteen registers (PRD section 2.4).

Ten registers carry ``updated_at`` and ``version``; the four append-only
registers (FuelIndex, EligibilityDetermination, CommunityPreference,
PerformanceReview) carry neither.
"""


def _pick(row, fields, versioned):
    out = {"id": row["id"]}
    for name in fields:
        out[name] = row.get(name)
    out["created_at"] = row["created_at"]
    if versioned:
        out["updated_at"] = row["updated_at"]
        out["version"] = row["version"]
    return out


COMMUNITY_FIELDS = (
    "code", "name", "state_code", "driving_miles_to_nearest_hub",
    "enplanements_prior_year", "min_required_weekly_round_trips",
    "min_required_weekly_seats", "status", "distance_band",
    "subsidy_per_passenger_cap_usd", "latest_determination_outcome",
    "active_agreement_count",
)

CARRIER_FIELDS = (
    "name", "certificate_number", "status", "latest_completion_factor",
    "latest_quality_score", "latest_performance_tier", "consecutive_watch_count",
)

AIRCRAFT_TYPE_FIELDS = (
    "code", "name", "seats", "is_jet", "fuel_burn_gal_per_hour",
    "hourly_operating_cost_usd", "is_retired",
)

FUEL_INDEX_FIELDS = ("index_month", "price_per_gallon_usd")

DETERMINATION_FIELDS = (
    "community_id", "waiver_requested", "driving_miles_at_determination",
    "avg_daily_enplanements", "distance_band", "subsidy_per_passenger_cap_usd",
    "outcome", "certified_by_user_id", "effective_at",
)

SOLICITATION_FIELDS = (
    "community_id", "closes_at", "round_number", "created_reason", "status",
    "preference_filing_count", "selected_proposal_id", "candidate_count_at_award",
)

PROPOSAL_FIELDS = (
    "solicitation_id", "carrier_id", "aircraft_type_id", "service_level",
    "weekly_round_trips", "seats_per_departure", "annual_subsidy_request_usd",
    "term_months", "payment_basis", "projected_annual_passengers",
    "subsidy_per_passenger_usd", "submission_state", "evaluation_state",
    "composite_score",
)

PREFERENCE_FIELDS = (
    "solicitation_id", "proposal_id", "rank", "filing_sequence", "rationale",
    "filed_by_user_id",
)

AGREEMENT_FIELDS = (
    "community_id", "carrier_id", "proposal_id", "predecessor_agreement_id",
    "min_weekly_round_trips", "min_monthly_seats", "annual_subsidy_usd",
    "payment_basis", "term_months", "rate_effective_from", "rate_effective_to",
    "baseline_fuel_index_usd", "annual_block_hours", "total_committed_usd",
    "disbursed_to_date_usd", "obligated_remaining_usd", "hold_in_premium_paid_usd",
    "cumulative_scheduled_departures", "cumulative_completed_departures",
    "cumulative_cancelled_carrier_departures",
    "cumulative_cancelled_weather_departures", "status", "terminated_at",
)

PERIOD_FIELDS = (
    "agreement_id", "period_month", "scheduled_departures",
    "completed_departures", "cancelled_carrier_departures",
    "cancelled_weather_departures", "seats_offered", "passengers_enplaned",
    "period_completion_factor", "status", "amendment_count",
)

PAYMENT_FIELDS = (
    "service_period_id", "variant_used", "monthly_entitlement_usd",
    "per_departure_rate_usd", "credited_departures", "gross_subsidy_usd",
    "cancellation_adjustment_usd", "withholding_pct",
    "performance_withholding_usd", "net_payment_usd", "hold_in_premium_usd",
    "total_disbursement_usd", "status", "approved_by_user_id",
    "disbursed_by_user_id", "reversal_reason_code",
)

REVIEW_FIELDS = (
    "agreement_id", "basis", "window_start_month", "window_end_month",
    "months_in_window", "included_period_count", "sum_scheduled_departures",
    "sum_completed_departures", "sum_cancelled_weather_departures",
    "sum_seats_offered", "sum_passengers_enplaned", "completion_factor",
    "seat_fulfillment", "load_factor", "quality_score", "tier", "action_taken",
    "reviewed_by_user_id",
)

PETITION_FIELDS = (
    "community_id", "agreement_id", "reason_code", "narrative",
    "requested_effective_at", "status", "return_count", "decision_note",
    "decided_by_user_id", "filed_by_user_id",
)

RENEGOTIATION_FIELDS = (
    "agreement_id", "trigger_type", "fuel_index_month",
    "documented_cost_increase_pct", "requested_annual_subsidy_usd",
    "justification", "current_fuel_index_usd", "fuel_cost_delta_usd",
    "justified_delta_usd", "ceiling_annual_subsidy_usd",
    "countered_annual_subsidy_usd", "approved_annual_subsidy_usd",
    "revision_count", "status", "effective_at",
)


def community(row):
    return _pick(row, COMMUNITY_FIELDS, True)


def carrier(row):
    return _pick(row, CARRIER_FIELDS, True)


def aircraft_type(row):
    return _pick(row, AIRCRAFT_TYPE_FIELDS, True)


def fuel_index(row):
    return _pick(row, FUEL_INDEX_FIELDS, False)


def determination(row):
    return _pick(row, DETERMINATION_FIELDS, False)


def solicitation(row):
    return _pick(row, SOLICITATION_FIELDS, True)


def proposal(row):
    return _pick(row, PROPOSAL_FIELDS, True)


def preference(row):
    return _pick(row, PREFERENCE_FIELDS, False)


def agreement(row):
    return _pick(row, AGREEMENT_FIELDS, True)


def period(row):
    return _pick(row, PERIOD_FIELDS, True)


def payment(row):
    return _pick(row, PAYMENT_FIELDS, True)


def review(row):
    return _pick(row, REVIEW_FIELDS, False)


def petition(row):
    return _pick(row, PETITION_FIELDS, True)


def renegotiation(row):
    return _pick(row, RENEGOTIATION_FIELDS, True)
