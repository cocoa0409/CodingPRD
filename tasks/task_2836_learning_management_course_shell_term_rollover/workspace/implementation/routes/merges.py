"""Cross-listing two sections through a merge request -- PRD 3.5."""

from decimal import Decimal

from flask import Blueprint

import lookup
from db import by_created, db, mark, new_record, set_field
from errors import require
from middleware import LMS_ADMIN, REGISTRAR, actor, as_int, as_str, bad, body
from routes.common import apply_filters, created, guard, listing, ok
from services import compute

bp = Blueprint("merges", __name__)

ACTIONS = ("SUBMIT", "APPROVE", "DECLINE", "APPLY", "REVERSE")
LIVE_SHELL = ("PROVISIONED", "PUBLISHED")
DEFAULT_JUSTIFICATION = "cross-listed section"
ZERO = Decimal("0.00")


def not_already_merged(child):
    require(child["merged_into_shell_id"] is None
            and child["provisioning_state"] != "MERGED",
            "ERR_SHELL_ALREADY_MERGED",
            "The child shell has already been absorbed into a parent.")


def same_term_official(parent, child):
    require(parent["term_id"] == child["term_id"]
            and parent["shell_type"] == "OFFICIAL"
            and child["shell_type"] == "OFFICIAL",
            "ERR_CROSS_TERM_MERGE",
            "Both shells must be OFFICIAL shells of the same term.")


def no_chain(parent, child):
    require(parent["merged_into_shell_id"] is None
            and child["absorbed_child_count"] == 0,
            "ERR_MERGE_CHAIN_FORBIDDEN",
            "Merge chains are forbidden.")


def segregation(merge):
    require(actor() != merge["submitted_by_user_id"],
            "ERR_SEGREGATION_OF_DUTIES",
            "The user who submitted this merge request may not decide it.")


@bp.post("/merge-requests")
def create_merge():
    guard(LMS_ADMIN)
    payload = body()
    parent = lookup.fk(payload, "parent_shell_id", "shells")
    child = lookup.fk(payload, "child_shell_id", "shells")
    if parent is None:
        as_str(payload, "parent_shell_id", required=True)
    if child is None:
        as_str(payload, "child_shell_id", required=True)
    justification = as_str(payload, "justification",
                           default=DEFAULT_JUSTIFICATION)
    expected = as_int(payload, "expected_parent_shell_version", required=True)
    if child["id"] == parent["id"]:
        bad("child_shell_id", "must differ from parent_shell_id")

    require(expected == parent["version"], "ERR_STALE_VERSION",
            "The parent shell has moved on to version %d." % parent["version"])
    not_already_merged(child)
    same_term_official(parent, child)
    no_chain(parent, child)

    merge = new_record(
        _kind="merge",
        parent_shell_id=parent["id"],
        child_shell_id=child["id"],
        justification=justification,
        submitted_by_user_id=actor(),
        decided_by_user_id=None,
        merge_state="DRAFT",
        moved_enrollment_count=0,
        reversed_enrollment_count=0,
        seat_ledger_before=None,
        seat_ledger_after=None,
    )
    db.merges[merge["id"]] = merge
    # PRD 2.7: "A successful create increments the parent shell's version by
    # one, so a superseding request must re-read the parent shell first."
    mark(parent)
    return created(merge)


@bp.get("/merge-requests")
def list_merges():
    guard(LMS_ADMIN, REGISTRAR)
    records = apply_filters(db.merges.values(), {
        "parent_shell_id": "parent_shell_id",
        "child_shell_id": "child_shell_id",
        "merge_state": "merge_state",
    })
    return listing(records)


@bp.get("/merge-requests/<merge_id>")
def read_merge(merge_id):
    guard(LMS_ADMIN, REGISTRAR)
    return ok(lookup.merge(merge_id))


def relocate(merge, parent, child, term):
    """The apply relocation of PRD 3.5, walked in created_at ascending order."""
    set_field(merge, "seat_ledger_before", term["total_active_enrollments"])
    moving = by_created([e for e in db.enrollments.values()
                         if e["shell_id"] == child["id"]
                         and e["enrollment_state"] == "ACTIVE"])
    for row in moving:
        set_field(row, "shell_id", parent["id"])
        set_field(row, "merged_from_shell_id", child["id"])
        mark(row)
    set_field(merge, "moved_enrollment_count", len(moving))
    set_field(child, "provisioning_state", "MERGED")
    set_field(child, "merged_into_shell_id", parent["id"])
    set_field(child, "active_enrollment_count", 0)
    set_field(child, "waitlisted_enrollment_count", 0)
    set_field(child, "seat_utilization_pct", ZERO)
    set_field(child, "overflow_flag", False)
    mark(child)
    # No waitlist promotion fires on the parent (PRD 3.5).
    compute.recompute_shell(child)
    compute.recompute_shell(parent)
    mark(parent)
    compute.recompute_term(term)
    mark(term)
    set_field(merge, "seat_ledger_after", term["total_active_enrollments"])


def send_home(merge, parent, child, term):
    returning = by_created([e for e in db.enrollments.values()
                            if e["shell_id"] == parent["id"]
                            and e["merged_from_shell_id"] == child["id"]])
    for row in returning:
        set_field(row, "shell_id", child["id"])
        set_field(row, "merged_from_shell_id", None)
        mark(row)
    set_field(merge, "reversed_enrollment_count", len(returning))
    set_field(child, "provisioning_state", "PROVISIONED")
    set_field(child, "merged_into_shell_id", None)
    mark(child)
    compute.recompute_shell(child)
    compute.recompute_shell(parent)
    mark(parent)
    compute.recompute_term(term)
    mark(term)


@bp.post("/merge-requests/<merge_id>/transitions")
def drive_merge(merge_id):
    guard(LMS_ADMIN)
    merge = lookup.merge(merge_id)
    payload = body()
    action = as_str(payload, "action", required=True)
    require(action in ACTIONS, "ERR_INVALID_STATE_TRANSITION",
            "'%s' is not a declared merge action." % action)
    parent = db.shells[merge["parent_shell_id"]]
    child = db.shells[merge["child_shell_id"]]
    term = db.terms[parent["term_id"]]
    state = merge["merge_state"]

    if action == "SUBMIT":
        require(state == "DRAFT", "ERR_INVALID_STATE_TRANSITION",
                "SUBMIT runs from DRAFT, not from %s." % state)
        require(parent["provisioning_state"] in LIVE_SHELL
                and child["provisioning_state"] in LIVE_SHELL,
                "ERR_INVALID_STATE_TRANSITION",
                "Both shells must be PROVISIONED or PUBLISHED to submit.")
        set_field(merge, "merge_state", "SUBMITTED")
        mark(merge)
        return ok(merge)

    if action in ("APPROVE", "DECLINE"):
        require(state == "SUBMITTED", "ERR_INVALID_STATE_TRANSITION",
                "%s runs from SUBMITTED, not from %s." % (action, state))
        segregation(merge)
        if action == "APPROVE":
            not_already_merged(child)
            same_term_official(parent, child)
            no_chain(parent, child)
            set_field(merge, "merge_state", "APPROVED")
        else:
            set_field(merge, "merge_state", "DECLINED")
        set_field(merge, "decided_by_user_id", actor())
        mark(merge)
        return ok(merge)

    if action == "APPLY":
        require(state == "APPROVED", "ERR_INVALID_STATE_TRANSITION",
                "APPLY runs from APPROVED, not from %s." % state)
        not_already_merged(child)
        relocate(merge, parent, child, term)
        set_field(merge, "merge_state", "APPLIED")
        mark(merge)
        return ok(merge)

    require(state == "APPLIED", "ERR_INVALID_STATE_TRANSITION",
            "REVERSE runs from APPLIED, not from %s." % state)
    require(parent["provisioning_state"] in LIVE_SHELL,
            "ERR_INVALID_STATE_TRANSITION",
            "The parent shell must be PROVISIONED or PUBLISHED to reverse.")
    send_home(merge, parent, child, term)
    set_field(merge, "merge_state", "REVERSED")
    mark(merge)
    return ok(merge)
