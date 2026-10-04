"""Transparency report routes."""
from flask import Blueprint, request

from db import db, _parse_iso
from errors import (ApiError, ERR_INVALID_STATE, ERR_LEGAL_REQUESTS_PENDING)
from helpers import (base_entity, get_body, require_fields, list_response,
                     lookup, touch, check_occ, parse_datetime_field, iso)
from middleware import require_roles
from response import success_object

bp = Blueprint("transparency", __name__)

TERMINAL = {"COMPLIED", "REJECTED", "PARTIALLY_COMPLIED"}


@bp.post("/wiki/transparency-reports")
def create_report():
    require_roles("LegalCounsel")
    body = get_body()
    require_fields(body, ["period_start", "period_end"])
    start = parse_datetime_field(body["period_start"], "period_start")
    end = parse_datetime_field(body["period_end"], "period_end")
    r = base_entity()
    r.update({
        "period_start": iso(start),
        "period_end": iso(end),
        "total_requests": 0,
        "complied_count": 0,
        "rejected_count": 0,
        "status": "DRAFT",
    })
    db.transparency_reports[r["id"]] = r
    return success_object(r, status=201)


@bp.get("/wiki/transparency-reports")
def list_reports():
    require_roles("LegalCounsel", "Anonymous", "PlatformAdmin")
    return list_response(db.transparency_reports,
                         filters={"status": request.args.get("status")})


@bp.get("/wiki/transparency-reports/<reportId>")
def get_report(reportId):
    require_roles("LegalCounsel", "Anonymous")
    return success_object(lookup(db.transparency_reports, reportId,
                                 "Transparency report"))


@bp.post("/wiki/transparency-reports/<reportId>/publish")
def publish_report(reportId):
    require_roles("LegalCounsel")
    report = lookup(db.transparency_reports, reportId, "Transparency report")
    if report["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE,
                       "Only a DRAFT report can be published", 409)
    body = get_body()
    check_occ(body, "expected_report_version", report)
    start = _parse_iso(report["period_start"])
    end = _parse_iso(report["period_end"])
    in_period = [lr for lr in db.legal_requests.values()
                 if start <= _parse_iso(lr["received_at"]) < end]
    if any(lr["status"] not in TERMINAL for lr in in_period):
        raise ApiError(ERR_LEGAL_REQUESTS_PENDING,
                       "Legal requests in period not all terminal", 409)
    report["total_requests"] = len(in_period)
    report["complied_count"] = sum(
        1 for lr in in_period
        if lr["status"] in ("COMPLIED", "PARTIALLY_COMPLIED"))
    report["rejected_count"] = sum(
        1 for lr in in_period if lr["status"] == "REJECTED")
    report["status"] = "PUBLISHED"
    touch(report)
    for lr in in_period:
        lr["transparency_report_id"] = report["id"]
        touch(lr, bump_version=False)
    return success_object(report)
