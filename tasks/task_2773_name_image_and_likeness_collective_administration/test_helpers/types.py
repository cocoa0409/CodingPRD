"""TypedDict shapes for every resource the NIL Collective Administration API returns.

Field sets follow PRD s2.4: collectives, membership tiers, donor members,
commitments, contributions, athletes, deal contracts, deliverables and payment
releases all carry ``updated_at`` and ``version``; the communication log carries
only ``id`` and ``created_at`` because it is append-only, so its shape below has
neither ``updated_at`` nor ``version``. Every entity type except the collective
carries ``sequence_no``.
"""

from typing import List, Optional, TypedDict


class Collective(TypedDict):
    id: str
    name: str
    institution_name: str
    institution_ipeds_code: str
    home_state_code: str
    association_ruleset: str
    entity_structure: str
    communication_policy: str
    charitable_deduction_enabled: bool
    structure_effective_at: Optional[str]
    structure_change_count: int
    funding_posture: str
    settled_net_funds_cents: int
    committed_unreleased_cents: int
    released_total_cents: int
    reversed_total_cents: int
    created_at: str
    updated_at: str
    version: int


class MembershipTier(TypedDict):
    id: str
    collective_id: str
    tier_code: str
    tier_name: str
    annual_dues_cents: int
    benefit_rank: int
    tier_status: str
    active_commitment_count: int
    sequence_no: int
    created_at: str
    updated_at: str
    version: int


class DonorMember(TypedDict):
    id: str
    collective_id: str
    membership_tier_id: str
    display_name: str
    email: str
    donor_kind: str
    annual_agi_cents: int
    status: str
    lifetime_settled_cents: int
    lifetime_deductible_cents: int
    sequence_no: int
    created_at: str
    updated_at: str
    version: int


class Commitment(TypedDict):
    id: str
    donor_member_id: str
    kind: str
    amount_cents: int
    billing_interval: str
    installments_total: int
    installments_charged: int
    status: str
    pause_reason: str
    superseded_by_commitment_id: Optional[str]
    sequence_no: int
    created_at: str
    updated_at: str
    version: int


class Contribution(TypedDict):
    id: str
    donor_member_id: str
    commitment_id: Optional[str]
    gross_amount_cents: int
    processing_fee_cents: int
    net_amount_cents: int
    deductible_amount_cents: int
    deduction_variant: str
    source_kind: str
    designation: str
    status: str
    received_at: str
    sequence_no: int
    created_at: str
    updated_at: str
    version: int


class Athlete(TypedDict):
    id: str
    collective_id: str
    full_name: str
    portal_user_id: str
    sport: str
    class_year: int
    roster_weight: int
    eligibility_status: str
    tax_person_kind: str
    taxpayer_doc_on_file: str
    treaty_exempt_claimed: bool
    annual_committed_value_cents: int
    tax_year_gross_paid_cents: int
    tax_year_withheld_cents: int
    tax_form_required: str
    sequence_no: int
    created_at: str
    updated_at: str
    version: int


class DealContract(TypedDict):
    id: str
    collective_id: str
    athlete_id: str
    deal_kind: str
    allocation_batch_code: Optional[str]
    total_value_cents: int
    effective_start_at: str
    effective_end_at: str
    funding_designation: str
    exclusivity_category: str
    lifecycle_status: str
    payment_status: str
    disclosure_status: str
    disclosure_due_at: Optional[str]
    disclosure_submitted_at: Optional[str]
    disclosure_return_count: int
    released_total_cents: int
    deliverable_value_total_cents: int
    clawback_amount_cents: int
    termination_reason: str
    sequence_no: int
    created_at: str
    updated_at: str
    version: int


class EvidenceRecord(TypedDict):
    evidence_kind: str
    reference_label: str
    recorded_at: str
    sequence_no: int


class Deliverable(TypedDict):
    id: str
    deal_contract_id: str
    deliverable_kind: str
    unit_value_cents: int
    due_at: str
    required_charity_hours_tenths: int
    charity_hours_tenths: int
    status: str
    evidence_records: List[EvidenceRecord]
    evidence_count: int
    submission_count: int
    late_flag: bool
    performed_at: Optional[str]
    submitted_at: Optional[str]
    verified_by_user_id: Optional[str]
    verified_at: Optional[str]
    payout_basis: Optional[str]
    payout_eligible_cents: int
    sequence_no: int
    created_at: str
    updated_at: str
    version: int


class PaymentRelease(TypedDict):
    id: str
    deal_contract_id: str
    deliverable_id: Optional[str]
    release_kind: str
    requested_amount_cents: int
    withholding_basis: str
    withholding_amount_cents: int
    net_payable_cents: int
    status: str
    initiated_by_user_id: str
    released_at: Optional[str]
    reversal_reason: str
    sequence_no: int
    created_at: str
    updated_at: str
    version: int


class CommunicationLog(TypedDict):
    """Append-only touchpoint record: no ``updated_at`` and no ``version`` (PRD s2.4)."""

    id: str
    collective_id: str
    athlete_id: Optional[str]
    actor_role: str
    channel: str
    topic: str
    note: Optional[str]
    verdict: str
    rationale_code: str
    logged_at: str
    sequence_no: int
    created_at: str


class BillingRunReport(TypedDict):
    """The billing-run response is a report rather than an entity (PRD s3.6)."""

    run_kind: str
    executed_at: str
    charged_commitment_count: int
    settled_contribution_count: int
    failed_contribution_count: int
    recomputed_contribution_count: int
    deduction_delta_cents: int


class RosterAllocationReport(TypedDict):
    """The roster batch response summarises the division (PRD s3.8)."""

    allocation_batch_code: str
    created_contract_count: int
    allocated_total_cents: int
    remainder_cents: int
    min_share_cents: int
    max_share_cents: int


class ClockReading(TypedDict):
    current_utc: str
    previous_utc: str
