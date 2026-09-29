"""Role authority: exclusive operations, the two separation-of-duties rules, the
entity-backed provider identity, and the one operation every role shares.

Each test separates the role check from the identity check: a role that is simply
not on the endpoint's list is refused with `ERR_UNAUTHORIZED`, while a caller that
holds the right role but the wrong identity is refused by the rule that names it.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_DUAL_AUTHORIZATION_REQUIRED,
    ERR_PROVIDER_SCOPE_VIOLATION,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_UNAUTHORIZED,
)
from test_helpers.constants import (
    CYCLE_DRAFT,
    CYCLE_FUNDED,
    CYCLE_INPUTS_LOCKED,
    CYCLE_RESULTS_APPROVED,
    FILING_TYPE_INCOME_TAX_WITHHOLDING,
    FUNDING_APPROVED,
    FUNDING_DRAFT,
    FUNDING_RELEASED,
    GTN_APPROVED,
    GTN_CLEARED,
)
from test_helpers.test_users import (
    AUDITOR_HEADERS,
    CONTROLLER_2_HEADERS,
    CONTROLLER_HEADERS,
    CONTROLLER_USER_ID,
    OPS_HEADERS,
    PLATFORM_ADMIN_HEADERS,
    TREASURY_APPROVER_HEADERS,
    TREASURY_RELEASER_HEADERS,
    TREASURY_RELEASER_USER_ID,
    make_provider_user_headers,
)

_SINGLE_FILING_COUNTRY = {"required_filing_types": [FILING_TYPE_INCOME_TAX_WITHHOLDING]}


def test_provider_user_may_not_open_a_payroll_cycle(api):
    """The provider that will later produce the results is not on the calendar endpoint's
    role list, so nothing opens until operations issues the identical payload.

    PRD 2.1: "If both headers are present but the named role is not authorized for the
    endpoint being called, the request fails with `ERR_UNAUTHORIZED` (HTTP 403)."

    PRD 4: "| POST | `/payroll/cycles` | Opens a consolidated payroll cycle for one
    engagement and resolves its input cutoff | GlobalPayrollOps |"

    Design: Corner/rbac/provider_user_cannot_open_a_payroll_cycle
    """
    ctx = fx.setup_active_engagement(api, country_overrides=_SINGLE_FILING_COUNTRY)

    response = api.create_cycle(
        f.cycle_payload(ctx["engagement_id"]), ctx["provider_headers"]
    )
    validate_error(response, ERR_UNAUTHORIZED, 403)

    cycles, meta = validate_paginated(
        api.list_cycles(OPS_HEADERS, {"engagement_id": ctx["engagement_id"]})
    )
    a.assert_pagination_meta(meta, expected_total=0, expected_has_more=False)
    assert cycles == [], f"no period was opened, got {cycles}"

    opened = validate_success(
        api.create_cycle(f.cycle_payload(ctx["engagement_id"]), OPS_HEADERS), 201
    )
    a.assert_cycle_state(opened, CYCLE_DRAFT)
    assert opened["period_label"] == "2026-08", (
        f"the same payload carries for operations, got {opened['period_label']!r}"
    )


def test_compliance_auditor_may_not_approve_a_funding_instruction(api):
    """The auditor decides residency and attests controls, but funding approval is a
    treasury act, so the instruction keeps its draft state and no approver is stamped.

    PRD 2.1: "`ComplianceAuditor` owns payroll data privacy: it is the only role that
    may decide an engagement's residency terms or record the manual residency
    attestation, and it is read-only everywhere else."

    PRD 3.6: "Approval is the first of the two treasury authorizations and belongs
    exclusively to a `TreasuryOfficer`."

    Design: Corner/rbac/compliance_auditor_cannot_approve_a_funding_instruction
    """
    ctx = fx.setup_drafted_funding(api, country_overrides=_SINGLE_FILING_COUNTRY)

    response = api.approve_funding_instruction(ctx["funding_id"], AUDITOR_HEADERS)
    validate_error(response, ERR_UNAUTHORIZED, 403)

    funding = fx.read_funding(api, ctx["funding_id"])
    assert funding["status"] == FUNDING_DRAFT, (
        f"the instruction is still awaiting its first signature, got {funding['status']}"
    )
    a.assert_null_fields(funding, ["approver_user_id", "releaser_user_id"])

    cycle = fx.read_cycle(api, ctx["cycle_id"])
    a.assert_cycle_state(cycle, CYCLE_RESULTS_APPROVED)
    a.assert_minor_amount(cycle["funded_total_minor"], 0, "funded_total_minor")


def test_treasury_officer_may_not_release_the_instruction_it_approved(api):
    """The role check passes — the approver is a `TreasuryOfficer` and release is its own
    act — but the identity check fails, and the second officer then releases the money.

    PRD 2.11: "The second is treasury dual authorization. The principal that approves a
    funding instruction is recorded as `approver_user_id`; the principal that releases it
    is recorded as `releaser_user_id`. Release requires that the acting `X-User-ID` differ
    from `approver_user_id`, and an attempt by the approver to release its own instruction
    is rejected with `ERR_DUAL_AUTHORIZATION_REQUIRED` (HTTP 403)."

    Design: Corner/rbac/treasury_officer_cannot_release_the_instruction_they_approved
    """
    ctx = fx.setup_approved_funding(api, country_overrides=_SINGLE_FILING_COUNTRY)

    response = api.release_funding_instruction(
        ctx["funding_id"], TREASURY_APPROVER_HEADERS
    )
    validate_error(response, ERR_DUAL_AUTHORIZATION_REQUIRED, 403)

    funding = fx.read_funding(api, ctx["funding_id"])
    assert funding["status"] == FUNDING_APPROVED, (
        f"the instruction is still merely approved, got {funding['status']}"
    )
    a.assert_null_fields(funding, ["releaser_user_id"])
    cycle = fx.read_cycle(api, ctx["cycle_id"])
    a.assert_cycle_state(cycle, CYCLE_RESULTS_APPROVED)
    a.assert_minor_amount(cycle["funded_total_minor"], 0, "funded_total_minor")

    released = validate_success(
        api.release_funding_instruction(ctx["funding_id"], TREASURY_RELEASER_HEADERS)
    )
    assert released["status"] == FUNDING_RELEASED, (
        f"the second signature moves the money, got {released['status']}"
    )
    assert released["releaser_user_id"] == TREASURY_RELEASER_USER_ID, (
        f"the releaser is stamped from the header, got {released['releaser_user_id']!r}"
    )
    a.assert_cycle_state(fx.read_cycle(api, ctx["cycle_id"]), CYCLE_FUNDED)


def test_controller_that_submitted_the_extract_may_not_review_the_run(api):
    """Extract submission is shared with `PayrollController`, and that very act
    disqualifies the submitting identity from reviewing the resulting run.

    PRD 2.11: "When a gross-to-net run of that cycle is later reviewed, the acting
    `X-User-ID` must differ from the cycle's `input_submitter_user_id`; if they are equal
    the review is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    PRD 3.5: "First, the acting `X-User-ID` must differ from the cycle's
    `input_submitter_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/rbac/controller_who_submitted_the_extract_cannot_review_the_run
    """
    ctx = fx.setup_validated_extract(
        api,
        submitter_headers=CONTROLLER_HEADERS,
        country_overrides=_SINGLE_FILING_COUNTRY,
    )
    ctx = fx.setup_locked_cycle(api, ctx)
    assert ctx["cycle"]["input_submitter_user_id"] == CONTROLLER_USER_ID, (
        "the submitting controller is stamped on the cycle, got "
        f"{ctx['cycle']['input_submitter_user_id']!r}"
    )
    run = fx.submit_run(
        api,
        ctx["cycle_id"],
        ctx["input_file_id"],
        ctx["provider_id"],
        ctx["cycle_version"],
    )
    assert run["status"] == GTN_CLEARED, (
        f"the first period's run clears, got {run['status']}"
    )

    response = api.review_gtn_run(
        run["id"], f.review_approve_payload(), CONTROLLER_HEADERS
    )
    validate_error(response, ERR_SEGREGATION_OF_DUTIES, 403)

    unreviewed = fx.read_run(api, run["id"])
    assert unreviewed["status"] == GTN_CLEARED, (
        f"the run is still awaiting review, got {unreviewed['status']}"
    )
    cycle = fx.read_cycle(api, ctx["cycle_id"])
    a.assert_cycle_state(cycle, CYCLE_INPUTS_LOCKED)
    assert cycle["input_submitter_user_id"] == CONTROLLER_USER_ID, (
        f"the prohibition still names ctrl-01, got {cycle['input_submitter_user_id']!r}"
    )

    approved = validate_success(
        api.review_gtn_run(run["id"], f.review_approve_payload(), CONTROLLER_2_HEADERS)
    )
    assert approved["status"] == GTN_APPROVED, (
        f"a second controller identity may review, got {approved['status']}"
    )
    a.assert_cycle_state(fx.read_cycle(api, ctx["cycle_id"]), CYCLE_RESULTS_APPROVED)


def test_foreign_provider_user_may_not_submit_a_run_on_another_providers_cycle(api):
    """Both callers hold `ProviderUser`, so the role check cannot separate them: the
    entity-backed identity does, and only the write is scoped — the read stays open.

    PRD 2.1: "Concretely, when a `ProviderUser` submits or resubmits gross-to-net results
    for a cycle, the acting `X-User-ID` must equal the `provider_id` of that cycle's
    engagement, and any other value is rejected with `ERR_PROVIDER_SCOPE_VIOLATION`
    (HTTP 403)."

    PRD 4: "| GET | `/payroll/cycles/{id}` | Reads one payroll cycle including its
    resolved cutoff and derived totals | PlatformAdmin, GlobalPayrollOps,
    PayrollController, TreasuryOfficer, ProviderUser, ComplianceAuditor |"

    Design: Corner/rbac/foreign_provider_user_cannot_submit_a_run_on_another_providers_cycle
    """
    ctx = fx.setup_locked_cycle(api, country_overrides=_SINGLE_FILING_COUNTRY)
    rival = fx.create_rival_provider(api)
    rival_headers = make_provider_user_headers(rival["id"])
    payload = f.gtn_run_payload(
        ctx["cycle_id"], ctx["input_file_id"], ctx["cycle_version"]
    )

    response = api.create_gtn_run(payload, rival_headers)
    validate_error(response, ERR_PROVIDER_SCOPE_VIOLATION, 403)

    runs, meta = validate_paginated(
        api.list_gtn_runs(CONTROLLER_HEADERS, {"cycle_id": ctx["cycle_id"]})
    )
    a.assert_pagination_meta(meta, expected_total=0, expected_has_more=False)
    assert runs == [], f"no results were recorded, got {runs}"

    seen_by_rival = validate_success(api.get_cycle(ctx["cycle_id"], rival_headers))
    a.assert_cycle_state(seen_by_rival, CYCLE_INPUTS_LOCKED)
    assert seen_by_rival["id"] == ctx["cycle_id"], (
        f"the shared read stays open to the rival, got {seen_by_rival['id']!r}"
    )

    accepted = validate_success(api.create_gtn_run(payload, ctx["provider_headers"]), 201)
    assert accepted["status"] == GTN_CLEARED, (
        f"the engaged provider's identical body carries, got {accepted['status']}"
    )


def test_every_role_reads_the_same_cycle_detail(api):
    """The cycle read is the one operation shared by all six roles: each of them sees the
    identical period, and none of the reads mutates it.

    PRD 4: "| GET | `/payroll/cycles/{id}` | Reads one payroll cycle including its
    resolved cutoff and derived totals | PlatformAdmin, GlobalPayrollOps,
    PayrollController, TreasuryOfficer, ProviderUser, ComplianceAuditor |"

    PRD 2.4: "and `version`, an integer that starts at 1 on creation and increases by
    exactly 1 on every mutation of that row."

    Design: Corner/rbac/every_role_can_read_the_shared_cycle_detail
    """
    ctx = fx.setup_draft_cycle(api, country_overrides=_SINGLE_FILING_COUNTRY)
    every_role = [
        PLATFORM_ADMIN_HEADERS,
        OPS_HEADERS,
        CONTROLLER_HEADERS,
        TREASURY_APPROVER_HEADERS,
        ctx["provider_headers"],
        AUDITOR_HEADERS,
    ]

    reads = [
        validate_success(api.get_cycle(ctx["cycle_id"], headers))
        for headers in every_role
    ]

    assert len(reads) == 6, f"all six roles were exercised, got {len(reads)}"
    for cycle in reads:
        a.assert_cycle_state(cycle, CYCLE_DRAFT)
        assert cycle["period_label"] == "2026-08", (
            f"every role sees the same period, got {cycle['period_label']!r}"
        )
        assert cycle["id"] == ctx["cycle_id"], (
            f"every role sees the same row, got {cycle['id']!r}"
        )
        a.assert_common_fields(cycle, expected_version=1)
