"""Assignment routes: commit, gold audits, grading and payout (PRD 3.3-3.10)."""

from flask import Blueprint

import auth
import db
import services
from envelope import list_ok, ok, paginate
from errors import (
    ERR_ALREADY_TERMINAL,
    ERR_COMMIT_NOT_FOUND,
    ERR_COMMIT_WINDOW_CLOSED,
    ERR_FIELD_SCHEMA_MISMATCH,
    ERR_GOLD_AUDIT_NOT_FOUND,
    ERR_GOLD_ROTATION_ACTIVE,
    ERR_INSTRUCTION_REVISION_MISMATCH,
    ERR_INVALID_STATE,
    ERR_ITEM_NOT_FOUND,
    ERR_PROGRAM_OPERATIONALLY_RESTRICTED,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_STALE_VERSION,
    ERR_WORKER_RESTRICTED,
    fail,
)
from helpers import (
    json_body,
    opt_bool,
    ordered_by_creation,
    pagination_params,
    query_enum,
    require_enum,
    require_int,
    require_str,
)

bp = Blueprint("commits", __name__)

ADMIN = auth.ROLE_ADMIN
REVIEWER = auth.ROLE_REVIEWER
WORKER = auth.ROLE_WORKER


def _commit_or_404(commit_id):
    commit = db.commits.get(commit_id)
    if commit is None:
        fail(ERR_COMMIT_NOT_FOUND)
    return commit


@bp.get("/api/commits")
def list_commits():
    principal = auth.enforce_headers()
    auth.enforce_role(principal, (ADMIN, REVIEWER, WORKER))
    status = query_enum("status", services.COMMIT_STATUSES)
    kind = query_enum("kind", services.COMMIT_KINDS)
    rows = list(db.commits.values())
    if status:
        rows = [c for c in rows if c.get("status") == status]
    if kind:
        rows = [c for c in rows if c.get("kind") == kind]
    rows = ordered_by_creation(rows)
    limit, offset = pagination_params()
    page, pagination = paginate(rows, limit, offset)
    return list_ok([services.commit_view(c) for c in page], pagination=pagination)


@bp.get("/api/commits/<commit_id>")
def read_commit(commit_id):
    principal = auth.enforce_headers()
    auth.enforce_role(principal, (ADMIN, REVIEWER, WORKER))
    commit = _commit_or_404(commit_id)
    if principal.role == WORKER and commit.get("worker_id") != principal.user_id:
        fail(ERR_COMMIT_NOT_FOUND)
    return ok(services.commit_view(commit))


@bp.post("/api/commits/<commit_id>/commit-label")
def commit_label(commit_id):
    """Submit a worker label payload, or record an abstention (PRD section 3.3)."""
    principal = auth.enforce_headers()
    auth.enforce_role(principal, (WORKER,))
    commit = _commit_or_404(commit_id)

    body = json_body()
    abstained = opt_bool(body, "abstained", False)
    instructions_ack = body.get("instructions_ack", False)
    payload = body.get("payload")

    item = db.items.get(commit.get("item_id"))
    unit = db.spec_units.get(item.get("spec_unit_id")) if item else None
    program = db.programs.get(unit.get("program_id")) if unit else None

    # Rank 3 -- the acting worker may only answer their own assignment.
    if commit.get("worker_id") != principal.user_id:
        fail(ERR_COMMIT_NOT_FOUND)

    # Rank 5 -- state admissibility.
    if program is None or program.get("status") == "FROZEN" or item is None:
        fail(ERR_INVALID_STATE)
    if commit.get("status") != "DISPATCHED":
        fail(ERR_ALREADY_TERMINAL)
    if item.get("status") == "RESOLVED":
        fail(ERR_INVALID_STATE)

    # Rank 6 -- safety band.
    worker = db.workers.get(commit.get("worker_id"))
    services.refresh_worker_restricted(worker)
    if worker is not None and worker.get("restricted"):
        fail(ERR_WORKER_RESTRICTED)

    if not abstained:
        if instructions_ack is not True:
            fail(ERR_FIELD_SCHEMA_MISMATCH, "instructions_ack must be true on every commit.")
        schema = list(unit.get("field_schema") or [])
        if not isinstance(payload, dict) or set(payload.keys()) != set(schema):
            fail(ERR_FIELD_SCHEMA_MISMATCH)

    # Rank 7 -- the pinned instruction revision.
    if unit.get("frozen_revision") is not None and commit.get("instruction_revision") is not None:
        if commit.get("instruction_revision") != unit.get("frozen_revision"):
            fail(ERR_INSTRUCTION_REVISION_MISMATCH)

    # Rank 8 -- the commit window.
    if db.now() >= commit.get("commit_deadline_at"):
        fail(ERR_COMMIT_WINDOW_CLOSED)

    if abstained:
        commit["status"] = "ABSTAINED"
        commit["abstained"] = True
        commit["committed_value"] = None
    else:
        commit["status"] = "COMMITTED"
        commit["abstained"] = False
        commit["payload"] = payload
        commit["committed_value"] = services.canonical_value(payload, list(unit.get("field_schema") or []))
    db.touch(commit)

    services.refresh_item_derived(item)
    db.touch(item)
    if not abstained:
        services.stamp_value_groups(item)
        services.refresh_item_derived(item)
        services.resolve_consensus(item)
    return ok(services.commit_view(commit))


@bp.post("/api/commits/<commit_id>/gold-audits")
def create_gold_audit(commit_id):
    """Create a GOLD audit over an already committed panel member (PRD §3.7)."""
    principal = auth.enforce_headers()
    auth.enforce_role(principal, (REVIEWER,))
    commit = _commit_or_404(commit_id)

    body = json_body()
    gold_task_key = require_str(body, "gold_task_key")

    item = db.items.get(commit.get("item_id"))
    if item is None:
        fail(ERR_ITEM_NOT_FOUND)
    unit = db.spec_units.get(item.get("spec_unit_id"))
    program = db.programs.get(unit.get("program_id")) if unit else None

    # Rank 5 -- state admissibility.
    if program is None or program.get("status") == "FROZEN":
        fail(ERR_INVALID_STATE)
    if commit.get("status") != "COMMITTED":
        fail(ERR_INVALID_STATE)

    # Rank 9 -- the weekly gold rotation. PRD §3.7: a piece whose
    # gold_audits_this_week has reached 3 carries gold_rotation while it is not
    # in REWORK, and it "cannot be dispatched back into a production panel".
    if int(item.get("gold_audits_this_week", 0) or 0) >= services.GOLD_ROTATION_THRESHOLD and item.get(
        "consensus_status"
    ) != "REWORK":
        fail(ERR_GOLD_ROTATION_ACTIVE)

    # Rank 6 -- the engagement-restricted guard reaches gold-audit creation.
    services.refresh_incident_flags(program)
    if program.get("operational_restricted"):
        fail(ERR_PROGRAM_OPERATIONALLY_RESTRICTED)

    audit = services.create_gold_audit(item, gold_task_key)
    return ok(services.commit_view(audit), status=201)


@bp.post("/api/gold-audits/<audit_id>/grade-audit")
def grade_audit(audit_id):
    principal = auth.enforce_headers()
    auth.enforce_role(principal, (REVIEWER,))
    audit = db.commits.get(audit_id)
    if audit is None or audit.get("kind") != "GOLD":
        fail(ERR_GOLD_AUDIT_NOT_FOUND)

    body = json_body()
    outcome = require_enum(body, "gold_outcome", services.GOLD_OUTCOMES)
    expected_item_version = require_int(body, "expected_item_version")

    item = db.items.get(audit.get("item_id"))
    if item is None:
        fail(ERR_ITEM_NOT_FOUND)
    unit = db.spec_units.get(item.get("spec_unit_id"))
    program = db.programs.get(unit.get("program_id")) if unit else None

    # Rank 4 -- optimistic concurrency.
    if int(expected_item_version) != int(item.get("version")):
        fail(ERR_STALE_VERSION)

    # Rank 5 -- state admissibility.
    if program is None or program.get("status") == "FROZEN":
        fail(ERR_INVALID_STATE)
    if audit.get("status") == "COMMIT_EXPIRED":
        fail(ERR_ALREADY_TERMINAL)

    # Rank 9 -- segregation of duties.
    if auth.reviewer_holds_commit(principal.user_id, item["id"]):
        fail(ERR_SEGREGATION_OF_DUTIES)

    services.grade_audit(audit, outcome, principal.user_id)
    return ok(services.commit_view(audit))


@bp.post("/api/commits/<commit_id>/payout-records")
def payout_record(commit_id):
    principal = auth.enforce_headers()
    auth.enforce_role(principal, (ADMIN,))
    commit = _commit_or_404(commit_id)

    body = json_body()
    amount_cents = require_int(body, "amount_cents")
    currency = require_str(body, "currency")

    services.accept_payout(commit, amount_cents, currency)
    return ok(services.commit_view(commit))