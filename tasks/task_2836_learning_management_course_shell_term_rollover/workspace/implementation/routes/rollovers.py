"""Term rollover jobs -- PRD 3.6."""

from decimal import Decimal

from flask import Blueprint

import lookup
from db import by_created, db, mark, new_record, set_field
from errors import require
from middleware import (INSTRUCTOR, LMS_ADMIN, as_bool, as_enum, as_int,
                        as_str, bad, body)
from routes.common import apply_filters, created, guard, listing, ok
from routes.content import sandbox_gate
from services import compute
from util import q2

bp = Blueprint("rollovers", __name__)

ACTIONS = ("VALIDATE", "EXECUTE", "COMPENSATE")
SHIFT_MODES = ("ANCHOR_PROPORTIONAL", "FIXED_OFFSET")
SOURCE_STATES = ("CONCLUDED", "ARCHIVED")
QUOTA_FAILURE = "sandbox storage quota exceeded"
ZERO = Decimal("0.00")


def source_eligible(source, target_term_id):
    require(source["provisioning_state"] in SOURCE_STATES
            and source["term_id"] != target_term_id,
            "ERR_ROLLOVER_SOURCE_INELIGIBLE",
            "The source shell must be CONCLUDED or ARCHIVED and sit in a term "
            "other than the target term.")


def target_empty(target, states=("REQUESTED", "PROVISIONED")):
    enrolled = [e for e in db.enrollments.values()
                if e["shell_id"] == target["id"]]
    require(target["provisioning_state"] in states
            and target["content_item_count"] == 0 and not enrolled,
            "ERR_ROLLOVER_TARGET_NOT_EMPTY",
            "The target shell must be empty and awaiting content.")


@bp.post("/rollover-jobs")
def create_job():
    guard(LMS_ADMIN)
    payload = body()
    source = lookup.fk(payload, "source_shell_id", "shells")
    target = lookup.fk(payload, "target_shell_id", "shells")
    target_term = lookup.fk(payload, "target_term_id", "terms")
    if source is None:
        as_str(payload, "source_shell_id", required=True)
    if target is None:
        as_str(payload, "target_shell_id", required=True)
    if target_term is None:
        as_str(payload, "target_term_id", required=True)
    expected = as_int(payload, "expected_target_shell_version", required=True)
    strip_dates = as_bool(payload, "strip_dates", default=True)
    strip_submissions = as_bool(payload, "strip_submissions", default=True)
    strip_grades = as_bool(payload, "strip_grades", default=True)
    mode = as_enum(payload, "date_shift_mode", SHIFT_MODES,
                   default="ANCHOR_PROPORTIONAL")

    require(expected == target["version"], "ERR_STALE_VERSION",
            "The target shell has moved on to version %d." % target["version"])
    sandbox_gate(target)
    source_eligible(source, target_term["id"])
    target_empty(target)

    job = new_record(
        _kind="job",
        source_shell_id=source["id"],
        target_shell_id=target["id"],
        target_term_id=target_term["id"],
        expected_target_shell_version=expected,
        strip_dates=strip_dates,
        strip_submissions=strip_submissions,
        strip_grades=strip_grades,
        date_shift_mode=mode,
        job_state="DRAFT",
        eligible_item_count=0,
        copied_item_count=0,
        skipped_item_count=0,
        date_stripped_count=0,
        date_shifted_count=0,
        copied_storage_mb=ZERO,
        failure_reason=None,
    )
    db.jobs[job["id"]] = job
    # PRD 2.7: "A successful create increments the target shell's version by one."
    mark(target)
    return created(job)


@bp.get("/rollover-jobs")
def list_jobs():
    guard(LMS_ADMIN, INSTRUCTOR)
    records = apply_filters(db.jobs.values(), {
        "source_shell_id": "source_shell_id",
        "target_shell_id": "target_shell_id",
        "target_term_id": "target_term_id",
        "job_state": "job_state",
        "date_shift_mode": "date_shift_mode",
    })
    return listing(records)


@bp.get("/rollover-jobs/<job_id>")
def read_job(job_id):
    guard(LMS_ADMIN, INSTRUCTOR)
    return ok(lookup.job(job_id))


def copy_grades(job, source, target):
    """strip_grades false carries each source enrollment's earned_points_total
    onto the matching target enrollment for the same person_id (PRD 3.6)."""
    target_rows = {e["person_id"]: e for e in db.enrollments.values()
                   if e["shell_id"] == target["id"]}
    for row in by_created([e for e in db.enrollments.values()
                           if e["shell_id"] == source["id"]]):
        twin = target_rows.get(row["person_id"])
        if twin is None:
            continue
        set_field(twin, "earned_points_total", q2(row["earned_points_total"]))
        compute.recompute_enrollment_grades(twin)
        mark(twin)


def run_copy(job, source, target):
    source_term = db.terms[source["term_id"]]
    target_term = db.terms[job["target_term_id"]]
    copied = 0
    skipped = 0
    stripped = 0
    shifted = 0
    storage = ZERO
    for item in by_created([i for i in db.items.values()
                            if i["shell_id"] == source["id"]
                            and i["copy_state"] != "SKIPPED"]):
        if not job["strip_submissions"] and item["has_submissions"]:
            skipped += 1
            continue
        due_at = None
        date_stripped = False
        if item["due_at"] is None:
            due_at = None
        elif job["strip_dates"]:
            date_stripped = True
            stripped += 1
        else:
            due_at = compute.project_due_at(item["due_at"], source_term,
                                            target_term, job["date_shift_mode"])
            shifted += 1
        copy = new_record(
            _kind="item",
            shell_id=target["id"],
            source_item_id=item["id"],
            item_type=item["item_type"],
            title=item["title"],
            due_at=due_at,
            points_possible=item["points_possible"],
            storage_mb=item["storage_mb"],
            has_submissions=False if job["strip_submissions"] else item["has_submissions"],
            submission_count=0 if job["strip_submissions"] else item["submission_count"],
            date_stripped=date_stripped,
            copy_state="COPIED",
        )
        db.items[copy["id"]] = copy
        copied += 1
        storage = storage + item["storage_mb"]
    set_field(job, "copied_item_count", copied)
    set_field(job, "skipped_item_count", skipped)
    set_field(job, "date_stripped_count", stripped)
    set_field(job, "date_shifted_count", shifted)
    set_field(job, "copied_storage_mb", q2(storage))
    if not job["strip_grades"]:
        copy_grades(job, source, target)
    compute.recompute_shell(target)
    mark(target)
    compute.recompute_chargeback(db.people.get(target["owner_person_id"]))


@bp.post("/rollover-jobs/<job_id>/transitions")
def drive_job(job_id):
    guard(LMS_ADMIN)
    job = lookup.job(job_id)
    payload = body()
    action = as_str(payload, "action", required=True)
    require(action in ACTIONS, "ERR_INVALID_STATE_TRANSITION",
            "'%s' is not a declared rollover action." % action)
    source = db.shells[job["source_shell_id"]]
    target = db.shells[job["target_shell_id"]]
    target_term = db.terms[job["target_term_id"]]
    state = job["job_state"]

    if action == "VALIDATE":
        if job["target_term_id"] != target["term_id"]:
            bad("target_term_id", "must match the target shell's own term_id")
        require(state == "DRAFT", "ERR_INVALID_STATE_TRANSITION",
                "VALIDATE runs from DRAFT, not from %s." % state)
        require(target["provisioning_state"] == "PROVISIONED",
                "ERR_INVALID_STATE_TRANSITION",
                "The target shell must be PROVISIONED to validate a rollover.")
        source_eligible(source, job["target_term_id"])
        target_empty(target, ("REQUESTED", "PROVISIONED"))
        eligible = [i for i in db.items.values()
                    if i["shell_id"] == source["id"] and i["copy_state"] != "SKIPPED"]
        set_field(job, "job_state", "VALIDATED")
        set_field(job, "eligible_item_count", len(eligible))
        mark(job)
        return ok(job)

    if action == "EXECUTE":
        require(state == "VALIDATED", "ERR_INVALID_STATE_TRANSITION",
                "EXECUTE runs from VALIDATED, not from %s." % state)
        require(target["provisioning_state"] == "PROVISIONED",
                "ERR_INVALID_STATE_TRANSITION",
                "The target shell must still be PROVISIONED to execute.")
        set_field(job, "job_state", "COPYING")
        run_copy(job, source, target)
        over_quota = (target["shell_type"] in ("SANDBOX", "DEV")
                      and target["storage_mb"] > compute.SANDBOX_STORAGE_QUOTA_MB)
        settled = (job["copied_item_count"] + job["skipped_item_count"]
                   == job["eligible_item_count"])
        if over_quota:
            set_field(job, "job_state", "FAILED")
            set_field(job, "failure_reason", QUOTA_FAILURE)
        elif settled:
            set_field(job, "job_state", "COMPLETED")
            compute.recompute_rollover_pct(target_term)
            mark(target_term)
        mark(job)
        return ok(job)

    require(state == "FAILED", "ERR_INVALID_STATE_TRANSITION",
            "COMPENSATE runs from FAILED, not from %s." % state)
    for item in by_created([i for i in db.items.values()
                            if i["shell_id"] == target["id"]
                            and i["copy_state"] == "COPIED"
                            and i["source_item_id"] in db.items
                            and db.items[i["source_item_id"]]["shell_id"] == source["id"]]):
        set_field(item, "copy_state", "SKIPPED")
        set_field(item, "storage_mb", ZERO)
        mark(item)
    compute.recompute_shell(target)
    mark(target)
    compute.recompute_chargeback(db.people.get(target["owner_person_id"]))
    set_field(job, "job_state", "COMPENSATED")
    mark(job)
    return ok(job)
