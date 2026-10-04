"""Composite setup helpers.

These encapsulate the multi-step setup sequences shared across the test suite:
building a program + contract + PCP + clinician + member, driving an enrollment
through the outreach funnel to ACTIVE, and running visits / urgent episodes to
completion. Setup calls use the lenient success validator so failures surface
as clear "Setup failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .assertions import unwrap_singleton
from .factories import (
    DEFAULTS,
    create_assessment_payload,
    create_capitated_contract_payload,
    create_care_program_payload,
    create_clinician_payload,
    create_enrollment_payload,
    create_member_payload,
    create_pcp_provider_payload,
    create_shared_savings_contract_payload,
    create_urgent_episode_payload,
    create_visit_payload,
)
from .test_users import TEST_USERS, make_clinician_headers

ADMIN = TEST_USERS["platform_admin_headers"]
CONTRACT_ADMIN = TEST_USERS["contract_admin_headers"]
SPECIALIST = TEST_USERS["engagement_specialist_headers"]
COORDINATOR = TEST_USERS["care_coordinator_headers"]
ANALYST = TEST_USERS["performance_analyst_headers"]


# ---------------------------------------------------------------------------
# Tier 1: reference data scaffolding
# ---------------------------------------------------------------------------

def create_program(**overrides):
    """Create a CareProgram. Returns the program dict."""
    resp = api_client.create_care_program(create_care_program_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_capitated_contract(program_id, **overrides):
    resp = api_client.create_payer_contract(
        create_capitated_contract_payload(program_id, **overrides), CONTRACT_ADMIN
    )
    return get_success_data(resp)


def create_shared_savings_contract(program_id, **overrides):
    resp = api_client.create_payer_contract(
        create_shared_savings_contract_payload(program_id, **overrides), CONTRACT_ADMIN
    )
    return get_success_data(resp)


def create_pcp(program_id, **overrides):
    resp = api_client.create_pcp_provider(
        create_pcp_provider_payload(program_id, **overrides), ADMIN
    )
    return get_success_data(resp)


def create_clinician(program_id, **overrides):
    resp = api_client.create_clinician(
        create_clinician_payload(program_id, **overrides), ADMIN
    )
    return get_success_data(resp)


def create_member(program_id, contract_id, pcp_id, **overrides):
    resp = api_client.create_member(
        create_member_payload(program_id, contract_id, pcp_id, **overrides), ADMIN
    )
    return get_success_data(resp)


def setup_program_with_contract(**overrides):
    """CareProgram + CAPITATED contract + PCP. Returns (program, contract, pcp)."""
    program = create_program(**overrides.pop("program_overrides", {}))
    contract = create_capitated_contract(program["id"], **overrides.pop("contract_overrides", {}))
    pcp = create_pcp(program["id"], **overrides.pop("pcp_overrides", {}))
    return program, contract, pcp


def setup_basic_reference(with_clinician=True, clinician_overrides=None):
    """CareProgram + CAPITATED contract + PCP + (optionally) one NP clinician.
    Returns (program, contract, pcp, np_or_None)."""
    program, contract, pcp = setup_program_with_contract()
    np = None
    if with_clinician:
        np = create_clinician(program["id"], **(clinician_overrides or {}))
    return program, contract, pcp, np


# ---------------------------------------------------------------------------
# Tier 2: enrollment funnel progression
# ---------------------------------------------------------------------------

def create_member_with_enrollment(program, contract, pcp, member_overrides=None,
                                  outreach_channel="PHONE"):
    """Create a member and its first enrollment (IDENTIFIED).
    Returns (member, enrollment)."""
    member = create_member(program["id"], contract["id"], pcp["id"], **(member_overrides or {}))
    resp = api_client.create_enrollment(
        member["id"],
        create_enrollment_payload(member["version"], outreach_channel=outreach_channel),
        SPECIALIST,
    )
    enrollment = get_success_data(resp)
    return member, enrollment


def drive_enrollment_to_outreach(enrollment_id):
    resp = api_client.begin_outreach(enrollment_id, SPECIALIST)
    return get_success_data(resp)


def drive_enrollment_to_consented(enrollment_id, consent_document_id=None):
    """IDENTIFIED -> OUTREACH -> CONSENTED. Returns the CONSENTED enrollment."""
    drive_enrollment_to_outreach(enrollment_id)
    resp = api_client.record_consent(
        enrollment_id, {"consent_document_id": consent_document_id or DEFAULTS["CONSENT_DOC"]},
        SPECIALIST,
    )
    return get_success_data(resp)


def get_care_team_row(enrollment_id):
    """Fetch the enrollment's care team (1:1 sub-resource). Returns the dict."""
    resp = api_client.get_care_team(enrollment_id, COORDINATOR)
    data = get_success_data(resp)
    team = unwrap_singleton(data)
    assert team is not None, "expected a care team row for this enrollment"
    return team


def activate_care_team_for(enrollment_id, primary_np_id, **team_overrides):
    """Assign the primary NP and activate the care team. Returns the ACTIVE team."""
    payload = {"primary_np_id": primary_np_id}
    payload.update(team_overrides)
    resp = api_client.update_care_team(enrollment_id, payload, COORDINATOR)
    get_success_data(resp)
    resp = api_client.activate_care_team(enrollment_id, COORDINATOR)
    return get_success_data(resp)


def activate_enrollment(enrollment_id):
    resp = api_client.activate_enrollment(enrollment_id, SPECIALIST)
    return get_success_data(resp)


def setup_active_enrollment(member_overrides=None, clinician_overrides=None,
                            outreach_channel="PHONE"):
    """Full happy-path: program + contract + PCP + NP + member + enrollment
    driven IDENTIFIED -> ACTIVE with an ACTIVE care team whose primary NP is
    the created clinician.

    Returns dict with keys: program, contract, pcp, np, member, enrollment.
    """
    program, contract, pcp, np = setup_basic_reference(
        with_clinician=True, clinician_overrides=clinician_overrides
    )
    member, enrollment = create_member_with_enrollment(
        program, contract, pcp, member_overrides, outreach_channel
    )
    drive_enrollment_to_consented(enrollment["id"])
    activate_care_team_for(enrollment["id"], np["id"])
    enrollment = activate_enrollment(enrollment["id"])
    return {
        "program": program,
        "contract": contract,
        "pcp": pcp,
        "np": np,
        "member": member,
        "enrollment": enrollment,
    }


# ---------------------------------------------------------------------------
# Tier 3: visit lifecycle shortcuts
# ---------------------------------------------------------------------------

def create_scheduled_visit(enrollment_id, visit_type="ROUTINE_FOLLOWUP",
                           start="2026-09-02T09:00:00Z", end="2026-09-02T10:00:00Z"):
    resp = api_client.create_visit(
        create_visit_payload(enrollment_id, visit_type=visit_type,
                             scheduled_start=start, scheduled_end=end),
        COORDINATOR,
    )
    return get_success_data(resp)


def drive_visit_to_in_progress(visit):
    """SCHEDULED -> EN_ROUTE -> IN_PROGRESS, driven by the assigned clinician."""
    headers = make_clinician_headers(visit["clinician_id"])
    get_success_data(api_client.depart_visit(visit["id"], headers))
    resp = api_client.arrive_visit(visit["id"], headers)
    return get_success_data(resp)


def upsert_and_submit_assessment(visit, assessment_overrides=None):
    """Write the assessment and submit it. Returns the SUBMITTED assessment."""
    headers = make_clinician_headers(visit["clinician_id"])
    get_success_data(api_client.upsert_assessment(
        visit["id"], create_assessment_payload(**(assessment_overrides or {})), headers
    ))
    resp = api_client.submit_assessment(visit["id"], headers)
    return get_success_data(resp)


def complete_visit(visit, assessment_overrides=None):
    """Drive a SCHEDULED visit all the way to COMPLETED with a submitted
    assessment. Returns the COMPLETED visit."""
    drive_visit_to_in_progress(visit)
    upsert_and_submit_assessment(visit, assessment_overrides)
    headers = make_clinician_headers(visit["clinician_id"])
    resp = api_client.complete_visit(visit["id"], headers)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 4: urgent episodes
# ---------------------------------------------------------------------------

def create_triggered_episode(enrollment_id, trigger_source="MEMBER_CALL"):
    resp = api_client.create_urgent_episode(
        create_urgent_episode_payload(enrollment_id, trigger_source=trigger_source),
        COORDINATOR,
    )
    return get_success_data(resp)


def dispatch_episode(episode_id):
    resp = api_client.dispatch_episode(episode_id, COORDINATOR)
    return get_success_data(resp)


def arrive_episode(episode):
    headers = make_clinician_headers(episode["dispatched_clinician_id"])
    resp = api_client.arrive_episode(episode["id"], headers)
    return get_success_data(resp)


def resolve_episode(episode, resolved_outcome="AVOIDED_ED"):
    headers = make_clinician_headers(episode["dispatched_clinician_id"])
    resp = api_client.resolve_episode(episode["id"], {"resolved_outcome": resolved_outcome}, headers)
    return get_success_data(resp)


def create_dispatched_episode(enrollment_id, trigger_source="MEMBER_CALL"):
    episode = create_triggered_episode(enrollment_id, trigger_source)
    return dispatch_episode(episode["id"])


# ---------------------------------------------------------------------------
# Tier 5: measurements and settlements
# ---------------------------------------------------------------------------

def get_measurement_for_member(member_id, period_index=0):
    """Fetch the single PerformanceMeasurement row for (member, period)."""
    resp = api_client.list_performance_measurements(
        ANALYST, params={"member_id": member_id, "period_index": period_index}
    )
    data = get_success_data(resp)
    assert isinstance(data, list) and len(data) == 1, (
        f"expected exactly one measurement row for member {member_id}, got {data}"
    )
    return data[0]


def create_settlement(contract_id):
    resp = api_client.create_settlement(contract_id, CONTRACT_ADMIN)
    return get_success_data(resp)


def finalize_settlement(contract_id, settlement_id):
    resp = api_client.finalize_settlement(contract_id, settlement_id, CONTRACT_ADMIN)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Clock helpers
# ---------------------------------------------------------------------------

def set_clock(iso_timestamp):
    get_success_data(api_client.set_clock({"current_utc": iso_timestamp}, ADMIN))


def advance_clock(by_hours):
    get_success_data(api_client.advance_clock_hours({"by_hours": by_hours}, ADMIN))
