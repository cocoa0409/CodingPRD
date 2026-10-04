"""Specialty pharmacy pathway and its pool (PRD 3.7)."""

from flask import request

from body import body, opt, require
from bp import api
from db import db
from errors import APIError
from helpers import (
    bundle_of_preauth,
    recompute_bundle,
)
from calculations import pharmacy_pool_allocation
from listing import apply_filters, ordered, paginate
from lookups import check_occ, preauthorization as preauth_lookup
from middleware import resolve_actor
from response import ok, created
from serializers import serialize


@api.route("/medication-orders", methods=["POST"])
def create_medication_order():
    resolve_actor()
    data = body()
    member_id = require(data, "member_id")
    preauth_id = require(data, "preauthorization_id")
    medication_code = require(data, "medication_code")
    specialty_drug = bool(opt(data, "specialty_drug", False))
    quantity = opt(data, "quantity", 0)
    days_supply = opt(data, "days_supply", 0)
    acquisition_cost_cents = opt(data, "acquisition_cost_cents", 0)
    dispensing_pharmacy = opt(data, "dispensing_pharmacy")

    member = db.find("members", member_id)
    if member is None:
        raise APIError("ERR_NOT_FOUND", "The member_id does not resolve.")
    pa = db.find("preauthorizations", preauth_id)
    if pa is None:
        raise APIError("ERR_NOT_FOUND", "The preauthorization_id does not resolve.")

    row = db.common()
    row.update({
        "_collection": "medication_orders",
        "member_id": member_id,
        "care_advocate_id": member.get("care_advocate_id"),
        "preauthorization_id": preauth_id,
        "medication_code": medication_code,
        "specialty_drug": specialty_drug,
        "quantity": quantity,
        "days_supply": days_supply,
        "acquisition_cost_cents": acquisition_cost_cents,
        "dispensing_pharmacy": dispensing_pharmacy,
        "pharmacy_status": "PRESCRIBED",
        "plan_paid_cents": 0,
        "member_cost_cents": 0,
        "dispensed_on": None,
    })
    db.add(row)
    return created(serialize("medication_orders", row))


@api.route("/medication-orders/<order_id>", methods=["GET"])
def get_medication_order(order_id):
    resolve_actor()
    row = db.find("medication_orders", order_id)
    if row is None:
        raise APIError("ERR_NOT_FOUND", "The medication order does not resolve.")
    return ok(serialize("medication_orders", row))


@api.route("/medication-orders", methods=["GET"])
def list_medication_orders():
    resolve_actor()
    rows = ordered(db.all("medication_orders"))
    rows = apply_filters(rows, {
        "member_id": "member_id",
        "care_advocate_id": "care_advocate_id",
        "preauthorization_id": "preauthorization_id",
        "pharmacy_status": "pharmacy_status",
    })
    return paginate(rows, "medication_orders")


@api.route("/medication-orders/<order_id>/dispense", methods=["POST"])
def dispense(order_id):
    resolve_actor()
    order = db.find("medication_orders", order_id)
    if order is None:
        raise APIError("ERR_NOT_FOUND", "The medication order does not resolve.")

    # Priority 5: the declared-state rule.
    if order["pharmacy_status"] != "PRESCRIBED":
        raise APIError("ERR_INVALID_STATE", "The order is not PRESCRIBED.")

    pa = preauth_lookup(order["preauthorization_id"])
    if pa["review_status"] != "APPROVED":
        raise APIError("ERR_INVALID_STATE", "The order's authorization is not APPROVED.")

    bundle = bundle_of_preauth(db, pa)

    data = request.get_json(silent=True) or {}
    expected = data.get("expected_bundle_entitlement_version")
    if expected is None:
        raise APIError("ERR_INVALID_REQUEST",
                       "The required input 'expected_bundle_entitlement_version' is missing.")
    check_occ(expected, bundle["version"], "ERR_BUNDLE_VERSION_STALE",
              "The entitlement's version has advanced since it was observed.")

    # Priority 9: the clinic's contract must not be frozen for this authorization.
    plan = db.find("treatment_plans", pa["treatment_plan_id"])
    if plan is not None and plan.get("clinic_id"):
        from routes.cycles import _covering_contract
        contract = _covering_contract(plan["clinic_id"])
        if contract is not None and contract["contracting_status"] == "FROZEN":
            raise APIError("ERR_CLINIC_CONTRACT_FROZEN", "The clinic's active contract is FROZEN.")

    # Priority 13: a pool of exactly zero admits nothing.
    if bundle["pharmacy_remaining_cents"] < 1:
        raise APIError("ERR_PHARMACY_POOL_EXHAUSTED", "The bundle's pharmacy pool holds no cents.")

    plan_paid, member_cost, claimable = pharmacy_pool_allocation(
        db, order, bundle["pharmacy_remaining_cents"]
    )

    order["plan_paid_cents"] = plan_paid
    order["member_cost_cents"] = member_cost
    order["pharmacy_status"] = "DISPENSING"
    order["dispensed_on"] = db.now()
    db.touch(order)

    bundle["pharmacy_consumed_cents"] = (bundle.get("pharmacy_consumed_cents") or 0) + claimable
    recompute_bundle(db, bundle)
    return ok(serialize("medication_orders", order))


@api.route("/medication-orders/<order_id>/ship", methods=["POST"])
def ship(order_id):
    resolve_actor()
    order = db.find("medication_orders", order_id)
    if order is None:
        raise APIError("ERR_NOT_FOUND", "The medication order does not resolve.")
    if order["pharmacy_status"] != "DISPENSING":
        raise APIError("ERR_INVALID_STATE", "The order is not DISPENSING.")
    order["pharmacy_status"] = "DISPENSED"
    db.touch(order)
    return ok(serialize("medication_orders", order))


@api.route("/medication-orders/<order_id>/deliver", methods=["POST"])
def deliver(order_id):
    resolve_actor()
    order = db.find("medication_orders", order_id)
    if order is None:
        raise APIError("ERR_NOT_FOUND", "The medication order does not resolve.")
    if order["pharmacy_status"] not in ("DISPENSED", "SHIPPED"):
        raise APIError("ERR_INVALID_STATE", "The order is not DISPENSED or SHIPPED.")

    order["pharmacy_status"] = "DELIVERED"
    db.touch(order)

    # The member-share charge converts into a MEDICATION claim in RECEIVED,
    # billed at the order's own member_cost_cents.
    from calculations import member_accumulator_before, member_cost_share

    pa = db.find("preauthorizations", order["preauthorization_id"])
    plan_paid = order.get("plan_paid_cents") or 0
    allowed = plan_paid
    accumulator = member_accumulator_before(db, order["member_id"])
    provisional = member_cost_share(
        allowed,
        pa.get("member_cost_share_pct", 0) if pa else 0,
        accumulator,
        "MEDICATION",
        "PROVISIONAL",
    )

    claim = db.common()
    claim.update({
        "_collection": "claims",
        "_service_date": db.now(),
        "member_id": order["member_id"],
        "preauthorization_id": order["preauthorization_id"],
        "treatment_cycle_id": None,
        "service_category": "MEDICATION",
        "billed_cents": order["member_cost_cents"],
        "claim_status": "RECEIVED",
        "allowed_cents": 0,
        "member_cost_share_cents": provisional,
        "plan_paid_cents": 0,
        "member_accumulator_before_cents": accumulator,
        "member_accumulator_after_cents": accumulator,
        "adjudication_basis": None,
        "pended_reason": None,
    })
    db.add(claim)
    return ok(serialize("medication_orders", order))


@api.route("/medication-orders/<order_id>/cancel", methods=["POST"])
def cancel_order(order_id):
    resolve_actor()
    order = db.find("medication_orders", order_id)
    if order is None:
        raise APIError("ERR_NOT_FOUND", "The medication order does not resolve.")
    if order["pharmacy_status"] not in ("PRESCRIBED", "DISPENSING"):
        raise APIError("ERR_INVALID_STATE", "The order may not be cancelled from its current state.")

    released = 0
    if order["pharmacy_status"] == "DISPENSING":
        released = order.get("plan_paid_cents") or 0

    order["pharmacy_status"] = "CANCELLED"
    order["plan_paid_cents"] = 0
    order["member_cost_cents"] = 0
    db.touch(order)

    pa = db.find("preauthorizations", order["preauthorization_id"])
    if pa is not None:
        bundle = bundle_of_preauth(db, pa)
        if bundle is not None and released:
            bundle["pharmacy_consumed_cents"] = max(0, (bundle.get("pharmacy_consumed_cents") or 0) - released)
        if bundle is not None:
            recompute_bundle(db, bundle)
    return ok(serialize("medication_orders", order))