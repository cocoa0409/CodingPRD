"""ComplianceReport submission, listing, and review transitions."""
from flask import Blueprint, request

import envelope
import errors
import requtil
import store
from timeutil import parse_iso, seconds

bp = Blueprint("reports", __name__)

REPORT_STATES = {"SUBMITTED", "ACCEPTED", "DEFICIENT"}
REPORT_TARGET_ROLES = {
    "ACCEPTED": ["ComplianceMonitor"],
    "DEFICIENT": ["ComplianceMonitor"],
    "SUBMITTED": ["CompanyRepresentative"],
}
REPORT_TRANSITIONS = {
    "ACCEPTED": {"SUBMITTED"},
    "DEFICIENT": {"SUBMITTED"},
    "SUBMITTED": {"DEFICIENT"},
}


@bp.route("/enforcement/consent-orders/<orderId>/compliance-reports", methods=["POST"])
def submit_report(orderId):
    user_id, role = requtil.context()
    requtil.require_role(role, ["CompanyRepresentative"])
    order = requtil.get_or_404(
        store.db.consent_orders, orderId, "ERR_CONSENT_ORDER_NOT_FOUND", "ConsentOrder"
    )
    body = requtil.json_body()
    period_start = requtil.need_datetime(body, "period_start")
    period_end = requtil.need_datetime(body, "period_end")
    report_document_ref = requtil.need_str(body, "report_document_ref")
    start_dt = seconds(parse_iso(period_start))
    end_dt = seconds(parse_iso(period_end))
    if end_dt <= start_dt:
        errors.fail(
            "ERR_INVALID_REQUEST",
            "period_end must be strictly after period_start",
        )
    # Tier 5: reporting is permitted only while the order is IN_MONITORING.
    if order["status"] != "IN_MONITORING":
        errors.fail(
            "ERR_INVALID_STATE_TRANSITION",
            "Compliance reports are accepted only while the order is IN_MONITORING",
        )
    # Tier 10: closed-interval overlap — touching endpoints DO overlap.
    # DEFICIENT reports do not block resubmission of a corrected window.
    for other in store.db.compliance_reports.values():
        if (
            other["consent_order_id"] != order["id"]
            or other["status"] not in ("SUBMITTED", "ACCEPTED")
        ):
            continue
        other_start = seconds(parse_iso(other["period_start"]))
        other_end = seconds(parse_iso(other["period_end"]))
        if other_start <= end_dt and start_dt <= other_end:
            errors.fail(
                "ERR_REPORTING_PERIOD_OVERLAP",
                "The reporting window overlaps an existing SUBMITTED/ACCEPTED report",
            )
    # Tier 12: cross-entity referential integrity — checked AFTER the overlap rule.
    if user_id != order["subject_company_id"]:
        errors.fail(
            "ERR_REPORT_COMPANY_MISMATCH",
            "X-User-ID must equal the order's subject_company_id",
        )
    with store.db.lock:
        report = store.stamp_new(
            {
                "consent_order_id": order["id"],
                "submitted_by_company_id": user_id,
                "period_start": period_start,
                "period_end": period_end,
                "report_document_ref": report_document_ref,
                "status": "SUBMITTED",
                "deficiency_notes": None,
                "resubmission_count": 0,
                "reviewed_by_user_id": None,
            }
        )
        store.db.compliance_reports[report["id"]] = report
    return envelope.success(store.public(report), 201)


@bp.route("/enforcement/consent-orders/<orderId>/compliance-reports", methods=["GET"])
def list_reports(orderId):
    _user_id, role = requtil.context()
    requtil.require_role(role, requtil.ALL_ROLES)
    order = requtil.get_or_404(
        store.db.consent_orders, orderId, "ERR_CONSENT_ORDER_NOT_FOUND", "ConsentOrder"
    )
    limit, offset = requtil.page_params()
    items = [
        r
        for r in store.db.compliance_reports.values()
        if r["consent_order_id"] == order["id"]
    ]
    status_filter = request.args.get("status")
    if status_filter is not None:
        items = [r for r in items if r["status"] == status_filter]
    items.sort(key=lambda e: (parse_iso(e["created_at"]), e["_seq"]))
    total = len(items)
    page = [store.public(r) for r in items[offset:offset + limit]]
    return envelope.success_list(page, limit, offset, total)


@bp.route("/enforcement/compliance-reports/<reportId>/transition", methods=["POST"])
def transition_report(reportId):
    user_id, role = requtil.context()
    requtil.require_role(role, ["ComplianceMonitor", "CompanyRepresentative"])
    report = requtil.get_or_404(
        store.db.compliance_reports,
        reportId,
        "ERR_COMPLIANCE_REPORT_NOT_FOUND",
        "ComplianceReport",
    )
    body = requtil.json_body()
    target = requtil.need_enum(body, "target_state", REPORT_STATES)
    requtil.require_target_role(role, target, REPORT_TARGET_ROLES)
    deficiency_notes = None
    report_document_ref = None
    if target == "DEFICIENT":
        deficiency_notes = requtil.need_str(body, "deficiency_notes")
    if target == "SUBMITTED":
        report_document_ref = requtil.need_str(body, "report_document_ref")
    if target not in REPORT_TRANSITIONS or report["status"] not in REPORT_TRANSITIONS[target]:
        errors.fail(
            "ERR_INVALID_STATE_TRANSITION",
            "ComplianceReport cannot transition from {} to {}".format(
                report["status"], target
            ),
        )
    if target == "SUBMITTED":
        order = store.db.consent_orders.get(report["consent_order_id"])
        if order is None or user_id != order["subject_company_id"]:
            errors.fail(
                "ERR_SUBJECT_COMPANY_MISMATCH",
                "X-User-ID must equal the order's subject company id",
            )
    with store.db.lock:
        report["status"] = target
        if target in ("ACCEPTED", "DEFICIENT"):
            report["reviewed_by_user_id"] = user_id
        if target == "DEFICIENT":
            report["deficiency_notes"] = deficiency_notes
        if target == "SUBMITTED":
            report["resubmission_count"] += 1
            report["deficiency_notes"] = None
            report["report_document_ref"] = report_document_ref
        store.touch(report)
    return envelope.success(store.public(report), 200)
