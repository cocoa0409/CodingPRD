"""ServiceProvider endpoints."""
from flask import Blueprint

import db
from auth import require_roles
from errors import err
from lookups import get_sp
from response import ok_list, ok_object
from util import body_json, make_record, touch

bp = Blueprint("service_providers", __name__)

READ_ROLES = ("MLCAdministrator", "ServiceProviderUser", "MemberUser", "PublicSearcher")
ADMIN = ("MLCAdministrator",)


def sp_view(sp):
    return {k: v for k, v in sp.items() if not k.startswith("_")}


@bp.route("/mlc/service-providers", methods=["POST"])
@require_roles(*ADMIN)
def create_sp(_user_id, _role):
    body = body_json(required=("legal_name",))
    rec = make_record()
    rec.update({
        "legal_name": body["legal_name"],
        "participation_status": "PENDING",
        "accepted_rate_schedule_version": 0,
        "audit_credits": 0,
    })
    db.service_providers[rec["id"]] = rec
    return ok_object(sp_view(rec), 201)


@bp.route("/mlc/service-providers", methods=["GET"])
@require_roles(*READ_ROLES)
def list_sps(_user_id, _role):
    items = sorted(db.service_providers.values(), key=lambda r: r["created_at"])
    status = None
    from flask import request
    status = request.args.get("participation_status")
    if status:
        items = [s for s in items if s["participation_status"] == status]
    return ok_list([sp_view(s) for s in items])


@bp.route("/mlc/service-providers/<sp_id>", methods=["GET"])
@require_roles(*READ_ROLES)
def get_one_sp(sp_id, _user_id, _role):
    return ok_object(sp_view(get_sp(sp_id)))


@bp.route("/mlc/service-providers/<sp_id>/activate", methods=["POST"])
@require_roles(*ADMIN)
def activate_sp(sp_id, _user_id, _role):
    sp = get_sp(sp_id)
    if sp["participation_status"] != "PENDING":
        raise err("ERR_INVALID_STATE")
    active_sched = next(
        (s for s in db.rate_schedules.values() if s["status"] == "ACTIVE"), None)
    sp["participation_status"] = "ACTIVE"
    sp["accepted_rate_schedule_version"] = (
        active_sched["version"] if active_sched else 0)
    touch(sp)
    return ok_object(sp_view(sp))


@bp.route("/mlc/service-providers/<sp_id>/suspend", methods=["POST"])
@require_roles(*ADMIN)
def suspend_sp(sp_id, _user_id, _role):
    sp = get_sp(sp_id)
    if sp["participation_status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE")
    has_open = any(
        r["service_provider_id"] == sp_id and r["status"] in ("SUBMITTED", "UNDER_AUDIT")
        for r in db.usage_reports.values())
    if not has_open:
        raise err("ERR_DSP_NOT_SUSPENDABLE")
    sp["participation_status"] = "SUSPENDED"
    touch(sp)
    return ok_object(sp_view(sp))


@bp.route("/mlc/service-providers/<sp_id>/reinstate", methods=["POST"])
@require_roles(*ADMIN)
def reinstate_sp(sp_id, _user_id, _role):
    sp = get_sp(sp_id)
    if sp["participation_status"] != "SUSPENDED":
        raise err("ERR_INVALID_STATE")
    sp["participation_status"] = "ACTIVE"
    touch(sp)
    return ok_object(sp_view(sp))


@bp.route("/mlc/service-providers/<sp_id>/terminate", methods=["POST"])
@require_roles(*ADMIN)
def terminate_sp(sp_id, _user_id, _role):
    sp = get_sp(sp_id)
    if sp["participation_status"] not in ("ACTIVE", "SUSPENDED"):
        raise err("ERR_INVALID_STATE")
    open_reports = any(
        r["service_provider_id"] == sp_id and r["status"] in ("SUBMITTED", "UNDER_AUDIT")
        for r in db.usage_reports.values())
    if open_reports:
        raise err("ERR_DSP_HAS_OPEN_REPORTS")
    open_audits = any(
        a["service_provider_id"] == sp_id and a["status"] in ("OPEN", "FINDINGS_ISSUED")
        for a in db.audits.values())
    if open_audits:
        raise err("ERR_AUDIT_IN_PROGRESS")
    sp["participation_status"] = "TERMINATED"
    touch(sp)
    return ok_object(sp_view(sp))


@bp.route("/mlc/service-providers/<sp_id>/usage-reports", methods=["GET"])
@require_roles("MLCAdministrator", "ServiceProviderUser")
def list_sp_reports(sp_id, _user_id, _role):
    get_sp(sp_id)
    from flask import request
    items = sorted(
        (r for r in db.usage_reports.values() if r["service_provider_id"] == sp_id),
        key=lambda r: r["created_at"])
    status = request.args.get("status")
    if status:
        items = [r for r in items if r["status"] == status]
    from routes.usage import report_view
    return ok_list([report_view(r) for r in items])


@bp.route("/mlc/service-providers/<sp_id>/audits", methods=["GET"])
@require_roles("MLCAdministrator", "MemberUser")
def list_sp_audits(sp_id, _user_id, _role):
    get_sp(sp_id)
    from flask import request
    items = sorted(
        (a for a in db.audits.values() if a["service_provider_id"] == sp_id),
        key=lambda a: a["created_at"])
    status = request.args.get("status")
    if status:
        items = [a for a in items if a["status"] == status]
    from routes.audits import audit_view
    return ok_list([audit_view(a) for a in items])
