"""Entity shapes and lifecycle-state constants."""
from typing import List, TypedDict

from .constants import (
    ActivationChannel,
    ActivationStatus,
    AddOnStatus,
    AddOnType,
    AgreementStatus,
    AllocationStatus,
    CaseStatus,
    CycleStatus,
    EscalationReason,
    InventoryStatus,
    PartnerStatus,
    PlanStatus,
    PortStatus,
    SimMediaType,
    SubscriberStatus,
    TermStatus,
    TopicCode,
    UserRole,
    VoidReason,
)

__all__ = [
    "ActivationChannel",
    "ActivationStatus",
    "AddOnStatus",
    "AddOnType",
    "AgreementStatus",
    "AllocationStatus",
    "CaseStatus",
    "CycleStatus",
    "EscalationReason",
    "InventoryStatus",
    "PartnerStatus",
    "PlanStatus",
    "PortStatus",
    "SimMediaType",
    "SubscriberStatus",
    "TermStatus",
    "TopicCode",
    "UserRole",
    "VoidReason",
]


# --- CapacityAgreement / Plan / Subscriber: id + created_at + updated_at + version ---

class CapacityAgreement(TypedDict, total=False):
    id: str
    host_network_name: str
    state_code: str
    data_rate_microcents_per_mb: int
    voice_rate_microcents_per_min: int
    sms_rate_microcents_per_msg: int
    committed_data_mb: int
    committed_voice_minutes: int
    committed_sms_messages: int
    agreement_status: str
    congestion_active: bool
    congestion_index: int
    allocated_data_mb: int
    remaining_data_mb: int
    resolved_purchase_cost_microcents: int
    created_at: str
    updated_at: str
    version: int


class Plan(TypedDict, total=False):
    id: str
    agreement_id: str
    plan_code: str
    term_months: int
    intro_price_cents: int
    renewal_price_cents: int
    data_allotment_mb: int
    voice_allotment_min: int
    sms_allotment_msg: int
    deprioritization_threshold_mb: int
    plan_status: str
    created_at: str
    updated_at: str
    version: int


class Subscriber(TypedDict, total=False):
    id: str
    msisdn: str
    full_name: str
    state_code: str
    subscriber_status: str
    allocation_status: str
    cycle_index: int
    cycles_rolled: int
    data_used_mb_cycle: int
    deprioritized_this_cycle: bool
    cycle_deprioritization_days: int
    support_seconds_used: int
    support_seconds_budget: int
    self_service_deflection_count: int
    created_at: str
    updated_at: str
    version: int


class PrepaidTerm(TypedDict, total=False):
    id: str
    subscriber_id: str
    plan_id: str
    term_status: str
    term_price_cents: int
    starts_at: str
    expires_at: str
    deferred_revenue_cents: int
    earned_revenue_cents: int
    breakage_days: int
    breakage_cents_recognized: int
    void_reason: str
    created_at: str
    updated_at: str
    version: int


class Activation(TypedDict, total=False):
    id: str
    subscriber_id: str
    prepaid_term_id: str
    retail_partner_id: str
    activation_channel: str
    activation_status: str
    port_status: str
    porting_msisdn: str
    losing_carrier: str
    account_number_last4: str
    rejection_code: str
    held_data_mb: int
    provisioned_msisdn: str
    accepted_msisdn: str
    created_at: str
    updated_at: str
    version: int


class RetailPartner(TypedDict, total=False):
    id: str
    partner_name: str
    partner_status: str
    partner_state_codes: List[str]
    shipment_sla_days: int
    created_at: str
    updated_at: str
    version: int


class SimInventory(TypedDict, total=False):
    id: str
    retail_partner_id: str
    reserved_for_activation_id: str
    sim_media_type: str
    state_code: str
    unit_count: int
    inventory_status: str
    reserved_count: int
    shipment_channel: str
    units_shipped: int
    shipment_sla_days: int
    created_at: str
    updated_at: str
    version: int


class SupportCase(TypedDict, total=False):
    id: str
    subscriber_id: str
    topic_code: str
    case_status: str
    handling_seconds: int
    sla_due_at: str
    escalation_reason: str
    created_at: str
    updated_at: str
    version: int


class AddOn(TypedDict, total=False):
    id: str
    subscriber_id: str
    addon_type: str
    addon_status: str
    addon_price_cents: int
    per_day_allotment_mb: int
    addon_days: int
    start_at: str
    end_at: str
    deprovisioned_msisdn: str
    created_at: str
    updated_at: str
    version: int


# --- CycleRecord is the one immutable row: it carries ONLY id and created_at ---

class CycleRecord(TypedDict, total=False):
    id: str
    prepaid_term_id: str
    cycle_index: int
    cycle_status: str
    opened_at: str
    closed_at: str
    cycle_data_used_mb: int
    cycle_deprioritization_days: int
    earned_cents: int
    created_at: str


class UsageSummary(TypedDict, total=False):
    as_incurred_cost_microcents: int
    as_incurred_overage_cost_microcents: int
    committed_volume_cost_microcents: int
    data_volume_cost_microcents: int
    retroactive_volume_cost_microcents: int
    allocated_data_mb: int
    remaining_data_mb: int
    breakage_rate_ppm: int
    congestion_index: int
    congestion_active: bool


class ResolvedPurchase(TypedDict, total=False):
    resolved_purchase_cost_microcents: int
    projected_overage_data_mb: int
    projected_overage_cost_microcents: int
    committed_volume_cost_microcents: int
    monthly_committed_cost_microcents: int
    data_volume_cost_microcents: int
    marginal_tier_rate_microcents: int