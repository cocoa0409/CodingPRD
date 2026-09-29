"""State programs, applications, outreach and quarterly reporting
(PRD 3.10, 3.11, 3.12)."""

from flask import Blueprint, g

import calc
from errors import ApiError
from envelope import list_response, object_response
from guard import (
    authorize, check_shape, filter_rows, invalid_transition, need_application,
    need_event, need_program, need_report, need_representative, need_veteran,
    page_of, run_checks,
)
from store import bump, db, dt, new_row, now_date, now_instant, ordered, \
    parse_date, parse_instant
from views import view, view_all

bp = Blueprint("state", __name__, url_prefix="/cvso")

READ_PROGRAMS = ("SystemAdmin", "CountyOfficer", "StateAuditor", "IntakeClerk")
FILE_APPLICATION = ("IntakeClerk", "CountyOfficer")
READ_APPLICATIONS = ("IntakeClerk", "CountyOfficer", "StateAuditor",
                     "SystemAdmin", "VeteranClient")
PLAN_OUTREACH = ("CountyOfficer", "SystemAdmin")
READ_OUTREACH = ("CountyOfficer", "StateAuditor", "SystemAdmin", "IntakeClerk")
READ_REPORTS = ("CountyOfficer", "StateAuditor", "SystemAdmin")

PROGRAM_INPUTS = ("program_name", "annual_pool_cents", "min_rating_pct",
                  "requires_wartime", "max_award_cents")


# --------------------------------------------------------------------------
# state programs
# --------------------------------------------------------------------------

def _duplicate_code(code, exclude_id=None):
    for row in db.state_programs.values():
        if row["id"] == exclude_id:
            continue
        if row["program_code"] == code:
            return True
    return False


@bp.post("/state-programs")
def create_program():
    authorize(("SystemAdmin",))
    body = check_shape({
        "required": ["program_code", "program_name", "program_type",
                     "fiscal_year", "annual_pool_cents", "min_rating_pct",
                     "max_award_cents"],
        "optional": ["requires_wartime"],
    })

    def unique_code():
        if _duplicate_code(body["program_code"]):
            raise ApiError("ERR_DUPLICATE_PROGRAM_CODE",
                           "program_code is already configured")

    run_checks([(71, unique_code)])
    row = new_row()
    row["_kind"] = "state_program"
    row["program_code"] = body["program_code"]
    row["program_name"] = body["program_name"]
    row["program_type"] = body["program_type"]
    row["fiscal_year"] = body["fiscal_year"]
    row["annual_pool_cents"] = body["annual_pool_cents"]
    row["allocated_cents"] = 0
    row["min_rating_pct"] = body["min_rating_pct"]
    row["requires_wartime"] = bool(body.get("requires_wartime", False))
    row["max_award_cents"] = body["max_award_cents"]
    db.state_programs[row["id"]] = row
    return object_response(view(row), 201)


@bp.get("/state-programs")
def list_programs():
    authorize(READ_PROGRAMS)
    run_checks()
    rows = filter_rows(ordered(db.state_programs.values()),
                       {"program_type": "program_type",
                        "fiscal_year": "fiscal_year"})
    window, page = page_of(rows)
    return list_response(view_all(window), page)


@bp.get("/state-programs/<row_id>")
def read_program(row_id):
    authorize(READ_PROGRAMS)
    row = need_program(row_id)
    run_checks()
    return object_response(view(row))


@bp.patch("/state-programs/<row_id>")
def patch_program(row_id):
    authorize(("SystemAdmin",))
    body = check_shape({"optional": list(PROGRAM_INPUTS)})
    row = need_program(row_id)
    run_checks()
    for field in PROGRAM_INPUTS:
        if field in body:
            row[field] = body[field]
    bump(row)
    return object_response(view(row))


# --------------------------------------------------------------------------
# state benefit applications
# --------------------------------------------------------------------------

ELIGIBLE_INTAKE = {
    "PROPERTY_TAX_EXEMPTION": ("SCREENED", "ACTIVE"),
    "TUITION_WAIVER": ("SCREENED", "ACTIVE"),
    "BURIAL_BENEFIT": ("DECEASED",),
}


@bp.post("/state-benefit-applications")
def file_application():
    authorize(FILE_APPLICATION)
    body = check_shape({
        "required": ["veteran_id", "program_id", "fiscal_year",
                     "expected_program_version"],
        "optional": ["assessed_property_value_cents",
                     "tuition_credits_requested"],
        "occ": "expected_program_version",
    })
    veteran = need_veteran(body["veteran_id"])
    program = need_program(body["program_id"])

    def fresh():
        if program["version"] != body["expected_program_version"]:
            raise ApiError("ERR_STALE_PROGRAM_VERSION",
                           "expected_program_version does not match the"
                           " program's current version")

    def case_state():
        if veteran["intake_status"] not in ELIGIBLE_INTAKE[
                program["program_type"]]:
            raise ApiError("ERR_VETERAN_STATUS_INELIGIBLE",
                           "the veteran's case state does not admit a %s"
                           " application" % (program["program_type"],))

    def same_year():
        if body["fiscal_year"] != program["fiscal_year"]:
            raise ApiError("ERR_FISCAL_YEAR_MISMATCH",
                           "fiscal_year does not match the program")

    def money_input():
        assessed = body.get("assessed_property_value_cents")
        credits = body.get("tuition_credits_requested")
        program_type = program["program_type"]
        if program_type == "PROPERTY_TAX_EXEMPTION":
            ok = (assessed is not None and assessed > 0 and credits is None)
        elif program_type == "TUITION_WAIVER":
            ok = (credits is not None and credits > 0 and assessed is None)
        else:
            ok = (assessed is None and credits is None)
        if not ok:
            raise ApiError("ERR_PROGRAM_INPUT_MISMATCH",
                           "the money-bearing input does not match %s"
                           % (program_type,))

    def unique_application():
        for other in db.state_benefit_applications.values():
            if other["veteran_id"] != body["veteran_id"]:
                continue
            if other["program_id"] != body["program_id"]:
                continue
            if other["fiscal_year"] != body["fiscal_year"]:
                continue
            if other["determination_status"] in ("SUBMITTED", "APPROVED"):
                raise ApiError("ERR_DUPLICATE_BENEFIT_APPLICATION",
                               "an open application already exists")

    run_checks([(46, fresh), (49, case_state), (61, same_year),
                (63, money_input), (73, unique_application)])

    row = new_row()
    row["_kind"] = "state_benefit_application"
    row["veteran_id"] = body["veteran_id"]
    row["program_id"] = body["program_id"]
    row["fiscal_year"] = body["fiscal_year"]
    row["assessed_property_value_cents"] = \
        body.get("assessed_property_value_cents")
    row["tuition_credits_requested"] = body.get("tuition_credits_requested")
    row["determination_status"] = "SUBMITTED"
    row["disbursement_status"] = "NOT_APPLICABLE"
    row["gross_award_cents"] = 0
    row["admin_fee_cents"] = 0
    row["benefit_amount_cents"] = 0
    row["rating_at_approval_pct"] = 0
    row["determination_reason"] = None
    row["issued_on"] = None
    db.state_benefit_applications[row["id"]] = row
    return object_response(view(row), 201)


@bp.get("/state-benefit-applications")
def list_applications():
    authorize(READ_APPLICATIONS)
    run_checks()
    rows = filter_rows(ordered(db.state_benefit_applications.values()), {
        "veteran_id": "veteran_id",
        "program_id": "program_id",
        "fiscal_year": "fiscal_year",
        "determination_status": "determination_status",
        "disbursement_status": "disbursement_status",
    })
    window, page = page_of(rows)
    return list_response(view_all(window), page)


@bp.get("/state-benefit-applications/<row_id>")
def read_application(row_id):
    authorize(READ_APPLICATIONS)
    row = need_application(row_id)
    run_checks()
    return object_response(view(row))


@bp.post("/state-benefit-applications/<row_id>/determination")
def adjudicate_application(row_id):
    authorize(("StateAuditor",))
    body = check_shape({
        "actions": ("APPROVE", "DENY"),
        "optional": ["reason"],
        "action_required": {"DENY": ("reason",)},
    })
    application = need_application(row_id)
    action = body["action"]
    program = db.state_programs.get(application["program_id"])
    veteran = db.veterans.get(application["veteran_id"])
    rating = 0 if veteran is None else veteran["combined_rating_pct"]
    figures = {}

    def from_state():
        if application["determination_status"] != "SUBMITTED":
            invalid_transition("%s is not available from %s"
                               % (action, application["determination_status"]))

    def rating_floor():
        if action != "APPROVE":
            return
        if program is not None and rating < program["min_rating_pct"]:
            raise ApiError("ERR_PROGRAM_MIN_RATING_NOT_MET",
                           "the veteran's combined rating is below the"
                           " program floor")

    def wartime():
        if action != "APPROVE" or program is None:
            return
        if program["requires_wartime"]:
            days = 0 if veteran is None else veteran["wartime_service_days"]
            if days < calc.WARTIME_MIN_DAYS:
                raise ApiError("ERR_PROGRAM_WARTIME_REQUIRED",
                               "the program requires qualifying wartime"
                               " service")

    def pool():
        if action != "APPROVE" or program is None:
            return
        gross, fee, net = calc.award_breakdown(program, application, rating)
        figures["gross"] = gross
        figures["fee"] = fee
        figures["net"] = net
        if program["allocated_cents"] + net > program["annual_pool_cents"]:
            raise ApiError("ERR_PROGRAM_POOL_EXHAUSTED",
                           "the approval would overcommit the annual pool")

    run_checks([(40, from_state), (74, rating_floor), (75, wartime),
                (76, pool)])

    if action == "APPROVE":
        application["gross_award_cents"] = figures["gross"]
        application["admin_fee_cents"] = figures["fee"]
        application["benefit_amount_cents"] = figures["net"]
        application["rating_at_approval_pct"] = rating
        application["determination_status"] = "APPROVED"
        application["disbursement_status"] = "PENDING"
        bump(application)
        program["allocated_cents"] = program["allocated_cents"] + figures["net"]
        bump(program)
    else:
        application["determination_status"] = "DENIED"
        application["determination_reason"] = body["reason"]
        bump(application)
    return object_response(view(application))


@bp.post("/state-benefit-applications/<row_id>/disbursement")
def move_disbursement(row_id):
    authorize(("SystemAdmin",))

    def extra(body):
        if body.get("action") == "ISSUE":
            if parse_date(body["issued_on"]) > now_date():
                raise ApiError("ERR_VALIDATION",
                               "issued_on may not be later than the"
                               " logical-clock date")

    body = check_shape({
        "actions": ("ISSUE", "CLAW_BACK"),
        "optional": ["issued_on", "reason"],
        "action_required": {"ISSUE": ("issued_on",), "CLAW_BACK": ("reason",)},
        "extra": extra,
    })
    application = need_application(row_id)
    action = body["action"]
    program = db.state_programs.get(application["program_id"])

    def from_state():
        if action == "ISSUE":
            if application["disbursement_status"] != "PENDING" \
                    or application["determination_status"] != "APPROVED":
                invalid_transition("issuing is not available from %s/%s"
                                   % (application["determination_status"],
                                      application["disbursement_status"]))
        elif application["disbursement_status"] not in ("PENDING", "ISSUED"):
            invalid_transition("a claw-back is not available from %s"
                               % (application["disbursement_status"],))

    run_checks([(40, from_state)])

    if action == "ISSUE":
        application["disbursement_status"] = "ISSUED"
        application["issued_on"] = body["issued_on"]
        bump(application)
    else:
        application["disbursement_status"] = "CLAWED_BACK"
        bump(application)
        if program is not None:
            program["allocated_cents"] = \
                program["allocated_cents"] - application["benefit_amount_cents"]
            bump(program)
    return object_response(view(application))


# --------------------------------------------------------------------------
# outreach events
# --------------------------------------------------------------------------

@bp.post("/outreach-events")
def plan_event():
    authorize(PLAN_OUTREACH)
    body = check_shape({
        "required": ["assigned_representative_id", "event_type",
                     "location_name", "starts_at", "ends_at"],
        "optional": ["underserved_flag"],
        "interval": True,
    })
    representative = need_representative(body["assigned_representative_id"])
    starts = parse_instant(body["starts_at"])
    ends = parse_instant(body["ends_at"])

    def calendar():
        if calc.travel_conflict(representative["id"], starts, ends):
            raise ApiError("ERR_REPRESENTATIVE_TRAVEL_CONFLICT",
                           "the representative's travel calendar is occupied")

    run_checks([(67, calendar)])
    row = new_row()
    row["_kind"] = "outreach_event"
    row["assigned_representative_id"] = representative["id"]
    row["event_type"] = body["event_type"]
    row["location_name"] = body["location_name"]
    row["starts_at"] = body["starts_at"]
    row["ends_at"] = body["ends_at"]
    row["underserved_flag"] = bool(body.get("underserved_flag", False))
    row["status"] = "PLANNED"
    row["veterans_contacted"] = 0
    row["veterans_enrolled"] = 0
    row["cancellation_reason"] = None
    db.outreach_events[row["id"]] = row
    calc.refresh_caseload(representative)
    return object_response(view(row), 201)


@bp.get("/outreach-events")
def list_events():
    authorize(READ_OUTREACH)
    run_checks()
    rows = filter_rows(ordered(db.outreach_events.values()), {
        "assigned_representative_id": "assigned_representative_id",
        "status": "status",
        "event_type": "event_type",
        "underserved_flag": "underserved_flag",
    })
    window, page = page_of(rows)
    return list_response(view_all(window), page)


@bp.get("/outreach-events/<row_id>")
def read_event(row_id):
    authorize(READ_OUTREACH)
    row = need_event(row_id)
    run_checks()
    return object_response(view(row))


@bp.post("/outreach-events/<row_id>/status")
def drive_event(row_id):
    authorize(("CountyOfficer",))
    body = check_shape({
        "actions": ("HOLD", "CANCEL"),
        "optional": ["veterans_contacted", "veterans_enrolled", "reason"],
        "action_required": {
            "HOLD": ("veterans_contacted", "veterans_enrolled"),
            "CANCEL": ("reason",),
        },
        "enrolled": True,
    })
    event = need_event(row_id)
    action = body["action"]

    def from_state():
        if event["status"] != "PLANNED":
            invalid_transition("%s is not available from %s"
                               % (action, event["status"]))
        if action == "HOLD" and db.clock < dt(event["starts_at"]):
            invalid_transition("the event has not started yet")

    def calendar():
        if action != "HOLD":
            return
        if calc.travel_conflict(event["assigned_representative_id"],
                                dt(event["starts_at"]), dt(event["ends_at"]),
                                exclude_id=event["id"]):
            raise ApiError("ERR_REPRESENTATIVE_TRAVEL_CONFLICT",
                           "the representative's travel calendar is occupied")

    run_checks([(40, from_state), (67, calendar)])
    representative = db.representatives.get(event["assigned_representative_id"])

    if action == "HOLD":
        event["status"] = "HELD"
        event["veterans_contacted"] = body["veterans_contacted"]
        event["veterans_enrolled"] = body["veterans_enrolled"]
    else:
        event["status"] = "CANCELLED"
        event["cancellation_reason"] = body["reason"]
    bump(event)
    calc.refresh_caseload(representative)
    return object_response(view(event))


# --------------------------------------------------------------------------
# quarterly outcome reports
# --------------------------------------------------------------------------

def _apply_figures(report):
    figures = calc.compute_report_figures(report["fiscal_quarter"],
                                          report["weighting_basis"])
    report.update(figures)


@bp.post("/outcome-reports")
def open_report():
    authorize(("CountyOfficer",))
    body = check_shape({
        "required": ["fiscal_quarter"],
        "fiscal_quarter": True,
    })

    def unique_quarter():
        for other in db.outcome_reports.values():
            if other["fiscal_quarter"] == body["fiscal_quarter"]:
                raise ApiError("ERR_DUPLICATE_FISCAL_QUARTER",
                               "a report already covers that quarter")

    run_checks([(72, unique_quarter)])
    row = new_row()
    row["_kind"] = "outcome_report"
    row["fiscal_quarter"] = body["fiscal_quarter"]
    row["status"] = "OPEN"
    row["weighting_basis"] = None
    row["filed_claim_count"] = 0
    row["favorable_claim_count"] = 0
    row["performance_score"] = 0.0
    row["retro_dollars_cents"] = 0
    row["veterans_contacted_total"] = 0
    row["certified_by_representative_id"] = None
    row["submitted_at"] = None
    row["return_reason"] = None
    db.outcome_reports[row["id"]] = row
    return object_response(view(row), 201)


@bp.get("/outcome-reports")
def list_reports():
    authorize(READ_REPORTS)
    run_checks()
    rows = filter_rows(ordered(db.outcome_reports.values()), {
        "status": "status",
        "fiscal_quarter": "fiscal_quarter",
        "weighting_basis": "weighting_basis",
        "certified_by_representative_id": "certified_by_representative_id",
    })
    window, page = page_of(rows)
    return list_response(view_all(window), page)


@bp.get("/outcome-reports/<row_id>")
def read_report(row_id):
    authorize(READ_REPORTS)
    row = need_report(row_id)
    run_checks()
    return object_response(view(row))


@bp.post("/outcome-reports/<row_id>/compute")
def compute_report(row_id):
    authorize(("CountyOfficer",))
    body = check_shape({"required": ["weighting_basis"]})
    report = need_report(row_id)

    def from_state():
        if report["status"] not in ("OPEN", "RETURNED"):
            invalid_transition("a computation is not available from %s"
                               % (report["status"],))

    def closed():
        _, last_day = calc.quarter_window(report["fiscal_quarter"])
        if not now_date() > last_day:
            raise ApiError("ERR_QUARTER_NOT_CLOSED",
                           "the labelled quarter has not closed yet")

    run_checks([(40, from_state), (59, closed)])
    report["weighting_basis"] = body["weighting_basis"]
    _apply_figures(report)
    bump(report)
    return object_response(view(report))


@bp.post("/outcome-reports/<row_id>/submit")
def submit_report(row_id):
    authorize(("CountyOfficer",))
    check_shape({})
    report = need_report(row_id)

    def from_state():
        if report["status"] != "OPEN":
            invalid_transition("submission is not available from %s"
                               % (report["status"],))

    def computed():
        if report["weighting_basis"] is None:
            raise ApiError("ERR_REPORT_NOT_COMPUTED",
                           "the report has never been computed")

    run_checks([(40, from_state), (48, computed)])
    _apply_figures(report)
    report["status"] = "SUBMITTED"
    report["submitted_at"] = now_instant()
    report["certified_by_representative_id"] = g.user_id
    bump(report)
    return object_response(view(report))


@bp.post("/outcome-reports/<row_id>/review")
def review_report(row_id):
    authorize(("StateAuditor",))
    body = check_shape({
        "actions": ("ACCEPT", "RETURN"),
        "optional": ["reason"],
        "action_required": {"RETURN": ("reason",)},
    })
    report = need_report(row_id)
    action = body["action"]

    def from_state():
        if report["status"] != "SUBMITTED":
            invalid_transition("%s is not available from %s"
                               % (action, report["status"]))

    run_checks([(40, from_state)])
    if action == "ACCEPT":
        report["status"] = "ACCEPTED"
    else:
        report["status"] = "RETURNED"
        report["return_reason"] = body["reason"]
    bump(report)
    return object_response(view(report))


@bp.post("/outcome-reports/<row_id>/reopen")
def reopen_report(row_id):
    authorize(("SystemAdmin",))
    check_shape({})
    report = need_report(row_id)

    def from_state():
        if report["status"] != "RETURNED":
            invalid_transition("reopening is not available from %s"
                               % (report["status"],))

    run_checks([(40, from_state)])
    report["status"] = "OPEN"
    report["certified_by_representative_id"] = None
    report["submitted_at"] = None
    bump(report)
    return object_response(view(report))
