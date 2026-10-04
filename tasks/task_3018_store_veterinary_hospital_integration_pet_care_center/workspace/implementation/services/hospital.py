"""Veterinary encounters, prescriptions and the pharmacy counter (PRD §3.4 / §3.5)."""

from datetime import timedelta
from decimal import Decimal

import db
import domain
import validate
from errors import ApiError
from services import core


def pharmacy_held(store):
    hold = store["pharmacy_hold_until"]
    return hold is not None and db.now() <= hold


# ---------------------------------------------------------------------------
# encounters
# ---------------------------------------------------------------------------

def create_encounter(body, store_id):
    store = core.require_store(store_id)
    body = validate.shape(
        body,
        required=["pet_id", "clinician_name", "scheduled_at"],
        optional=["chief_complaint", "booking_id", "medical_notes"])
    pet = core.require_pet(body["pet_id"])
    booking = None
    if body.get("booking_id") is not None:
        booking = core.require_booking(body["booking_id"])
        if booking["pet_id"] != pet["id"]:
            raise ApiError("ERR_BOOKING_PET_MISMATCH")
    validate.check_backdating(store, pet)
    if booking is not None:
        validate.check_backdating(booking)
    # priority 4 — the hospital partition gate and the one-slot allowance
    if store["hospital_posture"] == "FROZEN":
        raise ApiError("ERR_STORE_HOSPITAL_FROZEN")
    occupancy = len([e for e in db.rows("encounters")
                     if e["store_id"] == store_id
                     and e["status"] in domain.ENCOUNTER_OCCUPANCY_STATES])
    if occupancy > store["hospital_capacity"]:
        raise ApiError("ERR_HOSPITAL_AT_CAPACITY")

    row = db.new_row()
    row.update({
        "pet_id": pet["id"], "store_id": store_id,
        "booking_id": booking["id"] if booking else None,
        "clinician_name": body["clinician_name"],
        "scheduled_at": db.parse_dt(body["scheduled_at"]),
        "chief_complaint": body.get("chief_complaint"),
        "exam_date": None, "medical_notes": body.get("medical_notes"),
        "charge_total_cents": 0, "status": "SCHEDULED",
    })
    db.add("encounters", row)
    core.refresh_store(store)
    return row


def check_in(body, store_id, encounter_id):
    store = core.require_store(store_id)
    encounter = core.require_encounter(encounter_id)
    if encounter["store_id"] != store_id:
        raise ApiError("ERR_ENCOUNTER_NOT_FOUND")
    body = validate.shape(body, required=["expected_encounter_version"], optional=[])
    validate.check_backdating(store, encounter)
    if encounter["status"] != "SCHEDULED":
        raise ApiError("ERR_ILLEGAL_STATE_TRANSITION")
    # priority 12 outranks priority 11: the hold is the broader prohibition
    if store["pharmacy_hold_until"] is not None and db.now() <= store["pharmacy_hold_until"]:
        raise ApiError("ERR_ENCOUNTER_BLOCKED_PHARMACY_HOLD")
    occupied = len([e for e in db.rows("encounters")
                    if e["store_id"] == store_id
                    and e["status"] in domain.ENCOUNTER_OCCUPIED_STATES])
    if occupied >= store["hospital_capacity"]:
        raise ApiError("ERR_HOSPITAL_AT_CAPACITY")
    validate.require_expected(body, encounter["version"], "expected_encounter_version")

    encounter["status"] = "CHECKED_IN"
    db.touch(encounter)
    pet = core.require_pet(encounter["pet_id"])
    if any(v["pet_id"] == pet["id"] and v["status"] == "BLOCKED"
           for v in db.rows("visits")):
        pet["status"] = "SUSPENDED"
        db.touch(pet)
    core.refresh_store(store)
    return encounter


def start_exam(body, store_id, encounter_id):
    store = core.require_store(store_id)
    encounter = core.require_encounter(encounter_id)
    if encounter["store_id"] != store_id:
        raise ApiError("ERR_ENCOUNTER_NOT_FOUND")
    body = validate.shape(body, required=["expected_encounter_version"], optional=[])
    validate.check_backdating(store, encounter)
    if encounter["status"] != "CHECKED_IN":
        raise ApiError("ERR_ENCOUNTER_NOT_CHECKED_IN")
    validate.require_expected(body, encounter["version"], "expected_encounter_version")
    encounter["status"] = "IN_EXAM"
    encounter["exam_date"] = db.now()
    db.touch(encounter)
    return encounter


def complete_exam(body, store_id, encounter_id):
    store = core.require_store(store_id)
    encounter = core.require_encounter(encounter_id)
    if encounter["store_id"] != store_id:
        raise ApiError("ERR_ENCOUNTER_NOT_FOUND")
    body = validate.shape(body, required=["expected_encounter_version"], optional=[])
    validate.check_backdating(store, encounter)
    if encounter["status"] != "IN_EXAM":
        raise ApiError("ERR_ENCOUNTER_NOT_IN_EXAM")
    validate.require_expected(body, encounter["version"], "expected_encounter_version")

    authorized_at = db.now()
    for auth in core.encounter_authorizations(encounter["id"]):
        if auth["status"] != "PENDING_EXAM":
            continue
        auth["status"] = "AUTHORIZED"
        auth["authorized_at"] = authorized_at
        auth["expires_at"] = authorized_at + timedelta(
            days=domain.ITEM_WINDOW_DAYS[auth["item_type"]])
        auth["price_at_authorization_cents"] = auth["unit_price_cents"] * auth["quantity"]
        db.touch(auth)
        for order in core.authorization_orders(auth["id"]):
            if order["status"] == "REQUESTED":
                if store["pharmacy_hold_until"] is None or db.now() > store["pharmacy_hold_until"]:
                    order["status"] = "AUTHORIZED"
                    if store["hospital_posture"] != "FROZEN":
                        order["on_hold"] = "NONE"
            order["current_retail_price_cents"] = auth["price_at_authorization_cents"]
            db.touch(order)

    encounter["status"] = "COMPLETED"
    encounter["charge_total_cents"] = _provisional_charge(encounter)
    db.touch(encounter)
    core.refresh_store(store)
    return encounter


def cancel_encounter(body, store_id, encounter_id):
    store = core.require_store(store_id)
    encounter = core.require_encounter(encounter_id)
    if encounter["store_id"] != store_id:
        raise ApiError("ERR_ENCOUNTER_NOT_FOUND")
    body = validate.shape(body, required=["expected_encounter_version"], optional=[])
    validate.check_backdating(store, encounter)
    if encounter["status"] not in ("SCHEDULED", "CHECKED_IN"):
        raise ApiError("ERR_ENCOUNTER_NOT_CANCELLABLE")
    validate.require_expected(body, encounter["version"], "expected_encounter_version")
    encounter["status"] = "CANCELLED"
    db.touch(encounter)
    for auth in core.encounter_authorizations(encounter["id"]):
        if auth["status"] in ("PENDING_EXAM", "AUTHORIZED"):
            auth["status"] = "REVOKED"
            db.touch(auth)
            _reject_outstanding_orders(store, auth)
    core.refresh_store(store)
    return encounter


def _reject_outstanding_orders(store, auth):
    for order in core.authorization_orders(auth["id"]):
        if order["status"] in ("REQUESTED", "AUTHORIZED"):
            order["status"] = "REJECTED"
            order["on_hold"] = "NONE"
            db.touch(order)


def _authorized_term(encounter):
    total = 0
    for auth in core.encounter_authorizations(encounter["id"]):
        if auth["status"] in ("AUTHORIZED", "PARTIALLY_DISPENSED"):
            total += auth["price_at_authorization_cents"]
    return total


def _dispensed_term(encounter):
    total = Decimal(0)
    for auth in core.encounter_authorizations(encounter["id"]):
        for order in core.authorization_orders(auth["id"]):
            if order["status"] == "DISPENSED":
                total += domain.round_half_up(
                    domain.dec(auth["unit_price_cents"]) * domain.dec(order["requested_quantity"]))
    return total


def _provisional_charge(encounter):
    return domain.EXAM_CHARGE_CENTS + _authorized_term(encounter)


def charge_summary(store_id, encounter_id):
    store = core.require_store(store_id)
    encounter = core.require_encounter(encounter_id)
    if encounter["store_id"] != store_id:
        raise ApiError("ERR_ENCOUNTER_NOT_FOUND")
    authorized = _authorized_term(encounter)
    dispensed = _dispensed_term(encounter)
    total = domain.EXAM_CHARGE_CENTS + authorized + int(dispensed)
    return {
        "exam_charge_cents": domain.EXAM_CHARGE_CENTS,
        "authorized_authorization_cents": authorized,
        "dispensed_pharmacy_cents": int(dispensed),
        "finalized_charge_total_cents": total,
    }


# ---------------------------------------------------------------------------
# prescriptions
# ---------------------------------------------------------------------------

def create_authorization(body, store_id):
    core.require_store(store_id)
    body = validate.shape(
        body,
        required=["pet_id", "encounter_id", "item_type", "item_name", "sku",
                  "unit_price_cents", "quantity"],
        optional=[])
    pet = core.require_pet(body["pet_id"])
    encounter = core.require_encounter(body["encounter_id"])
    if body["unit_price_cents"] < 0 or body["quantity"] < 1:
        raise ApiError("ERR_INVALID_REQUEST")
    validate.check_backdating(pet, encounter)
    # priority 13 — the prescription's pet must be the encounter's patient
    if encounter["pet_id"] != pet["id"]:
        raise ApiError("ERR_AUTHORIZATION_PET_MISMATCH")
    # priority 14 — the exam must have reached IN_EXAM or beyond
    if encounter["status"] not in ("IN_EXAM", "COMPLETED"):
        raise ApiError("ERR_UNDERLYING_EXAM_REQUIRED")

    row = db.new_row()
    row.update({
        "pet_id": pet["id"], "encounter_id": encounter["id"], "store_id": store_id,
        "item_type": body["item_type"], "item_name": body["item_name"],
        "sku": body["sku"], "unit_price_cents": int(body["unit_price_cents"]),
        "quantity": int(body["quantity"]), "authorized_at": None,
        "expires_at": None, "price_at_authorization_cents": 0,
        "retail_facing": True, "status": "PENDING_EXAM",
    })
    db.add("authorizations", row)
    return row


def revoke_authorization(body, store_id, authorization_id):
    store = core.require_store(store_id)
    auth = core.require_authorization(authorization_id)
    if auth["store_id"] != store_id:
        raise ApiError("ERR_AUTHORIZATION_NOT_FOUND")
    body = validate.shape(body, required=["expected_authorization_version"], optional=[])
    validate.check_backdating(store, auth)
    if auth["status"] not in ("AUTHORIZED", "PARTIALLY_DISPENSED"):
        raise ApiError("ERR_AUTHORIZATION_NOT_ACTIVE")
    validate.require_expected(body, auth["version"], "expected_authorization_version")
    auth["status"] = "REVOKED"
    db.touch(auth)
    for order in core.authorization_orders(auth["id"]):
        if order["status"] in ("REQUESTED", "AUTHORIZED"):
            order["status"] = "REJECTED"
            order["on_hold"] = "NONE"
            db.touch(order)
    core.recompute_stores_held(store)
    encounter = db.get("encounters", auth["encounter_id"])
    if encounter is not None:
        encounter["charge_total_cents"] = _provisional_charge(encounter)
        db.touch(encounter)
    return auth


def _remaining_quantity(auth):
    dispensed = sum(o["requested_quantity"] for o in core.authorization_orders(auth["id"])
                    if o["status"] == "DISPENSED")
    return auth["quantity"] - dispensed


def create_order(body, store_id):
    store = core.require_store(store_id)
    body = validate.shape(
        body,
        required=["authorization_id", "requested_quantity",
                  "expected_authorization_version"],
        optional=[])
    auth = core.require_authorization(body["authorization_id"])
    if auth["store_id"] != store_id:
        raise ApiError("ERR_AUTHORIZATION_NOT_FOUND")
    if body["requested_quantity"] < 1:
        raise ApiError("ERR_INVALID_REQUEST")
    validate.check_backdating(store, auth)
    if auth["status"] not in ("AUTHORIZED", "PARTIALLY_DISPENSED") \
            or (auth["expires_at"] is not None and db.now() > auth["expires_at"]):
        raise ApiError("ERR_AUTHORIZATION_NOT_ACTIVE")
    if pharmacy_held(store):
        raise ApiError("ERR_PHARMACY_HOLD_ACTIVE")
    if int(body["requested_quantity"]) > _remaining_quantity(auth):
        raise ApiError("ERR_QUANTITY_EXCEEDS_AUTHORIZATION")
    if "expected_authorization_version" not in body \
            or body["expected_authorization_version"] is None:
        raise ApiError("ERR_MISSING_EXPECTED_VERSION")
    if int(body["expected_authorization_version"]) != auth["version"]:
        raise ApiError("ERR_STALE_VERSION")

    row = db.new_row()
    row.update({
        "authorization_id": auth["id"], "store_id": store_id,
        "requested_quantity": int(body["requested_quantity"]),
        "on_hold": "HOLDING" if store["hospital_posture"] == "FROZEN" else "NONE",
        "status": "REQUESTED",
        "current_retail_price_cents": auth["price_at_authorization_cents"],
    })
    db.add("pharmacy_orders", row)
    db.touch(auth)
    # M8: the handoff is released on the strength of the live authorization
    row["status"] = "AUTHORIZED"
    if store["hospital_posture"] != "FROZEN":
        row["on_hold"] = "NONE"
    db.touch(row)
    core.recompute_stores_held(store)
    return row


def dispense_order(body, store_id, order_id):
    store = core.require_store(store_id)
    order = core.require_order(order_id)
    if order["store_id"] != store_id:
        raise ApiError("ERR_PHARMACY_ORDER_NOT_FOUND")
    body = validate.shape(body, required=["expected_order_version"], optional=[])
    validate.check_backdating(store, order)
    if order["status"] != "AUTHORIZED":
        raise ApiError("ERR_PHARMACY_ORDER_NOT_AUTHORIZED")
    auth = core.require_authorization(order["authorization_id"])
    if order["requested_quantity"] > _remaining_quantity(auth):
        raise ApiError("ERR_QUANTITY_EXCEEDS_AUTHORIZATION")
    if pharmacy_held(store):
        raise ApiError("ERR_PHARMACY_HOLD_ACTIVE")
    validate.require_expected(body, order["version"], "expected_order_version")

    order["status"] = "DISPENSED"
    db.touch(order)
    if order["requested_quantity"] < auth["quantity"]:
        auth["status"] = "PARTIALLY_DISPENSED"
    else:
        auth["status"] = "DISPENSED"
    db.touch(auth)
    order["current_retail_price_cents"] = auth["unit_price_cents"] * order["requested_quantity"]
    core.recompute_stores_held(store)
    return order


def reject_order(body, store_id, order_id):
    store = core.require_store(store_id)
    order = core.require_order(order_id)
    if order["store_id"] != store_id:
        raise ApiError("ERR_PHARMACY_ORDER_NOT_FOUND")
    body = validate.shape(body, required=["expected_order_version"], optional=[])
    validate.check_backdating(store, order)
    if order["status"] != "AUTHORIZED":
        raise ApiError("ERR_PHARMACY_ORDER_NOT_AUTHORIZED")
    validate.require_expected(body, order["version"], "expected_order_version")
    was_holding = order["on_hold"] == "HOLDING"
    order["status"] = "REJECTED"
    order["on_hold"] = "NONE"
    db.touch(order)
    auth = core.require_authorization(order["authorization_id"])
    # PRD §3.5: rejecting "returns the prescription's position: a prescription that
    # had been pushed to `PARTIALLY_DISPENSED` returns to `AUTHORIZED`". The
    # return is unconditional — nothing in the rule makes it depend on how many
    # orders of the prescription were dispensed.
    if auth["status"] == "PARTIALLY_DISPENSED":
        auth["status"] = "AUTHORIZED"
        db.touch(auth)
    if was_holding:
        core.recompute_stores_held(store)
    return order


def refresh_order_price(order):
    """PRD §3.5: the frozen price governs until the authorization is spent."""
    auth = db.get("authorizations", order["authorization_id"])
    if auth is None:
        return
    if auth["status"] == "DISPENSED":
        order["current_retail_price_cents"] = auth["unit_price_cents"] * order["requested_quantity"]
    else:
        order["current_retail_price_cents"] = auth["price_at_authorization_cents"]
    db.touch(order)