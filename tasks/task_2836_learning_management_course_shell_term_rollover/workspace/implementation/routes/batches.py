"""The SIS enrollment sync feed -- PRD 3.4 (ordered batches)."""

from flask import Blueprint

import lookup
from db import db, mark, new_record, now, set_field
from errors import require
from middleware import LMS_ADMIN, REGISTRAR, as_int, as_str, bad, body
from routes.common import apply_filters, created, guard, listing, ok
from routes.enrollments import (BLOCKING_PAIR_STATES, LIVE_SHELL, LMS_ROLES,
                                new_enrollment, pair_rows)
from services import compute

bp = Blueprint("batches", __name__)

ACTIONS = ("VALIDATE", "APPLY", "CANCEL")
OPS = ("ADD", "DROP")
MAX_OPERATIONS = 200


def read_operations(payload):
    if "operations" not in payload or payload["operations"] is None:
        bad("operations", "is required")
    raw = payload["operations"]
    if not isinstance(raw, list):
        bad("operations", "must be an array")
    if len(raw) < 1 or len(raw) > MAX_OPERATIONS:
        bad("operations", "must carry between 1 and %d entries" % MAX_OPERATIONS)
    cleaned = []
    for index, entry in enumerate(raw):
        label = "operations[%d]" % index
        if not isinstance(entry, dict):
            bad(label, "must be an object")
        op = entry.get("op")
        if op not in OPS:
            bad(label + ".op", "must be one of %s" % ", ".join(OPS))
        shell_id = entry.get("shell_id")
        person_id = entry.get("person_id")
        lms_role = entry.get("role")
        if not isinstance(shell_id, str) or shell_id.strip() == "":
            bad(label + ".shell_id", "must be a non-empty string")
        if not isinstance(person_id, str) or person_id.strip() == "":
            bad(label + ".person_id", "must be a non-empty string")
        if lms_role not in LMS_ROLES:
            bad(label + ".role", "must be one of %s" % ", ".join(LMS_ROLES))
        cleaned.append({"op": op, "shell_id": shell_id,
                        "person_id": person_id, "role": lms_role})
    return cleaned


def operation_valid(batch, entry):
    """An operation counts as valid when its shell resolves to a shell of this
    batch's term in PROVISIONED or PUBLISHED and its person resolves to a
    person whose access_revoked_at is null (PRD 3.4)."""
    shell = db.shells.get(entry["shell_id"])
    if shell is None or shell["term_id"] != batch["term_id"]:
        return False
    if shell["provisioning_state"] not in LIVE_SHELL:
        return False
    person = db.people.get(entry["person_id"])
    if person is None or person["access_revoked_at"] is not None:
        return False
    return True


@bp.post("/enrollment-sync-batches")
def create_batch():
    guard(REGISTRAR)
    payload = body()
    term = lookup.fk(payload, "term_id", "terms")
    if term is None:
        as_str(payload, "term_id", required=True)
    operations = read_operations(payload)
    batch_seq = as_int(payload, "batch_seq", default=term["sis_sync_epoch"] + 1)

    batch = new_record(
        _kind="batch",
        term_id=term["id"],
        batch_seq=batch_seq,
        operations=operations,
        batch_state="DRAFT",
        validated_operation_count=0,
        rejected_operation_count=0,
        applied_add_count=0,
        applied_drop_count=0,
        promoted_from_waitlist_count=0,
        failure_reason=None,
    )
    db.batches[batch["id"]] = batch
    return created(batch)


@bp.get("/enrollment-sync-batches")
def list_batches():
    guard(REGISTRAR, LMS_ADMIN)
    records = apply_filters(db.batches.values(), {
        "term_id": "term_id",
        "batch_state": "batch_state",
    })
    return listing(records)


@bp.get("/enrollment-sync-batches/<batch_id>")
def read_batch(batch_id):
    guard(REGISTRAR, LMS_ADMIN)
    return ok(lookup.batch(batch_id))


def apply_operations(batch, term):
    adds = 0
    drops = 0
    promotions = 0
    for entry in batch["operations"]:
        shell = db.shells[entry["shell_id"]]
        if entry["op"] == "ADD":
            person = db.people[entry["person_id"]]
            cap = compute.frozen_seat_cap(shell, term)
            open_seat = len(compute.active_rows(shell["id"])) < cap
            state = "ACTIVE"
            if entry["role"] == "STUDENT" and not open_seat:
                state = "WAITLISTED"
            new_enrollment(shell, person, entry["role"], state,
                           batch_id=batch["id"])
            adds += 1
            compute.run_capacity(shell, term, promote=False)
        else:
            live = [e for e in pair_rows(entry["shell_id"], entry["person_id"])
                    if e["enrollment_state"] == "ACTIVE"]
            if live:
                row = live[0]
                set_field(row, "enrollment_state", "DROPPED")
                set_field(row, "dropped_at", now())
                mark(row)
                drops += 1
            promotions += compute.run_capacity(shell, term, promote=True)
    set_field(batch, "applied_add_count", adds)
    set_field(batch, "applied_drop_count", drops)
    set_field(batch, "promoted_from_waitlist_count", promotions)


@bp.post("/enrollment-sync-batches/<batch_id>/transitions")
def drive_batch(batch_id):
    guard(REGISTRAR)
    batch = lookup.batch(batch_id)
    payload = body()
    action = as_str(payload, "action", required=True)
    require(action in ACTIONS, "ERR_INVALID_STATE_TRANSITION",
            "'%s' is not a declared sync-batch action." % action)
    term = db.terms[batch["term_id"]]
    state = batch["batch_state"]

    if action == "CANCEL":
        require(state == "DRAFT", "ERR_INVALID_STATE_TRANSITION",
                "CANCEL runs from DRAFT, not from %s." % state)
        set_field(batch, "batch_state", "CANCELLED")
        mark(batch)
        return ok(batch)

    if action == "VALIDATE":
        require(state == "DRAFT", "ERR_INVALID_STATE_TRANSITION",
                "VALIDATE runs from DRAFT, not from %s." % state)
        require(term["lifecycle_state"] in ("REGISTRATION_OPEN", "IN_SESSION"),
                "ERR_INVALID_STATE_TRANSITION",
                "A term in %s does not accept a sync batch."
                % term["lifecycle_state"])
        valid = 0
        rejected = 0
        for entry in batch["operations"]:
            if operation_valid(batch, entry):
                valid += 1
            else:
                rejected += 1
        set_field(batch, "batch_state", "VALIDATED")
        set_field(batch, "validated_operation_count", valid)
        set_field(batch, "rejected_operation_count", rejected)
        mark(batch)
        return ok(batch)

    require(state == "VALIDATED", "ERR_INVALID_STATE_TRANSITION",
            "APPLY runs from VALIDATED, not from %s." % state)
    seen_pairs = set()
    for entry in batch["operations"]:
        if entry["op"] != "ADD":
            continue
        pair = (entry["shell_id"], entry["person_id"])
        blocked = [e for e in pair_rows(pair[0], pair[1])
                   if e["enrollment_state"] in BLOCKING_PAIR_STATES]
        require(not blocked and pair not in seen_pairs, "ERR_ROLE_CONFLICT",
                "An ADD operation targets a shell-and-person pair that already "
                "holds a live enrollment.")
        seen_pairs.add(pair)
    require(batch["batch_seq"] == term["sis_sync_epoch"] + 1,
            "ERR_SYNC_EPOCH_OUT_OF_ORDER",
            "This batch arrived out of feed order.")

    drifted = [e for e in batch["operations"]
               if db.shells.get(e["shell_id"]) is None
               or db.shells[e["shell_id"]]["provisioning_state"] not in LIVE_SHELL]
    if batch["rejected_operation_count"] > 0 or drifted:
        set_field(batch, "batch_state", "FAILED")
        if batch["rejected_operation_count"] > 0:
            reason = "rejected operations present"
        else:
            reason = "shell state changed since validation"
        set_field(batch, "failure_reason", reason)
        mark(batch)
        return ok(batch)

    apply_operations(batch, term)
    set_field(batch, "batch_state", "APPLIED")
    set_field(term, "sis_sync_epoch", term["sis_sync_epoch"] + 1)
    mark(batch)
    mark(term)
    return ok(batch)
