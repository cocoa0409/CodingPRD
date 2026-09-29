"""Examination sites, bookings and appeal counselling (PRD 3.7, 3.9)."""

from flask import Blueprint, g

import calc
from errors import ApiError
from envelope import list_response, object_response
from guard import (
    authorize, check_shape, filter_rows, invalid_transition, need_appointment,
    need_claim, need_review, need_site, page_of, run_checks,
)
from store import bump, db, dt, fmt_date, new_row, now_date, ordered, \
    parse_date, parse_instant
from views import view, view_all

bp = Blueprint("exams", __name__, url_prefix="/cvso")

READ_SITES = ("SystemAdmin", "CountyOfficer", "StateAuditor")
READ_APPOINTMENTS = ("CountyOfficer", "StateAuditor", "SystemAdmin")
READ_REVIEWS = ("CountyOfficer", "StateAuditor", "SystemAdmin", "VeteranClient")


# --------------------------------------------------------------------------
# examination sites
# --------------------------------------------------------------------------

@bp.post("/exam-sites")
def create_site():
    authorize(("SystemAdmin",))
    body = check_shape({
        "required": ["name", "county_code"],
        "optional": ["concurrent_capacity", "buffer_minutes"],
    })
    run_checks()
    row = new_row()
    row["_kind"] = "exam_site"
    row["name"] = body["name"]
    row["county_code"] = body["county_code"]
    row["concurrent_capacity"] = body.get(
        "concurrent_capacity", calc.DEFAULT_CONCURRENT_CAPACITY)
    row["buffer_minutes"] = body.get("buffer_minutes",
                                     calc.DEFAULT_BUFFER_MINUTES)
    row["booked_slot_count"] = 0
    db.exam_sites[row["id"]] = row
    return object_response(view(row), 201)


@bp.get("/exam-sites")
def list_sites():
    authorize(READ_SITES)
    run_checks()
    rows = filter_rows(ordered(db.exam_sites.values()),
                       {"county_code": "county_code"})
    window, page = page_of(rows)
    return list_response(view_all(window), page)


@bp.get("/exam-sites/<row_id>")
def read_site(row_id):
    authorize(READ_SITES)
    row = need_site(row_id)
    run_checks()
    return object_response(view(row))


@bp.patch("/exam-sites/<row_id>")
def patch_site(row_id):
    authorize(("SystemAdmin",))
    body = check_shape({
        "optional": ["name", "county_code", "concurrent_capacity",
                     "buffer_minutes"],
    })
    row = need_site(row_id)
    run_checks()
    for field in ("name", "county_code", "concurrent_capacity",
                  "buffer_minutes"):
        if field in body:
            row[field] = body[field]
    bump(row)
    return object_response(view(row))


# --------------------------------------------------------------------------
# examination appointments
# --------------------------------------------------------------------------

@bp.post("/exam-appointments")
def book_appointment():
    authorize(("CountyOfficer",))
    body = check_shape({
        "required": ["claim_id", "exam_site_id", "starts_at", "ends_at"],
        "interval": True,
    })
    need_claim(body["claim_id"])
    site = need_site(body["exam_site_id"])
    starts = parse_instant(body["starts_at"])
    ends = parse_instant(body["ends_at"])

    def not_in_past():
        if starts < db.clock:
            raise ApiError("ERR_APPOINTMENT_IN_PAST",
                           "starts_at precedes the logical-clock instant")

    def capacity():
        if calc.site_overlap_count(site, starts, ends) \
                >= site["concurrent_capacity"]:
            raise ApiError("ERR_EXAM_SITE_CAPACITY_EXCEEDED",
                           "the site has no concurrent capacity left")

    run_checks([(56, not_in_past), (66, capacity)])
    row = new_row()
    row["_kind"] = "exam_appointment"
    row["claim_id"] = body["claim_id"]
    row["exam_site_id"] = body["exam_site_id"]
    row["starts_at"] = body["starts_at"]
    row["ends_at"] = body["ends_at"]
    row["status"] = "SCHEDULED"
    row["prep_session_completed"] = False
    row["completed_on"] = None
    row["cancellation_reason"] = None
    db.exam_appointments[row["id"]] = row
    site["booked_slot_count"] = site["booked_slot_count"] + 1
    bump(site)
    return object_response(view(row), 201)


@bp.get("/exam-appointments")
def list_appointments():
    authorize(READ_APPOINTMENTS)
    run_checks()
    rows = filter_rows(ordered(db.exam_appointments.values()), {
        "claim_id": "claim_id",
        "exam_site_id": "exam_site_id",
        "status": "status",
        "prep_session_completed": "prep_session_completed",
    })
    window, page = page_of(rows)
    return list_response(view_all(window), page)


@bp.get("/exam-appointments/<row_id>")
def read_appointment(row_id):
    authorize(READ_APPOINTMENTS)
    row = need_appointment(row_id)
    run_checks()
    return object_response(view(row))


@bp.post("/exam-appointments/<row_id>/status")
def drive_appointment(row_id):
    authorize(("CountyOfficer",))

    def extra(body):
        if body.get("action") == "COMPLETE":
            if parse_date(body["completed_on"]) > now_date():
                raise ApiError("ERR_VALIDATION",
                               "completed_on may not be later than the"
                               " logical-clock date")

    body = check_shape({
        "actions": ("COMPLETE_PREP", "COMPLETE", "NO_SHOW", "CANCEL"),
        "optional": ["reason", "completed_on"],
        "action_required": {
            "COMPLETE": ("completed_on",),
            "CANCEL": ("reason",),
        },
        "extra": extra,
    })
    appointment = need_appointment(row_id)
    action = body["action"]

    def from_state():
        if appointment["status"] != "SCHEDULED":
            invalid_transition("%s is not available from %s"
                               % (action, appointment["status"]))
        if action == "COMPLETE_PREP" and appointment["prep_session_completed"]:
            invalid_transition("the preparation session is already logged")
        if action == "NO_SHOW" and db.clock < dt(appointment["ends_at"]):
            invalid_transition("the appointment has not ended yet")

    def prep_done():
        if action == "COMPLETE" and not appointment["prep_session_completed"]:
            raise ApiError("ERR_EXAM_PREP_INCOMPLETE",
                           "the preparation session has not been logged")

    run_checks([(40, from_state), (52, prep_done)])
    site = db.exam_sites.get(appointment["exam_site_id"])
    claim = db.claims.get(appointment["claim_id"])

    if action == "COMPLETE_PREP":
        appointment["prep_session_completed"] = True
        bump(appointment)
        return object_response(view(appointment))

    if action == "COMPLETE":
        appointment["status"] = "COMPLETED"
        appointment["completed_on"] = body["completed_on"]
    elif action == "NO_SHOW":
        appointment["status"] = "NO_SHOW"
    else:
        appointment["status"] = "CANCELLED"
        appointment["cancellation_reason"] = body["reason"]
    bump(appointment)
    if site is not None:
        site["booked_slot_count"] = site["booked_slot_count"] - 1
        bump(site)

    if action == "COMPLETE" and claim is not None:
        item = new_row()
        item["_kind"] = "evidence_item"
        item["claim_id"] = claim["id"]
        item["evidence_type"] = "DBQ"
        item["status"] = "RECEIVED"
        item["provider_name"] = None
        item["nexus_opinion_strength"] = "NONE"
        item["requested_on"] = calc.clock_date_str()
        item["received_on"] = body["completed_on"]
        item["weight_points"] = 0.00
        item["status_reason"] = None
        item["auto_generated"] = True
        calc.refresh_item_points(item)
        db.evidence_items[item["id"]] = item
        calc.refresh_claim_score(claim)
        bump(claim)
    return object_response(view(appointment))


# --------------------------------------------------------------------------
# decision reviews
# --------------------------------------------------------------------------

@bp.post("/decision-reviews")
def open_review():
    authorize(("CountyOfficer",))
    body = check_shape({"required": ["claim_id", "review_lane"]})
    claim = need_claim(body["claim_id"])

    def from_state():
        if claim["status"] != "DECIDED":
            invalid_transition("counselling requires a DECIDED claim")

    run_checks([(40, from_state)])
    row = new_row()
    row["_kind"] = "decision_review"
    row["claim_id"] = claim["id"]
    row["counseled_by_representative_id"] = g.user_id
    row["review_lane"] = body["review_lane"]
    row["status"] = "COUNSELED"
    row["decision_notice_date"] = claim["decided_on"]
    row["deadline_on"] = fmt_date(calc.deadline_on(claim["decided_on"]))
    row["elected_on"] = None
    row["filed_on"] = None
    row["closure_reason"] = None
    db.decision_reviews[row["id"]] = row
    return object_response(view(row), 201)


@bp.get("/decision-reviews")
def list_reviews():
    authorize(READ_REVIEWS)
    run_checks()
    rows = filter_rows(ordered(db.decision_reviews.values()), {
        "claim_id": "claim_id",
        "counseled_by_representative_id": "counseled_by_representative_id",
        "status": "status",
        "review_lane": "review_lane",
    })
    window, page = page_of(rows)
    return list_response(view_all(window), page)


@bp.post("/decision-reviews/sweep-expirations")
def sweep_reviews():
    authorize(("SystemAdmin",))
    check_shape({})
    run_checks()
    expired = []
    for review in ordered(db.decision_reviews.values()):
        if review["status"] not in ("COUNSELED", "ELECTED"):
            continue
        if calc.days_remaining(review) < 0:
            review["status"] = "EXPIRED"
            review["closure_reason"] = "DEADLINE_SWEEP"
            bump(review)
            expired.append(review["id"])
    return object_response({"expired_count": len(expired),
                            "expired_review_ids": expired})


@bp.get("/decision-reviews/<row_id>")
def read_review(row_id):
    authorize(READ_REVIEWS)
    row = need_review(row_id)
    run_checks()
    return object_response(view(row))


REVIEW_FROM = {
    "ELECT": ("COUNSELED",),
    "FILE": ("ELECTED",),
    "WITHDRAW": ("COUNSELED", "ELECTED"),
}


@bp.post("/decision-reviews/<row_id>/status")
def drive_review(row_id):
    def owner():
        review = db.decision_reviews.get(row_id)
        if review is None:
            return None
        claim = db.claims.get(review["claim_id"])
        return None if claim is None else claim["veteran_id"]

    authorize(("CountyOfficer", "VeteranClient"), owner)

    def extra(body):
        action = body.get("action")
        if action == "ELECT" and parse_date(body["elected_on"]) > now_date():
            raise ApiError("ERR_VALIDATION",
                           "elected_on may not be later than the"
                           " logical-clock date")
        if action == "FILE" and parse_date(body["filed_on"]) > now_date():
            raise ApiError("ERR_VALIDATION",
                           "filed_on may not be later than the"
                           " logical-clock date")

    body = check_shape({
        "actions": ("ELECT", "FILE", "WITHDRAW"),
        "optional": ["review_lane", "elected_on", "filed_on", "reason"],
        "action_roles": (("ELECT", ("CountyOfficer",)),
                         ("FILE", ("CountyOfficer",)),
                         ("WITHDRAW", ("VeteranClient",))),
        "action_required": {
            "ELECT": ("elected_on",),
            "FILE": ("filed_on",),
            "WITHDRAW": ("reason",),
        },
        "extra": extra,
    })
    review = need_review(row_id)
    action = body["action"]

    def from_state():
        if review["status"] not in REVIEW_FROM[action]:
            invalid_transition("%s is not available from %s"
                               % (action, review["status"]))

    def in_window():
        if action in ("ELECT", "FILE") and calc.days_remaining(review) < 0:
            raise ApiError("ERR_APPEAL_DEADLINE_PASSED",
                           "the appeal window has closed")

    run_checks([(40, from_state), (55, in_window)])

    if action == "ELECT":
        review["status"] = "ELECTED"
        review["elected_on"] = body["elected_on"]
        if body.get("review_lane") is not None:
            review["review_lane"] = body["review_lane"]
        bump(review)
    elif action == "FILE":
        review["status"] = "FILED"
        review["filed_on"] = body["filed_on"]
        bump(review)
        claim = db.claims.get(review["claim_id"])
        if claim is not None and claim["status"] == "DECIDED":
            claim["status"] = "FILED"
            claim["reopen_count"] = claim["reopen_count"] + 1
            bump(claim)
            calc.refresh_caseload(calc.claim_preparer(claim))
    else:
        review["status"] = "WITHDRAWN"
        review["closure_reason"] = body["reason"]
        bump(review)
    return object_response(view(review))
