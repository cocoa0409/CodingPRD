"""Defect report endpoints: list and disposition (PRD 3.5)."""
from flask import Blueprint, request

import calc
import domain
import envelope
import serialize
import store
from authz import ALL_ROLES, authenticate, authorize
from errors import err
from validate import paginate_params, parse_body, validate

bp = Blueprint("defects", __name__)


@bp.route("/foundry/defect-reports", methods=["GET"])
def list_reports():
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    limit, offset = paginate_params()
    items = list(store.db["reports"].values())
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    return envelope.list_payload(items, serialize.defect_report, limit, offset)


@bp.route("/foundry/defect-reports/<rid>/disposition", methods=["POST"])
def disposition_report(rid):
    uid, role = authenticate()
    authorize(role, ["QualityInspector"])
    vals = validate(
        parse_body(),
        [{"name": "disposition", "kind": "enum", "values": ["REWORK", "SCRAP", "USE_AS_IS"]}],
    )
    report = domain.get_or_404("reports", rid)
    if report["status"] != "OPEN":
        raise err("ERR_INVALID_STATE_TRANSITION", "report is not OPEN")
    unit = store.db["units"][report["casting_unit_id"]]
    disposition = vals["disposition"]

    if disposition == "REWORK":
        if report["severity"] == "CRITICAL":
            raise err("ERR_CRITICAL_DEFECT_MUST_SCRAP", "critical defects must be scrapped")
        if unit["rework_count"] >= calc.MAX_REWORK_COUNT:
            raise err("ERR_REWORK_LIMIT_EXCEEDED", "unit already has 2 rework dispositions")
        report["status"] = "DISPOSITIONED"
        report["disposition"] = "REWORK"
        report["dispositioned_by"] = uid
        store.touch(report)
        unit["rework_count"] += 1
        unit["state"] = "REWORK"
        store.touch(unit)
        return envelope.success(serialize.defect_report(report))

    if disposition == "USE_AS_IS":
        if report["severity"] != "MINOR":
            raise err("ERR_USE_AS_IS_MINOR_ONLY", "USE_AS_IS requires severity MINOR")
        report["status"] = "DISPOSITIONED"
        report["disposition"] = "USE_AS_IS"
        report["dispositioned_by"] = uid
        store.touch(report)
        domain.mark_unit_finished(unit)
        return envelope.success(serialize.defect_report(report))

    # disposition == SCRAP
    domain.defect_scrap(unit, report, uid)
    return envelope.success(serialize.defect_report(report))
