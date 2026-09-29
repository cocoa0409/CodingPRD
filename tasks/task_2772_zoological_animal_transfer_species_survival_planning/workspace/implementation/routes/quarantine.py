from datetime import timedelta

from flask import Blueprint

import calc
import db
import services
from core import (actor, auth, body, fail, fmt_date, get_date, get_str, now_date, ok, pagination,
                  paginate, q_enum, q_str, sorted_rows)

bp = Blueprint("quarantine", __name__)

PHASES = ("SCHEDULED", "ACTIVE", "CLEARED", "FAILED", "CANCELLED")
CLASSES = ("STANDARD", "ENHANCED")
BLOCKING_PHASES = ("SCHEDULED", "ACTIVE", "CLEARED", "FAILED")


def _acting_vet():
    vet = db.veterinarians.get(actor())
    if vet is None:
        fail("ERR_VET_INSTITUTION_MISMATCH")
    return vet


@bp.post("/quarantine-occupancies")
@auth("Registrar")
def create_occupancy():
    b = body()
    institution_id = get_str(b, "institution_id", required=True)
    agreement_id = get_str(b, "transfer_agreement_id", required=True)
    animal_id = get_str(b, "animal_id", required=True)
    room_code = get_str(b, "quarantine_room_code", required=True)
    start, start_raw = get_date(b, "scheduled_start_date", required=True)
    end, end_raw = get_date(b, "scheduled_end_date", required=True)
    if not end > start:
        fail("ERR_INVALID_REQUEST", "scheduled_end_date must be strictly after scheduled_start_date.")

    db.get_institution(institution_id)
    agreement = db.get_agreement(agreement_id)
    db.get_animal(animal_id)

    # PRD 2.1: a registrar acting on an agreement it is no party to hears
    # ERR_NOT_A_PARTY_TO_AGREEMENT.  The reservation itself is not tied to one
    # side: the occupied resource is the institution-and-room pair (PRD 3.8), and
    # it is the shipment-confirmation gate that additionally requires the
    # SCHEDULED occupancy to sit at the receiving institution.
    services.party_check(agreement, actor())

    for other in db.sorted_by_seq(list(db.occupancies.values())):
        if other["institution_id"] != institution_id:
            continue
        if other["quarantine_room_code"] != room_code:
            continue
        if other["phase"] not in BLOCKING_PHASES:
            continue
        if other["phase"] == "CLEARED" and other["cleared_on"] is not None:
            effective_end = services.as_date(other["cleared_on"])
        else:
            effective_end = services.as_date(other["scheduled_end_date"])
        buffer_days = calc.EXTENDED_SANITATION_DAYS if other["phase"] == "FAILED" \
            else calc.SANITATION_BUFFER_DAYS
        block_start = services.as_date(other["scheduled_start_date"])
        block_end = effective_end + timedelta(days=buffer_days)
        if start < block_end and block_start < end:
            fail("ERR_QUARANTINE_ROOM_CONFLICT")

    occ = db.insert(db.occupancies, {
        "institution_id": institution_id,
        "transfer_agreement_id": agreement_id,
        "animal_id": animal_id,
        "clearing_veterinarian_id": None,
        "quarantine_room_code": room_code,
        "scheduled_start_date": start_raw,
        "scheduled_end_date": end_raw,
        "actual_start_date": None,
        "isolation_class": "STANDARD",
        "required_days": calc.QUARANTINE_MIN_DAYS_STANDARD,
        "phase": "SCHEDULED",
        "cleared_on": None,
    })
    return ok(services.occupancy_out(occ), 201)


@bp.post("/quarantine-occupancies/<occupancy_id>/clear")
@auth("Veterinarian")
def clear_occupancy(occupancy_id):
    b = body()
    get_str(b, "clearance_note")
    occ = db.get_occupancy(occupancy_id)
    vet = _acting_vet()

    if vet["institution_id"] != occ["institution_id"]:
        fail("ERR_VET_INSTITUTION_MISMATCH")

    for doc in services.documents_of(occ["transfer_agreement_id"]):
        if doc["document_type"] == "INTERSTATE_CVI" and doc["status"] == "ISSUED" \
                and doc["issuing_veterinarian_id"] == vet["id"]:
            fail("ERR_SEGREGATION_OF_DUTIES")

    if occ["phase"] != "ACTIVE":
        fail("ERR_QUARANTINE_NOT_CLEARED")

    if vet["license_status"] != "ACTIVE":
        fail("ERR_VET_LICENSE_INVALID")

    served = calc.whole_days(services.as_date(occ["actual_start_date"]), now_date())
    if served < occ["required_days"]:
        fail("ERR_QUARANTINE_MINIMUM_NOT_MET")

    occ["phase"] = "CLEARED"
    occ["cleared_on"] = fmt_date(now_date())
    occ["clearing_veterinarian_id"] = vet["id"]
    db.touch(occ)

    animal = db.animals.get(occ["animal_id"])
    if animal is not None and animal["location_status"] == "IN_QUARANTINE":
        animal["location_status"] = "AWAITING_INTRODUCTION"
        db.touch(animal)
    return ok(services.occupancy_out(occ))


@bp.post("/quarantine-occupancies/<occupancy_id>/fail")
@auth("Veterinarian")
def fail_occupancy(occupancy_id):
    b = body()
    failure_reason = get_str(b, "failure_reason", required=True)
    occ = db.get_occupancy(occupancy_id)
    vet = _acting_vet()

    if vet["institution_id"] != occ["institution_id"]:
        fail("ERR_VET_INSTITUTION_MISMATCH")

    if occ["phase"] != "ACTIVE":
        fail("ERR_QUARANTINE_NOT_CLEARED")

    if vet["license_status"] != "ACTIVE":
        fail("ERR_VET_LICENSE_INVALID")

    occ["phase"] = "FAILED"
    occ["clearing_veterinarian_id"] = vet["id"]
    occ["cleared_on"] = None
    db.touch(occ)

    agreement = db.agreements.get(occ["transfer_agreement_id"])
    animal = db.animals.get(occ["animal_id"])
    if agreement is not None:
        if agreement["status"] == "EXECUTED":
            services.terminate_agreement(agreement, "QUARANTINE_FAILED", skip_animal_location=True)
        if animal is not None:
            animal["location_status"] = "HELD"
            animal["holding_institution_id"] = agreement["sending_institution_id"]
            db.touch(animal)
    return ok(services.occupancy_out(occ))


@bp.get("/quarantine-occupancies/<occupancy_id>")
@auth()
def read_occupancy(occupancy_id):
    return ok(services.occupancy_out(db.get_occupancy(occupancy_id)))


@bp.get("/quarantine-occupancies")
@auth()
def list_occupancies():
    limit, offset = pagination()
    filters = {
        "institution_id": q_str("institution_id"),
        "transfer_agreement_id": q_str("transfer_agreement_id"),
        "animal_id": q_str("animal_id"),
        "clearing_veterinarian_id": q_str("clearing_veterinarian_id"),
        "quarantine_room_code": q_str("quarantine_room_code"),
        "phase": q_enum("phase", PHASES),
        "isolation_class": q_enum("isolation_class", CLASSES),
    }
    rows = list(db.occupancies.values())
    for field, value in filters.items():
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    return paginate(sorted_rows(rows), limit, offset, services.occupancy_out)
