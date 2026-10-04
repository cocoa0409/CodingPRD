"""Code redemptions: minting cards and disbursing physical prize grants.

  POST /op/code-redemptions                   mint an unredeemed card
  POST /op/code-redemptions/{id}/transition   DISBURSE
  GET  /op/code-redemptions                   list redemptions
  GET  /op/code-redemptions/{id}              retrieve one
"""

from flask import Blueprint, request

import db as store
import computed as calcs
import models
import response as envelope
from errors import fail
from middleware import (
    ROLE_OPS_ADMIN, ROLE_STORE_ORGANIZER, ROLE_JUDGE,
    STRING,
    require_role, check_body, check_query_enums, require_action,
)

bp = Blueprint("code_redemptions", __name__)

CODE_KINDS = ("DIGITAL", "PHYSICAL")
REDEMPTION_STATUSES = ("AVAILABLE", "REDEEMED", "DECLINED")
REDEMPTION_ACTIONS = ("DISBURSE",)


@bp.route("/op/code-redemptions", methods=["POST"])
def create_code():
    """Mint a code card pre-bound to a sanctioned event application."""
    require_role(request, (ROLE_OPS_ADMIN,))
    body = check_body(
        request,
        required=("redemption_code", "code_kind", "event_application_id"),
        types={"redemption_code": STRING, "code_kind": STRING,
               "event_application_id": STRING},
        enums={"code_kind": CODE_KINDS},
    )

    application = store.db.event_applications.get(body["event_application_id"])
    if application is None:
        fail("ERR_NOT_FOUND",
             "EventApplication %s does not exist." % body["event_application_id"])

    # The code must be globally unique across all minted cards.
    for existing in store.db.code_redemptions.values():
        if existing["redemption_code"] == body["redemption_code"]:
            fail("ERR_DUPLICATE_REDEMPTION_CODE",
                 "redemption_code '%s' is already minted." % body["redemption_code"])

    row = store.insert_code_redemption(
        body["code_kind"], body["redemption_code"], body["event_application_id"])
    return envelope.object_response(models.code_redemption_view(row), status=201)


@bp.route("/op/code-redemptions", methods=["GET"])
def list_codes():
    require_role(request, (ROLE_OPS_ADMIN, ROLE_STORE_ORGANIZER, ROLE_JUDGE))
    check_query_enums(request, {"status": REDEMPTION_STATUSES})
    rows = list(store.db.code_redemptions.values())
    for name in ("event_application_id", "status"):
        value = request.args.get(name)
        if value:
            rows = [r for r in rows if r[name] == value]
    rows.sort(key=lambda r: r["created_at"])
    limit, offset = envelope.paginate(rows, request.args)[1:3]
    return envelope.list_response([models.code_redemption_view(r) for r in rows],
                                  limit, offset)


@bp.route("/op/code-redemptions/<redemption_id>", methods=["GET"])
def get_code(redemption_id):
    require_role(request, (ROLE_OPS_ADMIN, ROLE_STORE_ORGANIZER, ROLE_JUDGE))
    row = store.db.code_redemptions.get(redemption_id)
    if row is None:
        fail("ERR_NOT_FOUND", "CodeRedemption %s does not exist." % redemption_id)
    return envelope.object_response(models.code_redemption_view(row))


@bp.route("/op/code-redemptions/<redemption_id>/transition", methods=["POST"])
def transition_code(redemption_id):
    """Disbursement moves a floored point value on both sides in one transaction.

    The grant's value is floor(PACK_COUNT_BY_TIER[tier] * 27 / 4), floored once
    for this redemption and used identically for total_drawn_tp and
    total_restored_tp, so the conserved invariant over the pool is bit-for-bit
    what it was before the disbursement.
    """
    require_role(request, (ROLE_OPS_ADMIN,))
    body = check_body(request, required=("action",), types={"action": STRING})
    require_action(body, REDEMPTION_ACTIONS)

    row = store.db.code_redemptions.get(redemption_id)
    if row is None:
        fail("ERR_NOT_FOUND", "CodeRedemption %s does not exist." % redemption_id)

    if row["status"] != "REDEEMED":
        fail("ERR_INVALID_STATE",
             "Only a REDEEMED card's physical grant may be disbursed.")
    if row["physical_grant_status"] != "RESERVED":
        fail("ERR_INVALID_STATE",
             "Only a RESERVED physical grant may be disbursed.")

    application = store.db.event_applications.get(row["event_application_id"])
    if application is None:
        fail("ERR_NOT_FOUND", "The card's event application no longer exists.")
    if application["status"] != "COMPLETED":
        fail("ERR_INVALID_STATE",
             "The cited event application must be COMPLETED before disbursement.")

    allocation_id = application.get("prize_allocation_id")
    if not allocation_id:
        fail("ERR_INVALID_STATE", "The cited event application has no prize pool.")
    allocation = store.db.prize_allocations.get(allocation_id)
    if allocation is None:
        fail("ERR_NOT_FOUND", "The application's prize pool no longer exists.")

    # Record the pool onto the card, then move the grant value on both sides.
    row["prize_allocation_id"] = allocation_id
    row["physical_grant_status"] = "DISBURSED"
    store.touch(row)

    grant_value = calcs.physical_grant_value(allocation["tier"])
    allocation["total_drawn_tp"] = allocation["total_drawn_tp"] + grant_value
    allocation["total_restored_tp"] = allocation["total_restored_tp"] + grant_value
    allocation["remaining_tp"] = calcs.prize_pool_remaining(allocation)
    store.touch(allocation)

    return envelope.object_response(models.code_redemption_view(row))