"""Composite scenario builders.

Almost every design instance opens with the same preamble: publish a
programme, qualify and screen an assessor, register an applicant, open an
initial cycle, confirm the team, plan and approve the work, witness it, and
raise a finding. That preamble is expressed once here as a chain of
``with_*`` steps over a shared context dictionary, and the ``scenario_*``
wrappers at the bottom stop the chain at a named cycle status.

Two rules the whole module obeys:

* Setup calls go through ``get_success_data``, so a broken preamble reports
  the failing step's error id instead of a downstream ``KeyError``.
* Identity headers are threaded per entity: each assessor gets its own
  ``LeadAssessor``/``TechnicalExpert``/``DecisionPanelMember`` header pair
  built from *that* assessor's id, and each organization gets its own
  ``ApplicantContact`` pair. No id is ever shared between two identities the
  PRD requires to be distinct.
"""

from typing import Any, Dict, List, Optional, Sequence, Tuple

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .constants import (
    ACTIVITY_CALIBRATION,
    CYCLE_INITIAL,
    DECISION_VOTING,
    DELIVERY_ON_SITE,
    EMPLOYMENT_CONTRACT,
    EMPLOYMENT_INTERNAL,
    NC_CRITICAL,
    OUTCOME_SATISFACTORY,
    PLAN_MODE_HYBRID,
    REVIEW_ACCEPT,
    ROLE_TYPE_LEAD_ASSESSOR,
    ROLE_TYPE_TECHNICAL_ASSESSOR,
    ROLE_TYPE_TECHNICAL_EXPERT,
    SCHEME_PUBLISHED,
    SCHEME_UNDER_REVIEW,
    SESSION_COMPLETED,
    EFFECTIVENESS_PASS,
)
from .test_users import (
    ASSESSMENT_MANAGER,
    SCHEME_MANAGER,
    make_applicant_contact_headers,
    make_decision_panel_member_headers,
    make_lead_assessor_headers,
    make_technical_expert_headers,
)

Context = Dict[str, Any]

# The instant every design instance parks the logical clock at before it
# starts building, and the instant it moves to before witnessing outcomes
# and findings are recorded.
CLOCK_BUILD_INSTANT = "2026-08-10T00:00:00Z"
CLOCK_BUILD_DATE = "2026-08-10"
CLOCK_ASSESSMENT_INSTANT = "2026-09-15T00:00:00Z"
CLOCK_ASSESSMENT_DATE = "2026-09-15"

PLANNED_START = "2026-09-07"
PLANNED_END = "2026-09-18"


# =========================================================================
# Single-call helpers
# =========================================================================


def set_clock(client, instant: str, headers: Optional[Dict] = None) -> None:
    """Move the logical clock; no stored resource is mutated by this call."""
    get_success_data(client.set_clock(instant, headers or SCHEME_MANAGER))


def create_scheme(client, program_code: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        client.create_scheme(f.scheme_payload(program_code, **overrides), SCHEME_MANAGER)
    )


def drive_scheme_status(
    client, scheme_id: str, to_status: str, revision_note: Optional[str] = None
) -> Dict[str, Any]:
    return get_success_data(
        client.set_scheme_status(
            scheme_id, f.scheme_status_payload(to_status, revision_note), SCHEME_MANAGER
        )
    )


def publish_scheme(client, scheme_id: str) -> Dict[str, Any]:
    """DRAFT to UNDER_REVIEW to PUBLISHED: the first publication."""
    drive_scheme_status(client, scheme_id, SCHEME_UNDER_REVIEW)
    return drive_scheme_status(client, scheme_id, SCHEME_PUBLISHED)


def republish_scheme(client, scheme_id: str, revision_note: str) -> Dict[str, Any]:
    """Re-open and publish again, which advances ``rule_revision``."""
    drive_scheme_status(client, scheme_id, SCHEME_UNDER_REVIEW)
    return drive_scheme_status(client, scheme_id, SCHEME_PUBLISHED, revision_note)


def create_published_scheme(client, program_code: str, **overrides: Any) -> Dict[str, Any]:
    scheme = create_scheme(client, program_code, **overrides)
    return publish_scheme(client, scheme["id"])


def register_assessor(
    client,
    full_name: str,
    email: str,
    employment_type: str = EMPLOYMENT_INTERNAL,
    annual_witness_capacity_days: Optional[int] = 20,
) -> Dict[str, Any]:
    return get_success_data(
        client.create_assessor(
            f.assessor_payload(
                full_name, email, employment_type, annual_witness_capacity_days
            ),
            ASSESSMENT_MANAGER,
        )
    )


def register_qualification(
    client,
    assessor_id: str,
    scheme_id: str,
    role_type: str = ROLE_TYPE_LEAD_ASSESSOR,
    years_experience: int = 8,
    declared_witness_days: int = 6,
    declared_training_modules: int = 3,
    last_witness_on: Optional[str] = "2026-05-10",
) -> Dict[str, Any]:
    return get_success_data(
        client.create_qualification(
            assessor_id,
            f.qualification_payload(
                scheme_id,
                role_type,
                years_experience,
                declared_witness_days,
                declared_training_modules,
                last_witness_on,
            ),
            ASSESSMENT_MANAGER,
        )
    )


def verify_qualification(
    client,
    qualification_id: str,
    verified_years_experience: int,
    verified_witness_days: int,
    verified_training_modules: int,
) -> Dict[str, Any]:
    return get_success_data(
        client.verify_evidence(
            qualification_id,
            f.verify_evidence_payload(
                verified_years_experience,
                verified_witness_days,
                verified_training_modules,
            ),
            SCHEME_MANAGER,
        )
    )


def screen_assessor(client, assessor_id: str) -> Dict[str, Any]:
    return get_success_data(client.screen_assessor(assessor_id, SCHEME_MANAGER))


def register_organization(
    client,
    legal_name: str,
    country_code: str = "DE",
    contact_email: str = "qa@acme.test",
) -> Dict[str, Any]:
    return get_success_data(
        client.create_organization(
            f.organization_payload(legal_name, country_code, contact_email),
            ASSESSMENT_MANAGER,
        )
    )


def open_initial_cycle(
    client,
    organization_id: str,
    scheme_id: str,
    requested_scope_lines: Optional[List[str]] = None,
    notice_days: Optional[int] = 30,
    cycle_type: str = CYCLE_INITIAL,
    headers: Optional[Dict] = None,
) -> Dict[str, Any]:
    return get_success_data(
        client.create_application(
            f.application_payload(
                organization_id,
                scheme_id,
                cycle_type,
                requested_scope_lines,
                notice_days,
            ),
            headers or ASSESSMENT_MANAGER,
        )
    )


def propose_team_member(
    client, application_id: str, assessor_id: str, role_type: str
) -> Dict[str, Any]:
    return get_success_data(
        client.propose_team_member(
            application_id,
            f.team_assignment_payload(assessor_id, role_type),
            ASSESSMENT_MANAGER,
        )
    )


def confirm_team_member(client, assignment_id: str) -> Dict[str, Any]:
    return get_success_data(
        client.confirm_team_assignment(assignment_id, ASSESSMENT_MANAGER)
    )


def read_application(client, application_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_application(application_id, ASSESSMENT_MANAGER))


def read_application_version(client, application_id: str) -> int:
    return read_application(client, application_id)["version"]


def read_nonconformity(client, nonconformity_id: str) -> Dict[str, Any]:
    return get_success_data(
        client.get_nonconformity(nonconformity_id, ASSESSMENT_MANAGER)
    )


def read_assessor(client, assessor_id: str) -> Dict[str, Any]:
    return get_success_data(client.get_assessor(assessor_id, ASSESSMENT_MANAGER))


def create_plan(
    client,
    application_id: str,
    on_site_days: int = 3,
    remote_days: int = 2,
    mode: str = PLAN_MODE_HYBRID,
    planned_start: str = PLANNED_START,
    planned_end: str = PLANNED_END,
    headers: Optional[Dict] = None,
) -> Dict[str, Any]:
    """Read the cycle's version immediately before creating, so that the
    optimistic-concurrency token of section 2.6 is always fresh."""
    version = read_application_version(client, application_id)
    return get_success_data(
        client.create_plan(
            application_id,
            f.plan_payload(
                version, on_site_days, remote_days, mode, planned_start, planned_end
            ),
            headers or ASSESSMENT_MANAGER,
        )
    )


def approve_plan(client, plan_id: str) -> Dict[str, Any]:
    return get_success_data(client.approve_plan(plan_id, ASSESSMENT_MANAGER))


def book_session(
    client,
    plan_id: str,
    assessor_id: str,
    starts_at: str,
    ends_at: str,
    activity_type: str = ACTIVITY_CALIBRATION,
    site_ref: str = "ACME-LAB-1",
    delivery_mode: str = DELIVERY_ON_SITE,
) -> Dict[str, Any]:
    return get_success_data(
        client.schedule_witness_session(
            plan_id,
            f.witness_session_payload(
                assessor_id, starts_at, ends_at, activity_type, site_ref, delivery_mode
            ),
            ASSESSMENT_MANAGER,
        )
    )


def complete_session(
    client,
    session_id: str,
    actor_headers: Dict[str, str],
    outcome: str = OUTCOME_SATISFACTORY,
    evidence_note: str = "Calibration activity witnessed end to end.",
) -> Dict[str, Any]:
    return get_success_data(
        client.record_session_outcome(
            session_id,
            f.session_outcome_payload(SESSION_COMPLETED, outcome, evidence_note),
            actor_headers,
        )
    )


def raise_finding(
    client,
    application_id: str,
    actor_headers: Dict[str, str],
    classification: str = NC_CRITICAL,
    clause_ref: str = "7.2.1",
    statement: str = "Uncertainty budget omits the reference standard drift term.",
) -> Dict[str, Any]:
    return get_success_data(
        client.raise_nonconformity(
            application_id,
            f.nonconformity_payload(clause_ref, classification, statement),
            actor_headers,
        )
    )


def close_assessment(client, application_id: str) -> Dict[str, Any]:
    return get_success_data(
        client.close_assessment(application_id, ASSESSMENT_MANAGER)
    )


def submit_response(
    client,
    nonconformity_id: str,
    applicant_headers: Dict[str, str],
    root_cause: str = "Template predates the 2025 reference standard change.",
    action_plan: str = "Rebuild the template and re-issue 42 affected certificates.",
) -> Dict[str, Any]:
    """Read the finding's version immediately before submitting (section 2.6)."""
    version = read_nonconformity(client, nonconformity_id)["version"]
    return get_success_data(
        client.submit_response(
            nonconformity_id,
            f.response_payload(version, root_cause, action_plan),
            applicant_headers,
        )
    )


def review_response(
    client,
    nonconformity_id: str,
    lead_headers: Dict[str, str],
    outcome: str = REVIEW_ACCEPT,
    review_note: str = "Root cause and plan address the systemic gap.",
) -> Dict[str, Any]:
    return get_success_data(
        client.review_response(
            nonconformity_id, f.review_payload(outcome, review_note), lead_headers
        )
    )


def verify_effectiveness(
    client,
    nonconformity_id: str,
    verifier_headers: Dict[str, str],
    outcome: str = EFFECTIVENESS_PASS,
    verified_evidence_count: int = 3,
) -> Dict[str, Any]:
    return get_success_data(
        client.verify_effectiveness(
            nonconformity_id,
            f.effectiveness_payload(outcome, verified_evidence_count),
            verifier_headers,
        )
    )


def read_voting_decision(client, application_id: str) -> Dict[str, Any]:
    """The single ``VOTING`` record of the cycle's current round."""
    rows = get_success_data(
        client.list_decisions(
            ASSESSMENT_MANAGER,
            {"application_id": application_id, "status": DECISION_VOTING},
        )
    )
    assert len(rows) == 1, f"Expected exactly one VOTING decision record, got {len(rows)}"
    return rows[0]


# =========================================================================
# The chained preamble
# =========================================================================
#
# The standard cast, used by every scenario wrapper:
#
#   lead  Lena Ahlgren, INTERNAL, capacity 20, LEAD_ASSESSOR qualification
#         declared 8 years / 6 witness days / 3 modules, verified 8 / 5 / 2
#   tech  Bruno Katz, CONTRACT, capacity 20, TECHNICAL_ASSESSOR qualification
#         declared 6 / 4 / 1, verified 6 / 4 / 1
#   org   Acme Calibration GmbH, DE
#
# Both qualifications clear their role's witness-day floor and the 60.00
# point bar, so both assessors reach GRANTED and then QUALIFIED.

LEAD_DECLARED = (8, 6, 3)
LEAD_VERIFIED = (8, 5, 2)
LEAD_LAST_WITNESS_ON = "2026-05-10"
TECH_DECLARED = (6, 4, 1)
TECH_VERIFIED = (6, 4, 1)
TECH_LAST_WITNESS_ON = "2026-06-01"

_HEADER_BUILDERS = {
    ROLE_TYPE_LEAD_ASSESSOR: make_lead_assessor_headers,
    ROLE_TYPE_TECHNICAL_ASSESSOR: make_technical_expert_headers,
    ROLE_TYPE_TECHNICAL_EXPERT: make_technical_expert_headers,
}


def new_context(client, program_code: str, **scheme_overrides: Any) -> Context:
    """Park the clock at the build instant and publish one programme once."""
    set_clock(client, CLOCK_BUILD_INSTANT)
    scheme = create_published_scheme(client, program_code, **scheme_overrides)
    return {
        "client": client,
        "scheme": scheme,
        "scheme_id": scheme["id"],
        "assessors": {},
        "assignments": {},
        "sessions": [],
        "findings": [],
    }


def with_assessor(
    ctx: Context,
    key: str,
    full_name: str,
    email: str,
    role_type: str,
    employment_type: str = EMPLOYMENT_INTERNAL,
    capacity_days: Optional[int] = 20,
    declared: Sequence[int] = LEAD_DECLARED,
    verified: Optional[Sequence[int]] = LEAD_VERIFIED,
    last_witness_on: Optional[str] = LEAD_LAST_WITNESS_ON,
    screen: bool = True,
) -> Context:
    """Recruit one assessor, register and verify one qualification, screen."""
    client = ctx["client"]
    assessor = register_assessor(
        client, full_name, email, employment_type, capacity_days
    )
    qualification = register_qualification(
        client,
        assessor["id"],
        ctx["scheme_id"],
        role_type,
        declared[0],
        declared[1],
        declared[2],
        last_witness_on,
    )
    if verified is not None:
        qualification = verify_qualification(
            client, qualification["id"], verified[0], verified[1], verified[2]
        )
    if screen:
        assessor = screen_assessor(client, assessor["id"])
    headers = _HEADER_BUILDERS[role_type](assessor["id"])
    ctx["assessors"][key] = {
        "assessor": assessor,
        "qualification": qualification,
        "headers": headers,
        "role_type": role_type,
    }
    ctx[f"{key}_id"] = assessor["id"]
    ctx[f"{key}_headers"] = headers
    ctx[f"{key}_qualification_id"] = qualification["id"]
    ctx[f"{key}_qualification"] = qualification
    return ctx


def with_lead(ctx: Context, key: str = "lead", **overrides: Any) -> Context:
    params: Dict[str, Any] = {
        "full_name": "Lena Ahlgren",
        "email": "lena.ahlgren@ab.test",
        "role_type": ROLE_TYPE_LEAD_ASSESSOR,
        "employment_type": EMPLOYMENT_INTERNAL,
        "declared": LEAD_DECLARED,
        "verified": LEAD_VERIFIED,
        "last_witness_on": LEAD_LAST_WITNESS_ON,
    }
    params.update(overrides)
    return with_assessor(ctx, key, **params)


def with_technical_assessor(ctx: Context, key: str = "tech", **overrides: Any) -> Context:
    params: Dict[str, Any] = {
        "full_name": "Bruno Katz",
        "email": "bruno.katz@ab.test",
        "role_type": ROLE_TYPE_TECHNICAL_ASSESSOR,
        "employment_type": EMPLOYMENT_CONTRACT,
        "declared": TECH_DECLARED,
        "verified": TECH_VERIFIED,
        "last_witness_on": TECH_LAST_WITNESS_ON,
    }
    params.update(overrides)
    return with_assessor(ctx, key, **params)


def with_panel_members(ctx: Context, count: int = 3) -> Context:
    """Qualified assessors who hold no team assignment on any cycle.

    Their independence is what makes them eligible to ballot: section 3.8
    bars a panel member who holds a team assignment of any status on the
    cycle under decision.
    """
    panel: List[Dict[str, Any]] = []
    for index in range(1, count + 1):
        key = f"panel{index}"
        with_assessor(
            ctx,
            key,
            full_name=f"Panel Member {index}",
            email=f"panel{index}@ab.test",
            role_type=ROLE_TYPE_TECHNICAL_EXPERT,
            employment_type=EMPLOYMENT_INTERNAL,
            declared=(8, 6, 3),
            verified=(8, 5, 2),
            last_witness_on=LEAD_LAST_WITNESS_ON,
        )
        member = ctx["assessors"][key]
        headers = make_decision_panel_member_headers(member["assessor"]["id"])
        member["panel_headers"] = headers
        ctx[f"{key}_panel_headers"] = headers
        panel.append(member)
    ctx["panel"] = panel
    return ctx


def with_organization(
    ctx: Context,
    key: str = "org",
    legal_name: str = "Acme Calibration GmbH",
    country_code: str = "DE",
    contact_email: str = "qa@acme.test",
) -> Context:
    organization = register_organization(
        ctx["client"], legal_name, country_code, contact_email
    )
    headers = make_applicant_contact_headers(organization["id"])
    ctx[key] = organization
    ctx[f"{key}_id"] = organization["id"]
    ctx[f"{key}_headers"] = headers
    if key == "org":
        ctx["applicant_headers"] = headers
    return ctx


def with_initial_cycle(
    ctx: Context,
    key: str = "app",
    organization_key: str = "org",
    requested_scope_lines: Optional[List[str]] = None,
    notice_days: Optional[int] = 30,
) -> Context:
    application = open_initial_cycle(
        ctx["client"],
        ctx[f"{organization_key}_id"],
        ctx["scheme_id"],
        requested_scope_lines,
        notice_days,
    )
    ctx[key] = application
    ctx[f"{key}_id"] = application["id"]
    return ctx


def with_confirmed_team(
    ctx: Context,
    members: Sequence[str] = ("lead",),
    application_key: str = "app",
) -> Context:
    """Propose and confirm each named assessor in its own declared role."""
    for member_key in members:
        member = ctx["assessors"][member_key]
        assignment = propose_team_member(
            ctx["client"],
            ctx[f"{application_key}_id"],
            member["assessor"]["id"],
            member["role_type"],
        )
        assignment = confirm_team_member(ctx["client"], assignment["id"])
        ctx["assignments"][member_key] = assignment
        ctx[f"ta_{member_key}_id"] = assignment["id"]
    return ctx


def with_approved_plan(
    ctx: Context,
    on_site_days: int = 3,
    remote_days: int = 2,
    mode: str = PLAN_MODE_HYBRID,
    planned_start: str = PLANNED_START,
    planned_end: str = PLANNED_END,
    application_key: str = "app",
    key: str = "plan",
    approve: bool = True,
) -> Context:
    plan = create_plan(
        ctx["client"],
        ctx[f"{application_key}_id"],
        on_site_days,
        remote_days,
        mode,
        planned_start,
        planned_end,
    )
    if approve:
        plan = approve_plan(ctx["client"], plan["id"])
    ctx[key] = plan
    ctx[f"{key}_id"] = plan["id"]
    return ctx


def with_booked_session(
    ctx: Context,
    assessor_key: str,
    starts_at: str,
    ends_at: str,
    activity_type: str = ACTIVITY_CALIBRATION,
    site_ref: str = "ACME-LAB-1",
    delivery_mode: str = DELIVERY_ON_SITE,
    plan_key: str = "plan",
    complete: bool = False,
    outcome: str = OUTCOME_SATISFACTORY,
    evidence_note: str = "Calibration activity witnessed end to end.",
) -> Context:
    session = book_session(
        ctx["client"],
        ctx[f"{plan_key}_id"],
        ctx["assessors"][assessor_key]["assessor"]["id"],
        starts_at,
        ends_at,
        activity_type,
        site_ref,
        delivery_mode,
    )
    if complete:
        session = complete_session(
            ctx["client"],
            session["id"],
            ctx["assessors"][assessor_key]["headers"],
            outcome,
            evidence_note,
        )
    ctx["sessions"].append(session)
    return ctx


def with_two_completed_sessions(ctx: Context, plan_key: str = "plan") -> Context:
    """Five witnessed assessor days across two completed sessions.

    The lead's slot runs 32 hours and therefore costs four assessor days;
    the technical assessor's runs eight hours and costs one.
    """
    with_booked_session(
        ctx,
        "lead",
        "2026-09-07T08:00:00Z",
        "2026-09-08T16:00:00Z",
        plan_key=plan_key,
        complete=True,
        evidence_note="Mass and temperature calibrations witnessed.",
    )
    with_booked_session(
        ctx,
        "tech",
        "2026-09-09T08:00:00Z",
        "2026-09-09T16:00:00Z",
        plan_key=plan_key,
        complete=True,
        evidence_note="Pressure calibration witnessed.",
    )
    return ctx


def with_finding(
    ctx: Context,
    classification: str = NC_CRITICAL,
    author_key: str = "lead",
    clause_ref: str = "7.2.1",
    statement: str = "Uncertainty budget omits the reference standard drift term.",
    application_key: str = "app",
) -> Context:
    finding = raise_finding(
        ctx["client"],
        ctx[f"{application_key}_id"],
        ctx["assessors"][author_key]["headers"],
        classification,
        clause_ref,
        statement,
    )
    ctx["findings"].append(finding)
    ctx["finding"] = finding
    ctx["finding_id"] = finding["id"]
    return ctx


def with_closed_assessment(ctx: Context, application_key: str = "app") -> Context:
    ctx[application_key] = close_assessment(ctx["client"], ctx[f"{application_key}_id"])
    return ctx


def with_accepted_response(ctx: Context, finding_key: str = "finding_id") -> Context:
    """Applicant responds, the lead assessor accepts."""
    submit_response(ctx["client"], ctx[finding_key], ctx["applicant_headers"])
    ctx["finding"] = review_response(
        ctx["client"], ctx[finding_key], ctx["lead_headers"], REVIEW_ACCEPT
    )
    return ctx


def with_effectiveness_pass(
    ctx: Context, finding_key: str = "finding_id", verified_evidence_count: int = 3
) -> Context:
    """The technical assessor -- a second pair of eyes -- closes the finding."""
    ctx["finding"] = verify_effectiveness(
        ctx["client"],
        ctx[finding_key],
        ctx["tech_headers"],
        EFFECTIVENESS_PASS,
        verified_evidence_count,
    )
    return ctx


def with_voting_decision(ctx: Context, application_key: str = "app") -> Context:
    decision = read_voting_decision(ctx["client"], ctx[f"{application_key}_id"])
    ctx["decision"] = decision
    ctx["decision_id"] = decision["id"]
    return ctx


# =========================================================================
# Scenario wrappers: the chain stopped at a named cycle status
# =========================================================================


def scenario_published_scheme(client, program_code: str, **scheme_overrides: Any) -> Context:
    """One programme, published once, so ``rule_revision`` is 1."""
    return new_context(client, program_code, **scheme_overrides)


def scenario_team_assigned(
    client,
    program_code: str,
    members: Sequence[str] = ("lead",),
    requested_scope_lines: Optional[List[str]] = None,
    scheme_overrides: Optional[Dict[str, Any]] = None,
    lead_overrides: Optional[Dict[str, Any]] = None,
    tech_overrides: Optional[Dict[str, Any]] = None,
    organization_overrides: Optional[Dict[str, Any]] = None,
) -> Context:
    """A cycle in ``TEAM_ASSIGNED`` with the named team confirmed."""
    ctx = new_context(client, program_code, **(scheme_overrides or {}))
    with_lead(ctx, **(lead_overrides or {}))
    if "tech" in members:
        with_technical_assessor(ctx, **(tech_overrides or {}))
    with_organization(ctx, **(organization_overrides or {}))
    with_initial_cycle(ctx, requested_scope_lines=requested_scope_lines)
    with_confirmed_team(ctx, members)
    return ctx


def scenario_planned(
    client,
    program_code: str,
    members: Sequence[str] = ("lead",),
    on_site_days: int = 3,
    remote_days: int = 2,
    mode: str = PLAN_MODE_HYBRID,
    **kwargs: Any,
) -> Context:
    """A cycle in ``PLANNED`` behind an ``APPROVED`` plan."""
    ctx = scenario_team_assigned(client, program_code, members, **kwargs)
    with_approved_plan(ctx, on_site_days, remote_days, mode)
    return ctx


def scenario_in_assessment(
    client, program_code: str, **kwargs: Any
) -> Context:
    """A cycle in ``IN_ASSESSMENT`` with two completed witnessing sessions."""
    ctx = scenario_planned(client, program_code, members=("lead", "tech"), **kwargs)
    with_two_completed_sessions(ctx)
    return ctx


def scenario_nc_open(
    client,
    program_code: str,
    classification: str = NC_CRITICAL,
    clock_instant: str = CLOCK_ASSESSMENT_INSTANT,
    **kwargs: Any,
) -> Context:
    """A cycle in ``NC_OPEN`` behind one blocking finding."""
    ctx = scenario_in_assessment(client, program_code, **kwargs)
    set_clock(client, clock_instant)
    with_finding(ctx, classification)
    with_closed_assessment(ctx)
    return ctx


def scenario_decision_pending(
    client,
    program_code: str,
    classification: str = NC_CRITICAL,
    verified_evidence_count: int = 3,
    **kwargs: Any,
) -> Context:
    """A cycle in ``DECISION_PENDING`` with one ``VOTING`` decision record."""
    ctx = scenario_nc_open(client, program_code, classification, **kwargs)
    with_accepted_response(ctx)
    with_effectiveness_pass(ctx, verified_evidence_count=verified_evidence_count)
    with_voting_decision(ctx)
    return ctx


# =========================================================================
# The decision panel and the granted scope
# =========================================================================

from .constants import VOTE_GRANT  # noqa: E402  (used only by the helpers below)


def cast_ballot(
    client,
    decision_id: str,
    panel_headers: Dict[str, str],
    vote: str = VOTE_GRANT,
    rationale: str = "Witnessing records support the full requested scope.",
) -> Dict[str, Any]:
    return get_success_data(
        client.cast_vote(decision_id, f.vote_payload(vote, rationale), panel_headers)
    )


def finalize_decision_record(
    client,
    decision_id: str,
    panel_headers: Dict[str, str],
    granted_scope_lines: Optional[List[str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        client.finalize_decision(
            decision_id, f.finalize_payload(granted_scope_lines), panel_headers
        )
    )


def read_only_scope(client, organization_id: str) -> Dict[str, Any]:
    rows = get_success_data(
        client.list_scopes(SCHEME_MANAGER, {"organization_id": organization_id})
    )
    assert len(rows) == 1, f"Expected exactly one scope, got {len(rows)}"
    return rows[0]


def with_unanimous_grant(
    ctx: Context,
    granted_scope_lines: Optional[List[str]] = None,
    organization_key: str = "org",
) -> Context:
    """Three independent GRANT ballots, then finalization by the third voter."""
    client = ctx["client"]
    for member in ctx["panel"]:
        cast_ballot(client, ctx["decision_id"], member["panel_headers"])
    ctx["decision"] = finalize_decision_record(
        client,
        ctx["decision_id"],
        ctx["panel"][-1]["panel_headers"],
        granted_scope_lines,
    )
    scope = read_only_scope(client, ctx[f"{organization_key}_id"])
    ctx["scope"] = scope
    ctx["scope_id"] = scope["id"]
    return ctx


def scenario_granted_scope(
    client,
    program_code: str,
    requested_scope_lines: Optional[List[str]] = None,
    clock_instant: str = CLOCK_ASSESSMENT_INSTANT,
    **kwargs: Any,
) -> Context:
    """A ``GRANTED`` cycle behind one ``ACTIVE`` scope.

    No finding is raised, so close-assessment moves the cycle straight to
    ``DECISION_PENDING`` and opens the round-1 record in ``VOTING``.
    """
    ctx = scenario_in_assessment(
        client, program_code, requested_scope_lines=requested_scope_lines, **kwargs
    )
    with_panel_members(ctx, 3)
    set_clock(client, clock_instant)
    with_closed_assessment(ctx)
    with_voting_decision(ctx)
    with_unanimous_grant(
        ctx,
        list(requested_scope_lines)
        if requested_scope_lines is not None
        else list(f.DEFAULT_SCOPE_LINES),
    )
    return ctx
