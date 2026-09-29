"""Tool placements in a shell -- PRD 3.7."""

from flask import Blueprint

import lookup
from db import db, mark, new_record, set_field
from errors import require
from middleware import INSTRUCTOR, LMS_ADMIN, as_str, body
from routes.common import apply_filters, created, guard, listing, ok
from routes.content import sandbox_gate
from services import access, cascade, compute

bp = Blueprint("placements", __name__)

ACTIONS = ("ACTIVATE", "REMOVE")
LIVE_SHELL = ("PROVISIONED", "PUBLISHED")
EXPOSED_STATES = ("ACTIVE", "WAITLISTED")


def ferpa_clear(tool, shell):
    """A placement that shares data may not expose a person whose ferpa_block
    is true (PRD 3.7 / 2.10 band 13)."""
    if tool["data_sharing_scope"] == "NONE":
        return
    for row in db.enrollments.values():
        if row["shell_id"] != shell["id"]:
            continue
        if row["enrollment_state"] not in EXPOSED_STATES:
            continue
        person = db.people.get(row["person_id"])
        if person is not None and person["ferpa_block"]:
            require(False, "ERR_FERPA_BLOCK_ACTIVE",
                    "A person in this shell carries a FERPA directory block.")


@bp.post("/tool-placements")
def create_placement():
    guard(INSTRUCTOR, LMS_ADMIN)
    payload = body()
    access.own_shell(lookup.peek("shells", payload.get("shell_id")))
    tool = lookup.fk(payload, "tool_id", "tools")
    shell = lookup.fk(payload, "shell_id", "shells")
    if tool is None:
        as_str(payload, "tool_id", required=True)
    if shell is None:
        as_str(payload, "shell_id", required=True)
    sandbox_gate(shell)
    require(shell["provisioning_state"] in LIVE_SHELL,
            "ERR_SHELL_STATE_BLOCKS_ENROLLMENT",
            "A shell in %s does not accept a tool placement."
            % shell["provisioning_state"])

    placement = new_record(
        _kind="placement",
        tool_id=tool["id"],
        shell_id=shell["id"],
        placement_state="REQUESTED",
        pinned_tool_version=None,
        blocked_reason=None,
    )
    db.placements[placement["id"]] = placement
    compute.recompute_shell(shell)
    return created(placement)


@bp.get("/tool-placements")
def list_placements():
    guard(INSTRUCTOR, LMS_ADMIN)
    records = apply_filters(db.placements.values(), {
        "tool_id": "tool_id",
        "shell_id": "shell_id",
        "placement_state": "placement_state",
    })
    return listing(records)


@bp.get("/tool-placements/<placement_id>")
def read_placement(placement_id):
    guard(INSTRUCTOR, LMS_ADMIN)
    return ok(lookup.placement(placement_id))


@bp.post("/tool-placements/<placement_id>/transitions")
def drive_placement(placement_id):
    guard(INSTRUCTOR, LMS_ADMIN)
    existing = lookup.peek("placements", placement_id)
    if existing is not None:
        access.own_shell(db.shells.get(existing["shell_id"]))
    placement = lookup.placement(placement_id)
    payload = body()
    action = as_str(payload, "action", required=True)
    require(action in ACTIONS, "ERR_INVALID_STATE_TRANSITION",
            "'%s' is not a declared placement action." % action)
    tool = db.tools[placement["tool_id"]]
    shell = db.shells[placement["shell_id"]]
    state = placement["placement_state"]

    if action == "ACTIVATE":
        require(state == "REQUESTED", "ERR_INVALID_STATE_TRANSITION",
                "ACTIVATE runs from REQUESTED, not from %s." % state)
        ferpa_clear(tool, shell)
        require(tool["approval_state"] in ("APPROVED", "CONDITIONAL"),
                "ERR_TOOL_NOT_APPROVED",
                "A tool in %s may not be placed." % tool["approval_state"])
        require(tool["approved_version"] == tool["tool_version"],
                "ERR_TOOL_VERSION_DRIFT",
                "The tool's approved_version no longer matches its tool_version.")
        require(shell["provisioning_state"] in LIVE_SHELL,
                "ERR_SHELL_STATE_BLOCKS_ENROLLMENT",
                "A shell in %s does not accept an active placement."
                % shell["provisioning_state"])
        set_field(placement, "placement_state", "ACTIVE")
        set_field(placement, "pinned_tool_version", tool["approved_version"])
        mark(placement)
        compute.rescore_tool(tool)
        mark(tool)
        compute.recompute_shell(shell)
        return ok(placement)

    require(state in ("REQUESTED", "ACTIVE", "BLOCKED"),
            "ERR_INVALID_STATE_TRANSITION",
            "REMOVE runs from REQUESTED, ACTIVE or BLOCKED, not from %s." % state)
    cascade.remove_placement(placement)
    return ok(placement)
