"""Delivery-area versions, address classification and edge disputes (PRD 3.1-3.3)."""
from flask import Blueprint

import auth
import calc
import clock
import db
import derive
import listing
import response
import serialize
import validate
from errors import fail

bp = Blueprint("zones", __name__)

READ_ROLES = auth.ALL_ROLES
ZONE_STATUSES = ("DRAFT", "ACTIVE", "SUPERSEDED")
ZONE_STATES = ("IN_ZONE", "EDGE", "OUT_OF_ZONE")
DISPUTE_STATUSES = ("SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED", "GRANTED", "DENIED", "WITHDRAWN")
REVIEW_ACTIONS = ("START_REVIEW", "REQUEST_INFO", "GRANT", "DENY", "WITHDRAW")
MANAGER_ACTIONS = ("START_REVIEW", "REQUEST_INFO", "GRANT", "DENY")

ZONE_MODEL_FIELDS = (
    ("max_drive_time_minutes", 25, 1),
    ("base_drive_minutes", 6, 0),
    ("minutes_per_mile", 3, 1),
    ("peak_surcharge_minutes", 7, 0),
    ("barrier_surcharge_minutes", 4, 0),
)


# --- delivery-area versions ---------------------------------------------------

@bp.post("/store-ops/zone-versions")
def publish_zone_version():
    actor = auth.authenticate(["StoreManager"])
    auth.guard(actor, [], [("store_id", "store")])
    body = validate.body()
    raw_store_id = body.get("store_id")
    store = None
    if isinstance(raw_store_id, str) and raw_store_id != "":
        store = auth.body_fk("store", raw_store_id)
    validate.string(body, "store_id")
    ring = validate.polygon(body)
    effective_from = validate.instant(body, "effective_from")
    effective_to = validate.instant(body, "effective_to")
    expected_store_version = validate.integer(body, "expected_store_version")
    record = {
        "store_id": store["id"],
        "polygon": ring,
        "effective_from": effective_from,
        "effective_to": effective_to,
    }
    for field, default, minimum in ZONE_MODEL_FIELDS:
        record[field] = validate.integer(
            body, field, required=False, default=default, minimum=minimum
        )
    if len(ring) < 3:
        fail("ERR_INVALID_POLYGON", "A delivery-area ring needs at least three vertices.")
    if not effective_to > effective_from:
        fail("ERR_INVALID_ZONE_WINDOW", "effective_to must be strictly after effective_from.")
    if expected_store_version != store["version"]:
        fail("ERR_STALE_STORE_VERSION", "The store has moved on; re-read it for a fresh version.")
    for existing in db.zone_versions.values():
        if existing["store_id"] != store["id"] or existing["status"] not in ("DRAFT", "ACTIVE"):
            continue
        if effective_from < existing["effective_to"] and existing["effective_from"] < effective_to:
            fail("ERR_ZONE_WINDOW_OVERLAP", "The window overlaps an existing draft or active version.")
    prior = [v for v in db.zone_versions.values() if v["store_id"] == store["id"]]
    record["version_number"] = len(prior) + 1
    record["status"] = "DRAFT"
    record["supersedes_zone_version_id"] = None
    record["activated_at"] = None
    db.insert(db.zone_versions, record)
    db.touch(store)
    return response.created(serialize.zone_version(record))


@bp.post("/store-ops/zone-versions/<zone_version_id>/activate")
def activate_zone_version(zone_version_id):
    actor = auth.authenticate(["StoreManager"])
    (version,) = auth.guard(actor, [("zone_version", zone_version_id)])
    if version["status"] != "DRAFT":
        fail("ERR_INVALID_ZONE_VERSION_STATE", "Only a DRAFT version can be activated.")
    if len(version["polygon"]) < 3:
        fail("ERR_INVALID_POLYGON", "A delivery-area ring needs at least three vertices.")
    displaced = [
        v
        for v in db.zone_versions.values()
        if v["store_id"] == version["store_id"]
        and v["id"] != version["id"]
        and v["status"] == "ACTIVE"
        and v["effective_to"] <= version["effective_from"]
    ]
    version["status"] = "ACTIVE"
    version["activated_at"] = clock.now()
    if displaced:
        displaced.sort(key=lambda v: (v["effective_to"], v["created_at"], v["_seq"]))
        superseded = displaced[-1]
        version["supersedes_zone_version_id"] = superseded["id"]
        superseded["status"] = "SUPERSEDED"
        db.touch(superseded)
    db.touch(version)
    store = db.stores.get(version["store_id"])
    if store is not None:
        db.touch(store)
    return response.ok(serialize.zone_version(version))


@bp.get("/store-ops/zone-versions/<zone_version_id>")
def read_zone_version(zone_version_id):
    actor = auth.authenticate(READ_ROLES)
    (version,) = auth.guard(actor, [("zone_version", zone_version_id)])
    return response.ok(serialize.zone_version(version))


@bp.get("/store-ops/zone-versions")
def list_zone_versions():
    actor = auth.authenticate(READ_ROLES)
    store_id = validate.filter_string("store_id")
    supersedes = validate.filter_string("supersedes_zone_version_id")
    status = validate.filter_enum("status", ZONE_STATUSES)
    records = list(db.zone_versions.values())
    if actor.is_manager:
        records = [v for v in records if v["store_id"] == actor.user_id]
    if store_id is not None:
        records = [v for v in records if v["store_id"] == store_id]
    if supersedes is not None:
        records = [v for v in records if v["supersedes_zone_version_id"] == supersedes]
    if status is not None:
        records = [v for v in records if v["status"] == status]
    return listing.respond(records, serialize.zone_version)


# --- service addresses --------------------------------------------------------

@bp.post("/store-ops/service-addresses")
def file_service_address():
    actor = auth.authenticate(["Dispatcher", "CustomerCareAgent", "StoreManager"])
    auth.guard(actor, [], [("store_id", "store")])
    body = validate.body()
    raw_store_id = body.get("store_id")
    store = None
    if isinstance(raw_store_id, str) and raw_store_id != "":
        store = auth.body_fk("store", raw_store_id)
    validate.string(body, "store_id")
    line1 = validate.string(body, "line1")
    latitude = validate.integer(body, "latitude_micro", minimum=-90000000, maximum=90000000)
    longitude = validate.integer(body, "longitude_micro", minimum=-180000000, maximum=180000000)
    crosses_barrier = validate.boolean(body, "crosses_barrier", required=False, default=False)
    version = derive.in_force_zone_version(store["id"])
    if version is None:
        fail("ERR_NO_ACTIVE_ZONE_VERSION", "The store has no delivery area in force.")
    miles = calc.grid_miles(store, latitude, longitude)
    minutes = calc.drive_time_estimate(version, miles, crosses_barrier, clock.now())
    record = {
        "store_id": store["id"],
        "line1": line1,
        "latitude_micro": latitude,
        "longitude_micro": longitude,
        "crosses_barrier": crosses_barrier,
        "grid_miles": miles,
        "drive_time_estimate_minutes": minutes,
        "zone_state": calc.zone_state(version, latitude, longitude, minutes),
        "evaluated_zone_version_number": version["version_number"],
        "evaluated_at": clock.now(),
        "override_state": None,
        "override_until": None,
    }
    db.insert(db.service_addresses, record)
    return response.created(serialize.service_address(record))


@bp.get("/store-ops/service-addresses/<service_address_id>")
def read_service_address(service_address_id):
    actor = auth.authenticate(READ_ROLES)
    (address,) = auth.guard(actor, [("service_address", service_address_id)])
    return response.ok(serialize.service_address(address))


@bp.get("/store-ops/service-addresses")
def list_service_addresses():
    actor = auth.authenticate(READ_ROLES)
    store_id = validate.filter_string("store_id")
    zone_state = validate.filter_enum("zone_state", ZONE_STATES)
    records = list(db.service_addresses.values())
    if actor.is_manager:
        records = [a for a in records if a["store_id"] == actor.user_id]
    if store_id is not None:
        records = [a for a in records if a["store_id"] == store_id]
    if zone_state is not None:
        records = [a for a in records if a["zone_state"] == zone_state]
    return listing.respond(records, serialize.service_address)


# --- edge disputes ------------------------------------------------------------

@bp.post("/store-ops/address-disputes")
def open_dispute():
    actor = auth.authenticate(["CustomerCareAgent", "StoreManager"])
    auth.guard(actor, [], [("service_address_id", "service_address")])
    body = validate.body()
    raw_address_id = body.get("service_address_id")
    address = None
    if isinstance(raw_address_id, str) and raw_address_id != "":
        address = auth.body_fk("service_address", raw_address_id)
    validate.string(body, "service_address_id")
    claimed_state = validate.enum(body, "claimed_state", ("IN_ZONE",))
    evidence_note = validate.string(body, "evidence_note")
    record = {
        "service_address_id": address["id"],
        "claimed_state": claimed_state,
        "evidence_note": evidence_note,
        "status": "SUBMITTED",
        "review_round_count": 0,
        "resolution": None,
        "granted_until": None,
        "decided_at": None,
        "reviewer_user_id": None,
    }
    db.insert(db.disputes, record)
    return response.created(serialize.address_dispute(record))


@bp.post("/store-ops/address-disputes/<address_dispute_id>/review")
def review_dispute(address_dispute_id):
    actor = auth.authenticate(["StoreManager", "CustomerCareAgent"])
    peeked = auth.peek_body().get("action")
    if peeked in MANAGER_ACTIONS and not actor.is_manager:
        fail("ERR_UNAUTHORIZED", "Action %s is reserved to a StoreManager." % peeked)
    if peeked == "WITHDRAW" and actor.role != "CustomerCareAgent":
        fail("ERR_UNAUTHORIZED", "Action WITHDRAW is reserved to a CustomerCareAgent.")
    (dispute,) = auth.guard(actor, [("address_dispute", address_dispute_id)])
    body = validate.body()
    action = validate.enum(body, "action", REVIEW_ACTIONS)
    validate.string(body, "note", required=False, min_len=None)
    granted_until = validate.instant(body, "granted_until", required=False)
    if action == "GRANT":
        if granted_until is None:
            fail("ERR_INVALID_REQUEST", "Field 'granted_until' is required on a GRANT.")
        if not granted_until > clock.now():
            fail("ERR_INVALID_REQUEST", "Field 'granted_until' must be strictly in the future.")
    allowed = {
        "START_REVIEW": ("SUBMITTED", "INFO_REQUESTED"),
        "REQUEST_INFO": ("UNDER_REVIEW",),
        "GRANT": ("UNDER_REVIEW",),
        "DENY": ("UNDER_REVIEW",),
        "WITHDRAW": ("SUBMITTED",),
    }[action]
    if dispute["status"] not in allowed:
        fail("ERR_INVALID_DISPUTE_STATE", "Action %s is not declared from %s." % (action, dispute["status"]))
    if action == "REQUEST_INFO" and dispute["review_round_count"] >= 2:
        fail("ERR_DISPUTE_ROUND_LIMIT", "The review loop is bounded at two rounds.")
    if action == "START_REVIEW":
        dispute["status"] = "UNDER_REVIEW"
        dispute["reviewer_user_id"] = actor.user_id
    elif action == "REQUEST_INFO":
        dispute["status"] = "INFO_REQUESTED"
        dispute["review_round_count"] = dispute["review_round_count"] + 1
        dispute["reviewer_user_id"] = actor.user_id
    elif action == "DENY":
        dispute["status"] = "DENIED"
        dispute["resolution"] = "DENIED"
        dispute["decided_at"] = clock.now()
    elif action == "WITHDRAW":
        dispute["status"] = "WITHDRAWN"
    else:
        dispute["status"] = "GRANTED"
        dispute["resolution"] = "GRANTED"
        dispute["decided_at"] = clock.now()
        dispute["granted_until"] = granted_until
        _apply_grant(dispute, granted_until)
    db.touch(dispute)
    return response.ok(serialize.address_dispute(dispute))


def _apply_grant(dispute, granted_until):
    """The grant cascade of PRD 3.3, hop by hop."""
    address = db.service_addresses.get(dispute["service_address_id"])
    if address is None:
        return
    address["override_state"] = "IN_ZONE"
    address["override_until"] = granted_until
    db.touch(address)
    held = [
        o
        for o in db.orders.values()
        if o["service_address_id"] == address["id"] and o["fulfillment_status"] == "ZONE_HELD"
    ]
    for order in db.ordered(held):
        if order["zone_held_at"] is not None:
            order["zone_hold_minutes"] = order["zone_hold_minutes"] + clock.elapsed_minutes_floor(
                clock.now(), order["zone_held_at"]
            )
        order["fulfillment_status"] = "ZONE_CLEARED"
        db.touch(order)


@bp.get("/store-ops/address-disputes/<address_dispute_id>")
def read_dispute(address_dispute_id):
    actor = auth.authenticate(READ_ROLES)
    (dispute,) = auth.guard(actor, [("address_dispute", address_dispute_id)])
    return response.ok(serialize.address_dispute(dispute))


@bp.get("/store-ops/address-disputes")
def list_disputes():
    actor = auth.authenticate(READ_ROLES)
    address_id = validate.filter_string("service_address_id")
    status = validate.filter_enum("status", DISPUTE_STATUSES)
    records = list(db.disputes.values())
    if actor.is_manager:
        records = [
            d
            for d in records
            if auth.owning_store_id("address_dispute", d) == actor.user_id
        ]
    if address_id is not None:
        records = [d for d in records if d["service_address_id"] == address_id]
    if status is not None:
        records = [d for d in records if d["status"] == status]
    return listing.respond(records, serialize.address_dispute)
