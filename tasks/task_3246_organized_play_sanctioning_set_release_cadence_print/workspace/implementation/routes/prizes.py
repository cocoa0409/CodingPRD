"""Prize allocations, distributions and reports.

  GET  /op/prize-allocations                    list allocations
  GET  /op/prize-allocations/{id}               retrieve one
  POST /op/prize-allocations/{id}/transition    REOPEN / INCREASE_REPRINT_RUN
  POST /op/prize-distributions                  propose a distribution
  GET  /op/prize-distributions                  list distributions
  GET  /op/prize-distributions/{id}             retrieve one
  POST /op/prize-distributions/{id}/transition  PASS / VOID
  GET  /op/prize-reports                        list reports
  GET  /op/prize-reports/{id}                   retrieve one
"""

from flask import Blueprint, request

import db as store
import computed as calcs
import models
import response as envelope
from errors import fail
from middleware import (
    ROLE_OPS_ADMIN, ROLE_STORE_ORGANIZER, ROLE_JUDGE,
    STRING, INTEGER,
    require_role, check_body, check_query_enums, require_action,
    is_ops_or_owner,
)
from services import cascade
from utils import clock, DISTRIBUTION_LOCK_DATE

bp = Blueprint("prizes", __name__)

ALLOCATION_STATUSES = ("OPEN", "CLOSED", "RELEASED")
DISTRIBUTION_STATUSES = ("PROPOSED", "PASSED", "VOIDED")
REPORT_STATUSES = ("FILED", "OVERDUE")
ALLOCATION_ACTIONS = ("REOPEN", "INCREASE_REPRINT_RUN")
DISTRIBUTION_ACTIONS = ("PASS", "VOID")


def _sync(allocation):
    """Re-derive the pool's live balance; the counters themselves move explicitly."""
    allocation["remaining_tp"] = calcs.prize_pool_remaining(allocation)
    store.touch(allocation)


# --------------------------------------------------------------------------
# Prize allocations
# --------------------------------------------------------------------------

@bp.route("/op/prize-allocations", methods=["GET"])
def list_allocations():
    require_role(request, (ROLE_OPS_ADMIN, ROLE_STORE_ORGANIZER, ROLE_JUDGE))
    check_query_enums(request, {"status": ALLOCATION_STATUSES})
    rows = list(store.db.prize_allocations.values())
    for name in ("store_id", "event_application_id", "status"):
        value = request.args.get(name)
        if value:
            rows = [r for r in rows if r[name] == value]
    rows.sort(key=lambda r: r["created_at"])
    limit, offset = envelope.paginate(rows, request.args)[1:3]
    return envelope.list_response([models.prize_allocation_view(r) for r in rows],
                                  limit, offset)


@bp.route("/op/prize-allocations/<allocation_id>", methods=["GET"])
def get_allocation(allocation_id):
    require_role(request, (ROLE_OPS_ADMIN, ROLE_STORE_ORGANIZER, ROLE_JUDGE))
    row = store.db.prize_allocations.get(allocation_id)
    if row is None:
        fail("ERR_NOT_FOUND", "PrizeAllocation %s does not exist." % allocation_id)
    return envelope.object_response(models.prize_allocation_view(row))


@bp.route("/op/prize-allocations/<allocation_id>/transition", methods=["POST"])
def transition_allocation(allocation_id):
    require_role(request, (ROLE_OPS_ADMIN,))
    body = check_body(
        request,
        required=("action",),
        optional=("additional_tp",),
        types={"action": STRING, "additional_tp": INTEGER},
    )
    action = require_action(body, ALLOCATION_ACTIONS)

    row = store.db.prize_allocations.get(allocation_id)
    if row is None:
        fail("ERR_NOT_FOUND", "PrizeAllocation %s does not exist." % allocation_id)

    if action == "REOPEN":
        _reopen(row)
    else:
        _increase(row, body)
    return envelope.object_response(models.prize_allocation_view(row))


def _reopen(row):
    """The one re-open cycle available on a pool.

    Available only from CLOSED, only once the cited set release has been
    retired, and only while the parent application's reporting column is DUE or
    SUBMITTED. Because it neither draws nor restores, the re-derivation can lift
    remaining_tp above any figure previously observed while the conserved
    invariant is left exactly as it was.
    """
    if row["status"] != "CLOSED":
        fail("ERR_INVALID_STATE", "Only a CLOSED allocation may be re-opened.")

    application = store.db.event_applications.get(row["event_application_id"])
    if application is None:
        fail("ERR_NOT_FOUND", "The pool's originating application no longer exists.")
    release = store.db.set_releases.get(application["set_release_id"])
    if release is None:
        fail("ERR_NOT_FOUND", "The pool's cited set release no longer exists.")

    if release["status"] != "RETIRED":
        fail("ERR_INVALID_STATE",
             "The cited set release must be RETIRED before the pool is re-opened.")
    if application["prizing_report_status"] not in ("DUE", "SUBMITTED"):
        fail("ERR_INVALID_STATE",
             "The parent application's reporting window must be DUE or SUBMITTED.")

    store.touch(row, status="OPEN")
    _sync(row)


def _increase(row, body):
    """Enlarge a pool directly: the addition lands on base_tp."""
    additional = body.get("additional_tp")
    if additional is None:
        fail("ERR_INVALID_REQUEST",
             "additional_tp is required for INCREASE_REPRINT_RUN.")
    if additional < 0:
        fail("ERR_INVALID_REQUEST", "additional_tp must not be negative.")
    row["base_tp"] = row["base_tp"] + additional
    store.touch(row)
    _sync(row)


# --------------------------------------------------------------------------
# Prize distributions
# --------------------------------------------------------------------------

@bp.route("/op/prize-distributions", methods=["POST"])
def create_distribution():
    require_role(request, (ROLE_STORE_ORGANIZER,))
    body = check_body(
        request,
        required=("prize_allocation_id", "recipient_ref", "quantity"),
        types={"prize_allocation_id": STRING, "recipient_ref": STRING, "quantity": INTEGER},
    )
    allocation = store.db.prize_allocations.get(body["prize_allocation_id"])
    if allocation is None:
        fail("ERR_NOT_FOUND",
             "PrizeAllocation %s does not exist." % body["prize_allocation_id"])
    if not is_ops_or_owner(request, allocation["store_id"]):
        fail("ERR_UNAUTHORIZED", "This pool belongs to another store.")

    row = store.insert_prize_distribution(
        body["prize_allocation_id"], body["recipient_ref"], body["quantity"])
    # No draw-down until PASSED.
    return envelope.object_response(models.prize_distribution_view(row), status=201)


@bp.route("/op/prize-distributions", methods=["GET"])
def list_distributions():
    require_role(request, (ROLE_OPS_ADMIN, ROLE_STORE_ORGANIZER, ROLE_JUDGE))
    check_query_enums(request, {"status": DISTRIBUTION_STATUSES})
    rows = list(store.db.prize_distributions.values())
    for name in ("prize_allocation_id", "status"):
        value = request.args.get(name)
        if value:
            rows = [r for r in rows if r[name] == value]
    rows.sort(key=lambda r: r["created_at"])
    limit, offset = envelope.paginate(rows, request.args)[1:3]
    return envelope.list_response([models.prize_distribution_view(r) for r in rows],
                                  limit, offset)


@bp.route("/op/prize-distributions/<distribution_id>", methods=["GET"])
def get_distribution(distribution_id):
    require_role(request, (ROLE_OPS_ADMIN, ROLE_STORE_ORGANIZER, ROLE_JUDGE))
    row = store.db.prize_distributions.get(distribution_id)
    if row is None:
        fail("ERR_NOT_FOUND", "PrizeDistribution %s does not exist." % distribution_id)
    return envelope.object_response(models.prize_distribution_view(row))


@bp.route("/op/prize-distributions/<distribution_id>/transition", methods=["POST"])
def transition_distribution(distribution_id):
    require_role(request, (ROLE_OPS_ADMIN, ROLE_STORE_ORGANIZER))
    body = check_body(request, required=("action",), types={"action": STRING})
    action = require_action(body, DISTRIBUTION_ACTIONS)

    row = store.db.prize_distributions.get(distribution_id)
    if row is None:
        fail("ERR_NOT_FOUND", "PrizeDistribution %s does not exist." % distribution_id)

    allocation = store.db.prize_allocations.get(row["prize_allocation_id"])
    if allocation is None:
        fail("ERR_NOT_FOUND", "The distribution's pool no longer exists.")

    if action == "PASS":
        _pass(row, allocation)
    else:
        _void(row, allocation)

    return envelope.object_response(models.prize_distribution_view(row))


def _pass(row, allocation):
    """Passing draws the quantity out of the pool.

    Permitted only while the pool is OPEN and only when the draw does not
    exceed the pool's current remaining_tp; a draw exactly equal to the whole
    remaining balance is legal and leaves the balance at zero. The draw rung
    (ERR_INSUFFICIENT_POOL, 402) is a business-fiscal rung and fires after the
    state rungs, so the OPEN check comes first.
    """
    if row["status"] != "PROPOSED":
        fail("ERR_INVALID_STATE", "Only a PROPOSED distribution may be passed.")
    if allocation["status"] != "OPEN":
        fail("ERR_INVALID_STATE", "The parent pool is not OPEN.")

    remaining = calcs.prize_pool_remaining(allocation)
    if row["quantity"] > remaining:
        fail("ERR_INSUFFICIENT_POOL",
             "The requested draw exceeds the pool's remaining tournament points.")

    # total_drawn_tp is a materialized counter and is INCREMENTED, not
    # re-derived: a distribution that is later voided leaves the drawn total
    # standing so that a void-then-pass cycle returns the balance to precisely
    # the figure it held before the void.
    allocation["total_drawn_tp"] = allocation["total_drawn_tp"] + row["quantity"]
    store.touch(row, status="PASSED")
    _sync(allocation)


def _void(row, allocation):
    """Voiding returns the quantity to the pool.

    Available only while the logical clock is still earlier than
    2026-10-15T00:00:00Z, because distributions lock at the reprint policy
    review date, and only if the distribution has not already been offset once.
    A second void would double-count the movement, which is why it is rejected.
    """
    if row["status"] != "PASSED":
        fail("ERR_INVALID_STATE",
             "Only a PASSED distribution may be voided; an already-voided "
             "distribution has already performed its compensating restore.")
    if clock.now() >= DISTRIBUTION_LOCK_DATE:
        fail("ERR_INVALID_STATE",
             "Distributions are locked at 2026-10-15T00:00:00Z and may no longer be voided.")

    # The compensating restore is an increment: it offsets this distribution's
    # draw exactly once. The materialized drawn total is deliberately left
    # alone, so remaining_tp returns to the pre-pass figure.
    allocation["total_restored_tp"] = allocation["total_restored_tp"] + row["quantity"]
    store.touch(row, status="VOIDED")
    _sync(allocation)


# --------------------------------------------------------------------------
# Prize reports
# --------------------------------------------------------------------------

@bp.route("/op/prize-reports", methods=["GET"])
def list_reports():
    require_role(request, (ROLE_OPS_ADMIN, ROLE_STORE_ORGANIZER, ROLE_JUDGE))
    check_query_enums(request, {"status": REPORT_STATUSES})
    rows = list(store.db.prize_reports.values())
    for name in ("event_application_id", "prize_allocation_id", "status"):
        value = request.args.get(name)
        if value:
            rows = [r for r in rows if r[name] == value]
    rows.sort(key=lambda r: r["created_at"])
    limit, offset = envelope.paginate(rows, request.args)[1:3]
    return envelope.list_response([models.prize_report_view(r) for r in rows],
                                  limit, offset)


@bp.route("/op/prize-reports/<report_id>", methods=["GET"])
def get_report(report_id):
    require_role(request, (ROLE_OPS_ADMIN, ROLE_STORE_ORGANIZER, ROLE_JUDGE))
    row = store.db.prize_reports.get(report_id)
    if row is None:
        fail("ERR_NOT_FOUND", "PrizeReport %s does not exist." % report_id)
    return envelope.object_response(models.prize_report_view(row))