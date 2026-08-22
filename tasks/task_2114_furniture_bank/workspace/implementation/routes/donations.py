"""Donation offers, the acceptance criteria, pickup booking, warehouse intake
and the quarantine protocol (PRD 3.4, 3.5), plus warehouse stock reads.
"""

from decimal import Decimal

from flask import Blueprint

from auth import authenticate, resolve
from core import CATEGORIES, COUNTIES, GRADES_ABCD, clock
from db import db, new_entity, serialize, touch, items_of_offer
from envelope import object_response
from errors import ApiError
from routes._common import filtered, respond_list
from services.calc import run_triage
from services.donations import (
    perform_intake, release_quarantine, truck_window_conflict,
)
from validation import (
    Field, pagination_params, require_window, validate_body,
)

bp = Blueprint("donations", __name__)


@bp.route("/donation-offers", methods=["POST"])
def create_donation_offer():
    authenticate(["IntakeCoordinator"])
    payload = validate_body([
        Field("donor_name", "string", min_length=1),
        Field("donor_phone", "string", min_length=1),
        Field("pickup_county", "enum", members=COUNTIES),
        Field("pickup_window_start", "datetime"),
        Field("pickup_window_end", "datetime"),
        Field("items", "object_array", non_empty_array=True, item_fields=[
            Field("category", "enum", members=CATEGORIES),
            Field("declared_condition", "enum", members=GRADES_ABCD),
            Field("soft_surface", "boolean"),
            Field("cubic_feet", "number", exclusive_minimum=0, maximum=200),
        ]),
    ])
    require_window(payload, "pickup_window_start", "pickup_window_end")

    offer = new_entity(
        donor_name=payload["donor_name"],
        donor_phone=payload["donor_phone"],
        pickup_county=payload["pickup_county"],
        pickup_window_start=payload["pickup_window_start"],
        pickup_window_end=payload["pickup_window_end"],
        truck_id=None,
        status="OFFERED",
        accepted_item_count=0,
        rejected_item_count=0,
        declared_soft_ratio=Decimal("0.000"),
        bed_bug_risk_score=Decimal("0.0"),
        inspector_user_id=None,
        quarantine_started_at=None,
        quarantine_release_due_at=None,
    )
    db.donation_offers[offer["id"]] = offer
    for element in payload["items"]:
        item = new_entity(
            offer_id=offer["id"],
            category=element["category"],
            declared_condition=element["declared_condition"],
            soft_surface=bool(element["soft_surface"]),
            cubic_feet=element["cubic_feet"],
            decision="PENDING",
            reject_reason=None,
            graded_condition=None,
        )
        db.donation_items[item["id"]] = item
    return object_response(serialize(offer), 201)


@bp.route("/donation-offers/<offer_id>", methods=["GET"])
def get_donation_offer(offer_id):
    authenticate(["IntakeCoordinator", "WarehouseLead", "PlatformAdmin"])
    offer = resolve("offer", offer_id)
    return object_response(serialize(offer))


@bp.route("/donation-offers", methods=["GET"])
def list_donation_offers():
    authenticate(["IntakeCoordinator", "WarehouseLead", "PlatformAdmin"])
    limit, offset = pagination_params()
    rows = filtered(list(db.donation_offers.values()), {
        "status": "status",
        "truck_id": "truck_id",
        "pickup_county": "pickup_county",
    })
    return respond_list(rows, limit, offset)


@bp.route("/donation-offers/<offer_id>/items", methods=["GET"])
def list_donation_items(offer_id):
    authenticate(["IntakeCoordinator", "WarehouseLead", "PlatformAdmin"])
    limit, offset = pagination_params()
    offer = resolve("offer", offer_id)
    rows = filtered(items_of_offer(offer["id"]), {"decision": "decision"})
    return respond_list(rows, limit, offset)


@bp.route("/donation-offers/<offer_id>/triage", methods=["POST"])
def triage_offer(offer_id):
    authenticate(["IntakeCoordinator"])
    validate_body([])
    offer = resolve("offer", offer_id)

    # (11) state gate
    if offer["status"] != "OFFERED":
        raise ApiError("ERR_OFFER_INVALID_STATE",
                       "Only an OFFERED donation offer may be triaged.")

    items = items_of_offer(offer["id"])
    soft_ratio, accepted, rejected, risk = run_triage(offer, items)
    offer["declared_soft_ratio"] = soft_ratio
    offer["accepted_item_count"] = accepted
    offer["rejected_item_count"] = rejected
    offer["bed_bug_risk_score"] = risk
    offer["status"] = "TRIAGED" if accepted >= 1 else "REJECTED"
    touch(offer)
    return object_response(serialize(offer))


@bp.route("/donation-offers/<offer_id>/schedule-pickup", methods=["POST"])
def schedule_pickup(offer_id):
    authenticate(["IntakeCoordinator"])
    payload = validate_body([Field("truck_id", "string")])
    offer = resolve("offer", offer_id)
    truck = resolve("truck", payload["truck_id"])

    # (11) state gate
    if offer["status"] != "TRIAGED":
        raise ApiError("ERR_OFFER_INVALID_STATE",
                       "Only a TRIAGED offer may have a pickup booked.")
    # (15) truck bed-bug lockout
    lockout = truck["bed_bug_lockout_until"]
    if lockout is not None and lockout > offer["pickup_window_start"]:
        raise ApiError("ERR_TRUCK_BED_BUG_LOCKOUT",
                       "The truck is locked out of service for that window.")
    # (18) truck resource window
    if truck_window_conflict(truck["id"], offer["pickup_window_start"],
                             offer["pickup_window_end"], exclude_offer_id=offer["id"]):
        raise ApiError("ERR_TRUCK_WINDOW_CONFLICT",
                       "The truck is already committed inside that window.")

    offer["truck_id"] = truck["id"]
    offer["status"] = "PICKUP_SCHEDULED"
    touch(offer)
    return object_response(serialize(offer))


@bp.route("/donation-offers/<offer_id>/intake", methods=["POST"])
def offer_intake(offer_id):
    actor = authenticate(["WarehouseLead"])
    payload = validate_body([
        Field("inspections", "object_array", item_fields=[
            Field("item_id", "string"),
            Field("graded_condition", "enum", members=GRADES_ABCD),
            Field("live_pest_observed", "boolean"),
        ]),
    ])
    offer = resolve("offer", offer_id)

    # (11) state gate
    if offer["status"] != "PICKUP_SCHEDULED":
        raise ApiError("ERR_OFFER_INVALID_STATE",
                       "An inspection is only accepted while the offer is PICKUP_SCHEDULED.")

    # The array must cover exactly the ACCEPTED pieces of this offer.
    accepted_ids = set(i["id"] for i in items_of_offer(offer["id"])
                       if i["decision"] == "ACCEPTED")
    supplied = [insp["item_id"] for insp in payload["inspections"]]
    if len(set(supplied)) != len(supplied) or set(supplied) != accepted_ids:
        raise ApiError("ERR_VALIDATION",
                       "`inspections` must cover exactly the ACCEPTED pieces of this offer.")

    perform_intake(offer, payload["inspections"], actor.user_id)
    return object_response(serialize(offer))


@bp.route("/donation-offers/<offer_id>/quarantine-release", methods=["POST"])
def quarantine_release(offer_id):
    actor = authenticate(["WarehouseLead"])
    validate_body([])
    offer = resolve("offer", offer_id)

    # (9) segregation of duties
    if offer["inspector_user_id"] is not None and offer["inspector_user_id"] == actor.user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The lead who inspected this offer may not release it.")
    # (11) state gate
    if offer["status"] != "QUARANTINED":
        raise ApiError("ERR_OFFER_INVALID_STATE",
                       "Only a QUARANTINED offer may be released.")
    # (16) quarantine dwell
    due = offer["quarantine_release_due_at"]
    if due is not None and clock.now() < due:
        raise ApiError("ERR_QUARANTINE_NOT_ELAPSED",
                       "The quarantine dwell period has not elapsed.")

    release_quarantine(offer)
    return object_response(serialize(offer))


# --------------------------------------------------------------------------
# Warehouse stock
# --------------------------------------------------------------------------
@bp.route("/inventory-items/<item_id>", methods=["GET"])
def get_inventory_item(item_id):
    authenticate(["WarehouseLead", "PlatformAdmin", "DispatchPlanner"])
    unit = resolve("inventory_item", item_id)
    return object_response(serialize(unit))


@bp.route("/inventory-items", methods=["GET"])
def list_inventory_items():
    authenticate(["WarehouseLead", "PlatformAdmin", "DispatchPlanner"])
    limit, offset = pagination_params()
    rows = filtered(list(db.inventory_items.values()), {
        "status": "status",
        "category": "category",
        "condition": "condition",
        "donation_item_id": "donation_item_id",
        "reserved_for_voucher_line_id": "reserved_for_voucher_line_id",
    })
    return respond_list(rows, limit, offset)
