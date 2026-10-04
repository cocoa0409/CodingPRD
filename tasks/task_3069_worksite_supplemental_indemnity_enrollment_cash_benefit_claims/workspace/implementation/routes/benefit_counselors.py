"""Benefit counselor endpoints."""
from flask import Blueprint, request

import db
import errors as E
from middleware import require_role
from response import success_object
from serializers import benefit_counselor, enrollment_campaign
from util import get_body, get_or_404, list_response

bp = Blueprint("benefit_counselors", __name__)

STORE = db.STORES["benefit_counselors"]


@bp.route("/benefit-counselors", methods=["POST"])
def create(role, user_id):
    require_role(role, {"CarrierAdmin"})
    body = get_body(["license_id", "full_name", "home_state"])
    for c in STORE.values():
        if c["license_id"] == body["license_id"]:
            raise E.err(E.ERR_INVALID_REQUEST, "license_id must be unique")
    rec = db.stamp_created({
        "license_id": body["license_id"],
        "full_name": body["full_name"],
        "home_state": body["home_state"],
        "status": "ACTIVE",
    })
    STORE[rec["id"]] = rec
    return success_object(benefit_counselor(rec), status=201)


@bp.route("/benefit-counselors/<rid>", methods=["GET"])
def get_one(role, user_id, rid):
    require_role(role, {"CarrierAdmin", "BenefitCounselor"})
    rec = get_or_404(STORE, rid)
    return success_object(benefit_counselor(rec))


def _transition(rid, allowed_from, target, extra_checks=None):
    rec = get_or_404(STORE, rid)
    if rec["status"] not in allowed_from:
        raise E.err(E.ERR_INVALID_STATE, f"Cannot transition from {rec['status']}")
    if extra_checks:
        extra_checks(rec)
    rec["status"] = target
    db.touch(rec)
    return success_object(benefit_counselor(rec))


@bp.route("/benefit-counselors/<rid>/suspend", methods=["POST"])
def suspend(role, user_id, rid):
    require_role(role, {"CarrierAdmin"})
    return _transition(rid, {"ACTIVE"}, "SUSPENDED")


@bp.route("/benefit-counselors/<rid>/activate", methods=["POST"])
def activate(role, user_id, rid):
    require_role(role, {"CarrierAdmin"})
    return _transition(rid, {"SUSPENDED"}, "ACTIVE")


@bp.route("/benefit-counselors/<rid>/terminate", methods=["POST"])
def terminate(role, user_id, rid):
    require_role(role, {"CarrierAdmin"})

    def check(rec):
        for c in db.STORES["enrollment_campaigns"].values():
            if c["counselor_id"] == rec["id"] and c["status"] == "OPEN":
                raise E.err(E.ERR_INVALID_STATE, "Counselor leads an OPEN campaign")

    return _transition(rid, {"ACTIVE", "SUSPENDED"}, "TERMINATED", extra_checks=check)


@bp.route("/benefit-counselors/<rid>/enrollment-campaigns", methods=["GET"])
def list_campaigns(role, user_id, rid):
    require_role(role, {"CarrierAdmin", "BenefitCounselor"})
    get_or_404(STORE, rid)
    store = db.STORES["enrollment_campaigns"]
    filters = {
        "counselor_id": rid,
        "status": request.args.get("status"),
    }
    return list_response(store, filters, enrollment_campaign)
