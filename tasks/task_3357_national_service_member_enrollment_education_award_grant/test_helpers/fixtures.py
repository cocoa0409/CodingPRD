"""Composite setup helpers.

Every fixture builds its preconditions from scratch against a fresh server
(the harness restarts the API before each test) using only PRD-declared
endpoints. The logical clock is pinned to 2026-09-01T00:00:00Z at the start
of every chain (PRD §2.4) and moved to 2026-10-02T00:00:00Z to close the
competition window when an award is needed.

Ownership threading: GranteeStaff calls always carry make_grantee_staff_headers
(org_id) and Member calls carry make_member_headers(member_id), per PRD §2.1.
"""
from datetime import date, timedelta

from prd_bench_local_runner.testing import get_success_data, validate_success

from .api_client import api_client
from .constants import (
    CLOCK_AFTER_CLOSE_ISO,
    CLOCK_START_ISO,
    DEFAULT_SERVICE_END,
    DEFAULT_SERVICE_START,
    TERM_MINUTES,
)
from .factories import (
    assign_corrective_action_payload,
    award_application_payload,
    create_application_payload,
    create_competition_payload,
    create_enrollment_payload,
    create_finding_payload,
    create_grievance_payload,
    create_hour_entry_payload,
    create_organization_payload,
    create_visit_payload,
    decide_finding_payload,
    exit_enrollment_payload,
    match_line,
    record_component_result_payload,
    register_member_payload,
    slot_request,
    submit_evidence_payload,
)
from .test_users import (
    TEST_USERS,
    make_compliance_officer_headers,
    make_grantee_staff_headers,
    make_member_headers,
)

OFFICER = TEST_USERS["officer_headers"]
ANON = TEST_USERS["anonymous_headers"]
TRUST = TEST_USERS["trust_admin_headers"]


def _ok(resp, what="setup call"):
    """Lenient setup validator: any 2xx returns data; otherwise a clear error."""
    if resp.status_code >= 300:
        raise AssertionError(
            f"Setup failed: {what} -> HTTP {resp.status_code}: {resp.text[:400]}"
        )
    return get_success_data(resp)


# --- clock --------------------------------------------------------------------

def set_clock(to_iso8601=CLOCK_START_ISO):
    return _ok(
        api_client.set_clock({"to_iso8601": to_iso8601}, OFFICER),
        f"set_clock({to_iso8601})",
    )


# --- organizations & competitions ----------------------------------------------

def create_org(**overrides) -> dict:
    return _ok(
        api_client.create_organization(create_organization_payload(**overrides), OFFICER),
        "create_organization",
    )


def create_competition(**overrides) -> dict:
    return _ok(
        api_client.create_competition(create_competition_payload(**overrides), OFFICER),
        "create_competition",
    )


def setup_org_competition() -> dict:
    """Logical clock pinned at the start instant; one org, one open competition."""
    set_clock(CLOCK_START_ISO)
    org = create_org()
    comp = create_competition()
    return {"org": org, "comp": comp, "org_id": org["id"], "comp_id": comp["id"]}


# --- applications & awards ------------------------------------------------------

def create_draft_application(
    comp_id,
    org_id,
    federal_share_requested_cents=4000000,
    slot_requests=None,
    match_lines=None,
) -> dict:
    staff = make_grantee_staff_headers(org_id)
    return _ok(
        api_client.create_application(
            comp_id,
            create_application_payload(
                org_id,
                federal_share_requested_cents=federal_share_requested_cents,
                slot_requests=slot_requests,
                match_lines=match_lines,
            ),
            staff,
        ),
        "create_application",
    )


def submit_application(app_id, org_id) -> dict:
    return _ok(
        api_client.submit_application(app_id, make_grantee_staff_headers(org_id)),
        "submit_application",
    )


def award_version(award_id) -> int:
    return _ok(api_client.get_award(award_id, OFFICER), "get_award")["version"]


def education_award_version(education_award_id) -> int:
    return _ok(
        api_client.get_education_award(education_award_id, TRUST), "get_education_award"
    )["version"]


def setup_awarded_program(
    federal_share_requested_cents=4000000,
    slot_requests=None,
    match_lines=None,
    federal_share_awarded_cents=None,
) -> dict:
    """Full chain: org + competition + application + submit + close window +
    award. Ends with the clock at 2026-10-02T00:00:00Z and an ACTIVE award.

    Defaults to 2 FULL_TIME slots, federal 4000000, CASH match 1000000.
    """
    if slot_requests is None:
        slot_requests = [slot_request("FULL_TIME", 2)]
    if match_lines is None:
        match_lines = [match_line("CASH", 1000000)]
    if federal_share_awarded_cents is None:
        federal_share_awarded_cents = federal_share_requested_cents

    base = setup_org_competition()
    app = create_draft_application(
        base["comp_id"], base["org_id"], federal_share_requested_cents, slot_requests, match_lines
    )
    submit_application(app["id"], base["org_id"])
    set_clock(CLOCK_AFTER_CLOSE_ISO)
    _ok(api_client.close_competition(base["comp_id"], OFFICER), "close_competition")
    award = _ok(
        api_client.award_application(
            app["id"], award_application_payload(federal_share_awarded_cents), OFFICER
        ),
        "award_application",
    )
    return {
        **base,
        "app": app,
        "app_id": app["id"],
        "award": award,
        "award_id": award["id"],
        "staff": make_grantee_staff_headers(base["org_id"]),
    }


# --- members & criminal history checks ------------------------------------------

def register_member(**overrides) -> dict:
    return _ok(
        api_client.register_member(register_member_payload(**overrides), ANON),
        "register_member",
    )


def initiate_check(member_id, org_id) -> dict:
    return _ok(
        api_client.create_criminal_check(member_id, make_grantee_staff_headers(org_id)),
        "create_criminal_check",
    )


def record_component(check_id, component, result) -> dict:
    return _ok(
        api_client.record_component_result(
            check_id, record_component_result_payload(component, result), OFFICER
        ),
        f"record_component_result({component}={result})",
    )


def clear_check(check_id) -> dict:
    """Record CLEAR on all three components; adjudicates the check CLEARED."""
    record_component(check_id, "NSOPR", "CLEAR")
    record_component(check_id, "STATE_REPOSITORY", "CLEAR")
    return record_component(check_id, "FBI_FINGERPRINT", "CLEAR")


def register_cleared_member(org_id, **member_overrides) -> str:
    """Member whose (only) criminal history check is adjudicated CLEARED."""
    member = register_member(**member_overrides)
    check = initiate_check(member["id"], org_id)
    clear_check(check["id"])
    return member["id"]


def register_pending_check_member(org_id, **member_overrides):
    """Member with a check initiated but no component results (adjudication
    PENDING). Returns (member_id, check_id)."""
    member = register_member(**member_overrides)
    check = initiate_check(member["id"], org_id)
    return member["id"], check["id"]


def register_flagged_member(org_id, **member_overrides):
    """Member whose latest check adjudicated FLAGGED (NSOPR FLAGGED, the other
    two CLEAR). Returns (member_id, check_id)."""
    member = register_member(**member_overrides)
    check = initiate_check(member["id"], org_id)
    record_component(check["id"], "NSOPR", "FLAGGED")
    record_component(check["id"], "STATE_REPOSITORY", "CLEAR")
    record_component(check["id"], "FBI_FINGERPRINT", "CLEAR")
    return member["id"], check["id"]


# --- enrollments ------------------------------------------------------------------

def enroll(
    award_id,
    org_id,
    member_id,
    term_category="FULL_TIME",
    service_start_date=DEFAULT_SERVICE_START,
    service_end_date=DEFAULT_SERVICE_END,
) -> dict:
    """Create an enrollment carrying the award's CURRENT version (OCC)."""
    version = award_version(award_id)
    resp = api_client.create_enrollment(
        award_id,
        create_enrollment_payload(
            member_id,
            term_category=term_category,
            service_start_date=service_start_date,
            service_end_date=service_end_date,
            expected_award_version=version,
        ),
        make_grantee_staff_headers(org_id),
    )
    return validate_success(resp, 201)


def certify_minutes(
    enrollment_id,
    org_id,
    chunks,
    first_service_date=date(2026, 10, 16),
    activity_code="DIRECT_SERVICE",
) -> list:
    """Create + certify one hour entry per chunk of minutes, on successive days."""
    staff = make_grantee_staff_headers(org_id)
    entries = []
    for i, minutes in enumerate(chunks):
        service_date = (first_service_date + timedelta(days=i)).isoformat()
        entry = _ok(
            api_client.create_hour_entry(
                enrollment_id,
                create_hour_entry_payload(service_date, minutes, activity_code),
                staff,
            ),
            f"create_hour_entry({minutes} min)",
        )
        entries.append(
            _ok(api_client.certify_hour_entry(entry["id"], staff), "certify_hour_entry")
        )
    return entries


def pay_allowance(enrollment_id, org_id, amount_cents, count) -> list:
    staff = make_grantee_staff_headers(org_id)
    payments = []
    for _ in range(count):
        payments.append(
            _ok(
                api_client.create_allowance_payment(
                    enrollment_id, {"amount_cents": amount_cents}, staff
                ),
                f"create_allowance_payment({amount_cents})",
            )
        )
    return payments


def get_enrollment(enrollment_id) -> dict:
    return _ok(api_client.get_enrollment(enrollment_id, OFFICER), "get_enrollment")


def setup_active_enrollment(
    minutes_chunks=None,
    term_category="FULL_TIME",
    member_overrides=None,
    service_start_date=DEFAULT_SERVICE_START,
    service_end_date=DEFAULT_SERVICE_END,
    **program_kwargs,
) -> dict:
    """Awarded program + one cleared member enrolled and ACTIVE, optionally with
    certified minutes. Returns program fields plus member_id/enrollment."""
    program = setup_awarded_program(**program_kwargs)
    member_id = register_cleared_member(
        program["org_id"], **(member_overrides or {})
    )
    enrollment = enroll(
        program["award_id"],
        program["org_id"],
        member_id,
        term_category=term_category,
        service_start_date=service_start_date,
        service_end_date=service_end_date,
    )
    result = {**program, "member_id": member_id, "enrollment": enrollment,
              "enrollment_id": enrollment["id"]}
    if minutes_chunks:
        certify_minutes(
            enrollment["id"], program["org_id"], minutes_chunks,
            activity_code="DIRECT_SERVICE",
        )
        result["enrollment"] = get_enrollment(enrollment["id"])
    return result


def exit_member(enrollment_id, org_id, exit_reason) -> dict:
    return validate_success(
        api_client.exit_enrollment(
            enrollment_id,
            exit_enrollment_payload(exit_reason),
            make_grantee_staff_headers(org_id),
        ),
        200,
    )


def setup_education_award(
    minutes_chunks=(36000,),
    exit_reason="COMPELLING_CIRCUMSTANCE",
    **program_kwargs,
) -> dict:
    """Active enrollment with the given certified minutes, exited with the given
    reason. Returns program fields plus member_id, enrollment_id and
    education_award_id (None for FOR_CAUSE)."""
    scenario = setup_active_enrollment(minutes_chunks=list(minutes_chunks), **program_kwargs)
    exited = exit_member(scenario["enrollment_id"], scenario["org_id"], exit_reason)
    return {
        **scenario,
        "enrollment": exited,
        "education_award_id": exited.get("education_award_id"),
    }


# --- compliance visits, findings, sweep -------------------------------------------

def schedule_visit(award_id, officer_id="co-one", visit_type="SITE_VISIT",
                   scheduled_date="2026-11-02") -> dict:
    return _ok(
        api_client.create_visit(
            award_id,
            create_visit_payload(visit_type, scheduled_date),
            make_compliance_officer_headers(officer_id),
        ),
        "create_visit",
    )


def conduct_visit(visit_id, officer_id="co-one") -> dict:
    return _ok(
        api_client.conduct_visit(visit_id, make_compliance_officer_headers(officer_id)),
        "conduct_visit",
    )


def record_finding(visit_id, officer_id="co-one", severity="HIGH",
                   description="Member files incomplete") -> dict:
    return _ok(
        api_client.create_finding(
            visit_id,
            create_finding_payload(severity, description),
            make_compliance_officer_headers(officer_id),
        ),
        "create_finding",
    )


def assign_corrective(finding_id, officer_id="co-one", requirement="Complete the member files",
                      due_days=14) -> dict:
    return _ok(
        api_client.assign_corrective_action(
            finding_id,
            assign_corrective_action_payload(requirement, due_days),
            make_compliance_officer_headers(officer_id),
        ),
        "assign_corrective_action",
    )


def submit_evidence(finding_id, org_id, evidence_note="Files completed 10/17") -> dict:
    return _ok(
        api_client.submit_evidence(
            finding_id,
            submit_evidence_payload(evidence_note),
            make_grantee_staff_headers(org_id),
        ),
        "submit_evidence",
    )


def decide_finding(finding_id, officer_id, decision="APPROVE", note=None) -> dict:
    return _ok(
        api_client.decide_finding(
            finding_id,
            decide_finding_payload(decision, note),
            make_compliance_officer_headers(officer_id),
        ),
        "decide_finding",
    )


def setup_finding_evidence_submitted(program=None, officer_id="co-one",
                                     scheduled_date="2026-11-02", due_days=14) -> dict:
    """Conducted visit + finding + corrective action assigned + evidence filed
    by the grantee. Returns program fields plus visit_id/finding_id."""
    if program is None:
        program = setup_awarded_program()
    visit = schedule_visit(program["award_id"], officer_id, scheduled_date=scheduled_date)
    conduct_visit(visit["id"], officer_id)
    finding = record_finding(visit["id"], officer_id)
    assign_corrective(finding["id"], officer_id, due_days=due_days)
    submit_evidence(finding["id"], program["org_id"])
    return {**program, "visit_id": visit["id"], "finding_id": finding["id"]}


def setup_award_suspended_by_overdue_sweep() -> dict:
    """Active enrollment + overdue assigned finding, then the sweep escalates
    the finding, suspends the award, and cascade-suspends the enrollment
    (PRD §3.8 three-hop cascade)."""
    scenario = setup_active_enrollment()
    visit = schedule_visit(scenario["award_id"], "co-one")
    conduct_visit(visit["id"], "co-one")
    finding = record_finding(visit["id"], "co-one")
    # Assigned at clock 2026-10-02 with due_days 14 -> due_at 2026-10-16.
    assign_corrective(finding["id"], "co-one", due_days=14)
    set_clock("2026-10-17T00:00:00Z")
    sweep = _ok(
        api_client.sweep_overdue(make_compliance_officer_headers("co-one")),
        "sweep_overdue",
    )
    return {
        **scenario,
        "visit_id": visit["id"],
        "finding_id": finding["id"],
        "sweep": sweep,
    }


# --- grievances -------------------------------------------------------------------

def file_grievance(enrollment_id, member_id, description="Disputed conduct finding") -> dict:
    return _ok(
        api_client.create_grievance(
            enrollment_id,
            create_grievance_payload(description),
            make_member_headers(member_id),
        ),
        "create_grievance",
    )


def escalate_grievance(grievance_id, member_id) -> dict:
    return _ok(
        api_client.escalate_grievance(grievance_id, make_member_headers(member_id)),
        "escalate_grievance",
    )
