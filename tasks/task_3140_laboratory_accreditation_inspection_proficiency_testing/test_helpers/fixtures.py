"""Composite setup helpers — multi-step scenario builders used by the test suite.

Every helper builds preconditions from scratch using only PRD-declared endpoints,
threads entity-backed identity through `make_director_headers` /
`make_inspector_headers`, and uses get_success_data so setup failures surface
as clear "Setup failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_checklist_edition_payload,
    create_competency_assessment_payload,
    create_enrollment_payload,
    create_finding_payload,
    create_inspection_cycle_payload,
    create_inspector_profile_payload,
    create_laboratory_payload,
    create_method_validation_payload,
    create_personnel_record_payload,
    create_pt_result_payload,
    create_pt_shipment_payload,
    create_pt_subscription_payload,
    create_section_payload,
    create_team_assignment_payload,
)
from .test_users import (
    TEST_USERS,
    make_director_headers,
    make_inspector_headers,
)

OFFICER = TEST_USERS["officer_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]
PTC = TEST_USERS["pt_coordinator_headers"]


# ---------------------------------------------------------------------------
# Tier 1: laboratories and enrollments
# ---------------------------------------------------------------------------

def create_laboratory(**overrides):
    """Create a laboratory. Returns the laboratory dict."""
    payload = create_laboratory_payload(**overrides)
    resp = api_client.create_laboratory(payload, OFFICER)
    return get_success_data(resp)


def create_enrollment_for_lab(lab_id, discipline="CHEMISTRY", **overrides):
    """Create a discipline enrollment under a laboratory (initially WAITING)."""
    payload = create_enrollment_payload(laboratory_id=lab_id, discipline=discipline,
                                        **overrides)
    resp = api_client.create_enrollment(payload, make_director_headers(lab_id))
    return get_success_data(resp)


def create_section_for_enrollment(enrollment_id, lab_id, **overrides):
    """Create a testing section under an enrollment (UNASSIGNED)."""
    payload = create_section_payload(enrollment_id=enrollment_id, **overrides)
    resp = api_client.create_section(payload, make_director_headers(lab_id))
    return get_success_data(resp)


def register_checklist_edition(code, version, **overrides):
    payload = create_checklist_edition_payload(checklist_code=code,
                                               checklist_version=version, **overrides)
    resp = api_client.create_checklist_edition(payload, OFFICER)
    return get_success_data(resp)


def assign_checklist_to_section(section_id, code, version,
                                expected_enrollment_version=None):
    """Assign a checklist edition to a section.

    Per PRD §2.9, when the parent enrollment is still WAITING the request must
    carry `expected_enrollment_version` equal to the enrollment's current
    version. When no explicit value is supplied, re-read the section's parent
    enrollment and supply the current version automatically when WAITING.
    """
    payload = {"checklist_code": code, "checklist_version": version}
    if expected_enrollment_version is None:
        sec = get_success_data(api_client.get_section(section_id, OFFICER))
        enr = get_success_data(api_client.get_enrollment(sec["enrollment_id"], OFFICER))
        if enr["status"] == "WAITING":
            expected_enrollment_version = enr["version"]
    if expected_enrollment_version is not None:
        payload["expected_enrollment_version"] = expected_enrollment_version
    resp = api_client.assign_checklist(section_id, payload, OFFICER)
    return get_success_data(resp)


def setup_lab_with_active_enrollment(discipline="CHEMISTRY",
                                     checklist_code="CHM",
                                     checklist_version="2026",
                                     section_overrides=None,
                                     num_sections=1):
    """Laboratory + enrollment + N sections, first section checklist-assigned so
    the enrollment flips ACTIVE and the laboratory flips ENROLLED.

    Returns dict(lab, enrollment, sections, edition).
    """
    lab = create_laboratory()
    enr = create_enrollment_for_lab(lab["id"], discipline)
    register_checklist_edition(checklist_code, checklist_version)
    sections = []
    for i in range(num_sections):
        ov = dict(section_overrides or {})
        ov.setdefault("section_name", f"Bench {i + 1}")
        sec = create_section_for_enrollment(enr["id"], lab["id"], **ov)
        sections.append(sec)
    for sec in sections:
        assign_checklist_to_section(sec["id"], checklist_code, checklist_version)
    enr = get_success_data(api_client.get_enrollment(enr["id"], OFFICER))
    lab = get_success_data(api_client.get_laboratory(lab["id"], OFFICER))
    return {"lab": lab, "enrollment": enr, "sections": sections}


# ---------------------------------------------------------------------------
# Tier 1b: personnel and method validations (posture inputs)
# ---------------------------------------------------------------------------

def create_qualified_personnel(enrollment_id, lab_id, **overrides):
    """Personnel record verified to QUALIFIED."""
    payload = create_personnel_record_payload(enrollment_id=enrollment_id, **overrides)
    pers = get_success_data(
        api_client.create_personnel_record(payload, make_director_headers(lab_id)))
    get_success_data(api_client.verify_qualification(pers["id"], OFFICER))
    return get_success_data(api_client.get_personnel_record(pers["id"], OFFICER))


def create_approved_method_validation(enrollment_id, lab_id, **overrides):
    """Method validation created, submitted, and approved."""
    payload = create_method_validation_payload(enrollment_id=enrollment_id, **overrides)
    mv = get_success_data(
        api_client.create_method_validation(payload, make_director_headers(lab_id)))
    get_success_data(
        api_client.submit_method_validation(mv["id"], make_director_headers(lab_id)))
    get_success_data(api_client.approve_method_validation(mv["id"], OFFICER))
    return get_success_data(api_client.get_method_validation(mv["id"], OFFICER))


# ---------------------------------------------------------------------------
# Tier 2: posture-ready laboratory (satisfies all four conduct gates)
# ---------------------------------------------------------------------------

def setup_posture_ready_lab(discipline="CHEMISTRY",
                            checklist_code="CHM",
                            checklist_version="2026",
                            section_overrides=None,
                            personnel=True,
                            method_validation=True):
    """Laboratory with one ACTIVE enrollment whose section is ASSIGNED, plus a
    QUALIFIED personnel record and an APPROVED method validation so any cycle on
    this laboratory has posture_ready == true.

    Returns dict(lab, enrollment, section, personnel, method_validation).
    """
    base = setup_lab_with_active_enrollment(
        discipline=discipline, checklist_code=checklist_code,
        checklist_version=checklist_version, section_overrides=section_overrides)
    pers = None
    mv = None
    if personnel:
        pers = create_qualified_personnel(base["enrollment"]["id"], base["lab"]["id"])
    if method_validation:
        mv = create_approved_method_validation(base["enrollment"]["id"],
                                               base["lab"]["id"])
    return {
        "lab": base["lab"],
        "enrollment": base["enrollment"],
        "section": base["sections"][0],
        "personnel": pers,
        "method_validation": mv,
    }


# ---------------------------------------------------------------------------
# Tier 2b: inspectors and team assembly
# ---------------------------------------------------------------------------

def create_inspector(affiliated_lab_id, specialties=("CHEMISTRY",), **overrides):
    payload = create_inspector_profile_payload(
        affiliated_laboratory_id=affiliated_lab_id,
        specialties=list(specialties), **overrides)
    resp = api_client.create_inspector_profile(payload, OFFICER)
    return get_success_data(resp)


def create_cycle(lab_id, scheduled_start="2026-09-10T00:00:00Z",
                 scheduled_end="2026-09-20T00:00:00Z", **overrides):
    payload = create_inspection_cycle_payload(
        laboratory_id=lab_id, scheduled_start=scheduled_start,
        scheduled_end=scheduled_end, **overrides)
    resp = api_client.create_inspection_cycle(payload, OFFICER)
    return get_success_data(resp)


def create_assignment(cycle_id, inspector_id, role="LEAD"):
    payload = create_team_assignment_payload(
        inspection_cycle_id=cycle_id, inspector_id=inspector_id, role_in_team=role)
    resp = api_client.create_team_assignment(payload, OFFICER)
    return get_success_data(resp)


def setup_screened_cycle(cycle=None, lab_id=None, inspector=None,
                         scheduled_start="2026-09-10T00:00:00Z",
                         scheduled_end="2026-09-20T00:00:00Z"):
    """A cycle with one CLEARED LEAD inspector, moved to SCREENED.

    Returns dict(cycle, inspector, assignment).
    """
    if cycle is None:
        assert lab_id is not None
        cycle = create_cycle(lab_id, scheduled_start, scheduled_end)
    if inspector is None:
        peer_lab = create_laboratory()
        inspector = create_inspector(peer_lab["id"])
    asg = create_assignment(cycle["id"], inspector["id"], "LEAD")
    get_success_data(api_client.clear_assignment(asg["id"], OFFICER))
    get_success_data(api_client.screen_team(cycle["id"], OFFICER))
    cycle = get_success_data(api_client.get_inspection_cycle(cycle["id"], OFFICER))
    return {"cycle": cycle, "inspector": inspector, "assignment": asg}


def setup_conducted_cycle(conduct_at="2026-09-12T00:00:00Z",
                          scheduled_start="2026-09-10T00:00:00Z",
                          scheduled_end="2026-09-20T00:00:00Z",
                          discipline="CHEMISTRY",
                          checklist_code="CHM",
                          section_overrides=None,
                          num_inspectors=2):
    """Posture-ready lab + screened cycle + clock advanced into the window +
    cycle CONDUCTED. Returns dict with everything tests need downstream.
    """
    lab_setup = setup_posture_ready_lab(
        discipline=discipline, checklist_code=checklist_code,
        section_overrides=section_overrides)
    lab = lab_setup["lab"]
    peer_lab = create_laboratory()
    inspectors = [
        create_inspector(peer_lab["id"], specialties=[discipline])
        for _ in range(num_inspectors)
    ]
    cycle = create_cycle(lab["id"], scheduled_start, scheduled_end)
    asg = create_assignment(cycle["id"], inspectors[0]["id"], "LEAD")
    get_success_data(api_client.clear_assignment(asg["id"], OFFICER))
    get_success_data(api_client.screen_team(cycle["id"], OFFICER))
    get_success_data(api_client.set_clock(conduct_at, ADMIN))
    get_success_data(api_client.conduct_cycle(cycle["id"], OFFICER))
    cycle = get_success_data(api_client.get_inspection_cycle(cycle["id"], OFFICER))
    return {
        "lab": lab,
        "enrollment": lab_setup["enrollment"],
        "section": lab_setup["section"],
        "personnel": lab_setup["personnel"],
        "method_validation": lab_setup["method_validation"],
        "peer_lab": peer_lab,
        "inspectors": inspectors,
        "cycle": cycle,
        "lead_assignment": asg,
    }


def cite_finding(cycle_id, section_id, inspector_id, level="LEVEL_1",
                 item_code="CHM.10000"):
    """Inspector cites a deficiency on a conducted cycle."""
    payload = create_finding_payload(
        inspection_cycle_id=cycle_id, section_id=section_id,
        checklist_item_code=item_code, deficiency_level=level)
    resp = api_client.create_finding(payload, make_inspector_headers(inspector_id))
    return get_success_data(resp)


def setup_findings_issued(conduct_at="2026-09-12T00:00:00Z",
                          level="LEVEL_1",
                          item_code="CHM.10000",
                          section_overrides=None,
                          discipline="CHEMISTRY",
                          checklist_code="CHM"):
    """Conducted cycle with one finding cited, then issue-findings called.

    Returns dict(cycle, finding, inspectors, lab, enrollment, section).
    """
    ctx = setup_conducted_cycle(conduct_at=conduct_at,
                                section_overrides=section_overrides,
                                discipline=discipline, checklist_code=checklist_code)
    finding = cite_finding(ctx["cycle"]["id"], ctx["section"]["id"],
                           ctx["inspectors"][0]["id"], level=level,
                           item_code=item_code)
    issued = get_success_data(api_client.issue_findings(ctx["cycle"]["id"], OFFICER))
    ctx["cycle"] = issued
    ctx["finding"] = finding
    return ctx


def respond_and_accept(finding_id, lab_id, accepting_inspector_id,
                       response_text="Corrected."):
    """Laboratory responds to a finding; a different inspector accepts."""
    get_success_data(api_client.respond_to_finding(
        finding_id, response_text, make_director_headers(lab_id)))
    get_success_data(api_client.accept_finding(
        finding_id, make_inspector_headers(accepting_inspector_id)))
    return get_success_data(api_client.get_finding(finding_id, OFFICER))


# ---------------------------------------------------------------------------
# Tier 3: PT program builders
# ---------------------------------------------------------------------------

def create_pt_subscription(enrollment_id, lab_id, analytes=None):
    payload = create_pt_subscription_payload(
        enrollment_id=enrollment_id,
        analytes=analytes or [{"name": "glucose", "critical": True}])
    resp = api_client.create_pt_subscription(payload, make_director_headers(lab_id))
    return get_success_data(resp)


def create_shipment(subscription_id, event_code=None):
    payload = create_pt_shipment_payload(subscription_id=subscription_id)
    if event_code is not None:
        payload["event_code"] = event_code
    resp = api_client.create_pt_shipment(payload, PTC)
    return get_success_data(resp)


def submit_result(shipment_id, lab_id, analyte_scores, collected_at="2026-09-02T00:00:00Z"):
    payload = create_pt_result_payload(shipment_id=shipment_id,
                                       collected_at=collected_at,
                                       analyte_scores=analyte_scores)
    resp = api_client.create_pt_result(payload, make_director_headers(lab_id))
    return resp


def submit_result_ok(shipment_id, lab_id, analyte_scores,
                     collected_at="2026-09-02T00:00:00Z"):
    return get_success_data(
        submit_result(shipment_id, lab_id, analyte_scores, collected_at))


def list_investigations(enrollment_id):
    data = get_success_data(api_client.list_pt_investigations(
        OFFICER, params={"enrollment_id": enrollment_id}))
    return data


def setup_pt_active_enrollment(analytes=None, discipline="CHEMISTRY"):
    """Lab with ACTIVE enrollment + PT subscription. Returns dict(lab, enrollment, subscription)."""
    base = setup_lab_with_active_enrollment(discipline=discipline)
    sub = create_pt_subscription(base["enrollment"]["id"], base["lab"]["id"],
                                 analytes=analytes)
    return {"lab": base["lab"], "enrollment": base["enrollment"],
            "sections": base["sections"], "subscription": sub}


def setup_single_unsatisfactory_event(analytes=None, failing_scores=None):
    """Enrollment with one graded UNSATISFACTORY event and the auto-created
    investigation left OPEN. Returns dict with ctx + investigation.
    """
    ctx = setup_pt_active_enrollment(analytes=analytes)
    analytes = analytes or [{"name": "glucose", "critical": True}]
    failing_scores = failing_scores or [
        {"name": a["name"], "score": 50} for a in analytes]
    sh = create_shipment(ctx["subscription"]["id"], event_code="C-2026-A")
    res = submit_result_ok(sh["id"], ctx["lab"]["id"], failing_scores)
    invs = list_investigations(ctx["enrollment"]["id"])
    assert len(invs) == 1, f"expected one auto-created investigation, got {len(invs)}"
    ctx.update({"shipment": sh, "result": res, "investigation": invs[0]})
    return ctx


def setup_rolling_unsatisfactory_enrollment(analytes=None):
    """Enrollment whose standing_rolling is UNSATISFACTORY: two graded
    UNSATISFACTORY events, the first investigation RESOLVED, the second OPEN.

    Returns dict(ctx..., inv1, inv2).
    """
    analytes = analytes or [{"name": "glucose", "critical": True}]
    failing = [{"name": a["name"], "score": 50} for a in analytes]
    ctx = setup_pt_active_enrollment(analytes=analytes)
    sh1 = create_shipment(ctx["subscription"]["id"], event_code="C-2026-A")
    submit_result_ok(sh1["id"], ctx["lab"]["id"], failing)
    get_success_data(api_client.close_pt_shipment(sh1["id"], PTC))
    inv1 = list_investigations(ctx["enrollment"]["id"])[0]
    get_success_data(api_client.resolve_investigation(inv1["id"], OFFICER))
    sh2 = create_shipment(ctx["subscription"]["id"], event_code="C-2026-B")
    submit_result_ok(sh2["id"], ctx["lab"]["id"], failing,
                     collected_at="2026-09-02T12:00:00Z")
    invs = list_investigations(ctx["enrollment"]["id"])
    assert len(invs) == 2, f"expected two investigations, got {len(invs)}"
    ctx.update({"shipment1": sh1, "shipment2": sh2, "inv1": inv1, "inv2": invs[1]})
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: decision / probation builders
# ---------------------------------------------------------------------------

def setup_decided_cycle(decision="DENIED", conduct_at="2026-09-12T00:00:00Z",
                        resolve_finding=False):
    """Findings-issued cycle, optionally with its finding accepted, decided.

    Returns ctx dict from setup_findings_issued plus final cycle state.
    """
    ctx = setup_findings_issued(conduct_at=conduct_at)
    if resolve_finding:
        respond_and_accept(ctx["finding"]["id"], ctx["lab"]["id"],
                           ctx["inspectors"][1]["id"])
    decided = get_success_data(
        api_client.decide_cycle(ctx["cycle"]["id"], decision, OFFICER))
    ctx["cycle"] = decided
    ctx["lab"] = get_success_data(api_client.get_laboratory(ctx["lab"]["id"], OFFICER))
    return ctx
