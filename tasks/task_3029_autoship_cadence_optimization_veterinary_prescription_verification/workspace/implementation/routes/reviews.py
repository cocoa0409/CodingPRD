"""Compassionate review endpoints."""

from flask import request

import db
import serializers
from errors import fail
from middleware import body
from routing import Arr, Obj, endpoint, resolve
from services import calculations, plans as plan_svc
from services.constants import REVIEW_OUTCOMES


@endpoint("/v1/compassionate-reviews/<review_id>/decide", ["POST"], ["CustomerService"])
def decide_review(caller, review_id):
    review = resolve(db.COMPASSIONATE_REVIEWS, review_id, "compassionate review")
    payload = body()

    if review.get("review_status") != "OPEN":
        fail("ERR_INVALID_STATE", "Only an OPEN review can be decided.")

    pet = db.PETS.get(review.get("pet_id"))
    if pet is None or pet.get("pet_status") != "PASSED":
        fail("ERR_INVALID_STATE", "The linked pet has not been reported as passed.")

    if caller.id == review.get("recorded_by"):
        fail(
            "ERR_SUBMITTER_CANNOT_AUTHORIZE",
            "The deciding identity must differ from the identity that recorded the passing.",
        )

    outcome = payload.get("outcome")
    if outcome not in REVIEW_OUTCOMES:
        fail("ERR_INVALID_REQUEST", "outcome must be APPROVED or REJECTED.")

    if outcome == "APPROVED":
        review["review_status"] = "APPROVED"
    else:
        review["review_status"] = "REJECTED"
        review["refunded_amount_cents"] = 0
    db.touch(review)

    # Either outcome cancels the parked shipment, releases its reservation and
    # settles its parked order: the order was "parked" on the passing, and the
    # decision is what settles it (SHIPPED -> CANCELED). Cancelling the order
    # first is what lets the approval's settlement find a CANCELED order to
    # write a refund onto.
    affected_id = review.get("affected_shipment_id")
    if affected_id:
        shipment = db.SHIPMENTS.get(affected_id)
        if shipment is not None and shipment.get("shipment_status") == "AWAITING_PET_PASSING_DECISION":
            shipment["shipment_status"] = "CANCELED"
            db.touch(shipment)
            plan_svc.release_shipment_reservations(shipment)
            order = db.ORDERS.get(shipment.get("order_id"))
            if order is not None and order.get("order_status") == "AWAITING_PET_PASSING_DECISION":
                order["order_status"] = "CANCELED"
                order["cancellation_reason"] = "PET_PASSED"
                db.touch(order)

    if outcome == "APPROVED":
        calculations.settle_orders_of_pet(review.get("pet_id"))
        review["refunded_amount_cents"] = calculations.review_refund_total(review.get("pet_id"))
        for plan in db.AUTOSHIP_PLANS.values():
            if plan.get("pet_id") == review.get("pet_id"):
                calculations.payment_settlement_net(plan)

    if pet is not None:
        pet["pet_lifecycle_state"] = serializers.pet_lifecycle_state(pet)

    return Obj(serializers.compassionate_review(review))


@endpoint(
    "/v1/compassionate-reviews",
    ["GET"],
    ["Customer", "CustomerService", "ComplianceOfficer"],
)
def list_reviews(caller, ):
    rows = db.ordered(db.COMPASSIONATE_REVIEWS.values())
    for key in ("pet_id", "affected_shipment_id", "review_status"):
        value = request.args.get(key)
        if value:
            rows = [r for r in rows if r.get(key) == value]
    if caller.is_customer:
        rows = [r for r in rows if r.get("pet_id") == caller.id]
    return Arr([serializers.compassionate_review(r) for r in rows])


@endpoint(
    "/v1/compassionate-reviews/<review_id>",
    ["GET"],
    ["Customer", "CustomerService", "ComplianceOfficer"],
)
def read_review(caller, review_id):
    review = resolve(db.COMPASSIONATE_REVIEWS, review_id, "compassionate review")
    if caller.is_customer and review.get("pet_id") != caller.id:
        fail("ERR_RESOURCE_NOT_FOUND", "No such review for this identity.")
    return Obj(serializers.compassionate_review(review))