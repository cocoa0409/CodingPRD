"""Calculation tests: technician currency vacuous satisfaction and the
escalation penalty in audit grading."""
import pytest
from test_helpers import (
    validate_success, get_success_data,
    create_certified_shop, create_technician, create_shop,
    create_published_requirement, open_cycle, attest,
    order_warranty_active, schedule_and_run_audit, sm,
    admin_as, auditor_as,
    TEST_USERS,
    WINDOW2_START, WINDOW2_END,
)

ADMIN = TEST_USERS["admin_headers"]
AUD1 = TEST_USERS["auditor_headers"]
AUD2 = TEST_USERS["auditor2_headers"]


def test_technician_currency_vacuous_full_progress(api):
    """PRD §3.4: "curriculum_progress_pct is 100.0 times the satisfied count
    divided by the required count, rounded to 2 decimal places round-half-up;
    a technician with an empty required set is defined at 100.0 by vacuous
    satisfaction." and "A PROVISIONAL technician becomes CURRENT the first
    time progress reaches 100.0, whether via a completion create or a sweep
    recompute."

    Design: Corner/calculations/technician_currency_vacuous_full_progress
    """
    shop = create_shop(legal_name="Vacuous Body", state_code="ME", zip_code="04101",
                       latitude=43.66, longitude=-70.26)
    tech = create_technician(shop["id"], full_name="Va Cu", tech_role="REFINISH")
    fetched = validate_success(api.get_technician(tech["id"], sm(shop["id"])))
    assert fetched["curriculum_progress_pct"] == 100.0
    assert fetched["status"] == "CURRENT"


def test_technician_currency_partial_progress_stays_provisional(api):
    """PRD §3.4: "The required set is every active course whose
    required_for_roles contains the technician's tech_role. A required course
    is satisfied when the technician holds a completion of that course in
    CURRENT status." and "PROVISIONAL while never-yet-current" (progress below
    100.0 keeps the technician out of CURRENT).

    Design: Corner/calculations/technician_currency_vacuous_full_progress
    """
    shop = create_shop(legal_name="Partial Body", state_code="ME", zip_code="04102",
                       latitude=43.66, longitude=-70.26)
    course1 = get_success_data(api.create_course(
        {"course_code": "TR-P1", "title": "P1", "required_for_roles": ["ESTIMATOR"],
         "validity_months": 12, "credit_hours": 2}, ADMIN))
    course2 = get_success_data(api.create_course(
        {"course_code": "TR-P2", "title": "P2", "required_for_roles": ["ESTIMATOR"],
         "validity_months": 12, "credit_hours": 2}, ADMIN))
    tech = create_technician(shop["id"], full_name="Pa Rt", tech_role="ESTIMATOR")
    get_success_data(api.create_completion(
        tech["id"], {"course_id": course1["id"], "completed_at": "2026-08-15T00:00:00Z",
                     "proof_uri": "s3://proof/p1.pdf"}, ADMIN))
    fetched = validate_success(api.get_technician(tech["id"], sm(shop["id"])))
    assert fetched["curriculum_progress_pct"] == 50.0
    assert fetched["status"] == "PROVISIONAL"


def test_certification_grade_with_escalation_penalty(api):
    """PRD §3.3: "On top of that sits an escalation penalty of 3 points per
    WarrantyClaim against the shop's repairs that is in ESCALATED status at
    the evaluation instant; the two together form the effective points. The
    grade boundaries are inclusive exactly as stated: 0 effective points is
    grade A; from 1 up to and including 5 is B; from 6 up to and including 24
    is C; 25 or more is F." PRD §3.7: "a claim whose defect_category is
    PART_DEFECT, or whose claim_amount_cents exceeds 500,000 cents, must pass
    through ESCALATED before it can be resolved".

    Design: Corner/calculations/certification_grade_with_escalation_penalty
    """
    shop, _cycle1 = create_certified_shop(
        legal_name="Penalty Body", state_code="VT", zip_code="05401",
        latitude=44.48, longitude=-73.21)
    tech = create_technician(shop["id"], full_name="Es Cal")
    order = order_warranty_active(
        shop["id"], tech["id"], vin="1HGCV1F34LA000016", estimate_total_cents=60000)

    claim = validate_success(api.create_warranty_claim(
        order["id"],
        {"claimant_contact": "cust@example.com", "defect_category": "PART_DEFECT",
         "claim_amount_cents": 10000},
        admin_as("adm-0")), 201)
    validate_success(api.review_claim(claim["id"], admin_as("adm-1")))
    validate_success(api.escalate_claim(claim["id"], admin_as("adm-2")))

    req = create_published_requirement(
        requirement_code="EQ-PEN-01", category="EQUIPMENT",
        severity_if_failed="MAJOR", effective_from="2026-09-02T06:00:00Z")
    att = attest(shop["id"], req["id"])
    cycle2 = open_cycle(shop["id"], WINDOW2_START, WINDOW2_END)
    audit2 = schedule_and_run_audit(
        cycle2["id"], AUD1,
        scheduled_start="2026-09-06T09:00:00Z",
        scheduled_end="2026-09-06T17:00:00Z",
        begin_at="2026-09-06T10:00:00Z")
    get_success_data(api.issue_findings(
        audit2["id"],
        {"findings": [{"attestation_id": att["id"], "severity": "MAJOR"}]},
        AUD1))
    cas = get_success_data(api.list_audit_corrective_actions(audit2["id"], AUD1))
    ca = cas[0]
    get_success_data(api.submit_corrective_action(
        ca["id"], {"evidence_uri": "s3://ev/penfix.pdf"}, sm(shop["id"])))
    get_success_data(api.verify_corrective_action(ca["id"], {"verdict": "VERIFIED"}, AUD2))

    cyc2 = validate_success(api.get_cycle(cycle2["id"], AUD1))
    validate_success(api.close_cycle(
        cycle2["id"], {"expected_cycle_version": cyc2["version"], "result": "PASS"}, AUD1))
    audit_now = validate_success(api.get_audit(audit2["id"], AUD1))
    assert audit_now["severity_points"] == 5
    assert audit_now["grade"] == "C"


def test_grade_a_with_zero_effective_points(api):
    """PRD §3.3: "The grade boundaries are inclusive exactly as stated: 0
    effective points is grade A" and "With zero findings, the audit passes
    outright: the audit's grade is set to A (the grade produced by zero
    effective points)".

    Design: Corner/calculations/certification_grade_with_escalation_penalty
    """
    shop, cycle = create_certified_shop(
        AUD2, legal_name="Zero Points Body", state_code="VT", zip_code="05402",
        latitude=44.48, longitude=-73.21)
    audits = get_success_data(api.list_audits(cycle["id"], AUD2))
    audit_now = validate_success(api.get_audit(audits[0]["id"], AUD2))
    assert audit_now["severity_points"] == 0
    assert audit_now["grade"] == "A"
    assert audit_now["status"] == "PASSED"
