"""Inclusive-boundary probes (SCAFFOLD_DIFFICULTY_DESIGN ``boundary_precision_check``).

Three metrics on three endpoints, each pinned so that a strict comparison, a
rounded running sum or a null-for-empty shortcut is visible from the response.
"""
from test_helpers import (
    BOARD_ADMIN_HEADERS,
    ApiErrorId,
    assert_instants_equal,
    assert_points,
    create_establishment,
    create_violation_code,
    refresh_establishment,
    refresh_inspection,
    refresh_workstation,
    sanitation_log_payload,
    setup_establishment_with_posted_practitioner,
    setup_finalized_inspection,
    setup_inspection_in_progress,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_exactly_fifty_demerits_is_restricted(api):
    """The RESTRICTED threshold is reached, not merely passed.

    PRD 2.6: the posture "is RESTRICTED when demerit_balance has reached 50.00
    points or more", and "To make the inclusivity concrete: a balance of 49.99
    yields WATCH, 50.00 yields RESTRICTED". PRD 3.5 pins the arithmetic:
    10.00 * 2.5 (MAJOR) * 2 * 1.0 * 1.0 = 50.00 exactly.

    Design: Difficulty/boundary_precision_check/posture_restricted_threshold_is_inclusive_at_exactly_fifty_demerits
    """
    code = create_violation_code(
        api, severity="MAJOR", base_points=10.00, fine_cents_base=8000,
        category="FACILITY", code="FAC-410",
    )
    est = create_establishment(
        api, station_capacity=5, county_code="NCF", legal_name="Vault Salon"
    )
    inspection = setup_finalized_inspection(
        api,
        est["id"],
        findings=[{"violation_code_id": code["id"], "observed_count": 2,
                   "corrected_on_site": False}],
        window_index=0,
    )["inspection"]

    assert_points(inspection["final_adjusted_score"], 50.00, "final_adjusted_score")
    assert inspection["final_outcome"] == "FAIL"

    after = refresh_establishment(api, est["id"])
    assert_points(after["demerit_balance"], 50.00, "demerit_balance")
    assert after["compliance_posture"] == "RESTRICTED"
    # A FAIL never promotes a facility that has never passed (PRD 3.7 hop four).
    assert after["license_status"] == "PENDING_INSPECTION"


def test_just_under_fifty_demerits_remains_watch(api):
    """The far side of the same boundary, built so a rounded sum would flip it.

    PRD 2.6: the posture is "WATCH when demerit_balance has reached 20.00 points
    or more" once the RESTRICTED test has failed. PRD 2.7 requires each finding's
    value to be rounded first and the sum rounded again, and PRD 3.5 gives
    9.90 * 1.0 (MINOR) * 5 * 1.0 * 1.0 = 49.50 -- an implementation that rounded
    the running total to whole points would report 50.00 and cross the band.

    Design: Difficulty/boundary_precision_check/posture_restricted_threshold_is_inclusive_at_exactly_fifty_demerits
    """
    code = create_violation_code(
        api, severity="MINOR", base_points=9.90, fine_cents_base=3000,
        category="RECORDKEEPING", code="REC-120",
    )
    est = create_establishment(
        api, station_capacity=5, county_code="NCG", legal_name="Rivet Salon"
    )
    inspection = setup_finalized_inspection(
        api,
        est["id"],
        findings=[{"violation_code_id": code["id"], "observed_count": 5,
                   "corrected_on_site": False}],
        window_index=0,
    )["inspection"]

    assert_points(inspection["final_adjusted_score"], 49.50, "final_adjusted_score")
    assert inspection["final_outcome"] == "FAIL"

    after = refresh_establishment(api, est["id"])
    assert_points(after["demerit_balance"], 49.50, "demerit_balance")
    assert after["compliance_posture"] == "WATCH"
    assert after["license_status"] == "PENDING_INSPECTION"


def test_submit_with_no_findings_scores_zero_rather_than_null(api):
    """The empty input set of the weighted sum is the numeric literal 0.00.

    PRD 3.5: "An inspection with no findings at all submits perfectly well, and
    its provisional_adjusted_score is 0.00 rather than null." The band follows the
    same score, and PRD 3.5 makes PASS the residual case once the score is not
    strictly greater than 10.00.

    Design: Difficulty/boundary_precision_check/submit_with_empty_finding_set_scores_zero_not_null
    """
    est = create_establishment(
        api, station_capacity=2, establishment_type="ESTHETICS_SPA",
        county_code="NCH", legal_name="Quiet Studio",
    )
    inspection = setup_inspection_in_progress(api, est["id"], window_index=0)
    assert inspection["status"] == "IN_PROGRESS"
    assert inspection["finding_count"] == 0

    submitted = validate_success(
        api.submit_inspection(inspection["id"], BOARD_ADMIN_HEADERS)
    )
    assert submitted["status"] == "PENDING_REVIEW"
    assert submitted["provisional_adjusted_score"] is not None
    assert_points(
        submitted["provisional_adjusted_score"], 0.00, "provisional_adjusted_score"
    )
    assert submitted["provisional_outcome"] == "PASS"
    assert submitted["finding_count"] == 0
    # The final variant has not run yet (PRD 3.5 writes it on finalization).
    assert submitted["final_adjusted_score"] is None
    assert submitted["final_outcome"] is None


def test_empty_finding_set_submit_posts_no_demerits(api):
    """The stored 0.00 survives a re-read and nothing reached the ledger.

    PRD 3.5 makes submission run the provisional pass only, and PRD 2.6 recomputes
    the posture solely "on every write that appends a DEMERIT_POINTS or FINE_CENTS
    ledger entry or changes license_status" -- which a submission is not. So the
    zero score must persist as a number while the facility stays at 0.00/CLEAR.

    Design: Difficulty/boundary_precision_check/submit_with_empty_finding_set_scores_zero_not_null
    """
    est = create_establishment(
        api, station_capacity=2, establishment_type="ESTHETICS_SPA", county_code="NCH"
    )
    inspection = setup_inspection_in_progress(api, est["id"], window_index=0)
    validate_success(api.submit_inspection(inspection["id"], BOARD_ADMIN_HEADERS))

    reread = refresh_inspection(api, inspection["id"])
    assert reread["status"] == "PENDING_REVIEW"
    assert reread["provisional_adjusted_score"] is not None
    assert_points(
        reread["provisional_adjusted_score"], 0.00, "provisional_adjusted_score"
    )
    assert reread["provisional_outcome"] == "PASS"
    assert reread["finding_count"] == 0
    assert reread["demerit_balance_before_finalize"] is None

    rows, meta = validate_paginated(
        api.list_ledger_entries(
            BOARD_ADMIN_HEADERS,
            {"establishment_id": est["id"], "ledger_type": "DEMERIT_POINTS",
             "limit": 100},
        )
    )
    assert meta["total_count"] == 0, rows

    after = refresh_establishment(api, est["id"])
    assert_points(after["demerit_balance"], 0.00, "demerit_balance")
    assert after["compliance_posture"] == "CLEAR"


def _compliant_nail_table(api):
    """A COMPLIANT NAIL_TABLE, so PRD 3.4's posting gate cannot pre-empt the
    contact-time check ("the station's posting_status must be COMPLIANT at the
    moment of filing")."""
    world = setup_establishment_with_posted_practitioner(api, station_type="NAIL_TABLE")
    station = refresh_workstation(api, world["workstation"]["id"])
    assert station["posting_status"] == "COMPLIANT"
    return station


def _logs_of(api, workstation_id):
    return validate_paginated(
        api.list_workstation_sanitation_logs(
            workstation_id, BOARD_ADMIN_HEADERS, {"limit": 100}
        )
    )


def test_ten_minutes_of_contact_is_accepted_at_the_minimum(api):
    """Exactly the declared minimum is compliant, and it is stored as filed.

    PRD 3.4: "each carries a minimum wet-contact time that the log must meet or
    exceed; the comparison is inclusive, so exactly the minimum is compliant.
    IMPLEMENT_DISINFECTION, FOOT_SPA_AFTER_CLIENT and FOOT_SPA_END_OF_DAY each
    require at least 10 minutes of contact", and "The system computes
    occupancy_end_at as performed_at advanced by contact_minutes minutes".

    Design: Difficulty/boundary_precision_check/implement_disinfection_contact_time_minimum_is_inclusive_at_ten_minutes
    """
    station = _compliant_nail_table(api)

    log = validate_success(
        api.create_sanitation_log(
            sanitation_log_payload(
                workstation_id=station["id"],
                log_type="IMPLEMENT_DISINFECTION",
                performed_at="2026-08-01T09:00:00.000Z",
                contact_minutes=10.00,
                disinfectant_epa_reg_number="EPA-88494-1",
                implement_batch_count=12,
            ),
            BOARD_ADMIN_HEADERS,
        ),
        201,
    )
    assert_points(log["contact_minutes"], 10.00, "contact_minutes")
    assert_instants_equal(
        log["occupancy_end_at"], "2026-08-01T09:10:00.000Z", "occupancy_end_at"
    )
    assert log["implement_batch_count"] == 12

    rows, meta = _logs_of(api, station["id"])
    assert meta["total_count"] == 1, rows
    assert rows[0]["id"] == log["id"]


def test_a_hundredth_of_a_minute_short_is_rejected(api):
    """9.99 minutes falls below the inclusive minimum and stores nothing.

    PRD 3.4: "A shortfall is rejected with
    ERR_DISINFECTANT_CONTACT_TIME_INSUFFICIENT (HTTP 422)", and PRD 2.7 carries
    ``contact_minutes`` "to two decimal places" -- so an implementation that
    truncates to whole minutes from above would wrongly accept this log.

    Design: Difficulty/boundary_precision_check/implement_disinfection_contact_time_minimum_is_inclusive_at_ten_minutes
    """
    station = _compliant_nail_table(api)

    resp = api.create_sanitation_log(
        sanitation_log_payload(
            workstation_id=station["id"],
            log_type="IMPLEMENT_DISINFECTION",
            performed_at="2026-08-01T11:00:00.000Z",
            contact_minutes=9.99,
            disinfectant_epa_reg_number="EPA-88494-1",
            implement_batch_count=12,
        ),
        BOARD_ADMIN_HEADERS,
    )
    validate_error(resp, ApiErrorId.ERR_DISINFECTANT_CONTACT_TIME_INSUFFICIENT, 422)

    rows, meta = _logs_of(api, station["id"])
    assert meta["total_count"] == 0, rows
