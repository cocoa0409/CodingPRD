"""Festival area, remediation and the bond ledger (PRD 3.9)."""

from flask import Blueprint

import auth
import db
import response
import validation
from errors import fail
from routes import common
from services import bond, calc, cascade

bp = Blueprint("restoration", __name__)


@bp.post("/ocr/venues/<venue_id>/festival-services")
def install_service(venue_id):
    auth.require(auth.SITE_OPS_LEAD, auth.RACE_DIRECTOR)
    venue = validation.path_venue(venue_id)
    payload = validation.body()
    service_type = validation.field_enum(payload, "service_type", validation.SERVICE_TYPES)
    footprint = validation.field_int(payload, "footprint_sqm", minimum=1)
    capacity = validation.field_int(payload, "capacity", minimum=1)
    water_draw = validation.field_int(payload, "water_draw_lpm", minimum=0, default=0)

    common.require_venue_open(venue)

    # Rungs 23 and 24: drawing water brings the land authority into it.
    if water_draw > 0:
        permit = common.governing_permit_or_fail(venue)
        if not permit["water_use_allowed"]:
            fail("ERR_WATER_USE_NOT_PERMITTED", "The governing permit forbids water use.")

    row = db.insert(
        "festival_services",
        {
            "venue_id": venue["id"],
            "service_type": service_type,
            "footprint_sqm": footprint,
            "capacity": capacity,
            "water_draw_lpm": water_draw,
            "status": "OPEN",
        },
    )
    with db.mutation(venue) as parcel:
        calc.apply_disturbed_area(parcel)
    return common.created(row)


@bp.get("/ocr/venues/<venue_id>/festival-services")
def list_services(venue_id):
    auth.require(*auth.OPERATOR_READERS)
    venue = validation.path_venue(venue_id)
    service_type = validation.query_enum("service_type", validation.SERVICE_TYPES)
    status = validation.query_enum("status", validation.FESTIVAL_STATUSES)
    rows = db.where("festival_services", venue_id=venue["id"])
    if service_type is not None:
        rows = [r for r in rows if r["service_type"] == service_type]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return common.listing(rows)


@bp.post("/ocr/venues/<venue_id>/restoration-tasks")
def open_task(venue_id):
    auth.require(auth.PERMIT_OFFICER, auth.SITE_OPS_LEAD)
    venue = validation.path_venue(venue_id)
    payload = validation.body()
    task_type = validation.field_enum(payload, "task_type", validation.TASK_TYPES)
    area = validation.field_int(payload, "area_sqm", minimum=1)

    # Rung 27: a task may not claim ground that was never disturbed.
    claimed = sum(int(t["area_sqm"]) for t in bond.tasks_of_venue(venue["id"])) + area
    if claimed > int(venue["disturbed_area_sqm"]):
        fail(
            "ERR_RESTORATION_AREA_EXCEEDED",
            "Remediated area %d exceeds the disturbed %d."
            % (claimed, int(venue["disturbed_area_sqm"])),
        )

    row = db.insert(
        "restoration_tasks",
        {
            "venue_id": venue["id"],
            "task_type": task_type,
            "area_sqm": area,
            "status": "PENDING",
            "bond_release_cents": 0,
            "inspection_rounds": 0,
            "findings_note": None,
        },
    )
    return common.created(row)


@bp.get("/ocr/venues/<venue_id>/restoration-tasks")
def list_tasks(venue_id):
    auth.require(
        auth.PERMIT_OFFICER, auth.COURSE_DESIGNER, auth.RACE_DIRECTOR, auth.SITE_OPS_LEAD
    )
    venue = validation.path_venue(venue_id)
    status = validation.query_enum("status", validation.TASK_STATUSES)
    task_type = validation.query_enum("task_type", validation.TASK_TYPES)
    rows = bond.tasks_of_venue(venue["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if task_type is not None:
        rows = [r for r in rows if r["task_type"] == task_type]
    return common.listing(rows)


@bp.get("/ocr/restoration-tasks/<task_id>")
def read_task(task_id):
    auth.require(
        auth.PERMIT_OFFICER, auth.COURSE_DESIGNER, auth.RACE_DIRECTOR, auth.SITE_OPS_LEAD
    )
    task = validation.path_task(task_id)
    return common.ok(task)


@bp.post("/ocr/restoration-tasks/<task_id>/inspect")
def inspect_task(task_id):
    auth.require(auth.PERMIT_OFFICER)
    task = validation.path_task(task_id)
    venue = common.venue_of(task)
    payload = validation.body()
    outcome = validation.field_enum(payload, "outcome", validation.INSPECTION_OUTCOMES)
    note = validation.field_str(payload, "findings_note", min_len=0, default=None)

    # Rung 9: the parcel posture first, then the no-op inspection.
    common.require_venue_open(venue)
    if outcome == task["status"]:
        fail("ERR_TASK_STATE_INVALID", "The task already reads %s." % task["status"])

    released_delta = 0
    with db.mutation(task) as row:
        row["inspection_rounds"] = int(row["inspection_rounds"]) + 1
        if note is not None:
            row["findings_note"] = note
        if outcome == "VERIFIED":
            share = bond.per_task_share(venue, row)
            row["bond_release_cents"] = share
            row["status"] = "VERIFIED"
            released_delta = share
        else:
            if row["status"] == "VERIFIED":
                released_delta = -int(row["bond_release_cents"])
                row["bond_release_cents"] = 0
            row["status"] = "REMEDIATION_REQUIRED"

    if released_delta != 0:
        with db.mutation(venue) as parcel:
            parcel["bond_released_cents"] = int(parcel["bond_released_cents"]) + released_delta
            calc.apply_bond_held(parcel)

    return common.ok(task)


@bp.post("/ocr/venues/<venue_id>/bond-releases")
def settle_bond(venue_id):
    auth.require(auth.PERMIT_OFFICER)
    venue = validation.path_venue(venue_id)
    payload = validation.body()
    settlement_type = validation.field_enum(
        payload, "settlement_type", validation.SETTLEMENT_TYPES
    )
    expected_version = validation.field_int(payload, "expected_venue_version")

    # Rung 8: the expected-version guard, because both settlements repeat legitimately.
    if expected_version != int(venue["version"]):
        fail(
            "ERR_STALE_VENUE_VERSION",
            "expected_venue_version %s does not match version %s."
            % (expected_version, venue["version"]),
        )

    # Rung 9: a closed-out parcel is terminal.
    if venue["site_posture"] == "CLOSED_OUT":
        fail("ERR_BOND_ALREADY_SETTLED", "Venue %s is already closed out." % venue["id"])

    # Rung 23.
    permit = common.governing_permit_or_fail(venue)

    if settlement_type == "FINAL":
        # Rung 28: every remediation task verified, and at least one of them.
        tasks = bond.tasks_of_venue(venue["id"])
        if not tasks or any(t["status"] != "VERIFIED" for t in tasks):
            fail("ERR_RESTORATION_INCOMPLETE", "Remediation of venue %s is unfinished." % venue["id"])

    with db.forced_mutation(venue) as parcel:
        if settlement_type == "PROGRESSIVE":
            bond.apply_progressive_settlement(parcel)
        else:
            bond.apply_final_settlement(parcel, permit)
            parcel["site_posture"] = "CLOSED_OUT"

    return common.ok(venue)


@bp.post("/ocr/_clock/set_current_utc")
def set_clock():
    auth.require(auth.PERMIT_OFFICER, auth.RACE_DIRECTOR)
    payload = validation.body()
    target = validation.field_datetime(payload, "to_iso8601")

    db.set_clock(target)

    expired_ids = []
    for permit in db.all_rows("permits"):
        if permit["status"] != "APPROVED":
            continue
        if permit["valid_until_utc"] is None or permit["valid_until_utc"] >= target:
            continue
        with db.mutation(permit) as row:
            row["status"] = "EXPIRED"
        expired_ids.append(permit["id"])
        venue = common.venue_of(permit)
        if venue is not None:
            cascade.freeze_venue(venue)

    return response.object_response(
        {"current_utc": db.iso(db.now()), "expired_permit_ids": expired_ids}
    )
