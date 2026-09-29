"""Composite setup helpers for the Global Payroll Aggregation API.

The server is restarted before every individual test, so each test starts against
an empty database and rebuilds all of its preconditions through the PRD's own
endpoints. These helpers are the shared, reusable prefixes of those chains.

Layering, from cheapest to most expensive:
  1. primitives      — one endpoint call each (`create_country`, `submit_extract`, …)
  2. reads           — `read_cycle`, `read_provider`, … for post-condition asserts
  3. estate tiers    — `setup_active_engagement`, `setup_draft_cycle`
  4. payroll tiers   — `setup_validated_extract`, `setup_locked_cycle`,
                       `setup_scored_run`, `setup_results_approved_cycle`
  5. treasury tiers  — `setup_verified_bank_account`, `setup_drafted_funding`,
                       `setup_approved_funding`, `setup_funded_cycle`
  6. filing/standing — `sweep_filings`, `lodge_filing`, `setup_closable_cycle`,
                       `confirmed_incident`, `plan_transition`

Every helper returns the inner `data` object the server sent, never the envelope,
so callers never index `["data"]` a second time.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data, validate_success

from . import factories as f
from .api_client import ApiClient
from .constants import (
    DECISION_APPROVE,
    SEV1,
)
from .test_users import (
    AUDITOR_HEADERS,
    CONTROLLER_HEADERS,
    OPS_HEADERS,
    PLATFORM_ADMIN_HEADERS,
    TREASURY_APPROVER_HEADERS,
    TREASURY_RELEASER_HEADERS,
    make_provider_user_headers,
)

Ctx = Dict[str, Any]


# ─── Tier 1: primitives ───────────────────────────────────────────────────────


def set_clock(client: ApiClient, instant: str, headers=PLATFORM_ADMIN_HEADERS) -> None:
    """Move the logical clock (PRD 2.5). `instant` is a full ISO 8601 instant."""
    get_success_data(client.set_clock(instant, headers))


def create_country(client: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        client.create_country_profile(
            f.country_profile_payload(**overrides), PLATFORM_ADMIN_HEADERS
        )
    )


def create_provider(client: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        client.create_provider(f.provider_payload(**overrides), PLATFORM_ADMIN_HEADERS)
    )


def create_rival_provider(client: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        client.create_provider(
            f.rival_provider_payload(**overrides), PLATFORM_ADMIN_HEADERS
        )
    )


def create_engagement(
    client: ApiClient, country_profile_id: str, provider_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        client.create_engagement(
            f.engagement_payload(country_profile_id, provider_id, **overrides),
            PLATFORM_ADMIN_HEADERS,
        )
    )


def approve_residency(
    client: ApiClient, engagement_id: str, residency_terms_ref: str = "DPA-DE-2026-01"
) -> Dict[str, Any]:
    return get_success_data(
        client.residency_decision(
            engagement_id,
            f.residency_approve_payload(residency_terms_ref),
            AUDITOR_HEADERS,
        )
    )


def create_cycle(
    client: ApiClient, engagement_id: str, headers=OPS_HEADERS, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        client.create_cycle(f.cycle_payload(engagement_id, **overrides), headers)
    )


def submit_extract(
    client: ApiClient, cycle_id: str, headers=OPS_HEADERS, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        client.create_input_file(f.input_file_payload(cycle_id, **overrides), headers)
    )


def validate_extract(
    client: ApiClient, input_file_id: str, headers=OPS_HEADERS
) -> Dict[str, Any]:
    return get_success_data(client.validate_input_file(input_file_id, headers))


def lock_inputs(client: ApiClient, cycle_id: str, headers=OPS_HEADERS) -> Dict[str, Any]:
    return get_success_data(client.lock_inputs(cycle_id, headers))


def submit_run(
    client: ApiClient,
    cycle_id: str,
    input_file_id: str,
    provider_id: str,
    expected_cycle_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        client.create_gtn_run(
            f.gtn_run_payload(
                cycle_id, input_file_id, expected_cycle_version, **overrides
            ),
            make_provider_user_headers(provider_id),
        )
    )


def approve_run(
    client: ApiClient,
    run_id: str,
    headers=CONTROLLER_HEADERS,
    variance_justification: Optional[str] = None,
) -> Dict[str, Any]:
    return get_success_data(
        client.review_gtn_run(
            run_id, f.review_approve_payload(variance_justification), headers
        )
    )


def return_run(
    client: ApiClient, run_id: str, headers=CONTROLLER_HEADERS, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        client.review_gtn_run(run_id, f.review_return_payload(**overrides), headers)
    )


def create_bank_account(
    client: ApiClient, engagement_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        client.create_bank_account(
            f.bank_account_payload(engagement_id, **overrides), PLATFORM_ADMIN_HEADERS
        )
    )


def verify_bank_account(client: ApiClient, bank_account_id: str) -> Dict[str, Any]:
    return get_success_data(
        client.verify_bank_account(bank_account_id, PLATFORM_ADMIN_HEADERS)
    )


def draft_funding(
    client: ApiClient,
    cycle_id: str,
    bank_account_id: str,
    headers=TREASURY_APPROVER_HEADERS,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        client.create_funding_instruction(
            f.funding_instruction_payload(cycle_id, bank_account_id, **overrides),
            headers,
        )
    )


def approve_funding(
    client: ApiClient, funding_instruction_id: str, headers=TREASURY_APPROVER_HEADERS
) -> Dict[str, Any]:
    return get_success_data(
        client.approve_funding_instruction(funding_instruction_id, headers)
    )


def release_funding(
    client: ApiClient, funding_instruction_id: str, headers=TREASURY_RELEASER_HEADERS
) -> Dict[str, Any]:
    return get_success_data(
        client.release_funding_instruction(funding_instruction_id, headers)
    )


def raise_incident(
    client: ApiClient,
    engagement_id: str,
    severity: str = SEV1,
    headers=OPS_HEADERS,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        client.create_incident(
            f.incident_payload(engagement_id, severity, **overrides), headers
        )
    )


def confirm_incident(
    client: ApiClient, incident_id: str, headers=CONTROLLER_HEADERS
) -> Dict[str, Any]:
    return get_success_data(client.confirm_incident(incident_id, headers))


def escalate_incident(
    client: ApiClient, incident_id: str, headers=CONTROLLER_HEADERS
) -> Dict[str, Any]:
    return get_success_data(
        client.escalate_incident(incident_id, headers, f.escalate_payload())
    )


def remediate_incident(
    client: ApiClient, incident_id: str, headers=CONTROLLER_HEADERS, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        client.remediate_incident(incident_id, f.remediate_payload(**overrides), headers)
    )


# ─── Tier 2: reads used for post-condition assertions ─────────────────────────


def read_country(client: ApiClient, country_profile_id: str, headers=PLATFORM_ADMIN_HEADERS):
    return validate_success(client.get_country_profile(country_profile_id, headers))


def read_provider(client: ApiClient, provider_id: str, headers=PLATFORM_ADMIN_HEADERS):
    return validate_success(client.get_provider(provider_id, headers))


def read_engagement(client: ApiClient, engagement_id: str, headers=PLATFORM_ADMIN_HEADERS):
    return validate_success(client.get_engagement(engagement_id, headers))


def read_cycle(client: ApiClient, cycle_id: str, headers=OPS_HEADERS):
    return validate_success(client.get_cycle(cycle_id, headers))


def read_run(client: ApiClient, run_id: str, headers=CONTROLLER_HEADERS):
    return validate_success(client.get_gtn_run(run_id, headers))


def read_funding(client: ApiClient, funding_instruction_id: str, headers=TREASURY_APPROVER_HEADERS):
    return validate_success(
        client.get_funding_instruction(funding_instruction_id, headers)
    )


def read_filing(client: ApiClient, filing_id: str, headers=OPS_HEADERS):
    return validate_success(client.get_filing(filing_id, headers))


def read_incident(client: ApiClient, incident_id: str, headers=CONTROLLER_HEADERS):
    return validate_success(client.get_incident(incident_id, headers))


def filings_of_cycle(
    client: ApiClient, cycle_id: str, headers=OPS_HEADERS, **filters: Any
) -> List[Dict[str, Any]]:
    """The cycle's statutory filings in `created_at` ascending order (PRD 2.3)."""
    response = client.list_filings(headers, f.pagination_params(cycle_id=cycle_id, **filters))
    return validate_success(response)


# ─── Tier 3: the estate ───────────────────────────────────────────────────────


def setup_active_engagement(
    client: ApiClient,
    country: Optional[Dict[str, Any]] = None,
    provider: Optional[Dict[str, Any]] = None,
    country_overrides: Optional[Dict[str, Any]] = None,
    provider_overrides: Optional[Dict[str, Any]] = None,
    engagement_overrides: Optional[Dict[str, Any]] = None,
    residency_terms_ref: str = "DPA-DE-2026-01",
) -> Ctx:
    """A country, a provider and an engagement activated by the residency decision.

    PRD 3.2: what makes an engagement operational is the residency decision, and
    only a `ComplianceAuditor` may take it.
    """
    country = country or create_country(client, **(country_overrides or {}))
    provider = provider or create_provider(client, **(provider_overrides or {}))
    engagement = create_engagement(
        client, country["id"], provider["id"], **(engagement_overrides or {})
    )
    engagement = approve_residency(client, engagement["id"], residency_terms_ref)
    return {
        "country": country,
        "country_id": country["id"],
        "provider": provider,
        "provider_id": provider["id"],
        "provider_headers": make_provider_user_headers(provider["id"]),
        "engagement": engagement,
        "engagement_id": engagement["id"],
        "engagement_version": engagement["version"],
    }


def setup_draft_cycle(
    client: ApiClient,
    ctx: Optional[Ctx] = None,
    cycle_overrides: Optional[Dict[str, Any]] = None,
    **estate_kwargs: Any,
) -> Ctx:
    """An ACTIVE engagement plus one DRAFT payroll cycle for it (PRD 3.3)."""
    ctx = ctx or setup_active_engagement(client, **estate_kwargs)
    cycle = create_cycle(client, ctx["engagement_id"], **(cycle_overrides or {}))
    ctx = dict(ctx)
    ctx.update(
        {
            "cycle": cycle,
            "cycle_id": cycle["id"],
            "cycle_version": cycle["version"],
        }
    )
    return ctx


# ─── Tier 4: the payroll run ──────────────────────────────────────────────────


def setup_validated_extract(
    client: ApiClient,
    ctx: Optional[Ctx] = None,
    extract_overrides: Optional[Dict[str, Any]] = None,
    submitter_headers=OPS_HEADERS,
    **cycle_kwargs: Any,
) -> Ctx:
    """A DRAFT cycle carrying exactly one VALIDATED extract (PRD 3.4)."""
    ctx = ctx or setup_draft_cycle(client, **cycle_kwargs)
    extract = submit_extract(
        client, ctx["cycle_id"], submitter_headers, **(extract_overrides or {})
    )
    extract = validate_extract(client, extract["id"])
    ctx = dict(ctx)
    ctx.update({"input_file": extract, "input_file_id": extract["id"]})
    return ctx


def setup_locked_cycle(
    client: ApiClient, ctx: Optional[Ctx] = None, **extract_kwargs: Any
) -> Ctx:
    """A cycle in INPUTS_LOCKED with its statutory obligations minted (PRD 3.4)."""
    ctx = ctx or setup_validated_extract(client, **extract_kwargs)
    cycle = lock_inputs(client, ctx["cycle_id"])
    ctx = dict(ctx)
    ctx.update({"cycle": cycle, "cycle_version": cycle["version"]})
    return ctx


def setup_scored_run(
    client: ApiClient,
    ctx: Optional[Ctx] = None,
    run_overrides: Optional[Dict[str, Any]] = None,
    **lock_kwargs: Any,
) -> Ctx:
    """A locked cycle carrying one submitted-and-scored gross-to-net run.

    PRD 3.5: the variance analysis runs in the very same request, so the returned
    run has already re-branched out of `SUBMITTED`.
    """
    ctx = ctx or setup_locked_cycle(client, **lock_kwargs)
    run = submit_run(
        client,
        ctx["cycle_id"],
        ctx["input_file_id"],
        ctx["provider_id"],
        ctx["cycle_version"],
        **(run_overrides or {}),
    )
    cycle = read_cycle(client, ctx["cycle_id"])
    ctx = dict(ctx)
    ctx.update(
        {
            "run": run,
            "run_id": run["id"],
            "cycle": cycle,
            "cycle_version": cycle["version"],
        }
    )
    return ctx


def setup_results_approved_cycle(
    client: ApiClient,
    ctx: Optional[Ctx] = None,
    reviewer_headers=CONTROLLER_HEADERS,
    variance_justification: Optional[str] = None,
    **run_kwargs: Any,
) -> Ctx:
    """A cycle in RESULTS_APPROVED behind an APPROVED run (PRD 3.5)."""
    ctx = ctx or setup_scored_run(client, **run_kwargs)
    run = approve_run(client, ctx["run_id"], reviewer_headers, variance_justification)
    cycle = read_cycle(client, ctx["cycle_id"])
    ctx = dict(ctx)
    ctx.update({"run": run, "cycle": cycle, "cycle_version": cycle["version"]})
    return ctx


# ─── Tier 5: treasury ─────────────────────────────────────────────────────────


def setup_verified_bank_account(
    client: ApiClient, ctx: Ctx, **overrides: Any
) -> Ctx:
    """A VERIFIED local disbursement account on the engagement (PRD 3.1)."""
    account = create_bank_account(client, ctx["engagement_id"], **overrides)
    account = verify_bank_account(client, account["id"])
    ctx = dict(ctx)
    ctx.update({"bank_account": account, "bank_account_id": account["id"]})
    return ctx


def setup_drafted_funding(
    client: ApiClient,
    ctx: Optional[Ctx] = None,
    account_overrides: Optional[Dict[str, Any]] = None,
    funding_overrides: Optional[Dict[str, Any]] = None,
    **approved_kwargs: Any,
) -> Ctx:
    """A RESULTS_APPROVED cycle with a DRAFT funding instruction (PRD 3.6)."""
    ctx = ctx or setup_results_approved_cycle(client, **approved_kwargs)
    if "bank_account_id" not in ctx:
        ctx = setup_verified_bank_account(client, ctx, **(account_overrides or {}))
    funding = draft_funding(
        client,
        ctx["cycle_id"],
        ctx["bank_account_id"],
        **(funding_overrides or {}),
    )
    ctx = dict(ctx)
    ctx.update({"funding": funding, "funding_id": funding["id"]})
    return ctx


def setup_approved_funding(
    client: ApiClient, ctx: Optional[Ctx] = None, **draft_kwargs: Any
) -> Ctx:
    """A funding instruction approved by treas-01, awaiting a second signature."""
    ctx = ctx or setup_drafted_funding(client, **draft_kwargs)
    funding = approve_funding(client, ctx["funding_id"])
    ctx = dict(ctx)
    ctx.update({"funding": funding})
    return ctx


def setup_funded_cycle(
    client: ApiClient, ctx: Optional[Ctx] = None, **approve_kwargs: Any
) -> Ctx:
    """A FUNDED cycle: released by treas-02, distinct from the approver (PRD 3.6)."""
    ctx = ctx or setup_approved_funding(client, **approve_kwargs)
    funding = release_funding(client, ctx["funding_id"])
    cycle = read_cycle(client, ctx["cycle_id"])
    ctx = dict(ctx)
    ctx.update({"funding": funding, "cycle": cycle, "cycle_version": cycle["version"]})
    return ctx


# ─── Tier 6: filings, standing and provider transitions ───────────────────────


def sweep_filings(client: ApiClient, cycle_id: str, headers=OPS_HEADERS):
    """Run the cycle's statutory filing sweep (PRD 3.7)."""
    return get_success_data(client.filing_sweep(cycle_id, headers))


def lodge_filing(
    client: ApiClient, filing_id: str, provider_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Lodge a filing as the responsible provider (PRD 3.7)."""
    return get_success_data(
        client.file_filing(
            filing_id,
            f.file_filing_payload(**overrides),
            make_provider_user_headers(provider_id),
        )
    )


def confirm_filing(
    client: ApiClient, filing_id: str, headers=OPS_HEADERS, **overrides: Any
) -> Dict[str, Any]:
    """PRD 3.7: either `GlobalPayrollOps` or a `ProviderUser` may confirm."""
    return get_success_data(
        client.confirm_filing(filing_id, f.confirm_filing_payload(**overrides), headers)
    )


def open_penalty_dispute(
    client: ApiClient, filing_id: str, provider_id: str, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        client.penalty_dispute(
            filing_id,
            f.penalty_dispute_payload(**overrides),
            make_provider_user_headers(provider_id),
        )
    )


def decide_penalty_dispute(
    client: ApiClient, filing_id: str, decision: str, headers=CONTROLLER_HEADERS
) -> Dict[str, Any]:
    return get_success_data(
        client.penalty_dispute_decision(
            filing_id, f.penalty_decision_payload(decision), headers
        )
    )


def record_evidence(
    client: ApiClient, cycle_id: str, control_ref: str, **overrides: Any
) -> Dict[str, Any]:
    """Record a manual attestation. Only a `ComplianceAuditor` may do so (PRD 3.9)."""
    return get_success_data(
        client.create_audit_evidence(
            f.audit_evidence_payload(cycle_id, control_ref, **overrides),
            AUDITOR_HEADERS,
        )
    )


def evidence_of_cycle(
    client: ApiClient, cycle_id: str, headers=AUDITOR_HEADERS, **filters: Any
):
    return validate_success(
        client.list_cycle_audit_evidence(cycle_id, headers, f.pagination_params(**filters))
    )


def release_hold(client: ApiClient, cycle_id: str, headers=OPS_HEADERS) -> Dict[str, Any]:
    return get_success_data(client.release_hold(cycle_id, headers))


def cancel_cycle(
    client: ApiClient, cycle_id: str, headers=OPS_HEADERS, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        client.cancel_cycle(cycle_id, f.cancel_payload(**overrides), headers)
    )


def close_cycle(
    client: ApiClient, cycle_id: str, headers=CONTROLLER_HEADERS
) -> Dict[str, Any]:
    return get_success_data(client.close_cycle(cycle_id, headers))


def plan_transition(
    client: ApiClient,
    engagement_id: str,
    incoming_provider_id: str,
    expected_engagement_version: int,
    headers=CONTROLLER_HEADERS,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        client.transition_plan(
            engagement_id,
            f.transition_plan_payload(
                incoming_provider_id, expected_engagement_version, **overrides
            ),
            headers,
        )
    )


def decide_transition(
    client: ApiClient,
    engagement_id: str,
    payload: Dict[str, Any],
    headers=PLATFORM_ADMIN_HEADERS,
) -> Dict[str, Any]:
    return get_success_data(
        client.transition_decision(engagement_id, payload, headers)
    )


def setup_closable_cycle(
    client: ApiClient, ctx: Optional[Ctx] = None, **funded_kwargs: Any
) -> Ctx:
    """A FUNDED cycle whose statutory obligations are all CONFIRMED (PRD 3.9).

    The three closing preconditions are the FUNDED status, every non-voided
    filing confirmed, and the four system-minted controls, which the funded chain
    has already produced.
    """
    ctx = ctx or setup_funded_cycle(client, **funded_kwargs)
    for filing in filings_of_cycle(client, ctx["cycle_id"]):
        lodged = lodge_filing(client, filing["id"], ctx["provider_id"])
        confirm_filing(client, lodged["id"])
    ctx = dict(ctx)
    ctx["cycle"] = read_cycle(client, ctx["cycle_id"])
    return ctx


def confirmed_incident(
    client: ApiClient, engagement_id: str, severity: str, **overrides: Any
) -> Dict[str, Any]:
    """An incident whose weight already counts against the service score (PRD 3.8)."""
    incident = raise_incident(client, engagement_id, severity, **overrides)
    return confirm_incident(client, incident["id"])


def setup_baseline_and_locked_second_period(
    client: ApiClient,
    ctx: Optional[Ctx] = None,
    second_cycle_overrides: Optional[Dict[str, Any]] = None,
    second_extract_overrides: Optional[Dict[str, Any]] = None,
    **approved_kwargs: Any,
) -> Ctx:
    """A RESULTS_APPROVED 2026-08 baseline plus a locked adjacent 2026-09 period.

    PRD 3.5: the baseline is the gross-to-net run with status `APPROVED` whose
    cycle is the one named by this cycle's `prior_cycle_id`, so the second period
    is opened with `prior_cycle_id` pointing at the first.

    On return the `cycle_*` and `input_file_*` keys address the second period, and
    `baseline_cycle_id` / `baseline_run` still address the first.
    """
    ctx = ctx or setup_results_approved_cycle(client, **approved_kwargs)
    baseline_cycle_id = ctx["cycle_id"]
    baseline_run = ctx["run"]
    second = create_cycle(
        client,
        ctx["engagement_id"],
        period_label="2026-09",
        period_start_date="2026-09-01",
        period_end_date="2026-10-01",
        pay_date="2026-09-30",
        prior_cycle_id=baseline_cycle_id,
        **(second_cycle_overrides or {}),
    )
    extract = submit_extract(client, second["id"], **(second_extract_overrides or {}))
    extract = validate_extract(client, extract["id"])
    locked = lock_inputs(client, second["id"])
    ctx = dict(ctx)
    ctx.update(
        {
            "baseline_cycle_id": baseline_cycle_id,
            "baseline_run": baseline_run,
            "cycle": locked,
            "cycle_id": locked["id"],
            "cycle_version": locked["version"],
            "input_file": extract,
            "input_file_id": extract["id"],
        }
    )
    return ctx


def setup_second_results_approved_period(
    client: ApiClient,
    ctx: Ctx,
    cycle_overrides: Optional[Dict[str, Any]] = None,
    extract_overrides: Optional[Dict[str, Any]] = None,
) -> Ctx:
    """Drive a second, adjacent 2026-09 period of the same engagement to approval.

    No `prior_cycle_id` is supplied, so PRD 3.5 leaves the second period without a
    variance baseline and its run clears without a justification.
    """
    ctx = setup_draft_cycle(
        client,
        ctx,
        cycle_overrides={
            "period_label": "2026-09",
            "period_start_date": "2026-09-01",
            "period_end_date": "2026-10-01",
            "pay_date": "2026-09-30",
            **(cycle_overrides or {}),
        },
    )
    ctx = setup_validated_extract(client, ctx, extract_overrides=extract_overrides)
    ctx = setup_locked_cycle(client, ctx)
    ctx = setup_scored_run(client, ctx)
    return setup_results_approved_cycle(client, ctx)


def drive_cycle_to_closable(
    client: ApiClient,
    ctx: Ctx,
    cycle_overrides: Optional[Dict[str, Any]] = None,
    extract_overrides: Optional[Dict[str, Any]] = None,
) -> Ctx:
    """Open a cycle on an existing estate and drive it to the closing gate.

    PRD 3.9: the three closing checks are the FUNDED status, every non-`VOIDED`
    filing `CONFIRMED`, and the four system-minted controls, all of which this
    chain produces in order.
    """
    ctx = setup_draft_cycle(client, ctx, cycle_overrides=cycle_overrides)
    ctx = setup_validated_extract(client, ctx, extract_overrides=extract_overrides)
    ctx = setup_locked_cycle(client, ctx)
    ctx = setup_scored_run(client, ctx)
    ctx = setup_results_approved_cycle(client, ctx)
    ctx = setup_drafted_funding(client, ctx)
    ctx = setup_approved_funding(client, ctx)
    ctx = setup_funded_cycle(client, ctx)
    return setup_closable_cycle(client, ctx)
