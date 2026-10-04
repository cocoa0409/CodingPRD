"""Composite setup fixtures (PRD §3 workflows).

Every fixture builds its preconditions from scratch through PRD §4 endpoints
— the server is restarted against an empty database before every test, so
nothing may be assumed to exist. Setup calls use the lenient
``get_success_data`` validator: a failure raises "Setup step failed" with the
server's error_id instead of a confusing assertion deep in a test.

Identity threading (PRD §2.1) is mandatory: Inspector calls carry
``make_inspector_headers(inspector["id"])`` and OperatorRep calls carry
``make_operator_rep_headers(operator["id"])`` — the shared fallback headers
in TEST_USERS are never used on ownership-gated endpoints.

Clock discipline: fixtures NEVER move the logical clock unless their
docstring says so. Tests pin the clock (``set_clock``) before calling a
fixture when a timestamp literal matters, and advance it themselves between
lifecycle steps. Default instants are >= the startup reading
2026-09-01T00:00:00Z (PRD §2.4).
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client as _api
from .constants import (
    ABATEMENT_BASE_DAYS,
    CONTEST_WINDOW_DAYS,
    TEST_DEFAULTS,
)
from .factories import (
    abate_citation_payload,
    add_days_to_date,
    add_days_to_timestamp,
    approve_mine_plan_payload,
    confirm_withdrawal_payload,
    create_citation_payload,
    create_contest_payload,
    create_ido_payload,
    create_inspection_cycle_payload,
    create_inspection_payload,
    create_inspector_payload,
    create_mine_payload,
    create_operator_payload,
    decide_contest_payload,
    extend_abatement_payload,
    publish_report_payload,
    reassign_inspection_payload,
    reject_mine_plan_payload,
    report_accident_payload,
    submit_mine_plan_payload,
    verify_citation_abatement_payload,
    verify_ido_abatement_payload,
)
from .test_users import (
    TEST_USERS,
    make_inspector_headers,
    make_operator_rep_headers,
)

_ADMIN = TEST_USERS["admin_headers"]
_DM = TEST_USERS["district_manager_headers"]
_JUDGE = TEST_USERS["commission_judge_headers"]

# Plan types required for the REGULAR-completion gate (PRD §3.3):
# UNDERGROUND mines need all three; SURFACE mines need EMERGENCY_RESPONSE.
REQUIRED_PLAN_TYPES = {
    "UNDERGROUND": ("VENTILATION", "ROOF_CONTROL", "EMERGENCY_RESPONSE"),
    "SURFACE": ("EMERGENCY_RESPONSE",),
}


# ─── Clock (PRD §2.4) ─────────────────────────────────────────────────────────

def set_clock(current_utc: str) -> dict:
    """Set the logical clock (MSHAAdmin). Also flips APPROVED mine plans whose
    next_revision_due_at has been reached to REVISION_DUE (PRD §3.7)."""
    return get_success_data(_api.set_clock(current_utc, _ADMIN))


def advance_clock_past_contest_window(citation: dict) -> str:
    """Move the clock strictly past issued_at + 30 days (issued_at + 31 days)
    so an uncontested assessment can be finalized (PRD §3.4). Returns the new
    clock reading."""
    target = add_days_to_timestamp(citation["issued_at"], CONTEST_WINDOW_DAYS + 1)
    set_clock(target)
    return target


# ─── Registry (PRD §3.1) ──────────────────────────────────────────────────────

def setup_operator(**overrides) -> dict:
    """Create one operator. Control size-tier points via
    ``annual_tonnage_tons=...``."""
    return get_success_data(_api.create_operator(create_operator_payload(**overrides), _ADMIN))


def setup_inspector(**overrides) -> dict:
    """Create one inspector (badge_number auto-uniqued). Control the
    assignment gates via ``certification=...`` / ``conflicted_operator_ids=...``."""
    return get_success_data(_api.create_inspector(create_inspector_payload(**overrides), _ADMIN))


def setup_mine(operator: dict = None, mine_type: str = "UNDERGROUND",
               activation_date: str = None, **overrides):
    """Create (operator if needed) + mine. Returns ``(operator, mine)``.
    A new mine starts status=ACTIVE, production_status=NORMAL, pov_status=NONE
    with no cycles (PRD §3.1)."""
    if operator is None:
        operator = setup_operator()
    payload = create_mine_payload(
        operator["id"],
        mine_type=mine_type,
        activation_date=activation_date or TEST_DEFAULTS["ACTIVATION_DATE"],
        **overrides,
    )
    mine = get_success_data(_api.create_mine(payload, _ADMIN))
    return operator, mine


def setup_registry(mine_type: str = "UNDERGROUND", tonnage: int = None,
                   certification: str = "BOTH", conflicted_operator_ids=None,
                   mine_overrides: dict = None):
    """The common triple: operator + mine + one inspector.
    Returns ``(operator, mine, inspector)``."""
    op_over = {}
    if tonnage is not None:
        op_over["annual_tonnage_tons"] = tonnage
    operator = setup_operator(**op_over)
    operator, mine = setup_mine(operator, mine_type=mine_type, **(mine_overrides or {}))
    insp_over = {"certification": certification}
    if conflicted_operator_ids is not None:
        insp_over["conflicted_operator_ids"] = conflicted_operator_ids
    inspector = setup_inspector(**insp_over)
    return operator, mine, inspector


# ─── Readback helpers (GETs are open to every business role, PRD §2.1) ───────

def refresh_operator(operator_id: str) -> dict:
    return get_success_data(_api.get_operator(operator_id, _ADMIN))


def refresh_mine(mine_id: str) -> dict:
    return get_success_data(_api.get_mine(mine_id, _ADMIN))


def refresh_inspector(inspector_id: str) -> dict:
    return get_success_data(_api.get_inspector(inspector_id, _ADMIN))


def refresh_cycle(cycle_id: str) -> dict:
    return get_success_data(_api.get_inspection_cycle(cycle_id, _ADMIN))


def refresh_inspection(inspection_id: str) -> dict:
    return get_success_data(_api.get_inspection(inspection_id, _ADMIN))


def refresh_citation(citation_id: str) -> dict:
    return get_success_data(_api.get_citation(citation_id, _ADMIN))


def refresh_ido(order_id: str) -> dict:
    return get_success_data(_api.get_imminent_danger_order(order_id, _ADMIN))


def refresh_contest(contest_id: str) -> dict:
    return get_success_data(_api.get_contest(contest_id, _ADMIN))


def refresh_plan(plan_id: str) -> dict:
    return get_success_data(_api.get_mine_plan(plan_id, _ADMIN))


def refresh_accident(accident_id: str) -> dict:
    return get_success_data(_api.get_accident(accident_id, _ADMIN))


def get_assessment_for_citation(citation_id: str) -> dict:
    """The citation's penalty-assessment listing carries zero or one element
    (PRD §2.10); exactly one exists once the citation exists. Returns it."""
    data, meta = validate_paginated(
        _api.list_citation_penalty_assessments(citation_id, _ADMIN)
    )
    assert len(data) == 1, (
        f"expected exactly one PenaltyAssessment for citation {citation_id}, "
        f"got {len(data)}"
    )
    return data[0]


# ─── Inspection lifecycle (PRD §3.3) ──────────────────────────────────────────

def assign_inspection(mine: dict, inspector: dict, kind: str = "SPOT",
                      cycle_id: str = None, accident_id: str = None,
                      planned_start_at: str = None, planned_end_at: str = None,
                      **overrides) -> dict:
    """Assign an inspection (DistrictManager). REGULAR requires cycle_id;
    ACCIDENT_INVESTIGATION requires accident_id. The default planned window
    (2026-09-01T08:00-12:00Z) is strictly positive; windows occupy the
    inspector's schedule under half-open semantics."""
    payload = create_inspection_payload(
        mine["id"],
        inspector["id"],
        kind=kind,
        cycle_id=cycle_id,
        accident_id=accident_id,
        planned_start_at=planned_start_at or TEST_DEFAULTS["PLANNED_START_AT"],
        planned_end_at=planned_end_at or TEST_DEFAULTS["PLANNED_END_AT"],
        **overrides,
    )
    return get_success_data(_api.create_inspection(payload, _DM))


def file_reviewed_inspection(mine: dict, inspector: dict, kind: str = "SPOT",
                             **kwargs) -> dict:
    """Assign + record the pre-entry mine-file review as the ASSIGNEE
    (X-User-ID == inspection.inspector_id). Returns FILE_REVIEWED inspection."""
    inspection = assign_inspection(mine, inspector, kind=kind, **kwargs)
    return get_success_data(
        _api.file_review_inspection(inspection["id"], make_inspector_headers(inspector["id"]))
    )


def in_progress_inspection(mine: dict, inspector: dict, kind: str = "SPOT",
                           **kwargs) -> dict:
    """Assign + file-review + start. Preconditions the caller must respect:
    no non-TERMINATED IDO at the mine (safety gate) and the inspector holds
    no other IN_PROGRESS inspection (engagement gate, capacity 1).
    Starting an ACCIDENT_INVESTIGATION flips its accident REPORTED ->
    UNDER_INVESTIGATION."""
    inspection = file_reviewed_inspection(mine, inspector, kind=kind, **kwargs)
    return get_success_data(
        _api.start_inspection(inspection["id"], make_inspector_headers(inspector["id"]))
    )


def completed_spot_inspection(mine: dict, inspector: dict, **kwargs) -> dict:
    """SPOT inspection walked to COMPLETED. SPOT / FOLLOW_UP /
    ACCIDENT_INVESTIGATION completions carry no plan gate and no quota
    crediting (PRD §3.3)."""
    inspection = in_progress_inspection(mine, inspector, kind="SPOT", **kwargs)
    return get_success_data(
        _api.complete_inspection(inspection["id"], make_inspector_headers(inspector["id"]))
    )


def reassign_inspection_flow(inspection: dict, new_inspector: dict) -> dict:
    """Reassign to another inspector (DistrictManager); the inspection stays
    ASSIGNED (self-loop) or returns FILE_REVIEWED -> ASSIGNED and
    file_reviewed_at resets to null."""
    return get_success_data(
        _api.reassign_inspection(
            inspection["id"], reassign_inspection_payload(new_inspector["id"]), _DM
        )
    )


def cancel_inspection_flow(inspection: dict) -> dict:
    """Cancel from ASSIGNED / FILE_REVIEWED / SUSPENDED (DistrictManager)."""
    return get_success_data(_api.cancel_inspection(inspection["id"], _DM))


# ─── Inspection cycles (PRD §3.2, §2.6) ───────────────────────────────────────

def open_cycle(mine: dict, period_start: str = None) -> dict:
    """Open the mine's next cycle with geometrically correct dates: cycle 1
    starts at the mine's activation_date; later cycles start the day after
    the latest prior period_end. Only one cycle may be OPEN at a time."""
    if period_start is None:
        cycles, _meta = validate_paginated(_api.list_inspection_cycles(mine["id"], _ADMIN))
        if not cycles:
            period_start = mine["activation_date"]
        else:
            latest_end = max(c["period_end"] for c in cycles)
            period_start = add_days_to_date(latest_end, 1)
    payload = create_inspection_cycle_payload(period_start, mine_type=mine["mine_type"])
    return get_success_data(_api.create_inspection_cycle(mine["id"], payload, _ADMIN))


def close_cycle(cycle: dict) -> dict:
    """Close a cycle (MSHAAdmin): COMPLIANT when completed_inspections >=
    required_inspections (early close permitted); after period_end an unmet
    cycle closes DELINQUENT."""
    return get_success_data(_api.close_inspection_cycle(cycle["id"], _ADMIN))


def setup_mine_with_open_cycle(mine_type: str = "UNDERGROUND", **registry_kwargs):
    """Operator + mine + inspector + OPEN cycle 1.
    Returns (operator, mine, inspector, cycle)."""
    operator, mine, inspector = setup_registry(mine_type=mine_type, **registry_kwargs)
    cycle = open_cycle(mine)
    return operator, mine, inspector, cycle


def setup_mine_with_delinquent_cycle(mine_type: str = "UNDERGROUND",
                                     activation_date: str = None,
                                     **registry_kwargs):
    """Cycle 1 closed DELINQUENT (unmet, clock moved past its period_end) and
    cycle 2 OPEN — the state the oldest-DELINQUENT-first crediting rule and
    the CURED transition operate on.

    CLOCK: this fixture advances the logical clock to the day after cycle 1's
    period_end (>= the startup reading for default dates).

    Returns a dict: operator, mine, inspector, cycle1 (DELINQUENT),
    cycle2 (OPEN)."""
    operator, mine, inspector = setup_registry(
        mine_type=mine_type,
        mine_overrides=(
            {"activation_date": activation_date} if activation_date else None
        ),
        **registry_kwargs,
    )
    cycle1 = open_cycle(mine)
    set_clock(add_days_to_date(cycle1["period_end"], 1) + "T00:00:00Z")
    cycle1 = close_cycle(refresh_cycle(cycle1["id"]))
    assert cycle1["status"] == "DELINQUENT", (
        f"cycle 1 should close DELINQUENT (unmet, period elapsed), got {cycle1['status']}"
    )
    cycle2 = open_cycle(refresh_mine(mine["id"]))
    return {
        "operator": operator,
        "mine": refresh_mine(mine["id"]),
        "inspector": inspector,
        "cycle1": cycle1,
        "cycle2": cycle2,
    }


# ─── Mine plans and the REGULAR-completion plan gate (PRD §3.3, §3.7) ────────

def submit_plan(mine: dict, operator: dict, plan_type: str,
                document_ref: str = None) -> dict:
    """Submit a plan as the owning OperatorRep (X-User-ID == operator.id);
    the server assigns revision_no = 1 + max prior revision of the same
    (mine, plan_type)."""
    payload = submit_mine_plan_payload(plan_type=plan_type)
    if document_ref is not None:
        payload["document_ref"] = document_ref
    return get_success_data(
        _api.submit_mine_plan(mine["id"], payload, make_operator_rep_headers(operator["id"]))
    )


def approve_plan(plan: dict) -> dict:
    """Approve a SUBMITTED plan (DistrictManager) under the OCC rule of
    PRD §2.8: the owning mine's version is re-read immediately before the
    call so expected_mine_version always matches. Approval stamps
    approved_at, sets next_revision_due_at = approved_at + 180 days,
    supersedes the previously APPROVED plan of the same (mine, plan_type),
    and increments Mine.version."""
    mine_id = plan["mine_id"]
    current_mine = refresh_mine(mine_id)
    return get_success_data(
        _api.approve_mine_plan(
            plan["id"], approve_mine_plan_payload(current_mine["version"]), _DM
        )
    )


def submit_and_approve_plan(mine: dict, operator: dict, plan_type: str,
                            document_ref: str = None) -> dict:
    """Submit + approve in one step. Returns the APPROVED plan."""
    return approve_plan(submit_plan(mine, operator, plan_type, document_ref))


def setup_required_plans(mine: dict, operator: dict) -> dict:
    """Approve every plan type the mine's type requires for the
    REGULAR-completion gate (UNDERGROUND: VENTILATION + ROOF_CONTROL +
    EMERGENCY_RESPONSE; SURFACE: EMERGENCY_RESPONSE alone). Returns
    {plan_type: approved_plan}."""
    plans = {}
    for plan_type in REQUIRED_PLAN_TYPES[mine["mine_type"]]:
        plans[plan_type] = submit_and_approve_plan(mine, operator, plan_type)
    return plans


def setup_regular_completion_ready(mine_type: str = "UNDERGROUND",
                                   **registry_kwargs) -> dict:
    """Full REGULAR-completion setup: operator + mine + inspector + OPEN
    cycle 1 + every required plan type APPROVED + a REGULAR inspection of
    that cycle IN_PROGRESS. Returns a dict with all of them."""
    operator, mine, inspector = setup_registry(mine_type=mine_type, **registry_kwargs)
    plans = setup_required_plans(mine, operator)
    mine = refresh_mine(mine["id"])
    cycle = open_cycle(mine)
    inspection = in_progress_inspection(
        mine, inspector, kind="REGULAR", cycle_id=cycle["id"]
    )
    return {
        "operator": operator,
        "mine": mine,
        "inspector": inspector,
        "plans": plans,
        "cycle": cycle,
        "inspection": inspection,
    }


def completed_regular_inspection(mine: dict, cycle: dict, inspector: dict,
                                 **kwargs) -> dict:
    """Walk a REGULAR inspection of the given cycle to COMPLETED as the
    assignee. The caller must have approved the required plans first (see
    setup_required_plans); completion runs the quota crediting of PRD §3.2
    and credits exactly one cycle."""
    inspection = in_progress_inspection(
        mine, inspector, kind="REGULAR", cycle_id=cycle["id"], **kwargs
    )
    return get_success_data(
        _api.complete_inspection(inspection["id"], make_inspector_headers(inspector["id"]))
    )


# ─── Citations, abatement, assessments (PRD §3.4) ────────────────────────────

def issue_citation(inspection: dict, mine: dict, inspector: dict,
                   **factor_overrides) -> dict:
    """Issue a citation as the assignee of an IN_PROGRESS inspection.
    factor_overrides controls the seven penalty factors (negligence,
    gravity_likelihood, gravity_severity, persons_affected,
    significant_and_substantial, repeat_violation) plus kind/standard_code.
    Issuance auto-creates the citation's PenaltyAssessment (PROPOSED)."""
    payload = create_citation_payload(inspection["id"], mine["id"], **factor_overrides)
    return get_success_data(
        _api.create_citation(payload, make_inspector_headers(inspector["id"]))
    )


def setup_citation(mine_type: str = "UNDERGROUND", tonnage: int = None,
                   citation_factors: dict = None, **registry_kwargs) -> dict:
    """SPOT inspection IN_PROGRESS + one citation issued on it.
    Returns {operator, mine, inspector, inspection, citation, assessment}."""
    operator, mine, inspector = setup_registry(
        mine_type=mine_type, tonnage=tonnage, **registry_kwargs
    )
    inspection = in_progress_inspection(mine, inspector, kind="SPOT")
    citation = issue_citation(inspection, mine, inspector, **(citation_factors or {}))
    assessment = get_assessment_for_citation(citation["id"])
    return {
        "operator": operator,
        "mine": mine,
        "inspector": inspector,
        "inspection": inspection,
        "citation": citation,
        "assessment": assessment,
    }


def issue_n_citations(inspection: dict, mine: dict, inspector: dict, n: int,
                      factor_overrides: dict = None, standard_code_prefix: str = "30 CFR 75.") -> list:
    """Issue n citations on the same IN_PROGRESS inspection, each with a
    distinct standard_code so repeat/history semantics stay caller-controlled
    (history counts priors regardless of standard; repeat_violation is an
    issuer-set boolean). Returns the citations in issuance order."""
    citations = []
    for i in range(n):
        over = dict(factor_overrides or {})
        over.setdefault("standard_code", f"{standard_code_prefix}{200 + i}")
        citations.append(issue_citation(inspection, mine, inspector, **over))
    return citations


def abate_citation_flow(citation: dict, operator: dict) -> dict:
    """Operator reports abatement (OPEN -> ABATED, stamps abated_at).
    Abatement after the deadline is accepted but forfeits good faith (PRD
    §3.4). X-User-ID must be the mine's operator."""
    return get_success_data(
        _api.abate_citation(
            citation["id"], abate_citation_payload(), make_operator_rep_headers(operator["id"])
        )
    )


def extend_citation_flow(citation: dict, operator: dict) -> dict:
    """The single permitted abatement extension: only while the abatement
    axis is OPEN and the clock reads strictly before the current deadline;
    adds ceil(base_days / 2) days (30->15, 15->8, 5->3, 1->1)."""
    return get_success_data(
        _api.extend_citation_abatement(
            citation["id"], extend_abatement_payload(), make_operator_rep_headers(operator["id"])
        )
    )


def verify_citation_flow(citation: dict, verifier: dict) -> dict:
    """Verify abatement (ABATED -> VERIFIED) as an inspector OTHER than the
    issuer — segregation of duties (ERR_SOD_VERIFY_SELF on the issuer)."""
    return get_success_data(
        _api.verify_citation_abatement(
            citation["id"],
            verify_citation_abatement_payload(),
            make_inspector_headers(verifier["id"]),
        )
    )


def setup_verified_citation(citation_factors: dict = None, mine_type: str = "UNDERGROUND",
                            tonnage: int = None, **registry_kwargs) -> dict:
    """Citation abated by the operator and verified on time by a SECOND
    inspector (same logical-clock reading throughout => verified_at <=
    abatement_deadline, so the good-faith discount applies at finalization).
    Returns the setup_citation bundle plus ``verifier``."""
    bundle = setup_citation(
        mine_type=mine_type, tonnage=tonnage, citation_factors=citation_factors,
        **registry_kwargs,
    )
    verifier = setup_inspector()
    bundle["citation"] = abate_citation_flow(bundle["citation"], bundle["operator"])
    bundle["citation"] = verify_citation_flow(bundle["citation"], verifier)
    bundle["verifier"] = verifier
    bundle["assessment"] = get_assessment_for_citation(bundle["citation"]["id"])
    return bundle


def finalize_assessment_flow(assessment: dict) -> dict:
    """Finalize an uncontested PROPOSED assessment (MSHAAdmin). The caller
    must first move the clock strictly past citation.issued_at + 30 days —
    see advance_clock_past_contest_window()."""
    return get_success_data(_api.finalize_penalty_assessment(assessment["id"], _ADMIN))


def setup_finalizable_assessment(citation_factors: dict = None,
                                 verified_on_time: bool = False, **kwargs) -> dict:
    """Citation + PROPOSED assessment with the contest window lapsed (clock
    advanced to issued_at + 31 days). When verified_on_time is true the
    citation is abated + verified (on time) before the advance, so the final
    variant applies the 10% good-faith discount. Returns the bundle."""
    if verified_on_time:
        bundle = setup_verified_citation(citation_factors=citation_factors, **kwargs)
    else:
        bundle = setup_citation(citation_factors=citation_factors, **kwargs)
    advance_clock_past_contest_window(bundle["citation"])
    bundle["assessment"] = get_assessment_for_citation(bundle["citation"]["id"])
    return bundle


# ─── Imminent-danger orders (PRD §3.5) ────────────────────────────────────────

def issue_ido(mine: dict, inspector: dict, hazard_description: str = None,
              inspection_id: str = None) -> dict:
    """Issue an imminent-danger order as the given inspector. Requires the
    mine ACTIVE, no other non-TERMINATED order at the mine, and issuance
    strictly after any prior order's terminated_at. The cascade fires
    immediately: mine.production_status -> HALTED and every IN_PROGRESS
    inspection at the mine -> SUSPENDED."""
    payload = create_ido_payload(mine["id"], inspection_id=inspection_id)
    if hazard_description is not None:
        payload["hazard_description"] = hazard_description
    return get_success_data(
        _api.create_imminent_danger_order(payload, make_inspector_headers(inspector["id"]))
    )


def confirm_ido_withdrawal_flow(order: dict, inspector: dict,
                                miners_withdrawn_count: int = None) -> dict:
    """ISSUED -> WITHDRAWAL_CONFIRMED with the supplied miner count (>= 0)."""
    return get_success_data(
        _api.confirm_ido_withdrawal(
            order["id"],
            confirm_withdrawal_payload(miners_withdrawn_count),
            make_inspector_headers(inspector["id"]),
        )
    )


def verify_ido_abatement_flow(order: dict, verifier: dict) -> dict:
    """WITHDRAWAL_CONFIRMED -> ABATEMENT_VERIFIED as an inspector OTHER than
    the issuer (ERR_SOD_VERIFY_SELF otherwise)."""
    return get_success_data(
        _api.verify_ido_abatement(
            order["id"], verify_ido_abatement_payload(), make_inspector_headers(verifier["id"])
        )
    )


def terminate_ido_flow(order: dict) -> dict:
    """ABATEMENT_VERIFIED -> TERMINATED (DistrictManager). When no other
    non-TERMINATED order remains at the mine, production_status returns to
    NORMAL and every SUSPENDED inspection resumes to IN_PROGRESS."""
    return get_success_data(_api.terminate_ido(order["id"], _DM))


def setup_terminated_ido(mine_type: str = "UNDERGROUND", **registry_kwargs) -> dict:
    """An IDO walked ISSUED -> WITHDRAWAL_CONFIRMED -> ABATEMENT_VERIFIED ->
    TERMINATED, using a second inspector as verifier. The mine ends back at
    production_status NORMAL. Returns {operator, mine, issuer, verifier,
    order}."""
    operator, mine, issuer = setup_registry(mine_type=mine_type, **registry_kwargs)
    verifier = setup_inspector()
    order = issue_ido(mine, issuer)
    order = confirm_ido_withdrawal_flow(order, issuer)
    order = verify_ido_abatement_flow(order, verifier)
    order = terminate_ido_flow(order)
    return {
        "operator": operator,
        "mine": refresh_mine(mine["id"]),
        "issuer": issuer,
        "verifier": verifier,
        "order": order,
    }


def setup_mine_with_active_ido(mine_type: str = "UNDERGROUND", **registry_kwargs) -> dict:
    """Mine carrying one non-TERMINATED IDO (ISSUED): production_status
    HALTED. For safety-gate (ERR_IMMINENT_DANGER_ACTIVE), cascade, and
    one-active-order (ERR_IDO_ACTIVE_EXISTS) probes. Returns {operator, mine,
    issuer, order}."""
    operator, mine, issuer = setup_registry(mine_type=mine_type, **registry_kwargs)
    order = issue_ido(mine, issuer)
    return {
        "operator": operator,
        "mine": refresh_mine(mine["id"]),
        "issuer": issuer,
        "order": order,
    }


# ─── Contests and commission adjudication (PRD §3.6) ─────────────────────────

def file_contest_flow(citation: dict, operator: dict, grounds: str = None) -> dict:
    """File a contest as the owning OperatorRep. The citation's current
    version is re-read immediately before filing so expected_citation_version
    satisfies the OCC rule (PRD §2.8). Timeliness requires filing on or
    before issued_at + 30 days. Side effects: citation contest axis
    UNCONTESTED -> CONTESTED (version +1) and its assessment PROPOSED ->
    CONTESTED."""
    current = refresh_citation(citation["id"])
    payload = create_contest_payload(current["id"], current["version"])
    if grounds is not None:
        payload["grounds"] = grounds
    return get_success_data(
        _api.create_contest(payload, make_operator_rep_headers(operator["id"]))
    )


def docket_contest_flow(contest: dict) -> dict:
    """FILED -> DOCKETED (CommissionJudge)."""
    return get_success_data(_api.docket_contest(contest["id"], _JUDGE))


def decide_contest_flow(contest: dict, outcome: str,
                        modified_penalty_cents: int = None) -> dict:
    """DOCKETED -> DECIDED (CommissionJudge). Outcome propagates: AFFIRMED
    finalizes at the final-variant pipeline (good-faith when verified on
    time); MODIFIED finalizes at max(modified_penalty_cents, floor) with no
    discount; VACATED finalizes at 0 and excludes the citation from POV and
    history windows from decided_at onward."""
    return get_success_data(
        _api.decide_contest(
            contest["id"], decide_contest_payload(outcome, modified_penalty_cents), _JUDGE
        )
    )


def withdraw_contest_flow(contest: dict, operator: dict) -> dict:
    """Withdraw from FILED or DOCKETED as the FILING operator — a compensating
    action: citation contest axis CONTESTED -> UNCONTESTED (version +1) and
    assessment CONTESTED -> PROPOSED."""
    return get_success_data(
        _api.withdraw_contest(contest["id"], make_operator_rep_headers(operator["id"]))
    )


def setup_contested_citation(citation_factors: dict = None, docketed: bool = False,
                             **kwargs) -> dict:
    """Citation with an open contest (FILED, or DOCKETED when docketed=True).
    Returns the setup_citation bundle plus ``contest``."""
    bundle = setup_citation(citation_factors=citation_factors, **kwargs)
    contest = file_contest_flow(bundle["citation"], bundle["operator"])
    if docketed:
        contest = docket_contest_flow(contest)
    bundle["contest"] = contest
    bundle["citation"] = refresh_citation(bundle["citation"]["id"])
    bundle["assessment"] = get_assessment_for_citation(bundle["citation"]["id"])
    return bundle


# ─── Accidents (PRD §3.7) ─────────────────────────────────────────────────────

def report_accident_flow(mine: dict, operator: dict, occurred_at: str,
                         severity: str = "FATAL", description: str = None) -> dict:
    """Report an accident as the owning OperatorRep (mine must be ACTIVE).
    late_report is a strict-greater-than comparison: > 900s for FATAL,
    > 7200s otherwise; exactly at the limit is timely. A late report
    auto-issues the fixed-factor '50.10 LATE REPORT' citation."""
    payload = report_accident_payload(mine["id"], occurred_at, severity=severity)
    if description is not None:
        payload["description"] = description
    return get_success_data(
        _api.report_accident(payload, make_operator_rep_headers(operator["id"]))
    )


def setup_accident_under_investigation(mine_type: str = "SURFACE",
                                       occurred_at: str = None, severity: str = "LOST_TIME",
                                       **registry_kwargs) -> dict:
    """Accident reported and under investigation: an ACCIDENT_INVESTIGATION
    inspection assigned to the inspector, file-reviewed, and started — the
    start flips the accident REPORTED -> UNDER_INVESTIGATION. Default
    occurred_at is the startup reading (timely for either severity)."""
    operator, mine, inspector = setup_registry(mine_type=mine_type, **registry_kwargs)
    accident = report_accident_flow(
        mine, operator,
        occurred_at or "2026-09-01T00:00:00Z",
        severity=severity,
    )
    inspection = in_progress_inspection(
        mine, inspector, kind="ACCIDENT_INVESTIGATION", accident_id=accident["id"]
    )
    return {
        "operator": operator,
        "mine": mine,
        "inspector": inspector,
        "accident": refresh_accident(accident["id"]),
        "inspection": inspection,
    }


def setup_completed_accident_investigation(**kwargs) -> dict:
    """The investigation inspection COMPLETED (no plan gate, no crediting),
    leaving the accident UNDER_INVESTIGATION and publishable."""
    bundle = setup_accident_under_investigation(**kwargs)
    bundle["inspection"] = get_success_data(
        _api.complete_inspection(
            bundle["inspection"]["id"],
            make_inspector_headers(bundle["inspector"]["id"]),
        )
    )
    return bundle


def publish_report_flow(accident: dict, root_cause: str = None,
                        report_text: str = None) -> dict:
    """Publish the public report (MSHAAdmin); requires a COMPLETED
    ACCIDENT_INVESTIGATION inspection (ERR_ACCIDENT_INVESTIGATION_INCOMPLETE)
    and both root_cause and report_text (ERR_INVALID_REQUEST)."""
    payload = publish_report_payload()
    if root_cause is not None:
        payload["root_cause"] = root_cause
    if report_text is not None:
        payload["report_text"] = report_text
    return get_success_data(_api.publish_accident_report(accident["id"], payload, _ADMIN))


def setup_published_accident(**kwargs) -> dict:
    """Accident walked REPORTED -> UNDER_INVESTIGATION -> REPORT_PUBLISHED;
    its public projection becomes readable (before publication the public
    read answers ERR_NOT_FOUND as if absent)."""
    bundle = setup_completed_accident_investigation(**kwargs)
    bundle["accident"] = publish_report_flow(bundle["accident"])
    return bundle


# ─── Pattern of violations (PRD §3.7) ─────────────────────────────────────────

def issue_citations_for_pov(mine: dict, inspector: dict, specs: list,
                            base_date: str = "2026-09-01") -> list:
    """Issue one citation per spec, each on its own SPOT inspection walked
    ASSIGNED -> FILE_REVIEWED -> IN_PROGRESS -> COMPLETED. Each spec is a
    dict of citation factor overrides (e.g.
    {"significant_and_substantial": True, "negligence": "HIGH"}).

    Planned windows are spread one day apart (base_date + i days,
    08:00-12:00) so the per-inspector double-booking gate (half-open
    windows) never trips, and each inspection is completed before the next
    starts (engagement gate, capacity 1). The fixture does NOT move the
    clock; callers pin it first when window membership matters (the POV
    window is screened_at - 365 days, exclusive, through screened_at
    inclusive). Returns the citations in issuance order."""
    citations = []
    for i, spec in enumerate(specs):
        day = add_days_to_date(base_date, i)
        inspection = in_progress_inspection(
            mine,
            inspector,
            kind="SPOT",
            planned_start_at=f"{day}T08:00:00Z",
            planned_end_at=f"{day}T12:00:00Z",
        )
        citations.append(issue_citation(inspection, mine, inspector, **spec))
        get_success_data(
            _api.complete_inspection(
                inspection["id"], make_inspector_headers(inspector["id"])
            )
        )
    return citations


def run_screening(mine: dict) -> dict:
    """Run a SCREENING-variant POV evaluation (MSHAAdmin). Result
    POTENTIAL_POV iff weighted_score >= 8; escalates a NONE mine to
    POTENTIAL_POV, and a below-threshold result relaxes a POTENTIAL_POV mine
    back to NONE."""
    return get_success_data(_api.run_pov_screening(mine["id"], _ADMIN))


def setup_potential_pov_mine(mine_type: str = "UNDERGROUND", ss_citations: int = 4,
                             **registry_kwargs) -> dict:
    """Mine escalated to POTENTIAL_POV: ``ss_citations`` S&S citations
    (MODERATE negligence, no HIGH/RECKLESS bonus, no IDOs) give
    weighted_score = 2 * ss_citations; the default 4 land exactly on the
    threshold of 8. Returns {operator, mine, inspector, citations,
    screening}."""
    operator, mine, inspector = setup_registry(mine_type=mine_type, **registry_kwargs)
    specs = [
        {
            "significant_and_substantial": True,
            "negligence": "MODERATE",
            "gravity_likelihood": "UNLIKELY",
            "gravity_severity": "NO_INJURY",
            "persons_affected": 1,
            "repeat_violation": False,
        }
    ] * ss_citations
    citations = issue_citations_for_pov(mine, inspector, specs)
    screening = run_screening(mine)
    return {
        "operator": operator,
        "mine": refresh_mine(mine["id"]),
        "inspector": inspector,
        "citations": citations,
        "screening": screening,
    }


def setup_pov_final_mine(mine_type: str = "UNDERGROUND", **registry_kwargs) -> dict:
    """Mine escalated all the way to POV_FINAL: screening (POTENTIAL_POV)
    then the DistrictManager's POV notice (FINAL_DETERMINATION variant,
    weighted_score >= 8). Side effects: every OPEN cycle gains one required
    inspection, and from now on every newly issued S&S citation at the mine
    auto-creates an ImminentDangerOrder. Returns the potential-POV bundle
    plus ``notice``."""
    bundle = setup_potential_pov_mine(mine_type=mine_type, **registry_kwargs)
    notice = get_success_data(_api.issue_pov_notice(bundle["mine"]["id"], _DM))
    bundle["notice"] = notice
    bundle["mine"] = refresh_mine(bundle["mine"]["id"])
    return bundle


# ─── Abatement deadline helper ────────────────────────────────────────────────

def expected_abatement_deadline(issued_at: str, gravity_severity: str,
                                extended: bool = False) -> str:
    """Reference deadline: issued_at + base days (30/15/5/1 by severity),
    plus ceil(base/2) days once when extended (PRD §3.4)."""
    from .factories import abatement_extension_days

    days = ABATEMENT_BASE_DAYS[gravity_severity]
    if extended:
        days += abatement_extension_days(gravity_severity)
    return add_days_to_timestamp(issued_at, days)
