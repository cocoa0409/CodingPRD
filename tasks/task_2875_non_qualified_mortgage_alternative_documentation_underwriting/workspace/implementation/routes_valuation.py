"""Valuation orders, receipt, review decisions and the appraisal review row."""
from datetime import timedelta

from flask import Blueprint, request

from core import (ApiError, Field, authenticate, invalid, iso_instant, ordered, paginate,
                  raw_body, respond_collection, respond_created, respond_object,
                  validate_body)
from store import Tx, db, resolve_fk
import services

bp = Blueprint("valuations", __name__)

VALUATION_TYPES = ("PRIMARY_APPRAISAL", "SECOND_APPRAISAL", "DESK_REVIEW", "FIELD_REVIEW")
ORDER_ROLES = ("LoanOfficer", "Underwriter", "AppraisalReviewer")
ORDER_READERS = ("LoanOfficer", "Underwriter", "AppraisalReviewer", "PostCloseAuditor")
REVIEW_READERS = ("LoanOfficer", "Underwriter", "AppraisalReviewer", "PostCloseAuditor",
                  "SecuritizationAnalyst")
OPEN_FILE_STATUSES = ("DOC_TYPE_SELECTED", "UNDERWRITING", "SUSPENDED")

ORDER_FIELDS = [
    Field("loan_file_id", "str", True),
    Field("valuation_type", "enum", True, VALUATION_TYPES),
    Field("vendor_code", "str", True),
    Field("effective_date", "datetime", True),
]


def order_state(condition, message):
    if not condition:
        raise ApiError("ERR_VALUATION_ORDER_STATE_INVALID", message)


@bp.post("/valuation-orders")
def create_order():
    authenticate(ORDER_ROLES)
    raw = raw_body()
    loan_file = resolve_fk(raw, "loan_file_id", "loan_files")
    values = validate_body(ORDER_FIELDS)
    # priority 10
    if loan_file["status"] not in OPEN_FILE_STATUSES:
        raise ApiError("ERR_LOAN_FILE_STATE_INVALID",
                       "loan file status %s does not permit a valuation order"
                       % loan_file["status"])
    kind = values["valuation_type"]
    # priority 25
    if services.reorder_too_soon(loan_file, kind):
        raise ApiError("ERR_VALUATION_REORDER_TOO_SOON",
                       "a %s order was placed within the 30-day re-order buffer" % kind)

    tx = Tx()
    effective = values["effective_date"]
    row = db.insert("valuation_orders", {
        "loan_file_id": loan_file["id"],
        "valuation_type": kind,
        "vendor_code": values["vendor_code"],
        "effective_date": iso_instant(effective),
        "validity_expires_date": iso_instant(
            effective + timedelta(days=services.VALIDITY_WINDOW_DAYS)),
        "appraised_value_cents": None,
        "status": "ORDERED",
        "rejection_reason": None,
    })
    review = services.ensure_review(loan_file, tx)
    if kind == "SECOND_APPRAISAL" and review["second_valuation_status"] == "SECOND_REQUIRED":
        tx.watch(review)
        review["second_valuation_status"] = "SECOND_ORDERED"
    tx.commit()
    return respond_created(row)


@bp.get("/valuation-orders/<ident>")
def read_order(ident):
    authenticate(ORDER_READERS)
    return respond_object(db.fetch("valuation_orders", ident))


@bp.get("/loan-files/<ident>/valuation-orders")
def list_orders(ident):
    authenticate(ORDER_READERS)
    loan_file = db.fetch("loan_files", ident)
    rows = services.orders_of(loan_file)
    for key in ("valuation_type", "status"):
        wanted = request.args.get(key)
        if wanted:
            rows = [r for r in rows if r[key] == wanted]
    page, limit, offset, total = paginate(ordered(rows))
    return respond_collection(page, limit, offset, total)


@bp.post("/valuation-orders/<ident>/receive")
def receive_order(ident):
    authenticate(("AppraisalReviewer",))
    order = db.fetch("valuation_orders", ident)
    values = validate_body([Field("appraised_value_cents", "int", True)])
    if values["appraised_value_cents"] < 0:
        invalid("appraised_value_cents must not be negative")
    # priority 13
    order_state(order["status"] == "ORDERED",
                "valuation order status %s does not permit receipt" % order["status"])
    loan_file = db.find("loan_files", order["loan_file_id"])
    order_state(loan_file["status"] in ("UNDERWRITING", "SUSPENDED"),
                "a value may only be received while the file is UNDERWRITING or SUSPENDED")

    tx = Tx()
    tx.watch(order)
    order["appraised_value_cents"] = values["appraised_value_cents"]
    order["status"] = "RECEIVED"
    review = services.ensure_review(loan_file, tx)
    tx.watch(review)
    if (order["valuation_type"] == "PRIMARY_APPRAISAL"
            and review["primary_review_status"] == "PRIMARY_NOT_ORDERED"):
        review["primary_review_status"] = "PRIMARY_PENDING_REVIEW"
    if (order["valuation_type"] == "SECOND_APPRAISAL"
            and review["second_valuation_status"] == "SECOND_ORDERED"):
        review["second_valuation_status"] = "SECOND_RECEIVED"
    tx.commit()
    return respond_object(order)


@bp.post("/valuation-orders/<ident>/decision")
def decide_order(ident):
    authenticate(("AppraisalReviewer",))
    order = db.fetch("valuation_orders", ident)
    values = validate_body([
        Field("decision", "enum", True, ("ACCEPTED", "REJECTED")),
        Field("rejection_reason", "str"),
    ])
    if values["decision"] == "REJECTED" and "rejection_reason" not in values:
        invalid("rejection_reason is required when the decision is REJECTED")
    # priority 13
    order_state(order["status"] == "RECEIVED",
                "valuation order status %s does not permit a decision" % order["status"])
    loan_file = db.find("loan_files", order["loan_file_id"])

    tx = Tx()
    tx.watch(order)
    tx.watch(loan_file)
    if values["decision"] == "REJECTED":
        order["status"] = "REJECTED"
        order["rejection_reason"] = values["rejection_reason"]
        review = services.review_of(loan_file)
        if review is not None and order["valuation_type"] == "PRIMARY_APPRAISAL":
            tx.watch(review)
            review["primary_review_status"] = "PRIMARY_NOT_ORDERED"
    else:
        order["status"] = "ACCEPTED"
        services.accept_valuation(order, loan_file, tx)
    tx.commit()
    return respond_object(order)


@bp.get("/loan-files/<ident>/appraisal-reviews")
def list_reviews(ident):
    authenticate(REVIEW_READERS)
    loan_file = db.fetch("loan_files", ident)
    review = services.review_of(loan_file)
    rows = [review] if review is not None else []
    page, limit, offset, total = paginate(rows)
    return respond_collection(page, limit, offset, total)


@bp.post("/appraisal-reviews/<ident>/override-escalation")
def override_escalation(ident):
    authenticate(("AppraisalReviewer",))
    review = db.fetch("reviews", ident)
    values = validate_body([Field("override_justification", "str", True)])
    # priority 43
    if (review["primary_review_status"] != "PRIMARY_ESCALATED"
            or review["second_valuation_status"] != "SECOND_RECONCILED"):
        raise ApiError("ERR_REVIEW_STATE_INVALID",
                       "the appraisal review is not in an escalated state")

    tx = Tx()
    tx.watch(review)
    review["primary_review_status"] = "PRIMARY_CLEARED"
    review["escalation_reason"] = "OVERRIDDEN_BY_REVIEWER"
    review["_override_justification"] = values["override_justification"]
    loan_file = db.find("loan_files", review["loan_file_id"])
    if loan_file is not None:
        tx.watch(loan_file)
        services.recompute_eligibility(loan_file)
    tx.commit()
    return respond_object(review)
