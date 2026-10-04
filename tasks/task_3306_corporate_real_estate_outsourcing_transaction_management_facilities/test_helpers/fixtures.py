"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() from the framework (lenient validator) so setup failures
produce clear "Setup failed" errors rather than confusing assertion failures.

Every helper drives the system exclusively through PRD-declared endpoints.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_account_payload,
    create_assignment_payload,
    create_audit_payload,
    create_audit_review_payload,
    create_broker_engagement_payload,
    create_commission_record_payload,
    create_consolidation_project_payload,
    create_data_license_payload,
    create_fee_accrual_payload,
    create_kpi_payload,
    create_lease_payload,
    create_scorecard_payload,
    create_site_payload,
    create_transaction_request_payload,
    create_transition_task_payload,
    create_vendor_payload,
)
from .test_users import (
    TEST_USERS,
    make_account_executive_headers,
    make_approval_authority_headers,
)


# ─── Identity helpers ─────────────────────────────────

def ae_headers(account) -> dict:
    """AccountExecutive headers whose X-User-ID is the account's own id.

    The PRD interprets the AccountExecutive's X-User-ID as the id of the acting
    PortfolioAccount, so every ownership-gated account operation must carry it.
    """
    account_id = account["id"] if isinstance(account, dict) else account
    return make_account_executive_headers(account_id)


def auth_headers(assignment) -> dict:
    """ApprovalAuthority headers whose X-User-ID is the AccountAssignment id."""
    assignment_id = assignment["id"] if isinstance(assignment, dict) else assignment
    return make_approval_authority_headers(assignment_id)


ANON = TEST_USERS
TM = TEST_USERS["transaction_manager_headers"]
FM = TEST_USERS["facilities_manager_headers"]
OP = TEST_USERS["occupancy_planner_headers"]
GM = TEST_USERS["governance_manager_headers"]
DS = TEST_USERS["data_steward_headers"]
TRANS = TEST_USERS["transition_manager_headers"]


# ─── Tier 1: State progression ────────────────────────

def create_account(**overrides) -> dict:
    """Create a PortfolioAccount (born DRAFT). Returns the created account."""
    res = api_client.create_account(
        create_account_payload(**overrides), TEST_USERS["account_executive_headers"]
    )
    return get_success_data(res)


def create_activated_account(**overrides) -> dict:
    """Create a PortfolioAccount and activate it. Returns the ACTIVE account."""
    account = create_account(**overrides)
    res = api_client.activate_account(account["id"], ae_headers(account))
    return get_success_data(res)


def create_account_with_approver(
    approval_level: str = "ACCOUNT_EXECUTIVE",
    assignee_name: str = "Dana Director",
    **overrides,
):
    """Active account + one APPROVAL_AUTHORITY assignment. Returns (account, assignment)."""
    account = create_activated_account(**overrides)
    assignment = get_success_data(
        api_client.create_assignment(
            account["id"],
            create_assignment_payload(
                assignee_name=assignee_name, approval_level=approval_level
            ),
            ae_headers(account),
        )
    )
    return account, assignment


def create_assignment(account, approval_level="ACCOUNT_EXECUTIVE",
                      assignee_name="Dana Director", **overrides) -> dict:
    """Add an APPROVAL_AUTHORITY assignment to an account."""
    return get_success_data(
        api_client.create_assignment(
            account["id"],
            create_assignment_payload(
                assignee_name=assignee_name,
                approval_level=approval_level,
                **overrides,
            ),
            ae_headers(account),
        )
    )


# ─── Tier 2: Entity hierarchy ─────────────────────────

def create_lease(account, **overrides) -> dict:
    """Create a Lease in PIPELINE on the account."""
    res = api_client.create_lease(
        create_lease_payload(account["id"], **overrides), TM
    )
    return get_success_data(res)


def create_transaction_request(account, lease, **overrides) -> dict:
    """Create a TransactionRequest in DRAFT."""
    res = api_client.create_transaction_request(
        create_transaction_request_payload(account["id"], lease["id"], **overrides), TM
    )
    return get_success_data(res)


def submit_transaction_request(account, request) -> dict:
    res = api_client.submit_transaction_request(request["id"], TM)
    return get_success_data(res)


def approve_transaction_request(request, assignment, level="ACCOUNT_EXECUTIVE") -> dict:
    """Apply an affirmative approval-chain decision. Cascades the lease."""
    res = api_client.decide_transaction_request(
        request["id"], {"decision": "APPROVE", "level": level}, auth_headers(assignment)
    )
    return get_success_data(res)


def reject_transaction_request(request, assignment, level="ACCOUNT_EXECUTIVE") -> dict:
    res = api_client.decide_transaction_request(
        request["id"], {"decision": "REJECT", "level": level}, auth_headers(assignment)
    )
    return get_success_data(res)


def setup_approved_request(
    request_overrides=None,
    lease_overrides=None,
    approval_level="ACCOUNT_EXECUTIVE",
    **account_overrides,
):
    """Active account + approver + lease + APPROVED transaction request.

    Drives: account -> activate -> assignment -> lease -> request -> submit
    request -> submit lease -> approve. The request's submission moves it to
    PENDING_APPROVAL; the lease's own submission moves it to APPROVAL_PENDING,
    which is the precondition PRD §3.2 sets for the approval decision to cascade
    the lease to BROKER_ASSIGNED. Returns (account, lease, request, assignment).
    """
    account, assignment = create_account_with_approver(
        approval_level=approval_level, **account_overrides
    )
    lease = create_lease(account, **(lease_overrides or {}))
    request = create_transaction_request(account, lease, **(request_overrides or {}))
    submit_transaction_request(account, request)
    submit_lease_for_approval(lease)
    request = approve_transaction_request(request, assignment, level=approval_level)
    # Re-read the lease so callers observe the post-decision pipeline_state
    # (the approval decision cascades the lease to BROKER_ASSIGNED inside the DB).
    lease = get_success_data(api_client.get_lease(lease["id"], TM))
    return account, lease, request, assignment


def setup_pending_request(
    request_overrides=None, lease_overrides=None, approval_level="ACCOUNT_EXECUTIVE",
    **account_overrides,
):
    """Active account + approver + lease + PENDING_APPROVAL request.

    Also submits the lease itself, so it sits in APPROVAL_PENDING alongside the
    request — the state pair PRD §3.2 requires for the approval/rejection fork.
    Returns (account, lease, request, assignment).
    """
    account, assignment = create_account_with_approver(
        approval_level=approval_level, **account_overrides
    )
    lease = create_lease(account, **(lease_overrides or {}))
    request = create_transaction_request(account, lease, **(request_overrides or {}))
    request = submit_transaction_request(account, request)
    lease = submit_lease_for_approval(lease)
    # Re-read so callers observe pipeline_state APPROVAL_PENDING rather than the
    # stale pre-submission snapshot.
    lease = get_success_data(api_client.get_lease(lease["id"], TM))
    return account, lease, request, assignment


def create_broker_engagement(account, request, **overrides) -> dict:
    res = api_client.create_broker_engagement(
        create_broker_engagement_payload(account["id"], request["id"], **overrides), TM
    )
    return get_success_data(res)


def assign_broker_engagement(engagement) -> dict:
    res = api_client.assign_broker_engagement(engagement["id"], TM)
    return get_success_data(res)


# ─── Tier 3: Full lifecycle shortcuts ─────────────────

def setup_broker_in_market(
    request_overrides=None, lease_overrides=None, engagement_overrides=None,
    approval_level="ACCOUNT_EXECUTIVE", **account_overrides,
):
    """Approved request + ASSIGNED engagement + lease in IN_MARKET.

    Returns (account, lease, request, assignment, engagement).
    """
    account, lease, request, assignment = setup_approved_request(
        request_overrides=request_overrides,
        lease_overrides=lease_overrides,
        approval_level=approval_level,
        **account_overrides,
    )
    engagement = create_broker_engagement(
        account, request, **(engagement_overrides or {})
    )
    engagement = assign_broker_engagement(engagement)
    lease = get_success_data(
        api_client.launch_marketing(lease["id"], TM)
    )
    return account, lease, request, assignment, engagement


def setup_negotiating_lease(
    request_overrides=None, lease_overrides=None, engagement_overrides=None,
    approval_level="ACCOUNT_EXECUTIVE", **account_overrides,
):
    """Approved request + ASSIGNED engagement + lease in NEGOTIATING.

    Returns (account, lease, request, assignment, engagement).
    """
    account, lease, request, assignment, engagement = setup_broker_in_market(
        request_overrides=request_overrides,
        lease_overrides=lease_overrides,
        engagement_overrides=engagement_overrides,
        approval_level=approval_level,
        **account_overrides,
    )
    lease = get_success_data(api_client.open_negotiation(lease["id"], TM))
    return account, lease, request, assignment, engagement


def setup_lease_executed(
    request_overrides=None, lease_overrides=None, engagement_overrides=None,
    **account_overrides,
):
    """Full transaction lifecycle through lease EXECUTED.

    Returns (account, lease, request, assignment, engagement).
    """
    account, lease, request, assignment, engagement = setup_negotiating_lease(
        request_overrides=request_overrides,
        lease_overrides=lease_overrides,
        engagement_overrides=engagement_overrides,
        **account_overrides,
    )
    lease = get_success_data(api_client.execute_lease(lease["id"], TM))
    return account, lease, request, assignment, engagement


# ─── Facilities ───────────────────────────────────────

def create_vendor(account, **overrides) -> dict:
    res = api_client.create_vendor(
        create_vendor_payload(account["id"], **overrides), FM
    )
    return get_success_data(res)


def activate_vendor(vendor) -> dict:
    return get_success_data(api_client.activate_vendor(vendor["id"], FM))


def create_active_vendor(account, **overrides) -> dict:
    vendor = create_vendor(account, **overrides)
    return activate_vendor(vendor)


def create_site(account, vendor, **overrides) -> dict:
    res = api_client.create_site(
        create_site_payload(account["id"], vendor["id"], **overrides), FM
    )
    return get_success_data(res)


def vacate_site(site) -> dict:
    return get_success_data(api_client.vacate_site(site["id"], FM))


def consolidate_site(site, window_start, window_end) -> dict:
    return get_success_data(
        api_client.consolidate_site(
            site["id"], {"window_start": window_start, "window_end": window_end}, FM
        )
    )


# ─── Consolidation projects ───────────────────────────

def create_consolidation_project(account, **overrides) -> dict:
    res = api_client.create_consolidation_project(
        create_consolidation_project_payload(account["id"], **overrides), OP
    )
    return get_success_data(res)


def submit_consolidation_project(project) -> dict:
    return get_success_data(api_client.submit_consolidation_project(project["id"], OP))


def create_approved_project(account, assignment, **overrides) -> dict:
    """ConsolidationProject driven to APPROVED. Returns the project."""
    project = create_consolidation_project(account, **overrides)
    submit_consolidation_project(project)
    return get_success_data(
        api_client.approve_consolidation_project(project["id"], auth_headers(assignment))
    )


def setup_project_with_three_sites(
    reductions=(40_001, 25_002, 15_003), sqfts=(40_001, 25_002, 15_003),
    planned=None, inflation=1.05, rates=(3.335, 6.665, 4.005),
    consolidate=False, **account_overrides,
):
    """Active account + approver + vendor + APPROVED 3-site consolidation project.

    The three sites are assigned to the project in creation order so element i of
    the per-site arrays applies to the i-th site. When consolidate=True each site
    is vacated and moved into consolidation with adjacent, non-overlapping windows.

    Returns (account, project, vendor, sites, assignment).
    """
    account, assignment = create_account_with_approver(**account_overrides)
    vendor = create_active_vendor(account)
    planned = planned if planned is not None else sum(reductions)
    project = create_approved_project(
        account,
        assignment,
        planned_sqft_reduction=planned,
        cost_inflation_factor=inflation,
        per_site_rates=list(rates),
        per_site_sqft_reductions=list(reductions),
    )
    windows = [
        ("2026-10-01T00:00:00Z", "2026-12-01T00:00:00Z"),
        ("2026-12-01T00:00:00Z", "2027-02-01T00:00:00Z"),
        ("2027-02-01T00:00:00Z", "2027-04-01T00:00:00Z"),
    ]
    sites = []
    for i, (red, sqft) in enumerate(zip(reductions, sqfts)):
        site = create_site(
            account,
            vendor,
            site_name=f"Tower {sqft}",
            sqft=sqft,
            sqft_reduction=red,
            consolidation_project_id=project["id"],
        )
        if consolidate:
            vacate_site(site)
            site = consolidate_site(site, windows[i][0], windows[i][1])
        sites.append(site)
    return account, project, vendor, sites, assignment


# ─── Governance ───────────────────────────────────────

def create_kpi(account, **overrides) -> dict:
    res = api_client.create_kpi(create_kpi_payload(account["id"], **overrides), GM)
    return get_success_data(res)


def evaluate_kpi(kpi, actual_value) -> dict:
    return get_success_data(
        api_client.evaluate_kpi(kpi["id"], {"actual_value": actual_value}, GM)
    )


def create_scorecard(account, **overrides) -> dict:
    res = api_client.create_scorecard(
        create_scorecard_payload(account["id"], **overrides), GM
    )
    return get_success_data(res)


def publish_scorecard(account, scorecard) -> dict:
    version = get_success_data(api_client.get_account(account["id"], ae_headers(account)))[
        "version"
    ]
    return get_success_data(
        api_client.publish_scorecard(
            scorecard["id"], {"expected_account_version": version}, GM
        )
    )


def create_audit(account, **overrides) -> dict:
    res = api_client.create_audit(create_audit_payload(account["id"], **overrides), GM)
    return get_success_data(res)


def start_audit(audit) -> dict:
    return get_success_data(api_client.start_audit(audit["id"], GM))


def decide_audit(audit, outcome="PASSED") -> dict:
    return get_success_data(
        api_client.decide_audit(audit["id"], {"outcome": outcome}, GM)
    )


def create_failed_audit(account, **overrides) -> dict:
    """DisciplineAudit driven to FAILED (remediation_required true, cooling-off set)."""
    audit = create_audit(account, **overrides)
    start_audit(audit)
    return decide_audit(audit, "FAILED")


def create_audit_review(audit, expected_account_version, **overrides) -> dict:
    payload = create_audit_review_payload(**overrides)
    payload["expected_account_version"] = expected_account_version
    return get_success_data(
        api_client.create_audit_review(audit["id"], payload, GM)
    )


# ─── Fee accruals & commission ────────────────────────

def create_commission_record(account, headers=None, **overrides) -> dict:
    res = api_client.create_commission_record(
        create_commission_record_payload(account["id"], **overrides),
        headers or TEST_USERS["account_executive_headers"],
    )
    return get_success_data(res)


def create_fee_accrual(account, **overrides) -> dict:
    res = api_client.create_fee_accrual(
        create_fee_accrual_payload(account["id"], **overrides), ae_headers(account)
    )
    return get_success_data(res)


def apply_credits_to_accrual(accrual) -> dict:
    return get_success_data(
        api_client.apply_lease_execution(accrual["id"], TM)
    )


# ─── Data licences ────────────────────────────────────

def create_data_license(account, **overrides) -> dict:
    res = api_client.create_data_license(
        create_data_license_payload(account["id"], **overrides), DS
    )
    return get_success_data(res)


def grant_data_license(license, consent=False) -> dict:
    payload = {"client_consent_confirmed": True} if consent else {}
    return get_success_data(
        api_client.grant_data_license(license["id"], payload, DS)
    )


def create_granted_data_license(account, consent=False, **overrides) -> dict:
    license = create_data_license(account, **overrides)
    return grant_data_license(license, consent=consent)


# ─── Transitions & closure ────────────────────────────

def begin_offboarding(account) -> dict:
    return get_success_data(api_client.begin_transition(account["id"], ae_headers(account)))


def create_transition_task(account, **overrides) -> dict:
    res = api_client.create_transition_task(
        create_transition_task_payload(account["id"], **overrides), TRANS
    )
    return get_success_data(res)


def start_transition_task(task) -> dict:
    return get_success_data(api_client.start_transition_task(task["id"], TRANS))


def complete_transition_task(task) -> dict:
    get_success_data(api_client.start_transition_task(task["id"], TRANS))
    return get_success_data(api_client.complete_transition_task(task["id"], TRANS))


def setup_offboarding_account(task_overrides=None, **account_overrides):
    """Active account driven to OFFBOARDING with one PENDING transition task.

    Returns (account, task).
    """
    account = create_activated_account(**account_overrides)
    account = begin_offboarding(account)
    defaults = {"task_name": "Records handover", "task_type": "DATA_HANDOVER"}
    defaults.update(task_overrides or {})
    task = create_transition_task(account, **defaults)
    return account, task


def setup_offboarding_with_complete_task(task_overrides=None, **account_overrides):
    """OFFBOARDING account whose single blocking task is DONE (completion 10000).

    Returns (account, task).
    """
    account, task = setup_offboarding_account(
        task_overrides=task_overrides, **account_overrides
    )
    task = complete_transition_task(task)
    return account, task


# ─── Tier 5: Terminal states ──────────────────────────

def setup_closed_converted_account(**account_overrides):
    """Account driven through OFFBOARDING to CLOSED_CONVERTED.

    Returns the CLOSED_CONVERTED account.
    """
    account, _task = setup_offboarding_with_complete_task(
        task_overrides={"task_type": "RECORDS_TRANSFER"}, **account_overrides
    )
    return get_success_data(
        api_client.close_converted_account(account["id"], ae_headers(account))
    )


def setup_termination_cascade_account(
    data_scope="LINE_ITEM", grant_consent=True, account_name="Cascade Co",
    **account_overrides,
):
    """Account ready for the termination cascade.

    The ACTIVE vendor, its OCCUPIED site and the GRANTED data licence are all
    created while the account is ACTIVE; the account is then driven to
    OFFBOARDING with a DONE blocking task so completion_pct_bps is 10000.

    ``account_name`` is unique per account (PRD §3.1), so the two tests that
    build this fixture in the same server session must pass distinct names.

    Returns (account, vendor, site, license).
    """
    account = create_activated_account(account_name=account_name, **account_overrides)
    vendor = create_active_vendor(account)
    site = create_site(
        account,
        vendor,
        site_name="Tower 360128",
        sqft=360_128,
        sqft_reduction=360_128,
    )
    license = create_granted_data_license(
        account, consent=grant_consent, data_scope=data_scope
    )
    account = begin_offboarding(account)
    task = create_transition_task(account)
    complete_transition_task(task)
    return account, vendor, site, license


def setup_offboarding_with_granted_licence(
    data_scope="AGGREGATE", consent=False, account_name="Licence Co",
    **account_overrides,
):
    """GRANTED licence captured before offboarding; account ready to close.

    Returns (account, license).
    """
    account = create_activated_account(account_name=account_name, **account_overrides)
    license = create_granted_data_license(
        account, consent=consent, data_scope=data_scope
    )
    account = begin_offboarding(account)
    task = create_transition_task(account, task_type="RECORDS_TRANSFER")
    complete_transition_task(task)
    return account, license


def set_clock(to_iso8601) -> dict:
    """Advance the logical clock as the AccountExecutive."""
    return get_success_data(
        api_client.set_clock(to_iso8601, TEST_USERS["account_executive_headers"])
    )


def get_account(account) -> dict:
    return get_success_data(api_client.get_account(account["id"], ae_headers(account)))

# ─── Specialised composites ───────────────────────────

def create_commission_record_tm(account, **overrides) -> dict:
    """Post a CommissionRecord as the TransactionManager."""
    res = api_client.create_commission_record(
        create_commission_record_payload(account["id"], **overrides), TM
    )
    return get_success_data(res)


def setup_executed_lease_with_accrual(
    accrual_period="2026-Q2", base_fee_cents=2_000_000, extra_record=None,
    clock="2026-10-01T00:00:00Z",
):
    """Active account with lease EXECUTED, plus an OPEN fee accrual.

    Drives the full transaction pipeline: account -> activate -> assignment ->
    lease -> request -> submit -> approve -> engagement -> assign ->
    launch-marketing -> open-negotiation -> engagement execute -> lease execute.
    Lease execution posts the THIRD_PARTY CommissionRecord derived from the
    request's prior rent and third-party commission.

    ``extra_record`` is an optional dict of overrides for an additional
    CommissionRecord posted after execution.

    Returns (account, lease, request, assignment, engagement, accrual).
    """
    if clock:
        set_clock(clock)
    account, assignment = create_account_with_approver()
    lease = create_lease(account)
    request = create_transaction_request(account, lease)
    submit_transaction_request(account, request)
    submit_lease_for_approval(lease)
    request = approve_transaction_request(request, assignment)
    engagement = create_broker_engagement(account, request)
    engagement = assign_broker_engagement(engagement)
    lease = get_success_data(api_client.launch_marketing(lease["id"], TM))
    lease = get_success_data(api_client.open_negotiation(lease["id"], TM))
    # PRD §3.4: the lease-execution route is the one that creates the THIRD_PARTY
    # CommissionRecord against the account fee. Executing the broker engagement
    # instead would drive the request to EXECUTED first and leave the lease route
    # with no APPROVED request to post from, so the two routes are alternatives —
    # whichever fires first consumes the request's third-party commission once.
    lease = get_success_data(api_client.execute_lease(lease["id"], TM))
    accrual = create_fee_accrual(
        account, period=accrual_period, base_fee_cents=base_fee_cents
    )
    if extra_record is not None:
        create_commission_record(account, **extra_record)
    return account, lease, request, assignment, engagement, accrual


def setup_two_vacated_sites_with_committed_window(
    first_window=("2026-10-01T00:00:00Z", "2026-12-01T00:00:00Z"),
    **account_overrides,
):
    """Account with an APPROVED project and two VACATED sites.

    The first site already carries a committed consolidation window; the second
    is VACATED and assigned to the same project, ready to commit a window.

    Returns (account, project, vendor, first_site, second_site, assignment).
    """
    account, assignment = create_account_with_approver(**account_overrides)
    vendor = create_active_vendor(account)
    project = create_approved_project(
        account,
        assignment,
        planned_sqft_reduction=65_003,
        cost_inflation_factor=1.05,
        per_site_rates=[3.335, 6.665],
        per_site_sqft_reductions=[40_001, 25_002],
    )
    first = create_site(
        account, vendor, site_name="Tower 42000", sqft=40_001,
        sqft_reduction=40_001, consolidation_project_id=project["id"],
    )
    first = vacate_site(first)
    first = consolidate_site(first, first_window[0], first_window[1])
    second = create_site(
        account, vendor, site_name="Tower 28500", sqft=25_002,
        sqft_reduction=25_002, consolidation_project_id=project["id"],
    )
    second = vacate_site(second)
    return account, project, vendor, first, second, assignment


def setup_sites_for_execution_gate(
    reductions=(40_001, 25_002), sqfts=(40_001, 25_002),
    **account_overrides,
):
    """Approved project whose assigned sites are still OCCUPIED.

    Returns (account, project, vendor, sites, assignment).
    """
    account, assignment = create_account_with_approver(**account_overrides)
    vendor = create_active_vendor(account)
    project = create_approved_project(
        account,
        assignment,
        planned_sqft_reduction=sum(reductions),
        cost_inflation_factor=1.05,
        per_site_rates=[3.335, 6.665],
        per_site_sqft_reductions=list(reductions),
    )
    sites = []
    for red, sqft in zip(reductions, sqfts):
        sites.append(
            create_site(
                account, vendor, site_name=f"Tower {sqft}", sqft=sqft,
                sqft_reduction=red, consolidation_project_id=project["id"],
            )
        )
    return account, project, vendor, sites, assignment


def setup_draft_account_with_vendor_elsewhere(
    name_active="Vendor Host Co", name_draft="DraftCo", **account_overrides
):
    """A DRAFT account plus a vendor persisted on a separate ACTIVE account.

    The vendor gives the oversized-site request a resolvable foreign key while
    the account under test stays non-ACTIVE.

    Returns (draft_account, vendor).
    """
    active = create_activated_account(
        account_name=name_active, client_name="GlobalTech Industries",
        **account_overrides,
    )
    vendor = create_active_vendor(active)
    draft = create_account(
        account_name=name_draft, client_name="Draft Holdings", **account_overrides
    )
    return draft, vendor


def submit_lease_for_approval(lease) -> dict:
    return get_success_data(api_client.submit_lease_for_approval(lease["id"], TM))


def reject_lease(lease) -> dict:
    return get_success_data(api_client.reject_lease(lease["id"], TM))


def approve_lease(lease) -> dict:
    return get_success_data(api_client.approve_lease(lease["id"], TM))


def revise_lease(lease, expected_account_version) -> dict:
    return get_success_data(
        api_client.revise_lease(
            lease["id"], {"expected_account_version": expected_account_version}, TM
        )
    )


def return_project_to_planning(project) -> dict:
    return get_success_data(
        api_client.return_consolidation_to_planning(project["id"], OP)
    )
