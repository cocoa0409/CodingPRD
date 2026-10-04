"""Routes: bonded period reports (open/reconcile/file/accept/reject/amend)
and the platform logical clock."""

from flask import Blueprint, request

import calc
import envelope
import serializers
import store
import validation as v

bp = Blueprint("reports", __name__)


def _get_report_or_404(rid):
    report = store.reports.get(rid)
    if report is None:
        raise envelope.err_not_found("Bonded period report not found")
    return report


@bp.route("/barrel-aging/bonded-reports", methods=["POST"])
def create_report():
    _, role = v.authenticate()
    v.require_role(role, ["BondedPreparer"])
    body = v.get_body()
    v.check_allowed_fields(body, {"period_start", "period_end"})
    ps = v.req_datetime(body, "period_start")
    pe = v.req_datetime(body, "period_end")
    if not (ps < pe):
        raise envelope.err_validation("period_start must be strictly before period_end")

    # Gate 7 compliance: no overlap with any non-REJECTED report; adjacency
    # (period_start == other period_end) is allowed.
    for other in store.reports.values():
        if other["state"] == "REJECTED":
            continue
        if ps < other["period_end"] and other["period_start"] < pe:
            raise envelope.err_period_overlap()

    now = store.now()
    report = {
        "id": store.new_id(),
        "period_start": ps,
        "period_end": pe,
        "opening_inventory_liters": None,
        "period_fills_liters": None,
        "period_withdrawals_liters": None,
        "loss_actual_liters": None,
        "loss_statutory_liters": None,
        "reported_loss_liters": None,
        "closing_inventory_liters": None,
        "state": "OPEN",
        "prepared_by_user_id": None,
        "filed_by_user_id": None,
        "decided_by_user_id": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.reports[report["id"]] = report
    return envelope.ok_object(serializers.serialize_report(report), status=201)


@bp.route("/barrel-aging/bonded-reports/<rid>", methods=["GET"])
def get_report(rid):
    _, role = v.authenticate()
    v.require_role(role, v.ALL_ROLES)
    return envelope.ok_object(serializers.serialize_report(_get_report_or_404(rid)))


@bp.route("/barrel-aging/bonded-reports", methods=["GET"])
def list_reports():
    _, role = v.authenticate()
    v.require_role(role, v.ALL_ROLES)
    limit, offset = v.parse_pagination()
    state_filter = request.args.get("state")
    items = []
    for rep in sorted(store.reports.values(), key=lambda r: (r["created_at"], r["_seq"])):
        if state_filter is not None and rep["state"] != state_filter:
            continue
        items.append(serializers.serialize_report(rep))
    page, total = v.paginate(items, limit, offset)
    return envelope.ok_list(page, limit, offset, total)


@bp.route("/barrel-aging/bonded-reports/<rid>/reconcile", methods=["POST"])
def reconcile_report(rid):
    user_id, role = v.authenticate()
    v.require_role(role, ["BondedPreparer"])
    body = v.get_body()
    v.check_allowed_fields(body, set())
    report = _get_report_or_404(rid)

    if report["state"] != "OPEN":
        raise envelope.err_invalid_state("Report is not OPEN")
    if store.now() < report["period_end"]:
        raise envelope.err_invalid_state("Report period has not closed")

    figures = calc.compute_report_figures(report)
    report.update(figures)
    report["state"] = "RECONCILED"
    report["prepared_by_user_id"] = user_id
    report["version"] += 1
    report["updated_at"] = store.now()
    return envelope.ok_object(serializers.serialize_report(report))


@bp.route("/barrel-aging/bonded-reports/<rid>/file", methods=["POST"])
def file_report(rid):
    user_id, role = v.authenticate()
    v.require_role(role, ["BondedPreparer"])
    body = v.get_body()
    v.check_allowed_fields(body, set())
    report = _get_report_or_404(rid)
    if report["state"] not in ("RECONCILED", "AMENDED"):
        raise envelope.err_invalid_state("Report is not RECONCILED or AMENDED")
    report["state"] = "FILED"
    report["filed_by_user_id"] = user_id
    report["version"] += 1
    report["updated_at"] = store.now()
    return envelope.ok_object(serializers.serialize_report(report))


@bp.route("/barrel-aging/bonded-reports/<rid>/accept", methods=["POST"])
def accept_report(rid):
    return _decide(rid, "ACCEPTED")


@bp.route("/barrel-aging/bonded-reports/<rid>/reject", methods=["POST"])
def reject_report(rid):
    return _decide(rid, "REJECTED")


def _decide(rid, target):
    user_id, role = v.authenticate()
    v.require_role(role, ["ComplianceOfficer"])
    body = v.get_body()
    v.check_allowed_fields(body, set())
    report = _get_report_or_404(rid)
    if report["state"] != "FILED":
        raise envelope.err_invalid_state("Report is not FILED")
    # Segregation of duties: the decider must differ from the filer.
    if user_id == report["filed_by_user_id"]:
        raise envelope.err_segregation()
    report["state"] = target
    report["decided_by_user_id"] = user_id
    report["version"] += 1
    report["updated_at"] = store.now()
    return envelope.ok_object(serializers.serialize_report(report))


@bp.route("/barrel-aging/bonded-reports/<rid>/amend", methods=["POST"])
def amend_report(rid):
    _, role = v.authenticate()
    v.require_role(role, ["BondedPreparer"])
    body = v.get_body()
    v.check_allowed_fields(body, set())
    report = _get_report_or_404(rid)
    if report["state"] != "REJECTED":
        raise envelope.err_invalid_state("Report is not REJECTED")
    report["state"] = "AMENDED"
    report["version"] += 1
    report["updated_at"] = store.now()
    return envelope.ok_object(serializers.serialize_report(report))


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = v.authenticate()
    v.require_role(role, ["PlatformAdmin"])
    body = v.get_body()
    v.check_allowed_fields(body, {"to_iso8601"})
    target = v.req_datetime(body, "to_iso8601")
    if target < store.now():
        raise envelope.err_clock_regression()
    store.set_clock(target)
    calc.refresh_all()
    return envelope.ok_object({"current_utc": store.fmt_ts(store.now())})
