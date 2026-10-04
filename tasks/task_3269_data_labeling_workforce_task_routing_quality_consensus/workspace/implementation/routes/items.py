"""Labeling piece routes: listing, dispatch, reviewer decisions and rework."""

from flask import Blueprint

import auth
import db
import services
from envelope import list_ok, ok, paginate
from errors import (
    ERR_COMMIT_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_WORKER_RESTRICTED,
    ERR_INVALID_STATE,
    ERR_ITEM_NOT_FOUND,
    ERR_PROGRAM_NOT_FOUND,
    ERR_PROGRAM_OPERATIONALLY_RESTRICTED,
    ERR_QUORUM_NOT_REACHED,
    ERR_SEGREGATION_OF_DUTIES,
    fail,
)
from helpers import (
    json_body,
    opt_str,
    ordered_by_creation,
    pagination_params,
    query_enum,
    query_str,
    require_enum_ci,
    require_str,
)

bp = Blueprint("items", __name__)

ADMIN = auth.ROLE_ADMIN
REVIEWER = auth.ROLE_REVIEWER
WORKER = auth.ROLE_WORKER


def _item_or_404(item_id):
    item = db.items.get(item_id)
    if item is None:
        fail(ERR_ITEM_NOT_FOUND)
    return item


@bp.get("/api/items")
def list_items():
    principal = auth.enforce_headers()
    auth.enforce_role(principal, (ADMIN, REVIEWER, WORKER))
    spec_unit_id = query_str("spec_unit_id")
    program_id = query_str("program_id")
    consensus_status = query_enum("consensus_status", services.CONSENSUS_STATUSES)

    rows = list(db.items.values())
    if spec_unit_id:
        rows = [i for i in rows if i.get("spec_unit_id") == spec_unit_id]
    if program_id:
        kept = []
        for item in rows:
            unit = db.spec_units.get(item.get("spec_unit_id"))
            if unit is not None and unit.get("program_id") == program_id:
                kept.append(item)
        rows = kept
    if consensus_status:
        rows = [i for i in rows if i.get("consensus_status") == consensus_status]

    if spec_unit_id:
        # The item list for a unit is ordered by item_seq ascending (PRD §2.3).
        rows = sorted(rows, key=lambda i: (i.get("item_seq") or 0, db.creation_seq(i)))
    else:
        rows = ordered_by_creation(rows)

    limit, offset = pagination_params()
    page, pagination = paginate(rows, limit, offset)
    return list_ok([services.item_view(i) for i in page], pagination=pagination)


@bp.get("/api/items/<item_id>")
def read_item(item_id):
    principal = auth.enforce_headers()
    auth.enforce_role(principal, (ADMIN, REVIEWER, WORKER))
    item = _item_or_404(item_id)
    return ok(services.item_view(item))


@bp.post("/api/items/<item_id>/dispatch-panel")
def dispatch_panel(item_id):
    principal = auth.enforce_headers()
    auth.enforce_role(principal, (ADMIN,))
    item = _item_or_404(item_id)
    services.dispatch_panel(item)
    return ok(services.item_view(item))


@bp.post("/api/items/<item_id>/reviewer-action")
def reviewer_action(item_id):
    principal = auth.enforce_headers()
    auth.enforce_role(principal, (REVIEWER, ADMIN))
    item = _item_or_404(item_id)

    body = json_body()
    action = require_enum_ci(body, "reviewer_action", ("RESOLVE_PANEL_DECISION", "OPEN_REWORK"))
    decision_value = opt_str(body, "decision_value", None)

    if action == "RESOLVE_PANEL_DECISION":
        return ok(_resolve_panel(item, principal, decision_value))
    return ok(services.open_rework(item, principal.user_id))


def _resolve_panel(item, principal, decision_value):
    unit = db.spec_units.get(item.get("spec_unit_id"))
    program = db.programs.get(unit.get("program_id")) if unit else None

    # Rank 5 -- state admissibility.
    if program is None or program.get("status") == "FROZEN":
        fail(ERR_INVALID_STATE)
    # PRD §3.5 ties the reviewer's authority to "at least commitment_quorum
    # non-abstaining commits" and reserves ERR_QUORUM_NOT_REACHED for that
    # floor, so the quorum gate is reported ahead of the state gate: a piece
    # still short of quorum is refused for the quorum rather than for its
    # consensus state.
    quorum = int(program.get("commitment_quorum", services.DEFAULT_COMMITMENT_QUORUM))
    if len(services.committed_rows(item["id"])) < quorum:
        fail(ERR_QUORUM_NOT_REACHED)
    if item.get("consensus_status") != "HELD_QUORUM":
        fail(ERR_INVALID_STATE)

    services.refresh_incident_flags(program)
    if program.get("operational_restricted"):
        fail(ERR_PROGRAM_OPERATIONALLY_RESTRICTED)

    # Rank 9 -- the segregation guard.
    if auth.reviewer_holds_commit(principal.user_id, item["id"]):
        fail(ERR_SEGREGATION_OF_DUTIES)

    item["consensus_status"] = "CERTIFIED"
    item["item_status"] = "COMPLETED"
    item["status"] = "RESOLVED"
    item["holds_quorum"] = False
    if decision_value is not None:
        item["modal_label"] = decision_value
    item["delivered_at"] = db.now()
    services.stamp_value_groups(item)
    services.refresh_item_derived(item)
    db.touch(item)

    if unit is not None:
        services.pin_frozen_revision(unit, item)
        services.refresh_unit_metrics(unit)
        db.touch(unit)
        services.maybe_complete_unit(unit)
    services.refresh_program_plan(program)
    db.touch(program)
    return services.item_view(item)


@bp.post("/api/items/<item_id>/submit-rework")
def submit_rework(item_id):
    principal = auth.enforce_headers()
    auth.enforce_role(principal, (WORKER,))
    item = _item_or_404(item_id)

    body = json_body()
    commit_id = require_str(body, "commit_id")
    payload = body.get("payload")
    instructions_ack = body.get("instructions_ack", False)
    if "instructions_ack" not in body:
        fail(ERR_INVALID_REQUEST, "instructions_ack is required.")

    unit = db.spec_units.get(item.get("spec_unit_id"))
    program = db.programs.get(unit.get("program_id")) if unit else None
    if program is not None and program.get("status") == "FROZEN":
        fail(ERR_INVALID_STATE)
    if item.get("consensus_status") != "REWORK":
        fail(ERR_INVALID_STATE)

    commit = db.commits.get(commit_id)
    if commit is None or commit.get("item_id") != item_id:
        fail(ERR_COMMIT_NOT_FOUND)

    # Ownership: the acting worker must own the superseded assignment (PRD §3.6).
    if commit.get("worker_id") != principal.user_id:
        fail(ERR_SEGREGATION_OF_DUTIES)

    services.submit_rework(item, commit_id, payload, bool(instructions_ack))
    return ok(services.item_view(item))


@bp.get("/api/items/<item_id>/commits")
def list_commits(item_id):
    principal = auth.enforce_headers()
    auth.enforce_role(principal, (ADMIN, REVIEWER, WORKER))
    _item_or_404(item_id)
    kind = query_enum("kind", services.COMMIT_KINDS)
    status = query_enum("status", services.COMMIT_STATUSES)

    rows = db.commits_of_item(item_id)
    if kind:
        rows = [c for c in rows if c.get("kind") == kind]
    if status:
        rows = [c for c in rows if c.get("status") == status]
    # The commit list orders by dispatch_rank ascending (PRD §2.3).
    rows = sorted(rows, key=lambda c: (c.get("dispatch_rank") or 0, db.creation_seq(c)))

    limit, offset = pagination_params()
    page, pagination = paginate(rows, limit, offset)
    return list_ok([services.commit_view(c) for c in page], pagination=pagination)


@bp.get("/api/items/<item_id>/appeal-cases")
def list_appeals(item_id):
    principal = auth.enforce_headers()
    auth.enforce_role(principal, (ADMIN, REVIEWER, WORKER))
    _item_or_404(item_id)
    rows = [a for a in db.appeals.values() if a.get("item_id") == item_id]
    rows = ordered_by_creation(rows)
    limit, offset = pagination_params()
    page, pagination = paginate(rows, limit, offset)
    return list_ok([services.appeal_view(a) for a in page], pagination=pagination)