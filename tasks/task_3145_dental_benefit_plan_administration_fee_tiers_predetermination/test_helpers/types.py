"""Entity record shapes.

These TypedDicts document the fields the PRD makes readable on each
resource.  They are documentation for test authors, not runtime gates.

Every primary resource carries the standard fields ``id``, ``created_at``,
``updated_at`` and ``version``.  The one exception is ``ClaimAttachment``,
which the PRD describes as immutable once uploaded: it records only ``id``
and ``created_at`` (plus the server-stamped ``transmitted_on``), and has no
``updated_at`` and no ``version``.
"""

from typing import Any, Dict, Optional

from typing_extensions import TypedDict


class Plan(TypedDict, total=False):
    id: str
    plan_code: str
    plan_year_start_month: int
    annual_maximum_cents: int
    deductible_cents: int
    deductible_applies_preventive: bool
    preventive_coinsurance_pct: int
    basic_coinsurance_pct: int
    major_coinsurance_pct: int
    basic_waiting_months: int
    major_waiting_months: int
    missing_tooth_clause_active: bool
    abp_enabled: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Provider(TypedDict, total=False):
    id: str
    npi: str
    legal_name: str
    tier: str
    license_state: str
    contracted_on: str
    status: str
    created_at: str
    updated_at: str
    version: int


class FeeSchedule(TypedDict, total=False):
    id: str
    tier: str
    effective_from: str
    effective_to: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class FeeScheduleEntry(TypedDict, total=False):
    id: str
    fee_schedule_id: str
    cdt_code: str
    allowed_cents: int
    category: str
    requires_attachment: bool
    abp_alternative_cdt: str
    created_at: str
    updated_at: str
    version: int


class Subscriber(TypedDict, total=False):
    id: str
    plan_id: str
    member_id: str
    full_name: str
    date_of_birth: str
    effective_date: str
    cob_priority: str
    other_plan_external_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Dependent(TypedDict, total=False):
    id: str
    subscriber_id: str
    full_name: str
    date_of_birth: str
    relationship: str
    status: str
    created_at: str
    updated_at: str
    version: int


class LimitationRule(TypedDict, total=False):
    id: str
    plan_id: str
    cdt_code: str
    rule_kind: str
    window_months: int
    max_occurrences: int
    age_years_min: int
    age_years_max: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Predetermination(TypedDict, total=False):
    id: str
    subscriber_id: str
    dependent_id: Optional[str]
    provider_id: str
    cdt_code: str
    submitted_amount_cents: int
    planned_service_date: str
    clinical_reviewer_id: str
    estimated_allowed_cents: int
    estimated_plan_pay_cents: int
    estimated_patient_pay_cents: int
    abp_applied: bool
    version_pin_fee_schedule_id: Optional[str]
    expires_on: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict, total=False):
    id: str
    subscriber_id: str
    dependent_id: Optional[str]
    provider_id: str
    predetermination_id: Optional[str]
    service_date: str
    received_date: str
    total_submitted_cents: int
    total_allowed_cents: int
    total_plan_pay_cents: int
    total_patient_pay_cents: int
    cob_other_plan_paid_cents: int
    cob_secondary_payment_cents: int
    tooth_missing_prior_to_coverage: Dict[str, Any]
    status: str
    created_at: str
    updated_at: str
    version: int


class ClaimLine(TypedDict, total=False):
    id: str
    claim_id: str
    line_number: int
    cdt_code: str
    tooth_number: str
    submitted_amount_cents: int
    category: str
    allowed_cents: int
    abp_applied: bool
    abp_patient_difference_cents: int
    deductible_applied_cents: int
    coinsurance_plan_cents: int
    plan_pay_cents: int
    patient_pay_cents: int
    denial_code: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ClaimAttachment(TypedDict, total=False):
    # Immutable once uploaded: id + created_at only, no updated_at/version.
    id: str
    claim_id: str
    claim_line_id: str
    attachment_kind: str
    blob_ref: str
    transmitted_on: str
    created_at: str


class BenefitAccumulator(TypedDict, total=False):
    id: str
    subscriber_id: str
    dependent_id: Optional[str]
    plan_year_key: str
    deductible_met_cents: int
    annual_max_used_cents: int
    created_at: str
    updated_at: str
    version: int
