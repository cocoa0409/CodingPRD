"""Guest records, waivers, standing and rider ability assessments (PRD 3.3, 3.4)."""

import datetime

from flask import Blueprint

import calc
import derive
import fields
from auth import EVERYONE, auth
from derive import Touch, assessment_json, guest_json
from envelope import created, listing, ok
from errors import ApiError
from fields import body, require
from lookup import find
from store import db

bp = Blueprint("guests", __name__)

STANDINGS = ("GOOD", "RESTRICTED", "SUSPENDED")
ASSESSMENT_STATUSES = (
    "PENDING",
    "EVALUATED",
    "RE_EVALUATION_REQUESTED",
    "SUPERSEDED",
)


@bp.post("/guests")
def create_guest():
    auth("ReservationsAgent", "RanchManager")
    data = body()
    require(data, "full_name", "birth_date", "weight_lb")
    full_name = fields.as_str(data, "full_name")
    birth_date = fields.as_date(data, "birth_date")
    weight = fields.as_number(data, "weight_lb", exclusive_min=0)
    row = db.insert(
        "guests",
        {
            "full_name": full_name,
            "birth_date": birth_date,
            "weight_lb": weight,
            "guest_standing": "GOOD",
            "waiver_signed_on": None,
            "waiver_expires_on": None,
            "waiver_revoked_at": None,
            "equine_statute_ack": False,
            "waiver_signed_by_guardian_guest_id": None,
        },
    )
    return created(guest_json(row))


@bp.get("/guests/<guest_id>")
def read_guest(guest_id):
    user_id, role = auth(*EVERYONE)
    if role == "Guest" and user_id != guest_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "A guest may read only their own record.")
    return ok(guest_json(find("guests", guest_id)))


@bp.get("/guests")
def list_guests():
    auth("RanchManager", "ReservationsAgent", "HorseProgramDirector", "SafetyOfficer")
    standing = fields.query_enum("guest_standing", STANDINGS)
    guardian = fields.query_filter("waiver_signed_by_guardian_guest_id")
    rows = derive.rows_of(
        "guests",
        guest_standing=standing,
        waiver_signed_by_guardian_guest_id=guardian,
    )
    return listing(rows, guest_json)


@bp.post("/guests/<guest_id>/waiver-signature")
def waiver_signature(guest_id):
    user_id, role = auth("ReservationsAgent", "Guest")
    if role == "Guest" and user_id != guest_id:
        raise ApiError(
            "ERR_NOT_RESOURCE_OWNER", "A guest may sign only their own waiver."
        )
    guest = find("guests", guest_id)
    data = body()
    guardian = None
    if isinstance(data.get("waiver_signed_by_guardian_guest_id"), str):
        guardian = find("guests", data["waiver_signed_by_guardian_guest_id"])
    require(data, "signed_on", "equine_statute_ack")
    signed_on = fields.as_date(data, "signed_on")
    ack = fields.as_bool(data, "equine_statute_ack")
    fields.as_str(data, "waiver_signed_by_guardian_guest_id")

    if ack is not True:
        raise ApiError(
            "ERR_EQUINE_STATUTE_ACK_REQUIRED",
            "The statutory equine-activity acknowledgement must be true.",
        )
    if derive.guest_age(guest) < calc.ADULT_AGE_YEARS:
        if (
            guardian is None
            or derive.guest_age(guardian) < calc.ADULT_AGE_YEARS
            or derive.waiver_status(guardian) != "SIGNED"
        ):
            raise ApiError(
                "ERR_GUARDIAN_SIGNATURE_REQUIRED",
                "A minor's waiver must name an adult guardian with a live waiver.",
            )

    guest["waiver_signed_on"] = signed_on
    guest["waiver_expires_on"] = signed_on + datetime.timedelta(
        days=calc.WAIVER_VALID_DAYS
    )
    guest["waiver_revoked_at"] = None
    guest["equine_statute_ack"] = ack
    guest["waiver_signed_by_guardian_guest_id"] = (
        guardian["id"] if guardian is not None else None
    )
    db.touch(guest)
    return ok(guest_json(guest))


@bp.post("/guests/<guest_id>/waiver-revocation")
def waiver_revocation(guest_id):
    auth("RanchManager")
    guest = find("guests", guest_id)
    data = body()
    require(data, "reason")
    fields.as_str(data, "reason")

    guest["waiver_revoked_at"] = db.clock_iso()
    touch = Touch()
    derive.cancel_future_seats(guest["id"], touch, statuses=("CONFIRMED",))
    touch.add(guest)
    touch.finalize()
    return ok(guest_json(guest))


@bp.post("/guests/<guest_id>/suspension")
def suspend_guest(guest_id):
    auth("RanchManager", "SafetyOfficer")
    guest = find("guests", guest_id)
    data = body()
    require(data, "target_standing", "reason")
    target = fields.as_enum(data, "target_standing", ("SUSPENDED", "RESTRICTED"))
    fields.as_str(data, "reason")

    touch = Touch()
    derive.apply_standing(guest, target, touch)
    touch.finalize()
    return ok(guest_json(guest))


@bp.post("/guests/<guest_id>/reinstatement")
def reinstate_guest(guest_id):
    auth("RanchManager")
    guest = find("guests", guest_id)
    data = body()
    require(data, "reason")
    fields.as_str(data, "reason")

    guest["guest_standing"] = "GOOD"
    db.touch(guest)
    return ok(guest_json(guest))


# --------------------------------------------------------- rider assessments
@bp.post("/guests/<guest_id>/rider-assessments")
def open_assessment(guest_id):
    auth("HorseProgramDirector")
    guest = find("guests", guest_id)
    data = body()
    require(data, "requested_ability", "expected_guest_version")
    requested = fields.as_enum(data, "requested_ability", calc.RIDER_RANKS)
    pin = fields.as_int(data, "expected_guest_version")

    if pin != int(guest["version"]):
        raise ApiError(
            "ERR_STALE_GUEST_VERSION",
            "The supplied expected_guest_version is out of date.",
        )

    touch = Touch()
    for prior in derive.assessments_of_guest(guest["id"]):
        if prior["assessment_status"] in ("EVALUATED", "RE_EVALUATION_REQUESTED"):
            prior["assessment_status"] = "SUPERSEDED"
            touch.add(prior)
    row = db.insert(
        "rider_assessments",
        {
            "guest_id": guest["id"],
            "requested_ability": requested,
            "assessed_ability": None,
            "assessed_by_note": None,
            "evaluated_at": None,
            "assessment_status": "PENDING",
            "re_evaluation_reason": None,
        },
    )
    touch.add(guest)
    touch.finalize()
    return created(assessment_json(row))


@bp.get("/rider-assessments/<assessment_id>")
def read_assessment(assessment_id):
    auth(
        "RanchManager",
        "HorseProgramDirector",
        "ActivityGuide",
        "ReservationsAgent",
        "SafetyOfficer",
    )
    return ok(assessment_json(find("rider_assessments", assessment_id)))


@bp.get("/rider-assessments")
def list_assessments():
    auth(
        "RanchManager",
        "HorseProgramDirector",
        "ActivityGuide",
        "ReservationsAgent",
        "SafetyOfficer",
    )
    guest_id = fields.query_filter("guest_id")
    status = fields.query_enum("assessment_status", ASSESSMENT_STATUSES)
    rows = derive.rows_of("rider_assessments", guest_id=guest_id, assessment_status=status)
    return listing(rows, assessment_json)


@bp.post("/rider-assessments/<assessment_id>/evaluate")
def evaluate_assessment(assessment_id):
    auth("HorseProgramDirector")
    assessment = find("rider_assessments", assessment_id)
    data = body()
    require(data, "assessed_ability", "assessed_by_note", "evaluated_at")
    ability = fields.as_enum(data, "assessed_ability", calc.RIDER_RANKS)
    note = fields.as_str(data, "assessed_by_note")
    evaluated_at = fields.as_instant(data, "evaluated_at")

    if assessment["assessment_status"] not in ("PENDING", "RE_EVALUATION_REQUESTED"):
        raise ApiError(
            "ERR_ASSESSMENT_STATE_INVALID",
            "A %s assessment cannot be evaluated." % assessment["assessment_status"],
        )

    assessment["assessed_ability"] = ability
    assessment["assessed_by_note"] = note
    assessment["evaluated_at"] = evaluated_at
    assessment["re_evaluation_reason"] = None
    assessment["assessment_status"] = "EVALUATED"
    db.touch(assessment)
    guest = db.guests.get(assessment["guest_id"])
    if guest is not None:
        db.touch(guest)
    return ok(assessment_json(assessment))


@bp.post("/rider-assessments/<assessment_id>/flag-re-evaluation")
def flag_assessment(assessment_id):
    auth("HorseProgramDirector", "ActivityGuide")
    assessment = find("rider_assessments", assessment_id)
    data = body()
    require(data, "re_evaluation_reason")
    reason = fields.as_str(data, "re_evaluation_reason")

    if assessment["assessment_status"] != "EVALUATED":
        raise ApiError(
            "ERR_ASSESSMENT_STATE_INVALID",
            "Only an EVALUATED assessment may be flagged for re-evaluation.",
        )

    assessment["assessment_status"] = "RE_EVALUATION_REQUESTED"
    assessment["re_evaluation_reason"] = reason
    touch = Touch()
    touch.add(assessment)
    guest = db.guests.get(assessment["guest_id"])
    if guest is not None:
        derive.cancel_future_seats(
            guest["id"], touch, statuses=("CONFIRMED",), min_rank_above="NOVICE"
        )
        touch.add(guest)
    touch.finalize()
    return ok(assessment_json(assessment))
