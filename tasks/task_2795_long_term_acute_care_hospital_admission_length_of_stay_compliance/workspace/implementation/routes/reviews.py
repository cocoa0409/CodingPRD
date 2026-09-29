"""Denial-risk reviews, documentation queries and physician responses (PRD 3.8)."""

from flask import Blueprint

import auth
import lookup
import serialize
import validate
from clock import now
from envelope import array_response, object_response
from errors import ApiError
from services import cascade, scoring
from store import db, sorted_rows, touch

bp = Blueprint("reviews", __name__)

CO = auth.ROLE_COMPLIANCE_OFFICER
IC = auth.ROLE_INTAKE_COORDINATOR
URN = auth.ROLE_UR_NURSE
AP = auth.ROLE_ATTENDING_PHYSICIAN
RIA = auth.ROLE_REVENUE_ANALYST

REVIEW_STATUSES = ("OPEN", "QUERIES_ISSUED", "CLEARED", "ESCALATED", "VOIDED")
QUERY_STATUSES = ("ISSUED", "ANSWERED", "CLOSED", "EXPIRED", "VOIDED")
QUERY_TYPES = ("VENT_WEANING_RATIONALE", "WOUND_STAGING", "IDT_PARTICIPATION",
               "SITE_NEUTRAL_JUSTIFICATION")
RESOLVE_OUTCOMES = ("CLEARED", "ESCALATED")
LIVE_REVIEW_STATUSES = ("OPEN", "QUERIES_ISSUED")


# --------------------------------------------------------------------------- #
# reviews
# --------------------------------------------------------------------------- #

@bp.route("/stays/<stay_id>/denial-risk-reviews", methods=["GET"])
def list_stay_reviews(stay_id):
    auth.require_role(CO, RIA, URN, AP, IC)
    stay = lookup.stay(stay_id)
    limit, offset = validate.pagination()
    status = validate.query_enum("status", REVIEW_STATUSES)

    rows = [r for r in db.reviews.values() if r["stay_id"] == stay["id"]]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = sorted_rows(rows)
    page = lookup.page(rows, limit, offset)
    return array_response([serialize.review(r) for r in page], limit, offset, len(rows))


@bp.route("/denial-risk-reviews/<review_id>", methods=["GET"])
def get_review(review_id):
    auth.require_role(CO, RIA, URN, AP)
    return object_response(serialize.review(lookup.review(review_id)))


@bp.route("/denial-risk-reviews/<review_id>/rescore", methods=["POST"])
def rescore_review(review_id):
    validate.get_body()
    auth.require_role(CO)
    review = lookup.review(review_id)
    if review["status"] == "VOIDED":
        raise ApiError("ERR_INVALID_STATE", "A VOIDED review can no longer be rescored.")

    scoring.expire_overdue_queries(review)
    if review["status"] == "QUERIES_ISSUED" and not scoring.has_issued_query(review):
        review["status"] = "OPEN"
    scoring.apply_scores(review)
    return object_response(serialize.review(review))


@bp.route("/denial-risk-reviews/<review_id>/resolve", methods=["POST"])
def resolve_review(review_id):
    body = validate.get_body()
    outcome = validate.req_enum(body, "outcome", RESOLVE_OUTCOMES)
    resolution_note = validate.req_str(body, "resolution_note", 1, 1000)
    auth.require_role(CO)
    review = lookup.review(review_id)

    if review["status"] not in LIVE_REVIEW_STATUSES:
        raise ApiError("ERR_INVALID_STATE",
                       "Only an OPEN or QUERIES_ISSUED review may be resolved.")

    if outcome == "CLEARED":
        if review["status"] != "OPEN":
            raise ApiError("ERR_INVALID_STATE", "A CLEARED resolution is permitted only from OPEN.")
        if review["risk_band"] == "HIGH":
            raise ApiError("ERR_INVALID_STATE", "A HIGH-risk chart cannot be cleared.")
        if scoring.has_issued_query(review):
            raise ApiError("ERR_INVALID_STATE",
                           "A query on the review is still ISSUED.")

    review["status"] = outcome
    review["resolved_by_user_id"] = auth.acting_user_id()
    review["resolution_note"] = resolution_note
    touch(review)
    return object_response(serialize.review(review))


# --------------------------------------------------------------------------- #
# documentation queries
# --------------------------------------------------------------------------- #

@bp.route("/denial-risk-reviews/<review_id>/documentation-queries", methods=["POST"])
def issue_documentation_query(review_id):
    body = validate.get_body()
    query_type = validate.req_enum(body, "query_type", QUERY_TYPES)
    prompt_text = validate.req_str(body, "prompt_text", 1, 1000)
    auth.require_role(URN)
    review = lookup.review(review_id)

    if review["status"] not in LIVE_REVIEW_STATUSES:
        raise ApiError("ERR_INVALID_STATE",
                       "Only an OPEN or QUERIES_ISSUED review may issue a query.")
    stay = db.stays[review["stay_id"]]
    if stay["clinical_status"] != "DISCHARGED":
        raise ApiError("ERR_INVALID_STATE", "The review's stay is not DISCHARGED.")

    query = cascade.issue_query(review, stay, query_type, prompt_text, auth.acting_user_id())
    if review["status"] == "OPEN":
        review["status"] = "QUERIES_ISSUED"
        touch(review)
    return object_response(serialize.query(query), 201)


@bp.route("/documentation-queries/<query_id>", methods=["GET"])
def get_query(query_id):
    auth.require_role(CO, URN, AP, RIA)
    return object_response(serialize.query(lookup.query(query_id)))


@bp.route("/documentation-queries", methods=["GET"])
def list_queries():
    auth.require_role(CO, URN, AP, RIA)
    limit, offset = validate.pagination()
    review_id = validate.query_str("denial_risk_review_id")
    stay_id = validate.query_str("stay_id")
    physician_id = validate.query_str("answered_by_physician_id")
    status = validate.query_enum("status", QUERY_STATUSES)

    rows = list(db.queries.values())
    if review_id is not None:
        rows = [r for r in rows if r["denial_risk_review_id"] == review_id]
    if stay_id is not None:
        rows = [r for r in rows if r["stay_id"] == stay_id]
    if physician_id is not None:
        rows = [r for r in rows if r["answered_by_physician_id"] == physician_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]

    rows = sorted_rows(rows)
    page = lookup.page(rows, limit, offset)
    return array_response([serialize.query(r) for r in page], limit, offset, len(rows))


@bp.route("/documentation-queries/<query_id>/answer", methods=["POST"])
def answer_query(query_id):
    body = validate.get_body()
    response_text = validate.req_str(body, "response_text", 1, 2000)
    auth.require_role(AP)
    query = lookup.query(query_id)
    physician = auth.acting_physician()

    if query["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_STATE", "Only an ISSUED query may be answered.")

    if physician["credential_status"] != "ACTIVE":
        raise ApiError("ERR_PHYSICIAN_NOT_CREDENTIALED",
                       "Answering a query requires an ACTIVE credential.")

    instant = now()
    if query["due_at"] is not None and instant > query["due_at"]:
        query["status"] = "EXPIRED"
        touch(query)
        raise ApiError("ERR_QUERY_RESPONSE_WINDOW_EXPIRED",
                       "The 72-hour query response window has expired.")

    query["status"] = "ANSWERED"
    query["response_text"] = response_text
    query["answered_at"] = instant
    query["answered_by_physician_id"] = physician["id"]
    touch(query)

    review = db.reviews.get(query["denial_risk_review_id"])
    if review is not None:
        scoring.apply_scores(review)

    return object_response(serialize.query(query))


@bp.route("/documentation-queries/<query_id>/close", methods=["POST"])
def close_query(query_id):
    validate.get_body()
    auth.require_role(URN)
    query = lookup.query(query_id)

    if query["status"] != "ANSWERED":
        raise ApiError("ERR_INVALID_STATE", "Only an ANSWERED query may be closed.")

    actor = auth.acting_user_id()
    if actor == query["issued_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The nurse closing a query must differ from the one who issued it.")

    query["status"] = "CLOSED"
    query["closed_by_user_id"] = actor
    touch(query)
    return object_response(serialize.query(query))
