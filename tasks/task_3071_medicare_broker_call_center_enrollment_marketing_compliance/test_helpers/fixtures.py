"""
Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch against an empty database
using only PRD-declared endpoints. Setup calls use ``get_success_data()`` so a
broken chain produces a clear "Setup failed" error rather than a confusing
assertion failure deep inside a test.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CLOCK_START, CLOCK_START_0900, DEFAULT_SOA_MAX_AGE_DAYS,
)
from .factories import (
    create_agency_payload, create_carrier_payload, create_agent_payload,
    create_license_payload, create_certification_payload,
    create_appointment_payload, create_member_payload, create_scope_payload,
    create_call_session_payload, connect_call_payload, complete_call_payload,
    create_plan_payload, create_formulary_drug_payload,
    create_pharmacy_network_entry_payload, create_provider_directory_entry_payload,
    create_enrollment_payload, create_complaint_payload,
    create_coaching_assignment_payload, create_reconciliation_payload,
    create_correction_payload,
)
from .test_users import TEST_USERS, make_licensed_agent_headers

ADMIN = TEST_USERS["platform_admin_headers"]
DIRECTOR = TEST_USERS["director_of_sales_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
LICENSING = TEST_USERS["licensing_coordinator_headers"]
COACH = TEST_USERS["coach_headers"]
CARRIER_INT = TEST_USERS["carrier_integration_headers"]

# Last clock the server echoed back to ``set_clock`` (canonical 3-digit form).
_CLOCK_READ = {"current": CLOCK_START}


# ─── Tier 1: clock and master data ───────────────────────────

def set_clock(current_utc: str):
    """Set the server's logical clock. Returns the reported instant.

    The canonical (3-fractional-digit) form the server echoes back is remembered
    so fixtures can stamp children from the clock the server actually holds.
    """
    reported = get_success_data(api_client.set_clock(current_utc, ADMIN))
    _CLOCK_READ["current"] = reported["current_utc"]
    return reported


def current_clock() -> str:
    """The logical clock the server currently holds, in canonical form."""
    return _CLOCK_READ["current"]


def create_agency(**overrides):
    return get_success_data(
        api_client.create_agency(create_agency_payload(**overrides), ADMIN))


def create_carrier(**overrides):
    return get_success_data(
        api_client.create_carrier(create_carrier_payload(**overrides), ADMIN))


def create_plan(carrier_id: str, **overrides):
    return get_success_data(
        api_client.create_plan(create_plan_payload(carrier_id, **overrides), ADMIN))


def add_formulary_drug(plan_id: str, **overrides):
    return get_success_data(api_client.add_formulary_drug(
        plan_id, create_formulary_drug_payload(**overrides), ADMIN))


def add_pharmacy_network_entry(plan_id: str, **overrides):
    return get_success_data(api_client.add_pharmacy_network_entry(
        plan_id, create_pharmacy_network_entry_payload(**overrides), ADMIN))


def add_provider_directory_entry(plan_id: str, **overrides):
    return get_success_data(api_client.add_provider_directory_entry(
        plan_id, create_provider_directory_entry_payload(**overrides), ADMIN))


# ─── Tier 1: staffing pipeline ───────────────────────────────

def create_agent_in_pipeline(agency_id: str, **overrides):
    """Create a newly minted agent sitting in PROVISIONING."""
    return get_success_data(api_client.create_agent(
        create_agent_payload(agency_id, **overrides), DIRECTOR))


def license_agent(agent_id: str, **overrides):
    """PROVISIONING -> LICENSED. Returns the AgentStateLicense row."""
    return get_success_data(api_client.add_license(
        agent_id, create_license_payload(**overrides), LICENSING))


def certify_agent(agent_id: str, carrier_id: str, **overrides):
    """LICENSED -> CERTIFIED. Returns the CarrierCertification row."""
    return get_success_data(api_client.add_certification(
        agent_id, create_certification_payload(carrier_id, **overrides), LICENSING))


def appoint_agent(agent_id: str, carrier_id: str, **overrides):
    """CERTIFIED -> ACTIVE. Returns the CarrierAppointment row."""
    return get_success_data(api_client.add_appointment(
        agent_id, create_appointment_payload(carrier_id, **overrides), LICENSING))


def create_and_activate_agent(agency_id: str, carrier_id: str,
                              license_overrides=None, cert_overrides=None,
                              appt_overrides=None, **overrides):
    """Full staffing ladder: create -> license -> certify -> appoint.

    Returns (agent, license, certification, appointment).
    """
    agent = create_agent_in_pipeline(agency_id, **overrides)
    lic = license_agent(agent["id"], **(license_overrides or {}))
    cert = certify_agent(agent["id"], carrier_id, **(cert_overrides or {}))
    appt = appoint_agent(agent["id"], carrier_id, **(appt_overrides or {}))
    agent = get_success_data(api_client.get_agent(agent["id"], DIRECTOR))
    return agent, lic, cert, appt


def create_licensed_certified_agent(agency_id: str, carrier_id: str, **overrides):
    """Create -> license -> certify, stopping at CERTIFIED (no appointment)."""
    agent = create_agent_in_pipeline(agency_id, **overrides)
    license_agent(agent["id"])
    certify_agent(agent["id"], carrier_id)
    return get_success_data(api_client.get_agent(agent["id"], DIRECTOR))


# ─── Tier 2: members, scopes, calls ──────────────────────────

def create_member_for_agent(agency_id: str, agent_id: str, **overrides):
    """Create a member as the acting LicensedAgent. Returns (member, version)."""
    headers = make_licensed_agent_headers(agent_id)
    member = get_success_data(api_client.create_member(
        create_member_payload(agency_id, **overrides), headers))
    return member, member["version"]


def capture_scope(member_id: str, agent_id: str, member_version: int, **overrides):
    """Capture a scope of appointment as the acting LicensedAgent.

    ``captured_on`` defaults to the current logical clock rather than a fixed
    literal: PRD §2.5 makes a scope usable only while ``captured_on`` is at or
    before the logical clock, so a fixture that captures a scope while the clock
    sits earlier than its own literal would build a precondition the PRD forbids.
    """
    headers = make_licensed_agent_headers(agent_id)
    payload = create_scope_payload(member_id, agent_id, member_version, **overrides)
    if "captured_on" not in overrides:
        payload["captured_on"] = current_clock()
    return get_success_data(api_client.create_scope(payload, headers))


def open_call(agent_id: str, member_id: str, scope_id: str, **overrides):
    """Open a RINGING call session attached to a scope."""
    headers = make_licensed_agent_headers(agent_id)
    return get_success_data(api_client.create_call_session(
        create_call_session_payload(agent_id, member_id, scope_id, **overrides),
        headers))


def connect_call(agent_id: str, call_id: str, **overrides):
    headers = make_licensed_agent_headers(agent_id)
    return get_success_data(api_client.connect_call(
        call_id, connect_call_payload(**overrides), headers))


def complete_call(agent_id: str, call_id: str, **overrides):
    headers = make_licensed_agent_headers(agent_id)
    return get_success_data(api_client.complete_call(
        call_id, complete_call_payload(**overrides), headers))


def drop_call(agent_id: str, call_id: str, **overrides):
    headers = make_licensed_agent_headers(agent_id)
    payload = {"reason": overrides.pop("reason", "CALLER_HUNG_UP")}
    payload.update(overrides)
    return get_success_data(api_client.drop_call(call_id, payload, headers))


def get_call(agent_id: str, call_id: str):
    return get_success_data(
        api_client.get_call_session(call_id, make_licensed_agent_headers(agent_id)))


def submit_enrollment(agent_id: str, call_id: str, member_id: str, plan_id: str,
                      scope_id: str, call_session_version: int, **overrides):
    headers = make_licensed_agent_headers(agent_id)
    return get_success_data(api_client.create_enrollment(
        create_enrollment_payload(call_id, member_id, plan_id, agent_id, scope_id,
                                  call_session_version, **overrides),
        headers))


def acknowledge_enrollment(enrollment_id: str, carrier_id: str):
    return get_success_data(api_client.acknowledge_enrollment(
        enrollment_id, {"carrier_id": carrier_id}, CARRIER_INT))


def effectuate_enrollment(enrollment_id: str):
    return get_success_data(
        api_client.effectuate_enrollment(enrollment_id, CARRIER_INT))


def reject_enrollment(enrollment_id: str, **overrides):
    payload = {"reason": overrides.pop("reason", "CARRIER_DUPLICATE")}
    payload.update(overrides)
    return get_success_data(
        api_client.reject_enrollment(enrollment_id, payload, CARRIER_INT))


def withdraw_enrollment(agent_id: str, enrollment_id: str, **overrides):
    headers = make_licensed_agent_headers(agent_id)
    payload = {"reason": overrides.pop("reason", "BENEFICIARY_CHANGED_MIND")}
    payload.update(overrides)
    return get_success_data(api_client.withdraw_enrollment(
        enrollment_id, payload, headers))


def disenroll_enrollment(enrollment_id: str, **overrides):
    payload = {
        "disenrollment_date": overrides.pop("disenrollment_date",
                                            "2026-11-10T00:00:00Z"),
        "disenrollment_reason": overrides.pop("disenrollment_reason",
                                              "BENEFICIARY_REQUEST"),
    }
    payload.update(overrides)
    return get_success_data(
        api_client.disenroll_enrollment(enrollment_id, payload, CARRIER_INT))


# ─── Composite: the shared anchor scenario ───────────────────

def setup_master_data(capacity: int = 3, **agency_overrides):
    """Clock at 2026-10-01 + agency + contracted carrier + MAPD plan TX/TX-201.

    Returns a dict with agency, carrier and plan.
    """
    set_clock(CLOCK_START)
    agency = create_agency(aep_daily_submission_capacity=capacity, **agency_overrides)
    carrier = create_carrier()
    plan = create_plan(carrier["id"])
    return {"agency": agency, "carrier": carrier, "plan": plan}


def setup_agency_with_active_agent(**agency_overrides):
    """Clock + agency + carrier + plan + a fully licensed/certified/appointed agent.

    No member, scope or call is created. Returns a dict.
    """
    scn = setup_master_data(**agency_overrides)
    agent, lic, cert, appt = create_and_activate_agent(
        scn["agency"]["id"], scn["carrier"]["id"])
    scn.update({"agent": agent, "license": lic, "certification": cert,
                "appointment": appt})
    return scn


def setup_scope_and_completed_call(scn, member_index: int = 0, **call_overrides):
    """Add a member, a captured scope and a COMPLETED call to ``scn``.

    ``member_index`` 0 uses Ada Whitfield, 1 uses Hollis Pike. Returns the
    updated scenario dict with ``member``, ``member_version``, ``scope`` and
    ``call`` populated (suffixed ``_two`` for index 1).
    """
    agency_id = scn["agency"]["id"]
    agent_id = scn["agent"]["id"]
    suffix = "" if member_index == 0 else "_two"
    if member_index == 0:
        member, version = create_member_for_agent(agency_id, agent_id)
    else:
        member, version = create_member_for_agent(
            agency_id, agent_id, full_name="Hollis Pike",
            medicare_beneficiary_id="3GH6-VG7-PM94",
            date_of_birth="1952-11-19T00:00:00Z")
    scope = capture_scope(member["id"], agent_id, version)
    call = open_call(agent_id, member["id"], scope["id"], **call_overrides)
    connect_call(agent_id, call["id"])
    call = complete_call(agent_id, call["id"])
    key = "member" if member_index == 0 else "member_two"
    scn[key] = member
    scn[f"member_version{suffix}"] = version
    scn[f"scope{suffix}"] = scope
    scn[f"call{suffix}"] = call
    return scn


def setup_submitted_enrollment(scn, **enrollment_overrides):
    """Extend ``scn`` through POST /enrollments. Returns ``scn`` with
    ``enrollment`` set and the call version refreshed.
    """
    call = scn["call"]
    enrollment = submit_enrollment(
        scn["agent"]["id"], call["id"], scn["member"]["id"], scn["plan"]["id"],
        scn["scope"]["id"], call["version"], **enrollment_overrides)
    scn["enrollment"] = enrollment
    scn["call"] = get_call(scn["agent"]["id"], call["id"])
    return scn


def setup_effectuated_enrollment(scn, **enrollment_overrides):
    """Full anchor through effectuation: the enrollment sits (EFFECTUATED, ENROLLED)."""
    setup_submitted_enrollment(scn, **enrollment_overrides)
    acknowledge_enrollment(scn["enrollment"]["id"], scn["carrier"]["id"])
    effectuate_enrollment(scn["enrollment"]["id"])
    scn["enrollment"] = get_success_data(api_client.get_enrollment(
        scn["enrollment"]["id"], DIRECTOR))
    return scn


def setup_acknowledged_enrollment(scn, **enrollment_overrides):
    """Full anchor through acknowledgment."""
    setup_submitted_enrollment(scn, **enrollment_overrides)
    acknowledge_enrollment(scn["enrollment"]["id"], scn["carrier"]["id"])
    scn["enrollment"] = get_success_data(api_client.get_enrollment(
        scn["enrollment"]["id"], DIRECTOR))
    return scn


def setup_call_ready_scenario(capacity: int = 3, with_second_member: bool = True,
                              **agency_overrides):
    """The most common setup: master data + active agent + one completed call.

    With ``with_second_member`` a second member and scope are also prepared.
    Returns the scenario dict.
    """
    scn = setup_agency_with_active_agent(**agency_overrides)
    setup_scope_and_completed_call(scn, member_index=0)
    if with_second_member:
        setup_scope_and_completed_call(scn, member_index=1)
    return scn


def setup_enrollment_ready_scenario(**agency_overrides):
    """Master data + active agent + completed call + submitted enrollment."""
    scn = setup_agency_with_active_agent(**agency_overrides)
    setup_scope_and_completed_call(scn, member_index=0)
    return setup_submitted_enrollment(scn)


# ─── Tier 3: late-lifecycle and terminal states ──────────────

def setup_agency_frozen(scn):
    """Drive the agency to FROZEN with five substantiated complaints.

    Returns the refreshed agency dict.
    """
    agent_id = scn["agent"]["id"]
    for i in range(5):
        c = get_success_data(api_client.create_complaint(
            create_complaint_payload(
                agent_id, complaint_type="MISREPRESENTATION", source="CMS",
                severity="HIGH",
                filed_on=f"2026-09-{20 + i:02d}T00:00:00Z"), COMPLIANCE))
        api_client.begin_review(c["id"], COMPLIANCE)
        get_success_data(api_client.substantiate_complaint(c["id"], COMPLIANCE))
    scn["agency"] = get_success_data(api_client.get_agency(scn["agency"]["id"], ADMIN))
    return scn["agency"]


def setup_agency_restricted(scn):
    """Drive the agency to RESTRICTED with one substantiated complaint."""
    c = get_success_data(api_client.create_complaint(
        create_complaint_payload(scn["agent"]["id"], complaint_type="MISREPRESENTATION",
                                 source="CMS", severity="HIGH",
                                 filed_on="2026-09-28T00:00:00Z"), COMPLIANCE))
    api_client.begin_review(c["id"], COMPLIANCE)
    get_success_data(api_client.substantiate_complaint(c["id"], COMPLIANCE))
    scn["agency"] = get_success_data(api_client.get_agency(scn["agency"]["id"], ADMIN))
    return scn["agency"]


def create_substantiated_complaints(scn, count: int, start_day: int = 20,
                                    complaint_type: str = "MISREPRESENTATION",
                                    severity: str = "HIGH"):
    """File, review and substantiate ``count`` complaints against the scenario agent."""
    ids = []
    for i in range(count):
        c = get_success_data(api_client.create_complaint(
            create_complaint_payload(
                scn["agent"]["id"], complaint_type=complaint_type, source="CMS",
                severity=severity,
                filed_on=f"2026-09-{start_day + i:02d}T00:00:00Z"), COMPLIANCE))
        api_client.begin_review(c["id"], COMPLIANCE)
        get_success_data(api_client.substantiate_complaint(c["id"], COMPLIANCE))
        ids.append(c["id"])
    return ids


def raise_chargeback_tier(scn, target_tier: int):
    """Raise the scenario agent's chargeback_tier to ``target_tier``.

    Each withdrawal of a SUBMITTED enrollment increments the tier by one, so
    this creates and withdraws that many fresh enrollments on the scenario's
    completed call.
    """
    for _ in range(target_tier):
        call = get_call(scn["agent"]["id"], scn["call"]["id"])
        enrollment = submit_enrollment(
            scn["agent"]["id"], scn["call"]["id"], scn["member"]["id"],
            scn["plan"]["id"], scn["scope"]["id"], call["version"])
        withdraw_enrollment(scn["agent"]["id"], enrollment["id"])
    scn["agent"] = get_success_data(api_client.get_agent(scn["agent"]["id"], DIRECTOR))
    return scn["agent"]["chargeback_tier"]


def setup_agent_at_chargeback_tier(tier: int = 4, **agency_overrides):
    """Master data + active agent + completed call + agent at ``tier``."""
    scn = setup_enrollment_ready_scenario(**agency_overrides)
    raise_chargeback_tier(scn, tier)
    return scn


def raise_tier_with_repeated_withdrawals(scn, times: int):
    """Withdraw ``times`` fresh enrollments on the scenario's completed call.

    Each withdrawal increments the agent's chargeback_tier by one. The call
    session version is re-read between submissions. Returns the final tier.
    """
    return raise_chargeback_tier(scn, times)


def setup_tier_then_effectuated_enrollment(scn, tier: int):
    """Raise the tier by withdrawals, then leave one EFFECTUATED enrollment.

    Returns ``scn`` with ``enrollment`` at (EFFECTUATED, ENROLLED) and
    ``agent`` at the requested chargeback tier.
    """
    raise_chargeback_tier(scn, tier)
    call = get_call(scn["agent"]["id"], scn["call"]["id"])
    enrollment = submit_enrollment(
        scn["agent"]["id"], scn["call"]["id"], scn["member"]["id"],
        scn["plan"]["id"], scn["scope"]["id"], call["version"])
    acknowledge_enrollment(enrollment["id"], scn["carrier"]["id"])
    effectuate_enrollment(enrollment["id"])
    scn["enrollment"] = get_success_data(
        api_client.get_enrollment(enrollment["id"], DIRECTOR))
    return scn


# ─── Tier 4: threshold targeting ─────────────────────────────

def setup_with_soa_max_age(days: int, **agency_overrides):
    """Master data whose agency declares a non-default scope staleness window."""
    scn = setup_agency_with_active_agent(soa_max_age_days=days, **agency_overrides)
    setup_scope_and_completed_call(scn, member_index=0)
    return scn


def setup_manual_coaching(scn, due_offset_days: int = 14, **overrides):
    """Create a manual coaching assignment against the scenario agent."""
    payload = create_coaching_assignment_payload(scn["agent"]["id"], **overrides)
    coaching = get_success_data(
        api_client.create_coaching_assignment(payload, COACH))
    scn["coaching"] = coaching
    return coaching


def setup_reconciliation(scn, **overrides):
    """Open a reconciliation period for the scenario carrier and period 2026-10."""
    recon = get_success_data(api_client.create_reconciliation(
        create_reconciliation_payload(scn["carrier"]["id"], **overrides),
        DIRECTOR))
    scn["reconciliation"] = recon
    return recon


def setup_open_reconciliation_with_ledger(scn, **overrides):
    """Submitted enrollment + an OPEN reconciliation holding the INITIAL entry."""
    scn = setup_enrollment_ready_scenario()
    recon = setup_reconciliation(scn, **overrides)
    return scn, recon


def setup_three_enrollment_listing_scenario():
    """Master data + active agent + three enrollments on distinct effective days.

    Ada's call yields two submissions (the call version is refreshed between
    them) and Hollis Pike's call yields the third. Returns the scenario dict with
    ``enrollments`` populated.
    """
    scn = setup_agency_with_active_agent()
    setup_scope_and_completed_call(scn, member_index=0)
    setup_scope_and_completed_call(scn, member_index=1)
    agent_id = scn["agent"]["id"]

    first = submit_enrollment(agent_id, scn["call"]["id"], scn["member"]["id"],
                              scn["plan"]["id"], scn["scope"]["id"],
                              scn["call"]["version"])
    scn["call"] = get_call(agent_id, scn["call"]["id"])
    second = submit_enrollment(agent_id, scn["call"]["id"], scn["member"]["id"],
                               scn["plan"]["id"], scn["scope"]["id"],
                               scn["call"]["version"],
                               effective_date="2026-11-02T00:00:00Z")
    third = submit_enrollment(agent_id, scn["call_two"]["id"], scn["member_two"]["id"],
                              scn["plan"]["id"], scn["scope_two"]["id"],
                              scn["call_two"]["version"],
                              effective_date="2026-11-03T00:00:00Z")
    scn["enrollments"] = [first, second, third]
    return scn


def setup_ringing_call(scn, member_index=0, **call_overrides):
    """Add a member, a captured scope and a RINGING (never connected) call."""
    agency_id = scn["agency"]["id"]
    agent_id = scn["agent"]["id"]
    suffix = "" if member_index == 0 else "_two"
    if member_index == 0:
        member, version = create_member_for_agent(agency_id, agent_id)
    else:
        member, version = create_member_for_agent(
            agency_id, agent_id, full_name="Hollis Pike",
            medicare_beneficiary_id="3GH6-VG7-PM94",
            date_of_birth="1952-11-19T00:00:00Z")
    scope = capture_scope(member["id"], agent_id, version)
    call = open_call(agent_id, member["id"], scope["id"], **call_overrides)
    scn[f"member{suffix}"] = member
    scn[f"scope{suffix}"] = scope
    scn[f"call{suffix}"] = call
    return scn


def setup_complaint_in_review(scn, **overrides):
    """File a complaint and move it into review. Returns the complaint dict."""
    payload = create_complaint_payload(scn["agent"]["id"], **overrides)
    complaint = get_success_data(api_client.create_complaint(payload, COMPLIANCE))
    api_client.begin_review(complaint["id"], COMPLIANCE)
    scn["complaint"] = complaint
    return complaint


# ─── Tier 4: multi-carrier / multi-plan comparison scenarios ─

def setup_three_plan_comparison_scenario():
    """Master data plus three ACTIVE MAPD plans in the member's service area.

    ALPHA and GAMMA are byte-identical apart from GAMMA having no pharmacy
    network entry; BETA differs on premium, deductible, star rating and
    formulary coverage. The member lists two provider NPIs. Returns a dict with
    ``alpha``, ``beta``, ``gamma``, ``member``, ``scope`` and ``agent``.

    A plan has no agency of its own, so the staffing-authority rule (one
    appointment spanning every candidate) can only be satisfied when all three
    candidate plans sit under one carrier. All three plans are therefore created
    under a single carrier, and the agent is appointed with that carrier.
    """
    set_clock(CLOCK_START)
    agency = create_agency(aep_daily_submission_capacity=3)

    carrier = create_carrier()
    alpha = create_plan(carrier["id"])
    add_formulary_drug(alpha["id"])
    add_formulary_drug(alpha["id"], drug_name="Metformin 500mg", rxcui="861007",
                       tier=2, monthly_copay_cents=600)
    add_pharmacy_network_entry(alpha["id"])
    add_provider_directory_entry(alpha["id"])

    beta = create_plan(carrier["id"], plan_id_code="BBN-H0099-004",
                       monthly_premium_cents=3200, annual_drug_deductible_cents=0,
                       star_rating=5.0, formulary_id="FORM-BBN-V4",
                       pharmacy_network_id="PHARM-BBN-V1",
                       provider_directory_id="PROV-BBN-V2")
    add_formulary_drug(beta["id"], monthly_copay_cents=1500)
    add_formulary_drug(beta["id"], drug_name="Metformin 500mg", rxcui="861007",
                       tier=3, monthly_copay_cents=3000,
                       prior_authorization_required=True, covered=False)
    add_provider_directory_entry(beta["id"])

    gamma = create_plan(carrier["id"], plan_id_code="GCC-H0044-002",
                        pharmacy_network_id="PHARM-GCC-V1")
    add_formulary_drug(gamma["id"])
    add_formulary_drug(gamma["id"], drug_name="Metformin 500mg", rxcui="861007",
                       tier=2, monthly_copay_cents=600)
    add_provider_directory_entry(gamma["id"])

    agent, _, _, _ = create_and_activate_agent(agency["id"], carrier["id"])
    member, version = create_member_for_agent(
        agency["id"], agent["id"],
        drug_list=[
            {"drug_name": "Lisinopril 10mg", "rxcui": "314076", "monthly_fills": 1},
            {"drug_name": "Metformin 500mg", "rxcui": "861007", "monthly_fills": 2},
        ],
        provider_npis=["1000000001", "2000000002"])
    scope = capture_scope(member["id"], agent["id"], version)
    return {"agency": agency, "agent": agent, "member": member, "scope": scope,
            "alpha": alpha, "beta": beta, "gamma": gamma,
            "carrier": carrier, "carrier_a": carrier}


def setup_two_plan_comparison_scenario():
    """Master data plus two ACTIVE plans in the member's service area.

    Both plans sit under one carrier: a plan carries no agency of its own, so the
    staffing-authority rule requires one appointment spanning every candidate.
    """
    set_clock(CLOCK_START)
    agency = create_agency(aep_daily_submission_capacity=3)
    carrier = create_carrier()
    plan_a = create_plan(carrier["id"])
    add_formulary_drug(plan_a["id"])
    add_provider_directory_entry(plan_a["id"])
    plan_b = create_plan(carrier["id"], plan_id_code="BBN-H0099-004",
                         monthly_premium_cents=3200, annual_drug_deductible_cents=0,
                         star_rating=5.0)
    add_pharmacy_network_entry(plan_b["id"], pharmacy_npi="3000000002",
                              pharmacy_name="Bluebonnet Pharmacy")
    add_provider_directory_entry(plan_b["id"])
    agent, _, _, _ = create_and_activate_agent(agency["id"], carrier["id"])
    member, version = create_member_for_agent(agency["id"], agent["id"])
    scope = capture_scope(member["id"], agent["id"], version)
    return {"agency": agency, "agent": agent, "member": member, "scope": scope,
            "plan_a": plan_a, "plan_b": plan_b, "carrier": carrier, "carrier_a": carrier}


__all__ = [name for name in dir() if not name.startswith("_")]