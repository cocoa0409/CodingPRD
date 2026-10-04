"""Advertising reviews, scam reports, and the scam-pattern publication
(PRD 3.8)."""
from flask import Blueprint, request

import db
import domain
import web
from constants import (
    AD_REVIEW_OUTCOMES,
    ALL_ROLES,
    ROLE_BUSINESS_REP,
    ROLE_BUREAU_ADMIN,
    ROLE_CONSUMER,
    ROLE_STANDARDS_REVIEWER,
    SCAM_PATTERN_MIN_REPORTS,
)
from errors import ApiError
from routes_core import get_business_or_404

bp = Blueprint("surveillance", __name__)

REVIEW_LIST_ROLES = {ROLE_BUREAU_ADMIN, ROLE_STANDARDS_REVIEWER, ROLE_BUSINESS_REP}


def get_ad_review_or_404(review_id):
    review = db.STORE.advertising_reviews.get(review_id)
    if review is None:
        raise ApiError("ERR_AD_REVIEW_NOT_FOUND")
    return review


def get_scam_report_or_404(report_id):
    report = db.STORE.scam_reports.get(report_id)
    if report is None:
        raise ApiError("ERR_SCAM_REPORT_NOT_FOUND")
    return report


def serialize_ad_review(review):
    return db.serialize(review)


def serialize_scam_report(report):
    return db.serialize(report)


# ---------------------------------------------------------------------------
# POST /businesses/{id}/advertising-reviews
# ---------------------------------------------------------------------------
@bp.route("/businesses/<business_id>/advertising-reviews", methods=["POST"])
def open_ad_review(business_id):
    web.authz({ROLE_BUREAU_ADMIN, ROLE_STANDARDS_REVIEWER})
    business = get_business_or_404(business_id)
    data = web.body()
    claim_description = web.require_string(data, "claim_description")
    review = db.new_entity(
        "advertising_reviews",
        {
            "business_id": business_id,
            "claim_description": claim_description,
            "status": "UNDER_REVIEW",
            "regulator_name": None,
            "opened_at": db.now(),
            "concluded_at": None,
            "referred_at": None,
        },
    )
    # CLEAR -> UNDER_AD_REVIEW; REFERRED_TO_REGULATOR is sticky and stays put
    if business["advertising_compliance_status"] == "CLEAR":
        business["advertising_compliance_status"] = "UNDER_AD_REVIEW"
    # opening a review regenerates the provisional rating (advertising
    # deduction may have changed) and bumps the business
    domain.regenerate_provisional(business)
    return web.success_object(serialize_ad_review(review), status=201)


# ---------------------------------------------------------------------------
# POST /advertising-reviews/{id}/conclude
# ---------------------------------------------------------------------------
@bp.route("/advertising-reviews/<review_id>/conclude", methods=["POST"])
def conclude_ad_review(review_id):
    web.authz({ROLE_STANDARDS_REVIEWER})
    review = get_ad_review_or_404(review_id)
    data = web.body()
    # priority 5: schema — a deceptive conclusion requires regulator_name
    outcome = web.require_enum(data, "outcome", AD_REVIEW_OUTCOMES)
    regulator_name = web.optional_string(data, "regulator_name")
    if outcome == "SUBSTANTIATED_DECEPTIVE" and not regulator_name:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "SUBSTANTIATED_DECEPTIVE requires regulator_name",
        )
    # priority 7: from-state
    if review["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_AD_REVIEW_INVALID_STATE")
    business = get_business_or_404(review["business_id"])
    now = db.now()
    review["concluded_at"] = now
    if outcome == "CLEARED":
        review["status"] = "CLEARED"
        # the business returns to CLEAR only when no other review of that
        # business remains UNDER_REVIEW — the same condition lets a referred
        # business return to CLEAR
        still_open = any(
            r["status"] == "UNDER_REVIEW"
            for r in db.STORE.advertising_reviews.values()
            if r["business_id"] == business["id"] and r["id"] != review["id"]
        )
        if not still_open:
            business["advertising_compliance_status"] = "CLEAR"
    else:  # SUBSTANTIATED_DECEPTIVE
        review["status"] = "REFERRED_TO_REGULATOR"
        review["referred_at"] = now
        review["regulator_name"] = regulator_name
        business["advertising_compliance_status"] = "REFERRED_TO_REGULATOR"
    db.touch(review)
    # either conclusion regenerates the provisional rating
    domain.regenerate_provisional(business)
    return web.success_object(serialize_ad_review(review), status=200)


# ---------------------------------------------------------------------------
# GET /businesses/{id}/advertising-reviews
# ---------------------------------------------------------------------------
@bp.route("/businesses/<business_id>/advertising-reviews", methods=["GET"])
def list_ad_reviews(business_id):
    web.authz(REVIEW_LIST_ROLES)
    get_business_or_404(business_id)
    status = request.args.get("status")
    items = [
        r for r in db.STORE.advertising_reviews.values()
        if r["business_id"] == business_id
    ]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    return web.paginated_entities(items, serialize_ad_review)


# ---------------------------------------------------------------------------
# POST /scam-reports
# ---------------------------------------------------------------------------
@bp.route("/scam-reports", methods=["POST"])
def file_scam_report():
    user_id, role = web.authz({ROLE_CONSUMER})
    data = web.body()
    # priority 3: ownership on the payload consumer id
    consumer_id = data.get("consumer_id")
    if consumer_id is not None and consumer_id != user_id:
        raise ApiError("ERR_FORBIDDEN_OWNERSHIP")
    # priority 4: body-id existence
    if consumer_id is not None and consumer_id not in db.STORE.consumers:
        raise ApiError("ERR_CONSUMER_NOT_FOUND")
    business_id = data.get("business_id")
    if business_id is not None and business_id not in db.STORE.businesses:
        raise ApiError("ERR_BUSINESS_NOT_FOUND")
    # priority 5: schema
    web.require_fields(data, "consumer_id", "business_id")
    description = web.require_string(data, "description")
    incident_date = web.require_datetime(data, "incident_date")
    report = db.new_entity(
        "scam_reports",
        {
            "consumer_id": consumer_id,
            "business_id": business_id,
            "description": description,
            "incident_date": incident_date,
            "status": "RECEIVED",
            "published_at": None,
        },
    )
    return web.success_object(serialize_scam_report(report), status=201)


# ---------------------------------------------------------------------------
# GET /businesses/{id}/scam-reports
# ---------------------------------------------------------------------------
@bp.route("/businesses/<business_id>/scam-reports", methods=["GET"])
def list_scam_reports(business_id):
    web.authz(ALL_ROLES)
    get_business_or_404(business_id)
    status = request.args.get("status")
    items = [
        r for r in db.STORE.scam_reports.values()
        if r["business_id"] == business_id
    ]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    return web.paginated_entities(items, serialize_scam_report)


# ---------------------------------------------------------------------------
# POST /scam-reports/{id}/publish
# ---------------------------------------------------------------------------
@bp.route("/scam-reports/<report_id>/publish", methods=["POST"])
def publish_scam_report(report_id):
    web.authz({ROLE_BUREAU_ADMIN})
    report = get_scam_report_or_404(report_id)
    if report["status"] != "RECEIVED":
        raise ApiError("ERR_SCAM_REPORT_INVALID_STATE")
    report["status"] = "PUBLISHED"
    report["published_at"] = db.now()
    db.touch(report)
    business = db.STORE.businesses.get(report["business_id"])
    if business is not None:
        # published_scam_count_12m recomputes; provisional regenerates
        domain.regenerate_provisional(business)
    return web.success_object(serialize_scam_report(report), status=200)


# ---------------------------------------------------------------------------
# GET /scam-patterns
# ---------------------------------------------------------------------------
@bp.route("/scam-patterns", methods=["GET"])
def scam_patterns():
    web.authz(ALL_ROLES)
    now = db.now()
    rows = []
    for business in db.STORE.businesses.values():
        count = domain.published_scam_count(business["id"], now)
        if count >= 1:
            rows.append(
                {
                    "business_id": business["id"],
                    "legal_name": business["legal_name"],
                    "published_report_count_12m": count,
                    "pattern_flag": count >= SCAM_PATTERN_MIN_REPORTS,
                    "_seq": business["_seq"],
                }
            )
    # count DESC, tie-break legal_name ASC — never id (insertion order only
    # stabilizes exact ties via the stable sort)
    rows.sort(key=lambda r: (-r["published_report_count_12m"], r["legal_name"]))
    for row in rows:
        row.pop("_seq", None)
    limit, offset = web.pagination_params()
    page, meta_fields = web.paginate(rows, limit, offset)
    return web.success_wrapped_list("patterns", page, meta_fields)
