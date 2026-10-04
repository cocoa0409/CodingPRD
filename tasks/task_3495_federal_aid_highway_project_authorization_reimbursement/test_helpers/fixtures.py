"""Composite setup fixtures for the PRD §3 workflows.

Every fixture builds its preconditions from scratch through declared API
endpoints only — the harness restarts the server before every test, so each
test begins against an empty database. Setup calls go through
get_success_data() so a broken precondition fails with a clear message.

Clock discipline: the logical clock is write-only (POST
/_clock/set_current_utc), so fixtures thread explicit ISO dates forward and
never move the clock backwards. Every default date is >= CLOCK_START
(2026-09-01T00:00:00Z); standard milestones satisfy each window with slack
(31 vs 30 days, 22 vs 21 days; EIS uses exactly 45, the passing boundary).

Segregation of duties: change-order requests use the primary engineer and
state concurrence the alternate engineer; the final voucher is decided by
the primary FHWA reviewer and audits are created by the alternate reviewer.
"""
from typing import Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from . import factories
from .api_client import api_client
from .constants import (
    AUDIT_FINDINGS_RESPONSE_DAYS,
    CLOCK_START,
    DATE_AUDIT_FINALIZE,
    DATE_AUTHORIZE,
    DATE_OPEN_BIDS,
    DATE_STIP_SUBMIT,
    DEFAULT_AGREEMENT_NUMBER,
    DEFAULT_APPORTIONED_CENTS,
    DEFAULT_DBE_GOAL_PCT,
    DEFAULT_FFY,
    DEFAULT_INITIAL_OBLIGATED_CENTS,
    DEFAULT_PERIOD_END,
    DEFAULT_PERIOD_START,
    DEFAULT_PROJECT_COST_CENTS,
    DEFAULT_STATE_CODE,
    DEFAULT_STIP_START_FFY,
    EIS_COMMENT_PERIOD_DAYS,
    MIN_ADVERTISEMENT_DAYS,
    STIP_COMMENT_PERIOD_DAYS,
    iso_plus_days,
    max_iso,
)
from .test_users import TEST_USERS

H = TEST_USERS  # shorthand


def _setup(resp, what: str):
    data = get_success_data(resp)
    assert data is not None, f"Setup failed: {what} returned no data"
    return data


# ---------------------------------------------------------------------------
# Tier 0: clock + leaf creators
# ---------------------------------------------------------------------------
def set_clock(current_utc: str = CLOCK_START, headers: Optional[dict] = None) -> dict:
    return _setup(
        api_client.set_clock({"current_utc": current_utc}, headers or H["platform_admin"]),
        f"set clock to {current_utc}",
    )


def create_funding_program(
    code: str = "NHPP",
    eligible_activity_codes: Optional[List[str]] = None,
    name: Optional[str] = None,
    headers: Optional[dict] = None,
) -> dict:
    payload = factories.create_funding_program_payload(
        code=code, name=name, eligible_activity_codes=eligible_activity_codes
    )
    return _setup(
        api_client.create_funding_program(payload, headers or H["platform_admin"]),
        f"create funding program {code}",
    )


def create_apportionment(
    funding_program_id: str,
    state_code: str = DEFAULT_STATE_CODE,
    federal_fiscal_year: int = DEFAULT_FFY,
    apportioned_cents: int = DEFAULT_APPORTIONED_CENTS,
    headers: Optional[dict] = None,
) -> dict:
    payload = factories.create_apportionment_payload(
        funding_program_id,
        state_code=state_code,
        federal_fiscal_year=federal_fiscal_year,
        apportioned_cents=apportioned_cents,
    )
    return _setup(
        api_client.create_apportionment(payload, headers or H["fhwa_division_admin"]),
        f"create apportionment ({state_code}, FFY {federal_fiscal_year})",
    )


def create_stip(
    state_code: str = DEFAULT_STATE_CODE,
    land_pct: float = 0.0,
    start_ffy: int = DEFAULT_STIP_START_FFY,
    description: str = "Statewide Transportation Improvement Program",
    headers: Optional[dict] = None,
) -> dict:
    payload = factories.create_stip_payload(
        state_code=state_code,
        state_federal_land_pct=land_pct,
        start_federal_fiscal_year=start_ffy,
        description=description,
    )
    return _setup(
        api_client.create_stip(payload, headers or H["state_dot_planner"]),
        f"create STIP for {state_code}",
    )


def add_stip_comment(
    stip_id: str,
    author_name: str = "Public Citizen",
    comment_text: str = "Please fund this corridor.",
    headers: Optional[dict] = None,
) -> dict:
    payload = factories.create_comment_payload(author_name, comment_text)
    return _setup(
        api_client.create_stip_comment(
            stip_id, payload, headers or H["state_dot_planner"]
        ),
        f"add comment to STIP {stip_id}",
    )


def create_project(
    stip_id: str,
    funding_program_id: str,
    headers: Optional[dict] = None,
    **overrides,
) -> dict:
    """Nominate a project (lands NOMINATED). `overrides` are create-payload
    fields: route_name, description, activity_code, is_interstate_system,
    dbe_goal_pct, total_estimated_cost_cents."""
    payload = factories.create_project_payload(stip_id, funding_program_id, **overrides)
    return _setup(
        api_client.create_project(payload, headers or H["state_dot_planner"]),
        "create project",
    )


def submit_stip(stip_id: str, headers: Optional[dict] = None) -> dict:
    return _setup(
        api_client.submit_stip(stip_id, headers or H["state_dot_planner"]),
        f"submit STIP {stip_id}",
    )


def decide_stip(
    stip_id: str, decision: str = "APPROVE", headers: Optional[dict] = None
) -> dict:
    payload = factories.create_stip_decision_payload(decision)
    return _setup(
        api_client.decide_stip(stip_id, payload, headers or H["fhwa_division_admin"]),
        f"decide STIP {stip_id} {decision}",
    )


# ---------------------------------------------------------------------------
# Tier 1: STIP lifecycle (PUBLIC_INVOLVEMENT -> SUBMITTED -> APPROVED)
# ---------------------------------------------------------------------------
def create_submitted_stip(
    state_code: str = DEFAULT_STATE_CODE,
    land_pct: float = 0.0,
    start_ffy: int = DEFAULT_STIP_START_FFY,
    description: str = "Statewide Transportation Improvement Program",
    num_comments: int = 1,
    clock_start: str = CLOCK_START,
    submit_date: str = DATE_STIP_SUBMIT,
) -> dict:
    """STIP advanced to SUBMITTED: created at clock_start, comments recorded
    in the window, clock advanced past the 30-day window, then submitted."""
    set_clock(clock_start)
    stip = create_stip(state_code, land_pct, start_ffy, description)
    for i in range(num_comments):
        add_stip_comment(
            stip["id"],
            author_name=f"Public Citizen {i + 1}",
            comment_text=f"Comment {i + 1}.",
        )
    set_clock(max_iso(submit_date, iso_plus_days(clock_start, STIP_COMMENT_PERIOD_DAYS + 1)))
    return submit_stip(stip["id"])


def create_approved_stip(**kwargs) -> dict:
    """STIP run through the public-involvement cycle to APPROVED. With no
    projects, the fiscal-constraint check passes trivially."""
    stip = create_submitted_stip(**kwargs)
    return decide_stip(stip["id"], "APPROVE")


# ---------------------------------------------------------------------------
# Tier 2: program + STIP + projects pipeline (STIP lands APPROVED)
# ---------------------------------------------------------------------------
def setup_stip_pipeline(
    program_code: str = "NHPP",
    eligible_activity_codes: Optional[List[str]] = None,
    state_code: str = DEFAULT_STATE_CODE,
    land_pct: float = 0.0,
    start_ffy: int = DEFAULT_STIP_START_FFY,
    apportionments: Optional[Dict[int, int]] = None,
    project_specs: Optional[List[dict]] = None,
    description: str = "Statewide Transportation Improvement Program",
    clock_start: str = CLOCK_START,
    submit_date: str = DATE_STIP_SUBMIT,
) -> dict:
    """Clock -> funding program -> apportionment(s) -> STIP -> comment ->
    project(s) -> advance past the comment window -> submit -> APPROVE.

    `apportionments` maps FFY -> apportioned cents; the default covers the
    current-FFY cell. Pass {} explicitly for a no-capacity scenario.
    `project_specs` is a list of create-payload override dicts; the default
    is one standard project, [] for none. Projects are nominated BEFORE the
    approval decision (nomination is accepted regardless of STIP status, and
    their provisional estimates feed the approval's fiscal check).
    """
    set_clock(clock_start)
    program = create_funding_program(program_code, eligible_activity_codes)
    if apportionments is None:
        apportionments = {DEFAULT_FFY: DEFAULT_APPORTIONED_CENTS}
    apportionment_rows = {
        ffy: create_apportionment(
            program["id"], state_code=state_code, federal_fiscal_year=ffy,
            apportioned_cents=cents,
        )
        for ffy, cents in apportionments.items()
    }
    stip = create_stip(state_code, land_pct, start_ffy, description)
    add_stip_comment(stip["id"])
    specs = [{}] if project_specs is None else project_specs
    projects = [create_project(stip["id"], program["id"], **spec) for spec in specs]
    effective_submit = max_iso(
        submit_date, iso_plus_days(clock_start, STIP_COMMENT_PERIOD_DAYS + 1)
    )
    set_clock(effective_submit)
    stip = submit_stip(stip["id"])
    stip = decide_stip(stip["id"], "APPROVE")
    return {
        "program": program,
        "apportionments": apportionment_rows,
        "stip": stip,
        "projects": projects,
        "submit_date": effective_submit,
    }


# ---------------------------------------------------------------------------
# Tier 3: project progression (eligibility -> clearances -> authorization)
# ---------------------------------------------------------------------------
def determine_project_eligible(
    project_id: str, headers: Optional[dict] = None
) -> dict:
    payload = factories.create_determination_payload("ELIGIBLE")
    return _setup(
        api_client.determine_eligibility(
            project_id, payload, headers or H["fhwa_division_admin"]
        ),
        f"determine project {project_id} ELIGIBLE",
    )


def clear_project(
    project_id: str,
    nepa_class: str = "CE",
    row_cert_level: str = "LEVEL_1_FULL",
    engineer_headers: Optional[dict] = None,
    reviewer_headers: Optional[dict] = None,
) -> dict:
    """Open and clear both regulatory clearances of an ELIGIBLE project.
    For an EIS environmental clearance the clock is advanced exactly
    EIS_COMMENT_PERIOD_DAYS past the clearance's created_at before deciding
    (the exactly-45-days boundary passes); CE and EA carry no wait."""
    eng = engineer_headers or H["state_dot_engineer"]
    rev = reviewer_headers or H["fhwa_reviewer"]
    env = _setup(
        api_client.create_clearance(
            factories.create_clearance_payload(project_id, "ENVIRONMENTAL", nepa_class),
            eng,
        ),
        "create environmental clearance",
    )
    if nepa_class == "EIS":
        set_clock(iso_plus_days(env["created_at"], EIS_COMMENT_PERIOD_DAYS))
    env = _setup(
        api_client.decide_clearance(
            env["id"], factories.create_clearance_decision_payload("CLEARED"), rev
        ),
        "clear environmental clearance",
    )
    row = _setup(
        api_client.create_clearance(
            factories.create_clearance_payload(project_id, "RIGHT_OF_WAY", None), eng
        ),
        "create right-of-way clearance",
    )
    row = _setup(
        api_client.decide_clearance(
            row["id"],
            factories.create_clearance_decision_payload("CLEARED", row_cert_level),
            rev,
        ),
        "clear right-of-way clearance",
    )
    return {"environmental": env, "right_of_way": row}


def authorize_project(
    project_id: str,
    initial_obligated_cents: int = DEFAULT_INITIAL_OBLIGATED_CENTS,
    agreement_number: str = DEFAULT_AGREEMENT_NUMBER,
    auth_clock: str = DATE_AUTHORIZE,
    headers: Optional[dict] = None,
) -> dict:
    """Authorize an ELIGIBLE, fully cleared project. The clock is set to
    `auth_clock` first; the cell drawn is (program, state, FFY of auth_clock)."""
    set_clock(auth_clock)
    payload = factories.create_authorization_payload(
        project_id, agreement_number, initial_obligated_cents
    )
    return _setup(
        api_client.create_authorization(payload, headers or H["fhwa_division_admin"]),
        f"authorize project {project_id}",
    )


# ---------------------------------------------------------------------------
# Tier 4: advertisement -> bids -> award
# ---------------------------------------------------------------------------
def advertise_project(project_id: str, headers: Optional[dict] = None) -> dict:
    return _setup(
        api_client.advertise_project(project_id, headers or H["state_dot_engineer"]),
        f"advertise project {project_id}",
    )


def list_bids(project_id: str, headers: Optional[dict] = None) -> List[dict]:
    resp = api_client.list_project_bids(project_id, headers or H["fhwa_reviewer"])
    bids, _meta = validate_paginated(resp)
    return bids


def open_project_bids(
    project_id: str,
    bids: Optional[List[dict]] = None,
    bids_clock: str = DATE_OPEN_BIDS,
    headers: Optional[dict] = None,
) -> List[dict]:
    """Set the clock to `bids_clock` (must be >= advertised_on + 21 days),
    open the sealed bids, and return the created Bid rows in submission_seq
    order."""
    set_clock(bids_clock)
    payload = factories.create_open_bids_payload(bids)
    _setup(
        api_client.open_bids(project_id, payload, headers or H["state_dot_engineer"]),
        f"open bids for project {project_id}",
    )
    return list_bids(project_id)


def select_winning_bid(bids: List[dict]) -> dict:
    """Lowest responsive SUBMITTED bid; ties break by submission_seq."""
    candidates = [b for b in bids if b["is_responsive"] and b["status"] == "SUBMITTED"]
    assert candidates, "Setup failed: no responsive bids to award"
    return min(candidates, key=lambda b: (b["bid_amount_cents"], b["submission_seq"]))


def award_project(
    project_id: str,
    bid_id: str,
    dbe_commitment_pct: float = DEFAULT_DBE_GOAL_PCT,
    good_faith_effort_documented: Optional[bool] = None,
    headers: Optional[dict] = None,
) -> dict:
    payload = factories.create_award_payload(
        bid_id, dbe_commitment_pct, good_faith_effort_documented
    )
    return _setup(
        api_client.award_project(project_id, payload, headers or H["fhwa_reviewer"]),
        f"award project {project_id}",
    )


def progress_project_to_under_construction(
    project_id: str,
    initial_obligated_cents: int = DEFAULT_INITIAL_OBLIGATED_CENTS,
    agreement_number: str = DEFAULT_AGREEMENT_NUMBER,
    nepa_class: str = "CE",
    row_cert_level: str = "LEVEL_1_FULL",
    auth_clock: str = DATE_AUTHORIZE,
    submit_date: str = DATE_STIP_SUBMIT,
    bids: Optional[List[dict]] = None,
    dbe_commitment_pct: float = DEFAULT_DBE_GOAL_PCT,
) -> dict:
    """For a NOMINATED project of an APPROVED STIP: determine ELIGIBLE ->
    clear both clearances -> authorize -> advertise -> open bids -> award.
    The clock threads forward and never moves backwards."""
    project = determine_project_eligible(project_id)
    clearances = clear_project(project_id, nepa_class, row_cert_level)
    if nepa_class == "EIS":
        auth_clock = max_iso(auth_clock, iso_plus_days(submit_date, EIS_COMMENT_PERIOD_DAYS))
    authorization = authorize_project(
        project_id, initial_obligated_cents, agreement_number, auth_clock
    )
    project = advertise_project(project_id)
    bids_clock = max_iso(
        DATE_OPEN_BIDS, iso_plus_days(auth_clock, MIN_ADVERTISEMENT_DAYS + 1)
    )
    bid_rows = open_project_bids(project_id, bids, bids_clock)
    winner = select_winning_bid(bid_rows)
    project = award_project(project_id, winner["id"], dbe_commitment_pct)
    return {
        "project": project,
        "clearances": clearances,
        "authorization": authorization,
        "bids": bid_rows,
        "awarded_bid": winner,
        "auth_clock": auth_clock,
        "bids_clock": bids_clock,
    }


def setup_project_under_construction(
    program_code: str = "NHPP",
    eligible_activity_codes: Optional[List[str]] = None,
    activity_code: str = "ROAD_RESURFACING",
    is_interstate_system: bool = False,
    land_pct: float = 0.0,
    state_code: str = DEFAULT_STATE_CODE,
    project_cost_cents: int = DEFAULT_PROJECT_COST_CENTS,
    dbe_goal_pct: float = DEFAULT_DBE_GOAL_PCT,
    apportioned_cents: int = DEFAULT_APPORTIONED_CENTS,
    initial_obligated_cents: int = DEFAULT_INITIAL_OBLIGATED_CENTS,
    agreement_number: str = DEFAULT_AGREEMENT_NUMBER,
    nepa_class: str = "CE",
    row_cert_level: str = "LEVEL_1_FULL",
    auth_clock: str = DATE_AUTHORIZE,
    bids: Optional[List[dict]] = None,
    dbe_commitment_pct: Optional[float] = None,
) -> dict:
    """Complete pipeline through award: approved STIP with one project,
    ELIGIBLE, both clearances CLEARED, OBLIGATED authorization, advertised,
    bids opened, awarded to the lowest responsive bid — the project lands
    UNDER_CONSTRUCTION."""
    pipeline = setup_stip_pipeline(
        program_code=program_code,
        eligible_activity_codes=eligible_activity_codes,
        state_code=state_code,
        land_pct=land_pct,
        apportionments={DEFAULT_FFY: apportioned_cents},
        project_specs=[
            {
                "activity_code": activity_code,
                "is_interstate_system": is_interstate_system,
                "dbe_goal_pct": dbe_goal_pct,
                "total_estimated_cost_cents": project_cost_cents,
            }
        ],
    )
    progressed = progress_project_to_under_construction(
        pipeline["projects"][0]["id"],
        initial_obligated_cents=initial_obligated_cents,
        agreement_number=agreement_number,
        nepa_class=nepa_class,
        row_cert_level=row_cert_level,
        auth_clock=auth_clock,
        submit_date=pipeline["submit_date"],
        bids=bids,
        dbe_commitment_pct=(
            dbe_commitment_pct if dbe_commitment_pct is not None else dbe_goal_pct
        ),
    )
    return {**pipeline, **progressed}


# ---------------------------------------------------------------------------
# Tier 5: vouchers (progress billing)
# ---------------------------------------------------------------------------
def create_draft_voucher(
    authorization_id: str,
    period_start_date: str = DEFAULT_PERIOD_START,
    period_end_date: str = DEFAULT_PERIOD_END,
    line_items: Optional[List[dict]] = None,
    documentation_complete: bool = True,
    is_final: bool = False,
    headers: Optional[dict] = None,
    **overrides,
) -> dict:
    payload = factories.create_voucher_payload(
        authorization_id,
        period_start_date=period_start_date,
        period_end_date=period_end_date,
        line_items=line_items,
        documentation_complete=documentation_complete,
        is_final=is_final,
        **overrides,
    )
    return _setup(
        api_client.create_voucher(payload, headers or H["state_dot_engineer"]),
        "create voucher",
    )


def submit_voucher(
    voucher_id: str,
    revisions: Optional[dict] = None,
    headers: Optional[dict] = None,
) -> dict:
    """Submit a DRAFT voucher, or resubmit a REJECTED one with optional
    revised period/line_items/documentation_complete (PRD §3.7)."""
    return _setup(
        api_client.submit_voucher(
            voucher_id, headers or H["state_dot_engineer"], payload=revisions or {}
        ),
        f"submit voucher {voucher_id}",
    )


def decide_voucher(
    voucher_id: str,
    decision: str = "APPROVE",
    ineligible_line_indexes: Optional[List[int]] = None,
    headers: Optional[dict] = None,
) -> dict:
    payload = factories.create_voucher_decision_payload(decision, ineligible_line_indexes)
    return _setup(
        api_client.decide_voucher(voucher_id, payload, headers or H["fhwa_reviewer"]),
        f"decide voucher {voucher_id} {decision}",
    )


def create_submitted_voucher(
    authorization_id: str, headers: Optional[dict] = None, **voucher_kwargs
) -> dict:
    voucher = create_draft_voucher(authorization_id, headers=headers, **voucher_kwargs)
    return submit_voucher(voucher["id"], headers=headers)


def create_approved_voucher(
    authorization_id: str,
    ineligible_line_indexes: Optional[List[int]] = None,
    reviewer_headers: Optional[dict] = None,
    headers: Optional[dict] = None,
    **voucher_kwargs,
) -> dict:
    """Create + submit + APPROVE. On approval the reimbursement cascade
    posts: Authorization.reimbursed_cents grows, an exact draw flips it to
    FULLY_DRAWN, and an is_final voucher completes the project."""
    voucher = create_submitted_voucher(authorization_id, headers=headers, **voucher_kwargs)
    return decide_voucher(
        voucher["id"],
        "APPROVE",
        ineligible_line_indexes,
        headers=reviewer_headers or H["fhwa_reviewer"],
    )


# ---------------------------------------------------------------------------
# Tier 5: change orders (cost overruns)
# ---------------------------------------------------------------------------
def create_change_order(
    authorization_id: str,
    delta_cost_cents: int = 100_000,
    description: str = "Unforeseen site conditions",
    requester_headers: Optional[dict] = None,
) -> dict:
    """REQUESTED change order. The requester defaults to the primary state
    engineer; concurrence must use a DIFFERENT engineer (PRD §3.8 SoD)."""
    payload = factories.create_change_order_payload(
        authorization_id, description, delta_cost_cents
    )
    return _setup(
        api_client.create_change_order(
            payload, requester_headers or H["state_dot_engineer"]
        ),
        "create change order",
    )


def concur_change_order(
    change_order_id: str, concurrer_headers: Optional[dict] = None
) -> dict:
    """State concurrence. Defaults to the ALTERNATE engineer so the
    segregation-of-duties gate passes."""
    return _setup(
        api_client.state_concur_change_order(
            change_order_id, concurrer_headers or H["state_dot_engineer_alt"]
        ),
        f"state-concur change order {change_order_id}",
    )


def federal_decide_change_order(
    change_order_id: str,
    decision: str = "APPROVE",
    headers: Optional[dict] = None,
) -> dict:
    payload = factories.create_federal_decision_payload(decision)
    return _setup(
        api_client.federal_decide_change_order(
            change_order_id, payload, headers or H["fhwa_reviewer"]
        ),
        f"federal-decide change order {change_order_id} {decision}",
    )


def create_concurred_change_order(
    authorization_id: str,
    delta_cost_cents: int = 100_000,
    description: str = "Unforeseen site conditions",
) -> dict:
    co = create_change_order(authorization_id, delta_cost_cents, description)
    return concur_change_order(co["id"])


def create_approved_change_order(
    authorization_id: str,
    delta_cost_cents: int = 100_000,
    description: str = "Unforeseen site conditions",
) -> dict:
    """REQUESTED -> STATE_CONCURRED -> FEDERAL_APPROVED with participation
    cascade posted."""
    co = create_concurred_change_order(authorization_id, delta_cost_cents, description)
    return federal_decide_change_order(co["id"], "APPROVE")


# ---------------------------------------------------------------------------
# Tier 6: closeout (final voucher -> audit -> repayment -> CLOSED)
# ---------------------------------------------------------------------------
def setup_project_complete(
    reviewer_headers: Optional[dict] = None,
    final_voucher_kwargs: Optional[dict] = None,
    **pipeline_kwargs,
) -> dict:
    """Full pipeline through the final voucher: project lands COMPLETE.
    The final voucher is decided by `reviewer_headers` (default the primary
    FHWA reviewer) — the audit that follows must use a different reviewer
    (PRD §3.9 SoD), which setup_audit does by default."""
    ctx = setup_project_under_construction(**pipeline_kwargs)
    voucher_kwargs = {"is_final": True}
    if final_voucher_kwargs:
        voucher_kwargs.update(final_voucher_kwargs)
    final_voucher = create_approved_voucher(
        ctx["authorization"]["id"],
        reviewer_headers=reviewer_headers,
        **voucher_kwargs,
    )
    # The final-voucher approval moves the project UNDER_CONSTRUCTION ->
    # COMPLETE server-side (PRD §3.7); re-fetch so callers see the landed
    # state rather than the stale pre-voucher snapshot.
    project = get_success_data(
        api_client.get_project(ctx["project"]["id"], H["fhwa_reviewer"])
    )
    return {**ctx, "project": project, "final_voucher": final_voucher}


def create_audit(
    project_id: str, auditor_headers: Optional[dict] = None
) -> dict:
    """Initiate the closeout audit of a COMPLETE project. Defaults to the
    ALTERNATE reviewer so the auditor differs from the final voucher's
    approver (PRD §3.9 segregation of duties)."""
    payload = factories.create_audit_payload(project_id)
    return _setup(
        api_client.create_audit(payload, auditor_headers or H["fhwa_reviewer_alt"]),
        f"create audit for project {project_id}",
    )


def issue_audit_findings(
    audit_id: str,
    findings_text: str = "No ineligible expenditures found.",
    ineligible_amount_cents: int = 0,
    headers: Optional[dict] = None,
) -> dict:
    payload = factories.create_findings_payload(findings_text, ineligible_amount_cents)
    return _setup(
        api_client.issue_audit_findings(
            audit_id, payload, headers or H["fhwa_reviewer_alt"]
        ),
        f"issue findings on audit {audit_id}",
    )


def finalize_audit(audit_id: str, headers: Optional[dict] = None) -> dict:
    return _setup(
        api_client.finalize_audit(audit_id, headers or H["fhwa_reviewer_alt"]),
        f"finalize audit {audit_id}",
    )


def record_repayment(
    audit_id: str, amount_cents: int, headers: Optional[dict] = None
) -> dict:
    payload = factories.create_repayment_payload(amount_cents)
    return _setup(
        api_client.record_repayment(
            audit_id, payload, headers or H["fhwa_reviewer_alt"]
        ),
        f"record repayment {amount_cents} on audit {audit_id}",
    )


def setup_audit_issued(
    ineligible_amount_cents: int = 0,
    findings_text: str = "Findings.",
    **pipeline_kwargs,
) -> dict:
    """COMPLETE project + audit INITIATED + findings issued (FINDINGS_ISSUED)."""
    ctx = setup_project_complete(**pipeline_kwargs)
    audit = create_audit(ctx["project"]["id"])
    audit = issue_audit_findings(audit["id"], findings_text, ineligible_amount_cents)
    return {**ctx, "audit": audit}


def setup_finalized_audit(
    ineligible_amount_cents: int = 0,
    findings_text: str = "Findings.",
    finalize_date: str = DATE_AUDIT_FINALIZE,
    **pipeline_kwargs,
) -> dict:
    """Findings issued, clock advanced past the 30-day response window, then
    finalized. When repayment_due_cents == 0 the audit auto-continues to
    CLOSED in the same operation, firing the closeout cascade."""
    ctx = setup_audit_issued(
        ineligible_amount_cents=ineligible_amount_cents,
        findings_text=findings_text,
        **pipeline_kwargs,
    )
    effective_finalize = max_iso(
        finalize_date,
        iso_plus_days(ctx["bids_clock"], AUDIT_FINDINGS_RESPONSE_DAYS + 1),
    )
    set_clock(effective_finalize)
    audit = finalize_audit(ctx["audit"]["id"])
    return {**ctx, "audit": audit, "finalize_date": effective_finalize}


def setup_closed_out_project(
    ineligible_amount_cents: int = 0,
    repay: bool = True,
    **pipeline_kwargs,
) -> dict:
    """Full lifecycle to terminal: audit CLOSED (auto-close when no
    repayment is due, otherwise the exact due amount is recorded), which
    cascades the authorization deobligation and the project CLOSED_OUT."""
    ctx = setup_finalized_audit(
        ineligible_amount_cents=ineligible_amount_cents, **pipeline_kwargs
    )
    audit = ctx["audit"]
    if audit["status"] != "CLOSED" and repay:
        audit = record_repayment(audit["id"], audit["repayment_due_cents"])
    assert audit["status"] == "CLOSED", (
        f"Setup failed: audit did not close (status {audit['status']}, "
        f"repayment_due_cents {audit.get('repayment_due_cents')})"
    )
    return {**ctx, "audit": audit}


# ---------------------------------------------------------------------------
# Specialized: authorization driven to exactly FULLY_DRAWN
# ---------------------------------------------------------------------------
def setup_fully_drawn_authorization(
    program_code: str = "HSIP",
    activity_code: str = "ROAD_RESURFACING",
    line_amounts_cents: Optional[List[int]] = None,
    initial_obligated_cents: int = 190,
    project_cost_cents: int = 300,
    **pipeline_kwargs,
) -> dict:
    """Project UNDER_CONSTRUCTION whose one approved voucher draws the
    authorization to exactly zero remaining (OBLIGATED -> FULLY_DRAWN).

    Defaults mirror the pinned rounding example: HSIP share 0.90 applied to
    lines [105, 105] reimburses 95 + 95 = 190 == initial_obligated_cents.
    Callers overriding the share or lines must keep
    sum(per-line round_half_up(amount * share)) == initial_obligated_cents.
    """
    lines = line_amounts_cents or [105, 105]
    ctx = setup_project_under_construction(
        program_code=program_code,
        activity_code=activity_code,
        project_cost_cents=project_cost_cents,
        initial_obligated_cents=initial_obligated_cents,
        **pipeline_kwargs,
    )
    voucher = create_approved_voucher(
        ctx["authorization"]["id"],
        line_items=[
            factories.create_line_item(f"line {i + 1}", amount)
            for i, amount in enumerate(lines)
        ],
    )
    authorization = _setup(
        api_client.get_authorization(ctx["authorization"]["id"], H["fhwa_reviewer"]),
        "re-read authorization",
    )
    assert authorization["status"] == "FULLY_DRAWN", (
        f"Setup failed: expected FULLY_DRAWN, got {authorization['status']} "
        f"(reimbursed {authorization['reimbursed_cents']} / "
        f"obligated {authorization['obligated_cents']})"
    )
    return {**ctx, "voucher": voucher, "authorization": authorization}
