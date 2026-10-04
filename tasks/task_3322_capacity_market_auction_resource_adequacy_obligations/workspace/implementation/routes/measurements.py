"""Measurement reports and settlement entries routes."""
from flask import Blueprint, request

from db import db
from middleware import require_roles, require_any
from response import success_object, success_list
from util import (base_entity, touch, dec, require_fields, is_number, get_body,
                  strip_internal, paginate, sort_created, parse_dt)
from errors import (err_not_found, err_invalid_request, err_invalid_state,
                    err_invalid_time_range, err_ownership, err_owner_suspended,
                    err_measurement_not_applicable, err_measurement_overlap)
from services.calcs import mv_verified_ucap

bp = Blueprint("measurements", __name__)


def _serialize(m):
    return strip_internal(m)


def _serialize_entry(e):
    return strip_internal(e)


@bp.route("/capacity-market/measurement-reports", methods=["POST"])
def create_report():
    user_id, role = require_roles("ResourceOwner")
    body = get_body()
    require_fields(body, ["resource_id", "delivery_year_id", "reporting_period_start",
                          "reporting_period_end", "metered_mwh", "baseline_mwh"])
    resource = db.resources.get(body["resource_id"])
    if resource is None:
        raise err_not_found("resource not found")
    dy = db.delivery_years.get(body["delivery_year_id"])
    if dy is None:
        raise err_not_found("delivery year not found")
    revision_of_id = body.get("revision_of_id")
    prior = None
    if revision_of_id is not None:
        prior = db.measurement_reports.get(revision_of_id)
        if prior is None:
            raise err_not_found("revision_of_id report not found")

    if user_id != resource["owner_id"]:
        raise err_ownership()
    owner = db.owners.get(resource["owner_id"])
    if owner and owner["status"] == "SUSPENDED":
        raise err_owner_suspended()

    # GEN may not submit
    if resource["resource_type"] == "GEN":
        raise err_measurement_not_applicable()

    start = parse_dt(body["reporting_period_start"], "reporting_period_start")
    end = parse_dt(body["reporting_period_end"], "reporting_period_end")
    if end <= start:
        raise err_invalid_time_range("reporting_period_end must be after reporting_period_start")

    metered = body["metered_mwh"]
    baseline = body["baseline_mwh"]
    if not is_number(metered) or dec(metered) < 0:
        raise err_invalid_request("metered_mwh must be >= 0")
    if not is_number(baseline) or dec(baseline) <= 0:
        raise err_invalid_request("baseline_mwh must be > 0")

    # revision handling
    if prior is not None:
        if prior["status"] != "REJECTED":
            raise err_invalid_state("revision_of_id must reference a REJECTED report")
        # a revision's window must not overlap any VERIFIED report for the resource
        for other in db.measurement_reports.values():
            if other["resource_id"] != resource["id"] or other["status"] != "VERIFIED":
                continue
            if start < other["_end_dt"] and other["_start_dt"] < end:
                raise err_measurement_overlap()

    r = base_entity()
    r.update({
        "resource_id": resource["id"],
        "delivery_year_id": dy["id"],
        "reporting_period_start": body["reporting_period_start"],
        "reporting_period_end": body["reporting_period_end"],
        "metered_mwh": dec(metered),
        "baseline_mwh": dec(baseline),
        "verified_ucap_mw": None,
        "revision_of_id": revision_of_id,
        "status": "SUBMITTED",
        "_start_dt": start,
        "_end_dt": end,
    })
    db.measurement_reports[r["id"]] = r
    return success_object(_serialize(r), 201)


@bp.route("/capacity-market/measurement-reports", methods=["GET"])
def list_reports():
    require_any()
    items = list(db.measurement_reports.values())
    for key in ("resource_id", "delivery_year_id", "revision_of_id", "status"):
        v = request.args.get(key)
        if v:
            items = [m for m in items if m.get(key) == v]
    items = sort_created(items)
    page, limit, offset, total = paginate(items, request.args)
    return success_list([_serialize(m) for m in page], limit, offset, total)


@bp.route("/capacity-market/measurement-reports/<rid>", methods=["GET"])
def get_report(rid):
    require_any()
    r = db.measurement_reports.get(rid)
    if r is None:
        raise err_not_found("measurement report not found")
    return success_object(_serialize(r))


@bp.route("/capacity-market/measurement-reports/<rid>/start-review", methods=["POST"])
def start_review(rid):
    require_roles("MarketAdmin")
    r = db.measurement_reports.get(rid)
    if r is None:
        raise err_not_found("measurement report not found")
    if r["status"] != "SUBMITTED":
        raise err_invalid_state("report is not SUBMITTED")
    r["status"] = "UNDER_REVIEW"
    touch(r)
    return success_object(_serialize(r))


@bp.route("/capacity-market/measurement-reports/<rid>/verify", methods=["POST"])
def verify_report(rid):
    require_roles("MarketAdmin")
    r = db.measurement_reports.get(rid)
    if r is None:
        raise err_not_found("measurement report not found")
    if r["status"] != "UNDER_REVIEW":
        raise err_invalid_state("report is not UNDER_REVIEW")
    resource = db.resources.get(r["resource_id"])
    if resource is None:
        raise err_not_found("resource not found")
    # window overlap vs VERIFIED reports for same resource
    for other in db.measurement_reports.values():
        if other["id"] == rid or other["resource_id"] != r["resource_id"]:
            continue
        if other["status"] != "VERIFIED":
            continue
        if r["_start_dt"] < other["_end_dt"] and other["_start_dt"] < r["_end_dt"]:
            raise err_measurement_overlap()
    r["verified_ucap_mw"] = mv_verified_ucap(r, resource)
    r["status"] = "VERIFIED"
    touch(r)
    # shortfall cascade: ACTIVE commitment in this DY and verified < committed -> must_offer true
    for c in db.commitments.values():
        if (c["resource_id"] == resource["id"]
                and c["delivery_year_id"] == r["delivery_year_id"]
                and c["status"] == "ACTIVE"):
            if dec(r["verified_ucap_mw"]) < dec(c["committed_mw"]):
                resource["must_offer"] = True
                touch(resource)
            break
    return success_object(_serialize(r))


@bp.route("/capacity-market/measurement-reports/<rid>/reject", methods=["POST"])
def reject_report(rid):
    require_roles("MarketAdmin")
    r = db.measurement_reports.get(rid)
    if r is None:
        raise err_not_found("measurement report not found")
    if r["status"] != "UNDER_REVIEW":
        raise err_invalid_state("report is not UNDER_REVIEW")
    r["status"] = "REJECTED"
    touch(r)
    return success_object(_serialize(r))


# ------------- Settlement entries -------------

@bp.route("/capacity-market/settlement-entries", methods=["GET"])
def list_entries():
    require_any()
    items = list(db.settlement_entries.values())
    for key in ("delivery_year_id", "commitment_id", "emergency_event_id", "entry_type"):
        v = request.args.get(key)
        if v:
            items = [e for e in items if e.get(key) == v]
    items = sort_created(items)
    page, limit, offset, total = paginate(items, request.args)
    return success_list([_serialize_entry(e) for e in page], limit, offset, total)


@bp.route("/capacity-market/settlement-entries/<eid>", methods=["GET"])
def get_entry(eid):
    require_any()
    e = db.settlement_entries.get(eid)
    if e is None:
        raise err_not_found("settlement entry not found")
    return success_object(_serialize_entry(e))
