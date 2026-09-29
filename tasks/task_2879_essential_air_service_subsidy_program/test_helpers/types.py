"""TypedDict shapes for request payloads and response resources.

Field names are transcribed verbatim from the PRD narratives.

Ten registers carry the full audit quartet id / created_at / updated_at /
version: Community, Carrier, AircraftType, Solicitation, Proposal,
ServiceAgreement, ServicePeriod, SubsidyPayment, TerminationPetition and
RateRenegotiation. The remaining four — FuelIndex, EligibilityDetermination,
CommunityPreference and PerformanceReview — are append-only and carry only
id and created_at.
"""

from typing import Any, Dict, List, Optional, TypedDict


# ─── Common resource property mixins ─────────────────────────────────

class VersionedResource(TypedDict, total=False):
    """A register row that may be mutated: carries the full audit quartet."""
    id: str
    created_at: str
    updated_at: str
    version: int


class AppendOnlyResource(TypedDict, total=False):
    """A register row that is written once and never mutated."""
    id: str
    created_at: str


# ─── Clock ───────────────────────────────────────────────────────────

class ClockSetPayload(TypedDict):
    to_iso8601: str


class ClockResource(TypedDict, total=False):
    current_utc: str


# ─── Communities ─────────────────────────────────────────────────────

class CommunityCreatePayload(TypedDict, total=False):
    code: str
    name: str
    state_code: str
    driving_miles_to_nearest_hub: float
    enplanements_prior_year: int
    min_required_weekly_round_trips: int
    min_required_weekly_seats: int


class CommunityResource(VersionedResource, total=False):
    code: str
    name: str
    state_code: str
    driving_miles_to_nearest_hub: float
    enplanements_prior_year: int
    min_required_weekly_round_trips: int
    min_required_weekly_seats: int
    status: str
    distance_band: Optional[str]
    subsidy_per_passenger_cap_usd: Optional[float]
    latest_determination_outcome: Optional[str]
    active_agreement_count: int


# ─── Eligibility determinations (append-only) ────────────────────────

class EligibilityDeterminationPayload(TypedDict, total=False):
    waiver_requested: bool


class EligibilityDeterminationResource(AppendOnlyResource, total=False):
    community_id: str
    outcome: str
    distance_band: str
    subsidy_per_passenger_cap_usd: Optional[float]
    avg_daily_enplanements: float
    waiver_requested: bool
    certified_by_user_id: str
    effective_at: str
    driving_miles_at_determination: float


# ─── Carriers ────────────────────────────────────────────────────────

class CarrierCreatePayload(TypedDict, total=False):
    name: str
    certificate_number: str


class CarrierResource(VersionedResource, total=False):
    name: str
    certificate_number: str
    status: str
    consecutive_watch_count: int
    latest_completion_factor: Optional[float]
    latest_quality_score: Optional[float]
    latest_performance_tier: Optional[str]


class CarrierStandingPayload(TypedDict, total=False):
    action: str
    note: str


# ─── Aircraft types ──────────────────────────────────────────────────

class AircraftTypeCreatePayload(TypedDict, total=False):
    code: str
    name: str
    seats: int
    is_jet: bool
    fuel_burn_gal_per_hour: float
    hourly_operating_cost_usd: float


class AircraftTypeResource(VersionedResource, total=False):
    code: str
    name: str
    seats: int
    is_jet: bool
    fuel_burn_gal_per_hour: float
    hourly_operating_cost_usd: float
    is_retired: bool


class AircraftTypeRetirePayload(TypedDict, total=False):
    note: str


# ─── Fuel indices (append-only) ──────────────────────────────────────

class FuelIndexCreatePayload(TypedDict, total=False):
    index_month: str
    price_per_gallon_usd: float


class FuelIndexResource(AppendOnlyResource, total=False):
    index_month: str
    price_per_gallon_usd: float


# ─── Solicitations ───────────────────────────────────────────────────

class SolicitationCreatePayload(TypedDict, total=False):
    community_id: str
    closes_at: str


class SolicitationResource(VersionedResource, total=False):
    community_id: str
    closes_at: str
    status: str
    round_number: int
    created_reason: str
    preference_filing_count: int
    selected_proposal_id: Optional[str]
    candidate_count_at_award: Optional[int]


class SolicitationActionPayload(TypedDict, total=False):
    action: str
    note: str


class PreferenceRankingEntry(TypedDict, total=False):
    proposal_id: str
    rank: int


class PreferenceFilingPayload(TypedDict, total=False):
    expected_solicitation_version: int
    rankings: List[PreferenceRankingEntry]
    rationale: str


class CommunityPreferenceResource(AppendOnlyResource, total=False):
    solicitation_id: str
    proposal_id: str
    rank: int
    filing_sequence: int
    filed_by_user_id: str
    rationale: str


class SelectionOrderPayload(TypedDict, total=False):
    order_note: str


class RankingPreviewResource(TypedDict, total=False):
    candidate_count: int
    top_proposal_id: Optional[str]
    top_composite_score: Optional[float]
    ranked_proposal_ids: List[str]
    excluded_proposal_ids: List[str]


# ─── Proposals ───────────────────────────────────────────────────────

class ProposalCreatePayload(TypedDict, total=False):
    solicitation_id: str
    carrier_id: str
    aircraft_type_id: str
    service_level: str
    weekly_round_trips: int
    seats_per_departure: int
    annual_subsidy_request_usd: float
    term_months: int
    payment_basis: str


class ProposalResource(VersionedResource, total=False):
    solicitation_id: str
    carrier_id: str
    aircraft_type_id: str
    service_level: str
    weekly_round_trips: int
    seats_per_departure: int
    annual_subsidy_request_usd: float
    term_months: int
    payment_basis: str
    submission_state: str
    evaluation_state: str
    projected_annual_passengers: int
    subsidy_per_passenger_usd: float
    composite_score: Optional[float]


class ProposalActionPayload(TypedDict, total=False):
    action: str
    note: str


# ─── Service agreements ──────────────────────────────────────────────

class ServiceAgreementResource(VersionedResource, total=False):
    community_id: str
    carrier_id: str
    proposal_id: str
    status: str
    annual_subsidy_usd: float
    term_months: int
    payment_basis: str
    min_weekly_round_trips: int
    min_monthly_seats: int
    annual_block_hours: float
    baseline_fuel_index_usd: float
    rate_effective_from: str
    rate_effective_to: str
    total_committed_usd: float
    disbursed_to_date_usd: float
    obligated_remaining_usd: float
    hold_in_premium_paid_usd: float
    cumulative_scheduled_departures: int
    cumulative_completed_departures: int
    cumulative_cancelled_carrier_departures: int
    cumulative_cancelled_weather_departures: int
    predecessor_agreement_id: Optional[str]
    terminated_at: Optional[str]


class AgreementStatusActionPayload(TypedDict, total=False):
    action: str
    note: str


# ─── Service periods ─────────────────────────────────────────────────

class ServicePeriodCreatePayload(TypedDict, total=False):
    agreement_id: str
    period_month: str


class ServicePeriodResource(VersionedResource, total=False):
    agreement_id: str
    period_month: str
    status: str
    scheduled_departures: int
    completed_departures: int
    cancelled_carrier_departures: int
    cancelled_weather_departures: int
    seats_offered: int
    passengers_enplaned: int
    period_completion_factor: Optional[float]
    amendment_count: int


class ServicePeriodReportPayload(TypedDict, total=False):
    scheduled_departures: int
    completed_departures: int
    cancelled_carrier_departures: int
    cancelled_weather_departures: int
    seats_offered: int
    passengers_enplaned: int


class ServicePeriodAmendPayload(ServicePeriodReportPayload, total=False):
    expected_agreement_version: int


class PaymentPreviewResource(TypedDict, total=False):
    completed_flight_proration_net_usd: float
    scheduled_flight_flat_net_usd: float
    variant_in_effect: str
    divergence_usd: float
    per_departure_rate_usd: float
    credited_departures: int


class CertifyPayload(TypedDict, total=False):
    certification_note: str


# ─── Subsidy payments ────────────────────────────────────────────────

class SubsidyPaymentResource(VersionedResource, total=False):
    service_period_id: str
    status: str
    variant_used: str
    monthly_entitlement_usd: float
    per_departure_rate_usd: float
    credited_departures: int
    gross_subsidy_usd: float
    cancellation_adjustment_usd: float
    withholding_pct: float
    performance_withholding_usd: float
    net_payment_usd: float
    hold_in_premium_usd: float
    total_disbursement_usd: float
    approved_by_user_id: Optional[str]
    disbursed_by_user_id: Optional[str]
    reversal_reason_code: Optional[str]


class PaymentActionPayload(TypedDict, total=False):
    action: str
    reversal_reason_code: str


# ─── Performance reviews (append-only) ───────────────────────────────

class PerformanceReviewPayload(TypedDict, total=False):
    agreement_id: str
    basis: str
    window_start_month: str
    window_end_month: str


class PerformanceReviewResource(AppendOnlyResource, total=False):
    agreement_id: str
    basis: str
    window_start_month: str
    window_end_month: str
    months_in_window: int
    included_period_count: int
    sum_scheduled_departures: int
    sum_completed_departures: int
    sum_cancelled_weather_departures: int
    sum_seats_offered: int
    sum_passengers_enplaned: int
    completion_factor: float
    tier: str
    seat_fulfillment: float
    load_factor: float
    quality_score: float
    action_taken: str
    reviewed_by_user_id: str


# ─── Termination petitions ───────────────────────────────────────────

class TerminationPetitionCreatePayload(TypedDict, total=False):
    community_id: str
    agreement_id: str
    reason_code: str
    narrative: str
    requested_effective_at: str


class TerminationPetitionResource(VersionedResource, total=False):
    community_id: str
    agreement_id: str
    reason_code: str
    narrative: str
    requested_effective_at: str
    status: str
    return_count: int
    filed_by_user_id: str
    decided_by_user_id: Optional[str]
    decision_note: Optional[str]


class PetitionDecisionPayload(TypedDict, total=False):
    action: str
    decision_note: str


class PetitionWithdrawPayload(TypedDict, total=False):
    withdraw_note: str


# ─── Rate renegotiations ─────────────────────────────────────────────

class RateRenegotiationCreatePayload(TypedDict, total=False):
    agreement_id: str
    trigger_type: str
    requested_annual_subsidy_usd: float
    justification: str
    fuel_index_month: str
    documented_cost_increase_pct: float


class RateRenegotiationResource(VersionedResource, total=False):
    agreement_id: str
    trigger_type: str
    status: str
    fuel_index_month: Optional[str]
    documented_cost_increase_pct: Optional[float]
    current_fuel_index_usd: Optional[float]
    fuel_cost_delta_usd: Optional[float]
    justified_delta_usd: float
    ceiling_annual_subsidy_usd: float
    requested_annual_subsidy_usd: float
    countered_annual_subsidy_usd: Optional[float]
    approved_annual_subsidy_usd: Optional[float]
    revision_count: int
    effective_at: Optional[str]


class RenegotiationActionPayload(TypedDict, total=False):
    action: str
    revised_annual_subsidy_usd: float
    action_note: str


# ─── Convenience aliases ─────────────────────────────────────────────

Json = Dict[str, Any]
