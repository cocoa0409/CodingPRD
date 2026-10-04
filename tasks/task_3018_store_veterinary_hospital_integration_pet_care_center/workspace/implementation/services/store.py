"""Stores, members, pets, breed rules, bays, cross-sells and the logical clock."""

import db
import domain
import validate
from errors import ApiError
from services import core


# ---------------------------------------------------------------------------
# stores
# ---------------------------------------------------------------------------

def create_store(body):
    body = validate.shape(
        body,
        required=["store_code", "city", "state_code", "service_bay_count",
                  "hospital_capacity"],
        optional=[])
    if any(s["store_code"] == body["store_code"] for s in db.rows("stores")):
        raise ApiError("ERR_STORE_CODE_DUPLICATE")
    if body["service_bay_count"] < 1 or body["hospital_capacity"] < 1:
        raise ApiError("ERR_INVALID_REQUEST")
    row = db.new_row()
    row.update({
        "store_code": body["store_code"], "city": body["city"],
        "state_code": body["state_code"],
        "service_bay_count": int(body["service_bay_count"]),
        "hospital_capacity": int(body["hospital_capacity"]),
        "hospital_occupancy": 0, "hospital_posture": "OPEN",
        "pharmacy_hold_until": None, "cross_sell_credit_balance_cents": 0,
        "incident_risk_index": 0, "restricted_training_slots_pending": 0,
        "frozen_vaccination_clinics": 0, "stores_held_total": 0,
    })
    db.add("stores", row)
    return row


def restrict(body, store_id):
    store = core.require_store(store_id)
    body = validate.shape(body, required=["expected_store_version"], optional=[])
    validate.check_backdating(store)
    if store["hospital_posture"] != "OPEN":
        raise ApiError("ERR_ILLEGAL_STATE_TRANSITION")
    if store["hospital_occupancy"] < store["hospital_capacity"]:
        raise ApiError("ERR_HOSPITAL_AT_CAPACITY")
    validate.require_expected(body, store["version"], "expected_store_version")
    core.apply_posture(store, "RESTRICTED")
    core.refresh_store(store, recompute_posture=False)
    return store


def lift_posture_restriction(body, store_id):
    store = core.require_store(store_id)
    body = validate.shape(body, required=["expected_store_version"], optional=[])
    validate.check_backdating(store)
    if store["hospital_posture"] != "RESTRICTED":
        raise ApiError("ERR_ILLEGAL_STATE_TRANSITION")
    if store["hospital_occupancy"] >= store["hospital_capacity"]:
        raise ApiError("ERR_HOSPITAL_AT_CAPACITY")
    validate.require_expected(body, store["version"], "expected_store_version")
    core.apply_posture(store, "OPEN")
    core.refresh_store(store, recompute_posture=False)
    return store


def freeze_hospital(body, store_id):
    store = core.require_store(store_id)
    body = validate.shape(body, required=["expected_store_version"], optional=[])
    validate.check_backdating(store)
    if store["hospital_posture"] == "FROZEN":
        raise ApiError("ERR_ILLEGAL_STATE_TRANSITION")
    if store["hospital_posture"] != "RESTRICTED":
        raise ApiError("ERR_STORE_NOT_RESTRICTED")
    validate.require_expected(body, store["version"], "expected_store_version")
    core.apply_posture(store, "FROZEN")
    core.refresh_store(store, recompute_posture=False)
    return store


def reopen_hospital(body, store_id):
    store = core.require_store(store_id)
    body = validate.shape(body, required=["expected_store_version"], optional=[])
    validate.check_backdating(store)
    if store["hospital_posture"] != "FROZEN":
        raise ApiError("ERR_ILLEGAL_STATE_TRANSITION")
    _, occupied = core.store_occupancy(store)
    if occupied >= store["hospital_capacity"]:
        raise ApiError("ERR_HOSPITAL_AT_CAPACITY")
    validate.require_expected(body, store["version"], "expected_store_version")
    core.apply_posture(store, "OPEN")
    core.refresh_store(store, recompute_posture=False)
    return store


def bump_occupancy(body, store_id):
    store = core.require_store(store_id)
    body = validate.shape(body, required=["expected_store_version", "magnitude"],
                          optional=[])
    validate.check_backdating(store)
    magnitude = int(body["magnitude"])
    if magnitude < 0:
        raise ApiError("ERR_INVALID_REQUEST")
    if store["hospital_posture"] == "FROZEN":
        raise ApiError("ERR_STORE_HOSPITAL_FROZEN")
    scheduled = [e for e in db.rows("encounters")
                 if e["store_id"] == store_id and e["status"] == "SCHEDULED"]
    # A zero magnitude moves nothing and only re-runs the occupancy and posture
    # recalculation; the SCHEDULED-count precondition applies to the rows it moves.
    if magnitude and len(scheduled) < magnitude:
        raise ApiError("ERR_ILLEGAL_STATE_TRANSITION",
                       "The store has fewer SCHEDULED encounters than the requested magnitude.")
    validate.require_expected(body, store["version"], "expected_store_version")
    for encounter in scheduled[:magnitude]:
        encounter["status"] = "CHECKED_IN"
        db.touch(encounter)
    # deliberately stops at CHECKED_IN: the Pet-suspension cascade never fires
    core.refresh_store(store)
    return store


# ---------------------------------------------------------------------------
# members and pets
# ---------------------------------------------------------------------------

def create_member(body):
    body = validate.shape(
        body,
        required=["full_name", "email", "state_code", "home_store_id"],
        optional=[])
    core.require_store(body["home_store_id"])
    if "@" not in body["email"]:
        raise ApiError("ERR_INVALID_REQUEST")
    if any(m["email"] == body["email"] for m in db.rows("members")):
        raise ApiError("ERR_MEMBER_EMAIL_DUPLICATE")
    row = db.new_row()
    row.update({
        "full_name": body["full_name"], "email": body["email"],
        "state_code": body["state_code"], "home_store_id": body["home_store_id"],
        "outstanding_balance_cents": 0, "status": "ACTIVE",
    })
    db.add("members", row)
    return row


def set_member_status(member_id, status, body=None):
    member = core.require_member(member_id)
    validate.shape(body, optional=["expected_member_version"], allowed=[])
    validate.check_backdating(member)
    if body and body.get("expected_member_version") is not None:
        validate.require_expected(body, member["version"], "expected_member_version")
    member["status"] = status
    db.touch(member)
    return member


def archive_member(member_id, body=None):
    member = core.require_member(member_id)
    validate.shape(body, optional=["expected_member_version"], allowed=[])
    validate.check_backdating(member)
    if body and body.get("expected_member_version") is not None:
        validate.require_expected(body, member["version"], "expected_member_version")
    if any(p["status"] == "ACTIVE" for p in core.member_packages(member["id"])):
        raise ApiError("ERR_PACKAGE_ALREADY_ACTIVE",
                       "The member still holds an ACTIVE service package.")
    member["status"] = "ARCHIVED"
    db.touch(member)
    return member


def create_pet(body):
    body = validate.shape(
        body,
        required=["member_id", "name", "species", "breed", "weight_kg"],
        optional=[])
    member = core.require_member(body["member_id"])
    if float(body["weight_kg"]) <= 0:
        raise ApiError("ERR_INVALID_REQUEST")
    row = db.new_row()
    row.update({
        "member_id": member["id"], "name": body["name"], "species": body["species"],
        "breed": body["breed"], "weight_kg": body["weight_kg"],
        "rabies_vaccination_expires_at": None, "risk_score": 0, "status": "ACTIVE",
    })
    db.add("pets", row)
    return row


def archive_pet(body, pet_id):
    pet = core.require_pet(pet_id)
    body = validate.shape(body, required=["expected_pet_version"], optional=[])
    validate.check_backdating(pet)
    validate.require_expected(body, pet["version"], "expected_pet_version")
    pet["status"] = "ARCHIVED"
    db.touch(pet)
    return pet


# ---------------------------------------------------------------------------
# breed handling rules
# ---------------------------------------------------------------------------

def create_breed_rule(body):
    body = validate.shape(
        body,
        required=["breed", "species", "risk_points", "handling_tier"],
        optional=["allowed_for_grooming"])
    if body["risk_points"] < 0:
        raise ApiError("ERR_INVALID_REQUEST")
    for rule in db.rows("breed_rules"):
        if rule["species"] == body["species"] \
                and rule["breed"].lower() == body["breed"].lower():
            raise ApiError("ERR_BREED_RULE_DUPLICATE")
    row = db.new_row(versioned=False, common=False)
    row.update({
        "breed": body["breed"], "species": body["species"],
        "risk_points": int(body["risk_points"]),
        "handling_tier": body["handling_tier"],
        "allowed_for_grooming": bool(body.get("allowed_for_grooming", True)),
    })
    db.add("breed_rules", row)
    return row


# ---------------------------------------------------------------------------
# service bays
# ---------------------------------------------------------------------------

def create_bay(body, store_id):
    store = core.require_store(store_id)
    body = validate.shape(body, required=["bay_code"], optional=[])
    validate.check_backdating(store)
    if any(b["bay_code"] == body["bay_code"] and b["store_id"] == store_id
           for b in db.rows("bays")):
        raise ApiError("ERR_BAY_CODE_DUPLICATE")
    row = db.new_row()
    frozen = store["hospital_posture"] == "FROZEN"
    row.update({
        "store_id": store_id, "bay_code": body["bay_code"],
        "is_frozen": frozen, "status": "FROZEN" if frozen else "ACTIVE",
    })
    if frozen:
        row["version"] = 1
        db.touch(row)
    db.add("bays", row)
    return row


def disable_bay(body, store_id, bay_id):
    store = core.require_store(store_id)
    bay = core.require_bay(bay_id)
    if bay["store_id"] != store_id:
        raise ApiError("ERR_SERVICE_BAY_NOT_FOUND")
    body = validate.shape(body, required=["expected_bay_version"], optional=[])
    validate.check_backdating(store, bay)
    live = [b for b in db.rows("bookings")
            if b["bay_id"] == bay["id"] and b["status"] in domain.LIVE_BOOKING_STATES]
    if live:
        raise ApiError("ERR_BAY_HAS_ACTIVE_BOOKINGS")
    if bay["status"] != "ACTIVE":
        raise ApiError("ERR_BAY_NOT_ACTIVE")
    validate.require_expected(body, bay["version"], "expected_bay_version")
    bay["status"] = "DISABLED"
    db.touch(bay)
    return bay


# ---------------------------------------------------------------------------
# retail cross-sells
# ---------------------------------------------------------------------------

def create_cross_sell(body, store_id):
    store = core.require_store(store_id)
    body = validate.shape(
        body,
        required=["authorization_id", "pet_id", "sku", "expected_pet_version"],
        optional=[])
    auth = core.require_authorization(body["authorization_id"])
    if auth["store_id"] != store_id:
        raise ApiError("ERR_AUTHORIZATION_NOT_FOUND")
    pet = core.require_pet(body["pet_id"])
    validate.check_backdating(store, auth, pet)
    if auth["pet_id"] != pet["id"]:
        raise ApiError("ERR_AUTHORIZATION_PET_MISMATCH")
    if body.get("expected_pet_version") is None:
        raise ApiError("ERR_MISSING_EXPECTED_VERSION")
    if int(body["expected_pet_version"]) != pet["version"]:
        raise ApiError("ERR_STALE_VERSION")
    # Take the live retail line value, falling back to the frozen one while the
    # prescription is still PENDING_EXAM (its price is not frozen until the exam
    # completes, and the cross-sell must still be priced).
    gross = auth["unit_price_cents"] * auth["quantity"]
    if gross == 0:
        gross = auth["price_at_authorization_cents"]
    granted = domain.cents(domain.dec(gross) * domain.CROSS_SELL_CREDIT_RATE)
    row = db.new_row()
    row.update({
        "store_id": store_id, "authorization_id": auth["id"], "pet_id": pet["id"],
        "sku": body["sku"], "gross_cents": gross,
        "credit_granted_cents": granted, "credit_redeemed_cents": 0,
        "status": "PENDING",
    })
    db.add("cross_sells", row)
    core.recompute_cross_sell_balance(store)
    return row


def redeem_cross_sell(body, store_id, cross_sell_id):
    store = core.require_store(store_id)
    row = core.require_cross_sell(cross_sell_id)
    if row["store_id"] != store_id:
        raise ApiError("ERR_CROSS_SELL_NOT_FOUND")
    validate.check_backdating(store, row)
    body = validate.shape(
        body, required=["expected_cross_sell_version", "credit_redeemed_cents"],
        optional=[])
    if row["status"] != "PENDING":
        raise ApiError("ERR_ILLEGAL_STATE_TRANSITION")
    if int(body["credit_redeemed_cents"]) < 0:
        raise ApiError("ERR_INVALID_REQUEST")
    validate.require_expected(body, row["version"], "expected_cross_sell_version")
    row["status"] = "REDEEMED"
    row["credit_redeemed_cents"] = int(body["credit_redeemed_cents"])
    db.touch(row)
    core.recompute_cross_sell_balance(store)
    return row


# ---------------------------------------------------------------------------
# the logical clock (§2.5)
# ---------------------------------------------------------------------------

def set_clock(body):
    body = validate.shape(body, required=["to_iso8601"], optional=[])
    try:
        target = db.parse_dt(body["to_iso8601"])
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST")
    if target > db.clock["highest"]:
        db.clock["highest"] = target
    db.clock["current"] = target
    core.on_clock_moved()
    return {"current_utc": db.iso(db.clock["current"]),
            "highest_set_utc": db.iso(db.clock["highest"])}


def read_store(store_id):
    return core.require_store(store_id)