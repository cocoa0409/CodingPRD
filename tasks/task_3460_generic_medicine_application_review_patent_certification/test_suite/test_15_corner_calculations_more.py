"""Queue B / calculations: due-date timeliness, cancelled filtering, late notice."""
from test_helpers import (
    api_client, validate_success, validate_error, ApiErrorId, TEST_USERS,
    set_clock, make_applicant, make_reference_product, make_application,
    add_be_study, make_facility, schedule_inspection, record_outcome,
    submit_application, list_cycles, get_application, add_amendment,
    setup_submitted, send_notice, list_awards, make_applicant_headers,
)

REVIEWER = TEST_USERS["regulatory_reviewer_headers"]


def test_deficiency_response_on_due_date_is_timely_then_second_cycle_lapses():
    """PRD section 3.5: "it must arrive on or before
    `deficiency_response_due_date` — the due date itself is timely" and "A
    deficiency letter issued against a cycle that already stands in
    `AMENDMENT_RECEIVED` starts the next round: the current cycle closes —
    status `CLOSED` with `closed_reason` `SUPERSEDED` — and a fresh cycle
    opens already in `CRL_ISSUED`", whose own unmet clock lapses the
    application.

    Design: Corner/calculations/deficiency_response_on_due_date_is_timely_then_second_cycle_lapses
    """
    ctx = setup_submitted()
    app_id, ac_id = ctx["app"]["id"], ctx["applicant"]["id"]
    cyc1 = list_cycles(app_id)[0]["id"]

    set_clock("2026-11-01T00:00:00Z")
    issued = validate_success(api_client.issue_deficiency(
        cyc1, {"deficiency_summary": "first round comments"}, REVIEWER), 201)
    assert issued["deficiency_response_due_date"] == "2027-11-01"

    set_clock("2027-11-01T00:00:00Z")
    add_amendment(app_id, ac_id, classification="MINOR",
                  notes="response filed on the due date")
    cycle = list_cycles(app_id)[0]
    assert cycle["status"] == "AMENDMENT_RECEIVED", "the due date itself is timely"
    assert cycle["deficiency_response_received_date"] == "2027-11-01"

    set_clock("2027-12-01T00:00:00Z")
    validate_success(api_client.issue_deficiency(
        cyc1, {"deficiency_summary": "second round comments"}, REVIEWER), 201)
    cycles = list_cycles(app_id)
    assert cycles[0]["status"] == "CLOSED" and cycles[0]["closed_reason"] == "SUPERSEDED"
    assert cycles[1]["cycle_number"] == 2 and cycles[1]["status"] == "CRL_ISSUED"
    assert cycles[1]["deficiency_response_due_date"] == "2028-12-01"

    set_clock("2028-12-02T00:00:00Z")
    assert get_application(app_id)["status"] == "LAPSED", (
        "cycle 2's unanswered clock lapses the application")


def test_cancelled_inspections_excluded_from_overlap_and_clearance_inputs():
    """PRD section 3.6: "A `CANCELLED` inspection is inert: it participates
    neither in clearance evaluation nor in overlap blocking."

    Design: Corner/calculations/cancelled_inspections_excluded_from_overlap_and_clearance_inputs
    """
    applicant = make_applicant(legal_name="Cancel Filter Co")
    rld = make_reference_product(brand_name="Filterex")
    app = make_application(rld["id"], applicant["id"])
    add_be_study(app["id"], applicant["id"])
    facility = make_facility(applicant["id"], facility_name="CF Plant")
    insp1 = schedule_inspection(facility["id"], app["id"],
                                scheduled_start_date="2026-09-10",
                                scheduled_end_date="2026-09-12")
    record_outcome(insp1["id"], "CANCELLED")
    submit_application(app["id"], applicant["id"])

    reused = api_client.create_inspection({
        "facility_id": facility["id"], "application_id": app["id"],
        "scheduled_start_date": "2026-09-10", "scheduled_end_date": "2026-09-12"},
        REVIEWER)
    validate_success(reused, 201)

    resp = api_client.approval_decision(app["id"], {"decision": "APPROVE"}, REVIEWER)
    validate_error(resp, ApiErrorId.ERR_FACILITY_CLEARANCE_FAILED)
    assert resp.status_code == 422, (
        "a CANCELLED pass and a merely SCHEDULED inspection clear nothing")


def test_late_p4_notice_is_recorded_but_forfeits_exclusivity():
    """PRD section 3.4: "`is_timely` is true when the notice date falls within
    20 calendar days of the application's `received_date`, the twentieth day
    itself counting as timely. A late notice is still recorded, but recording
    it forfeits the applicant's `ELIGIBLE` exclusivity award with reason
    `NOTICE_LATE`."

    Design: Corner/calculations/late_p4_notice_is_recorded_but_forfeits_exclusivity
    """
    ctx = setup_submitted(patent_expiry="2030-01-01",
                          cert_type="PARAGRAPH_IV_CHALLENGE")
    app_id, ac_id = ctx["app"]["id"], ctx["applicant"]["id"]
    award_id = list_awards(application_id=app_id)[0]["id"]

    set_clock("2026-09-22T00:00:00Z")
    notice = validate_success(api_client.create_notice(
        ctx["cert"]["id"], make_applicant_headers(ac_id)), 201)
    assert notice["notice_date"] == "2026-09-22"
    assert notice["is_timely"] is False, "day 21 after receipt exceeds the 20-day window"

    award = validate_success(api_client.get_exclusivity_award(award_id, REVIEWER), 200)
    assert award["status"] == "FORFEITED"
    assert award["forfeiture_reason"] == "NOTICE_LATE", (
        "lateness is a forfeiture event, not a request error")
