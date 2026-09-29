"""Seasonal contracts, bunkhouse space and the retention bonus (PRD 3.10)."""

from flask import Blueprint

import calc
import derive
import fields
from auth import auth
from derive import Touch, staff_json
from envelope import created, listing, ok
from errors import ApiError
from fields import body, require
from lookup import find
from store import db

bp = Blueprint("staff", __name__)

ROLE_TYPES = ("WRANGLER", "GUIDE", "KITCHEN", "HOUSEKEEPING")
CERTIFICATIONS = (
    "WILDERNESS_FIRST_AID",
    "EQUINE_HANDLER",
    "FLY_CASTING",
    "CHILD_PROGRAM",
)
EMPLOYMENT_STATUSES = ("HIRED", "ACTIVE", "COMPLETED_SEASON", "DEPARTED_EARLY")
STAFF_READERS = ("RanchManager", "ActivityGuide", "SafetyOfficer", "HorseProgramDirector")


@bp.post("/seasons/<season_id>/staff-members")
def hire_staff(season_id):
    auth("RanchManager")
    season = find("seasons", season_id)
    data = body()
    require(data, "full_name", "role_type", "hired_on", "contract_end_date")
    full_name = fields.as_str(data, "full_name")
    role_type = fields.as_enum(data, "role_type", ROLE_TYPES)
    certifications = fields.as_enum_list(data, "certifications", CERTIFICATIONS)
    hired_on = fields.as_date(data, "hired_on")
    end_date = fields.as_date(data, "contract_end_date")
    if end_date <= hired_on:
        fields.bad("contract_end_date", "must be strictly later than hired_on")

    row = db.insert(
        "staff_members",
        {
            "season_id": season["id"],
            "full_name": full_name,
            "role_type": role_type,
            "certifications": certifications if certifications is not None else [],
            "hired_on": hired_on,
            "contract_end_date": end_date,
            "housing_unit_code": None,
            "housing_bunk_number": None,
            "employment_status": "HIRED",
            "separated_on": None,
            "contract_days": calc.days_between(hired_on, end_date),
            "retention_bonus_settled_cents": 0,
            "days_worked_frozen": None,
        },
    )
    return created(staff_json(row))


@bp.get("/staff-members/<staff_id>")
def read_staff(staff_id):
    auth(*STAFF_READERS)
    return ok(staff_json(find("staff_members", staff_id)))


@bp.get("/staff-members")
def list_staff():
    auth(*STAFF_READERS)
    rows = derive.rows_of(
        "staff_members",
        season_id=fields.query_filter("season_id"),
        role_type=fields.query_enum("role_type", ROLE_TYPES),
        employment_status=fields.query_enum("employment_status", EMPLOYMENT_STATUSES),
    )
    return listing(rows, staff_json)


@bp.post("/staff-members/<staff_id>/onboard")
def onboard_staff(staff_id):
    auth("RanchManager")
    staff = find("staff_members", staff_id)
    data = body()
    require(data, "housing_unit_code", "housing_bunk_number")
    unit = fields.as_str(data, "housing_unit_code")
    bunk = fields.as_int(data, "housing_bunk_number", minimum=1)

    if staff["employment_status"] != "HIRED":
        raise ApiError(
            "ERR_STAFF_STATE_INVALID",
            "Only a HIRED staff member may be onboarded; this one is %s."
            % staff["employment_status"],
        )
    if db.clock_date() < staff["hired_on"]:
        raise ApiError(
            "ERR_CONTRACT_DATE_INVALID", "The contract start date has not arrived."
        )
    for other in db.staff_members.values():
        if other["id"] == staff["id"] or other["season_id"] != staff["season_id"]:
            continue
        if other["employment_status"] not in ("HIRED", "ACTIVE"):
            continue
        if (
            other.get("housing_unit_code") == unit
            and other.get("housing_bunk_number") == bunk
        ):
            raise ApiError("ERR_HOUSING_BUNK_TAKEN", "That bunk is already allotted.")

    staff["employment_status"] = "ACTIVE"
    staff["housing_unit_code"] = unit
    staff["housing_bunk_number"] = bunk
    db.touch(staff)
    return ok(staff_json(staff))


@bp.post("/staff-members/<staff_id>/separate")
def separate_staff(staff_id):
    auth("RanchManager")
    staff = find("staff_members", staff_id)
    data = body()
    require(data, "reason")
    fields.as_str(data, "reason")

    if staff["employment_status"] not in ("HIRED", "ACTIVE"):
        raise ApiError(
            "ERR_STAFF_STATE_INVALID",
            "A %s contract cannot be separated." % staff["employment_status"],
        )
    if (
        staff["employment_status"] == "ACTIVE"
        and db.clock_date() >= staff["contract_end_date"]
    ):
        raise ApiError(
            "ERR_CONTRACT_DATE_INVALID",
            "On or after contract_end_date the contract must be completed instead.",
        )

    season = db.seasons.get(staff["season_id"])
    days_worked = derive.staff_days_worked(staff)
    settled = calc.settled_bonus(
        season["retention_bonus_cents"], days_worked, staff["contract_days"], False
    )
    staff["separated_on"] = db.clock_date()
    staff["days_worked_frozen"] = days_worked
    staff["employment_status"] = "DEPARTED_EARLY"
    staff["retention_bonus_settled_cents"] = settled
    season["retention_bonus_liability_cents"] = (
        int(season["retention_bonus_liability_cents"]) + settled
    )

    touch = Touch()
    for assignment in db.rows("guide_assignments"):
        if assignment["staff_member_id"] != staff["id"]:
            continue
        if assignment["assignment_status"] != "SCHEDULED":
            continue
        assignment["assignment_status"] = "RELEASED"
        touch.add(assignment)
        touch.slot(db.activity_slots.get(assignment["slot_id"]))
    touch.add(staff)
    touch.add(season)
    touch.finalize()
    return ok(staff_json(staff))


@bp.post("/staff-members/<staff_id>/complete-season")
def complete_staff_season(staff_id):
    auth("RanchManager")
    staff = find("staff_members", staff_id)

    if staff["employment_status"] != "ACTIVE":
        raise ApiError(
            "ERR_STAFF_STATE_INVALID",
            "Only an ACTIVE contract may be completed; this one is %s."
            % staff["employment_status"],
        )
    if db.clock_date() < staff["contract_end_date"]:
        raise ApiError(
            "ERR_CONTRACT_DATE_INVALID", "The contract end date has not arrived."
        )
    for assignment in db.guide_assignments.values():
        if (
            assignment["staff_member_id"] == staff["id"]
            and assignment["assignment_status"] == "SCHEDULED"
        ):
            raise ApiError(
                "ERR_GUIDE_ASSIGNMENTS_OPEN",
                "A guide assignment of this staff member is still SCHEDULED.",
            )

    season = db.seasons.get(staff["season_id"])
    settled = int(season["retention_bonus_cents"])
    staff["days_worked_frozen"] = derive.staff_days_worked(staff)
    staff["employment_status"] = "COMPLETED_SEASON"
    staff["retention_bonus_settled_cents"] = settled
    staff["housing_unit_code"] = None
    staff["housing_bunk_number"] = None
    season["retention_bonus_liability_cents"] = (
        int(season["retention_bonus_liability_cents"]) + settled
    )
    db.touch(staff)
    db.touch(season)
    return ok(staff_json(staff))
