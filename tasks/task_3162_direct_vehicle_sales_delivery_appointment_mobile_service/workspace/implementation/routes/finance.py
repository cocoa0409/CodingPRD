"""Trade-in appraisal and financing application routes."""

from flask import Blueprint, request

from db import DB
from errors import fail
from repository import find, get, matches, serialize
from response import list_response, object_response
from routes.common import (
    body, bool_field, check_version, int_field, paged, require_owner, text_field,
    counted,
)
from services import financing as financing_service

bp = Blueprint("finance", __name__)


@bp.get("/trade-in-appraisals")
def list_appraisals():
    rows = [r for r in DB.appraisals.values()
            if matches(request.args, "order_id", r["order_id"])
            and matches(request.args, "status", r["status"])]
    page, limit, offset, total = counted(rows)
    return list_response([serialize(r) for r in page], limit, offset,
                         total_count=total)


@bp.get("/trade-in-appraisals/<appraisal_id>")
def get_appraisal(appraisal_id):
    return object_response(serialize(get("appraisal", appraisal_id)))


@bp.get("/financing-applications")
def list_applications():
    rows = [r for r in DB.applications.values()
            if matches(request.args, "order_id", r["order_id"])
            and matches(request.args, "buyer_id", r["buyer_id"])
            and matches(request.args, "status", r["status"])]
    page, limit, offset, total = counted(rows)
    return list_response([serialize(r) for r in page], limit, offset,
                         total_count=total)


@bp.get("/financing-applications/<application_id>")
def get_application(application_id):
    return object_response(serialize(get("application", application_id)))


@bp.post("/financing-applications/<application_id>/decision")
def decide(application_id):
    application = get("application", application_id)
    payload = body()
    outcome = text_field(payload, "outcome")
    if outcome not in ("APPROVED", "DECLINED"):
        fail("ERR_INVALID_REQUEST", "outcome must be APPROVED or DECLINED.")
    return object_response(serialize(financing_service.decide(application, outcome)))


@bp.post("/financing-applications/<application_id>/contract-review")
def contract_review(application_id):
    application = get("application", application_id)
    payload = body()
    check_version(payload, "expected_application_version", application)
    return object_response(serialize(financing_service.contract_review(application)))


@bp.post("/financing-applications/<application_id>/fund")
def fund(application_id):
    application = get("application", application_id)
    payload = body()
    check_version(payload, "expected_application_version", application)
    return object_response(serialize(financing_service.fund(application)))