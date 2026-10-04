"""Permit application routes."""
from datetime import timedelta

from flask import Blueprint, request

from db import store, now, fmt_dt, stamp_created, touch, parse_dt
from errors import (
    raise_err,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_INVALID_REQUEST,
    ERR_POSTURE_BLOCKED,
    ERR_PERMIT_FEE_OUTSTANDING,
    ERR_AM_REVIEW_EXPIRED,
    ERR_PERMIT_REVISION_SUPERSEDED,
    ERR_PLAN_REVISION_NOT_APPROVED,
    ERR_FORBIDDEN,
)
from middleware import require_roles, get_role, parse_pagination
from validate import body_dict, req_str, req_enum, req_int, opt_int
from response import success_object, success_list
import services

bp = Blueprint("permits", __name__)

CODE_PATHS = {"PRESCRIPTIVE", "ALTERNATIVE_MEANS"}


def _site_or_404(site_id):
    site = store.sites.get(site_id)
    if site is None:
        raise_err(ERR_NOT_FOUND, "site not found")
    services.lazy_eval_site(site)
    return site


@bp.post("/construction/sites/<site_id>/permit-applications")
def create_permit(site_id):
    require_roles("PermitCoordinator")
    site = _site_or_404(site_id)
    body = body_dict(request.get_json(silent=True))
    rev_id = req_str(body, "plan_revision_id")
    requested = req_enum(body, "requested_path", CODE_PATHS)
    if rev_id not in store.revisions:
        raise_err(ERR_NOT_FOUND, "plan revision not found")
    permit = stamp_created({
        "site_id": site_id,
        "plan_revision_id": rev_id,
        "requested_path": requested,
        "granted_path": None,
        "review_round": 0,
        "am_submitted_at": None,
        "am_decision_due_at": None,
        "fee_due_cents": 0,
        "fee_paid_cents": 0,
        "status": "DRAFT",
    })
    store.permits[permit["id"]] = permit
    return success_object(permit, status=201)


@bp.get("/construction/sites/<site_id>/permit-applications")
def list_permits(site_id):
    require_roles("PlatformAdmin", "SiteManager", "PermitCoordinator", "JurisdictionReviewer")
    _site_or_404(site_id)
    limit, offset = parse_pagination()
    apps = [p for p in store.permits.values() if p["site_id"] == site_id]
    status_filter = request.args.get("status")
    if status_filter:
        apps = [p for p in apps if p["status"] == status_filter]
    apps.sort(key=lambda p: p["created_at"])
    total = len(apps)
    return success_list(apps[offset:offset + limit], limit, offset, total)


@bp.get("/construction/sites/<site_id>/permit-applications/<app_id>")
def get_permit(site_id, app_id):
    require_roles("PlatformAdmin", "SiteManager", "PermitCoordinator", "JurisdictionReviewer")
    _site_or_404(site_id)
    permit = store.permits.get(app_id)
    if permit is None or permit["site_id"] != site_id:
        raise_err(ERR_NOT_FOUND, "permit application not found")
    services.lazy_eval_permit(permit)
    return success_object(permit)


def _stamp_am(permit, site):
    jur = store.jurisdictions.get(site["jurisdiction_id"])
    submitted = now()
    permit["am_submitted_at"] = fmt_dt(submitted)
    permit["am_decision_due_at"] = fmt_dt(
        submitted + timedelta(days=jur["alternative_means_review_days"])
    )


@bp.post("/construction/sites/<site_id>/permit-applications/<app_id>/action")
def permit_action(site_id, app_id):
    role = require_roles("PermitCoordinator", "JurisdictionReviewer")
    site = _site_or_404(site_id)
    permit = store.permits.get(app_id)
    if permit is None or permit["site_id"] != site_id:
        raise_err(ERR_NOT_FOUND, "permit application not found")
    services.lazy_eval_permit(permit)
    body = body_dict(request.get_json(silent=True))
    action = body.get("action")
    if not isinstance(action, str):
        raise_err(ERR_INVALID_REQUEST, "action is required")

    if action in ("SUBMIT", "PAY_FEE", "RESUBMIT", "WITHDRAW"):
        if role != "PermitCoordinator":
            _forbidden()
    if action == "DECIDE":
        if role != "JurisdictionReviewer":
            _forbidden()

    if action == "SUBMIT":
        return _submit(permit, site)
    if action == "PAY_FEE":
        return _pay_fee(permit, body)
    if action == "DECIDE":
        return _decide(permit, site, body)
    if action == "RESUBMIT":
        return _resubmit(permit, site)
    if action == "WITHDRAW":
        return _withdraw(permit)
    raise_err(ERR_INVALID_REQUEST, "unknown action %s" % action)


def _forbidden():
    raise_err(ERR_FORBIDDEN, "role not permitted for this action")


def _submit(permit, site):
    if permit["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, "permit must be DRAFT to submit")
    # priority 6: posture/jurisdiction gate for submissions
    if site["posture"] == "STOP":
        raise_err(ERR_POSTURE_BLOCKED, "site posture is STOP")
    rev = store.revisions.get(permit["plan_revision_id"])
    if rev is None:
        raise_err(ERR_NOT_FOUND, "plan revision not found")
    if rev["status"] == "VOIDED":
        raise_err(ERR_PERMIT_REVISION_SUPERSEDED, "referenced revision has been voided")
    if rev["status"] != "APPROVED":
        raise_err(ERR_PLAN_REVISION_NOT_APPROVED, "referenced revision is not APPROVED")
    jur = store.jurisdictions.get(site["jurisdiction_id"])
    if jur is None or jur["status"] != "ACTIVE":
        raise_err(ERR_POSTURE_BLOCKED, "jurisdiction is not ACTIVE")

    if permit["requested_path"] == "PRESCRIPTIVE" and jur["permits_prescriptive_printed_path"]:
        permit["status"] = "SUBMITTED"
        permit["fee_due_cents"] = services.permit_fee(permit, routed_to_am=False)
    else:
        permit["status"] = "AM_REVIEW"
        permit["fee_due_cents"] = services.permit_fee(permit, routed_to_am=True)
        _stamp_am(permit, site)
    touch(permit)
    services.recompute_posture(site["id"])
    return success_object(permit)


def _pay_fee(permit, body):
    if permit["status"] in ("WITHDRAWN", "DENIED", "APPROVED"):
        raise_err(ERR_INVALID_STATE, "cannot pay fee on a terminal application")
    amount = req_int(body, "amount_cents", minimum=1)
    permit["fee_paid_cents"] += amount
    touch(permit)
    return success_object(permit)


def _decide(permit, site, body):
    decision = body.get("decision")
    if decision not in ("APPROVE", "DENY"):
        raise_err(ERR_INVALID_REQUEST, "decision must be APPROVE or DENY")
    if (
        permit["status"] == "RESUBMIT_REQUIRED"
        and permit.get("am_expired_from_status") == "AM_REVIEW"
    ):
        if decision == "APPROVE":
            raise_err(ERR_AM_REVIEW_EXPIRED, "AM review decision deadline has passed")
    if permit["status"] not in ("SUBMITTED", "AM_REVIEW"):
        raise_err(ERR_INVALID_STATE, "permit is not decidable in status %s" % permit["status"])
    if decision == "APPROVE":
        if permit["status"] == "AM_REVIEW":
            if now() > parse_dt(permit["am_decision_due_at"]):
                raise_err(ERR_AM_REVIEW_EXPIRED, "AM review decision deadline has passed")
        if permit["fee_paid_cents"] < permit["fee_due_cents"]:
            raise_err(ERR_PERMIT_FEE_OUTSTANDING, "permit fee is not fully paid")
        permit["granted_path"] = (
            "PRESCRIPTIVE" if permit["status"] == "SUBMITTED" else "ALTERNATIVE_MEANS"
        )
        permit["status"] = "APPROVED"
    else:
        permit["status"] = "DENIED"
    touch(permit)
    services.recompute_posture(site["id"])
    return success_object(permit)


def _resubmit(permit, site):
    if permit["status"] != "RESUBMIT_REQUIRED":
        raise_err(ERR_INVALID_STATE, "permit must be RESUBMIT_REQUIRED to resubmit")
    if permit["review_round"] >= services.MAX_AM_REVIEW_ROUNDS:
        raise_err(ERR_INVALID_STATE, "maximum AM review rounds reached")
    permit["review_round"] += 1
    permit["fee_due_cents"] = services.permit_fee(permit, routed_to_am=True)
    _stamp_am(permit, site)
    permit["status"] = "AM_REVIEW"
    touch(permit)
    services.recompute_posture(site["id"])
    return success_object(permit)


def _withdraw(permit):
    if permit["status"] not in ("DRAFT", "SUBMITTED", "AM_REVIEW"):
        raise_err(ERR_INVALID_STATE, "permit cannot be withdrawn from %s" % permit["status"])
    permit["status"] = "WITHDRAWN"
    touch(permit)
    services.recompute_posture(permit["site_id"])
    return success_object(permit)
