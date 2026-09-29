from flask import Blueprint

import calc
import db
import services
from core import (actor, auth, body, dec, fail, fmt_date, get_instant, get_int, get_num,
                  get_num_list, get_str, now_date, now_instant, ok, pagination, paginate, q_enum,
                  q_str, sorted_rows)

bp = Blueprint("bookings", __name__)

STATUSES = ("RESERVED", "CONFIRMED", "IN_TRANSIT", "DELIVERED", "ABORTED")
LIVE_BOOKINGS = ("RESERVED", "CONFIRMED", "IN_TRANSIT")


@bp.post("/shipment-bookings")
@auth("Registrar")
def create_booking():
    b = body()
    agreement_id = get_str(b, "transfer_agreement_id", required=True)
    carrier_code = get_str(b, "carrier_code", required=True)
    crate_serial = get_str(b, "crate_serial", required=True)
    departure, departure_raw = get_instant(b, "departure_utc", required=True)
    arrival, arrival_raw = get_instant(b, "arrival_utc", required=True)
    temp_min = get_num(b, "temp_min_c", required=True)
    temp_max = get_num(b, "temp_max_c", required=True)
    expected_version = get_int(b, "expected_transfer_agreement_version", required=True)
    if not arrival > departure:
        fail("ERR_INVALID_REQUEST", "arrival_utc must be strictly after departure_utc.")
    if not temp_max > temp_min:
        fail("ERR_INVALID_REQUEST", "temp_max_c must be strictly greater than temp_min_c.")

    agreement = db.get_agreement(agreement_id)
    services.party_check(agreement, actor())

    if expected_version != agreement["version"]:
        fail("ERR_STALE_AGREEMENT_VERSION")

    if agreement["status"] != "EXECUTED":
        fail("ERR_AGREEMENT_INVALID_STATE")

    overlapping = 0
    for other in db.bookings.values():
        if other["carrier_code"] != carrier_code or other["status"] not in LIVE_BOOKINGS:
            continue
        other_dep = services.as_instant(other["departure_utc"])
        other_arr = services.as_instant(other["arrival_utc"])
        if other_dep <= arrival and departure <= other_arr:
            overlapping += 1
    if overlapping >= calc.CARRIER_OVERLAP_LIMIT:
        fail("ERR_CARRIER_CAPACITY_EXCEEDED")

    for other in services.bookings_of(agreement_id):
        if other["status"] == "RESERVED":
            other["status"] = "ABORTED"
            db.touch(other)

    booking = db.insert(db.bookings, {
        "transfer_agreement_id": agreement_id,
        "carrier_code": carrier_code,
        "crate_serial": crate_serial,
        "departure_utc": departure_raw,
        "arrival_utc": arrival_raw,
        "temp_min_c": temp_min,
        "temp_max_c": temp_max,
        "temperature_samples": None,
        "thermal_excursion_minutes": 0,
        "status": "RESERVED",
        "departed_at": None,
        "delivered_at": None,
    })
    db.touch(agreement)
    return ok(services.booking_out(booking), 201)


@bp.post("/shipment-bookings/<booking_id>/confirm")
@auth("Registrar")
def confirm_booking(booking_id):
    b = body()
    get_str(b, "confirmation_note")
    booking = db.get_booking(booking_id)
    agreement = db.agreements.get(booking["transfer_agreement_id"])
    services.party_check(agreement, actor(), "sending_institution_id")

    if booking["status"] != "RESERVED":
        fail("ERR_BOOKING_INVALID_STATE")

    animal = db.animals.get(agreement["animal_id"])
    departure_date = services.as_instant(booking["departure_utc"]).date()
    arrival_date = services.as_instant(booking["arrival_utc"]).date()

    # rung 11 -- crate conditioning: completeness first, then recency
    if services.crate_count(animal["id"]) < calc.MIN_CRATE_SESSIONS:
        fail("ERR_CRATE_TRAINING_INCOMPLETE")
    last_session = services.last_crate_session(animal["id"])
    if last_session is None or \
            calc.whole_days(services.as_date(last_session), departure_date) > calc.CRATE_RECENCY_DAYS:
        fail("ERR_CRATE_TRAINING_STALE")

    # rung 12 -- paperwork, in the exact order a confirmation walks its gates
    docs = services.documents_of(agreement["id"])
    certificates = [d for d in docs
                    if d["document_type"] == "INTERSTATE_CVI" and d["status"] == "ISSUED"]
    if not certificates:
        fail("ERR_HEALTH_CERTIFICATE_MISSING")
    for required in calc.REQUIRED_DOCUMENTS[agreement["transfer_scope"]]:
        if required == "INTERSTATE_CVI":
            continue
        if not any(d for d in docs if d["document_type"] == required and d["status"] == "ISSUED"):
            fail("ERR_PERMIT_NOT_ISSUED")
    scheduled = [o for o in services.occupancies_of(agreement["id"])
                 if o["phase"] == "SCHEDULED"
                 and o["institution_id"] == agreement["receiving_institution_id"]]
    if not scheduled:
        fail("ERR_QUARANTINE_NOT_SCHEDULED")
    if not any(c for c in certificates
               if c["valid_until"] is not None
               and services.as_date(c["valid_until"]) >= arrival_date):
        fail("ERR_HEALTH_CERTIFICATE_EXPIRED")

    booking["status"] = "CONFIRMED"
    db.touch(booking)
    return ok(services.booking_out(booking))


@bp.post("/shipment-bookings/<booking_id>/depart")
@auth("Registrar")
def depart_booking(booking_id):
    b = body()
    get_str(b, "departure_note")
    booking = db.get_booking(booking_id)
    agreement = db.agreements.get(booking["transfer_agreement_id"])
    services.party_check(agreement, actor(), "sending_institution_id")

    if booking["status"] != "CONFIRMED":
        fail("ERR_BOOKING_INVALID_STATE")
    animal = db.animals.get(agreement["animal_id"])
    if animal is None or animal["location_status"] != "RESERVED":
        fail("ERR_ANIMAL_LOCATION_CONFLICT")

    booking["status"] = "IN_TRANSIT"
    booking["departed_at"] = now_instant()
    db.touch(booking)
    animal["location_status"] = "IN_TRANSIT"
    db.touch(animal)
    return ok(services.booking_out(booking))


@bp.post("/shipment-bookings/<booking_id>/deliver")
@auth("Registrar")
def deliver_booking(booking_id):
    b = body()
    samples = get_num_list(b, "temperature_samples", required=True)
    booking = db.get_booking(booking_id)
    agreement = db.agreements.get(booking["transfer_agreement_id"])
    services.party_check(agreement, actor(), "receiving_institution_id")

    if booking["status"] != "IN_TRANSIT":
        fail("ERR_BOOKING_INVALID_STATE")

    excursion = calc.thermal_excursion(samples, booking["temp_min_c"], booking["temp_max_c"])
    booking["temperature_samples"] = samples
    booking["thermal_excursion_minutes"] = excursion
    booking["status"] = "DELIVERED"
    booking["delivered_at"] = now_instant()
    db.touch(booking)

    delivery_date = now_date()
    credit = services.valuation(agreement, delivery_date)
    final = calc.final_credit(credit, excursion)
    provisional = agreement["provisional_credit_points"]
    previous = dec(provisional) if provisional is not None else dec(0)
    agreement["final_credit_points"] = final
    db.touch(agreement)
    sending = db.institutions.get(agreement["sending_institution_id"])
    receiving = db.institutions.get(agreement["receiving_institution_id"])
    if sending is not None and receiving is not None:
        services.post_credit(sending, receiving, final - previous)

    animal = db.animals.get(agreement["animal_id"])
    if animal is not None:
        animal["holding_institution_id"] = agreement["receiving_institution_id"]
        if animal["location_status"] == "IN_TRANSIT":
            animal["location_status"] = "IN_QUARANTINE"
        db.touch(animal)

    for occ in services.occupancies_of(agreement["id"]):
        if occ["phase"] != "SCHEDULED":
            continue
        occ["phase"] = "ACTIVE"
        occ["actual_start_date"] = fmt_date(delivery_date)
        if excursion > calc.MAX_EXCURSION_MINUTES:
            occ["isolation_class"] = "ENHANCED"
            occ["required_days"] = calc.QUARANTINE_MIN_DAYS_ENHANCED
        else:
            occ["isolation_class"] = "STANDARD"
            occ["required_days"] = calc.QUARANTINE_MIN_DAYS_STANDARD
        db.touch(occ)

    return ok(services.booking_out(booking))


@bp.get("/shipment-bookings/<booking_id>")
@auth()
def read_booking(booking_id):
    return ok(services.booking_out(db.get_booking(booking_id)))


@bp.get("/shipment-bookings")
@auth()
def list_bookings():
    limit, offset = pagination()
    filters = {
        "transfer_agreement_id": q_str("transfer_agreement_id"),
        "carrier_code": q_str("carrier_code"),
        "status": q_enum("status", STATUSES),
    }
    rows = list(db.bookings.values())
    for field, value in filters.items():
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    return paginate(sorted_rows(rows), limit, offset, services.booking_out)
