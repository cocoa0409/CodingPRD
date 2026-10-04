"""True-up report and line endpoints."""
import flask

import db
from helpers import (err, success, get_json_body, require_fields, require_int,
                     require_enum, parse_pagination, list_response, stamp_new, touch)
from middleware import (authenticate, require_role, check_ownership,
                        authorize_agreement_path, scope_filter_for)
from services import (compute_position_lines, trueup_line_total, recompute_report_total,
                      current_unit_price_for, accrue_benefits)

bp = flask.Blueprint("trueup", __name__)
ALL = ("ProgramAdministrator", "LicensingSpecialist", "CustomerAdmin", "Auditor")


def _report_org_id(r):
    ag = db.agreements.get(r["agreement_id"])
    return ag["organization_id"] if ag else None


def _line_org_id(l):
    r = db.trueup_reports.get(l["report_id"])
    return _report_org_id(r) if r else None


def _get_report(rid):
    r = db.trueup_reports.get(rid)
    if r is None:
        err("ERR_NOT_FOUND", "True-up report not found.", 404)
    return r


def _new_snapshot(agreement_id, anniversary_id):
    snap = {
        "agreement_id": agreement_id,
        "anniversary_id": anniversary_id,
        "computed_at": db.now_iso(),
        "lines": compute_position_lines(agreement_id),
    }
    stamp_new(snap, with_version=False)
    db.snapshots[snap["id"]] = snap
    return snap


@bp.post("/licensing/agreements/<ag_id>/true-up-reports")
def create_report(ag_id):
    _, role, ag = authorize_agreement_path(("CustomerAdmin",), ag_id)
    if ag["status"] != "ACTIVE":
        err("ERR_AGREEMENT_NOT_ACTIVE", "Agreement must be ACTIVE.", 409)
    body = get_json_body()
    require_fields(body, ["anniversary_id"])
    ann = db.anniversaries.get(body["anniversary_id"])
    if ann is None:
        err("ERR_NOT_FOUND", "Anniversary not found.", 404)
    if ann["agreement_id"] != ag["id"]:
        err("ERR_NOT_FOUND", "Anniversary does not belong to this agreement.", 404)
    if ann["true_up_closed"]:
        err("ERR_ANNIVERSARY_CLOSED", "The anniversary's true-up is closed.", 409)
    for r in db.trueup_reports.values():
        if (r["agreement_id"] == ag["id"] and r["anniversary_id"] == ann["id"]
                and r["status"] != "REJECTED"):
            err("ERR_DUPLICATE_TRUE_UP",
                "A non-REJECTED true-up report already exists for this anniversary.", 409)
    snap = _new_snapshot(ag["id"], ann["id"])
    report = {
        "agreement_id": ag["id"],
        "anniversary_id": ann["id"],
        "status": "DRAFT",
        "snapshot_id": snap["id"],
        "total_amount_cents": 0,
        "revision_count": 0,
    }
    stamp_new(report, with_version=True)
    db.trueup_reports[report["id"]] = report
    return success(report, status=201, response_type="object")


@bp.get("/licensing/true-up-reports/<rid>")
def get_report(rid):
    user_id, role = authenticate()
    require_role(role, ALL)
    report = _get_report(rid)
    check_ownership(user_id, role, _report_org_id(report))
    return success(report, status=200, response_type="object")


@bp.get("/licensing/agreements/<ag_id>/true-up-reports")
def list_agreement_reports(ag_id):
    _, role, ag = authorize_agreement_path(ALL, ag_id)
    limit, offset = parse_pagination()
    items = [r for r in db.trueup_reports.values() if r["agreement_id"] == ag["id"]]
    status = flask.request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    return list_response(items, limit, offset)


@bp.get("/licensing/true-up-reports")
def flat_list_reports():
    user_id, role = authenticate()
    require_role(role, ALL)
    limit, offset = parse_pagination()
    items = list(db.trueup_reports.values())
    aid = flask.request.args.get("agreement_id")
    if aid is not None:
        items = [r for r in items if r["agreement_id"] == aid]
    ann = flask.request.args.get("anniversary_id")
    if ann is not None:
        items = [r for r in items if r["anniversary_id"] == ann]
    items = scope_filter_for(role, user_id, items, _report_org_id)
    return list_response(items, limit, offset)


@bp.post("/licensing/true-up-reports/<rid>/lines")
def add_line(rid):
    user_id, role = authenticate()
    require_role(role, ("CustomerAdmin",))
    report = _get_report(rid)
    check_ownership(user_id, role, _report_org_id(report))
    if report["status"] != "DRAFT":
        err("ERR_INVALID_STATE", "Lines can only be added to a DRAFT report.", 409)
    body = get_json_body()
    require_fields(body, ["product_id", "months_growth", "pricing_variant"])
    product = db.products.get(body["product_id"])
    if product is None:
        err("ERR_NOT_FOUND", "Product not found.", 404)
    months_growth = require_int(body, "months_growth")
    if not (1 <= months_growth <= 12):
        err("ERR_MONTHS_OUT_OF_RANGE", "months_growth must be within 1..12.", 422)
    pricing_variant = require_enum(body, "pricing_variant",
                                   ("ANNIVERSARY_PRORATION", "FULL_YEAR_RETROACTIVE"))
    snap = db.snapshots.get(report["snapshot_id"])
    growth = 0
    for l in snap["lines"]:
        if l["product_id"] == product["id"]:
            growth = max(0, l["required_licenses"] - l["entitled_quantity"])
            break
    ag = db.agreements.get(report["agreement_id"])
    unit_price = current_unit_price_for(ag, product)
    total = trueup_line_total(growth, unit_price, months_growth, pricing_variant)
    line = {
        "report_id": report["id"],
        "product_id": product["id"],
        "growth_quantity": growth,
        "months_growth": months_growth,
        "pricing_variant": pricing_variant,
        "unit_price_cents": unit_price,
        "total_amount_cents": total,
    }
    stamp_new(line, with_version=True)
    db.trueup_lines[line["id"]] = line
    recompute_report_total(report)
    touch(report)
    return success(line, status=201, response_type="object")


@bp.get("/licensing/true-up-reports/<rid>/lines")
def list_report_lines(rid):
    user_id, role = authenticate()
    require_role(role, ALL)
    report = _get_report(rid)
    check_ownership(user_id, role, _report_org_id(report))
    limit, offset = parse_pagination()
    items = [l for l in db.trueup_lines.values() if l["report_id"] == rid]
    return list_response(items, limit, offset)


@bp.get("/licensing/true-up-lines/<lid>")
def get_line(lid):
    user_id, role = authenticate()
    require_role(role, ALL)
    line = db.trueup_lines.get(lid)
    if line is None:
        err("ERR_NOT_FOUND", "True-up line not found.", 404)
    check_ownership(user_id, role, _line_org_id(line))
    return success(line, status=200, response_type="object")


@bp.get("/licensing/true-up-lines")
def flat_list_lines():
    user_id, role = authenticate()
    require_role(role, ALL)
    limit, offset = parse_pagination()
    items = list(db.trueup_lines.values())
    rid = flask.request.args.get("report_id")
    if rid is not None:
        items = [l for l in items if l["report_id"] == rid]
    pid = flask.request.args.get("product_id")
    if pid is not None:
        items = [l for l in items if l["product_id"] == pid]
    items = scope_filter_for(role, user_id, items, _line_org_id)
    return list_response(items, limit, offset)
