"""Enrolment, invitation response, confirmation, cancellation, air, survey."""

from flask import Blueprint

import calc
import cascades
import serialize
from auth import ALL_ROLES, authorize, own_qualifier, own_registration
from envelope import created, ok, paginate
from errors import fail
from gates import filtered, lookup, program_gate
from schema import (MISSING, body, f_bool, f_dt, f_enum, f_id, f_int, f_str,
                    raw_fk, validate)
from store import db, norm_dt, parse_dt

bp = Blueprint("registrations", __name__)

KINDS = ("WINNER", "GUEST")
RESPONSES = ("ACCEPT", "DECLINE")
AIR_ACTIONS = ("REQUEST", "TICKET", "CHANGE")
CABINS = ("ECONOMY", "PREMIUM_ECONOMY", "BUSINESS")
NON_TERMINAL_AIR = ("REQUESTED", "TICKETED", "CHANGE_PENDING")


@bp.post("/registrations")
def create_registration():
    actor = authorize("TravelDesk", "Participant")
    payload = body()

    # 5 - body foreign keys, in the order the input declares them.
    qualifier_id = raw_fk(payload, "qualifier_id")
    qualifier = lookup("qualifier", qualifier_id) if qualifier_id is not None else None
    link_id = raw_fk(payload, "guest_of_registration_id")
    if link_id is not None:
        lookup("registration", link_id)

    # 6 - participant ownership.
    if qualifier is not None:
        own_qualifier(actor, qualifier["id"])

    # 7 - request schema.
    data = validate(payload, [
        f_id("qualifier_id"),
        f_enum("registration_kind", KINDS),
        f_id("guest_of_registration_id", required=False),
        f_dt("arrival_date"),
        f_dt("departure_date"),
        f_int("rooms", required=False, default=1, minimum=1, maximum=3),
        f_int("expected_program_version"),
    ])
    qualifier = lookup("qualifier", data["qualifier_id"])
    own_qualifier(actor, qualifier["id"])
    program = db.programs.get(qualifier["program_id"])

    # 9 - stale parent version.
    if data["expected_program_version"] != program["version"]:
        fail("ERR_STALE_PROGRAM_VERSION")

    # 10 / 11 - lifecycle and qualifier award state.
    program_gate(program, ("REGISTRATION_OPEN",))
    if qualifier["award_status"] != "NOTIFIED":
        fail("ERR_QUALIFIER_STATE_INVALID")

    kind = data["registration_kind"]
    link = data.get("guest_of_registration_id")

    # 20 - guest allowance, checked before linkage.
    if kind == "GUEST":
        tier = db.award_tiers.get(qualifier.get("assigned_tier_id"))
        allowance = tier["guest_allowance"] if tier else 0
        live_guests = sum(1 for r in db.registrations.values()
                          if r["qualifier_id"] == qualifier["id"]
                          and r["registration_kind"] == "GUEST"
                          and r["attendance_status"] != "CANCELLED")
        if live_guests + 1 > allowance:
            fail("ERR_GUEST_ALLOWANCE_EXCEEDED")

    # 21 - guest linkage.
    if kind == "GUEST":
        if link is None:
            fail("ERR_GUEST_LINK_INVALID")
        target = db.registrations.get(link)
        if (target is None
                or target["registration_kind"] != "WINNER"
                or target["attendance_status"] == "CANCELLED"
                or target["qualifier_id"] != qualifier["id"]):
            fail("ERR_GUEST_LINK_INVALID")
    elif link is not None:
        fail("ERR_GUEST_LINK_INVALID")

    # 22 - one live WINNER seat per qualifier.
    if kind == "WINNER":
        for existing in db.registrations.values():
            if (existing["qualifier_id"] == qualifier["id"]
                    and existing["registration_kind"] == "WINNER"
                    and existing["attendance_status"] != "CANCELLED"):
                fail("ERR_DUPLICATE_WINNER_REGISTRATION")

    # 23 - ordered date pair.
    if not (parse_dt(data["departure_date"]) > parse_dt(data["arrival_date"])):
        fail("ERR_INVALID_DATE_RANGE")

    row = {
        "program_id": qualifier["program_id"],
        "qualifier_id": qualifier["id"],
        "registration_kind": kind,
        "guest_of_registration_id": link,
        "attendance_status": "INVITED",
        "arrival_date": norm_dt(data["arrival_date"]),
        "departure_date": norm_dt(data["departure_date"]),
        "rooms": data["rooms"],
        "room_nights": 0,
        "waiver_on_file": False,
        "air_status": "NOT_REQUESTED",
        "air_cabin_class": None,
        "air_deviation_pre_days": 0,
        "air_deviation_post_days": 0,
        "air_base_fare_cents": 0,
        "air_upgrade_cost_cents": 0,
        "air_deviation_fee_cents": 0,
        "air_change_count": 0,
        "air_change_fee_total_cents": 0,
        "cost_cents": 0,
        "satisfaction_score": None,
        "cancellation_reason": None,
    }
    db.stamp_new(row)
    db.registrations[row["id"]] = row
    db.touch(program)
    return created(serialize.registration(row))


@bp.get("/registrations/<registration_id>")
def read_registration(registration_id):
    actor = authorize(*ALL_ROLES)
    registration = lookup("registration", registration_id)
    own_registration(actor, registration)
    return ok(serialize.registration(registration))


@bp.get("/registrations")
def list_registrations():
    authorize(*ALL_ROLES)
    rows = filtered(db.ordered(db.registrations), [
        ("program_id", "program_id"),
        ("qualifier_id", "qualifier_id"),
        ("guest_of_registration_id", "guest_of_registration_id"),
        ("registration_kind", "registration_kind"),
        ("attendance_status", "attendance_status"),
        ("air_status", "air_status"),
    ])
    return paginate(rows, serialize.registration)


@bp.post("/registrations/<registration_id>/respond")
def respond(registration_id):
    actor = authorize("Participant")
    registration = lookup("registration", registration_id)
    own_registration(actor, registration)
    data = validate(body(), [
        f_enum("response", RESPONSES),
        f_bool("waiver_signed", required=False),
    ])
    program_gate(db.programs.get(registration["program_id"]), ("REGISTRATION_OPEN",))

    if registration["attendance_status"] != "INVITED":
        fail("ERR_REGISTRATION_STATE_INVALID")

    if data["response"] == "ACCEPT":
        registration["attendance_status"] = "ACCEPTED"
        if data.get("waiver_signed") is True:
            registration["waiver_on_file"] = True
    else:
        registration["attendance_status"] = "DECLINED"
        if registration["air_status"] in NON_TERMINAL_AIR:
            registration["air_status"] = "VOIDED"

    db.touch(registration)
    return ok(serialize.registration(registration))


@bp.post("/registrations/<registration_id>/confirm")
def confirm(registration_id):
    authorize("TravelDesk")
    registration = lookup("registration", registration_id)
    body()
    program = db.programs.get(registration["program_id"])
    program_gate(program, ("REGISTRATION_OPEN",))

    if registration["attendance_status"] != "ACCEPTED":
        fail("ERR_REGISTRATION_STATE_INVALID")

    hotels = [c for c in db.supplier_contracts.values()
              if c["program_id"] == program["id"]
              and c["supplier_kind"] == "HOTEL"
              and c["status"] == "EXECUTED"]
    if len(hotels) != 1:
        fail("ERR_NO_EXECUTED_HOTEL_CONTRACT")
    contract = hotels[0]

    arrival = parse_dt(registration["arrival_date"])
    departure = parse_dt(registration["departure_date"])
    if arrival < parse_dt(contract["stay_start_at"]) or departure > parse_dt(contract["stay_end_at"]):
        fail("ERR_STAY_WINDOW_VIOLATION")

    if not calc.per_night_occupancy_ok(db, contract, registration):
        fail("ERR_ROOM_BLOCK_EXHAUSTED")

    calc.program_budget_rollup(db, program)
    if program["budget_headroom_cents"] < registration["cost_cents"]:
        fail("ERR_BUDGET_HEADROOM_EXCEEDED")

    registration["attendance_status"] = "CONFIRMED"
    registration["room_nights"] = calc.registration_room_nights(registration)
    db.touch(registration)

    calc.room_night_ledger(db, contract)
    calc.program_budget_rollup(db, program)

    if registration["registration_kind"] == "WINNER":
        qualifier = db.qualifiers.get(registration["qualifier_id"])
        if qualifier is not None and qualifier["award_status"] == "NOTIFIED":
            qualifier["award_status"] = "REGISTERED"
            db.touch(qualifier)
            calc.program_budget_rollup(db, program)

    return ok(serialize.registration(registration))


@bp.post("/registrations/<registration_id>/cancel")
def cancel(registration_id):
    actor = authorize("TravelDesk", "Participant")
    registration = lookup("registration", registration_id)
    own_registration(actor, registration)
    data = validate(body(), [f_str("cancellation_reason")])
    program_gate(db.programs.get(registration["program_id"]),
                 ("REGISTRATION_OPEN", "ONSITE"))

    if registration["attendance_status"] not in ("INVITED", "ACCEPTED", "CONFIRMED"):
        fail("ERR_REGISTRATION_STATE_INVALID")

    cascades.cancel_registration(registration, data["cancellation_reason"])
    return ok(serialize.registration(registration))


@bp.post("/registrations/<registration_id>/air")
def air(registration_id):
    authorize("TravelDesk")
    registration = lookup("registration", registration_id)
    data = validate(body(), [
        f_enum("action", AIR_ACTIONS),
        f_enum("cabin_class", CABINS, required=False),
        f_int("deviation_pre_days", required=False, minimum=0, maximum=7),
        f_int("deviation_post_days", required=False, minimum=0, maximum=7),
        f_int("base_fare_cents", required=False, minimum=0),
    ])
    program = db.programs.get(registration["program_id"])
    program_gate(program, ("REGISTRATION_OPEN", "ONSITE"))

    action = data["action"]
    current = registration["air_status"]

    # 11 - the air axis itself.
    if action == "REQUEST":
        if current != "NOT_REQUESTED":
            fail("ERR_AIR_STATE_INVALID")
    elif action == "TICKET":
        if current not in ("REQUESTED", "CHANGE_PENDING"):
            fail("ERR_AIR_STATE_INVALID")
    else:
        if current != "TICKETED":
            fail("ERR_AIR_STATE_INVALID")

    # The attendance precondition applies to opening an air record.
    if action == "REQUEST" and registration["attendance_status"] not in (
            "INVITED", "ACCEPTED", "CONFIRMED"):
        fail("ERR_REGISTRATION_STATE_INVALID")

    # 25 - deviation ceiling, on the request and on a change's revised values.
    if action in ("REQUEST", "CHANGE"):
        pre = data.get("deviation_pre_days", registration["air_deviation_pre_days"])
        post = data.get("deviation_post_days", registration["air_deviation_post_days"])
        if pre + post > calc.DEVIATION_MAX_DAYS_TOTAL:
            fail("ERR_DEVIATION_LIMIT_EXCEEDED")

    if action in ("REQUEST", "CHANGE"):
        if "cabin_class" in data:
            registration["air_cabin_class"] = data["cabin_class"]
        if "deviation_pre_days" in data:
            registration["air_deviation_pre_days"] = data["deviation_pre_days"]
        if "deviation_post_days" in data:
            registration["air_deviation_post_days"] = data["deviation_post_days"]
        if "base_fare_cents" in data:
            registration["air_base_fare_cents"] = data["base_fare_cents"]

    if action == "REQUEST":
        registration["air_status"] = "REQUESTED"
    elif action == "TICKET":
        if current == "CHANGE_PENDING":
            registration["air_change_count"] += 1
        registration["air_status"] = "TICKETED"
    else:
        registration["air_status"] = "CHANGE_PENDING"

    calc.air_cost_and_change_fee(db, registration)
    db.touch(registration)

    if registration["attendance_status"] in ("CONFIRMED", "TRAVELLED"):
        calc.program_budget_rollup(db, program)

    return ok(serialize.registration(registration))


@bp.post("/registrations/<registration_id>/survey")
def survey(registration_id):
    actor = authorize("Participant", "TravelDesk")
    registration = lookup("registration", registration_id)
    own_registration(actor, registration)
    data = validate(body(), [f_int("satisfaction_score", minimum=1, maximum=10)])
    program_gate(db.programs.get(registration["program_id"]), ("ONSITE", "RECONCILED"))

    if registration["attendance_status"] not in ("CONFIRMED", "TRAVELLED"):
        fail("ERR_REGISTRATION_STATE_INVALID")

    registration["satisfaction_score"] = data["satisfaction_score"]
    db.touch(registration)
    return ok(serialize.registration(registration))
