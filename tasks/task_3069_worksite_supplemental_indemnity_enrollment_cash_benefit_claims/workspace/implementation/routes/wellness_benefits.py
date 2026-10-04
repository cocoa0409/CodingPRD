"""Wellness benefit endpoints."""
from flask import Blueprint, request

import db
import errors as E
from middleware import require_role
from response import success_object
from serializers import wellness_benefit
from util import add_months, get_body, get_or_404, list_response, parse_iso

bp = Blueprint("wellness_benefits", __name__)

STORE = db.STORES["wellness_benefits"]


@bp.route("/wellness-benefits", methods=["POST"])
def create(role, user_id):
    require_role(role, {"PolicyholderServices", "ClaimsAdjuster"})
    body = get_body(["policy_id", "calendar_year", "service_date"])
    policy = db.STORES["policies"].get(body["policy_id"])
    if policy is None:
        raise E.err(E.ERR_REFERENTIAL_INTEGRITY, "policy_id does not exist")
    cy = body["calendar_year"]
    if not isinstance(cy, int) or isinstance(cy, bool):
        raise E.err(E.ERR_INVALID_REQUEST, "calendar_year must be an integer")
    sd = parse_iso(body["service_date"], "service_date")
    rec = db.stamp_created({
        "policy_id": policy["id"],
        "calendar_year": cy,
        "service_date": db.format_ts(sd),
        "amount_cents": None,
        "status": "SUBMITTED",
    })
    STORE[rec["id"]] = rec
    return success_object(wellness_benefit(rec), status=201)


@bp.route("/wellness-benefits/<rid>", methods=["GET"])
def get_one(role, user_id, rid):
    require_role(role, {"CarrierAdmin", "ClaimsAdjuster", "PolicyholderServices"})
    rec = get_or_404(STORE, rid)
    return success_object(wellness_benefit(rec))


@bp.route("/wellness-benefits", methods=["GET"])
def list_all(role, user_id):
    require_role(role, {"CarrierAdmin", "ClaimsAdjuster", "PolicyholderServices"})
    cy = request.args.get("calendar_year")
    filters = {
        "policy_id": request.args.get("policy_id"),
        "status": request.args.get("status"),
    }
    if cy is not None:
        filters["calendar_year"] = cy
    return list_response(STORE, filters, wellness_benefit)


@bp.route("/wellness-benefits/<rid>/approve", methods=["POST"])
def approve(role, user_id, rid):
    require_role(role, {"ClaimsAdjuster"})
    rec = get_or_404(STORE, rid)
    if rec["status"] != "SUBMITTED":
        raise E.err(E.ERR_INVALID_STATE, f"Cannot approve from {rec['status']}")
    policy = db.STORES["policies"][rec["policy_id"]]
    if policy["status"] not in ("ACTIVE", "LAPSED", "PORTED"):
        raise E.err(E.ERR_POLICY_INACTIVE, "Policy is not in an approvable status")
    schedule = db.STORES["benefit_schedules"][policy["benefit_schedule_id"]]
    service_dt = parse_iso(rec["service_date"])
    waiting_end = add_months(parse_iso(policy["coverage_start_date"]), schedule["wellness_waiting_months"])
    if service_dt < waiting_end:
        raise E.err(E.ERR_WELLNESS_WAITING_PERIOD, "Service date before waiting period end")
    if service_dt.year != rec["calendar_year"]:
        raise E.err(E.ERR_INVALID_REQUEST, "service_date year does not match calendar_year")
    for w in STORE.values():
        if (
            w["id"] != rec["id"]
            and w["policy_id"] == rec["policy_id"]
            and w["calendar_year"] == rec["calendar_year"]
            and w["status"] in ("SUBMITTED", "APPROVED", "PAID")
        ):
            raise E.err(E.ERR_WELLNESS_DUPLICATE_YEAR, "Duplicate wellness benefit for this calendar year")
    rec["amount_cents"] = schedule["wellness_benefit_cents"]
    rec["status"] = "APPROVED"
    db.touch(rec)
    return success_object(wellness_benefit(rec))


@bp.route("/wellness-benefits/<rid>/deny", methods=["POST"])
def deny(role, user_id, rid):
    require_role(role, {"ClaimsAdjuster"})
    rec = get_or_404(STORE, rid)
    if rec["status"] != "SUBMITTED":
        raise E.err(E.ERR_INVALID_STATE, f"Cannot deny from {rec['status']}")
    rec["status"] = "DENIED"
    db.touch(rec)
    return success_object(wellness_benefit(rec))


@bp.route("/wellness-benefits/<rid>/pay", methods=["POST"])
def pay(role, user_id, rid):
    require_role(role, {"ClaimsAdjuster"})
    rec = get_or_404(STORE, rid)
    if rec["status"] != "APPROVED":
        raise E.err(E.ERR_INVALID_STATE, f"Cannot pay from {rec['status']}")
    rec["status"] = "PAID"
    db.touch(rec)
    return success_object(wellness_benefit(rec))
