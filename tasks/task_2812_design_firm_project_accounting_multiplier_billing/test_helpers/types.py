"""
Typed shapes for the design-firm project accounting API.

The TypedDicts mirror the field names the PRD declares for each resource, so a
test that mistypes a field name fails static reading rather than silently
asserting nothing. The dataclasses are the return shapes of the composite
builders in fixtures.py: a builder hands back every identifier and version
counter a test needs to drive the next hop of a cascade.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

try:  # Python 3.8+
    from typing import TypedDict
except ImportError:  # pragma: no cover
    from typing_extensions import TypedDict  # type: ignore

JsonDict = Dict[str, Any]


# ─── Resource shapes (PRD §2.4, §3.1-§3.9) ────────────────────────────


class ClientShape(TypedDict, total=False):
    """A Client carries only id and created_at (PRD §2.4: deliberately immutable)."""

    id: str
    created_at: str
    name: str
    is_public_agency: bool
    retainage_pct: float
    expense_markup_pct: float
    disallowed_categories: List[str]
    receipt_required_above: float
    review_cycle_days: int


class LaborRateShape(TypedDict, total=False):
    """A LaborRate carries only id and created_at (PRD §2.4)."""

    id: str
    created_at: str
    role_code: str
    raw_cost_rate: float
    effective_from: str
    effective_to: Optional[str]


class ProjectShape(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    client_id: str
    name: str
    contract_type: str
    contract_amount: float
    project_manager_user_id: str
    percent_complete_method: str
    target_multiplier: float
    wip_alert_threshold: float
    status: str
    locked_through_date: Optional[str]
    billing_posture: str
    certified_multiplier_ceiling: Optional[float]
    overhead_adjustment_required: bool
    raw_labor_cost_to_date: float
    unbilled_wip: float
    billed_open: float
    paid_gross_to_date: float
    written_off_gross: float
    total_charge_value: float
    earned_revenue_to_date: float
    net_multiplier_achieved: float


class PhaseShape(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    project_id: str
    wbs_code: str
    fee_basis: str
    fee_percent: Optional[float]
    lump_sum_fee: Optional[float]
    parent_phase_id: Optional[str]
    budget_labor_cost: float
    consultant_budget: float
    status: str
    depth: int
    is_leaf: bool
    phase_fee: float
    actual_labor_cost_to_date: float
    effort_based_percent_complete: float
    effort_based_earned_value: float
    assessed_percent_complete: float
    assessed_earned_value: float
    recognized_earned_value: float
    consultant_committed_open: float


class EarnedValueReport(TypedDict, total=False):
    """Computed read; carries none of the common resource properties (PRD §3.6)."""

    phase_id: str
    phase_fee: float
    budget_labor_cost: float
    actual_labor_cost_to_date: float
    effort_based_percent_complete: float
    effort_based_earned_value: float
    assessed_percent_complete: float
    assessed_earned_value: float
    selected_method: str
    recognized_earned_value: float


class WipAgingReport(TypedDict, total=False):
    """Computed read; carries none of the common resource properties (PRD §3.8)."""

    project_id: str
    as_of_date: str
    bucket_0_30: float
    bucket_31_60: float
    bucket_61_90: float
    bucket_over_90: float
    total_unbilled: float
    write_off_eligible_amount: float


class TimeEntryShape(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    project_id: str
    phase_id: str
    role_code: str
    work_date: str
    hours: float
    status: str
    raw_cost: float
    applied_multiplier: Optional[float]
    billable_amount: float
    submitted_by_user_id: str
    approved_by_user_id: Optional[str]
    billed_invoice_id: Optional[str]


class ExpenseShape(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    project_id: str
    phase_id: str
    category: str
    amount: float
    incurred_on: str
    receipt_attached: bool
    allowability_status: str
    allowability_reason: str
    billable_amount: float
    billing_status: str
    billed_invoice_id: Optional[str]
    incurred_by_user_id: str
    reviewed_by_user_id: Optional[str]
    review_justification: Optional[str]


class SubcontractShape(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    project_id: str
    phase_id: str
    consultant_name: str
    committed_amount: float
    pay_when_paid: bool
    commitment_start: str
    commitment_end: str
    status: str
    approved_to_date: float
    released_to_date: float
    committed_remaining: float


class ConsultantInvoiceShape(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    subcontract_id: str
    amount: float
    invoice_date: str
    backup_attached: bool
    approval_status: str
    payment_status: str
    billing_status: str
    applied_markup_pct: float
    markup_amount: float
    billable_amount: float
    entered_by_user_id: str
    approved_by_user_id: Optional[str]
    rejection_reason: Optional[str]
    client_invoice_id: Optional[str]


class InvoiceShape(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    project_id: str
    period_end: str
    status: str
    labor_billed: float
    expense_billed: float
    consultant_billed: float
    gross_billed: float
    volume_discount_pct: float
    discount_amount: float
    retainage_amount: float
    net_due: float
    swept_labor_count: int
    swept_expense_count: int
    swept_consultant_count: int
    backup_missing_count: int
    revision_round: int
    prepared_by_user_id: str
    submitted_by_user_id: Optional[str]
    client_decision_comment: Optional[str]
    paid_on: Optional[str]
    void_reason: Optional[str]


class WriteOffShape(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    project_id: str
    target_type: str
    invoice_id: Optional[str]
    amount: float
    reason: str
    status: str
    required_approver: str
    aging_days: int
    allocated_time_entry_ids: List[str]
    prepared_by_user_id: str
    approved_by_user_id: Optional[str]


class CertificationShape(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    fiscal_year: int
    ytd_months: int
    direct_labor_base: float
    indirect_cost_pool: float
    unallowable_costs: float
    status: str
    provisional_overhead_rate: float
    final_overhead_rate: Optional[float]
    certified_multiplier_ceiling: Optional[float]
    prepared_by_user_id: str
    certified_by_user_id: Optional[str]
    findings: Optional[str]


# ─── Composite builder return shapes ──────────────────────────────────


@dataclass
class ProjectContext:
    """
    Everything a test needs to keep driving a project it just stood up.

    ``version`` is the project version observed on the last read, which is what
    the two optimistically-concurrent creates of PRD §2.7 must be handed.
    """

    client_id: str
    project_id: str
    version: int
    phase_ids: List[str] = field(default_factory=list)
    multiplier_id: Optional[str] = None
    labor_rate_ids: List[str] = field(default_factory=list)
    is_public_agency: bool = False
    contract_type: str = "TIME_AND_MATERIALS"

    @property
    def phase_id(self) -> str:
        """The first phase created on the project."""
        return self.phase_ids[0]


@dataclass
class ChargeContext:
    """A project context plus the charges layered on top of it."""

    project: ProjectContext
    time_entry_ids: List[str] = field(default_factory=list)
    expense_ids: List[str] = field(default_factory=list)
    subcontract_ids: List[str] = field(default_factory=list)
    consultant_invoice_ids: List[str] = field(default_factory=list)
    invoice_ids: List[str] = field(default_factory=list)
    write_off_ids: List[str] = field(default_factory=list)

    @property
    def client_id(self) -> str:
        return self.project.client_id

    @property
    def project_id(self) -> str:
        return self.project.project_id

    @property
    def phase_id(self) -> str:
        return self.project.phase_id
