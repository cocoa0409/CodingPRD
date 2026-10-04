"""PrescriberOptOut endpoints."""

from flask import Blueprint

from db import db
from errors import (
    err_not_found,
    err_opt_out_invalid_state,
    err_prescriber_not_active,
)
from middleware import require_role, ALL_ROLES
from response import success_object
from services.calculations import recall_delivery
from services.common import touch

bp = Blueprint("opt_outs", __name__)


def _get_opt_out(oid):
    opt_out = db.opt_outs.get(oid)
    if opt_out is None:
        raise err_not_found("Opt-out not found")
    return opt_out


@bp.route("/prescriber-opt-outs/<oid>", methods=["GET"])
def get_opt_out(oid):
    require_role(ALL_ROLES)
    return success_object(_get_opt_out(oid))


@bp.route("/prescriber-opt-outs/<oid>/verify", methods=["POST"])
def verify_opt_out(oid):
    require_role(["PrivacyOfficer"])
    opt_out = _get_opt_out(oid)
    if opt_out["status"] != "SUBMITTED":
        raise err_opt_out_invalid_state("Opt-out must be SUBMITTED to verify")
    if db.prescribers[opt_out["prescriber_id"]]["status"] != "ACTIVE":
        raise err_prescriber_not_active()
    opt_out["status"] = "VERIFIED"
    touch(opt_out)
    return success_object(opt_out)


@bp.route("/prescriber-opt-outs/<oid>/activate", methods=["POST"])
def activate_opt_out(oid):
    require_role(["PrivacyOfficer"])
    opt_out = _get_opt_out(oid)
    if opt_out["status"] != "VERIFIED":
        raise err_opt_out_invalid_state("Opt-out must be VERIFIED to activate")
    if db.prescribers[opt_out["prescriber_id"]]["status"] != "ACTIVE":
        raise err_prescriber_not_active()
    opt_out["status"] = "ACTIVE"
    touch(opt_out)
    prescriber_id = opt_out["prescriber_id"]
    # Link 1: decrement deliverable count on ACTIVE products containing the prescriber.
    affected_products = []
    for product in sorted(db.products.values(), key=lambda p: p["created_at"]):
        if product["status"] == "ACTIVE" and prescriber_id in product["prescriber_ids"]:
            product["deliverable_prescriber_count"] -= 1
            touch(product)
            affected_products.append(product)
    # Link 2: recall COMPILED deliveries of those products containing the prescriber.
    affected_ids = {p["id"] for p in affected_products}
    for delivery in sorted(db.deliveries.values(), key=lambda d: d["created_at"]):
        period = db.periods[delivery["period_id"]]
        if (
            period["product_id"] in affected_ids
            and delivery["status"] == "COMPILED"
            and prescriber_id in delivery["included_prescriber_ids"]
        ):
            recall_delivery(delivery)
    return success_object(opt_out)


@bp.route("/prescriber-opt-outs/<oid>/reject", methods=["POST"])
def reject_opt_out(oid):
    require_role(["PrivacyOfficer"])
    opt_out = _get_opt_out(oid)
    if opt_out["status"] not in ("SUBMITTED", "VERIFIED"):
        raise err_opt_out_invalid_state("Opt-out must be SUBMITTED or VERIFIED to reject")
    opt_out["status"] = "REJECTED"
    touch(opt_out)
    return success_object(opt_out)


@bp.route("/prescriber-opt-outs/<oid>/lift", methods=["POST"])
def lift_opt_out(oid):
    require_role(["PrivacyOfficer"])
    opt_out = _get_opt_out(oid)
    if opt_out["status"] != "ACTIVE":
        raise err_opt_out_invalid_state("Opt-out must be ACTIVE to lift")
    opt_out["status"] = "LIFTED"
    touch(opt_out)
    prescriber_id = opt_out["prescriber_id"]
    for product in sorted(db.products.values(), key=lambda p: p["created_at"]):
        if prescriber_id in product["prescriber_ids"]:
            product["deliverable_prescriber_count"] += 1
            touch(product)
    return success_object(opt_out)
