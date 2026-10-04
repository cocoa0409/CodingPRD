"""Formats: registration, listing, epoch rotation and the banned/restricted lists.

  POST /op/formats                   register a constructed format
  GET  /op/formats                   list formats
  POST /op/formats/{id}/transition   ROTATE / BAN_CARD / RESTRICT_CARD
"""

from flask import Blueprint, request

import db as store
import models
import response as envelope
from errors import fail
from middleware import (
    ROLE_OPS_ADMIN, ROLE_STORE_ORGANIZER, ROLE_JUDGE,
    STRING,
    require_role, check_body, require_action,
)
from services import cascade
from utils import clock, ROTATION_DATE

bp = Blueprint("formats", __name__)

ROTATION_POLICIES = ("FIXED", "ROLLING")
LIST_KINDS = ("BANNED", "RESTRICTED")
FORMAT_ACTIONS = ("ROTATE", "BAN_CARD", "RESTRICT_CARD")


@bp.route("/op/formats", methods=["POST"])
def create_format():
    require_role(request, (ROLE_OPS_ADMIN,))
    body = check_body(
        request,
        required=("name", "format_code", "rotation_policy"),
        types={"name": STRING, "format_code": STRING, "rotation_policy": STRING},
        enums={"rotation_policy": ROTATION_POLICIES},
    )

    for existing in store.db.formats.values():
        if existing["name"] == body["name"]:
            fail("ERR_INVALID_REQUEST", "Format name already exists.")
        if existing["format_code"] == body["format_code"]:
            fail("ERR_INVALID_REQUEST", "format_code already exists.")

    row = store.insert_format(body["name"], body["format_code"], body["rotation_policy"])
    return envelope.object_response(models.format_view(row), status=201)


@bp.route("/op/formats", methods=["GET"])
def list_formats():
    require_role(request, (ROLE_OPS_ADMIN, ROLE_STORE_ORGANIZER, ROLE_JUDGE))
    rows = list(store.db.formats.values())
    rows.sort(key=lambda r: r["created_at"])
    limit, offset = envelope.paginate(rows, request.args)[1:3]
    return envelope.list_response(rows, limit, offset)


@bp.route("/op/formats/<format_id>/transition", methods=["POST"])
def transition_format(format_id):
    require_role(request, (ROLE_OPS_ADMIN,))
    body = check_body(
        request,
        required=("action",),
        optional=("card_ref", "list_kind"),
        types={"action": STRING, "card_ref": STRING, "list_kind": STRING},
        enums={"list_kind": LIST_KINDS},
    )
    action = require_action(body, FORMAT_ACTIONS)

    row = store.db.formats.get(format_id)
    if row is None:
        fail("ERR_NOT_FOUND", "Format %s does not exist." % format_id)

    if action == "ROTATE":
        _rotate(row)
    else:
        _update_list(row, action, body)

    return envelope.object_response(models.format_view(row))


def _rotate(row):
    """Rotation is gated by the calendar and by having a card pool to rotate."""
    if clock.now() < ROTATION_DATE:
        fail("ERR_INVALID_STATE",
             "A format may not rotate before 2026-10-15T00:00:00Z.")
    has_pool = any(r["status"] in ("RELEASED", "RETIRED")
                   for r in store.db.set_releases.values())
    if not has_pool:
        fail("ERR_INVALID_STATE",
             "No set release has reached RELEASED, so there is no card pool to rotate.")
    # cascade.rotate_format bumps current_epoch, rejects the format's approved
    # reprint plans and closes out unreported completed events.
    cascade.rotate_format(row)


def _update_list(row, action, body):
    """A list update is a self-loop on the epoch axis (§3.8).

    The named card_ref is appended to banned_card_refs or restricted_card_refs
    according to list_kind, and current_epoch is left exactly where it was.
    What the update does do is deny every approved event application citing the
    format and close each of their still-open prize pools.
    """
    card_ref = body.get("card_ref")
    if card_ref is None or card_ref == "":
        fail("ERR_INVALID_REQUEST", "card_ref is required for %s." % action)

    list_kind = body.get("list_kind")
    if list_kind is None:
        list_kind = "BANNED" if action == "BAN_CARD" else "RESTRICTED"

    target = row["banned_card_refs"] if list_kind == "BANNED" else row["restricted_card_refs"]
    if card_ref not in target:
        target.append(card_ref)
    store.touch(row)

    cascade.close_denied_application_pools(row["id"])