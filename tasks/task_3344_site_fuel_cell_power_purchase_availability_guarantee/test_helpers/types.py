"""Domain types: entity TypedDicts, status enums and the role enum."""
from enum import Enum
from typing import TypedDict, Optional


class SiteStatus(str, Enum):
    SITE_ACTIVE = "SITE_ACTIVE"
    SITE_SUSPENDED = "SITE_SUSPENDED"


class SiteLifecycleState(str, Enum):
    RESOURCE_AVAILABLE = "RESOURCE_AVAILABLE"
    RESOURCE_DRAWING = "RESOURCE_DRAWING"
    RESOURCE_CLOSED = "RESOURCE_CLOSED"


class CustomerStatus(str, Enum):
    CUSTOMER_ACTIVE = "CUSTOMER_ACTIVE"
    CUSTOMER_CREDIT_HOLD = "CUSTOMER_CREDIT_HOLD"
    CUSTOMER_SUSPENDED = "CUSTOMER_SUSPENDED"


class RenewalStage(str, Enum):
    RENEWAL_NONE = "RENEWAL_NONE"
    RENEWAL_OFFERED = "RENEWAL_OFFERED"
    RENEWAL_ACCEPTED = "RENEWAL_ACCEPTED"
    RENEWAL_DECLINED = "RENEWAL_DECLINED"


class CreditTier(str, Enum):
    CREDIT_PRIME = "CREDIT_PRIME"
    CREDIT_STANDARD = "CREDIT_STANDARD"
    CREDIT_SUBSTANDARD = "CREDIT_SUBSTANDARD"


class PpaState(str, Enum):
    PPA_DRAFT = "PPA_DRAFT"
    PPA_ACTIVE = "PPA_ACTIVE"
    PPA_SUSPENDED = "PPA_SUSPENDED"
    PPA_EXIT_PENDING = "PPA_EXIT_PENDING"
    PPA_TERMINATED = "PPA_TERMINATED"


class FuelResponsibility(str, Enum):
    PPA_FUEL_INCLUDED = "PPA_FUEL_INCLUDED"
    CUSTOMER_SOURCED_GAS = "CUSTOMER_SOURCED_GAS"


class ContractBasis(str, Enum):
    PPA_BASIS_AS_BUILT = "PPA_BASIS_AS_BUILT"
    PPA_BASIS_TRANSFERRED = "PPA_BASIS_TRANSFERRED"


class TransferStage(str, Enum):
    TRANSFER_NONE = "TRANSFER_NONE"
    TRANSFER_BLOCKED = "TRANSFER_BLOCKED"


class ServicePlanLifecycleState(str, Enum):
    SERVICE_PLAN_DRAFT = "SERVICE_PLAN_DRAFT"
    SERVICE_ACTIVE = "SERVICE_ACTIVE"
    SERVICE_MAINTENANCE_WINDOW_OPEN = "SERVICE_MAINTENANCE_WINDOW_OPEN"
    SERVICE_SUSPENDED = "SERVICE_SUSPENDED"
    SERVICE_ARCHIVED = "SERVICE_ARCHIVED"


class ModuleReplacementStage(str, Enum):
    REPLACEMENT_NONE = "REPLACEMENT_NONE"
    REPLACEMENT_SCHEDULED = "REPLACEMENT_SCHEDULED"
    REPLACEMENT_DISPATCHED = "REPLACEMENT_DISPATCHED"
    REPLACEMENT_BLOCKED = "REPLACEMENT_BLOCKED"


class RemoteMonitoringStatus(str, Enum):
    MONITORING_LINKED = "MONITORING_LINKED"
    MONITORING_DEGRADED = "MONITORING_DEGRADED"


class DeliveryLifecycleState(str, Enum):
    DELIVERY_SCHEDULED = "DELIVERY_SCHEDULED"
    DELIVERY_IN_TRANSIT = "DELIVERY_IN_TRANSIT"
    DELIVERY_CONFIRMED = "DELIVERY_CONFIRMED"
    DELIVERY_SETTLED = "DELIVERY_SETTLED"
    DELIVERY_CANCELLED = "DELIVERY_CANCELLED"


class SourcingMode(str, Enum):
    FIXED_PRICE_BLEND = "FIXED_PRICE_BLEND"
    INDEXED_BLEND = "INDEXED_BLEND"


class SettlementLineStatus(str, Enum):
    SETTLEMENT_DRAFT = "SETTLEMENT_DRAFT"
    SETTLEMENT_VALIDATED = "SETTLEMENT_VALIDATED"
    SETTLEMENT_APPROVED = "SETTLEMENT_APPROVED"
    SETTLEMENT_APPLIED = "SETTLEMENT_APPLIED"
    SETTLEMENT_REVERSED = "SETTLEMENT_REVERSED"


class AllocationBasis(str, Enum):
    ALLOCATION_ORDER = "ALLOCATION_ORDER"
    UNIT_INDEX = "UNIT_INDEX"


class AccrualType(str, Enum):
    CHARGE_ACCRUAL = "CHARGE_ACCRUAL"
    OUTPUT_GUARANTEE_ACCRUAL = "OUTPUT_GUARANTEE_ACCRUAL"
    TRUEUP_ACCRUAL = "TRUEUP_ACCRUAL"
    CAPACITY_ACCRUAL = "CAPACITY_ACCRUAL"


class AccrualLifecycleState(str, Enum):
    ACCRUAL_OPEN = "ACCRUAL_OPEN"
    ACCRUAL_RECONCILED = "ACCRUAL_RECONCILED"


class AllowanceKind(str, Enum):
    AVOIDED_COST_ALLOWANCE = "AVOIDED_COST_ALLOWANCE"
    CAPACITY_ALLOWANCE = "CAPACITY_ALLOWANCE"


class AllowanceLifecycleState(str, Enum):
    ALLOWANCE_ISSUED = "ALLOWANCE_ISSUED"
    ALLOWANCE_APPLIED = "ALLOWANCE_APPLIED"


class AppliedDirection(str, Enum):
    ALLOWANCE_APPLIED_AS_TIME = "ALLOWANCE_APPLIED_AS_TIME"
    ALLOWANCE_APPLIED_AS_REVERSAL = "ALLOWANCE_APPLIED_AS_REVERSAL"


class UserRole(str, Enum):
    SITE_OPERATOR = "SiteOperator"
    CUSTOMER = "Customer"
    CUSTOMER_SERVICE = "CustomerService"
    FUEL_COORDINATOR = "FuelCoordinator"
    SERVICE_ENGINEER = "ServiceEngineer"
    SETTLEMENT_ANALYST = "SettlementAnalyst"
    SETTLEMENT_APPROVER = "SettlementApprover"


# common_fields: true — carries id + created_at + updated_at + version
class Site(TypedDict):
    id: str
    name: str
    utility_territory: str
    grid_tariff_rate_cents_per_kwh: float
    grid_outage_events_per_year: int
    grid_annual_outage_hours: float
    gas_commodity_rate_cents_per_therm: float
    expected_annual_site_load_kwh: int
    tax_rate_pct: float
    status: str
    lifecycle_state: str
    active_ppa_count: int
    lifetime_customer_billable_cents: float
    lifetime_availability_credit_cents: float
    lifetime_settled_kwh: float
    total_contracted_kw: int
    contracted_purchase_cents: float
    committed_feedstock_therms: float
    initial_fuel_inventory_therms: float
    draw_position_therms: float
    current_avoided_fuel_cost_cents_per_therm: float
    lifetime_settle_reconcile_count: int
    allowed_downtime_hours_per_year: float
    reserved_capacity_hold_count: int
    clearance_zone_used: float
    clearance_zone_capacity: float
    footprint_sqm: float
    standby_charge_cents_per_kw_month: float
    interconnect_exit_fee_cents_per_kw: float
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    name: str
    industry_code: str
    credit_tier: str
    status: str
    renewal_stage: str
    outstanding_balance_cents: float
    lifetime_settled_cents: float
    lifetime_output_guarantee_credit_cents: float
    lifetime_availability_credit_cents: float
    active_ppa_count: int
    earned_customer_tokens: int
    spent_customer_tokens: int
    exposure_hold_pct: float
    hold_armed: bool
    reconcile_cadence_slots: int
    created_at: str
    updated_at: str
    version: int


class Ppa(TypedDict):
    id: str
    site_id: str
    customer_id: str
    term_years: int
    contracted_kw: int
    contracted_efficiency_kwh_per_therm: float
    contracted_annual_kwh: int
    tariff_base_cents_per_kwh: float
    escalator_pct: float
    fuel_adder_cents_per_therm: float
    guaranteed_availability_pct: float
    guaranteed_delivery_kwh: int
    customer_cure_deadline_days: int
    fuel_responsibility: str
    state: str
    state_entered_at: str
    effective_tariff_cents_per_kwh: float
    purchase_price_cents_per_kwh: float
    availability_penalty_cents_per_kwh: float
    effective_fuel_adder_cents_per_therm: float
    annual_customer_cost_cents: float
    exit_fee_cents: float
    realized_guarantee_credit_cents: float
    lifetime_settled_kwh: float
    lifetime_settled_cents: float
    committed_kwh_remaining: float
    customer_earned_ppa_tokens: int
    customer_spent_ppa_tokens: int
    customer_earned_output_tokens: int
    customer_spent_output_tokens: int
    contract_basis: str
    transfer_stage: str
    originating_ppa_id: Optional[str]
    assigned_service_plan_id: Optional[str]
    output_guarantee_reserve_cents: float
    capacity_guarantee_reserve_cents: float
    capacity_reserve_pre_cents: float
    capacity_reserve_credits_cents: float
    loss_floor_cents: float
    created_at: str
    updated_at: str
    version: int


class ServicePlan(TypedDict):
    id: str
    ppa_id: str
    remote_monitoring_status: str
    lifecycle_state: str
    module_replacement_stage: str
    radius_buffer_m: float
    monitoring_degraded_at: Optional[str]
    monitoring_degraded_days: int
    rollout_schedule_compliant: bool
    window_start_iso8601: Optional[str]
    window_end_iso8601: Optional[str]
    dispatch_hold: bool
    created_at: str
    updated_at: str
    version: int


class FuelDelivery(TypedDict):
    id: str
    site_id: str
    sourcing_mode: str
    volume_therms: float
    index_rate_cents_per_therm: Optional[float]
    fixed_price_cents_per_therm: float
    hedged_fraction: float
    attesting_customer_id: Optional[str]
    delivered_at: str
    confirm_after_iso8601: str
    lifecycle_state: str
    effective_commodity_rate_cents_per_therm: float
    candidate_ppa_a_kwh: float
    candidate_ppa_b_kwh: float
    candidate_ppa_distance_km: float
    selected_ppa_id: Optional[str]
    allocated_ppa_a_kwh: float
    allocated_ppa_b_kwh: float
    active_candidate_demands_at_site: int
    hold_window_start_iso8601: Optional[str]
    hold_window_end_iso8601: Optional[str]
    fuel_basis_rate_cents_per_therm: float
    created_at: str
    updated_at: str
    version: int


class SettlementLine(TypedDict):
    id: str
    ppa_id: str
    period_start: str
    period_end: str
    metered_kwh: float
    downtime_hours: float
    customer_index_cents_per_therm: Optional[float]
    customer_source_deadline_iso8601: str
    hourly_settlement: bool
    expense_hold_days: int
    status: str
    customer_sourced_index_cents_per_therm: float
    availability_credit_cents: float
    cap_side_pool_cents: float
    output_guarantee_credit_cents: float
    resource_side_pool_cents: float
    variable_energy_cents: float
    fixed_purchase_cents: float
    net_charge_cents: float
    net_charge_allocated_cents: float
    hourly_charge_cents: float
    allocation_basis: str
    escalated_rate_cents_per_kwh: float
    loss_component_cents: float
    component_sum_cents: float
    single_round_cents: float
    expected_net_charge_cents: float
    index_basis_cents_per_therm: float
    expected_net_low_cents: float
    expected_net_high_cents: float
    target_ppa_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PpaAccrual(TypedDict):
    id: str
    ppa_id: str
    site_id: str
    source_settlement_line_id: Optional[str]
    accrual_type: str
    amount_cents: float
    lifecycle_state: str
    signed_amount_cents: float
    applied_allowance_id: Optional[str]
    period_anchor_iso8601: str
    created_at: str
    updated_at: str
    version: int


class SettlementAllowance(TypedDict):
    id: str
    ppa_id: str
    allowance_kind: str
    amount_cents: float
    lifecycle_state: str
    applied_direction: Optional[str]
    applied_cap_cents: float
    applied_days: int
    capped_daily_energy_cents: float
    applied_amount_cents: float
    daily_energy_cents: float
    daily_fixed_cents: float
    applied_to_accrual_id: Optional[str]
    applied_to_ppa_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only audit record: id + created_at only.
class PpaTransition(TypedDict):
    id: str
    ppa_id: str
    from_state: str
    to_state: str
    trigger_code: str
    actor_role: str
    transition_reversed: bool
    created_at: str