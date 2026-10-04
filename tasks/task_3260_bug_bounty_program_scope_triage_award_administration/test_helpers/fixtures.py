"""Composite setup helpers.

Multi-step setup sequences so tests can focus on assertions. Every fixture
builds its preconditions from scratch using only PRD-declared endpoints.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_DEFAULT, SCOPE_BASE_EFFECTIVE_FROM
from .factories import (
    create_asset_payload,
    create_award_payload,
    create_invitation_payload,
    create_program_payload,
    create_remediation_ticket_payload,
    create_report_payload,
    create_researcher_payload,
    create_scope_version_payload,
)
from .test_users import TEST_USERS, make_researcher_headers

PLATFORM_ADMIN = TEST_USERS["platform_admin_headers"]
PROGRAM_ADMIN = TEST_USERS["program_admin_headers"]
TRIAGER = TEST_USERS["triager_headers"]
ANONYMOUS = TEST_USERS["anonymous_headers"]


def set_clock(to_iso8601: str):
    """Advance the logical clock."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, PLATFORM_ADMIN))


def create_program(**overrides):
    """Create a program (status DRAFT). Returns the Program dict."""
    return get_success_data(api_client.create_program(create_program_payload(**overrides), PLATFORM_ADMIN))


def create_asset(program_id, **overrides):
    """Create a scope asset (status ACTIVE)."""
    return get_success_data(
        api_client.create_asset(create_asset_payload(program_id, **overrides), PROGRAM_ADMIN))


def create_scope_version(program_id, in_scope_asset_ids, **overrides):
    """Create a scope version."""
    return get_success_data(api_client.create_scope_version(
        create_scope_version_payload(program_id, in_scope_asset_ids, **overrides), PROGRAM_ADMIN))


def activate_program(program_id):
    return get_success_data(api_client.activate_program(program_id, PROGRAM_ADMIN))


def register_researcher(**overrides):
    """Register a researcher (status ACTIVE, reputation 100). Returns Researcher dict."""
    return get_success_data(
        api_client.create_researcher(create_researcher_payload(**overrides), ANONYMOUS))


def setup_active_program(clock=CLOCK_DEFAULT, criticality="CRITICAL",
                         effective_from=SCOPE_BASE_EFFECTIVE_FROM,
                         **program_overrides):
    """ACTIVE program + one asset + one scope version effective now.

    Returns (program, asset). The scope version is created and the program
    activated; caller receives the refreshed program via a fresh read.
    """
    set_clock(clock)
    program = create_program(**program_overrides)
    asset = create_asset(program["id"], criticality=criticality)
    create_scope_version(program["id"], [asset["id"]], effective_from=effective_from)
    activate_program(program["id"])
    program = get_success_data(api_client.get_program(program["id"], PROGRAM_ADMIN))
    return program, asset


def submit_report(program, asset, researcher, **overrides):
    """Submit a report as the given researcher. Returns Report dict."""
    headers = make_researcher_headers(researcher["id"])
    return get_success_data(api_client.create_report(
        create_report_payload(program["id"], asset["id"], **overrides), headers))


def create_report_in_state(program, asset, researcher, target_state="TRIAGED",
                           impact=5, exploitability=5, affected_scope=5, **overrides):
    """Submit a report and walk it to the target state.

    Supported targets: NEW, TRIAGED, VALIDATED.
    """
    report = submit_report(program, asset, researcher, **overrides)
    if target_state == "NEW":
        return report
    get_success_data(api_client.triage_report(report["id"], {"action": "TRIAGE"}, TRIAGER))
    if target_state == "TRIAGED":
        report = get_success_data(api_client.get_report(report["id"], TRIAGER))
        return report
    report = get_success_data(api_client.validate_report(
        report["id"],
        {"impact": impact, "exploitability": exploitability, "affected_scope": affected_scope},
        TRIAGER,
    ))
    return report


def create_validated_report(program, asset, researcher, impact=5, exploitability=5,
                            affected_scope=5, **overrides):
    """Submit -> triage -> validate. Returns VALIDATED Report dict."""
    return create_report_in_state(
        program, asset, researcher, target_state="VALIDATED",
        impact=impact, exploitability=exploitability, affected_scope=affected_scope,
        **overrides)


def resolve_report(report_id, external_ref="ENG-1"):
    """Create a remediation ticket for a VALIDATED report and VERIFY it,
    cascading the report to RESOLVED. Returns (report, ticket)."""
    ticket = get_success_data(api_client.create_remediation_ticket(
        create_remediation_ticket_payload(report_id, external_ref=external_ref), PROGRAM_ADMIN))
    get_success_data(api_client.transition_remediation_ticket(
        ticket["id"], {"action": "START"}, PROGRAM_ADMIN))
    get_success_data(api_client.transition_remediation_ticket(
        ticket["id"], {"action": "FIX"}, PROGRAM_ADMIN))
    ticket = get_success_data(api_client.transition_remediation_ticket(
        ticket["id"], {"action": "VERIFY"}, PROGRAM_ADMIN))
    report = get_success_data(api_client.get_report(report_id, PROGRAM_ADMIN))
    return report, ticket


def create_award(report_id, award_type, **overrides):
    """Propose an award (PROPOSED). Returns Award dict."""
    return get_success_data(api_client.create_award(
        create_award_payload(report_id, award_type, **overrides), TRIAGER))


def approve_award(award_id):
    return get_success_data(api_client.approve_award(award_id, PROGRAM_ADMIN))


def pay_award(award_id):
    return get_success_data(api_client.pay_award(award_id, PLATFORM_ADMIN))


def submit_tax_document(researcher, document_type="W9"):
    """Researcher submits own tax document (-> SUBMITTED)."""
    return get_success_data(api_client.submit_tax_document(
        researcher["id"], {"document_type": document_type},
        make_researcher_headers(researcher["id"])))


def verify_tax_document(researcher):
    """PlatformAdmin marks the researcher's tax document VERIFIED."""
    return get_success_data(api_client.submit_tax_document(
        researcher["id"], {"mark_verified": True}, PLATFORM_ADMIN))


def issue_invitation(program_id, researcher_id):
    return get_success_data(api_client.create_invitation(
        create_invitation_payload(program_id, researcher_id), PROGRAM_ADMIN))


def get_researcher(researcher_id):
    return get_success_data(api_client.get_researcher(researcher_id, PLATFORM_ADMIN))


def get_program(program_id):
    return get_success_data(api_client.get_program(program_id, PROGRAM_ADMIN))


def get_report(report_id):
    return get_success_data(api_client.get_report(report_id, TRIAGER))


def get_award(award_id):
    return get_success_data(api_client.get_award(award_id, PROGRAM_ADMIN))
