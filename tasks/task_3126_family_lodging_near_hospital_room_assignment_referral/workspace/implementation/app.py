"""Family Lodging Hospital Referral API — Flask application entry point."""
import os
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request

import store
from auth import auth, require_roles
from envelope import success, list_response, error_response
from errors import (
    ApiError,
    err,
    ERR_INVALID_REQUEST,
    ERR_UNAUTHENTICATED,
    ERR_FORBIDDEN,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_NOT_FOUND,
    ERR_STALE_VERSION,
    ERR_INVALID_STATE,
    ERR_STAY_NOT_ACTIVE,
    ERR_OFFER_EXPIRED,
    ERR_DONATION_DEPLETED,
    ERR_REFERRAL_NOT_VERIFIED,
    ERR_SCREENING_NOT_CLEARED,
    ERR_FOOD_SAFETY_CERT_REQUIRED,
    ERR_FOOD_SAFETY_CERT_EXPIRED,
    ERR_FOOD_SAFETY_ATTESTATION_REQUIRED,
    ERR_DISTANCE_INELIGIBLE,
    ERR_GUEST_LIMIT_EXCEEDED,
    ERR_CAPACITY_EXCEEDED,
    ERR_ROOM_NOT_AVAILABLE,
    ERR_ROOM_HOUSE_MISMATCH,
    ERR_CARE_SPACE_CONFLICT,
    ERR_DUPLICATE_MEAL_SHIFT,
    ERR_DUPLICATE_ACTIVE_REFERRAL,
    ERR_REFERRAL_FAMILY_MISMATCH,
    ERR_BOOKING_REFERRAL_MISMATCH,
    ERR_INVALID_DATE_RANGE,
    ERR_TRANSITION_PLAN_REQUIRED,
    ERR_OVERPAYMENT,
    ERR_INSUFFICIENT_SUPPLY,
)
from validate import (
    get_body,
    check_unknown_fields,
    require_fields,
    req_str,
    req_int,
    req_number,
    req_bool,
    req_enum,
    opt_str,
    req_date,
    req_datetime,
)
import serializers as ser
from core import (
    compute_score,
    referral_chain_revocation,
    reoffer_freed_rooms,
    promote_one,
    reserved_room_ids,
    eligible_waitlisted,
    rank_waitlist,
    eligible_rooms,
    select_room,
    bump,
    new_record,
)

app = Flask(__name__)

ALL_ROLES = (
    "ProgramAdmin",
    "HouseManager",
    "HospitalReferrer",
    "FamilyContact",
    "VolunteerCoordinator",
)
ACUITY_VALUES = ("LOW", "MODERATE", "HIGH", "CRITICAL")


@app.errorhandler(ApiError)
def _api_error(e):
    return error_response(e)


@app.errorhandler(404)
def _not_found(e):
    return error_response(err(ERR_NOT_FOUND, "resource not found"))


@app.errorhandler(405)
def _method_not_allowed(e):
    return error_response(err(ERR_NOT_FOUND, "resource not found"))


@app.errorhandler(500)
def _internal(e):
    return error_response(err(ERR_INVALID_REQUEST, "internal error"))


# ---------------------------------------------------------------------------
# Lookup helpers (existence gate, priority 3)
# ---------------------------------------------------------------------------


def get_or_404(collection, rid, what):
    rec = store.db[collection].get(rid)
    if rec is None:
        raise err(ERR_NOT_FOUND, "%s not found" % what)
    return rec


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------


@app.route("/_clock/set_current_utc", methods=["POST"])
def clock_set():
    body = get_body()
    check_unknown_fields(body, ["to_iso8601"])
    require_fields(body, ["to_iso8601"])
    uid, role = auth()
    require_roles(role, ["ProgramAdmin"])
    target = req_datetime(body, "to_iso8601")
    store.set_clock(target)
    return success({"current_utc": store.now_iso()})


# ---------------------------------------------------------------------------
# Hospitals
# ---------------------------------------------------------------------------


@app.route("/api/hospitals", methods=["POST"])
def hospital_create():
    body = get_body()
    check_unknown_fields(body, ["name", "city"])
    require_fields(body, ["name", "city"])
    uid, role = auth()
    require_roles(role, ["ProgramAdmin"])
    name = req_str(body, "name")
    city = req_str(body, "city")
    rec = new_record({"name": name, "city": city})
    store.db["hospitals"][rec["id"]] = rec
    return success(ser.hospital_view(rec), status=201)


@app.route("/api/hospitals/<hid>", methods=["GET"])
def hospital_get(hid):
    uid, role = auth()
    require_roles(role, list(ALL_ROLES))
    h = get_or_404("hospitals", hid, "hospital")
    return success(ser.hospital_view(h))


@app.route("/api/hospitals/<hid>/houses", methods=["GET"])
def hospital_houses(hid):
    uid, role = auth()
    require_roles(role, list(ALL_ROLES))
    get_or_404("hospitals", hid, "hospital")
    houses = [
        h for h in store.db["houses"].values() if h["associated_hospital_id"] == hid
    ]
    houses.sort(key=lambda x: x["_seq"])
    return list_response([ser.house_view(h) for h in houses])


@app.route("/api/hospitals/<hid>/referrals", methods=["GET"])
def hospital_referrals(hid):
    uid, role = auth()
    require_roles(role, ["ProgramAdmin", "HouseManager", "HospitalReferrer"])
    get_or_404("hospitals", hid, "hospital")
    status = request.args.get("status")
    refs = [r for r in store.db["referrals"].values() if r["hospital_id"] == hid]
    if status is not None:
        refs = [r for r in refs if r["status"] == status]
    refs.sort(key=lambda x: x["_seq"])
    return list_response([ser.referral_view(r) for r in refs])


@app.route("/api/hospitals/<hid>/care-spaces", methods=["GET"])
def hospital_care_spaces(hid):
    uid, role = auth()
    require_roles(role, list(ALL_ROLES))
    get_or_404("hospitals", hid, "hospital")
    space_type = request.args.get("space_type")
    spaces = [c for c in store.db["care_spaces"].values() if c["hospital_id"] == hid]
    if space_type is not None:
        spaces = [c for c in spaces if c["space_type"] == space_type]
    spaces.sort(key=lambda x: x["_seq"])
    return list_response([ser.care_space_view(c) for c in spaces])


@app.route("/api/hospitals/<hid>/care-spaces", methods=["POST"])
def care_space_create(hid):
    body = get_body()
    check_unknown_fields(body, ["space_name", "space_type", "capacity"])
    require_fields(body, ["space_name", "space_type", "capacity"])
    uid, role = auth()
    require_roles(role, ["ProgramAdmin"])
    space_name = req_str(body, "space_name")
    space_type = req_enum(body, "space_type", ("FAMILY_ROOM", "MOBILE_CARE_UNIT"))
    capacity = req_int(body, "capacity")
    if capacity <= 0:
        raise err(ERR_INVALID_REQUEST, "capacity must be > 0")
    get_or_404("hospitals", hid, "hospital")
    rec = new_record(
        {
            "hospital_id": hid,
            "space_name": space_name,
            "space_type": space_type,
            "capacity": capacity,
        }
    )
    store.db["care_spaces"][rec["id"]] = rec
    return success(ser.care_space_view(rec), status=201)


# ---------------------------------------------------------------------------
# Houses / Rooms
# ---------------------------------------------------------------------------


@app.route("/api/houses", methods=["POST"])
def house_create():
    body = get_body()
    check_unknown_fields(body, ["name", "city", "associated_hospital_id"])
    require_fields(body, ["name", "city", "associated_hospital_id"])
    uid, role = auth()
    require_roles(role, ["ProgramAdmin"])
    name = req_str(body, "name")
    city = req_str(body, "city")
    hospital_id = req_str(body, "associated_hospital_id")
    get_or_404("hospitals", hospital_id, "hospital")
    rec = new_record(
        {"name": name, "city": city, "associated_hospital_id": hospital_id}
    )
    store.db["houses"][rec["id"]] = rec
    return success(ser.house_view(rec), status=201)


@app.route("/api/houses/<hid>", methods=["GET"])
def house_get(hid):
    uid, role = auth()
    require_roles(role, list(ALL_ROLES))
    h = get_or_404("houses", hid, "house")
    return success(ser.house_view(h))


@app.route("/api/houses/<hid>/supply-inventory", methods=["GET"])
def house_supply_inventory(hid):
    uid, role = auth()
    require_roles(role, ["ProgramAdmin", "HouseManager"])
    get_or_404("houses", hid, "house")
    rollup = {
        "HYGIENE_KIT": 0,
        "PANTRY_STAPLE": 0,
        "CLEANING_SUPPLY": 0,
        "BABY_SUPPLY": 0,
    }
    for d in store.db["donations"].values():
        if d["house_id"] == hid:
            rollup[d["supply_category"]] += d["quantity_received"] - d["quantity_distributed"]
    return success(rollup)


@app.route("/api/houses/<hid>/rooms", methods=["POST"])
def room_create(hid):
    body = get_body()
    check_unknown_fields(body, ["room_number", "bed_count", "occupancy_limit"])
    require_fields(body, ["room_number", "bed_count", "occupancy_limit"])
    uid, role = auth()
    require_roles(role, ["ProgramAdmin", "HouseManager"])
    room_number = req_str(body, "room_number")
    bed_count = req_int(body, "bed_count")
    occupancy_limit = req_int(body, "occupancy_limit")
    if bed_count <= 0:
        raise err(ERR_INVALID_REQUEST, "bed_count must be > 0")
    if occupancy_limit <= 0:
        raise err(ERR_INVALID_REQUEST, "occupancy_limit must be > 0")
    get_or_404("houses", hid, "house")
    rec = new_record(
        {
            "house_id": hid,
            "room_number": room_number,
            "bed_count": bed_count,
            "occupancy_limit": occupancy_limit,
            "status": "AVAILABLE",
            "occupied": False,
        }
    )
    store.db["rooms"][rec["id"]] = rec
    return success(ser.room_view(rec), status=201)


@app.route("/api/houses/<hid>/rooms", methods=["GET"])
def room_list(hid):
    uid, role = auth()
    require_roles(role, ["ProgramAdmin", "HouseManager"])
    get_or_404("houses", hid, "house")
    status = request.args.get("status")
    rooms = [r for r in store.db["rooms"].values() if r["house_id"] == hid]
    if status is not None:
        rooms = [r for r in rooms if r["status"] == status]
    rooms.sort(key=lambda x: x["_seq"])
    return list_response([ser.room_view(r) for r in rooms])


@app.route("/api/rooms/<rid>", methods=["GET"])
def room_get(rid):
    uid, role = auth()
    require_roles(role, ["ProgramAdmin", "HouseManager"])
    r = get_or_404("rooms", rid, "room")
    return success(ser.room_view(r))


@app.route("/api/rooms/<rid>/stay-requests", methods=["GET"])
def room_stay_requests(rid):
    uid, role = auth()
    require_roles(role, ["ProgramAdmin", "HouseManager"])
    get_or_404("rooms", rid, "room")
    reqs = [
        q
        for q in store.db["stay_requests"].values()
        if q["assignment_status"] == "OFFERED" and q["offered_room_id"] == rid
    ]
    reqs.sort(key=lambda x: x["_seq"])
    return list_response([ser.stay_request_view(q) for q in reqs])


@app.route("/api/rooms/<rid>/set-status", methods=["POST"])
def room_set_status(rid):
    body = get_body()
    check_unknown_fields(body, ["target_status"])
    require_fields(body, ["target_status"])
    uid, role = auth()
    require_roles(role, ["ProgramAdmin", "HouseManager"])
    target = req_enum(body, "target_status", ("AVAILABLE", "MAINTENANCE", "OFFLINE"))
    room = get_or_404("rooms", rid, "room")
    # State gate
    if target == "MAINTENANCE":
        if room["status"] != "AVAILABLE":
            raise err(ERR_INVALID_STATE, "only AVAILABLE rooms can enter MAINTENANCE")
        if room["occupied"]:
            raise err(ERR_ROOM_NOT_AVAILABLE, "room is occupied")
        if room["id"] in reserved_room_ids():
            raise err(ERR_ROOM_NOT_AVAILABLE, "room is reserved by an OFFERED request")
        room["status"] = "MAINTENANCE"
    elif target == "AVAILABLE":
        if room["status"] not in ("MAINTENANCE", "OFFLINE"):
            raise err(ERR_INVALID_STATE, "only MAINTENANCE or OFFLINE rooms can return to AVAILABLE")
        room["status"] = "AVAILABLE"
    else:  # OFFLINE
        if room["status"] == "OFFLINE":
            raise err(ERR_INVALID_STATE, "room already OFFLINE")
        room["status"] = "OFFLINE"
        # Cascade: occupying stay -> RELOCATION_REQUIRED, room freed
        if room["occupied"]:
            for stay in store.db["stays"].values():
                if (
                    stay["room_id"] == room["id"]
                    and stay["status"] in ("ACTIVE", "UNDER_REVIEW", "TRANSITION_PLANNED")
                ):
                    stay["status"] = "RELOCATION_REQUIRED"
                    bump(stay)
            room["occupied"] = False
        # Rescind any OFFERED hold on this room (no re-offer)
        for req in store.db["stay_requests"].values():
            if req["assignment_status"] == "OFFERED" and req["offered_room_id"] == room["id"]:
                req["assignment_status"] = "WAITLISTED"
                req["offered_room_id"] = None
                req["offer_expires_at"] = None
                req["waitlisted_since"] = store.now_iso()
                bump(req)
    bump(room)
    return success(ser.room_view(room))


# ---------------------------------------------------------------------------
# Families
# ---------------------------------------------------------------------------


@app.route("/api/families", methods=["POST"])
def family_create():
    body = get_body()
    check_unknown_fields(
        body,
        ["family_name", "primary_contact_name", "home_city", "distance_miles", "child_patient_name"],
    )
    require_fields(
        body,
        ["family_name", "primary_contact_name", "home_city", "distance_miles", "child_patient_name"],
    )
    uid, role = auth()
    require_roles(role, ["ProgramAdmin", "HouseManager"])
    family_name = req_str(body, "family_name")
    primary_contact_name = req_str(body, "primary_contact_name")
    home_city = req_str(body, "home_city")
    distance_miles = req_number(body, "distance_miles")
    child_patient_name = req_str(body, "child_patient_name")
    rec = new_record(
        {
            "family_name": family_name,
            "primary_contact_name": primary_contact_name,
            "home_city": home_city,
            "distance_miles": distance_miles,
            "child_patient_name": child_patient_name,
        }
    )
    store.db["families"][rec["id"]] = rec
    return success(ser.family_view(rec), status=201)


def _family_owned(family, uid, role):
    if role == "FamilyContact" and family["id"] != uid:
        raise err(ERR_FORBIDDEN, "FamilyContact may only access own family")


@app.route("/api/families/<fid>", methods=["GET"])
def family_get(fid):
    uid, role = auth()
    require_roles(role, ["ProgramAdmin", "HouseManager", "FamilyContact"])
    fam = get_or_404("families", fid, "family")
    _family_owned(fam, uid, role)
    return success(ser.family_view(fam))


@app.route("/api/families/<fid>/referrals", methods=["GET"])
def family_referrals(fid):
    uid, role = auth()
    require_roles(role, ["ProgramAdmin", "HouseManager", "FamilyContact", "HospitalReferrer"])
    fam = get_or_404("families", fid, "family")
    _family_owned(fam, uid, role)
    status = request.args.get("status")
    refs = [r for r in store.db["referrals"].values() if r["family_id"] == fid]
    if status is not None:
        refs = [r for r in refs if r["status"] == status]
    refs.sort(key=lambda x: x["_seq"])
    return list_response([ser.referral_view(r) for r in refs])


@app.route("/api/families/<fid>/stay-requests", methods=["GET"])
def family_stay_requests(fid):
    uid, role = auth()
    require_roles(role, ["ProgramAdmin", "HouseManager", "FamilyContact"])
    fam = get_or_404("families", fid, "family")
    _family_owned(fam, uid, role)
    status = request.args.get("assignment_status")
    reqs = [q for q in store.db["stay_requests"].values() if q["family_id"] == fid]
    if status is not None:
        reqs = [q for q in reqs if q["assignment_status"] == status]
    reqs.sort(key=lambda x: x["_seq"])
    return list_response([ser.stay_request_view(q) for q in reqs])


@app.route("/api/families/<fid>/care-space-bookings", methods=["GET"])
def family_care_space_bookings(fid):
    uid, role = auth()
    require_roles(role, ["ProgramAdmin", "HouseManager", "FamilyContact"])
    fam = get_or_404("families", fid, "family")
    _family_owned(fam, uid, role)
    status = request.args.get("status")
    books = [b for b in store.db["bookings"].values() if b["family_id"] == fid]
    if status is not None:
        books = [b for b in books if b["status"] == status]
    books.sort(key=lambda x: x["_seq"])
    return list_response([ser.booking_view(b) for b in books])


# ---------------------------------------------------------------------------
# Referrals
# ---------------------------------------------------------------------------


@app.route("/api/referrals", methods=["POST"])
def referral_create():
    body = get_body()
    check_unknown_fields(
        body,
        ["family_id", "hospital_id", "treating_unit", "care_type", "acuity_level", "attending_clinician"],
    )
    require_fields(
        body,
        ["family_id", "hospital_id", "treating_unit", "care_type", "acuity_level", "attending_clinician"],
    )
    uid, role = auth()
    require_roles(role, ["HospitalReferrer", "ProgramAdmin"])
    family_id = req_str(body, "family_id")
    hospital_id = req_str(body, "hospital_id")
    treating_unit = req_str(body, "treating_unit")
    care_type = req_enum(body, "care_type", ("INPATIENT", "OUTPATIENT"))
    acuity_level = req_enum(body, "acuity_level", ACUITY_VALUES)
    attending_clinician = req_str(body, "attending_clinician")
    if role == "HospitalReferrer" and hospital_id != uid:
        raise err(ERR_FORBIDDEN, "HospitalReferrer may only issue referrals for own hospital")
    get_or_404("families", family_id, "family")
    get_or_404("hospitals", hospital_id, "hospital")
    # At most one non-terminal referral per (family, hospital)
    for r in store.db["referrals"].values():
        if (
            r["family_id"] == family_id
            and r["hospital_id"] == hospital_id
            and r["status"] in ("PENDING", "VERIFIED")
        ):
            raise err(ERR_DUPLICATE_ACTIVE_REFERRAL, "a non-terminal referral already exists for this family and hospital")
    rec = new_record(
        {
            "family_id": family_id,
            "hospital_id": hospital_id,
            "treating_unit": treating_unit,
            "care_type": care_type,
            "acuity_level": acuity_level,
            "attending_clinician": attending_clinician,
            "status": "PENDING",
            "created_by_user_id": uid,
            "verified_by_user_id": None,
            "verified_at": None,
            "valid_until": None,
        }
    )
    store.db["referrals"][rec["id"]] = rec
    return success(ser.referral_view(rec), status=201)


@app.route("/api/referrals/<rid>", methods=["GET"])
def referral_get(rid):
    uid, role = auth()
    require_roles(role, ["ProgramAdmin", "HouseManager", "HospitalReferrer", "FamilyContact"])
    r = get_or_404("referrals", rid, "referral")
    return success(ser.referral_view(r))


@app.route("/api/referrals/<rid>/verify", methods=["POST"])
def referral_verify(rid):
    body = get_body()
    check_unknown_fields(body, ["decision", "notes"])
    require_fields(body, ["decision"])
    uid, role = auth()
    require_roles(role, ["HouseManager", "ProgramAdmin"])
    decision = req_enum(body, "decision", ("APPROVE", "DECLINE"))
    opt_str(body, "notes", None)
    ref = get_or_404("referrals", rid, "referral")
    # Segregation of duties (still an authorization-class failure)
    if ref["created_by_user_id"] == uid:
        raise err(ERR_SEGREGATION_OF_DUTIES, "verifier must differ from referral creator")
    if ref["status"] != "PENDING":
        raise err(ERR_INVALID_STATE, "referral is not PENDING")
    if decision == "APPROVE":
        ref["status"] = "VERIFIED"
        ref["verified_by_user_id"] = uid
        ref["verified_at"] = store.now_iso()
        ref["valid_until"] = store.iso(store.now() + timedelta(days=30))
        bump(ref)
        # Cascade: linked UNVERIFIED stay requests -> VERIFICATION_OK with verified score
        for req in store.db["stay_requests"].values():
            if req["referral_id"] == ref["id"] and req["verification_status"] == "UNVERIFIED":
                fam = store.db["families"].get(req["family_id"])
                req["verification_status"] = "VERIFICATION_OK"
                req["verified_score"] = compute_score(
                    fam["distance_miles"], ref["acuity_level"], req["expected_nights"]
                )
                bump(req)
    else:  # DECLINE
        ref["status"] = "DECLINED"
        ref["verified_by_user_id"] = uid
        bump(ref)
        for req in store.db["stay_requests"].values():
            if req["referral_id"] == ref["id"] and req["verification_status"] == "UNVERIFIED":
                req["verification_status"] = "VERIFICATION_FAILED"
                bump(req)
    return success(ser.referral_view(ref))


@app.route("/api/referrals/<rid>/revoke", methods=["POST"])
def referral_revoke(rid):
    body = get_body()
    check_unknown_fields(body, [])
    uid, role = auth()
    require_roles(role, ["HospitalReferrer", "ProgramAdmin"])
    ref = get_or_404("referrals", rid, "referral")
    if role == "HospitalReferrer" and ref["hospital_id"] != uid:
        raise err(ERR_FORBIDDEN, "HospitalReferrer may only revoke own hospital's referrals")
    if ref["status"] != "VERIFIED":
        raise err(ERR_INVALID_STATE, "referral is not VERIFIED")
    ref["status"] = "REVOKED"
    bump(ref)
    freed = referral_chain_revocation(ref)
    # Hop 3: re-offer each freed room per house
    by_house = {}
    for room_id in freed:
        room = store.db["rooms"].get(room_id)
        if room:
            by_house.setdefault(room["house_id"], []).append(room_id)
    for house_id, room_ids in by_house.items():
        reoffer_freed_rooms(house_id, room_ids)
    return success(ser.referral_view(ref))


# ---------------------------------------------------------------------------
# Stay requests
# ---------------------------------------------------------------------------


@app.route("/api/stay-requests", methods=["POST"])
def stay_request_create():
    body = get_body()
    check_unknown_fields(
        body,
        [
            "family_id",
            "house_id",
            "referral_id",
            "expected_nights",
            "self_reported_acuity",
            "expected_family_version",
        ],
    )
    require_fields(
        body,
        [
            "family_id",
            "house_id",
            "referral_id",
            "expected_nights",
            "self_reported_acuity",
            "expected_family_version",
        ],
    )
    uid, role = auth()
    require_roles(role, ["FamilyContact", "HouseManager", "ProgramAdmin"])
    family_id = req_str(body, "family_id")
    house_id = req_str(body, "house_id")
    referral_id = req_str(body, "referral_id")
    expected_nights = req_int(body, "expected_nights")
    self_reported_acuity = req_enum(body, "self_reported_acuity", ACUITY_VALUES)
    expected_family_version = req_int(body, "expected_family_version")
    # Authorization: ownership
    if role == "FamilyContact" and family_id != uid:
        raise err(ERR_FORBIDDEN, "FamilyContact may only create requests for own family")
    # Existence + OCC
    fam = get_or_404("families", family_id, "family")
    house = get_or_404("houses", house_id, "house")
    ref = get_or_404("referrals", referral_id, "referral")
    if fam["version"] != expected_family_version:
        raise err(ERR_STALE_VERSION, "expected_family_version does not match the family's current version")
    # Business constraints then referential then temporal (pipeline order)
    if not (fam["distance_miles"] >= 50):
        raise err(ERR_DISTANCE_INELIGIBLE, "family distance_miles must be at least 50")
    if ref["family_id"] != family_id:
        raise err(ERR_REFERRAL_FAMILY_MISMATCH, "referral does not belong to this family")
    if expected_nights <= 0:
        raise err(ERR_INVALID_DATE_RANGE, "expected_nights must be at least 1")
    # Build the new request
    now_iso = store.now_iso()
    provisional = compute_score(fam["distance_miles"], self_reported_acuity, expected_nights)
    if ref["status"] == "VERIFIED":
        verification_status = "VERIFICATION_OK"
        verified_score = compute_score(fam["distance_miles"], ref["acuity_level"], expected_nights)
    else:
        verification_status = "UNVERIFIED"
        verified_score = None
    rec = new_record(
        {
            "family_id": family_id,
            "house_id": house_id,
            "referral_id": referral_id,
            "expected_nights": expected_nights,
            "self_reported_acuity": self_reported_acuity,
            "verification_status": verification_status,
            "assignment_status": "WAITLISTED",
            "provisional_score": provisional,
            "verified_score": verified_score,
            "offered_room_id": None,
            "offer_expires_at": None,
            "waitlisted_since": now_iso,
            "superseded_by_request_id": None,
        }
    )
    store.db["stay_requests"][rec["id"]] = rec
    # Create-with-supersede: cancel prior WAITLISTED/OFFERED requests of the family
    for other in store.db["stay_requests"].values():
        if (
            other["id"] != rec["id"]
            and other["family_id"] == family_id
            and other["assignment_status"] in ("WAITLISTED", "OFFERED")
        ):
            other["assignment_status"] = "CANCELLED"
            other["superseded_by_request_id"] = rec["id"]
            if other["offered_room_id"]:
                other["offered_room_id"] = None
                other["offer_expires_at"] = None
            bump(other)
    # Family version increments by 1
    bump(fam)
    return success(ser.stay_request_view(rec), status=201)


@app.route("/api/stay-requests/<rid>", methods=["GET"])
def stay_request_get(rid):
    uid, role = auth()
    require_roles(role, ["ProgramAdmin", "HouseManager", "FamilyContact"])
    req = get_or_404("stay_requests", rid, "stay request")
    if role == "FamilyContact" and req["family_id"] != uid:
        raise err(ERR_FORBIDDEN, "FamilyContact may only access own family's requests")
    return success(ser.stay_request_view(req))


@app.route("/api/stay-requests", methods=["GET"])
def stay_request_list():
    uid, role = auth()
    require_roles(role, ["ProgramAdmin", "HouseManager", "FamilyContact"])
    house_id = request.args.get("house_id")
    family_id = request.args.get("family_id")
    referral_id = request.args.get("referral_id")
    assignment_status = request.args.get("assignment_status")
    reqs = list(store.db["stay_requests"].values())
    if role == "FamilyContact":
        reqs = [q for q in reqs if q["family_id"] == uid]
    if house_id is not None:
        reqs = [q for q in reqs if q["house_id"] == house_id]
    if family_id is not None:
        reqs = [q for q in reqs if q["family_id"] == family_id]
    if referral_id is not None:
        reqs = [q for q in reqs if q["referral_id"] == referral_id]
    if assignment_status is not None:
        reqs = [q for q in reqs if q["assignment_status"] == assignment_status]
    reqs.sort(key=lambda x: x["_seq"])
    return list_response([ser.stay_request_view(q) for q in reqs])


@app.route("/api/stay-requests/<rid>/offer", methods=["POST"])
def stay_request_offer(rid):
    body = get_body()
    check_unknown_fields(body, ["room_id"])
    require_fields(body, ["room_id"])
    uid, role = auth()
    require_roles(role, ["HouseManager", "ProgramAdmin"])
    room_id = req_str(body, "room_id")
    req = get_or_404("stay_requests", rid, "stay request")
    room = get_or_404("rooms", room_id, "room")
    # State gate
    if req["assignment_status"] != "WAITLISTED":
        raise err(ERR_INVALID_STATE, "request is not WAITLISTED")
    if req["verification_status"] != "VERIFICATION_OK":
        raise err(ERR_REFERRAL_NOT_VERIFIED, "request verification is not VERIFICATION_OK")
    # Business: room occupancy/reservation conflicts before referential fit? PRD
    # pipeline order: business_constraint (6) then business_referential (7), but
    # the scaffold's offer transition preconditions list house match first; both
    # checks are evaluated here with referential mismatch surfaced when the room
    # belongs to a different house, and room-availability otherwise.
    if room["house_id"] != req["house_id"]:
        raise err(ERR_ROOM_HOUSE_MISMATCH, "room does not belong to the request's house")
    if room["status"] != "AVAILABLE" or room["occupied"] or room["id"] in reserved_room_ids():
        raise err(ERR_ROOM_NOT_AVAILABLE, "room is not available")
    req["assignment_status"] = "OFFERED"
    req["offered_room_id"] = room["id"]
    req["offer_expires_at"] = store.iso(store.now() + timedelta(hours=48))
    bump(req)
    return success(ser.stay_request_view(req))


@app.route("/api/stay-requests/<rid>/respond", methods=["POST"])
def stay_request_respond(rid):
    body = get_body()
    check_unknown_fields(body, ["decision", "expected_stay_request_version"])
    require_fields(body, ["decision", "expected_stay_request_version"])
    uid, role = auth()
    require_roles(role, ["FamilyContact"])
    decision = req_enum(body, "decision", ("ACCEPT", "DECLINE"))
    expected_version = req_int(body, "expected_stay_request_version")
    req = get_or_404("stay_requests", rid, "stay request")
    if req["family_id"] != uid:
        raise err(ERR_FORBIDDEN, "FamilyContact may only respond to own family's requests")
    # OCC gate precedes state evaluation
    if req["version"] != expected_version:
        raise err(ERR_STALE_VERSION, "expected_stay_request_version does not match the request's current version")
    if req["assignment_status"] != "OFFERED":
        raise err(ERR_INVALID_STATE, "request is not OFFERED")
    expires = store.parse_datetime(req["offer_expires_at"])
    if expires is not None and expires < store.now():
        raise err(ERR_OFFER_EXPIRED, "offer has expired")
    if decision == "ACCEPT":
        req["assignment_status"] = "ACCEPTED"
    else:  # DECLINE -> back to WAITLISTED, reservation released, no re-offer
        req["assignment_status"] = "WAITLISTED"
        req["offered_room_id"] = None
        req["offer_expires_at"] = None
        req["waitlisted_since"] = store.now_iso()
    bump(req)
    return success(ser.stay_request_view(req))


@app.route("/api/stay-requests/<rid>/cancel", methods=["POST"])
def stay_request_cancel(rid):
    body = get_body()
    check_unknown_fields(body, [])
    uid, role = auth()
    require_roles(role, ["FamilyContact", "HouseManager", "ProgramAdmin"])
    req = get_or_404("stay_requests", rid, "stay request")
    if role == "FamilyContact" and req["family_id"] != uid:
        raise err(ERR_FORBIDDEN, "FamilyContact may only cancel own family's requests")
    if req["assignment_status"] not in ("WAITLISTED", "OFFERED"):
        raise err(ERR_INVALID_STATE, "request cannot be cancelled from its current state")
    if req["assignment_status"] == "OFFERED":
        req["offered_room_id"] = None
        req["offer_expires_at"] = None
    req["assignment_status"] = "CANCELLED"
    bump(req)
    return success(ser.stay_request_view(req))


@app.route("/api/stay-requests/<rid>/check-in", methods=["POST"])
def stay_request_check_in(rid):
    body = get_body()
    check_unknown_fields(body, [])
    uid, role = auth()
    require_roles(role, ["HouseManager", "ProgramAdmin"])
    req = get_or_404("stay_requests", rid, "stay request")
    if req["assignment_status"] != "ACCEPTED":
        raise err(ERR_INVALID_STATE, "request is not ACCEPTED")
    room = store.db["rooms"].get(req["offered_room_id"])
    if room is None:
        raise err(ERR_NOT_FOUND, "room not found")
    if room["status"] != "AVAILABLE" or room["occupied"]:
        raise err(ERR_ROOM_NOT_AVAILABLE, "room is not available")
    check_in = store.today()
    expected_out = check_in + timedelta(days=req["expected_nights"])
    stay = new_record(
        {
            "stay_request_id": req["id"],
            "family_id": req["family_id"],
            "room_id": room["id"],
            "check_in_date": check_in.isoformat(),
            "expected_check_out_date": expected_out.isoformat(),
            "actual_check_out_date": None,
            "status": "ACTIVE",
            "approved_extension_count": 0,
            "pending_extension_nights": None,
            "transition_plan_notes": None,
            "review_reason": None,
        }
    )
    store.db["stays"][stay["id"]] = stay
    req["assignment_status"] = "FULFILLED"
    bump(req)
    room["occupied"] = True
    bump(room)
    return success(ser.stay_view(stay), status=201)


# ---------------------------------------------------------------------------
# Stays
# ---------------------------------------------------------------------------


def _stay_family_check(stay, uid, role):
    if role == "FamilyContact" and stay["family_id"] != uid:
        raise err(ERR_FORBIDDEN, "FamilyContact may only access own family's stays")


@app.route("/api/stays/<sid>", methods=["GET"])
def stay_get(sid):
    uid, role = auth()
    require_roles(role, ["ProgramAdmin", "HouseManager", "FamilyContact"])
    stay = get_or_404("stays", sid, "stay")
    _stay_family_check(stay, uid, role)
    return success(ser.stay_view(stay))


@app.route("/api/stays", methods=["GET"])
def stay_list():
    uid, role = auth()
    require_roles(role, ["ProgramAdmin", "HouseManager"])
    family_id = request.args.get("family_id")
    room_id = request.args.get("room_id")
    stay_request_id = request.args.get("stay_request_id")
    status = request.args.get("status")
    stays = list(store.db["stays"].values())
    if family_id is not None:
        stays = [s for s in stays if s["family_id"] == family_id]
    if room_id is not None:
        stays = [s for s in stays if s["room_id"] == room_id]
    if stay_request_id is not None:
        stays = [s for s in stays if s["stay_request_id"] == stay_request_id]
    if status is not None:
        stays = [s for s in stays if s["status"] == status]
    stays.sort(key=lambda x: x["_seq"])
    return list_response([ser.stay_view(s) for s in stays])


@app.route("/api/stays/<sid>/guests", methods=["POST"])
def guest_create(sid):
    body = get_body()
    check_unknown_fields(body, ["guest_name", "relationship", "is_overnight"])
    require_fields(body, ["guest_name", "relationship", "is_overnight"])
    uid, role = auth()
    require_roles(role, ["FamilyContact", "HouseManager"])
    guest_name = req_str(body, "guest_name")
    relationship = req_str(body, "relationship")
    is_overnight = req_bool(body, "is_overnight")
    stay = get_or_404("stays", sid, "stay")
    if role == "FamilyContact" and stay["family_id"] != uid:
        raise err(ERR_FORBIDDEN, "FamilyContact may only register guests on own family's stays")
    # State gate
    if stay["status"] != "ACTIVE":
        raise err(ERR_STAY_NOT_ACTIVE, "stay is not ACTIVE")
    # Safety gate: same-day PASS screening
    today = store.today().isoformat()
    cleared = any(
        sc["stay_id"] == sid
        and sc["result"] == "PASS"
        and sc["screened_at"][:10] == today
        for sc in store.db["screenings"].values()
    )
    if not cleared:
        raise err(ERR_SCREENING_NOT_CLEARED, "no same-day PASS illness screening for this stay")
    # Occupancy limit for overnight guests
    if is_overnight:
        room = store.db["rooms"].get(stay["room_id"])
        limit = room["occupancy_limit"] if room else 0
        current = sum(
            1
            for g in store.db["guests"].values()
            if g["stay_id"] == sid and g["is_overnight"] and g["status"] == "REGISTERED"
        )
        if current + 1 > limit:
            raise err(ERR_GUEST_LIMIT_EXCEEDED, "overnight guest limit would be exceeded")
    rec = new_record(
        {
            "stay_id": sid,
            "guest_name": guest_name,
            "relationship": relationship,
            "is_overnight": is_overnight,
            "status": "REGISTERED",
        }
    )
    store.db["guests"][rec["id"]] = rec
    return success(ser.guest_view(rec), status=201)


@app.route("/api/stays/<sid>/guests", methods=["GET"])
def guest_list(sid):
    uid, role = auth()
    require_roles(role, ["ProgramAdmin", "HouseManager", "FamilyContact"])
    stay = get_or_404("stays", sid, "stay")
    _stay_family_check(stay, uid, role)
    status = request.args.get("status")
    guests = [g for g in store.db["guests"].values() if g["stay_id"] == sid]
    if status is not None:
        guests = [g for g in guests if g["status"] == status]
    guests.sort(key=lambda x: x["_seq"])
    return list_response([ser.guest_view(g) for g in guests])


@app.route("/api/stays/<sid>/screenings", methods=["POST"])
def screening_create(sid):
    body = get_body()
    check_unknown_fields(body, ["temperature_tenths_c", "symptom_count", "notes"])
    require_fields(body, ["temperature_tenths_c", "symptom_count"])
    uid, role = auth()
    require_roles(role, ["HouseManager", "ProgramAdmin"])
    temperature_tenths_c = req_int(body, "temperature_tenths_c")
    symptom_count = req_int(body, "symptom_count")
    notes = opt_str(body, "notes", "")
    if symptom_count < 0:
        raise err(ERR_INVALID_REQUEST, "symptom_count must be >= 0")
    stay = get_or_404("stays", sid, "stay")
    if stay["status"] != "ACTIVE":
        raise err(ERR_STAY_NOT_ACTIVE, "stay is not ACTIVE")
    result = "PASS" if (symptom_count == 0 and temperature_tenths_c < 380) else "FAIL"
    rec = {
        "id": store.new_id(),
        "created_at": store.now_iso(),
        "_seq": store.next_seq(),
        "stay_id": sid,
        "temperature_tenths_c": temperature_tenths_c,
        "symptom_count": symptom_count,
        "notes": notes,
        "result": result,
        "screened_at": store.now_iso(),
    }
    store.db["screenings"][rec["id"]] = rec
    return success(ser.screening_view(rec), status=201)


@app.route("/api/stays/<sid>/screenings", methods=["GET"])
def screening_list(sid):
    uid, role = auth()
    require_roles(role, ["ProgramAdmin", "HouseManager", "FamilyContact"])
    stay = get_or_404("stays", sid, "stay")
    _stay_family_check(stay, uid, role)
    result = request.args.get("result")
    scrs = [sc for sc in store.db["screenings"].values() if sc["stay_id"] == sid]
    if result is not None:
        scrs = [sc for sc in scrs if sc["result"] == result]
    scrs.sort(key=lambda x: x["_seq"])
    return list_response([ser.screening_view(sc) for sc in scrs])


def _stay_referral(stay):
    req = store.db["stay_requests"].get(stay["stay_request_id"])
    if req is None:
        return None
    return store.db["referrals"].get(req["referral_id"])


@app.route("/api/stays/<sid>/request-extension", methods=["POST"])
def stay_request_extension(sid):
    body = get_body()
    check_unknown_fields(body, ["additional_nights"])
    require_fields(body, ["additional_nights"])
    uid, role = auth()
    require_roles(role, ["FamilyContact", "HouseManager"])
    additional_nights = req_int(body, "additional_nights")
    stay = get_or_404("stays", sid, "stay")
    if role == "FamilyContact" and stay["family_id"] != uid:
        raise err(ERR_FORBIDDEN, "FamilyContact may only extend own family's stays")
    if stay["status"] != "ACTIVE":
        raise err(ERR_STAY_NOT_ACTIVE, "stay is not ACTIVE")
    # Business constraint (priority 6) precedes the referral state check (priority 4/5)
    if stay["approved_extension_count"] >= 2:
        raise err(ERR_TRANSITION_PLAN_REQUIRED, "extension limit reached; a transition plan is required")
    ref = _stay_referral(stay)
    if ref is None or ref["status"] != "VERIFIED":
        raise err(ERR_REFERRAL_NOT_VERIFIED, "backing referral is not VERIFIED")
    if additional_nights <= 0:
        raise err(ERR_INVALID_DATE_RANGE, "additional_nights must be at least 1")
    stay["status"] = "UNDER_REVIEW"
    stay["pending_extension_nights"] = additional_nights
    stay["review_reason"] = "EXTENSION_REQUEST"
    bump(stay)
    return success(ser.stay_view(stay))


@app.route("/api/stays/<sid>/review", methods=["POST"])
def stay_review(sid):
    body = get_body()
    check_unknown_fields(body, ["decision", "transition_plan_notes", "relocation_room_id"])
    require_fields(body, ["decision"])
    uid, role = auth()
    require_roles(role, ["HouseManager", "ProgramAdmin"])
    decision = req_enum(
        body, "decision", ("APPROVE_EXTENSION", "DENY_EXTENSION", "PLAN_TRANSITION", "RELOCATE")
    )
    stay = get_or_404("stays", sid, "stay")
    if decision in ("APPROVE_EXTENSION", "DENY_EXTENSION", "PLAN_TRANSITION"):
        if stay["status"] not in ("UNDER_REVIEW", "TRANSITION_PLANNED"):
            raise err(ERR_INVALID_STATE, "stay is not under review")
        if decision == "APPROVE_EXTENSION":
            if stay["status"] == "UNDER_REVIEW":
                if stay["review_reason"] != "EXTENSION_REQUEST":
                    raise err(ERR_INVALID_STATE, "no extension request is pending on this stay")
                new_out = store.parse_date(stay["expected_check_out_date"]) + timedelta(
                    days=stay["pending_extension_nights"]
                )
                stay["expected_check_out_date"] = new_out.isoformat()
                stay["approved_extension_count"] += 1
                stay["pending_extension_nights"] = None
                stay["review_reason"] = None
                stay["status"] = "ACTIVE"
            else:  # TRANSITION_PLANNED — plan revised, stay continues
                if stay["approved_extension_count"] >= 2:
                    raise err(ERR_TRANSITION_PLAN_REQUIRED, "extension limit reached")
                ref = _stay_referral(stay)
                if ref is None or ref["status"] != "VERIFIED":
                    raise err(ERR_REFERRAL_NOT_VERIFIED, "backing referral is not VERIFIED")
                stay["transition_plan_notes"] = None
                stay["review_reason"] = None
                stay["status"] = "ACTIVE"
        elif decision == "DENY_EXTENSION":
            if stay["status"] != "UNDER_REVIEW":
                raise err(ERR_INVALID_STATE, "stay is not UNDER_REVIEW")
            stay["pending_extension_nights"] = None
            stay["review_reason"] = None
            stay["status"] = "ACTIVE"
        else:  # PLAN_TRANSITION
            if stay["status"] != "UNDER_REVIEW":
                raise err(ERR_INVALID_STATE, "stay is not UNDER_REVIEW")
            notes = body.get("transition_plan_notes")
            if notes is None:
                raise err(ERR_INVALID_REQUEST, "transition_plan_notes is required")
            if not isinstance(notes, str):
                raise err(ERR_INVALID_REQUEST, "transition_plan_notes must be a string")
            stay["transition_plan_notes"] = notes
            stay["pending_extension_nights"] = None
            stay["status"] = "TRANSITION_PLANNED"
    else:  # RELOCATE
        if stay["status"] != "RELOCATION_REQUIRED":
            raise err(ERR_INVALID_STATE, "stay does not require relocation")
        relocation_room_id = body.get("relocation_room_id")
        if relocation_room_id is None:
            raise err(ERR_INVALID_REQUEST, "relocation_room_id is required")
        if not isinstance(relocation_room_id, str):
            raise err(ERR_INVALID_REQUEST, "relocation_room_id must be a string")
        new_room = store.db["rooms"].get(relocation_room_id)
        if new_room is None:
            raise err(ERR_NOT_FOUND, "room not found")
        old_room = store.db["rooms"].get(stay["room_id"])
        old_house = old_room["house_id"] if old_room else None
        if new_room["house_id"] != old_house:
            raise err(ERR_ROOM_NOT_AVAILABLE, "relocation room must be in the same house")
        if (
            new_room["status"] != "AVAILABLE"
            or new_room["occupied"]
            or new_room["id"] in reserved_room_ids()
        ):
            raise err(ERR_ROOM_NOT_AVAILABLE, "relocation room is not available")
        stay["room_id"] = new_room["id"]
        new_room["occupied"] = True
        bump(new_room)
        stay["status"] = "ACTIVE"
    bump(stay)
    return success(ser.stay_view(stay))


@app.route("/api/stays/<sid>/check-out", methods=["POST"])
def stay_check_out(sid):
    body = get_body()
    check_unknown_fields(body, [])
    uid, role = auth()
    require_roles(role, ["HouseManager", "ProgramAdmin"])
    stay = get_or_404("stays", sid, "stay")
    if stay["status"] == "CHECKED_OUT":
        raise err(ERR_INVALID_STATE, "stay is already CHECKED_OUT")
    was_relocation = stay["status"] == "RELOCATION_REQUIRED"
    check_out_date = store.today()
    stay["actual_check_out_date"] = check_out_date.isoformat()
    stay["status"] = "CHECKED_OUT"
    bump(stay)
    # Hop 1: release the room (no-op when RELOCATION_REQUIRED already released it)
    room = store.db["rooms"].get(stay["room_id"])
    freed_room_id = None
    if room is not None and room["occupied"] and not was_relocation:
        room["occupied"] = False
        bump(room)
        freed_room_id = room["id"]
    # Hop 2: freed room triggers an immediate promotion at the house
    if freed_room_id is not None and room is not None:
        promote_one(room["house_id"], prefer_room_id=freed_room_id)
    # Hop 3: guests REGISTERED -> DEPARTED
    for g in store.db["guests"].values():
        if g["stay_id"] == sid and g["status"] == "REGISTERED":
            g["status"] = "DEPARTED"
            bump(g)
    # Hop 4: contribution settlement / forgiveness
    check_in = store.parse_date(stay["check_in_date"])
    actual_nights = (check_out_date - check_in).days if check_in else 0
    for c in store.db["contributions"].values():
        if c["stay_id"] == sid and c["status"] in ("OPEN", "PARTIALLY_PAID"):
            settled = c["per_night_cents"] * actual_nights
            c["settled_amount_cents"] = settled
            c["requested_amount_cents"] = settled
            c["forgiven_cents"] = settled - c["paid_cents"] - c["waived_cents"]
            c["outstanding_cents"] = 0
            c["status"] = "FORGIVEN"
            bump(c)
    return success(ser.stay_view(stay))


# ---------------------------------------------------------------------------
# Contribution requests
# ---------------------------------------------------------------------------

_HARDSHIP_FACTOR = {"NONE": "1.0", "PARTIAL": "0.5", "FULL": "0.0"}


def _per_night(nightly_rate_cents, hardship_tier):
    factor = Decimal(_HARDSHIP_FACTOR[hardship_tier])
    raw = Decimal(nightly_rate_cents) * factor
    return int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


@app.route("/api/stays/<sid>/contribution-requests", methods=["POST"])
def contribution_create(sid):
    body = get_body()
    check_unknown_fields(body, ["nightly_rate_cents", "planned_nights", "hardship_tier"])
    require_fields(body, ["nightly_rate_cents", "planned_nights", "hardship_tier"])
    uid, role = auth()
    require_roles(role, ["HouseManager", "ProgramAdmin"])
    nightly_rate_cents = req_int(body, "nightly_rate_cents")
    planned_nights = req_int(body, "planned_nights")
    hardship_tier = req_enum(body, "hardship_tier", ("NONE", "PARTIAL", "FULL"))
    if nightly_rate_cents <= 0:
        raise err(ERR_INVALID_REQUEST, "nightly_rate_cents must be > 0")
    if planned_nights <= 0:
        raise err(ERR_INVALID_REQUEST, "planned_nights must be > 0")
    stay = get_or_404("stays", sid, "stay")
    if stay["status"] == "CHECKED_OUT":
        raise err(ERR_INVALID_STATE, "stay is CHECKED_OUT")
    per_night = _per_night(nightly_rate_cents, hardship_tier)
    requested = per_night * planned_nights
    rec = new_record(
        {
            "stay_id": sid,
            "nightly_rate_cents": nightly_rate_cents,
            "planned_nights": planned_nights,
            "hardship_tier": hardship_tier,
            "per_night_cents": per_night,
            "requested_amount_cents": requested,
            "settled_amount_cents": None,
            "paid_cents": 0,
            "waived_cents": 0,
            "forgiven_cents": 0,
            "outstanding_cents": requested,
            "status": "OPEN",
        }
    )
    store.db["contributions"][rec["id"]] = rec
    return success(ser.contribution_view(rec), status=201)


@app.route("/api/stays/<sid>/contribution-requests", methods=["GET"])
def contribution_list(sid):
    uid, role = auth()
    require_roles(role, ["ProgramAdmin", "HouseManager", "FamilyContact"])
    stay = get_or_404("stays", sid, "stay")
    _stay_family_check(stay, uid, role)
    status = request.args.get("status")
    items = [c for c in store.db["contributions"].values() if c["stay_id"] == sid]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items.sort(key=lambda x: x["_seq"])
    return list_response([ser.contribution_view(c) for c in items])


def _contribution_family_check(c, uid, role):
    if role == "FamilyContact":
        stay = store.db["stays"].get(c["stay_id"])
        if stay is None or stay["family_id"] != uid:
            raise err(ERR_FORBIDDEN, "FamilyContact may only access own family's contribution requests")


@app.route("/api/contribution-requests/<cid>", methods=["GET"])
def contribution_get(cid):
    uid, role = auth()
    require_roles(role, ["ProgramAdmin", "HouseManager", "FamilyContact"])
    c = get_or_404("contributions", cid, "contribution request")
    _contribution_family_check(c, uid, role)
    return success(ser.contribution_view(c))


@app.route("/api/contribution-requests/<cid>/record-payment", methods=["POST"])
def contribution_record_payment(cid):
    body = get_body()
    check_unknown_fields(body, ["amount_cents"])
    require_fields(body, ["amount_cents"])
    uid, role = auth()
    require_roles(role, ["FamilyContact", "HouseManager"])
    amount_cents = req_int(body, "amount_cents")
    c = get_or_404("contributions", cid, "contribution request")
    _contribution_family_check(c, uid, role)
    if c["status"] not in ("OPEN", "PARTIALLY_PAID"):
        raise err(ERR_INVALID_STATE, "contribution request is not payable")
    if amount_cents <= 0:
        raise err(ERR_INVALID_REQUEST, "amount_cents must be > 0")
    if amount_cents > c["outstanding_cents"]:
        raise err(ERR_OVERPAYMENT, "payment amount exceeds outstanding_cents")
    c["paid_cents"] += amount_cents
    c["outstanding_cents"] = (
        c["requested_amount_cents"] - c["paid_cents"] - c["waived_cents"] - c["forgiven_cents"]
    )
    c["status"] = "PAID" if c["outstanding_cents"] == 0 else "PARTIALLY_PAID"
    bump(c)
    return success(ser.contribution_view(c))


@app.route("/api/contribution-requests/<cid>/waive", methods=["POST"])
def contribution_waive(cid):
    body = get_body()
    check_unknown_fields(body, [])
    uid, role = auth()
    require_roles(role, ["HouseManager", "ProgramAdmin"])
    c = get_or_404("contributions", cid, "contribution request")
    if c["status"] not in ("OPEN", "PARTIALLY_PAID"):
        raise err(ERR_INVALID_STATE, "contribution request cannot be waived")
    c["waived_cents"] = c["outstanding_cents"]
    c["outstanding_cents"] = 0
    c["status"] = "WAIVED"
    bump(c)
    return success(ser.contribution_view(c))


# ---------------------------------------------------------------------------
# Volunteer groups and meal shifts
# ---------------------------------------------------------------------------


@app.route("/api/volunteer-groups", methods=["POST"])
def volunteer_group_create():
    body = get_body()
    check_unknown_fields(body, ["group_name", "contact_email"])
    require_fields(body, ["group_name", "contact_email"])
    uid, role = auth()
    require_roles(role, ["VolunteerCoordinator", "ProgramAdmin"])
    group_name = req_str(body, "group_name")
    contact_email = req_str(body, "contact_email")
    rec = new_record(
        {"group_name": group_name, "contact_email": contact_email, "certified_until": None}
    )
    store.db["volunteer_groups"][rec["id"]] = rec
    return success(ser.volunteer_group_view(rec), status=201)


@app.route("/api/volunteer-groups/<gid>", methods=["GET"])
def volunteer_group_get(gid):
    uid, role = auth()
    require_roles(role, ["VolunteerCoordinator", "ProgramAdmin", "HouseManager"])
    g = get_or_404("volunteer_groups", gid, "volunteer group")
    return success(ser.volunteer_group_view(g))


@app.route("/api/volunteer-groups/<gid>/certify", methods=["POST"])
def volunteer_group_certify(gid):
    body = get_body()
    check_unknown_fields(body, ["certified_until"])
    require_fields(body, ["certified_until"])
    uid, role = auth()
    require_roles(role, ["ProgramAdmin"])
    g = get_or_404("volunteer_groups", gid, "volunteer group")
    d = req_date(body, "certified_until")
    g["certified_until"] = d.isoformat()
    bump(g)
    return success(ser.volunteer_group_view(g))


@app.route("/api/volunteer-groups/<gid>/meal-shifts", methods=["GET"])
def volunteer_group_meal_shifts(gid):
    uid, role = auth()
    require_roles(role, ["VolunteerCoordinator", "ProgramAdmin", "HouseManager"])
    get_or_404("volunteer_groups", gid, "volunteer group")
    status = request.args.get("status")
    shifts = [
        m for m in store.db["meal_shifts"].values() if m["claimed_by_group_id"] == gid
    ]
    if status is not None:
        shifts = [m for m in shifts if m["status"] == status]
    shifts.sort(key=lambda x: x["_seq"])
    return list_response([ser.meal_shift_view(m) for m in shifts])


@app.route("/api/houses/<hid>/meal-shifts", methods=["POST"])
def meal_shift_create(hid):
    body = get_body()
    check_unknown_fields(body, ["shift_date", "meal_type", "servings_planned"])
    require_fields(body, ["shift_date", "meal_type", "servings_planned"])
    uid, role = auth()
    require_roles(role, ["HouseManager", "ProgramAdmin"])
    shift_date = req_date(body, "shift_date")
    meal_type = req_enum(body, "meal_type", ("BREAKFAST", "LUNCH", "DINNER"))
    servings_planned = req_int(body, "servings_planned")
    if servings_planned <= 0:
        raise err(ERR_INVALID_REQUEST, "servings_planned must be > 0")
    get_or_404("houses", hid, "house")
    for m in store.db["meal_shifts"].values():
        if (
            m["house_id"] == hid
            and m["shift_date"] == shift_date.isoformat()
            and m["meal_type"] == meal_type
        ):
            raise err(ERR_DUPLICATE_MEAL_SHIFT, "a meal shift already exists for this house, date and meal type")
    rec = new_record(
        {
            "house_id": hid,
            "shift_date": shift_date.isoformat(),
            "meal_type": meal_type,
            "servings_planned": servings_planned,
            "status": "OPEN",
            "claimed_by_group_id": None,
            "servings_served": None,
            "food_safety_attested": None,
        }
    )
    store.db["meal_shifts"][rec["id"]] = rec
    return success(ser.meal_shift_view(rec), status=201)


@app.route("/api/houses/<hid>/meal-shifts", methods=["GET"])
def meal_shift_list(hid):
    uid, role = auth()
    require_roles(role, ["HouseManager", "ProgramAdmin", "VolunteerCoordinator"])
    get_or_404("houses", hid, "house")
    shift_date = request.args.get("shift_date")
    status = request.args.get("status")
    shifts = [m for m in store.db["meal_shifts"].values() if m["house_id"] == hid]
    if shift_date is not None:
        shifts = [m for m in shifts if m["shift_date"] == shift_date]
    if status is not None:
        shifts = [m for m in shifts if m["status"] == status]
    shifts.sort(key=lambda x: x["_seq"])
    return list_response([ser.meal_shift_view(m) for m in shifts])


@app.route("/api/meal-shifts/<mid>/claim", methods=["POST"])
def meal_shift_claim(mid):
    body = get_body()
    check_unknown_fields(body, ["volunteer_group_id"])
    require_fields(body, ["volunteer_group_id"])
    uid, role = auth()
    require_roles(role, ["VolunteerCoordinator"])
    group_id = req_str(body, "volunteer_group_id")
    m = get_or_404("meal_shifts", mid, "meal shift")
    group = get_or_404("volunteer_groups", group_id, "volunteer group")
    if m["status"] != "OPEN":
        raise err(ERR_INVALID_STATE, "meal shift is not OPEN")
    # Safety gates
    if group["certified_until"] is None:
        raise err(ERR_FOOD_SAFETY_CERT_REQUIRED, "volunteer group is not certified")
    if group["certified_until"] < m["shift_date"]:
        raise err(ERR_FOOD_SAFETY_CERT_EXPIRED, "certification does not cover the shift date")
    m["status"] = "CLAIMED"
    m["claimed_by_group_id"] = group["id"]
    bump(m)
    return success(ser.meal_shift_view(m))


@app.route("/api/meal-shifts/<mid>/complete", methods=["POST"])
def meal_shift_complete(mid):
    body = get_body()
    check_unknown_fields(body, ["servings_served", "food_safety_attested"])
    require_fields(body, ["servings_served", "food_safety_attested"])
    uid, role = auth()
    require_roles(role, ["VolunteerCoordinator", "HouseManager"])
    servings_served = req_int(body, "servings_served")
    food_safety_attested = req_bool(body, "food_safety_attested")
    m = get_or_404("meal_shifts", mid, "meal shift")
    if m["status"] != "CLAIMED":
        raise err(ERR_INVALID_STATE, "meal shift is not CLAIMED")
    if food_safety_attested is not True:
        raise err(ERR_FOOD_SAFETY_ATTESTATION_REQUIRED, "food-safety attestation is required")
    if servings_served <= 0:
        raise err(ERR_INVALID_REQUEST, "servings_served must be > 0")
    m["status"] = "COMPLETED"
    m["servings_served"] = servings_served
    m["food_safety_attested"] = True
    bump(m)
    return success(ser.meal_shift_view(m))


@app.route("/api/meal-shifts/<mid>/cancel", methods=["POST"])
def meal_shift_cancel(mid):
    body = get_body()
    check_unknown_fields(body, [])
    uid, role = auth()
    require_roles(role, ["VolunteerCoordinator", "HouseManager", "ProgramAdmin"])
    m = get_or_404("meal_shifts", mid, "meal shift")
    if m["status"] == "CLAIMED":
        m["status"] = "OPEN"
        m["claimed_by_group_id"] = None
    elif m["status"] == "OPEN":
        m["status"] = "CANCELLED"
    else:
        raise err(ERR_INVALID_STATE, "meal shift cannot be cancelled from its current state")
    bump(m)
    return success(ser.meal_shift_view(m))


# ---------------------------------------------------------------------------
# Care space bookings
# ---------------------------------------------------------------------------


@app.route("/api/care-spaces/<cid>", methods=["GET"])
def care_space_get(cid):
    uid, role = auth()
    require_roles(role, list(ALL_ROLES))
    cs = get_or_404("care_spaces", cid, "care space")
    return success(ser.care_space_view(cs))


@app.route("/api/care-spaces/<cid>/bookings", methods=["POST"])
def booking_create(cid):
    body = get_body()
    check_unknown_fields(body, ["family_id", "start_at", "end_at", "party_size"])
    require_fields(body, ["family_id", "start_at", "end_at", "party_size"])
    uid, role = auth()
    require_roles(role, ["FamilyContact", "HouseManager"])
    family_id = req_str(body, "family_id")
    start_at = req_datetime(body, "start_at")
    end_at = req_datetime(body, "end_at")
    party_size = req_int(body, "party_size")
    if party_size <= 0:
        raise err(ERR_INVALID_REQUEST, "party_size must be > 0")
    if role == "FamilyContact" and family_id != uid:
        raise err(ERR_FORBIDDEN, "FamilyContact may only book for own family")
    cs = get_or_404("care_spaces", cid, "care space")
    fam = get_or_404("families", family_id, "family")
    # Business constraint: capacity
    if party_size > cs["capacity"]:
        raise err(ERR_CAPACITY_EXCEEDED, "party_size exceeds the care space capacity")
    # Business constraint: buffered overlap against CONFIRMED bookings
    for b in store.db["bookings"].values():
        if b["care_space_id"] != cid or b["status"] != "CONFIRMED":
            continue
        b_start = store.parse_datetime(b["start_at"])
        b_end = store.parse_datetime(b["end_at"]) + timedelta(minutes=30)
        if start_at < b_end and end_at > b_start:
            raise err(ERR_CARE_SPACE_CONFLICT, "booking overlaps an existing booking's buffered window")
    # Referential: family holds a VERIFIED referral at this hospital
    has_verified = any(
        r["family_id"] == family_id
        and r["hospital_id"] == cs["hospital_id"]
        and r["status"] == "VERIFIED"
        for r in store.db["referrals"].values()
    )
    if not has_verified:
        raise err(ERR_BOOKING_REFERRAL_MISMATCH, "family lacks a VERIFIED referral at this hospital")
    # Temporal
    if not (end_at > start_at):
        raise err(ERR_INVALID_DATE_RANGE, "end_at must be strictly after start_at")
    rec = new_record(
        {
            "care_space_id": cid,
            "family_id": fam["id"],
            "start_at": store.iso(start_at),
            "end_at": store.iso(end_at),
            "party_size": party_size,
            "status": "CONFIRMED",
        }
    )
    store.db["bookings"][rec["id"]] = rec
    return success(ser.booking_view(rec), status=201)


@app.route("/api/care-spaces/<cid>/bookings", methods=["GET"])
def booking_list(cid):
    uid, role = auth()
    require_roles(role, list(ALL_ROLES))
    get_or_404("care_spaces", cid, "care space")
    status = request.args.get("status")
    books = [b for b in store.db["bookings"].values() if b["care_space_id"] == cid]
    if status is not None:
        books = [b for b in books if b["status"] == status]
    books.sort(key=lambda x: x["_seq"])
    return list_response([ser.booking_view(b) for b in books])


@app.route("/api/care-space-bookings/<bid>/cancel", methods=["POST"])
def booking_cancel(bid):
    body = get_body()
    check_unknown_fields(body, [])
    uid, role = auth()
    require_roles(role, ["FamilyContact", "HouseManager"])
    b = get_or_404("bookings", bid, "booking")
    if role == "FamilyContact" and b["family_id"] != uid:
        raise err(ERR_FORBIDDEN, "FamilyContact may only cancel own family's bookings")
    if b["status"] != "CONFIRMED":
        raise err(ERR_INVALID_STATE, "booking is not CONFIRMED")
    b["status"] = "CANCELLED"
    bump(b)
    return success(ser.booking_view(b))


# ---------------------------------------------------------------------------
# In-kind donations
# ---------------------------------------------------------------------------


@app.route("/api/houses/<hid>/in-kind-donations", methods=["POST"])
def donation_create(hid):
    body = get_body()
    check_unknown_fields(body, ["donor_name", "supply_category", "quantity_received"])
    require_fields(body, ["donor_name", "supply_category", "quantity_received"])
    uid, role = auth()
    require_roles(role, ["HouseManager", "ProgramAdmin"])
    donor_name = req_str(body, "donor_name")
    supply_category = req_enum(
        body, "supply_category", ("HYGIENE_KIT", "PANTRY_STAPLE", "CLEANING_SUPPLY", "BABY_SUPPLY")
    )
    quantity_received = req_int(body, "quantity_received")
    if quantity_received <= 0:
        raise err(ERR_INVALID_REQUEST, "quantity_received must be > 0")
    get_or_404("houses", hid, "house")
    rec = new_record(
        {
            "house_id": hid,
            "donor_name": donor_name,
            "supply_category": supply_category,
            "quantity_received": quantity_received,
            "quantity_distributed": 0,
            "status": "RECEIVED",
        }
    )
    store.db["donations"][rec["id"]] = rec
    return success(ser.donation_view(rec), status=201)


@app.route("/api/houses/<hid>/in-kind-donations", methods=["GET"])
def donation_list(hid):
    uid, role = auth()
    require_roles(role, ["HouseManager", "ProgramAdmin"])
    get_or_404("houses", hid, "house")
    supply_category = request.args.get("supply_category")
    status = request.args.get("status")
    items = [d for d in store.db["donations"].values() if d["house_id"] == hid]
    if supply_category is not None:
        items = [d for d in items if d["supply_category"] == supply_category]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    items.sort(key=lambda x: x["_seq"])
    return list_response([ser.donation_view(d) for d in items])


@app.route("/api/in-kind-donations/<did>/distribute", methods=["POST"])
def donation_distribute(did):
    body = get_body()
    check_unknown_fields(body, ["quantity"])
    require_fields(body, ["quantity"])
    uid, role = auth()
    require_roles(role, ["HouseManager", "ProgramAdmin"])
    quantity = req_int(body, "quantity")
    d = get_or_404("donations", did, "donation")
    if d["status"] == "DEPLETED":
        raise err(ERR_DONATION_DEPLETED, "donation is DEPLETED")
    if quantity <= 0:
        raise err(ERR_INVALID_REQUEST, "quantity must be > 0")
    remaining = d["quantity_received"] - d["quantity_distributed"]
    if quantity > remaining:
        raise err(ERR_INSUFFICIENT_SUPPLY, "distribution quantity exceeds remaining units")
    d["quantity_distributed"] += quantity
    d["status"] = (
        "DEPLETED" if d["quantity_distributed"] == d["quantity_received"] else "PARTIALLY_DISTRIBUTED"
    )
    bump(d)
    return success(ser.donation_view(d))


# ---------------------------------------------------------------------------
# Ops sweeps
# ---------------------------------------------------------------------------


@app.route("/api/houses/<hid>/run-assignment-sweep", methods=["POST"])
def run_assignment_sweep(hid):
    body = get_body()
    check_unknown_fields(body, [])
    uid, role = auth()
    require_roles(role, ["HouseManager", "ProgramAdmin"])
    get_or_404("houses", hid, "house")
    now = store.now()
    expired_offer_ids = []
    expired_referral_ids = []
    promoted_request_ids = []
    # Step 1: expire stale offers at this house
    for req in store.db["stay_requests"].values():
        if (
            req["house_id"] == hid
            and req["assignment_status"] == "OFFERED"
            and req["offer_expires_at"]
        ):
            exp = store.parse_datetime(req["offer_expires_at"])
            if exp is not None and exp < now:
                req["assignment_status"] = "WAITLISTED"
                req["offered_room_id"] = None
                req["offer_expires_at"] = None
                req["waitlisted_since"] = store.now_iso()
                bump(req)
                expired_offer_ids.append(req["id"])
    # Step 2: expire stale referrals (those linked to requests of this house)
    referral_ids_at_house = {
        req["referral_id"]
        for req in store.db["stay_requests"].values()
        if req["house_id"] == hid
    }
    freed_by_house = {}
    for ref in list(store.db["referrals"].values()):
        if ref["status"] == "VERIFIED" and ref["valid_until"]:
            vu = store.parse_datetime(ref["valid_until"])
            if vu is not None and vu < now:
                ref["status"] = "EXPIRED"
                bump(ref)
                expired_referral_ids.append(ref["id"])
                freed = referral_chain_revocation(ref)
                for room_id in freed:
                    room = store.db["rooms"].get(room_id)
                    if room:
                        freed_by_house.setdefault(room["house_id"], []).append(room_id)
    # Hop 3 of each expiry cascade: re-offer freed rooms
    for house_id, room_ids in freed_by_house.items():
        for room_id in room_ids:
            promoted = promote_one(house_id, prefer_room_id=room_id)
            if promoted and house_id == hid:
                promoted_request_ids.append(promoted["id"])
    # Step 3+4: snapshot capacity at this house and promote in ranking order
    capacity = len(eligible_rooms(hid))
    while capacity > 0:
        promoted = promote_one(hid)
        if promoted is None:
            break
        promoted_request_ids.append(promoted["id"])
        capacity -= 1
    return success(
        {
            "expired_offer_ids": expired_offer_ids,
            "expired_referral_ids": expired_referral_ids,
            "promoted_request_ids": promoted_request_ids,
        }
    )


@app.route("/api/houses/<hid>/run-stay-review-sweep", methods=["POST"])
def run_stay_review_sweep(hid):
    body = get_body()
    check_unknown_fields(body, [])
    uid, role = auth()
    require_roles(role, ["HouseManager", "ProgramAdmin"])
    get_or_404("houses", hid, "house")
    today = store.today()
    flagged = []
    for stay in store.db["stays"].values():
        if stay["status"] != "ACTIVE":
            continue
        room = store.db["rooms"].get(stay["room_id"])
        if room is None or room["house_id"] != hid:
            continue
        check_in = store.parse_date(stay["check_in_date"])
        if check_in is None:
            continue
        nights = (today - check_in).days
        if nights >= 21:
            stay["status"] = "UNDER_REVIEW"
            stay["review_reason"] = "STAY_LENGTH"
            bump(stay)
            flagged.append(stay["id"])
    return success({"flagged_stay_ids": flagged})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
