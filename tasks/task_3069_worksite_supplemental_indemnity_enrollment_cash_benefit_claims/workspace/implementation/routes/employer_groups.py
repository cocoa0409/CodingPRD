"""Employer group endpoints."""
from flask import Blueprint, request

import db
import errors as E
import services
from middleware import require_role
from response import success_object, success_list
from serializers import employer_group, employee, enrollment_campaign, payroll_cycle
from util import get_body, get_or_404, list_response, pagination_params

bp = Blueprint("employer_groups", __name__)

STORE = db.STORES["employer_groups"]


@bp.route("/employer-groups", methods=["POST"])
def create(role, user_id):
    require_role(role, {"CarrierAdmin"})
    body = get_body(["name", "group_code"])
    pct = body.get("participation_minimum_pct", 0.10)
    pmc = body.get("participation_minimum_count", 3)
    conv = body.get("proration_convention", "DAILY")
    if conv not in ("DAILY", "HALF_MONTH"):
        raise E.err(E.ERR_INVALID_REQUEST, "proration_convention must be DAILY or HALF_MONTH")
    if not isinstance(pct, (int, float)) or isinstance(pct, bool):
        raise E.err(E.ERR_INVALID_REQUEST, "participation_minimum_pct must be a number")
    if not isinstance(pmc, int) or isinstance(pmc, bool):
        raise E.err(E.ERR_INVALID_REQUEST, "participation_minimum_count must be an integer")
    # uniqueness of group_code
    for g in STORE.values():
        if g["group_code"] == body["group_code"]:
            raise E.err(E.ERR_INVALID_REQUEST, "group_code must be unique")
    rec = db.stamp_created({
        "name": body["name"],
        "group_code": body["group_code"],
        "status": "PROSPECT",
        "participation_minimum_pct": pct,
        "participation_minimum_count": pmc,
        "proration_convention": conv,
    })
    STORE[rec["id"]] = rec
    return success_object(employer_group(rec), status=201)


@bp.route("/employer-groups/<rid>", methods=["GET"])
def get_one(role, user_id, rid):
    require_role(role, {"CarrierAdmin", "GroupAdmin", "BenefitCounselor"})
    rec = get_or_404(STORE, rid)
    return success_object(employer_group(rec))


@bp.route("/employer-groups", methods=["GET"])
def list_all(role, user_id):
    require_role(role, {"CarrierAdmin", "GroupAdmin", "BenefitCounselor"})
    filters = {"status": request.args.get("status")}
    return list_response(STORE, filters, employer_group)


def _transition(rid, allowed_from, target, cascade=None, extra_checks=None):
    rec = get_or_404(STORE, rid)
    if extra_checks:
        extra_checks(rec)
    if rec["status"] not in allowed_from:
        raise E.err(E.ERR_INVALID_STATE, f"Cannot transition from {rec['status']}")
    rec["status"] = target
    db.touch(rec)
    if cascade:
        cascade(rec)
    return success_object(employer_group(rec))


@bp.route("/employer-groups/<rid>/activate", methods=["POST"])
def activate(role, user_id, rid):
    require_role(role, {"CarrierAdmin"})

    def check(rec):
        pct = rec.get("participation_minimum_pct", 0.10)
        pmc = rec.get("participation_minimum_count", 3)
        if not (0 <= pct <= 1) or pmc < 0:
            raise E.err(E.ERR_INVALID_REQUEST, "participation minimums out of range")

    return _transition(rid, {"PROSPECT", "SUSPENDED"}, "ACTIVE", extra_checks=check)


@bp.route("/employer-groups/<rid>/suspend", methods=["POST"])
def suspend(role, user_id, rid):
    require_role(role, {"CarrierAdmin"})
    return _transition(rid, {"ACTIVE"}, "SUSPENDED", cascade=services.group_suspend_cascade)


@bp.route("/employer-groups/<rid>/terminate", methods=["POST"])
def terminate(role, user_id, rid):
    require_role(role, {"CarrierAdmin"})

    def check(rec):
        if rec["status"] == "ACTIVE":
            for c in db.STORES["enrollment_campaigns"].values():
                if c["employer_group_id"] == rec["id"] and c["status"] == "OPEN":
                    raise E.err(E.ERR_INVALID_STATE, "Group has OPEN campaigns")

    return _transition(
        rid, {"ACTIVE", "SUSPENDED"}, "TERMINATED",
        cascade=services.group_terminate_cascade, extra_checks=check,
    )


# --- nested listings ---

@bp.route("/employer-groups/<rid>/employees", methods=["GET"])
def list_employees(role, user_id, rid):
    require_role(role, {"CarrierAdmin", "GroupAdmin", "BenefitCounselor"})
    get_or_404(STORE, rid)
    store = db.STORES["employees"]
    filters = {
        "employer_group_id": rid,
        "status": request.args.get("status"),
    }
    return list_response(store, filters, employee)


@bp.route("/employer-groups/<rid>/enrollment-campaigns", methods=["GET"])
def list_campaigns(role, user_id, rid):
    require_role(role, {"CarrierAdmin", "GroupAdmin", "BenefitCounselor"})
    get_or_404(STORE, rid)
    store = db.STORES["enrollment_campaigns"]
    filters = {
        "employer_group_id": rid,
        "status": request.args.get("status"),
    }
    return list_response(store, filters, enrollment_campaign)


@bp.route("/employer-groups/<rid>/payroll-cycles", methods=["GET"])
def list_cycles(role, user_id, rid):
    require_role(role, {"CarrierAdmin", "GroupAdmin"})
    get_or_404(STORE, rid)
    store = db.STORES["payroll_cycles"]
    filters = {
        "employer_group_id": rid,
        "status": request.args.get("status"),
    }
    return list_response(store, filters, payroll_cycle)
