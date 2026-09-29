"""Rule-priority conflicts (SCAFFOLD_DIFFICULTY_DESIGN ``priority_pair_validation_conflict``).

Each pair builds a request that trips two rules at once and pins the one PRD 2.9
says must surface, then proves with a control case that the shadowed rule really
does fire on its own — otherwise the priority assertion would be vacuous.
"""
from test_helpers import (
    BOARD_ADMIN_HEADERS,
    INSPECTOR_HEADERS,
    ApiErrorId,
    advance_clock,
    assert_cents,
    assert_points,
    create_candidate,
    create_establishment,
    create_violation_code,
    finding_payload,
    issue_citation,
    refresh_citation,
    refresh_establishment,
    refresh_inspection,
    schedule_inspection,
    setup_finalized_inspection,
    validate_error,
    validate_paginated,
    validate_success,
    workstation_payload,
)


def _findings_of(api, inspection_id):
    return validate_paginated(
        api.list_violation_findings(
            BOARD_ADMIN_HEADERS, {"inspection_id": inspection_id, "limit": 100}
        )
    )


def test_scheduled_inspection_reports_status_gate_not_linkage_gate(api):
    """A doubly invalid finding reports the state gate, not the referential one.

    PRD 2.9 evaluates "State preconditions" at step 11, where
    ``ERR_INSPECTION_NOT_IN_PROGRESS`` lives, strictly before "Referential
    business rules" at step 15, where ``ERR_PRACTITIONER_NOT_LINKED_TO_ESTABLISHMENT``
    lives. The inspection here is still SCHEDULED *and* the attributed
    practitioner has no booth rental anywhere, so only the lower step number may
    be observable.

    Design: Difficulty/priority_pair_validation_conflict/inspection_status_gate_precedes_practitioner_linkage_gate_on_findings
    """
    code = create_violation_code(
        api, severity="MAJOR", base_points=6.00, fine_cents_base=12000,
        category="IMPLEMENT_HANDLING",
    )
    est = create_establishment(
        api, station_capacity=4, establishment_type="BARBERSHOP",
        county_code="NCB", legal_name="Tempo Barbers",
    )
    # No booth rental is ever opened for this candidate, so she is linked to
    # nothing (PRD 3.5's attributed-practitioner rule).
    stranger = create_candidate(api, license_type="BARBER", full_name="Rio Vance")
    assert stranger["license_status"] == "STUDENT"

    inspection = schedule_inspection(api, est["id"], window_index=0)
    assert inspection["status"] == "SCHEDULED"

    resp = api.create_finding(
        inspection["id"],
        finding_payload(
            violation_code_id=code["id"],
            observed_count=1,
            corrected_on_site=False,
            attributed_practitioner_id=stranger["id"],
        ),
        INSPECTOR_HEADERS,
    )
    body = validate_error(resp, ApiErrorId.ERR_INSPECTION_NOT_IN_PROGRESS, 409)
    assert body["error_id"] != ApiErrorId.ERR_PRACTITIONER_NOT_LINKED_TO_ESTABLISHMENT

    unchanged = refresh_inspection(api, inspection["id"])
    assert unchanged["status"] == "SCHEDULED"
    assert unchanged["finding_count"] == 0
    rows, meta = _findings_of(api, inspection["id"])
    assert meta["total_count"] == 0, rows


def test_linkage_gate_surfaces_once_the_inspection_is_in_progress(api):
    """Control case: with the state gate satisfied the linkage rule does fire.

    PRD 3.5: "an attributed_practitioner_id must name a practitioner linked to
    this establishment through a PROPOSED or ACTIVE booth rental on one of its
    workstations, failing which the finding is refused with
    ERR_PRACTITIONER_NOT_LINKED_TO_ESTABLISHMENT (HTTP 422)".

    Design: Difficulty/priority_pair_validation_conflict/inspection_status_gate_precedes_practitioner_linkage_gate_on_findings
    """
    code = create_violation_code(
        api, severity="MAJOR", base_points=6.00, fine_cents_base=12000,
        category="IMPLEMENT_HANDLING",
    )
    est = create_establishment(
        api, station_capacity=4, establishment_type="BARBERSHOP", county_code="NCB"
    )
    stranger = create_candidate(api, license_type="BARBER")

    inspection = schedule_inspection(api, est["id"], window_index=0)
    started = validate_success(api.start_inspection(inspection["id"], BOARD_ADMIN_HEADERS))
    assert started["status"] == "IN_PROGRESS"

    resp = api.create_finding(
        inspection["id"],
        finding_payload(
            violation_code_id=code["id"],
            observed_count=1,
            corrected_on_site=False,
            attributed_practitioner_id=stranger["id"],
        ),
        INSPECTOR_HEADERS,
    )
    validate_error(resp, ApiErrorId.ERR_PRACTITIONER_NOT_LINKED_TO_ESTABLISHMENT, 422)

    unchanged = refresh_inspection(api, inspection["id"])
    assert unchanged["finding_count"] == 0
    rows, meta = _findings_of(api, inspection["id"])
    assert meta["total_count"] == 0, rows


def test_frozen_posture_shadows_the_delinquent_fine_block_on_workstation_add(api):
    """Both gates are genuinely tripped, and PRD 2.9 names the winner outright.

    PRD 2.9: "Because the frozen-posture check at step 13 precedes the
    delinquency block at step 17, an establishment that is simultaneously FROZEN
    and carrying delinquent fines reports ERR_POSTURE_FROZEN, not
    ERR_OUTSTANDING_FINES_BLOCK_EXPANSION."

    The facility is left at PENDING_INSPECTION, which PRD 2.6 lists as operable,
    so the step-11 operability gate cannot shadow the pair; and the single finding
    is MAJOR, so PRD 3.9's delinquency sweep does not suspend the licence and
    collapse the two branches into one.

    Design: Difficulty/priority_pair_validation_conflict/frozen_posture_gate_precedes_delinquent_fine_gate_on_workstation_add
    """
    code = create_violation_code(
        api, severity="MAJOR", base_points=6.00, fine_cents_base=12000,
        category="IMPLEMENT_HANDLING", code="IMP-200",
    )
    est = create_establishment(
        api, station_capacity=8, establishment_type="SALON",
        county_code="NCD", legal_name="Bright Shears",
    )
    # 6.00 * 2.5 (MAJOR) * 7 * 1.0 * 1.0 = 105.00, so PRD 2.6 freezes the posture.
    inspection = setup_finalized_inspection(
        api,
        est["id"],
        findings=[{"violation_code_id": code["id"], "observed_count": 7,
                   "corrected_on_site": False}],
        window_index=0,
    )["inspection"]
    assert_points(inspection["final_adjusted_score"], 105.00, "final_adjusted_score")
    assert inspection["final_outcome"] == "FAIL"
    assert_points(
        inspection["demerit_balance_before_finalize"], 0.00,
        "demerit_balance_before_finalize",
    )

    citation = issue_citation(api, inspection["id"], subject_type="ESTABLISHMENT")
    assert_cents(citation["assessed_fine_cents"], 42000, "assessed_fine_cents")
    assert_cents(citation["administrative_fee_cents"], 3360, "administrative_fee_cents")
    assert_cents(citation["total_due_cents"], 45360, "total_due_cents")
    assert citation["max_finding_severity"] == "MAJOR"

    # PRD 3.9's delinquency sweep: due_at is issued_at + 30 days, and the
    # comparison against the new clock value is strict.
    advance_clock(api, "2026-09-01T00:00:00.000Z")

    delinquent = refresh_citation(api, citation["id"])
    assert delinquent["status"] == "DELINQUENT"
    assert_cents(delinquent["outstanding_fine_cents"], 49896, "outstanding_fine_cents")

    frozen = refresh_establishment(api, est["id"])
    assert frozen["license_status"] == "PENDING_INSPECTION"
    assert frozen["compliance_posture"] == "FROZEN"
    assert_points(frozen["demerit_balance"], 105.00, "demerit_balance")
    assert_cents(
        frozen["delinquent_fine_total_cents"], 49896, "delinquent_fine_total_cents"
    )

    resp = api.create_workstation(
        est["id"],
        workstation_payload(station_number=1, station_type="STYLING_CHAIR"),
        BOARD_ADMIN_HEADERS,
    )
    body = validate_error(resp, ApiErrorId.ERR_POSTURE_FROZEN, 409)
    assert body["error_id"] != ApiErrorId.ERR_OUTSTANDING_FINES_BLOCK_EXPANSION

    after = refresh_establishment(api, est["id"])
    assert after["station_count"] == 0


def test_delinquent_fines_alone_do_block_expansion_with_402(api):
    """Control case: with the posture clear, the fiscal gate at step 17 surfaces.

    PRD 3.3: "the establishment's delinquent_fine_total_cents must be exactly 0,
    and an establishment carrying delinquent fines is refused expansion with
    ERR_OUTSTANDING_FINES_BLOCK_EXPANSION (HTTP 402)". A 1.00-point MINOR visit
    keeps ``demerit_balance`` far below PRD 2.6's 100.00 freeze threshold, so the
    step-13 gate cannot pre-empt the step-17 one here.

    Design: Difficulty/priority_pair_validation_conflict/frozen_posture_gate_precedes_delinquent_fine_gate_on_workstation_add
    """
    code = create_violation_code(
        api, severity="MINOR", base_points=1.00, fine_cents_base=12000,
        category="RECORDKEEPING",
    )
    est = create_establishment(api, station_capacity=8, county_code="NCD")
    inspection = setup_finalized_inspection(
        api,
        est["id"],
        findings=[{"violation_code_id": code["id"], "observed_count": 1,
                   "corrected_on_site": False}],
        window_index=0,
    )["inspection"]
    assert_points(inspection["final_adjusted_score"], 1.00, "final_adjusted_score")
    assert inspection["final_outcome"] == "PASS"

    citation = issue_citation(api, inspection["id"], subject_type="ESTABLISHMENT")
    assert_cents(citation["total_due_cents"], 12600, "total_due_cents")
    advance_clock(api, "2026-09-01T00:00:00.000Z")

    delinquent = refresh_citation(api, citation["id"])
    assert delinquent["status"] == "DELINQUENT"
    assert_cents(delinquent["outstanding_fine_cents"], 13860, "outstanding_fine_cents")

    operable = refresh_establishment(api, est["id"])
    # PRD 2.6: 1.00 point is below every posture threshold and a MINOR citation
    # never counts toward open_critical_citation_count, so the posture is CLEAR.
    assert operable["compliance_posture"] == "CLEAR"
    assert_points(operable["demerit_balance"], 1.00, "demerit_balance")
    assert_cents(
        operable["delinquent_fine_total_cents"], 13860, "delinquent_fine_total_cents"
    )

    resp = api.create_workstation(
        est["id"],
        workstation_payload(station_number=1, station_type="STYLING_CHAIR"),
        BOARD_ADMIN_HEADERS,
    )
    validate_error(resp, ApiErrorId.ERR_OUTSTANDING_FINES_BLOCK_EXPANSION, 402)

    after = refresh_establishment(api, est["id"])
    assert after["station_count"] == 0
