"""Composite fixtures that walk the API to a wanted state.

Every test starts against an empty deployment (the harness restarts the
server before each test), so each test builds the world it needs through the
public API only. These helpers do that walking and return the entity bodies
(and therefore the live ``version`` counters) the test then asserts against.

Organisation, simplest to most far-reaching:

  Tier 1  clock and single-entity creation
  Tier 2  the certification chain and the case assignment chain
  Tier 3  full lifecycle shortcuts: mediation, resolution, escalation,
          referral, statements and awards
  Tier 4  accumulation helpers: caseload filling, resolved-case stockpiling
  Tier 5  composite "world" builder used by the pytest ``world`` fixture

Setup calls use the lenient success reader, so a failure inside a fixture is
reported as a setup failure rather than as a confusing assertion error.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import ApiClient
from . import factories as f
from .constants import CLOCK_STARTUP_DEFAULT, CORE_MODULES
from .test_users import (
    AGENCY_REVIEWER_HEADERS,
    ANONYMOUS_HEADERS,
    COORDINATOR_ADMIN_HEADERS,
    COORDINATOR_HEADERS,
    COORDINATOR_LEAD_HEADERS,
    make_employer_headers,
    make_ombudsman_headers,
    make_service_member_headers,
)

# Core-module training template: hours and passing exam scores that together
# satisfy the 20-hour / >= 80 certification standard (8 + 8 + 6 = 22 hours).
CORE_TRAINING_TEMPLATE = (
    {"module_code": "CORE_LAW", "hours": 8, "exam_score": 90, "completed_on": "2026-08-01T00:00:00Z"},
    {"module_code": "MEDIATION_SKILLS", "hours": 8, "exam_score": 88, "completed_on": "2026-08-05T00:00:00Z"},
    {"module_code": "DOCUMENTATION", "hours": 6, "exam_score": 95, "completed_on": "2026-08-10T00:00:00Z"},
)

# Issue types that trigger the employer-education documentation requirement.
EDUCATION_ISSUE_TYPES = ("BENEFITS", "PENSION")


# ═══ Tier 1: clock and single-entity creation ══════════════════════════════

def set_clock(api: ApiClient, to_iso8601: str = CLOCK_STARTUP_DEFAULT) -> None:
    """Move the logical clock. The clock endpoint returns no resource payload."""
    get_success_data(api.set_clock(f.clock_payload(to_iso8601), COORDINATOR_HEADERS))


def create_employer(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api.create_employer(f.employer_payload(**overrides), COORDINATOR_HEADERS))


def create_member(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api.create_member(f.member_payload(**overrides), ANONYMOUS_HEADERS))


def create_ombudsman(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api.create_ombudsman(f.ombudsman_payload(**overrides), ANONYMOUS_HEADERS))


def create_service_period(
    api: ApiClient,
    member_id: str,
    employer_id: str,
    as_coordinator: bool = False,
    **overrides: Any,
) -> Dict[str, Any]:
    """Record a service period; defaults to the member recording their own."""
    headers = COORDINATOR_HEADERS if as_coordinator else make_service_member_headers(member_id)
    return get_success_data(
        api.create_service_period(f.service_period_payload(member_id, employer_id, **overrides), headers)
    )


def create_case(api: ApiClient, member_id: str, employer_id: str, **overrides: Any) -> Dict[str, Any]:
    """File a case; the filing member must be the caller per the ownership rule."""
    return get_success_data(
        api.create_case(f.case_payload(member_id, employer_id, **overrides), make_service_member_headers(member_id))
    )


def create_event(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api.create_event(f.event_payload(**overrides), COORDINATOR_HEADERS))


def read_case(api: ApiClient, case_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api.get_case(case_id, headers or COORDINATOR_HEADERS))


def read_ombudsman(api: ApiClient, ombudsman_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_ombudsman(ombudsman_id, COORDINATOR_HEADERS))


def read_employer(api: ApiClient, employer_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_employer(employer_id, COORDINATOR_HEADERS))


# ═══ Tier 2: certification and assignment chains ═══════════════════════════

def add_training_record(
    api: ApiClient,
    ombudsman_id: str,
    module_code: str = "CORE_LAW",
    hours: float = 8,
    exam_score: int = 90,
    completed_on: str = "2026-08-01T00:00:00Z",
    proctor_headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Record one training module; the acting coordinator is stamped proctor_id."""
    headers = proctor_headers or COORDINATOR_ADMIN_HEADERS
    payload = f.training_record_payload(
        ombudsman_id,
        module_code=module_code,
        hours=hours,
        exam_score=exam_score,
        completed_on=completed_on,
        **overrides,
    )
    return get_success_data(api.create_training_record(payload, headers))


def transition_ombudsman(
    api: ApiClient,
    ombudsman_id: str,
    to_status: str,
    headers: Optional[Dict[str, str]] = None,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    payload = f.ombudsman_state_payload(to_status, reason=reason)
    return get_success_data(api.transition_ombudsman(ombudsman_id, payload, headers or COORDINATOR_HEADERS))


def certify_ombudsman(
    api: ApiClient,
    ombudsman_id: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Certify a TRAINEE. The default certifier never proctored the standard
    fixture's records, so the segregation-of-duties screen passes."""
    return transition_ombudsman(api, ombudsman_id, "CERTIFIED", headers or COORDINATOR_LEAD_HEADERS)


def create_certified_ombudsman(
    api: ApiClient,
    training_template: Any = CORE_TRAINING_TEMPLATE,
    proctor_headers: Optional[Dict[str, str]] = None,
    certifier_headers: Optional[Dict[str, str]] = None,
    **ombudsman_overrides: Any,
) -> Dict[str, Any]:
    """Signup + the three core records (proctored) + certification.

    Returns the ombudsman body as of the certification response, carrying
    status CERTIFIED, certified_on and certification_expires_on.
    """
    ombudsman = create_ombudsman(api, **ombudsman_overrides)
    for record in training_template:
        add_training_record(api, ombudsman["id"], proctor_headers=proctor_headers, **record)
    return certify_ombudsman(api, ombudsman["id"], headers=certifier_headers)


def transition_case(
    api: ApiClient,
    case_id: str,
    to_status: str,
    headers: Dict[str, str],
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    payload = f.case_state_payload(to_status, reason=reason)
    return get_success_data(api.transition_case(case_id, payload, headers))


def triage_case(api: ApiClient, case_id: str) -> Dict[str, Any]:
    """INTAKE -> TRIAGE by a coordinator; returns the case at version 2."""
    return transition_case(api, case_id, "TRIAGE", COORDINATOR_HEADERS)


def assign_case(api: ApiClient, case_id: str, ombudsman_id: str, expected_case_version: int) -> Dict[str, Any]:
    """TRIAGE/ASSIGNED -> ASSIGNED under OCC; returns the case with version bumped."""
    payload = f.assign_payload(ombudsman_id, expected_case_version)
    return get_success_data(api.assign_case(case_id, payload, COORDINATOR_HEADERS))


def create_assigned_case(
    api: ApiClient,
    employer: Dict[str, Any],
    member: Dict[str, Any],
    ombudsman: Dict[str, Any],
    **case_overrides: Any,
) -> Dict[str, Any]:
    """File + triage + assign. Returns the case in ASSIGNED (version 3)."""
    case = create_case(api, member["id"], employer["id"], **case_overrides)
    case = triage_case(api, case["id"])
    return assign_case(api, case["id"], ombudsman["id"], case["version"])


def add_case_note(
    api: ApiClient,
    case_id: str,
    note_type: str = "CONTACT",
    body: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    payload = f.case_note_payload(case_id, note_type=note_type, body=body or f"{note_type} note.")
    return get_success_data(api.create_case_note(payload, headers or COORDINATOR_HEADERS))


# ═══ Tier 3: lifecycle shortcuts ═══════════════════════════════════════════

def open_round(
    api: ApiClient,
    case_id: str,
    ombudsman_id: str,
    proposal_text: str = "Reinstate at prior role with back pay.",
    addressed_to: str = "EMPLOYER",
) -> Dict[str, Any]:
    """Open a mediation round as the assigned ombudsman; case -> AWAITING_RESPONSE."""
    payload = f.mediation_round_payload(case_id, proposal_text=proposal_text, addressed_to=addressed_to)
    return get_success_data(api.create_mediation_round(payload, make_ombudsman_headers(ombudsman_id)))


def respond_to_round(
    api: ApiClient,
    round_id: str,
    response: str,
    headers: Dict[str, str],
    counter_text: Optional[str] = None,
) -> Dict[str, Any]:
    payload = f.round_response_payload(response, counter_text=counter_text)
    return get_success_data(api.respond_to_round(round_id, payload, headers))


def respond_as_employer(api: ApiClient, round_id: str, employer_id: str, response: str,
                        counter_text: Optional[str] = None) -> Dict[str, Any]:
    return respond_to_round(api, round_id, response, make_employer_headers(employer_id), counter_text)


def respond_as_member(api: ApiClient, round_id: str, member_id: str, response: str,
                      counter_text: Optional[str] = None) -> Dict[str, Any]:
    return respond_to_round(api, round_id, response, make_service_member_headers(member_id), counter_text)


def add_documentation_notes(
    api: ApiClient,
    case_id: str,
    issue_type: str = "REEMPLOYMENT",
    contact_count: int = 1,
) -> List[Dict[str, Any]]:
    """Append the notes the documentation standard demands: one INTAKE, at
    least as many CONTACT notes as the case has rounds, one RESOLUTION, and -
    for BENEFITS or PENSION cases - one EMPLOYER_EDUCATION."""
    notes = [add_case_note(api, case_id, "INTAKE", "Intake interview completed.")]
    for index in range(contact_count):
        notes.append(add_case_note(api, case_id, "CONTACT", f"Party contact documented ({index + 1})."))
    notes.append(add_case_note(api, case_id, "RESOLUTION", "Terms memorialized."))
    if issue_type in EDUCATION_ISSUE_TYPES:
        notes.append(add_case_note(api, case_id, "EMPLOYER_EDUCATION", "Employer educated on benefit duties."))
    return notes


def resolve_case_informally(
    api: ApiClient,
    case_id: str,
    ombudsman_id: str,
    employer_id: Optional[str] = None,
    member_id: Optional[str] = None,
    addressed_to: str = "EMPLOYER",
    issue_type: str = "REEMPLOYMENT",
) -> Dict[str, Any]:
    """Drive a case from ASSIGNED to RESOLVED_INFORMAL through an ACCEPT.

    Documents the case (one CONTACT per the single round this helper opens),
    opens one round, and has the addressed party accept it. Returns the final
    case, the round, and the notes.
    """
    add_case_note(api, case_id, "INTAKE", "Intake interview completed.")
    mediation_round = open_round(api, case_id, ombudsman_id, addressed_to=addressed_to)
    add_case_note(api, case_id, "CONTACT", "Employer contacted for round 1.")
    add_case_note(api, case_id, "RESOLUTION", "Terms memorialized.")
    if issue_type in EDUCATION_ISSUE_TYPES:
        add_case_note(api, case_id, "EMPLOYER_EDUCATION", "Employer educated on benefit duties.")
    if addressed_to == "EMPLOYER":
        mediation_round = respond_as_employer(api, mediation_round["id"], employer_id, "ACCEPT")
    else:
        mediation_round = respond_as_member(api, mediation_round["id"], member_id, "ACCEPT")
    return {
        "case": read_case(api, case_id),
        "round": mediation_round,
    }


def escalate_case(
    api: ApiClient,
    case_id: str,
    employer_id: str,
    ombudsman_id: str,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    """Drive a case from ASSIGNED to ESCALATION_PENDING: one round, a DECLINE
    from the employer, then the assigned ombudsman escalates. Returns the
    escalated case and the declined round."""
    mediation_round = open_round(api, case_id, ombudsman_id)
    mediation_round = respond_as_employer(api, mediation_round["id"], employer_id, "DECLINE")
    case = transition_case(
        api, case_id, "ESCALATION_PENDING", make_ombudsman_headers(ombudsman_id), reason=reason
    )
    return {"case": case, "round": mediation_round}


def create_draft_referral(
    api: ApiClient,
    case_id: str,
    ombudsman_id: str,
    agency: str = "DOL_VETS",
    summary: str = "Informal resolution failed; statutory violation alleged.",
) -> Dict[str, Any]:
    """Draft a referral as the assigned ombudsman (case must be ESCALATION_PENDING)."""
    payload = f.referral_payload(case_id, agency=agency, summary=summary)
    return get_success_data(api.create_referral(payload, make_ombudsman_headers(ombudsman_id)))


def transition_referral(
    api: ApiClient,
    referral_id: str,
    to_status: str,
    headers: Optional[Dict[str, str]] = None,
    info_request_note: Optional[str] = None,
) -> Dict[str, Any]:
    payload = f.referral_state_payload(to_status, info_request_note=info_request_note)
    return get_success_data(api.transition_referral(referral_id, payload, headers or COORDINATOR_HEADERS))


def submit_referral(api: ApiClient, referral_id: str) -> Dict[str, Any]:
    """DRAFT -> SUBMITTED by a coordinator (first submission is window-checked)."""
    return transition_referral(api, referral_id, "SUBMITTED", COORDINATOR_HEADERS)


def setup_escalated_case_with_referral(
    api: ApiClient,
    employer: Dict[str, Any],
    member: Dict[str, Any],
    ombudsman: Dict[str, Any],
    agency: str = "DOL_VETS",
    **case_overrides: Any,
) -> Dict[str, Any]:
    """Assigned case -> declined round -> escalated -> DRAFT referral.

    Returns the case (ESCALATION_PENDING), the declined round, and the DRAFT
    referral, plus the parties, so a test can drive the submission cascade.
    """
    case = create_assigned_case(api, employer, member, ombudsman, **case_overrides)
    escalated = escalate_case(api, case["id"], employer["id"], ombudsman["id"])
    referral = create_draft_referral(api, case["id"], ombudsman["id"], agency=agency)
    return {
        "case": escalated["case"],
        "round": escalated["round"],
        "referral": referral,
        "employer": employer,
        "member": member,
        "ombudsman": ombudsman,
    }


def create_statement(
    api: ApiClient,
    employer_id: str,
    as_employer: bool = False,
    **overrides: Any,
) -> Dict[str, Any]:
    """Pledge a statement of support (PLEDGED)."""
    headers = make_employer_headers(employer_id) if as_employer else COORDINATOR_HEADERS
    return get_success_data(api.create_statement(f.statement_payload(employer_id, **overrides), headers))


def transition_statement(
    api: ApiClient,
    statement_id: str,
    to_status: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api.transition_statement(statement_id, f.statement_state_payload(to_status), headers or COORDINATOR_HEADERS)
    )


def sign_statement(api: ApiClient, statement_id: str, employer_id: Optional[str] = None) -> Dict[str, Any]:
    """PLEDGED/LAPSED -> SIGNED; as the employer itself when employer_id is given."""
    headers = make_employer_headers(employer_id) if employer_id else COORDINATOR_HEADERS
    return transition_statement(api, statement_id, "SIGNED", headers)


def create_signed_statement(api: ApiClient, employer_id: str, **overrides: Any) -> Dict[str, Any]:
    statement = create_statement(api, employer_id, **overrides)
    return sign_statement(api, statement["id"], employer_id)


def nominate_award(
    api: ApiClient,
    employer_id: str,
    tier: str = "BRONZE",
    rationale: str = "Clean informal resolutions and a signed statement.",
    headers: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload = f.award_payload(employer_id, tier=tier, rationale=rationale)
    return get_success_data(api.create_award(payload, headers or COORDINATOR_HEADERS))


def transition_award(api: ApiClient, award_id: str, to_status: str) -> Dict[str, Any]:
    return get_success_data(api.transition_award(award_id, f.award_state_payload(to_status), COORDINATOR_HEADERS))


def run_analysis(
    api: ApiClient,
    case_id: str,
    variant: str,
    expected_case_version: int,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Store an eligibility analysis under OCC; bumps the case version by 1."""
    payload = f.eligibility_analysis_payload(variant=variant, expected_case_version=expected_case_version)
    return get_success_data(api.create_eligibility_analysis(case_id, payload, headers or COORDINATOR_HEADERS))


def create_benefit_assessment(
    api: ApiClient,
    case_id: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_benefit_assessment(f.benefit_assessment_payload(case_id), headers or COORDINATOR_HEADERS)
    )


def transition_event(api: ApiClient, event_id: str, to_status: str) -> Dict[str, Any]:
    return get_success_data(api.transition_event(event_id, f.event_state_payload(to_status), COORDINATOR_HEADERS))


# ═══ Tier 4: accumulation helpers ══════════════════════════════════════════

def setup_member_with_service(
    api: ApiClient,
    employer_id: str,
    periods: List[Dict[str, Any]],
    member_overrides: Optional[Dict[str, Any]] = None,
    case_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Create a member, record each service period (member's own call), then
    file their case against the employer. Returns member, periods and case."""
    member = create_member(api, **(member_overrides or {}))
    created_periods = [
        create_service_period(api, member["id"], employer_id, **period) for period in periods
    ]
    case = create_case(api, member["id"], employer_id, **(case_overrides or {}))
    return {"member": member, "periods": created_periods, "case": case}


def fill_caseload(
    api: ApiClient,
    employer_id: str,
    ombudsman_id: str,
    count: int = 4,
    start_index: int = 1,
) -> List[Dict[str, Any]]:
    """Assign ``count`` fresh TRIAGE cases to one ombudsman, driving their
    active_caseload to exactly ``count``. Returns the member/case pairs."""
    assigned: List[Dict[str, Any]] = []
    for index in range(start_index, start_index + count):
        member = create_member(
            api,
            full_name=f"Caseload Member {index}",
            email=f"caseload-{index}@example.com",
        )
        case = create_case(api, member["id"], employer_id, description=f"Caseload filler {index}")
        case = triage_case(api, case["id"])
        case = assign_case(api, case["id"], ombudsman_id, case["version"])
        assigned.append({"member": member, "case": case})
    return assigned


def resolve_case_for_employer(
    api: ApiClient,
    employer: Dict[str, Any],
    ombudsman: Dict[str, Any],
    member_overrides: Optional[Dict[str, Any]] = None,
    case_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Create a fresh member and drive their case against this employer all
    the way to RESOLVED_INFORMAL, raising the employer's resolved_case_count
    by one. Returns member, case (RESOLVED_INFORMAL) and round."""
    member = create_member(api, **(member_overrides or {}))
    case = create_assigned_case(api, employer, member, ombudsman, **(case_overrides or {}))
    resolved = resolve_case_informally(
        api, case["id"], ombudsman["id"], employer_id=employer["id"], member_id=member["id"],
        issue_type=(case_overrides or {}).get("issue_type", "REEMPLOYMENT"),
    )
    return {"member": member, "case": resolved["case"], "round": resolved["round"]}


def setup_employer_with_resolved_cases(
    api: ApiClient,
    employer: Dict[str, Any],
    ombudsman: Dict[str, Any],
    count: int,
) -> List[Dict[str, Any]]:
    """Resolve ``count`` distinct members' cases for one employer, so its
    resolved_case_count stands at exactly ``count``."""
    resolved: List[Dict[str, Any]] = []
    for index in range(1, count + 1):
        resolved.append(
            resolve_case_for_employer(
                api,
                employer,
                ombudsman,
                member_overrides={
                    "full_name": f"Resolved Member {index}",
                    "email": f"resolved-{index}@example.com",
                },
                case_overrides={"description": f"Resolved case {index}"},
            )
        )
    return resolved


# ═══ Tier 5: composite world ═══════════════════════════════════════════════

def setup_basic_world(api: ApiClient, clock: str = CLOCK_STARTUP_DEFAULT) -> Dict[str, Any]:
    """Clock set, one employer, one member, one certified ombudsman.

    The most common standing arrangement; tests build their case-specific
    state on top. Returns the three entity bodies.
    """
    set_clock(api, clock)
    employer = create_employer(api)
    member = create_member(api)
    ombudsman = create_certified_ombudsman(api)
    return {"employer": employer, "member": member, "ombudsman": ombudsman}
