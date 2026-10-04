"""Worker, qualification, incident and settlement routes (PRD sections 3.9, 3.10)."""

from flask import Blueprint

import auth
import db
import services
from envelope import list_ok, ok, paginate
from errors import (
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_UNAUTHORIZED,
    ERR_PROGRAM_NOT_FOUND,
    ERR_QUALIFICATION_NOT_FOUND,
    ERR_QUALIFICATION_SCORE_BELOW_TIER,
    ERR_UNIT_CODE_DUPLICATE,
    ERR_WORKER_NOT_FOUND,
    ERR_WORKER_RESTRICTED,
    fail,
)
from helpers import (
    json_body,
    opt_enum,
    opt_int,
    opt_str,
    ordered_by_creation,
    pagination_params,
    query_enum,
    query_str,
    require_enum,
    require_enum_ci,
    require_int,
    require_str,
)

bp = Blueprint("workers", __name__)

ADMIN = auth.ROLE_ADMIN
REVIEWER = auth.ROLE_REVIEWER
WORKER = auth.ROLE_WORKER


def _enforce_worker_ownership(principal, worker):
    """A Worker principal may only read and act on their own WorkerIdentity."""
    if principal.role == WORKER and principal.user_id != worker["id"]:
        fail(ERR_WORKER_NOT_FOUND)


# --------------------------------------------------------------------------
# POST /api/workers -- the one endpoint open to an unauthenticated caller
# --------------------------------------------------------------------------
@bp.post("/api/workers")
def register_worker():
    uid, role = auth.raw_identity()
    if uid and role:
        # A caller that does supply both headers must be Anonymous or PlatformAdmin.
        if role not in (auth.ROLE_ANONYMOUS, ADMIN):
            fail(ERR_UNAUTHORIZED)

    body = json_body()

    handle = require_str(body, "handle")
    payout_currency = opt_enum(body, "payout_currency", services.CURRENCIES, "USD")
    settlement_min_cents = opt_int(
        body, "settlement_min_cents", services.DEFAULT_SETTLEMENT_MIN_CENTS
    )
    display_name = opt_str(body, "display_name", None)

    for existing in db.workers.values():
        if existing.get("handle") == handle:
            fail(ERR_UNIT_CODE_DUPLICATE)

    record = {
        "handle": handle,
        "display_name": display_name,
        "payout_currency": payout_currency,
        "settlement_min_cents": settlement_min_cents,
        "lifetime_base_cents": 0,
        "settled_cents": 0,
        "lifetime_earned_cents": 0,
        "worker_receivable_cents": 0,
        "total_accepted_payout_cents": 0,
        "restricted": False,
    }
    db.seal(record)
    db.workers[record["id"]] = record
    services.refresh_worker_metrics(record)
    return ok(services.worker_view(record), status=201)


@bp.get("/api/workers/<worker_id>")
def read_worker(worker_id):
    principal = auth.enforce_headers()
    auth.enforce_role(principal, (ADMIN, REVIEWER, WORKER))
    worker = db.workers.get(worker_id)
    if worker is None:
        fail(ERR_WORKER_NOT_FOUND)
    _enforce_worker_ownership(principal, worker)
    variant = query_str("earnings_variant")
    if variant is not None:
        upper = variant.upper()
        if upper not in ("ACCEPTED", "PROVISIONAL", "BASE"):
            fail(ERR_INVALID_REQUEST, "Unknown earnings_variant.")
        variant = upper
    return ok(services.worker_view(worker, variant))


@bp.post("/api/workers/<worker_id>/settlement-requests")
def settlement_request(worker_id):
    principal = auth.enforce_headers()
    auth.enforce_role(principal, (WORKER, ADMIN))
    worker = db.workers.get(worker_id)
    if worker is None:
        fail(ERR_WORKER_NOT_FOUND)
    _enforce_worker_ownership(principal, worker)

    body = json_body()
    amount_cents = require_int(body, "amount_cents")
    currency = opt_str(body, "currency", worker.get("payout_currency"))

    services.settle(worker, amount_cents, currency)
    return ok(services.worker_view(worker))


# --------------------------------------------------------------------------
# Qualifications
# --------------------------------------------------------------------------
@bp.get("/api/workers/<worker_id>/qualifications")
def list_qualifications(worker_id):
    principal = auth.enforce_headers()
    auth.enforce_role(principal, (ADMIN, REVIEWER))
    worker = db.workers.get(worker_id)
    if worker is None:
        fail(ERR_WORKER_NOT_FOUND)
    language = query_str("language_code")
    rows = db.qualifications_of_worker(worker_id)
    if language:
        rows = [q for q in rows if q.get("language_code") == language]
    rows = ordered_by_creation(rows)
    limit, offset = pagination_params()
    page, pagination = paginate(rows, limit, offset)
    return list_ok([services.qualification_view(q) for q in page], pagination=pagination)


@bp.post("/api/workers/<worker_id>/qualifications")
def qualification_action(worker_id):
    principal = auth.enforce_headers()
    auth.enforce_role(principal, (ADMIN, REVIEWER))
    worker = db.workers.get(worker_id)
    if worker is None:
        fail(ERR_WORKER_NOT_FOUND)

    body = json_body()
    language_code = require_enum(body, "language_code", services.LANGUAGES)
    tier = require_enum(body, "tier", services.TIERS)
    action = require_enum_ci(body, "qualification_action", ("ENROLL", "VERIFY", "RESET"))
    training_required = opt_int(
        body, "training_required_count", services.DEFAULT_TRAINING_REQUIRED_COUNT
    )

    if action == "ENROLL":
        return ok(_enroll(worker, language_code, tier, training_required))
    if action == "VERIFY":
        return ok(_verify(worker, language_code, tier))
    return ok(_reset(worker, language_code))


def _enroll(worker, language_code, tier, training_required):
    if services.qualification_by_worker_language(worker["id"], language_code) is not None:
        fail(ERR_UNIT_CODE_DUPLICATE)
    record = {
        "worker_id": worker["id"],
        "language_code": language_code,
        "tier": tier,
        "qualification_score": services.qualification_score(worker.get("handle"), language_code),
        "tier_min_score": services.TIER_MIN_SCORE[tier],
        "tier_multiplier": services.TIER_MULT[tier],
        "gold_audits_dispatched": 0,
        "gold_denominator_count": 0,
        "accepted_gold_count": 0,
        "provisional_gold_count": 0,
        "accuracy_pct": 0,
        "provisional_accuracy_pct": 0,
        "training_passed_count": 0,
        "training_required_count": training_required,
        "gold_fail_streak": 0,
        "restricted_accessible": False,
        "last_rehabilitated_epoch": None,
        "status": "IN_TRAINING",
    }
    db.seal(record)
    db.qualifications[record["id"]] = record
    return services.qualification_view(record)


def _verify(worker, language_code, tier):
    qual = services.qualification_by_worker_language(worker["id"], language_code)
    if qual is None:
        fail(ERR_QUALIFICATION_NOT_FOUND)

    # Rank 5 -- state admissibility.
    if qual.get("status") not in ("IN_TRAINING", "PROBATION"):
        fail(ERR_INVALID_STATE)
    if qual.get("status") == "PROBATION":
        if qual.get("last_rehabilitated_epoch") == db.current_epoch_index():
            fail(ERR_INVALID_STATE)

    # Rank 6 -- the worker may not be verified while an incident is open.
    services.refresh_worker_restricted(worker)
    if worker.get("restricted"):
        fail(ERR_WORKER_RESTRICTED)

    # Rank 9 -- the training gate, then the tier score gate on its own.
    if int(qual.get("training_passed_count", 0)) < int(qual.get("training_required_count", 0)):
        fail(ERR_INVALID_STATE)
    # The declared tier is what the score gate reads (PRD §2.6 pairs the
    # qualification_action with language_code and tier, and the gate is "at or
    # above `tier_min_score`"), so verifying at a new tier adopts it.
    declared_min = services.TIER_MIN_SCORE.get(tier, qual.get("tier_min_score", 0))
    if int(qual.get("qualification_score", 0)) < int(declared_min):
        fail(ERR_QUALIFICATION_SCORE_BELOW_TIER)

    if tier != qual.get("tier"):
        qual["tier"] = tier
        qual["tier_min_score"] = services.TIER_MIN_SCORE[tier]
        qual["tier_multiplier"] = services.TIER_MULT[tier]
    qual["status"] = "QUALIFIED"
    qual["gold_fail_streak"] = 0
    qual["last_rehabilitated_epoch"] = db.current_epoch_index()
    services.refresh_qualification_metrics(qual)
    db.touch(qual)
    return services.qualification_view(qual)


def _reset(worker, language_code):
    qual = services.qualification_by_worker_language(worker["id"], language_code)
    if qual is None:
        fail(ERR_QUALIFICATION_NOT_FOUND)

    open_incident = any(
        inc.get("status") == "OPEN" for inc in db.incidents_of_worker(worker["id"])
    )
    status = qual.get("status")

    if status == "PROBATION" and open_incident:
        qual["status"] = "SUSPENDED"
        qual["gold_fail_streak"] = 0
        services.refresh_qualification_metrics(qual)
        db.touch(qual)
        services.withdraw_worker_dispatched_commits(worker["id"])
        return services.qualification_view(qual)

    if status == "SUSPENDED" and int(qual.get("training_passed_count", 0)) < int(
        qual.get("training_required_count", 0)
    ):
        qual["status"] = "IN_TRAINING"
        qual["training_passed_count"] = 0
        services.refresh_qualification_metrics(qual)
        db.touch(qual)
        return services.qualification_view(qual)

    fail(ERR_INVALID_STATE)


# --------------------------------------------------------------------------
# Incidents
# --------------------------------------------------------------------------
@bp.get("/api/workers/<worker_id>/incidents")
def list_incidents(worker_id):
    principal = auth.enforce_headers()
    auth.enforce_role(principal, (ADMIN, REVIEWER))
    worker = db.workers.get(worker_id)
    if worker is None:
        fail(ERR_WORKER_NOT_FOUND)
    status = query_enum("status", services.INCIDENT_STATUSES)
    rows = db.incidents_of_worker(worker_id)
    if status:
        rows = [i for i in rows if i.get("status") == status]
    rows = ordered_by_creation(rows)
    limit, offset = pagination_params()
    page, pagination = paginate(rows, limit, offset)
    return list_ok([services.incident_view(i) for i in page], pagination=pagination)


@bp.post("/api/workers/<worker_id>/incidents")
def incident_action(worker_id):
    principal = auth.enforce_headers()
    auth.enforce_role(principal, (ADMIN,))
    worker = db.workers.get(worker_id)
    if worker is None:
        fail(ERR_WORKER_NOT_FOUND)

    body = json_body()
    program_code = require_str(body, "program_code")
    category = require_enum(body, "category", services.INCIDENT_CATEGORIES)
    severity = require_enum(body, "severity", services.INCIDENT_SEVERITIES[1:])
    description_text = require_str(body, "description_text")
    action = require_enum_ci(body, "incident_action", ("REPORT", "RESOLVE"))

    program = None
    for candidate in db.programs.values():
        if candidate.get("program_code") == program_code:
            program = candidate
            break
    if program is None:
        fail(ERR_PROGRAM_NOT_FOUND)

    if action == "REPORT":
        record = {
            "program_id": program["id"],
            "worker_id": worker["id"],
            "category": category,
            "severity": severity,
            "description_text": description_text,
            "status": "OPEN",
        }
        db.seal(record)
        db.incidents[record["id"]] = record
    else:
        # PRD §2.5: "the reporting action opens the incident ... while the
        # resolving action closes it and recomputes both flags again", so the
        # RESOLVE action closes the worker's outstanding incident on this
        # engagement rather than filing a second row.
        outstanding = [
            inc
            for inc in db.incidents_of_worker(worker["id"])
            if inc.get("program_id") == program["id"] and inc.get("status") == "OPEN"
        ]
        if not outstanding:
            fail(ERR_INVALID_STATE)
        record = outstanding[-1]
        record["status"] = "RESOLVED"
        db.touch(record)

    services.refresh_incident_flags(program)
    db.touch(program)
    services.refresh_worker_restricted(worker)
    db.touch(worker)
    return ok(services.incident_view(record), status=201)