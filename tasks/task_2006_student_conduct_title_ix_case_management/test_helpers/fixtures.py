"""Composite setup helpers.

Each helper builds case state from scratch through PRD-declared endpoints only.
Every test runs against a freshly restarted server with an empty database, so
fixtures never rely on carried-over state. Setup calls use get_success_data so
a broken precondition surfaces as a clear setup error.
"""
from typing import Dict, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK_ISO, HEARING_SLOT_ISO, HEARING_SLOT_LATER_ISO
from .factories import (
    advisor_appointment_payload,
    appeal_payload,
    attach_report_payload,
    begin_appeal_review_payload,
    create_case_payload,
    create_party_profile_payload,
    cross_exam_question_payload,
    decide_appeal_payload,
    determination_payload,
    dismiss_case_payload,
    evidence_item_payload,
    evidence_packet_payload,
    hearing_payload,
    informal_consent_payload,
    informal_resolution_payload,
    investigator_assignment_payload,
    issue_payload,
    no_contact_directive_payload,
    notice_payload,
    resolve_informal_payload,
    review_response_payload,
    set_clock_payload,
    supportive_measure_payload,
    university_appointment_payload,
    violation_report_payload,
)
from .test_users import (
    TEST_USERS,
    make_advisor_headers,
    make_appeal_officer_headers,
    make_coordinator_headers,
    make_decision_maker_headers,
    make_investigator_headers,
    make_party_headers,
)

# ---------------------------------------------------------------------------
# Directory (PartyProfile) helpers
# ---------------------------------------------------------------------------

_PROFILE_SPECS = {
    "comp": dict(full_name="Comp One", university_id="U-C-1", role_type="STUDENT", email="c1@example.edu"),
    "resp": dict(full_name="Resp One", university_id="U-R-1", role_type="STUDENT", email="r1@example.edu"),
    "resp_emp": dict(full_name="Resp Emp", university_id="U-RE-1", role_type="EMPLOYEE", email="re1@example.edu"),
    "coord": dict(full_name="Coord One", university_id="U-CO-1", role_type="STAFF", email="co1@example.edu"),
    "inv": dict(full_name="Inv One", university_id="U-INV-1", role_type="STAFF", email="inv1@example.edu"),
    "inv2": dict(full_name="Inv Two", university_id="U-INV-2", role_type="STAFF", email="inv2@example.edu"),
    "x": dict(full_name="X Person", university_id="U-X-1", role_type="STAFF", email="x1@example.edu"),
    "dm": dict(full_name="DM One", university_id="U-DM-1", role_type="FACULTY", email="dm1@example.edu"),
    "dm2": dict(full_name="DM Two", university_id="U-DM-2", role_type="FACULTY", email="dm2@example.edu"),
    "ao": dict(full_name="AO One", university_id="U-AO-1", role_type="STAFF", email="ao1@example.edu"),
    "ao2": dict(full_name="AO Two", university_id="U-AO-2", role_type="STAFF", email="ao2@example.edu"),
    "fac": dict(full_name="Fac One", university_id="U-FAC-1", role_type="STAFF", email="fac1@example.edu"),
    "advc": dict(full_name="Adv C", university_id="U-ADVC-1", role_type="EXTERNAL", email="advc@example.edu", advisor_eligible=True),
    "advr": dict(full_name="Adv R", university_id="U-ADVR-1", role_type="EXTERNAL", email="advr@example.edu", advisor_eligible=True),
    "adv3": dict(full_name="Adv Three", university_id="U-ADV3-1", role_type="EXTERNAL", email="adv3@example.edu", advisor_eligible=True),
    "out": dict(full_name="Outsider", university_id="U-OUT-1", role_type="EXTERNAL", email="out@example.edu", advisor_eligible=True),
    "out_student": dict(full_name="Out Student", university_id="U-OUTS-1", role_type="STUDENT", email="outs@example.edu"),
}


def create_profile(key: str, **overrides) -> dict:
    """Create one directory profile from a named spec. Returns the profile."""
    spec = dict(_PROFILE_SPECS[key])
    spec.update(overrides)
    resp = api_client.create_party_profile(
        create_party_profile_payload(**spec), TEST_USERS["case_admin_headers"]
    )
    return get_success_data(resp, 201)


def make_cast(*keys: str) -> Dict[str, dict]:
    """Create several profiles at once; returns {key: profile}."""
    return {key: create_profile(key) for key in keys}


def make_full_cast() -> Dict[str, dict]:
    """The standard nine-person cast used by the full case lifecycle."""
    return make_cast("comp", "resp", "coord", "inv", "dm", "ao", "fac", "advc", "advr")


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str):
    """Advance/set the logical clock. Does not itself fire transitions."""
    resp = api_client.set_logical_clock(
        set_clock_payload(to_iso8601), TEST_USERS["case_admin_headers"]
    )
    return get_success_data(resp, 200)


# ---------------------------------------------------------------------------
# Case intake and early workflow
# ---------------------------------------------------------------------------

def create_case(cast: Dict[str, dict], categories=("STALKING",), **overrides) -> dict:
    """Record a new report. Returns the case in RECEIVED.

    Identity fields default to the cast's comp/resp/coord entries but may be
    overridden explicitly (e.g. respondent_id=profile["id"] when the case's
    respondent is a non-default profile such as an EMPLOYEE).
    """
    complainant_id = overrides.pop("complainant_id", None) or cast["comp"]["id"]
    respondent_id = overrides.pop("respondent_id", None) or cast["resp"]["id"]
    coordinator_id = overrides.pop("coordinator_id", None) or cast["coord"]["id"]
    payload = create_case_payload(
        complainant_id, respondent_id, coordinator_id,
        categories=list(categories), **overrides,
    )
    resp = api_client.create_case(payload, make_coordinator_headers(coordinator_id))
    return get_success_data(resp, 201)


def get_case(case_id: str, coord_id: str) -> dict:
    return get_success_data(api_client.get_case(case_id, make_coordinator_headers(coord_id)))


def case_version(case_id: str, coord_id: str) -> int:
    return get_case(case_id, coord_id)["version"]


def begin_jurisdiction_review(case_id: str, coord_id: str) -> dict:
    resp = api_client.begin_jurisdiction_review(case_id, make_coordinator_headers(coord_id))
    return get_success_data(resp, 200)


def confirm_jurisdiction(case_id: str, coord_id: str) -> dict:
    resp = api_client.confirm_jurisdiction(case_id, make_coordinator_headers(coord_id))
    return get_success_data(resp, 200)


def file_formal_complaint(case_id: str, comp_id: str) -> dict:
    resp = api_client.file_formal_complaint(case_id, make_party_headers(comp_id))
    return get_success_data(resp, 200)


def drive_to_investigation(case_id: str, coord_id: str, comp_id: str) -> dict:
    """RECEIVED -> JURISDICTION_REVIEW -> AWAITING_FORMAL_COMPLAINT -> INVESTIGATION."""
    begin_jurisdiction_review(case_id, coord_id)
    confirm_jurisdiction(case_id, coord_id)
    file_formal_complaint(case_id, comp_id)
    return get_case(case_id, coord_id)


def dismiss_case(case_id: str, coord_id: str, **overrides) -> dict:
    resp = api_client.dismiss_case(
        case_id, dismiss_case_payload(**overrides), make_coordinator_headers(coord_id)
    )
    return get_success_data(resp, 200)


# ---------------------------------------------------------------------------
# Supportive measures / directives / violations
# ---------------------------------------------------------------------------

def create_measure(case_id: str, coord_id: str, **overrides) -> dict:
    resp = api_client.create_supportive_measure(
        case_id, supportive_measure_payload(**overrides), make_coordinator_headers(coord_id)
    )
    return get_success_data(resp, 201)


def terminate_measure(measure_id: str, coord_id: str) -> dict:
    resp = api_client.terminate_supportive_measure(measure_id, make_coordinator_headers(coord_id))
    return get_success_data(resp, 200)


def create_directive(case_id: str, coord_id: str, **overrides) -> dict:
    """Create a no-contact directive with a freshly read OCC version."""
    version = case_version(case_id, coord_id)
    payload = no_contact_directive_payload(version, **overrides)
    resp = api_client.create_no_contact_directive(
        case_id, payload, make_coordinator_headers(coord_id)
    )
    return get_success_data(resp, 201)


def report_violation(directive_id: str, reporter_id: str, reporter_kind: str = "party", **overrides) -> dict:
    headers = (
        make_party_headers(reporter_id)
        if reporter_kind == "party"
        else make_coordinator_headers(reporter_id)
    )
    resp = api_client.report_violation(directive_id, violation_report_payload(**overrides), headers)
    return get_success_data(resp, 201)


def substantiate_violation(violation_id: str, coord_id: str) -> dict:
    resp = api_client.substantiate_violation(violation_id, make_coordinator_headers(coord_id))
    return get_success_data(resp, 200)


# ---------------------------------------------------------------------------
# Investigator assignments and evidence
# ---------------------------------------------------------------------------

def propose_investigator(case_id: str, coord_id: str, inv_id: str) -> dict:
    resp = api_client.propose_investigator(
        case_id, investigator_assignment_payload(inv_id), make_coordinator_headers(coord_id)
    )
    return get_success_data(resp, 201)


def accept_assignment(assignment_id: str, inv_id: str) -> dict:
    resp = api_client.accept_assignment(assignment_id, make_investigator_headers(inv_id))
    return get_success_data(resp, 200)


def assign_active_investigator(case_id: str, coord_id: str, inv_id: str) -> dict:
    """Propose + accept. Returns the ACTIVE assignment."""
    assignment = propose_investigator(case_id, coord_id, inv_id)
    return accept_assignment(assignment["id"], inv_id)


def submit_evidence(case_id: str, actor_id: str, actor_kind: str = "party", **overrides) -> dict:
    headers = (
        make_party_headers(actor_id)
        if actor_kind == "party"
        else make_investigator_headers(actor_id)
    )
    resp = api_client.submit_evidence_item(case_id, evidence_item_payload(**overrides), headers)
    return get_success_data(resp, 201)


def review_evidence_item(item_id: str, inv_id: str, ruling: str, exclusion_reason: Optional[str] = None) -> dict:
    """begin-review + rule-relevance. Returns the ruled item."""
    get_success_data(api_client.begin_evidence_review(item_id, make_investigator_headers(inv_id)), 200)
    payload = {"ruling": ruling}
    if exclusion_reason is not None:
        payload["exclusion_reason"] = exclusion_reason
    resp = api_client.rule_evidence_relevance(item_id, payload, make_investigator_headers(inv_id))
    return get_success_data(resp, 200)


# ---------------------------------------------------------------------------
# Evidence packet lifecycle
# ---------------------------------------------------------------------------

def create_packet(case_id: str, coord_id: str, inv_id: str) -> dict:
    """Create a DRAFT packet with a freshly read OCC version."""
    version = case_version(case_id, coord_id)
    resp = api_client.create_evidence_packet(
        case_id, evidence_packet_payload(version), make_investigator_headers(inv_id)
    )
    return get_success_data(resp, 201)


def attach_report(packet_id: str, inv_id: str, summary: str = "Investigative findings narrative") -> dict:
    resp = api_client.attach_packet_report(
        packet_id, attach_report_payload(investigative_report_summary=summary),
        make_investigator_headers(inv_id),
    )
    return get_success_data(resp, 200)


def release_packet(packet_id: str, inv_id: str) -> dict:
    resp = api_client.release_packet(packet_id, make_investigator_headers(inv_id))
    return get_success_data(resp, 200)


def submit_response(packet_id: str, party_side: str, actor_id: str, text: str = "Reviewed") -> dict:
    resp = api_client.submit_review_response(
        packet_id, review_response_payload(party_side, response_text=text),
        make_party_headers(actor_id),
    )
    return get_success_data(resp, 201)


def submit_both_responses(packet_id: str, comp_id: str, resp_id: str) -> dict:
    """Both parties respond; the second response auto-closes the review window."""
    submit_response(packet_id, "COMPLAINANT", comp_id)
    return submit_response(packet_id, "RESPONDENT", resp_id)


def finalize_packet(packet_id: str, inv_id: str) -> dict:
    resp = api_client.finalize_packet(packet_id, make_investigator_headers(inv_id))
    return get_success_data(resp, 200)


def drive_to_hearing_preparation(case_id: str, cast: Dict[str, dict], with_evidence: bool = False) -> dict:
    """RECEIVED -> INVESTIGATION -> packet release/respond/finalize -> HEARING_PREPARATION.

    Returns {"case", "packet", "assignment", "item"}.
    """
    coord_id, comp_id, resp_id, inv_id = (
        cast["coord"]["id"], cast["comp"]["id"], cast["resp"]["id"], cast["inv"]["id"],
    )
    drive_to_investigation(case_id, coord_id, comp_id)
    assignment = assign_active_investigator(case_id, coord_id, inv_id)
    item = None
    if with_evidence:
        item = submit_evidence(case_id, comp_id, "party")
        item = review_evidence_item(item["id"], inv_id, "ACCEPTED")
    packet = create_packet(case_id, coord_id, inv_id)
    attach_report(packet["id"], inv_id)
    packet = release_packet(packet["id"], inv_id)
    packet = submit_both_responses(packet["id"], comp_id, resp_id)
    packet = finalize_packet(packet["id"], inv_id)
    return {
        "case": get_case(case_id, coord_id),
        "packet": packet,
        "assignment": get_success_data(
            api_client.get_assignment(assignment["id"], make_coordinator_headers(coord_id))
        ),
        "item": item,
    }


# ---------------------------------------------------------------------------
# Advisors
# ---------------------------------------------------------------------------

def appoint_advisor(case_id: str, party_side: str, advisor_id: str, actor_id: str, as_coordinator: bool = False) -> dict:
    headers = make_coordinator_headers(actor_id) if as_coordinator else make_party_headers(actor_id)
    resp = api_client.appoint_advisor(
        case_id, advisor_appointment_payload(party_side, advisor_id), headers
    )
    return get_success_data(resp, 201)


def appoint_both_advisors(case_id: str, cast: Dict[str, dict]):
    """Complainant-side and respondent-side party-selected advisors (ACTIVE)."""
    comp_appt = appoint_advisor(case_id, "COMPLAINANT", cast["advc"]["id"], cast["comp"]["id"])
    resp_appt = appoint_advisor(case_id, "RESPONDENT", cast["advr"]["id"], cast["resp"]["id"])
    return comp_appt, resp_appt


# ---------------------------------------------------------------------------
# Hearings and cross-examination
# ---------------------------------------------------------------------------

def schedule_hearing(case_id: str, coord_id: str, dm_id: str,
                     scheduled_at: str = HEARING_SLOT_ISO, duration: int = 60,
                     modality: str = "VIRTUAL") -> dict:
    payload = hearing_payload(
        dm_id, scheduled_at=scheduled_at,
        estimated_duration_minutes=duration, modality=modality,
    )
    resp = api_client.schedule_hearing(case_id, payload, make_coordinator_headers(coord_id))
    return get_success_data(resp, 201)


def convene_hearing(hearing_id: str, dm_id: str, at_iso: str = HEARING_SLOT_ISO) -> dict:
    """Set the clock to the hearing instant, then convene."""
    set_clock(at_iso)
    resp = api_client.convene_hearing(hearing_id, make_decision_maker_headers(dm_id))
    return get_success_data(resp, 200)


def close_cross_exam(hearing_id: str, dm_id: str) -> dict:
    resp = api_client.close_cross_exam(hearing_id, make_decision_maker_headers(dm_id))
    return get_success_data(resp, 200)


def ask_question(hearing_id: str, advisor_id: str, target_side: str, text: str = "Cross question") -> dict:
    resp = api_client.ask_cross_exam_question(
        hearing_id, cross_exam_question_payload(advisor_id, target_side, question_text=text),
        make_advisor_headers(advisor_id),
    )
    return get_success_data(resp, 201)


def rule_question(question_id: str, dm_id: str, ruling: str, ruling_reason: Optional[str] = None) -> dict:
    payload = {"ruling": ruling}
    if ruling_reason is not None:
        payload["ruling_reason"] = ruling_reason
    resp = api_client.rule_cross_exam_question(question_id, payload, make_decision_maker_headers(dm_id))
    return get_success_data(resp, 200)


def drive_case_to_deliberation(case_id: str, cast: Dict[str, dict],
                               hearing_slot: str = HEARING_SLOT_ISO,
                               convene_at: Optional[str] = None) -> dict:
    """Full path RECEIVED -> ... -> HEARING_PREPARATION -> convene -> close-cross-exam.

    Requires cast keys: comp, resp, coord, inv, dm, advc, advr.
    Returns {"case", "packet", "hearing", "assignment", "item"}.
    """
    stage = drive_to_hearing_preparation(case_id, cast)
    appoint_both_advisors(case_id, cast)
    hearing = schedule_hearing(case_id, cast["coord"]["id"], cast["dm"]["id"], scheduled_at=hearing_slot)
    hearing = convene_hearing(hearing["id"], cast["dm"]["id"], at_iso=convene_at or hearing_slot)
    hearing = close_cross_exam(hearing["id"], cast["dm"]["id"])
    stage["hearing"] = hearing
    stage["case"] = get_case(case_id, cast["coord"]["id"])
    return stage


# ---------------------------------------------------------------------------
# Determinations and sanctions
# ---------------------------------------------------------------------------

def create_determination_draft(case_id: str, coord_id: str, dm_id: str, **overrides) -> dict:
    version = case_version(case_id, coord_id)
    payload = determination_payload(version, **overrides)
    resp = api_client.create_determination(case_id, payload, make_decision_maker_headers(dm_id))
    return get_success_data(resp, 201)


def issue_determination(det_id: str, dm_id: str, selections) -> dict:
    resp = api_client.issue_determination(
        det_id, issue_payload(selections), make_decision_maker_headers(dm_id)
    )
    return get_success_data(resp, 200)


def drive_case_to_issued(case_id: str, cast: Dict[str, dict],
                         selections=None, hearing_slot: str = HEARING_SLOT_ISO,
                         convene_at: Optional[str] = None,
                         with_evidence: bool = False, **det_overrides) -> dict:
    """Full path through an ISSUED determination. Returns the stage dict plus
    "determination" and the sanctions list."""
    stage = drive_case_to_deliberation(
        case_id, cast, hearing_slot=hearing_slot, convene_at=convene_at
    ) if not with_evidence else _drive_case_to_deliberation_with_evidence(
        case_id, cast, hearing_slot=hearing_slot, convene_at=convene_at
    )
    det = create_determination_draft(case_id, cast["coord"]["id"], cast["dm"]["id"], **det_overrides)
    det = issue_determination(det["id"], cast["dm"]["id"], selections or [{"sanction_type": "WARNING"}])
    stage["determination"] = det
    stage["sanctions"] = get_success_data(
        api_client.list_determination_sanctions(det["id"], make_coordinator_headers(cast["coord"]["id"]))
    )
    stage["case"] = get_case(case_id, cast["coord"]["id"])
    return stage


def _drive_case_to_deliberation_with_evidence(case_id, cast, hearing_slot=HEARING_SLOT_ISO, convene_at=None):
    """Deliberation path that rules one evidence item ACCEPTED before packet release."""
    coord_id, comp_id, resp_id, inv_id = (
        cast["coord"]["id"], cast["comp"]["id"], cast["resp"]["id"], cast["inv"]["id"],
    )
    drive_to_investigation(case_id, coord_id, comp_id)
    assignment = assign_active_investigator(case_id, coord_id, inv_id)
    item = submit_evidence(case_id, comp_id, "party")
    item = review_evidence_item(item["id"], inv_id, "ACCEPTED")
    packet = create_packet(case_id, coord_id, inv_id)
    attach_report(packet["id"], inv_id)
    packet = release_packet(packet["id"], inv_id)
    packet = submit_both_responses(packet["id"], comp_id, resp_id)
    packet = finalize_packet(packet["id"], inv_id)
    appoint_both_advisors(case_id, cast)
    hearing = schedule_hearing(case_id, coord_id, cast["dm"]["id"], scheduled_at=hearing_slot)
    hearing = convene_hearing(hearing["id"], cast["dm"]["id"], at_iso=convene_at or hearing_slot)
    hearing = close_cross_exam(hearing["id"], cast["dm"]["id"])
    return {
        "case": get_case(case_id, coord_id),
        "packet": packet,
        "hearing": hearing,
        "assignment": get_success_data(
            api_client.get_assignment(assignment["id"], make_coordinator_headers(coord_id))
        ),
        "item": item,
    }


# ---------------------------------------------------------------------------
# Appeals and remand
# ---------------------------------------------------------------------------

def file_appeal(case_id: str, filer_id: str, filed_by_side: str, appeal_target: str,
                grounds, statement: str = "Appeal statement on the record") -> dict:
    resp = api_client.file_appeal(
        case_id, appeal_payload(filed_by_side, appeal_target, list(grounds), statement=statement),
        make_party_headers(filer_id),
    )
    return get_success_data(resp, 201)


def begin_appeal_review(appeal_id: str, coord_id: str, ao_id: str) -> dict:
    resp = api_client.begin_appeal_review(
        appeal_id, begin_appeal_review_payload(ao_id), make_coordinator_headers(coord_id)
    )
    return get_success_data(resp, 200)


def decide_appeal(appeal_id: str, ao_id: str, outcome: str, **overrides) -> dict:
    resp = api_client.decide_appeal(
        appeal_id, decide_appeal_payload(outcome, **overrides),
        make_appeal_officer_headers(ao_id),
    )
    return get_success_data(resp, 200)


def drive_case_to_remanded(case_id: str, cast: Dict[str, dict],
                           grounds=("NEW_EVIDENCE",), remand_scope="INVESTIGATION",
                           selections=None, with_evidence: bool = False,
                           **det_overrides) -> dict:
    """Issue a determination, then appeal and decide REMANDED. Returns stage dict
    with determination/appeal plus the pre-remand stage contents."""
    stage = drive_case_to_issued(
        case_id, cast,
        selections=selections or [{"sanction_type": "SUSPENSION", "duration_days": 120}],
        with_evidence=with_evidence,
        **({"aggravating_factor_count": 1, "mitigating_factor_count": 0,
            "prior_responsible_findings": 0} | det_overrides),
    )
    appeal = file_appeal(case_id, cast["resp"]["id"], "RESPONDENT", "DETERMINATION", grounds)
    appeal = begin_appeal_review(appeal["id"], cast["coord"]["id"], cast["ao"]["id"])
    appeal = decide_appeal(appeal["id"], cast["ao"]["id"], "REMANDED", remand_scope=remand_scope)
    stage["appeal"] = appeal
    stage["case"] = get_case(case_id, cast["coord"]["id"])
    return stage


def resume_case(case_id: str, coord_id: str) -> dict:
    resp = api_client.resume_case(case_id, make_coordinator_headers(coord_id))
    return get_success_data(resp, 200)


def drive_round_two_to_deliberation(case_id: str, cast: Dict[str, dict],
                                    hearing_slot: str = HEARING_SLOT_LATER_ISO) -> dict:
    """After a REMANDED -> INVESTIGATION resume: new assignment, fresh packet,
    second hearing, close-cross-exam. Advisors from round one remain ACTIVE."""
    coord_id, comp_id, resp_id, inv_id, dm_id = (
        cast["coord"]["id"], cast["comp"]["id"], cast["resp"]["id"],
        cast["inv"]["id"], cast["dm"]["id"],
    )
    assignment = assign_active_investigator(case_id, coord_id, inv_id)
    packet = create_packet(case_id, coord_id, inv_id)
    attach_report(packet["id"], inv_id, summary="Round two findings")
    packet = release_packet(packet["id"], inv_id)
    packet = submit_both_responses(packet["id"], comp_id, resp_id)
    packet = finalize_packet(packet["id"], inv_id)
    hearing = schedule_hearing(case_id, coord_id, dm_id, scheduled_at=hearing_slot)
    hearing = convene_hearing(hearing["id"], dm_id, at_iso=hearing_slot)
    hearing = close_cross_exam(hearing["id"], dm_id)
    return {
        "case": get_case(case_id, coord_id),
        "packet": packet,
        "hearing": hearing,
        "assignment": assignment,
    }


# ---------------------------------------------------------------------------
# Informal resolution
# ---------------------------------------------------------------------------

def propose_informal_resolution(case_id: str, coord_id: str, fac_id: str) -> dict:
    resp = api_client.propose_informal_resolution(
        case_id, informal_resolution_payload(fac_id), make_coordinator_headers(coord_id)
    )
    return get_success_data(resp, 201)


def consent_informal(resolution_id: str, party_side: str, actor_id: str, consent: bool) -> dict:
    resp = api_client.consent_informal_resolution(
        resolution_id, informal_consent_payload(party_side, consent), make_party_headers(actor_id)
    )
    return get_success_data(resp, 200)


def withdraw_informal(resolution_id: str, actor_id: str) -> dict:
    resp = api_client.withdraw_informal_resolution(resolution_id, make_party_headers(actor_id))
    return get_success_data(resp, 200)


def resolve_informal(resolution_id: str, coord_id: str, terms: str = "Mutual no-contact + counseling") -> dict:
    resp = api_client.resolve_informal_resolution(
        resolution_id, resolve_informal_payload(agreed_terms=terms),
        make_coordinator_headers(coord_id),
    )
    return get_success_data(resp, 200)


# ---------------------------------------------------------------------------
# Notices
# ---------------------------------------------------------------------------

def create_notice(case_id: str, sender_headers: dict, **overrides) -> dict:
    resp = api_client.create_notice(case_id, notice_payload(**overrides), sender_headers)
    return get_success_data(resp, 201)


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def get_annual_statistics(year: int, coord_id: str) -> dict:
    resp = api_client.get_annual_statistics(year, make_coordinator_headers(coord_id))
    return get_success_data(resp, 200)
