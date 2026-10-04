"""Reprint plans and the accessibility ceiling.

  POST /op/reprint-plans                   file a plan and compute its verdict
  GET  /op/reprint-plans                   list plans
  GET  /op/reprint-plans/{id}              retrieve one
  POST /op/reprint-plans/{id}/transition   APPROVE / PUBLISH
"""

from flask import Blueprint, request

import db as store
import computed as calcs
import models
import response as envelope
from errors import fail
from middleware import (
    ROLE_OPS_ADMIN,
    STRING, INTEGER,
    require_role, check_body, check_query_enums, require_action,
)
from utils import clock, REPRINT_PUBLISH_CUTOFF

bp = Blueprint("reprints", __name__)

PLAN_STATUSES = ("DRAFT", "APPROVED", "REJECTED", "PUBLISHED")
PLAN_ACTIONS = ("APPROVE", "PUBLISH")


@bp.route("/op/reprint-plans", methods=["POST"])
def create_plan():
    """The verdict is computed at filing time and is never client-supplied.

    secondary_market_index is adjusted upward by floor(64 * idx / 137) and
    compared against the ceiling of 42; first_print_index is recorded for the
    market-context audit but does not enter the verdict.
    """
    require_role(request, (ROLE_OPS_ADMIN,))
    body = check_body(
        request,
        required=("card_name", "set_release_id", "format_id",
                  "secondary_market_index", "first_print_index"),
        types={
            "card_name": STRING,
            "set_release_id": STRING,
            "format_id": STRING,
            "secondary_market_index": INTEGER,
            "first_print_index": INTEGER,
        },
    )

    release = store.db.set_releases.get(body["set_release_id"])
    if release is None:
        fail("ERR_NOT_FOUND", "SetRelease %s does not exist." % body["set_release_id"])
    format_row = store.db.formats.get(body["format_id"])
    if format_row is None:
        fail("ERR_NOT_FOUND", "Format %s does not exist." % body["format_id"])

    row = store.insert_reprint_plan(
        body["card_name"], body["set_release_id"], body["format_id"],
        body["secondary_market_index"], body["first_print_index"])
    row["verdict"] = calcs.reprint_policy_verdict(body["secondary_market_index"])
    return envelope.object_response(models.reprint_plan_view(row), status=201)


@bp.route("/op/reprint-plans", methods=["GET"])
def list_plans():
    require_role(request, (ROLE_OPS_ADMIN,))
    check_query_enums(request, {"status": PLAN_STATUSES})
    rows = list(store.db.reprint_plans.values())
    for name in ("format_id", "set_release_id", "status"):
        value = request.args.get(name)
        if value:
            rows = [r for r in rows if r[name] == value]
    rows.sort(key=lambda r: r["created_at"])
    limit, offset = envelope.paginate(rows, request.args)[1:3]
    return envelope.list_response([models.reprint_plan_view(r) for r in rows],
                                  limit, offset)


@bp.route("/op/reprint-plans/<plan_id>", methods=["GET"])
def get_plan(plan_id):
    require_role(request, (ROLE_OPS_ADMIN,))
    row = store.db.reprint_plans.get(plan_id)
    if row is None:
        fail("ERR_NOT_FOUND", "ReprintPlan %s does not exist." % plan_id)
    return envelope.object_response(models.reprint_plan_view(row))


@bp.route("/op/reprint-plans/<plan_id>/transition", methods=["POST"])
def transition_plan(plan_id):
    require_role(request, (ROLE_OPS_ADMIN,))
    body = check_body(request, required=("action",), types={"action": STRING})
    action = require_action(body, PLAN_ACTIONS)

    row = store.db.reprint_plans.get(plan_id)
    if row is None:
        fail("ERR_NOT_FOUND", "ReprintPlan %s does not exist." % plan_id)

    if action == "APPROVE":
        _approve(row)
    else:
        _publish(row)
    return envelope.object_response(models.reprint_plan_view(row))


def _approve(row):
    """One gate is commercial and one is temporal.

    A plan whose verdict is a denial is rejected before the review-window gate
    is consulted, which is the order the state rung precedes the business rung
    in any case: approval from the wrong starting state fails as
    ERR_INVALID_STATE rather than being evaluated against the ceiling.
    """
    if row["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", "Only a DRAFT plan may be approved.")
    if row["verdict"] != "REPRINT_ALLOWED":
        fail("ERR_REPRINT_MARKET_FLOOR",
             "The plan's verdict is REPRINT_DENIED; the market floor blocks approval.")

    release = store.db.set_releases.get(row["set_release_id"])
    if release is not None and release["status"] == "RETIRED":
        fail("ERR_REPRINT_REVIEW_CLOSED",
             "The plan's cited set release is already RETIRED; the review window is closed.")

    store.touch(row, status="APPROVED")


def _publish(row):
    """Publication carries its own hard calendar gate."""
    if row["status"] != "APPROVED":
        fail("ERR_INVALID_STATE", "Only an APPROVED plan may be published.")

    release = store.db.set_releases.get(row["set_release_id"])
    if release is not None and release["status"] == "RETIRED":
        fail("ERR_REPRINT_REVIEW_CLOSED",
             "The plan's cited set release is already RETIRED; the review window is closed.")

    if clock.now() >= REPRINT_PUBLISH_CUTOFF:
        fail("ERR_INVALID_STATE",
             "A reprint plan may not be published once the clock reaches "
             "2026-12-01T00:00:00Z.")

    # PUBLISH records the plan under its SetRelease.
    store.touch(row, status="PUBLISHED")