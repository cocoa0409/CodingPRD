"""Composite setup helpers.

Every test runs against a freshly restarted server with an empty database
and the logical clock at 2026-09-01T00:00:00Z (PRD §2.4). These helpers build
the multi-step preconditions (open term, admitted application, completed
evaluation, registered enrollment, certified package, in-session term) that
the test scenarios share.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TERM_OPEN_CLOCK, TERM_CENSUS_CLOCK
from .factories import (
    create_term_payload, create_program_payload,
    create_state_authorization_payload, create_staff_payload,
    create_applicant_payload, create_application_payload,
    create_tce_payload, create_enrollment_payload, create_section_payload,
)
from .test_users import TEST_USERS, make_applicant_headers

ADMIN = TEST_USERS["system_admin_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]
FAO1 = TEST_USERS["fao1_headers"]
FAO2 = TEST_USERS["fao2_headers"]


# ---------------------------------------------------------------- clock

def set_clock(to_iso8601: str):
    resp = api_client.set_clock(to_iso8601, ADMIN)
    get_success_data(resp)


# ---------------------------------------------------------------- catalog

def create_program(code="BS-CS", total_credits=120, licensure_flag=False) -> dict:
    resp = api_client.create_program(
        create_program_payload(
            code=code, total_credits_required=total_credits,
            licensure_flag=licensure_flag),
        REGISTRAR)
    return get_success_data(resp)


def authorize_state(program_id, state_code="CO", status="AUTHORIZED",
                    effective_from="2026-01-01", effective_to=None,
                    disclosure_text=None) -> dict:
    payload = create_state_authorization_payload(
        state_code=state_code, authorization_status=status,
        effective_from=effective_from)
    if effective_to is not None:
        payload["effective_to"] = effective_to
    if disclosure_text is not None:
        payload["disclosure_text"] = disclosure_text
    resp = api_client.create_state_authorization(program_id, payload, COMPLIANCE)
    return get_success_data(resp)


def create_term(**overrides) -> dict:
    resp = api_client.create_term(create_term_payload(**overrides), REGISTRAR)
    return get_success_data(resp)


def open_term(term_id, clock=TERM_OPEN_CLOCK) -> dict:
    """Set the logical clock and advance the term to ENROLLMENT_OPEN."""
    set_clock(clock)
    resp = api_client.advance_term(term_id, "ENROLLMENT_OPEN", REGISTRAR)
    return get_success_data(resp)


# ---------------------------------------------------------------- staff

def create_advisor(cap=5, full_name="Ann Advisor") -> dict:
    resp = api_client.create_staff(
        create_staff_payload(
            full_name=full_name, staff_type="ADVISOR", caseload_cap=cap),
        ADMIN)
    return get_success_data(resp)


def create_counselor(cap=5, compensation_plan="NON_INCENTIVE",
                     full_name="Cal Counselor") -> dict:
    payload = create_staff_payload(
        full_name=full_name, staff_type="COUNSELOR", caseload_cap=cap)
    if compensation_plan is not None:
        payload["compensation_plan"] = compensation_plan
    resp = api_client.create_staff(payload, ADMIN)
    return get_success_data(resp)


# ---------------------------------------------------------------- funnel

def create_applicant(state_code="CO", full_name="Pat Prospect") -> dict:
    resp = api_client.create_applicant(
        create_applicant_payload(full_name=full_name, state_code=state_code),
        REGISTRAR)
    return get_success_data(resp)


def create_submitted_application(applicant_id, term_id, program_id,
                                 **flags) -> dict:
    """Create an application as the applicant acting for itself (PRD §3.4)."""
    resp = api_client.create_application(
        create_application_payload(applicant_id, term_id, program_id, **flags),
        make_applicant_headers(applicant_id))
    return get_success_data(resp)


def admit_application(application_id) -> dict:
    """ADMIT decision by the registrar; returns the updated application."""
    resp = api_client.decide_application(
        application_id, {"decision": "ADMIT"}, REGISTRAR)
    return get_success_data(resp)


def create_completed_tce(application_id, accepted_credits=0,
                         in_progress_credits=0) -> dict:
    resp = api_client.create_tce(
        application_id,
        create_tce_payload(accepted_credits=accepted_credits,
                           in_progress_credits=in_progress_credits),
        REGISTRAR)
    tce = get_success_data(resp)
    get_success_data(api_client.advance_tce(tce["id"], "IN_REVIEW", REGISTRAR))
    resp = api_client.advance_tce(tce["id"], "COMPLETED", REGISTRAR)
    return get_success_data(resp)


def create_enrollment(application, advisor_id, intensity="FULL_TIME",
                      tuition_cents=500000) -> dict:
    """Convert an ADMITTED application; `application` carries the version the
    registrar last observed (PRD §2.8)."""
    resp = api_client.create_enrollment(
        create_enrollment_payload(
            application["id"], advisor_id, application["version"],
            enrollment_intensity=intensity, tuition_cents=tuition_cents),
        REGISTRAR)
    return get_success_data(resp)


# ---------------------------------------------------------------- composites

def setup_open_term_scenario(state_code="CO", program_kwargs=None,
                             term_kwargs=None) -> dict:
    """Program + AUTHORIZED state row + term advanced to ENROLLMENT_OPEN."""
    program = create_program(**(program_kwargs or {}))
    authorize_state(program["id"], state_code=state_code)
    term = create_term(**(term_kwargs or {}))
    term = open_term(term["id"])
    return {"program": program, "term": term}


def setup_registered_enrollment(state_code="CO", intensity="FULL_TIME",
                                tuition_cents=500000, advisor_cap=5,
                                accepted_credits=0, in_progress_credits=0,
                                program_kwargs=None,
                                application_flags=None) -> dict:
    """Full funnel: open term, advisor, applicant, ADMITTED application with a
    COMPLETED evaluation, converted into a REGISTERED enrollment."""
    ctx = setup_open_term_scenario(
        state_code=state_code, program_kwargs=program_kwargs)
    advisor = create_advisor(cap=advisor_cap)
    applicant = create_applicant(state_code=state_code)
    application = create_submitted_application(
        applicant["id"], ctx["term"]["id"], ctx["program"]["id"],
        **(application_flags or {}))
    application = admit_application(application["id"])
    tce = create_completed_tce(application["id"], accepted_credits,
                               in_progress_credits)
    enrollment = create_enrollment(application, advisor["id"],
                                   intensity=intensity,
                                   tuition_cents=tuition_cents)
    ctx.update({
        "advisor": advisor,
        "applicant": applicant,
        "application": application,
        "tce": tce,
        "enrollment": enrollment,
    })
    return ctx


def setup_certified_package(intensity="FULL_TIME", tuition_cents=500000,
                            efc_cents=0, **kwargs) -> dict:
    """REGISTERED enrollment plus a CERTIFIED aid package."""
    ctx = setup_registered_enrollment(
        intensity=intensity, tuition_cents=tuition_cents, **kwargs)
    package = create_aid_package(ctx["enrollment"]["id"], efc_cents)
    package = certify_aid_package(package["id"],
                                  ctx["enrollment"]["version"])
    ctx["package"] = package
    return ctx


def setup_in_session_disbursing(intensity="FULL_TIME", tuition_cents=500000,
                                efc_cents=0,
                                session_clock=TERM_CENSUS_CLOCK,
                                **kwargs) -> dict:
    """Certified package, then the term advanced to IN_SESSION at
    `session_clock` so due schedule entries release (PRD §3.1)."""
    ctx = setup_certified_package(
        intensity=intensity, tuition_cents=tuition_cents, efc_cents=efc_cents,
        **kwargs)
    set_clock(session_clock)
    get_success_data(api_client.advance_term(
        ctx["term"]["id"], "IN_SESSION", REGISTRAR))
    # Re-read through the lazy-evaluation boundary (PRD §2.10).
    ctx["enrollment"] = get_success_data(
        api_client.get_enrollment(ctx["enrollment"]["id"], REGISTRAR))
    ctx["package"] = get_success_data(
        api_client.list_aid_packages(ctx["enrollment"]["id"], FAO1))[0]
    return ctx


# ---------------------------------------------------------------- aid

def create_aid_package(enrollment_id, efc_cents=0, officer_headers=FAO1) -> dict:
    resp = api_client.create_aid_package(enrollment_id, efc_cents,
                                         officer_headers)
    return get_success_data(resp)


def certify_aid_package(package_id, expected_enrollment_version,
                        officer_headers=FAO2) -> dict:
    resp = api_client.certify_aid_package(
        package_id, expected_enrollment_version, officer_headers)
    return get_success_data(resp)


# ---------------------------------------------------------------- sections

def create_section(term_id, course_code="CS-101", capacity=1,
                   forecast_enrollment=1) -> dict:
    resp = api_client.create_section(
        term_id,
        create_section_payload(course_code=course_code, capacity=capacity,
                               forecast_enrollment=forecast_enrollment),
        REGISTRAR)
    return get_success_data(resp)


def open_section_with_gap(section_id, adjunct_hires) -> dict:
    """PLANNED -> STAFFING -> STAFFED(adjunct_hires) -> OPEN."""
    get_success_data(api_client.advance_section(section_id, "STAFFING", REGISTRAR))
    section = get_success_data(api_client.advance_section(
        section_id, "STAFFED", REGISTRAR, adjunct_hires=adjunct_hires))
    section = get_success_data(api_client.advance_section(
        section_id, "OPEN", REGISTRAR))
    return section


def open_zero_gap_section(section_id) -> dict:
    """PLANNED -> STAFFED -> OPEN for a section with adjuncts_required == 0."""
    get_success_data(api_client.advance_section(section_id, "STAFFED", REGISTRAR))
    return get_success_data(api_client.advance_section(
        section_id, "OPEN", REGISTRAR))
