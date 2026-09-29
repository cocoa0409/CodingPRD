"""
Composite builders and pytest fixtures for the design-firm project accounting API.

Every test runs against an empty database, so all state is built from scratch
through the PRD's own endpoints — there is no seeding back door. That makes the
setup chains long: before a single timesheet line can be approved the suite must
set the logical clock, register a client, publish a labour rate, create a
project, add a leaf phase, set a billing multiplier and activate the project.
The builders below collapse those chains, in five tiers:

1. State progression — set the clock, register the two canonical clients,
   publish a rate, walk a project from SETUP to ACTIVE.
2. Entity hierarchy — a client with a project with a leaf phase with an ACTIVE
   multiplier, returned as a ProjectContext that carries the live version
   counter the optimistically-concurrent creates of PRD §2.7 need.
3. Lifecycle shortcuts — a submitted line, an approved line, an allowable
   expense, an executed subcontract, an approved payable, a draft invoice, an
   approved invoice, a paid invoice, a certified fiscal year.
4. Accumulation and threshold targeting — a project whose unbilled work in
   progress has crossed ``wip_alert_threshold`` into REVIEW_REQUIRED, and a
   public-agency project whose fiscal year is certified so its posture is OPEN.
5. Finalisation and terminal states — a project driven all the way to CLOSED.

Every builder reads the project back afterwards where a version counter matters,
because PRD §2.4 makes a derived-field refresh a mutation: an approval bumps the
project's version even though no client named the project.
"""

from typing import Any, Dict, List, Optional

import pytest

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .constants import (
    CATEGORY_PRINTING,
    CLOCK_2026_06_01,
    CONTRACT_TIME_AND_MATERIALS,
    DECISION_APPROVE,
    FISCAL_YEAR_2026,
    METHOD_EFFORT_BASED,
    ROLE_CODE_PROJECT_ARCHITECT,
)
from .test_users import (
    ACCOUNTANT,
    CONTROLLER,
    CONTROLLER_CERTIFIER,
    CONTROLLER_PREPARER,
    FIRM_ADMIN,
    PROJECT_MANAGER,
    make_client_contact_headers,
)
from .types import ChargeContext, ProjectContext

JsonDict = Dict[str, Any]

# The canonical rate and multiplier the PRD's own worked example uses: 7.35 h at
# 62.50 with a multiplier of 3.0500 freezes raw 459.38 and billable 1401.11.
ARCHITECT_RAW_COST_RATE = 62.50
CANONICAL_MULTIPLIER = 3.0500
RATE_EFFECTIVE_FROM = "2026-01-01"


# ─── Tier 1: state progression ────────────────────────────────────────


def set_clock(api: ApiClient, instant: str = CLOCK_2026_06_01) -> str:
    """Move the logical clock (PRD §2.6). Only a FirmAdmin may do this."""
    get_success_data(api.set_clock(f.clock_payload(instant), FIRM_ADMIN))
    return instant


def create_private_client(api: ApiClient, **overrides: Any) -> JsonDict:
    """Register the canonical private practice client."""
    return get_success_data(
        api.create_client(f.private_client_payload(**overrides), FIRM_ADMIN)
    )


def create_public_client(api: ApiClient, **overrides: Any) -> JsonDict:
    """Register the canonical public agency client."""
    return get_success_data(
        api.create_client(f.public_client_payload(**overrides), FIRM_ADMIN)
    )


def publish_labor_rate(
    api: ApiClient,
    role_code: str = ROLE_CODE_PROJECT_ARCHITECT,
    raw_cost_rate: float = ARCHITECT_RAW_COST_RATE,
    effective_from: str = RATE_EFFECTIVE_FROM,
    effective_to: Optional[str] = None,
) -> JsonDict:
    """Publish one half-open labour rate window (PRD §3.2). Controller only."""
    payload = (
        f.labor_rate_payload(role_code, raw_cost_rate, effective_from)
        if effective_to is None
        else f.labor_rate_payload(role_code, raw_cost_rate, effective_from, effective_to)
    )
    return get_success_data(api.create_labor_rate(payload, CONTROLLER))


def read_project(api: ApiClient, project_id: str, headers: Optional[JsonDict] = None) -> JsonDict:
    """
    Retrieve a project. PRD §2.10 recomputes every rollup on read, so this is
    the canonical way to observe a cascade's effect on the ledger.
    """
    return get_success_data(api.get_project(project_id, headers or CONTROLLER))


def project_version(api: ApiClient, project_id: str) -> int:
    """The project's current ``version``, for the two OCC-guarded creates."""
    return read_project(api, project_id)["version"]


def read_phase(api: ApiClient, phase_id: str, headers: Optional[JsonDict] = None) -> JsonDict:
    return get_success_data(api.get_phase(phase_id, headers or CONTROLLER))


def read_time_entry(api: ApiClient, time_entry_id: str) -> JsonDict:
    return get_success_data(api.get_time_entry(time_entry_id, CONTROLLER))


def read_expense(api: ApiClient, expense_id: str) -> JsonDict:
    return get_success_data(api.get_expense(expense_id, CONTROLLER))


def read_subcontract(api: ApiClient, subcontract_id: str) -> JsonDict:
    return get_success_data(api.get_subcontract(subcontract_id, CONTROLLER))


def read_payable(api: ApiClient, consultant_invoice_id: str) -> JsonDict:
    return get_success_data(api.get_consultant_invoice(consultant_invoice_id, CONTROLLER))


def read_invoice(api: ApiClient, invoice_id: str) -> JsonDict:
    return get_success_data(api.get_invoice(invoice_id, CONTROLLER))


def read_write_off(api: ApiClient, write_off_id: str) -> JsonDict:
    return get_success_data(api.get_write_off(write_off_id, CONTROLLER))


def read_certification(api: ApiClient, certification_id: str) -> JsonDict:
    return get_success_data(api.get_certification(certification_id, CONTROLLER))


def read_aging(api: ApiClient, project_id: str) -> JsonDict:
    return get_success_data(api.get_wip_aging(project_id, CONTROLLER))


def read_earned_value(api: ApiClient, phase_id: str) -> JsonDict:
    return get_success_data(api.get_earned_value(phase_id, CONTROLLER))


# ─── Tier 2: entity hierarchy ─────────────────────────────────────────


def create_project(api: ApiClient, client_id: str, **overrides: Any) -> JsonDict:
    """Create a project in SETUP (PRD §3.1)."""
    return get_success_data(
        api.create_project(f.project_payload(client_id, **overrides), CONTROLLER)
    )


def add_lump_sum_phase(api: ApiClient, project_id: str, **overrides: Any) -> JsonDict:
    return get_success_data(
        api.create_phase(f.lump_sum_phase_payload(project_id, **overrides), CONTROLLER)
    )


def add_percent_phase(api: ApiClient, project_id: str, **overrides: Any) -> JsonDict:
    return get_success_data(
        api.create_phase(f.percent_phase_payload(project_id, **overrides), CONTROLLER)
    )


def set_multiplier(
    api: ApiClient,
    project_id: str,
    multiplier: float = CANONICAL_MULTIPLIER,
    effective_from: str = RATE_EFFECTIVE_FROM,
    expected_project_version: Optional[int] = None,
    **overrides: Any,
) -> JsonDict:
    """
    Set a billing multiplier, reading the project's current version first when
    the caller did not supply one (PRD §2.7 makes the field non-optional).
    """
    version = (
        expected_project_version
        if expected_project_version is not None
        else project_version(api, project_id)
    )
    return get_success_data(
        api.create_billing_multiplier(
            f.multiplier_payload(
                project_id,
                version,
                multiplier=multiplier,
                effective_from=effective_from,
                **overrides,
            ),
            CONTROLLER,
        )
    )


def activate_project(api: ApiClient, project_id: str) -> JsonDict:
    """Move a project SETUP → ACTIVE (PRD §3.1)."""
    return get_success_data(api.activate_project(project_id, CONTROLLER))


def build_active_project(
    api: ApiClient,
    *,
    clock: Optional[str] = CLOCK_2026_06_01,
    public_agency: bool = False,
    publish_rate: bool = True,
    multiplier: float = CANONICAL_MULTIPLIER,
    multiplier_effective_from: str = RATE_EFFECTIVE_FROM,
    client_overrides: Optional[JsonDict] = None,
    project_overrides: Optional[JsonDict] = None,
    phase_overrides: Optional[JsonDict] = None,
) -> ProjectContext:
    """
    Stand up the whole hierarchy an ACTIVE project needs: clock, client, labour
    rate, project, one LUMP_SUM leaf phase, an ACTIVE multiplier and activation.

    Returns a ProjectContext whose ``version`` is the project's version after
    activation, which is what the next OCC-guarded create must be handed.
    """
    if clock is not None:
        set_clock(api, clock)

    client = (
        create_public_client(api, **(client_overrides or {}))
        if public_agency
        else create_private_client(api, **(client_overrides or {}))
    )

    rate_ids: List[str] = []
    if publish_rate:
        rate_ids.append(publish_labor_rate(api)["id"])

    project = create_project(api, client["id"], **(project_overrides or {}))
    phase = add_lump_sum_phase(api, project["id"], **(phase_overrides or {}))
    multiplier_row = set_multiplier(
        api,
        project["id"],
        multiplier=multiplier,
        effective_from=multiplier_effective_from,
        expected_project_version=project["version"],
    )
    activated = activate_project(api, project["id"])

    return ProjectContext(
        client_id=client["id"],
        project_id=project["id"],
        version=activated["version"],
        phase_ids=[phase["id"]],
        multiplier_id=multiplier_row["id"],
        labor_rate_ids=rate_ids,
        is_public_agency=public_agency,
        contract_type=(project_overrides or {}).get(
            "contract_type", CONTRACT_TIME_AND_MATERIALS
        ),
    )


def refresh_version(api: ApiClient, ctx: ProjectContext) -> int:
    """Re-read the project and store its version on the context."""
    ctx.version = project_version(api, ctx.project_id)
    return ctx.version


# ─── Tier 3: lifecycle shortcuts ──────────────────────────────────────


def submit_time_entry(
    api: ApiClient,
    ctx: ProjectContext,
    hours: float = 7.35,
    work_date: str = "2026-05-11",
    role_code: str = ROLE_CODE_PROJECT_ARCHITECT,
    phase_id: Optional[str] = None,
    headers: Optional[JsonDict] = None,
) -> JsonDict:
    """Enter a timesheet line, which lands in SUBMITTED carrying no money."""
    return get_success_data(
        api.create_time_entry(
            f.time_entry_payload(
                ctx.project_id,
                phase_id or ctx.phase_id,
                role_code=role_code,
                work_date=work_date,
                hours=hours,
            ),
            headers or ACCOUNTANT,
        )
    )


def approve_time_entry(
    api: ApiClient, time_entry_id: str, headers: Optional[JsonDict] = None
) -> JsonDict:
    """
    Approve a line. The approver must differ from the submitter, so the default
    approver is the ProjectManager while the default submitter is the accountant.
    """
    return get_success_data(
        api.approve_time_entry(time_entry_id, headers or PROJECT_MANAGER)
    )


def add_approved_time_entry(
    api: ApiClient,
    ctx: ProjectContext,
    hours: float = 7.35,
    work_date: str = "2026-05-11",
    role_code: str = ROLE_CODE_PROJECT_ARCHITECT,
    phase_id: Optional[str] = None,
) -> JsonDict:
    """Submit and then approve one line, returning the approved row."""
    entry = submit_time_entry(
        api, ctx, hours=hours, work_date=work_date, role_code=role_code, phase_id=phase_id
    )
    return approve_time_entry(api, entry["id"])


def add_expense(
    api: ApiClient,
    ctx: ProjectContext,
    amount: float = 74.99,
    category: str = CATEGORY_PRINTING,
    incurred_on: str = "2026-05-13",
    receipt_attached: bool = False,
    phase_id: Optional[str] = None,
    headers: Optional[JsonDict] = None,
) -> JsonDict:
    """Record a reimbursable expense; allowability is adjudicated at capture."""
    return get_success_data(
        api.create_expense(
            f.expense_payload(
                ctx.project_id,
                phase_id or ctx.phase_id,
                category=category,
                amount=amount,
                incurred_on=incurred_on,
                receipt_attached=receipt_attached,
            ),
            headers or ACCOUNTANT,
        )
    )


def draft_subcontract(
    api: ApiClient,
    ctx: ProjectContext,
    committed_amount: float = 20000.00,
    pay_when_paid: bool = False,
    consultant_name: str = "Halcyon MEP",
    commitment_start: str = "2026-04-01",
    commitment_end: str = "2026-12-31",
    phase_id: Optional[str] = None,
) -> JsonDict:
    """Draft a subcontract, which consumes no capacity until it is executed."""
    return get_success_data(
        api.create_subcontract(
            f.subcontract_payload(
                ctx.project_id,
                phase_id or ctx.phase_id,
                consultant_name=consultant_name,
                committed_amount=committed_amount,
                pay_when_paid=pay_when_paid,
                commitment_start=commitment_start,
                commitment_end=commitment_end,
            ),
            CONTROLLER,
        )
    )


def execute_subcontract(api: ApiClient, subcontract_id: str) -> JsonDict:
    return get_success_data(api.execute_subcontract(subcontract_id, CONTROLLER))


def add_executed_subcontract(
    api: ApiClient, ctx: ProjectContext, **overrides: Any
) -> JsonDict:
    """Draft and execute one subcontract, returning the executed row."""
    drafted = draft_subcontract(api, ctx, **overrides)
    return execute_subcontract(api, drafted["id"])


def enter_payable(
    api: ApiClient,
    subcontract_id: str,
    amount: float = 20000.00,
    invoice_date: str = "2026-05-20",
    backup_attached: bool = True,
    headers: Optional[JsonDict] = None,
) -> JsonDict:
    """Enter a consultant payable, which starts RECEIVED / WITHHELD / UNBILLED."""
    return get_success_data(
        api.create_consultant_invoice(
            f.consultant_invoice_payload(
                subcontract_id,
                amount=amount,
                invoice_date=invoice_date,
                backup_attached=backup_attached,
            ),
            headers or ACCOUNTANT,
        )
    )


def approve_payable(
    api: ApiClient, consultant_invoice_id: str, headers: Optional[JsonDict] = None
) -> JsonDict:
    """Approve a payable; the approver must differ from the enterer."""
    return get_success_data(
        api.approve_consultant_invoice(consultant_invoice_id, headers or CONTROLLER)
    )


def add_approved_payable(
    api: ApiClient,
    subcontract_id: str,
    amount: float = 20000.00,
    invoice_date: str = "2026-05-20",
    backup_attached: bool = True,
) -> JsonDict:
    """Enter and approve one payable, returning the approved row."""
    payable = enter_payable(
        api,
        subcontract_id,
        amount=amount,
        invoice_date=invoice_date,
        backup_attached=backup_attached,
    )
    return approve_payable(api, payable["id"])


def prepare_invoice(
    api: ApiClient,
    ctx: ProjectContext,
    period_end: str = "2026-05-31",
    expected_project_version: Optional[int] = None,
    headers: Optional[JsonDict] = None,
) -> JsonDict:
    """
    Prepare a draft invoice, refreshing the project version first unless the
    caller pinned one deliberately (PRD §2.7).
    """
    version = (
        expected_project_version
        if expected_project_version is not None
        else refresh_version(api, ctx)
    )
    return get_success_data(
        api.create_invoice(
            f.invoice_payload(ctx.project_id, version, period_end=period_end),
            headers or ACCOUNTANT,
        )
    )


def submit_invoice(api: ApiClient, invoice_id: str, headers: Optional[JsonDict] = None) -> JsonDict:
    """
    Submit an invoice to the client. The submitter must differ from the
    preparer, so the default submitter is the Controller.
    """
    return get_success_data(api.submit_invoice(invoice_id, headers or CONTROLLER))


def client_review(
    api: ApiClient,
    invoice_id: str,
    client_id: str,
    decision: str = DECISION_APPROVE,
    comment: Optional[str] = None,
) -> JsonDict:
    """
    The client's own decision, made by the entity-backed ClientContact identity
    whose X-User-ID is the acting Client's id.
    """
    payload = (
        f.invoice_review_payload(decision)
        if comment is None
        else f.invoice_review_payload(decision, comment)
    )
    return get_success_data(
        api.review_invoice(invoice_id, payload, make_client_contact_headers(client_id))
    )


def revise_invoice(api: ApiClient, invoice_id: str) -> JsonDict:
    return get_success_data(api.revise_invoice(invoice_id, ACCOUNTANT))


def record_payment(api: ApiClient, invoice_id: str, received_on: str = "2026-06-01") -> JsonDict:
    return get_success_data(
        api.record_invoice_payment(
            invoice_id, f.record_payment_payload(received_on), CONTROLLER
        )
    )


def void_invoice(api: ApiClient, invoice_id: str, reason: str = "Wrong billing period selected") -> JsonDict:
    return get_success_data(
        api.void_invoice(invoice_id, f.void_payload(reason), CONTROLLER)
    )


def build_approved_invoice(
    api: ApiClient, ctx: ProjectContext, period_end: str = "2026-05-31"
) -> JsonDict:
    """Prepare, submit and have the client approve one invoice."""
    invoice = prepare_invoice(api, ctx, period_end=period_end)
    submit_invoice(api, invoice["id"])
    return client_review(api, invoice["id"], ctx.client_id, DECISION_APPROVE)


def build_paid_invoice(
    api: ApiClient,
    ctx: ProjectContext,
    period_end: str = "2026-05-31",
    received_on: str = "2026-06-01",
) -> JsonDict:
    """Drive one invoice all the way to PAID, which is what satisfies pay-when-paid."""
    approved = build_approved_invoice(api, ctx, period_end=period_end)
    return record_payment(api, approved["id"], received_on)


def prepare_labor_write_off(
    api: ApiClient,
    ctx: ProjectContext,
    amount: float,
    reason: str = "Stale charge on a cancelled study",
    headers: Optional[JsonDict] = None,
) -> JsonDict:
    return get_success_data(
        api.create_write_off(
            f.labor_write_off_payload(ctx.project_id, amount, reason=reason),
            headers or ACCOUNTANT,
        )
    )


def prepare_receivable_write_off(
    api: ApiClient,
    ctx: ProjectContext,
    invoice_id: str,
    amount: float,
    reason: str = "Client entered receivership; receivable uncollectible",
    headers: Optional[JsonDict] = None,
) -> JsonDict:
    return get_success_data(
        api.create_write_off(
            f.receivable_write_off_payload(
                ctx.project_id, invoice_id, amount, reason=reason
            ),
            headers or ACCOUNTANT,
        )
    )


def approve_write_off(
    api: ApiClient, write_off_id: str, headers: Optional[JsonDict] = None
) -> JsonDict:
    """Approve a routed write-off; the approver must differ from the preparer."""
    return get_success_data(api.approve_write_off(write_off_id, headers or CONTROLLER))


def submit_certification(
    api: ApiClient,
    fiscal_year: int = FISCAL_YEAR_2026,
    headers: Optional[JsonDict] = None,
    **figures: Any,
) -> JsonDict:
    """Submit a fiscal year's figures; the row lands SUBMITTED."""
    return get_success_data(
        api.create_certification(
            f.certification_payload(fiscal_year=fiscal_year, **figures),
            headers or CONTROLLER_PREPARER,
        )
    )


def certify_year(
    api: ApiClient, fiscal_year: int = FISCAL_YEAR_2026, **figures: Any
) -> JsonDict:
    """
    Submit and then certify one fiscal year. The certifier must differ from the
    preparer, so two distinct Controller identities are used.
    """
    submitted = submit_certification(api, fiscal_year=fiscal_year, **figures)
    return get_success_data(
        api.certify_certification(submitted["id"], CONTROLLER_CERTIFIER)
    )


# ─── Tier 4: accumulation and threshold targeting ─────────────────────


def build_project_with_labor(
    api: ApiClient,
    *,
    clock: str = CLOCK_2026_06_01,
    hours: List[float] = None,
    work_dates: List[str] = None,
) -> ChargeContext:
    """
    An ACTIVE project carrying approved labour. The default pair of lines is the
    PRD's own worked example plus a round 10.00 h line: 7.35 h freezes billable
    1401.11 and 10.00 h freezes 1906.25, so unbilled work in progress is 3307.36.
    """
    hours = [7.35, 10.00] if hours is None else hours
    work_dates = ["2026-05-11", "2026-05-12"] if work_dates is None else work_dates
    ctx = build_active_project(api, clock=clock)
    charges = ChargeContext(project=ctx)
    for hour_value, work_date in zip(hours, work_dates):
        approved = add_approved_time_entry(
            api, ctx, hours=hour_value, work_date=work_date
        )
        charges.time_entry_ids.append(approved["id"])
    refresh_version(api, ctx)
    return charges


def build_project_at_review_required(
    api: ApiClient, *, clock: str = CLOCK_2026_06_01
) -> ChargeContext:
    """
    A project whose ``unbilled_wip`` has passed strictly above the 50000.00
    default ``wip_alert_threshold``, so its posture is REVIEW_REQUIRED and the
    execution of a further consultant subcontract is blocked.

    A single approved payable of 50000.00 carries the standard 0.1000 markup, so
    it admits 55000.00 to work in progress in one hop.
    """
    ctx = build_active_project(
        api, clock=clock, phase_overrides={"consultant_budget": 100000.00}
    )
    charges = ChargeContext(project=ctx)
    subcontract = add_executed_subcontract(api, ctx, committed_amount=60000.00)
    charges.subcontract_ids.append(subcontract["id"])
    payable = add_approved_payable(api, subcontract["id"], amount=50000.00)
    charges.consultant_invoice_ids.append(payable["id"])
    refresh_version(api, ctx)
    return charges


def build_certified_public_project(
    api: ApiClient,
    *,
    clock: str = CLOCK_2026_06_01,
    multiplier: float = 2.5000,
) -> ProjectContext:
    """
    A public-agency project whose fiscal year is already certified, so its
    ``certified_multiplier_ceiling`` is 2.8325 and its posture is OPEN rather
    than HOLD. The certification is firm-wide and is written before the project
    so the multiplier is checked against a ceiling that is already in force.
    """
    set_clock(api, clock)
    certify_year(api, FISCAL_YEAR_2026)
    ctx = build_active_project(
        api,
        clock=None,
        public_agency=True,
        multiplier=multiplier,
        project_overrides={
            "name": "Transit Center Renovation",
            "contract_amount": 900000.00,
            "target_multiplier": 2.5000,
        },
    )
    refresh_version(api, ctx)
    return ctx


# ─── Tier 5: finalisation and terminal states ─────────────────────────


def build_closed_project(api: ApiClient, *, clock: str = CLOCK_2026_06_01) -> ChargeContext:
    """
    A project driven all the way to CLOSED by the bubble-up rule of PRD §3.6:
    its single leaf phase is COMPLETE, its ``unbilled_wip`` is exactly 0.00 and
    its only invoice is PAID.
    """
    ctx = build_active_project(api, clock=clock)
    charges = ChargeContext(project=ctx)
    approved = add_approved_time_entry(api, ctx, hours=10.00, work_date="2026-05-12")
    charges.time_entry_ids.append(approved["id"])
    paid = build_paid_invoice(api, ctx)
    charges.invoice_ids.append(paid["id"])
    get_success_data(api.complete_phase(ctx.phase_id, CONTROLLER))
    refresh_version(api, ctx)
    return charges


# ─── Pytest fixtures ──────────────────────────────────────────────────


@pytest.fixture
def api() -> ApiClient:
    """
    The endpoint client. The server is relaunched before every test, so each
    test starts against an empty database and builds all of its own state.
    """
    return ApiClient()


@pytest.fixture
def clock_june(api: ApiClient) -> str:
    """The logical clock pinned to 2026-06-01T00:00:00Z."""
    return set_clock(api, CLOCK_2026_06_01)


@pytest.fixture
def private_client(api: ApiClient, clock_june: str) -> JsonDict:
    """The canonical private practice client."""
    return create_private_client(api)


@pytest.fixture
def public_client(api: ApiClient, clock_june: str) -> JsonDict:
    """The canonical public agency client."""
    return create_public_client(api)


@pytest.fixture
def architect_rate(api: ApiClient, clock_june: str) -> JsonDict:
    """PROJECT_ARCHITECT at 62.50 from 2026-01-01, open-ended."""
    return publish_labor_rate(api)


@pytest.fixture
def active_project(api: ApiClient) -> ProjectContext:
    """An ACTIVE private-client project with one LUMP_SUM leaf phase."""
    return build_active_project(api)


@pytest.fixture
def active_fixed_fee_project(api: ApiClient) -> ProjectContext:
    """
    An ACTIVE FIXED_FEE project, which is the only contract type subject to the
    earned-value billing ceiling of PRD §3.7.
    """
    return build_active_project(
        api,
        project_overrides={
            "contract_type": "FIXED_FEE",
            "name": "Civic Center Addition",
        },
    )


@pytest.fixture
def active_assessed_project(api: ApiClient) -> ProjectContext:
    """An ACTIVE project whose percent-complete method is ASSESSED."""
    return build_active_project(
        api,
        project_overrides={
            "percent_complete_method": "ASSESSED",
            "name": "Harbor Master Plan",
        },
    )


@pytest.fixture
def project_with_labor(api: ApiClient) -> ChargeContext:
    """An ACTIVE project carrying 3307.36 of approved unbilled labour."""
    return build_project_with_labor(api)


@pytest.fixture
def review_required_project(api: ApiClient) -> ChargeContext:
    """A project whose posture has moved to REVIEW_REQUIRED."""
    return build_project_at_review_required(api)


@pytest.fixture
def certified_public_project(api: ApiClient) -> ProjectContext:
    """A public-agency project with 2026 certified, so its posture is OPEN."""
    return build_certified_public_project(api)


@pytest.fixture
def closed_project(api: ApiClient) -> ChargeContext:
    """A project the bubble-up rule has driven to CLOSED."""
    return build_closed_project(api)
