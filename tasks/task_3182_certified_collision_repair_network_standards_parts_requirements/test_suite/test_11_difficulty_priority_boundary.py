"""Difficulty tests (queue A): validation priority pairs and boundary
precision (grade thresholds, empty-set ratio)."""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    create_shop, create_certified_shop, create_technician, create_order,
    create_published_requirement, attest, open_cycle,
    schedule_and_run_audit, sm, auditor_as, certify_shop,
    WINDOW2_START, WINDOW2_END,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
AUD1 = TEST_USERS["auditor_headers"]
AUD2 = TEST_USERS["auditor2_headers"]


def test_state_vs_business_safety_on_approve(api):
    """PRD §2.10: "Validation across the board runs in a fixed priority order:
    authentication and authorization first (ERR_UNAUTHENTICATED, then
    ERR_UNAUTHORIZED), then existence (ERR_NOT_FOUND), then legal source state
    (ERR_INVALID_STATE, HTTP 409), then optimistic concurrency
    (ERR_STALE_VERSION), and only then the domain-specific business rules of
    §3 — safety classification, scanning and calibration chronology, ...".
    PRD §3.5: "From ESTIMATE, voiding is unconditional and moves the order to
    the terminal VOIDED."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_approve
    """
    shop, _cycle = create_certified_shop(
        legal_name="Priority Body", state_code="FL", zip_code="33101",
        latitude=25.76, longitude=-80.19)
    tech = create_technician(shop["id"], full_name="Vi Check")
    order = create_order(shop["id"], tech["id"], vin="1HGCV1F34LA000006",
                         estimate_total_cents=40000)
    validate_success(api.void_order(order["id"], {}, sm(shop["id"])))
    # VOIDED order with NO PRE_SCAN: both a state failure (wrong source state)
    # and a business-safety failure (missing pre-scan) apply; the state check
    # must surface.
    resp = api.approve_order(order["id"], sm(shop["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_approve_estimate_order_without_prescan_reports_safety(api):
    """PRD §3.5: "at least one PRE_SCAN procedure step with a result other
    than NOT_APPLICABLE must already exist on the order, else approval is
    rejected with ERR_PRE_SCAN_REQUIRED (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_approve
    """
    shop, _cycle = create_certified_shop(
        AUD2, legal_name="Priority Body 2", state_code="FL", zip_code="33102",
        latitude=25.76, longitude=-80.19)
    tech = create_technician(shop["id"], full_name="No Scan")
    order = create_order(shop["id"], tech["id"], vin="1HGCV1F34LA000046",
                         estimate_total_cents=40000)
    resp = api.approve_order(order["id"], sm(shop["id"]))
    validate_error(resp, ApiErrorId.ERR_PRE_SCAN_REQUIRED)


def test_business_safety_vs_business_referential_on_part_line(api):
    """PRD §3.6: "Safety-critical parts — airbags, seatbelts, structural
    components — may only be OE or OE_SURPLUS; a safety-critical line
    classified otherwise is rejected with ERR_SAFETY_PART_CLASS (HTTP 422)."
    PRD §2.10: "Where multiple business checks could reject the same request,
    the check whose category is safety-related surfaces before referential
    checks, which surface before constraint and temporal checks".

    Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_referential_on_part_line
    """
    shop, _cycle = create_certified_shop(
        legal_name="Safety First Auto", state_code="GA", zip_code="30301",
        latitude=33.75, longitude=-84.39)
    tech = create_technician(shop["id"], full_name="Di Volt")
    order = create_order(shop["id"], tech["id"], vin="1HGCV1F34LA000007",
                         estimate_total_cents=90000, vehicle_model_year=2019)
    resp = api.create_part_line(
        order["id"],
        {"part_number": "AIRBAG-1", "part_class": "AFTERMARKET",
         "unit_cost_cents": 30000, "quantity": 1, "is_safety_critical": True},
        sm(shop["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_SAFETY_PART_CLASS)


def test_safety_part_class_rejected_even_when_documented(api):
    """PRD §3.6: "Safety-critical parts — airbags, seatbelts, structural
    components — may only be OE or OE_SURPLUS; a safety-critical line
    classified otherwise is rejected with ERR_SAFETY_PART_CLASS (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_referential_on_part_line
    """
    shop, _cycle = create_certified_shop(
        AUD2, legal_name="Safety First Auto 2", state_code="GA", zip_code="30302",
        latitude=33.75, longitude=-84.39)
    tech = create_technician(shop["id"], full_name="Doc Safe")
    order = create_order(shop["id"], tech["id"], vin="1HGCV1F34LA000047",
                         estimate_total_cents=90000, vehicle_model_year=2019)
    resp = api.create_part_line(
        order["id"],
        {"part_number": "BELT-2", "part_class": "RECYCLED",
         "unit_cost_cents": 30000, "quantity": 1, "is_safety_critical": True,
         "alternative_justification": "consumer consent ref CC-9"},
        sm(shop["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_SAFETY_PART_CLASS)


def _attest_all(api, shop_id, req_ids):
    for rid in req_ids:
        attest(shop_id, rid)


def _grade_boundary_shop(api, legal_name, zip_code, findings):
    """CERTIFIED shop whose second-cycle audit issues the given findings; all
    corrective actions submitted and verified; cycle closed PASS. Returns the
    closed audit. (The shop must already be CERTIFIED — an APPLICANT's cycle
    closes without a posture change unless the grade is A or B on cycle 1,
    per §3.1.)"""
    shop = create_shop(legal_name=legal_name, state_code="IL", zip_code=zip_code,
                       latitude=41.88, longitude=-87.63)
    req_ids = []
    for i, (category, severity) in enumerate(findings):
        req = create_published_requirement(
            requirement_code=f"XX-{zip_code}-{i}", category=category,
            description=f"r{i}", severity_if_failed=severity,
            # The logical clock may already sit at the previous shop's audit
            # begin instant when this helper runs a second time in one test.
            effective_from="2026-09-02T10:00:00Z")
        req_ids.append(req["id"])
    att_ids = [attest(shop["id"], rid)["id"] for rid in req_ids]
    certify_shop(shop["id"])
    cycle = open_cycle(shop["id"], WINDOW2_START, WINDOW2_END)
    audit = schedule_and_run_audit(cycle["id"], AUD1,
                                   scheduled_start="2026-09-02T09:00:00Z",
                                   scheduled_end="2026-09-02T17:00:00Z",
                                   begin_at="2026-09-02T10:00:00Z")
    get_success_data(api.issue_findings(
        audit["id"],
        {"findings": [{"attestation_id": aid, "severity": sev}
                      for aid, (_cat, sev) in zip(att_ids, findings)]},
        AUD1))
    cas = get_success_data(api.list_audit_corrective_actions(audit["id"], AUD1))
    for ca in cas:
        get_success_data(api.submit_corrective_action(
            ca["id"], {"evidence_uri": "s3://ev/f.pdf"}, sm(shop["id"])))
    for ca in cas:
        get_success_data(api.verify_corrective_action(ca["id"], {"verdict": "VERIFIED"}, AUD2))
    cyc = validate_success(api.get_cycle(cycle["id"], AUD1))
    validate_success(api.close_cycle(
        cycle["id"], {"expected_cycle_version": cyc["version"], "result": "PASS"}, AUD1))
    return shop, audit, cycle


def test_grade_boundary_24_vs_25_points(api):
    """PRD §3.3: "The audit's severity_points are the sum over all of its
    corrective actions ... of severity weights: 1 per MINOR, 5 per MAJOR, 25
    per CRITICAL. ... The grade boundaries are inclusive exactly as stated: 0
    effective points is grade A; from 1 up to and including 5 is B; from 6 up
    to and including 24 is C; 25 or more is F." PRD §3.1: "A cycle close with
    grade C instead moves CERTIFIED → PROBATION" (and from APPLICANT, a close
    with grade C applies the grade's posture transition per PRD §3.3: "Closing
    with PASS from CORRECTIVE_ACTION ... applies the shop posture transition
    dictated by the grade (CERTIFIED for A or B, PROBATION for C, SUSPENDED
    for F)").

    Design: Difficulty/boundary_precision_check/grade_boundary_24_vs_25_points
    """
    # 24 points: 4 MAJOR (20) + 4 MINOR (4)
    shop24, audit24, _ = _grade_boundary_shop(
        api, "Boundary 24 Body", "60601",
        [("EQUIPMENT", "MAJOR")] * 4 + [("TOOLING", "MINOR")] * 4)
    a24 = validate_success(api.get_audit(audit24["id"], AUD1))
    assert a24["severity_points"] == 24
    assert a24["grade"] == "C"
    s24 = validate_success(api.get_shop(shop24["id"], ADMIN))
    assert s24["certification_status"] == "PROBATION"

    # 25 points: 1 CRITICAL
    shop25, audit25, _ = _grade_boundary_shop(
        api, "Boundary 25 Body", "60602",
        [("STRUCTURAL", "CRITICAL")])
    a25 = validate_success(api.get_audit(audit25["id"], AUD1))
    assert a25["severity_points"] == 25
    assert a25["grade"] == "F"
    s25 = validate_success(api.get_shop(shop25["id"], ADMIN))
    assert s25["certification_status"] == "SUSPENDED"


def test_grade_boundary_5_vs_6_points(api):
    """PRD §3.3: "The grade boundaries are inclusive exactly as stated: 0
    effective points is grade A; from 1 up to and including 5 is B; from 6 up
    to and including 24 is C; 25 or more is F."

    Design: Difficulty/boundary_precision_check/grade_boundary_24_vs_25_points
    """
    # 5 points: 1 MAJOR
    shop5, audit5, _ = _grade_boundary_shop(
        api, "Boundary 5 Body", "60603", [("EQUIPMENT", "MAJOR")])
    a5 = validate_success(api.get_audit(audit5["id"], AUD1))
    assert a5["severity_points"] == 5
    assert a5["grade"] == "B"

    # 6 points: 1 MAJOR + 1 MINOR
    _shop6, audit6, _ = _grade_boundary_shop(
        api, "Boundary 6 Body", "60604",
        [("EQUIPMENT", "MAJOR"), ("TOOLING", "MINOR")])
    a6 = validate_success(api.get_audit(audit6["id"], AUD1))
    assert a6["severity_points"] == 6
    assert a6["grade"] == "C"


def test_oe_ratio_empty_set_equals_one(api):
    """PRD §3.6: "both are defined as 1.0 when the order has no active lines
    at all — the empty set is vacuously compliant." PRD §3.6: "A line is born
    ACTIVE in line_status and may be removed — moving to the terminal REMOVED
    — only while the order remains editable in ESTIMATE, APPROVED, or
    IN_REPAIR."

    Design: Difficulty/boundary_precision_check/oe_ratio_empty_set_equals_one
    """
    shop, _cycle = create_certified_shop(
        legal_name="Emptyset Body", state_code="OR", zip_code="97201",
        latitude=45.51, longitude=-122.68)
    tech = create_technician(shop["id"], full_name="Mo Parts")
    order = create_order(shop["id"], tech["id"], vin="1HGCV1F34LA000008",
                         estimate_total_cents=30000)
    line = validate_success(api.create_part_line(
        order["id"],
        {"part_number": "TMP-1", "part_class": "AFTERMARKET", "unit_cost_cents": 1000,
         "quantity": 1, "alternative_justification": "temp line; consent ref C-9"},
        sm(shop["id"])), 201)
    validate_success(api.delete_part_line(order["id"], line["id"], sm(shop["id"])))
    fetched = validate_success(api.get_repair_order(order["id"], sm(shop["id"])))
    assert fetched["oe_parts_ratio_by_count"] == 1.0
    assert fetched["oe_parts_ratio_by_cost"] == 1.0


def test_oe_ratio_zero_lines_at_creation(api):
    """PRD §3.5: "The order begins in ESTIMATE with rework_count 0, both OE
    parts ratios at 0.0, and completed_at null." (creation-time values) and
    PRD §3.6: "both are defined as 1.0 when the order has no active lines at
    all — the empty set is vacuously compliant."

    Design: Difficulty/boundary_precision_check/oe_ratio_empty_set_equals_one
    """
    shop, _cycle = create_certified_shop(
        AUD2, legal_name="Emptyset Body 2", state_code="OR", zip_code="97202",
        latitude=45.51, longitude=-122.68)
    tech = create_technician(shop["id"], full_name="No Lines")
    order = create_order(shop["id"], tech["id"], vin="1HGCV1F34LA000048",
                         estimate_total_cents=30000)
    assert order["rework_count"] == 0
    assert order["completed_at"] is None
    assert order["oe_parts_ratio_by_count"] in (0.0, 1.0)
    assert order["oe_parts_ratio_by_cost"] in (0.0, 1.0)
    # Per the empty-set rule, a re-read after any ratio-affecting event must
    # report 1.0 while no active lines exist.
    line = validate_success(api.create_part_line(
        order["id"],
        {"part_number": "TMP-2", "part_class": "OE", "unit_cost_cents": 100,
         "quantity": 1},
        sm(shop["id"])), 201)
    validate_success(api.delete_part_line(order["id"], line["id"], sm(shop["id"])))
    fetched = validate_success(api.get_repair_order(order["id"], sm(shop["id"])))
    assert fetched["oe_parts_ratio_by_count"] == 1.0
    assert fetched["oe_parts_ratio_by_cost"] == 1.0
