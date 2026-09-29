"""Applications, completeness review rounds and the public comment record."""

from flask import Blueprint

import auth
import clock
import envelope
import services
import shape
import store
from errors import ApiError

bp = Blueprint("applications", __name__)

READ_ROLES = auth.STAFF_AND_PARTIES
ROUNDS_READ_ROLES = ["ProgramAdmin", "IntakeAnalyst", "DecisionOfficer", "Applicant"]
WITHDRAWABLE = ("DRAFT", "SUBMITTED", "COMPLETENESS_REVIEW", "INCOMPLETE", "DEEMED_COMPLETE")
COMPLETENESS_SOURCES = ("SUBMITTED", "COMPLETENESS_REVIEW")
STANCES = ("SUPPORT", "OPPOSE", "NEUTRAL")


# --- conversion, submission, withdrawal --------------------------------------

@bp.post("/applications")
def create_application():
    user_id, _role = auth.identity(["Applicant"])
    body = shape.body()
    loi_id = shape.string_field(body, "loi_id")
    requested_beds = shape.int_field(body, "requested_bed_count", minimum=1)
    capital_cost = shape.int_field(body, "projected_capital_cost_cents", minimum=0)
    narrative = shape.string_field(body, "narrative")
    partial = shape.bool_field(body, "partial_award_acceptable", required=False, default=False)

    letter = services.loi(loi_id)
    services.require_owner(user_id, letter["applicant_id"])

    if letter["review_determination"] != "REVIEWABLE":
        raise ApiError("ERR_LOI_NOT_REVIEWABLE",
                       "A non-reviewable letter cannot become an application.")
    if letter["status"] != "FILED":
        raise ApiError("ERR_LOI_ALREADY_CONVERTED",
                       "This letter of intent is no longer convertible.")

    services.require_standing_good(store.get("applicants", letter["applicant_id"]))

    for row in store.rows("applications"):
        if row["loi_id"] == loi_id:
            raise ApiError("ERR_DUPLICATE_LOI",
                           "An application already exists for this letter of intent.")

    record = store.create("applications", {
        "loi_id": loi_id,
        "batching_cycle_id": letter["batching_cycle_id"],
        "applicant_id": letter["applicant_id"],
        "requested_bed_count": requested_beds,
        "projected_capital_cost_cents": capital_cost,
        "narrative": narrative,
        "partial_award_acceptable": partial,
        "status": "DRAFT",
        "comparative_score": None,
        "score_sheet_count": 0,
        "allocated_bed_count": 0,
        "denial_reason": None,
        "completeness_round_count": 0,
        "decision_at": None,
        "appeal_window_closes_at": None,
    })
    letter["status"] = "CONVERTED"
    store.touch(letter)
    return envelope.ok(record, 201)


@bp.get("/applications/<record_id>")
def read_application(record_id):
    auth.identity(READ_ROLES)
    return envelope.ok(services.application(record_id))


@bp.get("/applications")
def list_applications():
    auth.identity(READ_ROLES)
    limit, offset = shape.pagination()
    picked = shape.filters("loi_id", "batching_cycle_id", "applicant_id", "status")
    rows = shape.apply_filters(store.sort_created(store.rows("applications")), picked)
    return envelope.ok_list(rows[offset:offset + limit], limit, offset, len(rows))


@bp.post("/applications/<record_id>/submit")
def submit_application(record_id):
    user_id, _role = auth.identity(["Applicant"])
    app = services.application(record_id)
    services.require_owner(user_id, app["applicant_id"])

    cycle_row = services.cycle_of_application(app)
    if app["status"] != "DRAFT" or cycle_row is None \
            or cycle_row["status"] != "OPEN_FOR_APPLICATIONS":
        raise ApiError("ERR_APPLICATION_NOT_SUBMITTABLE",
                       "The application or its cycle is not in a submittable state.")

    services.require_standing_good(services.applicant_of_application(app))

    if clock.now() > clock.parse_instant(cycle_row["application_deadline_at"]):
        raise ApiError("ERR_FILING_WINDOW_CLOSED", "The application window has closed.")

    app["status"] = "SUBMITTED"
    store.touch(app)
    return envelope.ok(app)


@bp.post("/applications/<record_id>/withdraw")
def withdraw_application(record_id):
    user_id, _role = auth.identity(["Applicant"])
    body = shape.body()
    shape.string_field(body, "reason", required=False, default=None)
    app = services.application(record_id)
    services.require_owner(user_id, app["applicant_id"])
    if app["status"] not in WITHDRAWABLE:
        raise ApiError("ERR_APPLICATION_NOT_SUBMITTABLE",
                       "A decided or already withdrawn application cannot be withdrawn.")
    services.require_no_hold(app["id"])
    app["status"] = "WITHDRAWN"
    store.touch(app)
    return envelope.ok(app)


# --- completeness review -----------------------------------------------------

def _require_completeness_stage(app):
    cycle_row = services.cycle_of_application(app)
    if (app["status"] not in COMPLETENESS_SOURCES or cycle_row is None
            or cycle_row["status"] != "COMPLETENESS_WINDOW"):
        raise ApiError("ERR_APPLICATION_NOT_IN_COMPLETENESS_REVIEW",
                       "The application is not in completeness review.")
    return cycle_row


@bp.post("/applications/<record_id>/completeness-reviews")
def issue_deficiency_notice(record_id):
    user_id, _role = auth.identity(["IntakeAnalyst"])
    body = shape.body()
    items = shape.array_field(body, "deficiency_items", non_empty=True)
    cure_raw, cure_at = shape.instant_field(body, "cure_deadline_at")
    app = services.application(record_id)
    cycle_row = _require_completeness_stage(app)

    completeness_deadline = clock.parse_instant(cycle_row["completeness_deadline_at"])
    if clock.now() > completeness_deadline:
        raise ApiError("ERR_FILING_WINDOW_CLOSED", "The completeness window has closed.")
    if cure_at > completeness_deadline:
        raise ApiError("ERR_INVALID_CYCLE_WINDOW",
                       "cure_deadline_at must fall at or before the cycle's "
                       "completeness_deadline_at.")

    record = store.create("completeness_reviews", {
        "application_id": app["id"],
        "round_number": app["completeness_round_count"] + 1,
        "deficiency_items": items,
        "cure_deadline_at": cure_raw,
        "issued_by_user_id": user_id,
        "status": "DEFICIENCY_NOTICE_ISSUED",
        "cure_response": None,
        "cured_at": None,
    })
    app["completeness_round_count"] = app["completeness_round_count"] + 1
    app["status"] = "INCOMPLETE"
    store.touch(app)
    return envelope.ok(record, 201)


@bp.get("/applications/<record_id>/completeness-reviews")
def list_completeness_reviews(record_id):
    auth.identity(ROUNDS_READ_ROLES)
    app = services.application(record_id)
    limit, offset = shape.pagination()
    rows = store.sort_created(services.reviews_of_application(app["id"]))
    return envelope.ok_list(rows[offset:offset + limit], limit, offset, len(rows))


@bp.post("/completeness-reviews/<record_id>/cure")
def cure_review(record_id):
    user_id, _role = auth.identity(["Applicant"])
    body = shape.body()
    response = shape.string_field(body, "cure_response")
    review = services.completeness_review(record_id)
    app = store.get("applications", review["application_id"])
    services.require_owner(user_id, app["applicant_id"] if app else None)

    if review["status"] != "DEFICIENCY_NOTICE_ISSUED":
        raise ApiError("ERR_COMPLETENESS_REVIEW_NOT_OPEN",
                       "This completeness review round is no longer open.")
    if clock.now() > clock.parse_instant(review["cure_deadline_at"]):
        raise ApiError("ERR_CURE_DEADLINE_PASSED", "The cure deadline has passed.")

    review["status"] = "CURED"
    review["cure_response"] = response
    review["cured_at"] = clock.now_str()
    store.touch(review)
    if app is not None:
        app["status"] = "COMPLETENESS_REVIEW"
        store.touch(app)
    return envelope.ok(review)


@bp.post("/applications/<record_id>/deem-complete")
def deem_complete(record_id):
    auth.identity(["IntakeAnalyst"])
    app = services.application(record_id)
    cycle_row = _require_completeness_stage(app)
    for review in services.reviews_of_application(app["id"]):
        if review["status"] == "DEFICIENCY_NOTICE_ISSUED":
            raise ApiError("ERR_COMPLETENESS_REVIEW_NOT_OPEN",
                           "An uncured deficiency notice is still open.")
    if clock.now() > clock.parse_instant(cycle_row["completeness_deadline_at"]):
        raise ApiError("ERR_FILING_WINDOW_CLOSED", "The completeness window has closed.")
    app["status"] = "DEEMED_COMPLETE"
    store.touch(app)
    return envelope.ok(app)


# --- public comments ---------------------------------------------------------

@bp.post("/applications/<record_id>/public-comments")
def file_comment(record_id):
    user_id, _role = auth.identity(["PublicParticipant"])
    body = shape.body()
    display_name = shape.string_field(body, "commenter_display_name")
    stance = shape.enum_field(body, "stance", STANCES)
    text = shape.string_field(body, "body")
    app = services.application(record_id)
    cycle_row = services.cycle_of_application(app)
    if cycle_row is not None and clock.now() > clock.parse_instant(
            cycle_row["comment_period_closes_at"]):
        raise ApiError("ERR_COMMENT_PERIOD_CLOSED", "The comment period has closed.")
    record = store.create("public_comments", {
        "application_id": app["id"],
        "commenter_user_id": user_id,
        "commenter_display_name": display_name,
        "stance": stance,
        "body": text,
        "filed_at": clock.now_str(),
    }, common=False)
    return envelope.ok(record, 201)


@bp.get("/applications/<record_id>/public-comments")
def list_comments(record_id):
    auth.identity(READ_ROLES)
    app = services.application(record_id)
    limit, offset = shape.pagination()
    rows = store.sort_created([c for c in store.rows("public_comments")
                               if c["application_id"] == app["id"]])
    return envelope.ok_list(rows[offset:offset + limit], limit, offset, len(rows))
