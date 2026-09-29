"""Content items, submissions and grade records -- PRD 3.6 and 3.8."""

from decimal import Decimal

from flask import Blueprint

import lookup
from db import db, mark, new_record, now, set_field
from errors import require
from middleware import (INSTRUCTOR, LMS_ADMIN, STUDENT, as_decimal, as_dt,
                        as_enum, as_str, bad, body)
from routes.common import (apply_filters, created, deleted, guard, listing, ok)
from services import access, compute
from util import q2

bp = Blueprint("content", __name__)

ITEM_TYPES = ("ASSIGNMENT", "QUIZ", "PAGE", "FILE")
COPY_STATES = ("SOURCE", "COPIED", "SKIPPED")
ZERO = Decimal("0.00")


def sandbox_gate(shell):
    """A SANDBOX or DEV shell receives no new content after its
    sandbox_expires_at (PRD 3.3 / 2.10 band 26)."""
    if shell["shell_type"] in ("SANDBOX", "DEV") and shell["sandbox_expires_at"]:
        require(now() <= shell["sandbox_expires_at"], "ERR_SANDBOX_EXPIRED",
                "This sandbox shell expired at %s." % shell["sandbox_expires_at"])


def resync(shell):
    compute.recompute_shell(shell)
    if shell["shell_type"] in ("SANDBOX", "DEV"):
        compute.recompute_chargeback(db.people.get(shell["owner_person_id"]))


@bp.post("/content-items")
def create_item():
    guard(INSTRUCTOR, LMS_ADMIN)
    payload = body()
    access.own_shell(lookup.peek("shells", payload.get("shell_id")))
    shell = lookup.fk(payload, "shell_id", "shells")
    if shell is None:
        as_str(payload, "shell_id", required=True)
    item_type = as_enum(payload, "item_type", ITEM_TYPES, required=True)
    title = as_str(payload, "title", required=True)
    due_at = as_dt(payload, "due_at")
    points_possible = as_decimal(payload, "points_possible", default=ZERO, low=0)
    storage_mb = as_decimal(payload, "storage_mb", default=ZERO, low=0)
    if item_type in ("PAGE", "FILE") and q2(points_possible) != ZERO:
        bad("points_possible", "must be 0 on a PAGE or FILE item")
    sandbox_gate(shell)

    item = new_record(
        _kind="item",
        shell_id=shell["id"],
        source_item_id=None,
        item_type=item_type,
        title=title,
        due_at=due_at,
        points_possible=q2(points_possible),
        storage_mb=q2(storage_mb),
        has_submissions=False,
        submission_count=0,
        date_stripped=False,
        copy_state="SOURCE",
    )
    db.items[item["id"]] = item
    resync(shell)
    return created(item)


@bp.get("/content-items")
def list_items():
    guard(INSTRUCTOR, LMS_ADMIN, STUDENT)
    records = apply_filters(db.items.values(), {
        "shell_id": "shell_id",
        "source_item_id": "source_item_id",
        "item_type": "item_type",
        "copy_state": "copy_state",
    })
    return listing(records)


@bp.get("/content-items/<item_id>")
def read_item(item_id):
    guard(INSTRUCTOR, LMS_ADMIN, STUDENT)
    return ok(lookup.item(item_id))


@bp.patch("/content-items/<item_id>")
def update_item(item_id):
    guard(INSTRUCTOR)
    existing = lookup.peek("items", item_id)
    if existing is not None:
        access.own_shell(db.shells.get(existing["shell_id"]))
    item = lookup.item(item_id)
    payload = body()
    title = as_str(payload, "title")
    due_at = as_dt(payload, "due_at")
    points_possible = as_decimal(payload, "points_possible", low=0)
    storage_mb = as_decimal(payload, "storage_mb", low=0)
    if (points_possible is not None and item["item_type"] in ("PAGE", "FILE")
            and q2(points_possible) != ZERO):
        bad("points_possible", "must be 0 on a PAGE or FILE item")
    if title is not None:
        set_field(item, "title", title)
    if "due_at" in payload and payload["due_at"] is None:
        set_field(item, "due_at", None)
    elif due_at is not None:
        set_field(item, "due_at", due_at)
    if points_possible is not None:
        set_field(item, "points_possible", q2(points_possible))
    if storage_mb is not None:
        set_field(item, "storage_mb", q2(storage_mb))
    mark(item)
    resync(db.shells[item["shell_id"]])
    return ok(item)


@bp.delete("/content-items/<item_id>")
def delete_item(item_id):
    guard(INSTRUCTOR)
    existing = lookup.peek("items", item_id)
    if existing is not None:
        access.own_shell(db.shells.get(existing["shell_id"]))
    item = lookup.item(item_id)
    require(not item["has_submissions"], "ERR_ITEM_HAS_SUBMISSIONS",
            "The gradebook must keep an item that carries submissions.")
    shell = db.shells[item["shell_id"]]
    del db.items[item["id"]]
    resync(shell)
    return deleted()


@bp.post("/content-items/<item_id>/submissions")
def record_submission(item_id):
    guard(INSTRUCTOR)
    item = lookup.item(item_id)
    payload = body()
    enrollment = lookup.fk(payload, "enrollment_id", "enrollments")
    if enrollment is None:
        as_str(payload, "enrollment_id", required=True)
    set_field(item, "has_submissions", True)
    set_field(item, "submission_count", item["submission_count"] + 1)
    mark(item)
    return created(item)


@bp.post("/_grade-records")
def record_grade():
    guard(INSTRUCTOR)
    payload = body()
    enrollment = lookup.fk(payload, "enrollment_id", "enrollments")
    item = lookup.fk(payload, "content_item_id", "items")
    if enrollment is None:
        as_str(payload, "enrollment_id", required=True)
    if item is None:
        as_str(payload, "content_item_id", required=True)
    earned_points = as_decimal(payload, "earned_points", required=True)

    key = (enrollment["id"], item["id"])
    db.grade_records[key] = {
        "enrollment_id": enrollment["id"],
        "content_item_id": item["id"],
        "earned_points": q2(earned_points),
    }
    compute.recompute_enrollment_grades(enrollment)
    mark(enrollment)
    return created(enrollment)
