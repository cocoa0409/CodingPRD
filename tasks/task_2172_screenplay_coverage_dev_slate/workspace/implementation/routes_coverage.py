"""Reader bench, coverage assignment, coverage reports and the tracking board."""

from decimal import Decimal

from flask import Blueprint

import calc
from core import (
    Field, authenticate, collection_rows, created, db, fail, filter_eq, fmt_dt,
    json_body, lookup, new_row, now, now_str, ok, ok_list, paginate, pagination,
    parse_dt, parse_fields, qp, touch,
)

bp = Blueprint("coverage", __name__)

ASSIGNMENT_READ_ROLES = ("SlateAdmin", "StoryEditor", "Reader", "DevelopmentExec")
BOARD_ROLES = ("SlateAdmin", "StoryEditor", "DevelopmentExec", "BusinessAffairs",
               "CommitteeMember")


# --------------------------------------------------------------------------
# Readers
# --------------------------------------------------------------------------
@bp.post("/readers")
def create_reader():
    authenticate(("SlateAdmin",))
    body = json_body()
    data = parse_fields(body, [
        Field("display_name", "string", required=True),
        Field("specialty_genre", "enum", required=True, enum=calc.GENRES),
        Field("weekly_capacity", "integer", required=True, lo=1, hi=20),
        Field("employment_type", "enum", required=True, enum=calc.EMPLOYMENT_TYPES),
        Field("status", "enum", default="ACTIVE", enum=calc.READER_STATUSES),
    ])
    row = new_row("readers", {
        "display_name": data["display_name"],
        "specialty_genre": data["specialty_genre"],
        "weekly_capacity": data["weekly_capacity"],
        "employment_type": data["employment_type"],
        "status": data["status"],
        "active_assignment_count": 0,
        "completed_report_count": 0,
        "calibration_bias": Decimal("0.00"),
    })
    return created(row)


@bp.get("/readers/<rid>")
def read_reader(rid):
    authenticate(("SlateAdmin", "StoryEditor", "Reader"))
    return ok(lookup("readers", rid, "ERR_READER_NOT_FOUND"))


@bp.get("/readers")
def list_readers():
    authenticate(("SlateAdmin", "StoryEditor"))
    limit, offset = pagination()
    rows = collection_rows("readers")
    rows = filter_eq(rows, "status", qp("status"))
    rows = filter_eq(rows, "specialty_genre", qp("specialty_genre"))
    rows = filter_eq(rows, "employment_type", qp("employment_type"))
    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.patch("/readers/<rid>")
def patch_reader(rid):
    authenticate(("SlateAdmin",))
    reader = lookup("readers", rid, "ERR_READER_NOT_FOUND")
    body = json_body()
    data = parse_fields(body, [
        Field("status", "enum", enum=calc.READER_STATUSES),
        Field("weekly_capacity", "integer", lo=1, hi=20),
    ])
    if data["status"] is not None:
        reader["status"] = data["status"]
    if data["weekly_capacity"] is not None:
        reader["weekly_capacity"] = data["weekly_capacity"]
    touch(reader)
    return ok(reader)


# --------------------------------------------------------------------------
# Coverage assignment
# --------------------------------------------------------------------------
@bp.post("/submissions/<sid>/assign-reader")
def assign_reader(sid):
    user_id, _role = authenticate(("StoryEditor",))
    submission = lookup("submissions", sid, "ERR_SUBMISSION_NOT_FOUND")
    body = json_body()
    named_reader = None
    if body.get("reader_id") is not None:
        named_reader = lookup("readers", body.get("reader_id"), "ERR_READER_NOT_FOUND")
    data = parse_fields(body, [
        Field("reader_id", "string"),
        Field("window_start", "datetime"),
        Field("window_due", "datetime"),
        Field("excluded_reader_ids", "array", default=[]),
    ])
    if submission["status"] != "INTAKE_CLEARED":
        fail("ERR_INVALID_STATE", "A reader may only be assigned from INTAKE_CLEARED.")

    calc.apply_lazy_expiry(submission)
    forms = calc.release_forms_of(submission["id"])
    if any(f["status"] == "EXPIRED" for f in forms):
        fail("ERR_RELEASE_FORM_EXPIRED", "A release form on this submission has expired.")
    if submission["release_form_required"]:
        if not any(f["status"] in ("EXECUTED", "WAIVED") for f in forms):
            fail("ERR_RELEASE_FORM_REQUIRED", "An executed or waived release form is required.")

    prop = db.properties.get(submission["property_id"])
    if prop is not None and prop["rights_chain_status"] == "DISPUTED":
        fail("ERR_PROPERTY_RIGHTS_DISPUTED", "The property's chain of title is disputed.")

    window_start = (parse_dt(data["window_start"]) if data["window_start"] is not None
                    else now())
    window_due = (parse_dt(data["window_due"]) if data["window_due"] is not None
                  else parse_dt(submission["coverage_due_at"]))
    excluded = set(x for x in (data["excluded_reader_ids"] or []) if isinstance(x, str))

    if named_reader is not None:
        if calc.reader_window_conflict(named_reader["id"], window_start, window_due):
            fail("ERR_READER_WINDOW_CONFLICT", "The reader's coverage window collides.")
        if (named_reader["status"] != "ACTIVE"
                or named_reader["active_assignment_count"] >= named_reader["weekly_capacity"]):
            fail("ERR_READER_AT_CAPACITY", "The named reader is unavailable or at capacity.")
        reader = named_reader
        auto_selected = False
    else:
        reader = calc.select_reader(prop, submission, window_start, window_due, excluded)
        if reader is None:
            fail("ERR_NO_ELIGIBLE_READER", "No eligible reader is available.")
        auto_selected = True

    assignment = new_row("assignments", {
        "submission_id": submission["id"],
        "reader_id": reader["id"],
        "assigned_by_user_id": user_id,
        "window_start": fmt_dt(window_start),
        "window_due": fmt_dt(window_due),
        "status": "ASSIGNED",
        "recall_reason": None,
        "auto_selected": auto_selected,
    })
    new_row("reports", {
        "assignment_id": assignment["id"],
        "logline_score": None,
        "structure_score": None,
        "character_score": None,
        "dialogue_score": None,
        "marketability_score": None,
        "recommendation": None,
        "synopsis_word_count": 0,
        "comparable_titles": [],
        "composite_score": None,
        "normalized_score": None,
        "revision_round_count": 0,
        "revision_note": None,
        "status": "DRAFT",
        "approved_by_user_id": None,
        "rejection_reason": None,
    })
    calc.recompute_reader_counters(reader)
    touch(reader)
    submission["status"] = "READER_ASSIGNED"
    touch(submission)
    return created(assignment)


@bp.get("/coverage-assignments/<aid>")
def read_assignment(aid):
    authenticate(ASSIGNMENT_READ_ROLES)
    return ok(lookup("assignments", aid, "ERR_ASSIGNMENT_NOT_FOUND"))


@bp.get("/coverage-assignments")
def list_assignments():
    authenticate(ASSIGNMENT_READ_ROLES)
    limit, offset = pagination()
    rows = collection_rows("assignments")
    rows = filter_eq(rows, "submission_id", qp("submission_id"))
    rows = filter_eq(rows, "reader_id", qp("reader_id"))
    rows = filter_eq(rows, "status", qp("status"))
    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.post("/coverage-assignments/<aid>/start")
def start_assignment(aid):
    user_id, _role = authenticate(("Reader",))
    assignment = lookup("assignments", aid, "ERR_ASSIGNMENT_NOT_FOUND")
    if assignment["reader_id"] != user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "This assignment belongs to another reader.")
    if assignment["status"] != "ASSIGNED":
        fail("ERR_INVALID_STATE", "Only an ASSIGNED assignment may be started.")
    assignment["status"] = "IN_PROGRESS"
    touch(assignment)
    return ok(assignment)


@bp.post("/coverage-assignments/<aid>/recall")
def recall_assignment(aid):
    authenticate(("StoryEditor",))
    assignment = lookup("assignments", aid, "ERR_ASSIGNMENT_NOT_FOUND")
    body = json_body()
    data = parse_fields(body, [Field("reason", "string", required=True)])
    if assignment["status"] in ("COMPLETED", "RECALLED"):
        fail("ERR_TERMINAL_STATE", "This assignment has already reached a terminal state.")
    if assignment["status"] not in ("ASSIGNED", "IN_PROGRESS"):
        fail("ERR_INVALID_STATE", "Only an ASSIGNED or IN_PROGRESS assignment may be recalled.")
    assignment["status"] = "RECALLED"
    assignment["recall_reason"] = data["reason"]
    touch(assignment)
    reader = db.readers.get(assignment["reader_id"])
    if reader is not None:
        calc.recompute_reader_counters(reader)
        touch(reader)
    report = calc.report_of_assignment(assignment["id"])
    if report is not None and report["status"] in ("DRAFT", "REVISION_REQUESTED"):
        report["status"] = "REJECTED"
        touch(report)
    submission = db.submissions.get(assignment["submission_id"])
    if submission is not None:
        submission["status"] = "INTAKE_CLEARED"
        touch(submission)
    return ok(assignment)


# --------------------------------------------------------------------------
# Coverage reports
# --------------------------------------------------------------------------
def _owning_reader_id(report):
    assignment = db.assignments.get(report["assignment_id"])
    return assignment["reader_id"] if assignment else None


@bp.get("/coverage-reports/<rid>")
def read_report(rid):
    authenticate(ASSIGNMENT_READ_ROLES)
    return ok(lookup("reports", rid, "ERR_REPORT_NOT_FOUND"))


@bp.get("/coverage-reports")
def list_reports():
    authenticate(ASSIGNMENT_READ_ROLES)
    limit, offset = pagination()
    rows = collection_rows("reports")
    rows = filter_eq(rows, "assignment_id", qp("assignment_id"))
    rows = filter_eq(rows, "status", qp("status"))
    rows = filter_eq(rows, "recommendation", qp("recommendation"))
    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.patch("/coverage-reports/<rid>")
def patch_report(rid):
    user_id, _role = authenticate(("Reader",))
    report = lookup("reports", rid, "ERR_REPORT_NOT_FOUND")
    body = json_body()
    data = parse_fields(body, [
        Field("logline_score", "integer", lo=1, hi=10),
        Field("structure_score", "integer", lo=1, hi=10),
        Field("character_score", "integer", lo=1, hi=10),
        Field("dialogue_score", "integer", lo=1, hi=10),
        Field("marketability_score", "integer", lo=1, hi=10),
        Field("recommendation", "enum", enum=calc.RECOMMENDATIONS),
        Field("synopsis_word_count", "integer"),
        Field("comparable_titles", "array"),
    ])
    if _owning_reader_id(report) != user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "This report belongs to another reader's assignment.")
    for field in ("logline_score", "structure_score", "character_score", "dialogue_score",
                  "marketability_score", "recommendation", "synopsis_word_count",
                  "comparable_titles"):
        if data[field] is not None:
            report[field] = data[field]
    touch(report)
    return ok(report)


@bp.post("/coverage-reports/<rid>/submit")
def submit_report(rid):
    user_id, _role = authenticate(("Reader",))
    report = lookup("reports", rid, "ERR_REPORT_NOT_FOUND")
    assignment = db.assignments.get(report["assignment_id"])
    if _owning_reader_id(report) != user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "This report belongs to another reader's assignment.")
    if report["status"] not in ("DRAFT", "REVISION_REQUESTED"):
        fail("ERR_INVALID_STATE", "Only a DRAFT or REVISION_REQUESTED report may be submitted.")
    if assignment is None or assignment["status"] not in ("ASSIGNED", "IN_PROGRESS"):
        fail("ERR_INVALID_STATE", "The parent assignment is not open for submission.")
    for field in ("logline_score", "structure_score", "character_score", "dialogue_score",
                  "marketability_score"):
        value = report[field]
        if not isinstance(value, int) or isinstance(value, bool) or value < 1 or value > 10:
            fail("ERR_COVERAGE_INCOMPLETE", "The coverage standard is not met.")
    if report["recommendation"] is None:
        fail("ERR_COVERAGE_INCOMPLETE", "The coverage standard is not met.")
    if (report["synopsis_word_count"] or 0) < calc.COVERAGE_MIN_SYNOPSIS_WORDS:
        fail("ERR_COVERAGE_INCOMPLETE", "The coverage standard is not met.")

    reader = db.readers.get(assignment["reader_id"])
    composite, normalized = calc.coverage_score_pair(report, reader)
    report["composite_score"] = composite
    report["normalized_score"] = normalized
    report["status"] = "SUBMITTED"
    touch(report)
    assignment["status"] = "SUBMITTED"
    touch(assignment)
    submission = db.submissions.get(assignment["submission_id"])
    if submission is not None:
        submission["status"] = "COVERAGE_IN_REVIEW"
        touch(submission)
    return ok(report)


@bp.post("/coverage-reports/<rid>/request-revision")
def request_revision(rid):
    authenticate(("StoryEditor",))
    report = lookup("reports", rid, "ERR_REPORT_NOT_FOUND")
    body = json_body()
    data = parse_fields(body, [Field("revision_note", "string", required=True)])
    if report["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE", "Only a SUBMITTED report may be returned for revision.")
    if report["revision_round_count"] >= calc.COVERAGE_MAX_REVISION_ROUNDS:
        fail("ERR_REVISION_LIMIT_EXCEEDED", "The revision allowance is exhausted.")
    report["status"] = "REVISION_REQUESTED"
    report["revision_round_count"] += 1
    report["revision_note"] = data["revision_note"]
    touch(report)
    assignment = db.assignments.get(report["assignment_id"])
    if assignment is not None:
        assignment["status"] = "IN_PROGRESS"
        touch(assignment)
        submission = db.submissions.get(assignment["submission_id"])
        if submission is not None:
            submission["status"] = "READER_ASSIGNED"
            touch(submission)
    return ok(report)


@bp.post("/coverage-reports/<rid>/approve")
def approve_report(rid):
    user_id, _role = authenticate(("StoryEditor",))
    report = lookup("reports", rid, "ERR_REPORT_NOT_FOUND")
    assignment = db.assignments.get(report["assignment_id"])
    if report["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE", "Only a SUBMITTED report may be approved.")
    if assignment is not None and assignment["assigned_by_user_id"] == user_id:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The approving editor may not be the editor who made the assignment.")

    # link one
    report["status"] = "APPROVED"
    report["approved_by_user_id"] = user_id
    touch(report)
    # link two
    assignment["status"] = "COMPLETED"
    touch(assignment)
    # link three
    reader = db.readers.get(assignment["reader_id"])
    if reader is not None:
        calc.recompute_reader_counters(reader)
        calc.recompute_calibration_bias(reader)
        touch(reader)
    # link four
    submission = db.submissions.get(assignment["submission_id"])
    prop = db.properties.get(submission["property_id"]) if submission else None
    if submission is not None:
        submission["decision"] = report["recommendation"]
        if report["recommendation"] == "PASS":
            submission["status"] = "PASSED"
            touch(submission)
        else:
            submission["status"] = "TRACKED"
            touch(submission)
            # link five
            heat, tier, competing = calc.tracking_heat_score(report, prop, submission)
            new_row("board_entries", {
                "property_id": prop["id"],
                "report_id": report["id"],
                "board_tier": tier,
                "heat_score": heat,
                "competing_submission_count": competing,
                "entered_at": now_str(),
                "status": "LIVE",
            })
            if calc.tier_rank(tier) > calc.tier_rank(prop["tracking_tier"]):
                prop["tracking_tier"] = tier
                touch(prop)
    return ok(report)


@bp.post("/coverage-reports/<rid>/reject")
def reject_report(rid):
    authenticate(("StoryEditor",))
    report = lookup("reports", rid, "ERR_REPORT_NOT_FOUND")
    body = json_body()
    data = parse_fields(body, [Field("reason", "string", required=True)])
    if report["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE", "Only a SUBMITTED report may be rejected.")
    if report["revision_round_count"] < calc.COVERAGE_MAX_REVISION_ROUNDS:
        fail("ERR_INVALID_STATE", "The revision allowance has not been exhausted.")
    report["status"] = "REJECTED"
    report["rejection_reason"] = data["reason"]
    touch(report)
    assignment = db.assignments.get(report["assignment_id"])
    if assignment is not None:
        assignment["status"] = "RECALLED"
        touch(assignment)
        reader = db.readers.get(assignment["reader_id"])
        if reader is not None:
            calc.recompute_reader_counters(reader)
            touch(reader)
        submission = db.submissions.get(assignment["submission_id"])
        if submission is not None:
            submission["status"] = "INTAKE_CLEARED"
            touch(submission)
    return ok(report)


# --------------------------------------------------------------------------
# Tracking board
# --------------------------------------------------------------------------
@bp.get("/tracking-board-entries/<bid>")
def read_board_entry(bid):
    authenticate(BOARD_ROLES)
    return ok(lookup("board_entries", bid, "ERR_BOARD_ENTRY_NOT_FOUND"))


@bp.get("/tracking-board-entries")
def list_board_entries():
    authenticate(BOARD_ROLES)
    limit, offset = pagination()
    rows = collection_rows("board_entries")
    rows = filter_eq(rows, "property_id", qp("property_id"))
    rows = filter_eq(rows, "report_id", qp("report_id"))
    rows = filter_eq(rows, "board_tier", qp("board_tier"))
    rows = filter_eq(rows, "status", qp("status"))
    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit, offset, total)
