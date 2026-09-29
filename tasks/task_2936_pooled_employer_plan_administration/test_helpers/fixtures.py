"""
Composite state builders.

Nothing in this API is seeded: the server boots empty and every entity a test
needs is built here through the declared endpoints, in the order the contract
requires.  Each builder returns the server's own payloads so a test can assert
against real identifiers and real version counters.

Identity is threaded explicitly.  A pooled plan provider acts under a header
whose user id is its own provider id, a service provider under its service
provider id and an adopting employer under its employer id, so each context
object carries the headers of the entities it owns.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import constants as k
from . import factories as f
from .api_client import ApiClient
from .test_users import (
    auditor_headers,
    employer_headers,
    plan_provider_headers,
    regulator_headers,
    service_provider_headers,
)


def _data(response) -> Dict[str, Any]:
    """Unwrap a fixture-setup response, failing loudly on a non-2xx."""
    return get_success_data(response)


# ─── Logical clock ────────────────────────────────────


def set_clock(client: ApiClient, current_utc: str) -> Dict[str, Any]:
    """Move the logical clock; only regulator operations may do this."""
    return _data(client.set_clock(current_utc, headers=regulator_headers()))


# ─── Context objects ──────────────────────────────────


@dataclass
class PlanContext:
    """A pooled plan with its sponsor, its two providers and its allocations."""

    provider: Dict[str, Any]
    plan: Dict[str, Any]
    recordkeeper: Dict[str, Any]
    trustee: Dict[str, Any]
    named_fiduciary_allocation: Optional[Dict[str, Any]] = None
    trustee_allocation: Optional[Dict[str, Any]] = None

    @property
    def provider_id(self) -> str:
        return self.provider["id"]

    @property
    def plan_id(self) -> str:
        return self.plan["id"]

    @property
    def recordkeeper_id(self) -> str:
        return self.recordkeeper["id"]

    @property
    def trustee_id(self) -> str:
        return self.trustee["id"]

    @property
    def provider_headers(self) -> Dict[str, str]:
        return plan_provider_headers(self.provider_id)

    @property
    def recordkeeper_headers(self) -> Dict[str, str]:
        return service_provider_headers(self.recordkeeper_id)

    @property
    def trustee_headers(self) -> Dict[str, str]:
        return service_provider_headers(self.trustee_id)

    def refresh(self, client: ApiClient) -> Dict[str, Any]:
        """Re-read the plan document and return the fresh payload."""
        self.plan = _data(client.get_plan_document(self.plan_id, self.provider_headers))
        return self.plan

    @property
    def plan_version(self) -> int:
        return self.plan["version"]


@dataclass
class EmployerContext:
    """An adopting employer with its plan and its election history."""

    plan: PlanContext
    employer: Dict[str, Any]
    elections: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def employer_id(self) -> str:
        return self.employer["id"]

    @property
    def headers(self) -> Dict[str, str]:
        return employer_headers(self.employer_id)

    @property
    def election(self) -> Dict[str, Any]:
        return self.elections[-1]

    @property
    def election_id(self) -> str:
        return self.election["id"]

    def refresh(self, client: ApiClient) -> Dict[str, Any]:
        """Re-read the employer and return the fresh payload."""
        self.employer = _data(
            client.get_adopting_employer(self.employer_id, self.headers)
        )
        return self.employer

    @property
    def employer_version(self) -> int:
        return self.employer["version"]


# ─── Plan bootstrap ───────────────────────────────────


def registered_provider(
    client: ApiClient, payload: Optional[dict] = None, **overrides: Any
) -> Dict[str, Any]:
    """Create a pooled plan provider and approve its registration."""
    provider = _data(
        client.create_plan_provider(
            payload if payload is not None else f.plan_provider_payload(**overrides),
            regulator_headers(),
        )
    )
    return _data(
        client.register_plan_provider(
            provider["id"], f.register_provider_payload(), regulator_headers()
        )
    )


def pending_provider(
    client: ApiClient, payload: Optional[dict] = None, **overrides: Any
) -> Dict[str, Any]:
    """Create a pooled plan provider and leave its registration pending."""
    return _data(
        client.create_plan_provider(
            payload if payload is not None else f.plan_provider_payload(**overrides),
            regulator_headers(),
        )
    )


def draft_plan(
    client: ApiClient, provider: Dict[str, Any], payload: Optional[dict] = None, **overrides: Any
) -> Dict[str, Any]:
    """Create a DRAFT plan document under a provider."""
    return _data(
        client.create_plan_document(
            payload
            if payload is not None
            else f.plan_document_payload(provider["id"], **overrides),
            plan_provider_headers(provider["id"]),
        )
    )


def engage_provider(
    client: ApiClient, plan_ctx_or_provider_id: Any, payload: dict
) -> Dict[str, Any]:
    """Engage a service provider on a plan, acting as the plan's sponsor."""
    provider_id = (
        plan_ctx_or_provider_id.provider_id
        if isinstance(plan_ctx_or_provider_id, PlanContext)
        else plan_ctx_or_provider_id
    )
    return _data(
        client.create_service_provider(payload, plan_provider_headers(provider_id))
    )


def allocate_role(
    client: ApiClient,
    plan_ctx: PlanContext,
    service_provider_id: str,
    fiduciary_role: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """
    Allocate a fiduciary function, quoting the plan's current version.

    The plan document is re-read first because an accepted allocation bumps the
    plan's version, so the expected version has to be read fresh for every
    allocation rather than remembered from the bootstrap.
    """
    plan_ctx.refresh(client)
    return _data(
        client.create_fiduciary_role_allocation(
            f.fiduciary_allocation_payload(
                plan_ctx.plan_id,
                service_provider_id,
                fiduciary_role,
                plan_ctx.plan_version,
                **overrides,
            ),
            plan_ctx.provider_headers,
        )
    )


def acknowledge_role(
    client: ApiClient,
    allocation: Dict[str, Any],
    statement: str,
) -> Dict[str, Any]:
    """Acknowledge an allocation as the service provider that holds it."""
    return _data(
        client.acknowledge_fiduciary_role_allocation(
            allocation["id"],
            f.acknowledge_allocation_payload(statement),
            service_provider_headers(allocation["service_provider_id"]),
        )
    )


def plan_with_acknowledged_roles(client: ApiClient, **plan_overrides: Any) -> PlanContext:
    """
    Build a DRAFT plan that satisfies every activation precondition.

    The sponsor is registered, a recordkeeper holds the acknowledged named
    fiduciary function and a trustee holds the acknowledged trustee function,
    but the plan document itself has not been activated yet.
    """
    provider = registered_provider(client)
    plan = draft_plan(client, provider, **plan_overrides)
    recordkeeper = engage_provider(
        client, provider["id"], f.recordkeeper_payload(plan["id"])
    )
    trustee = engage_provider(client, provider["id"], f.trustee_payload(plan["id"]))
    plan_ctx = PlanContext(
        provider=provider, plan=plan, recordkeeper=recordkeeper, trustee=trustee
    )
    named = allocate_role(
        client, plan_ctx, recordkeeper["id"], k.FIDUCIARY_NAMED_FIDUCIARY_3_16
    )
    plan_ctx.named_fiduciary_allocation = acknowledge_role(
        client, named, k.NAMED_FIDUCIARY_ACKNOWLEDGMENT
    )
    trustee_allocation = allocate_role(
        client, plan_ctx, trustee["id"], k.FIDUCIARY_TRUSTEE_403A
    )
    plan_ctx.trustee_allocation = acknowledge_role(
        client, trustee_allocation, k.TRUSTEE_ACKNOWLEDGMENT
    )
    plan_ctx.refresh(client)
    return plan_ctx


def active_plan(client: ApiClient, **plan_overrides: Any) -> PlanContext:
    """Build an ACTIVE plan: the whole sponsor and fiduciary chain, activated."""
    plan_ctx = plan_with_acknowledged_roles(client, **plan_overrides)
    plan_ctx.plan = _data(
        client.activate_plan_document(plan_ctx.plan_id, plan_ctx.provider_headers)
    )
    return plan_ctx


def second_plan(client: ApiClient, plan_ctx: PlanContext) -> Dict[str, Any]:
    """Add a second DRAFT plan document under the same sponsor."""
    return _data(
        client.create_plan_document(
            f.second_plan_document_payload(plan_ctx.provider_id),
            plan_ctx.provider_headers,
        )
    )


def audit_firm(
    client: ApiClient, plan_ctx: PlanContext, **overrides: Any
) -> Dict[str, Any]:
    """Engage an audit firm on a plan."""
    return engage_provider(
        client, plan_ctx.provider_id, f.auditor_firm_payload(plan_ctx.plan_id, **overrides)
    )


# ─── Employer adoption ────────────────────────────────


def applied_employer(
    client: ApiClient,
    plan_ctx: PlanContext,
    payload: Optional[dict] = None,
    **overrides: Any,
) -> EmployerContext:
    """Add an employer that has APPLIED but elected nothing yet."""
    employer = _data(
        client.create_adopting_employer(
            payload
            if payload is not None
            else f.adopting_employer_payload(plan_ctx.plan_id, **overrides),
            plan_ctx.provider_headers,
        )
    )
    return EmployerContext(plan=plan_ctx, employer=employer)


def drafted_election(
    client: ApiClient, emp_ctx: EmployerContext, payload: Optional[dict] = None, **overrides: Any
) -> Dict[str, Any]:
    """Draft an election for an employer, quoting its current version."""
    emp_ctx.refresh(client)
    election = _data(
        client.create_design_election(
            payload
            if payload is not None
            else f.design_election_payload(
                emp_ctx.employer_id, emp_ctx.employer_version, **overrides
            ),
            emp_ctx.headers,
        )
    )
    emp_ctx.elections.append(election)
    return election


def submitted_election(
    client: ApiClient,
    emp_ctx: EmployerContext,
    signatory_name: str = k.PALISADE_SIGNATORY,
    payload: Optional[dict] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Draft and submit an election."""
    election = drafted_election(client, emp_ctx, payload, **overrides)
    election = _data(
        client.submit_design_election(
            election["id"], f.submit_election_payload(signatory_name), emp_ctx.headers
        )
    )
    emp_ctx.elections[-1] = election
    return election


def active_employer(
    client: ApiClient,
    plan_ctx: PlanContext,
    payload: Optional[dict] = None,
    election_payload: Optional[dict] = None,
    signatory_name: str = k.PALISADE_SIGNATORY,
    **overrides: Any,
) -> EmployerContext:
    """Add an employer whose election has been submitted and approved."""
    emp_ctx = applied_employer(client, plan_ctx, payload, **overrides)
    submitted_election(
        client, emp_ctx, signatory_name=signatory_name, payload=election_payload
    )
    approved = _data(
        client.approve_design_election(emp_ctx.election_id, plan_ctx.provider_headers)
    )
    emp_ctx.elections[-1] = approved
    emp_ctx.refresh(client)
    return emp_ctx


def second_active_employer(
    client: ApiClient, plan_ctx: PlanContext, **overrides: Any
) -> EmployerContext:
    """Add a second, larger active employer to the same plan."""
    emp_ctx = applied_employer(
        client, plan_ctx, f.second_adopting_employer_payload(plan_ctx.plan_id, **overrides)
    )
    submitted_election(client, emp_ctx, signatory_name=k.QUARRY_SIGNATORY)
    approved = _data(
        client.approve_design_election(emp_ctx.election_id, plan_ctx.provider_headers)
    )
    emp_ctx.elections[-1] = approved
    emp_ctx.refresh(client)
    return emp_ctx


# ─── Payroll and remittance ───────────────────────────


def received_batch(
    client: ApiClient,
    emp_ctx: EmployerContext,
    payload: Optional[dict] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Deliver a payroll batch as the employer; it stays RECEIVED."""
    return _data(
        client.create_payroll_batch(
            payload
            if payload is not None
            else f.payroll_batch_payload(emp_ctx.employer_id, **overrides),
            emp_ctx.headers,
        )
    )


def validated_batch(
    client: ApiClient,
    emp_ctx: EmployerContext,
    payload: Optional[dict] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Deliver a batch and have the plan recordkeeper reconcile it."""
    batch = received_batch(client, emp_ctx, payload, **overrides)
    return _data(
        client.validate_payroll_batch(
            batch["id"],
            f.validate_batch_payload(),
            emp_ctx.plan.recordkeeper_headers,
        )
    )


def pending_deposit(
    client: ApiClient,
    emp_ctx: EmployerContext,
    batch: Dict[str, Any],
    clock: Optional[str] = k.DEPOSIT_CLOCK,
    **overrides: Any,
) -> Dict[str, Any]:
    """
    Record a remittance against a validated batch; it stays PENDING.

    A deposit date may not be later than the logical-clock calendar date, so the
    clock is moved to the day of the remittance first unless the caller opts out.
    """
    if clock is not None:
        set_clock(client, clock)
    return _data(
        client.create_remittance_deposit(
            f.remittance_deposit_payload(batch["id"], **overrides), emp_ctx.headers
        )
    )


def posted_deposit(
    client: ApiClient,
    emp_ctx: EmployerContext,
    batch: Dict[str, Any],
    posting_reference: str = k.POSTING_REFERENCE,
    clock: Optional[str] = k.DEPOSIT_CLOCK,
    **overrides: Any,
) -> Dict[str, Any]:
    """Record and post a remittance, which evaluates its timeliness."""
    deposit = pending_deposit(client, emp_ctx, batch, clock, **overrides)
    return _data(
        client.post_remittance_deposit(
            deposit["id"],
            f.post_deposit_payload(posting_reference),
            emp_ctx.plan.recordkeeper_headers,
        )
    )


def timely_deposit(
    client: ApiClient,
    emp_ctx: EmployerContext,
    batch: Dict[str, Any],
    clock: Optional[str] = k.TIMELY_DEPOSIT_CLOCK,
    **overrides: Any,
) -> Dict[str, Any]:
    """Post a deposit dated on the seventh business day after withholding."""
    overrides.setdefault("deposit_date", k.DEPOSIT_DATE_SEVENTH_BUSINESS_DAY)
    return posted_deposit(client, emp_ctx, batch, clock=clock, **overrides)


def late_deposit(
    client: ApiClient,
    emp_ctx: EmployerContext,
    batch: Dict[str, Any],
    clock: Optional[str] = k.LATE_DEPOSIT_CLOCK,
    **overrides: Any,
) -> Dict[str, Any]:
    """Post a deposit dated on the eighth business day after withholding."""
    overrides.setdefault("deposit_date", k.DEPOSIT_DATE_EIGHTH_BUSINESS_DAY)
    return posted_deposit(client, emp_ctx, batch, clock=clock, **overrides)


def corrected_computation(
    client: ApiClient,
    emp_ctx: EmployerContext,
    deposit: Dict[str, Any],
    correction_method: str = k.CORRECTION_IRS_6621_UNDERPAYMENT,
    recovery_date: str = k.RECOVERY_DATE,
    actual_investment_return_cents: int = 0,
) -> Dict[str, Any]:
    """Compute the correction figures for a late deposit."""
    return _data(
        client.compute_deposit_correction(
            deposit["id"],
            f.compute_correction_payload(
                correction_method, recovery_date, actual_investment_return_cents
            ),
            emp_ctx.plan.recordkeeper_headers,
        )
    )


def funded_correction(
    client: ApiClient,
    emp_ctx: EmployerContext,
    deposit: Dict[str, Any],
    form_5330_reference: Optional[str] = None,
) -> Dict[str, Any]:
    """Fund a computed correction as the employer."""
    return _data(
        client.fund_deposit_correction(
            deposit["id"],
            emp_ctx.headers,
            f.fund_correction_payload(form_5330_reference),
        )
    )


def late_then_corrected_deposit(
    client: ApiClient, emp_ctx: EmployerContext, batch: Dict[str, Any], **overrides: Any
) -> Dict[str, Any]:
    """Walk a deposit all the way from LATE to CORRECTED."""
    deposit = late_deposit(client, emp_ctx, batch, **overrides)
    deposit = corrected_computation(client, emp_ctx, deposit)
    return funded_correction(client, emp_ctx, deposit, k.FORM_5330_REFERENCE)


# ─── Compliance testing ───────────────────────────────


def scheduled_test(
    client: ApiClient,
    plan_ctx: PlanContext,
    payload: Optional[dict] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Schedule a compliance test as the plan's sponsor."""
    return _data(
        client.create_compliance_test(
            payload
            if payload is not None
            else f.compliance_test_payload(plan_ctx.plan_id, **overrides),
            plan_ctx.provider_headers,
        )
    )


def run_test(
    client: ApiClient, plan_ctx: PlanContext, test: Dict[str, Any]
) -> Dict[str, Any]:
    """Run a scheduled test as the plan recordkeeper."""
    return _data(client.run_compliance_test(test["id"], plan_ctx.recordkeeper_headers))


def completed_test(
    client: ApiClient, plan_ctx: PlanContext, payload: Optional[dict] = None, **overrides: Any
) -> Dict[str, Any]:
    """Schedule and run a compliance test."""
    return run_test(client, plan_ctx, scheduled_test(client, plan_ctx, payload, **overrides))


# ─── Annual return ────────────────────────────────────


def draft_filing(
    client: ApiClient, plan_ctx: PlanContext, plan_year: int = k.PLAN_YEAR
) -> Dict[str, Any]:
    """Open the plan's annual return for a plan year."""
    return _data(
        client.create_plan_filing(
            f.plan_filing_payload(plan_ctx.plan_id, plan_year), plan_ctx.provider_headers
        )
    )


def prepared_filing(
    client: ApiClient, plan_ctx: PlanContext, plan_year: int = k.PLAN_YEAR
) -> Dict[str, Any]:
    """Open and prepare the annual return, snapshotting every figure."""
    filing = draft_filing(client, plan_ctx, plan_year)
    return _data(
        client.prepare_plan_filing(filing["id"], plan_ctx.recordkeeper_headers)
    )


def certified_filing(
    client: ApiClient, plan_ctx: PlanContext, plan_year: int = k.PLAN_YEAR
) -> Dict[str, Any]:
    """Prepare the return and clear its employer-data branch."""
    filing = prepared_filing(client, plan_ctx, plan_year)
    return _data(
        client.certify_plan_filing_employer_data(
            filing["id"], plan_ctx.provider_headers
        )
    )


def attested_filing(
    client: ApiClient,
    plan_ctx: PlanContext,
    filing: Dict[str, Any],
    audit_firm_service_provider_id: str,
    audit_opinion: str = k.OPINION_UNMODIFIED,
) -> Dict[str, Any]:
    """Clear a prepared return's audit branch as the independent auditor."""
    return _data(
        client.attest_plan_filing(
            filing["id"],
            f.attest_filing_payload(audit_firm_service_provider_id, audit_opinion),
            auditor_headers(),
        )
    )


def filed_filing(
    client: ApiClient, plan_ctx: PlanContext, filing: Dict[str, Any]
) -> Dict[str, Any]:
    """File a return that has cleared every required branch."""
    return _data(client.file_plan_filing(filing["id"], regulator_headers()))


# ─── Exit and transfer ────────────────────────────────


def requested_exit(
    client: ApiClient,
    emp_ctx: EmployerContext,
    payload: Optional[dict] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Request an exit as the employer."""
    return _data(
        client.create_exit_transfer(
            payload
            if payload is not None
            else f.exit_transfer_payload(emp_ctx.employer_id, **overrides),
            emp_ctx.headers,
        )
    )


def approved_exit(
    client: ApiClient,
    emp_ctx: EmployerContext,
    payload: Optional[dict] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Request and approve an exit, opening the blackout window."""
    transfer = requested_exit(client, emp_ctx, payload, **overrides)
    return _data(
        client.approve_exit_transfer(transfer["id"], emp_ctx.plan.provider_headers)
    )


def settled_exit(
    client: ApiClient,
    emp_ctx: EmployerContext,
    payload: Optional[dict] = None,
    settle_clock: str = k.POST_BLACKOUT_CLOCK,
    **overrides: Any,
) -> Dict[str, Any]:
    """
    Approve an exit, move the clock past the blackout window and settle it.

    Settlement is only available once the blackout window has closed, so the
    logical clock is advanced before the settle call.
    """
    transfer = approved_exit(client, emp_ctx, payload, **overrides)
    if settle_clock is not None:
        set_clock(client, settle_clock)
    return _data(
        client.settle_exit_transfer(transfer["id"], emp_ctx.plan.provider_headers)
    )


def reversed_exit(
    client: ApiClient,
    emp_ctx: EmployerContext,
    transfer: Dict[str, Any],
    reversal_reason: str,
) -> Dict[str, Any]:
    """Unwind a settled transfer as the plan's sponsor."""
    return _data(
        client.reverse_exit_transfer(
            transfer["id"],
            f.reverse_transfer_payload(reversal_reason),
            emp_ctx.plan.provider_headers,
        )
    )


# ─── Fee disclosure ───────────────────────────────────


def issued_disclosure(
    client: ApiClient,
    plan_ctx: PlanContext,
    payload: Optional[dict] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Issue a fee disclosure for a period as the plan's sponsor."""
    return _data(
        client.create_fee_disclosure(
            payload
            if payload is not None
            else f.fee_disclosure_payload(plan_ctx.plan_id, **overrides),
            plan_ctx.provider_headers,
        )
    )
