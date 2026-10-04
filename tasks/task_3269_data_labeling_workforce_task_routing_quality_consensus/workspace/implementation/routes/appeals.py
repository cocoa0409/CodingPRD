"""Appeal ladder routes (PRD section 3.12).

The twelve edges of the ladder:
    ADVOCACY    -> PROPOSED              (PROPOSE)
    PROPOSED    -> CONCURRENCE           (CONCUR on PAY_REVERSAL/AMBIGUOUS)
    CONCURRENCE -> ACCEPTED              (automatic)
    PROPOSED    -> ADJUDICATION          (ESCALATE on QUALIFICATION_RESET)
    ADJUDICATION-> CONCURRENCE           (CONCUR on QUALIFICATION_RESET)
    ADJUDICATION-> PROPOSED              (ESCALATE, reviewer to reviewer cycle)
    ADJUDICATION-> REVIEWER_SUSPENSION   (SUSPEND by PlatformAdmin)
    PROPOSED    -> REJECTED              (WITHDRAW by the filing worker)
    ADJUDICATION-> DEADLOCK              (automatic deadlock sweep)
plus the proposal's compensating-amount stamp and the two terminal leaves.
"""

from flask import Blueprint

import auth
import db
import services
from envelope import ok
from errors import (
    ERR_APPEAL_CASE_NOT_FOUND,
    ERR_UNAUTHORIZED,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_ITEM_NOT_FOUND,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_STALE_VERSION,
    fail,
)
from helpers import (
    json_body,
    opt_enum,
    opt_str,
    require_enum,
    require_enum_ci,
    require_int,
    require_str,
)

bp = Blueprint("appeals", __name__)

ADMIN = auth.ROLE_ADMIN
REVIEWER = auth.ROLE_REVIEWER
WORKER = auth.ROLE_WORKER

TERMINAL = ("ACCEPTED", "REVIEWER_SUSPENSION", "REJECTED", "DEADLOCK")


def _claim_or_404(claim_id):
    claim = db.appeals.get(claim_id)
    if claim is None:
        fail(ERR_APPEAL_CASE_NOT_FOUND)
    return claim


def _disputed_commit(claim):
    """The claim's worker's assignment on the disputed piece."""
    rows = [
        c
        for c in db.commits.values()
        if c.get("item_id") == claim.get("item_id") and c.get("worker_id") == claim.get("worker_id")
    ]
    if not rows:
        return None
    accepted = [c for c in rows if c.get("payment_status") == "ACCEPTED"]
    pool = accepted or rows
    return sorted(pool, key=lambda c: (c.get("dispatch_rank") or 0, db.creation_seq(c)))[0]


def _patience(claim):
    program = db.programs.get(claim.get("program_id"))
    return int((program or {}).get("patience_seconds", services.DEFAULT_PATIENCE_SECONDS))


def _program(claim):
    return db.programs.get(claim.get("program_id"))


def _enforce_not_frozen(claim):
    program = _program(claim)
    if program is not None and program.get("status") == "FROZEN":
        fail(ERR_INVALID_STATE)


# --------------------------------------------------------------------------
# POST /api/appeal-cases
# --------------------------------------------------------------------------
@bp.post("/api/appeal-cases")
def file_appeal():
    principal = auth.enforce_headers()
    auth.enforce_role(principal, (WORKER, REVIEWER))
    body = json_body()

    item_id = require_str(body, "item_id")
    grounds = require_enum(body, "grounds", services.APPEAL_GROUNDS)
    statement_text = require_str(body, "statement_text")
    requested_reviewer_id = opt_str(body, "requested_reviewer_id", None)

    item = db.items.get(item_id)
    if item is None:
        fail(ERR_ITEM_NOT_FOUND)
    unit = db.spec_units.get(item.get("spec_unit_id"))
    if unit is None:
        fail(ERR_ITEM_NOT_FOUND)
    program = db.programs.get(unit.get("program_id"))
    if program is None:
        fail(ERR_ITEM_NOT_FOUND)

    # The claim resolves its own references rather than trusting the client.
    worker_id = principal.user_id
    if principal.role == REVIEWER:
        worker_id = opt_str(body, "worker_id", principal.user_id)

    record = {
        "program_id": program["id"],
        "item_id": item_id,
        "worker_id": worker_id,
        "spec_unit_id": unit["id"],
        "grounds": grounds,
        "statement_text": statement_text,
        "requested_reviewer_id": requested_reviewer_id,
        "adjudicator_id": None,
        "proposed_outcome": None,
        "revised_amount_cents": None,
        "lock_reason": None,
        "consensus_outcome": None,
        "adjudication_started_at": None,
        "status": "ADVOCACY",
    }
    db.seal(record)
    db.appeals[record["id"]] = record
    return ok(services.appeal_view(record), status=201)


# --------------------------------------------------------------------------
# POST /api/appeal-cases/{id}/advance-appeal
# --------------------------------------------------------------------------
@bp.post("/api/appeal-cases/<claim_id>/advance-appeal")
def advance_appeal(claim_id):
    principal = auth.enforce_headers()
    auth.enforce_role(principal, (REVIEWER, ADMIN, WORKER))
    claim = _claim_or_404(claim_id)

    body = json_body()
    action = require_enum_ci(body, "appeal_action", ("PROPOSE", "ESCALATE", "SUSPEND", "WITHDRAW"))
    proposed_outcome = opt_enum(body, "proposed_outcome", services.PROPOSED_OUTCOMES, None)

    _enforce_not_frozen(claim)

    if action == "PROPOSE":
        return ok(_propose(claim, principal, proposed_outcome))
    if action == "ESCALATE":
        return ok(_escalate(claim, principal, proposed_outcome))
    if action == "SUSPEND":
        return ok(_suspend(claim, principal))
    return ok(_withdraw(claim, principal))


def _propose(claim, principal, proposed_outcome):
    if principal.role not in (REVIEWER, ADMIN):
        fail(ERR_UNAUTHORIZED)
    if claim.get("status") != "ADVOCACY":
        fail(ERR_INVALID_STATE)
    if proposed_outcome is None:
        fail(ERR_INVALID_REQUEST, "proposed_outcome is required.")
    if auth.reviewer_holds_commit(principal.user_id, claim["item_id"]):
        fail(ERR_SEGREGATION_OF_DUTIES)

    claim["status"] = "PROPOSED"
    claim["adjudicator_id"] = principal.user_id
    claim["proposed_outcome"] = proposed_outcome
    claim["revised_amount_cents"] = None
    if claim.get("grounds") == "AMBIGUOUS_INSTRUCTIONS" and proposed_outcome == "PAY_REVERSAL":
        disputed = _disputed_commit(claim)
        claim["revised_amount_cents"] = (
            int(disputed.get("paid_amount_cents", 0)) if disputed is not None else 0
        )
    db.touch(claim)
    return services.appeal_view(claim)


def _escalate(claim, principal, proposed_outcome):
    if principal.role not in (REVIEWER, ADMIN):
        fail(ERR_UNAUTHORIZED)
    status = claim.get("status")
    if status not in ("PROPOSED", "ADJUDICATION"):
        fail(ERR_INVALID_STATE)
    if principal.user_id == claim.get("adjudicator_id"):
        fail(ERR_SEGREGATION_OF_DUTIES)

    if status == "PROPOSED":
        if claim.get("proposed_outcome") != "QUALIFICATION_RESET":
            fail(ERR_INVALID_STATE)
        claim["status"] = "ADJUDICATION"
        claim["adjudication_started_at"] = db.now()
        db.touch(claim)
        return services.appeal_view(claim)

    # ADJUDICATION -> PROPOSED: a different reviewer takes the proposal over.
    if proposed_outcome is None:
        fail(ERR_INVALID_REQUEST, "proposed_outcome is required.")
    claim["status"] = "PROPOSED"
    claim["adjudicator_id"] = principal.user_id
    claim["proposed_outcome"] = proposed_outcome
    claim["revised_amount_cents"] = None
    if claim.get("grounds") == "AMBIGUOUS_INSTRUCTIONS" and proposed_outcome == "PAY_REVERSAL":
        disputed = _disputed_commit(claim)
        claim["revised_amount_cents"] = (
            int(disputed.get("paid_amount_cents", 0)) if disputed is not None else 0
        )
    claim["adjudication_started_at"] = None
    db.touch(claim)
    return services.appeal_view(claim)


def _suspend(claim, principal):
    if principal.role != ADMIN:
        fail(ERR_UNAUTHORIZED)
    if claim.get("status") != "ADJUDICATION":
        fail(ERR_INVALID_STATE)
    if db.elapsed_seconds(claim.get("adjudication_started_at")) < _patience(claim):
        fail(ERR_INVALID_STATE)

    claim["status"] = "REVIEWER_SUSPENSION"
    claim["lock_reason"] = "REVIEWER_SUSPENSION"
    db.touch(claim)

    item = db.items.get(claim.get("item_id"))
    if item is not None:
        item["holds_quorum"] = True
        services.refresh_item_derived(item)
        db.touch(item)
    return services.appeal_view(claim)


def _withdraw(claim, principal):
    if principal.role != WORKER:
        fail(ERR_UNAUTHORIZED)
    if claim.get("status") != "PROPOSED":
        fail(ERR_INVALID_STATE)
    if principal.user_id != claim.get("worker_id"):
        fail(ERR_SEGREGATION_OF_DUTIES)
    if db.elapsed_seconds(claim.get("created_at")) > _patience(claim):
        fail(ERR_INVALID_STATE)

    claim["status"] = "REJECTED"
    claim["lock_reason"] = None
    db.touch(claim)
    return services.appeal_view(claim)


# --------------------------------------------------------------------------
# POST /api/appeal-cases/{id}/concur
# --------------------------------------------------------------------------
@bp.post("/api/appeal-cases/<claim_id>/concur")
def concur(claim_id):
    principal = auth.enforce_headers()
    auth.enforce_role(principal, (REVIEWER,))
    claim = _claim_or_404(claim_id)

    body = json_body()
    expected_claim_version = require_int(body, "expected_claim_version")

    # Rank 4 -- optimistic concurrency.
    if int(expected_claim_version) != int(claim.get("version")):
        fail(ERR_STALE_VERSION)

    _enforce_not_frozen(claim)

    # Rank 5 -- state admissibility.
    status = claim.get("status")
    if status not in ("PROPOSED", "ADJUDICATION"):
        fail(ERR_INVALID_STATE)

    # Rank 9 -- segregation of duties, including the claim's own adjudicator.
    if principal.user_id == claim.get("adjudicator_id"):
        fail(ERR_SEGREGATION_OF_DUTIES)
    if auth.reviewer_holds_commit(principal.user_id, claim["item_id"]):
        fail(ERR_SEGREGATION_OF_DUTIES)

    if status == "PROPOSED":
        if not (
            claim.get("proposed_outcome") == "PAY_REVERSAL"
            and claim.get("grounds") == "AMBIGUOUS_INSTRUCTIONS"
        ):
            fail(ERR_INVALID_STATE)
        _apply_pay_reversal(claim)
        claim["status"] = "CONCURRENCE"
        db.touch(claim)
        _redispatch_disputed_piece(claim)
        # The concurrence completing without disagreement accepts the claim.
        claim["status"] = "ACCEPTED"
        db.touch(claim)
        return ok(services.appeal_view(claim))

    if claim.get("proposed_outcome") != "QUALIFICATION_RESET":
        fail(ERR_INVALID_STATE)
    _apply_qualification_reset(claim)
    claim["status"] = "CONCURRENCE"
    db.touch(claim)
    return ok(services.appeal_view(claim))


def _apply_pay_reversal(claim):
    """Move the disputed payment to REVERSED and credit the receivable (PRD 3.12)."""
    disputed = _disputed_commit(claim)
    revised = int(claim.get("revised_amount_cents") or 0)

    if disputed is not None:
        worker = db.workers.get(disputed.get("worker_id"))
        services.refresh_worker_metrics(worker)
        if worker is not None:
            # The reversal credits the receivable and never rewinds lifetime earnings.
            disputed["payment_status"] = "REVERSED"
            disputed["reversed_amount_cents"] = revised
            disputed["payment_capped"] = False
            db.touch(disputed)
            services.refresh_worker_metrics(worker)
            if int(worker.get("worker_receivable_cents", 0)) < 0:
                fail(ERR_INSUFFICIENT_RECEIVABLE)
            db.touch(worker)

    qualification = None
    if disputed is not None:
        item = db.items.get(disputed.get("item_id"))
        unit = db.spec_units.get(item.get("spec_unit_id")) if item else None
        program = db.programs.get(unit.get("program_id")) if unit else None
        qualification = services.qualification_of_commit(disputed, program)
    if qualification is not None:
        qualification["gold_fail_streak"] = 0
        services.refresh_qualification_metrics(qualification)
        db.touch(qualification)


def _apply_qualification_reset(claim):
    """Clear the disputed qualification's failure streak; no money moves."""
    disputed = _disputed_commit(claim)
    if disputed is None:
        return
    item = db.items.get(disputed.get("item_id"))
    unit = db.spec_units.get(item.get("spec_unit_id")) if item else None
    program = db.programs.get(unit.get("program_id")) if unit else None
    qualification = services.qualification_of_commit(disputed, program)
    if qualification is None:
        qualification = services.qualification_by_worker_language(
            claim.get("worker_id"), (program or {}).get("language_code")
        )
    if qualification is not None:
        qualification["gold_fail_streak"] = 0
        services.refresh_qualification_metrics(qualification)
        db.touch(qualification)


def _redispatch_disputed_piece(claim):
    item = db.items.get(claim.get("item_id"))
    if item is None:
        return
    item["consensus_status"] = "REWORK"
    item["item_status"] = "REWORK"
    item["status"] = "IN_PANEL"
    item["rework_cycles"] = int(item.get("rework_cycles", 0)) + 1
    item["rework_started_at"] = db.now()
    item["delivered_at"] = None
    services.refresh_item_derived(item)
    db.touch(item)

    unit = db.spec_units.get(item.get("spec_unit_id"))
    program = db.programs.get(unit.get("program_id")) if unit else None
    if unit is not None:
        unit_panel_size = int(unit.get("panel_size", services.DEFAULT_PANEL_SIZE) or services.DEFAULT_PANEL_SIZE)
        if program is not None:
            services.fresh_panel_member(
                item, program, unit, int(item["rework_cycles"]) + unit_panel_size
            )
        services.refresh_unit_metrics(unit)
        db.touch(unit)
    if program is not None:
        services.refresh_program_plan(program)
        db.touch(program)