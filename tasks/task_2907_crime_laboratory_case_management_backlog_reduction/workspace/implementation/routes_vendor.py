"""Vendor engagements: award, shipment, return and withdrawal."""
from decimal import Decimal

from flask import Blueprint

import serialize
import services as S
from auth import CASE_MANAGER, endpoint
from envelope import object_response
from errors import ApiError
from store import db, new_row, touch
from util import dec, fractional_days, q2, qcents
from validate import Field, parse

bp = Blueprint("vendor", __name__)


@bp.route("/lab/examination-requests/<examination_request_id>"
          "/vendor-engagements", methods=["POST"])
@endpoint(CASE_MANAGER)
def award_engagement(examination_request_id):
    request_row = S.find_examination_request(examination_request_id)
    body = parse([
        Field("vendor_id", "string", required=True, min_length=1),
        Field("window_start_utc", "instant", required=True),
        Field("window_end_utc", "instant", required=True),
        Field("rush_flag", "boolean", default=False),
    ])
    vendor = S.find_vendor(body["vendor_id"])
    if request_row["status"] != "QUEUED":
        raise ApiError("ERR_EXAM_REQUEST_INVALID_STATE")
    if body["window_end_utc"] <= body["window_start_utc"]:
        raise ApiError("ERR_INVALID_INTERVAL")
    if (request_row["discipline"] not in vendor["accredited_disciplines"]
            or vendor["accreditation_expires_at_utc"] <= body["window_end_utc"]):
        raise ApiError("ERR_VENDOR_NOT_ACCREDITED")
    if vendor["status"] != "ACTIVE":
        raise ApiError("ERR_VENDOR_SUSPENDED")
    occupying = 0
    for existing in S.occupying_engagements(vendor["id"]):
        if S.windows_intersect_closed(
                body["window_start_utc"], body["window_end_utc"],
                existing["window_start_utc"], existing["window_end_utc"]):
            occupying += 1
    if occupying + 1 > vendor["concurrent_case_capacity"]:
        raise ApiError("ERR_VENDOR_CAPACITY_EXCEEDED")
    pricing = S.price_award(vendor, request_row["item_count"], body["rush_flag"])
    committed = (int(vendor["encumbered_cents"]) + int(vendor["spent_cents"])
                 + pricing["award_amount_cents"])
    if committed > int(vendor["contract_ceiling_cents"]):
        raise ApiError("ERR_VENDOR_CEILING_EXCEEDED")
    row = new_row()
    row.update({
        "examination_request_id": request_row["id"],
        "vendor_id": vendor["id"],
        "window_start_utc": body["window_start_utc"],
        "window_end_utc": body["window_end_utc"],
        "rush_flag": body["rush_flag"],
        "item_count": request_row["item_count"],
        "final_invoice_cents": None,
        "variance_cents": None,
        "status": "AWARDED",
        "awarded_at_utc": db.now(),
        "shipped_at_utc": None,
        "returned_at_utc": None,
        "custody_days": None,
        "cancellation_reason": None,
    })
    row.update(pricing)
    db.vendor_engagements[row["id"]] = row
    vendor["encumbered_cents"] = (
        int(vendor["encumbered_cents"]) + pricing["award_amount_cents"]
    )
    touch(vendor)
    request_row["status"] = "OUTSOURCED"
    touch(request_row)
    case = db.cases.get(request_row["case_id"])
    if case is not None:
        S.case_recompute(case)
    return object_response(serialize.vendor_engagement(row), 201)


@bp.route("/lab/vendor-engagements/<vendor_engagement_id>/confirm-shipment",
          methods=["POST"])
@endpoint(CASE_MANAGER)
def confirm_shipment(vendor_engagement_id):
    engagement = S.find_vendor_engagement(vendor_engagement_id)
    parse([Field("shipment_note", "string")])
    if engagement["status"] != "AWARDED":
        raise ApiError("ERR_VENDOR_ENGAGEMENT_INVALID_STATE")
    request_row = db.examination_requests.get(engagement["examination_request_id"])
    item = None
    if request_row is not None:
        item = db.evidence_items.get(request_row["evidence_item_id"])
    if item is None or item["custody_status"] != "IN_VAULT":
        raise ApiError("ERR_EVIDENCE_CUSTODY_INVALID_STATE")
    if not item["seal_intact"]:
        raise ApiError("ERR_EVIDENCE_SEAL_BROKEN")
    engagement["status"] = "AT_VENDOR"
    engagement["shipped_at_utc"] = db.now()
    touch(engagement)
    item["custody_status"] = "IN_ANALYSIS"
    item["checkout_count"] = item["checkout_count"] + 1
    touch(item)
    return object_response(serialize.vendor_engagement(engagement), 200)


@bp.route("/lab/vendor-engagements/<vendor_engagement_id>/record-return",
          methods=["POST"])
@endpoint(CASE_MANAGER)
def record_return(vendor_engagement_id):
    engagement = S.find_vendor_engagement(vendor_engagement_id)
    body = parse([
        Field("final_invoice_cents", "integer", required=True, minimum=0),
    ])
    if engagement["status"] != "AT_VENDOR":
        raise ApiError("ERR_VENDOR_ENGAGEMENT_INVALID_STATE")
    returned = db.now()
    award = int(engagement["award_amount_cents"])
    invoice = body["final_invoice_cents"]
    engagement["status"] = "RETURNED"
    engagement["returned_at_utc"] = returned
    engagement["custody_days"] = fractional_days(
        engagement["awarded_at_utc"], returned)
    engagement["final_invoice_cents"] = invoice
    engagement["variance_cents"] = invoice - award
    touch(engagement)
    vendor = db.vendors.get(engagement["vendor_id"])
    if vendor is not None:
        vendor["encumbered_cents"] = int(vendor["encumbered_cents"]) - award
        vendor["spent_cents"] = int(vendor["spent_cents"]) + invoice
        touch(vendor)
    request_row = db.examination_requests.get(engagement["examination_request_id"])
    if request_row is not None:
        request_row["status"] = "TECH_REVIEW"
        S.refresh_vendor_custody_days(request_row)
        touch(request_row)
        item = db.evidence_items.get(request_row["evidence_item_id"])
        if item is not None and item["custody_status"] == "IN_ANALYSIS":
            item["custody_status"] = "IN_VAULT"
            touch(item)
        case = db.cases.get(request_row["case_id"])
        if case is not None:
            S.case_recompute(case)
    tolerance = qcents(Decimal(award) * S.VENDOR_VARIANCE_TOLERANCE_PCT)
    if abs(engagement["variance_cents"]) > tolerance:
        S.open_nonconformance(
            "VENDOR_VARIANCE", "MINOR",
            "Vendor invoice variance on engagement %s exceeds tolerance."
            % engagement["id"],
            examination_request_id=engagement["examination_request_id"],
            analyst_id=None,
        )
    return object_response(serialize.vendor_engagement(engagement), 200)


@bp.route("/lab/vendor-engagements/<vendor_engagement_id>/cancel",
          methods=["POST"])
@endpoint(CASE_MANAGER)
def cancel_engagement(vendor_engagement_id):
    engagement = S.find_vendor_engagement(vendor_engagement_id)
    body = parse([Field("cancellation_reason", "string", required=True)])
    if engagement["status"] not in ("AWARDED", "AT_VENDOR"):
        raise ApiError("ERR_VENDOR_ENGAGEMENT_INVALID_STATE")
    was_at_vendor = engagement["status"] == "AT_VENDOR"
    engagement["status"] = "CANCELLED"
    engagement["cancellation_reason"] = body["cancellation_reason"]
    touch(engagement)
    vendor = db.vendors.get(engagement["vendor_id"])
    if vendor is not None:
        vendor["encumbered_cents"] = (
            int(vendor["encumbered_cents"]) - int(engagement["award_amount_cents"])
        )
        touch(vendor)
    request_row = db.examination_requests.get(engagement["examination_request_id"])
    if request_row is not None:
        request_row["status"] = "QUEUED"
        touch(request_row)
        if was_at_vendor:
            item = db.evidence_items.get(request_row["evidence_item_id"])
            if item is not None and item["custody_status"] == "IN_ANALYSIS":
                item["custody_status"] = "IN_VAULT"
                touch(item)
        case = db.cases.get(request_row["case_id"])
        if case is not None:
            S.case_recompute(case)
    return object_response(serialize.vendor_engagement(engagement), 200)
