"""VetReport endpoints: file reports driving the injury protocol (PRD 3.3)."""
from flask import Blueprint, request

from db import DB, new_id
from errors import ApiError
from middleware import ALL_ROLES, auth
from response import ok, ok_list
from services import (
    animal_injury_cascade,
    get_or_404,
    ser,
    sorted_created,
    stamp_immutable,
    touch,
)
from util import as_enum, as_str, body, pagination_args, required

bp = Blueprint("vet_reports", __name__, url_prefix="/api")

SUBJECT_TYPES = {"ANIMAL", "CONTESTANT"}
DISPOSITIONS = {"CLEARED", "INJURED_TURNOUT", "RETIRED"}


@bp.post("/vet-reports")
def create_vet_report():
    auth(["Veterinarian"])
    data = body()
    # Body FK existence for any supplied references.
    animal_id = data.get("animal_id")
    contestant_id = data.get("contestant_id")
    performance_id = data.get("performance_id")
    if animal_id is not None:
        get_or_404("stock_animals", animal_id)
    if contestant_id is not None:
        get_or_404("contestants", contestant_id)
    if performance_id is not None:
        get_or_404("performances", performance_id)
    # Field shape and subject/disposition pairing.
    subject_type = as_enum(
        required(data, "subject_type"), "subject_type", SUBJECT_TYPES
    )
    disposition = as_enum(required(data, "disposition"), "disposition", DISPOSITIONS)
    findings = as_str(required(data, "findings"), "findings")
    veterinarian_name = as_str(
        required(data, "veterinarian_name"), "veterinarian_name"
    )
    if subject_type == "ANIMAL":
        if animal_id is None:
            raise ApiError(
                "ERR_VALIDATION", 400, "ANIMAL reports require animal_id"
            )
        if contestant_id is not None:
            raise ApiError(
                "ERR_VALIDATION", 400, "ANIMAL reports must leave contestant_id null"
            )
    else:  # CONTESTANT
        if contestant_id is None:
            raise ApiError(
                "ERR_VALIDATION", 400, "CONTESTANT reports require contestant_id"
            )
        if animal_id is not None:
            raise ApiError(
                "ERR_VALIDATION", 400, "CONTESTANT reports must leave animal_id null"
            )
        if disposition != "INJURED_TURNOUT":
            raise ApiError(
                "ERR_VALIDATION",
                400,
                "CONTESTANT reports allow only the INJURED_TURNOUT disposition",
            )
    # State legality of the animal transition the disposition drives.
    animal = None
    if subject_type == "ANIMAL":
        animal = DB["stock_animals"][animal_id]
        if disposition == "CLEARED":
            if animal["status"] != "INJURED":
                raise ApiError(
                    "ERR_INVALID_STATE",
                    409,
                    "Cleared is valid only from INJURED",
                )
        elif disposition == "INJURED_TURNOUT":
            if animal["status"] not in ("AVAILABLE", "DRAWN", "COMPETED"):
                raise ApiError(
                    "ERR_INVALID_STATE",
                    409,
                    f"INJURED_TURNOUT is not valid from status {animal['status']}",
                )
        else:  # RETIRED
            if animal["status"] not in ("AVAILABLE", "DRAWN", "INJURED"):
                raise ApiError(
                    "ERR_INVALID_STATE",
                    409,
                    f"RETIRED is not valid from status {animal['status']}",
                )
    rec = {
        "id": new_id(),
        "subject_type": subject_type,
        "animal_id": animal_id,
        "contestant_id": contestant_id,
        "performance_id": performance_id,
        "findings": findings,
        "disposition": disposition,
        "veterinarian_name": veterinarian_name,
    }
    stamp_immutable(rec)
    DB["vet_reports"][rec["id"]] = rec
    # Animal welfare cascades (PRD 3.3 / StockAnimal state machine).
    if animal is not None:
        if disposition == "CLEARED":
            animal["status"] = "AVAILABLE"
            touch(animal)
        elif disposition == "INJURED_TURNOUT":
            if animal["status"] == "DRAWN":
                animal_injury_cascade(animal, rec, "INJURED")
            else:
                animal["status"] = "INJURED"
                touch(animal)
        else:  # RETIRED
            if animal["status"] == "DRAWN":
                animal_injury_cascade(animal, rec, "RETIRED")
            else:
                animal["status"] = "RETIRED"
                touch(animal)
    return ok(ser(rec), status=201)


@bp.get("/vet-reports")
def list_vet_reports():
    auth(ALL_ROLES)
    animal_id = request.args.get("animal_id")
    contestant_id = request.args.get("contestant_id")
    performance_id = request.args.get("performance_id")
    items = DB["vet_reports"].values()
    if animal_id is not None:
        items = [r for r in items if r["animal_id"] == animal_id]
    if contestant_id is not None:
        items = [r for r in items if r["contestant_id"] == contestant_id]
    if performance_id is not None:
        items = [r for r in items if r["performance_id"] == performance_id]
    items = sorted_created(items)
    limit, offset = pagination_args()
    return ok_list(
        [ser(r) for r in items[offset : offset + limit]], len(items), limit, offset
    )


@bp.get("/vet-reports/<report_id>")
def get_vet_report(report_id):
    auth(ALL_ROLES)
    return ok(ser(get_or_404("vet_reports", report_id)))
