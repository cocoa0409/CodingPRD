"""Typed views of the resources the service persists.

Mutable resources carry id / created_at / updated_at / version. The two resource
kinds the PRD declares immutable — a channel's surcharge rules and an offer's
priced lines — carry ONLY id and created_at, so their TypedDicts deliberately
omit updated_at and version.
"""

from typing import Any, Dict, List, Optional, TypedDict


class MutableResource(TypedDict):
    """Common fields of every mutable resource (PRD 2.4)."""

    id: str
    created_at: str
    updated_at: str
    version: int


class ImmutableResource(TypedDict):
    """Common fields of the two immutable resource kinds (PRD 2.4)."""

    id: str
    created_at: str


class Channel(MutableResource, total=False):
    channel_code: str
    channel_kind: str
    content_tier: str
    content_tier_rank: int
    content_markup_pct: float
    incentive_multiplier: float
    monthly_platform_fee_cents: int
    per_message_cost_cents: int
    per_segment_fee_cents: int
    servicing_parity_change: bool
    servicing_parity_refund: bool
    required_disclosure_codes: List[str]
    booking_count: int
    activity_cost_cents: int
    cost_per_booking_flat_cents: int
    cost_per_booking_activity_cents: int


class SurchargeRule(ImmutableResource, total=False):
    channel_id: str
    surcharge_code: str
    item_scope: str
    rate_pct: float
    threshold_cents: int
    min_cents: int
    max_cents: int


class DistributionPartner(MutableResource, total=False):
    partner_name: str
    partner_type: str
    iata_code: str
    home_country: str
    certification_status: str


class FareFiling(MutableResource, total=False):
    fare_basis_code: str
    origin: str
    destination: str
    cabin: str
    base_amount_cents: int
    sale_from: str
    sale_to: str
    travel_from: str
    travel_to: str
    min_content_tier_rank: int
    refundable: bool
    is_private: bool
    status: str
    revision_number: int
    base_filing_id: Optional[str]
    filed_by_user_id: str


class AncillaryProduct(MutableResource, total=False):
    ancillary_code: str
    name: str
    list_amount_cents: int
    min_content_tier_rank: int
    refundable: bool


class BundleDefinition(MutableResource, total=False):
    bundle_code: str
    ancillary_codes: List[str]
    bundle_discount_pct: float
    min_content_tier_rank: int


class AgencyAgreement(MutableResource, total=False):
    partner_id: str
    channel_id: str
    status: str
    proposed_incentive_pct: float
    agreed_incentive_pct: Optional[float]
    incentive_cap_cents: int
    target_net_revenue_cents: int
    negotiation_round: int
    proposed_by_user_id: str
    signed_by_user_id: Optional[str]
    cumulative_net_revenue_cents: int
    incentive_accrued_cents: int
    incentive_tier: str
    tier_downgrade_count: int


class CorporateContract(MutableResource, total=False):
    corporate_partner_id: str
    negotiated_fare_filing_id: str
    account_code: str
    max_offer_total_cents: int
    traceability_required: bool
    tracking_ref_prefix: str
    min_content_tier_rank: int
    effective_from: str
    effective_to: str
    validity_state: str


class Offer(MutableResource, total=False):
    channel_id: str
    partner_id: str
    fare_filing_id: str
    bundle_id: Optional[str]
    corporate_contract_id: Optional[str]
    trip_origin: str
    trip_destination: str
    departure_date: str
    cabin: str
    status: str
    subtotal_cents: int
    surcharge_cents: int
    total_cents: int
    item_count: int
    expires_at: str
    priced_channel_version: int
    acknowledged_disclosure_codes: List[str]
    disclosure_complete: bool


class OfferItem(ImmutableResource, total=False):
    offer_id: str
    sequence: int
    item_type: str
    item_code: str
    list_amount_cents: int
    net_amount_cents: int
    refundable: bool


class Order(MutableResource, total=False):
    offer_id: str
    channel_id: str
    partner_id: str
    agency_agreement_id: Optional[str]
    corporate_tracking_ref: Optional[str]
    payment_status: str
    fulfillment_status: str
    net_revenue_cents: int
    paid_amount_cents: int
    refunded_amount_cents: int
    message_count: int
    segment_count: int


class ServiceRequest(MutableResource, total=False):
    order_id: str
    request_type: str
    status: str
    requested_change_note: Optional[str]
    submitted_by_user_id: str
    reviewed_by_user_id: Optional[str]
    refundable_base_cents: int
    cancellation_fee_cents: int
    refund_total_cents: int
    incentive_clawback_cents: int


class PartnerCertification(MutableResource, total=False):
    partner_id: str
    channel_id: str
    env_code: str
    status: str
    reserved_test_minutes: int
    readiness_score_strict: int
    readiness_score_provisional: int
    mandatory_failed_count: int
    certified_variant: Optional[str]
    tested_by_user_id: str


class ConnectivityTest(MutableResource, total=False):
    certification_id: str
    test_code: str
    is_mandatory: bool
    scheduled_start: str
    scheduled_end: str
    duration_minutes: int
    status: str
    score: Optional[int]


Payload = Dict[str, Any]
Headers = Dict[str, str]
