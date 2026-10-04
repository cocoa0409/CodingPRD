"""Set releases: announcement, listing and retirement.

  POST /op/set-releases                   announce a set release
  GET  /op/set-releases                   list set releases
  POST /op/set-releases/{id}/transition   RETIRE
"""

from flask import Blueprint, request

import db as store
import models
import response as envelope
from errors import fail
from middleware import (
    ROLE_OPS_ADMIN, ROLE_STORE_ORGANIZER, ROLE_JUDGE, ROLE_DISTRIBUTOR,
    STRING, DATETIME,
    require_role, check_body, check_query_enums, require_action,
)
from services import cascade
from utils import parse_dt

bp = Blueprint("set_releases", __name__)

RELEASE_STATUSES = ("ANNOUNCED", "PRERELEASE", "RELEASED", "RETIRED")
RELEASE_ACTIONS = ("RETIRE",)


# --------------------------------------------------------------------------
# POST /op/set-releases
# --------------------------------------------------------------------------

@bp.route("/op/set-releases", methods=["POST"])
def create_set_release():
    require_role(request, (ROLE_OPS_ADMIN,))
    body = check_body(
        request,
        required=("set_code", "prerelease_start_date", "prerelease_end_date", "street_date"),
        types={
            "set_code": STRING,
            "prerelease_start_date": DATETIME,
            "prerelease_end_date": DATETIME,
            "street_date": DATETIME,
        },
    )

    prerelease_start = parse_dt(body["prerelease_start_date"])
    prerelease_end = parse_dt(body["prerelease_end_date"])
    street_date = parse_dt(body["street_date"])
    if prerelease_start is None or prerelease_end is None or street_date is None:
        fail("ERR_INVALID_REQUEST", "Prerelease and street dates must be ISO 8601 datetimes.")

    # The prerelease window sits strictly before the street date (§2.5, §3.7).
    if street_date < prerelease_end:
        fail("ERR_STREET_DATE_BEFORE_PRERELEASE",
             "street_date must fall at or after prerelease_end_date.")

    # The set code is globally unique across SetRelease rows (§1.4 priority 22).
    for existing in store.db.set_releases.values():
        if existing["set_code"] == body["set_code"]:
            fail("ERR_DUPLICATE_SET_CODE",
                 "set_code '%s' already exists." % body["set_code"])

    row = store.insert_set_release(
        body["set_code"], prerelease_start, prerelease_end, street_date)
    return envelope.object_response(models.set_release_view(row), status=201)


# --------------------------------------------------------------------------
# GET /op/set-releases
# --------------------------------------------------------------------------

@bp.route("/op/set-releases", methods=["GET"])
def list_set_releases():
    require_role(request, (ROLE_OPS_ADMIN, ROLE_STORE_ORGANIZER, ROLE_JUDGE,
                           ROLE_DISTRIBUTOR))
    check_query_enums(request, {"status": RELEASE_STATUSES})
    rows = list(store.db.set_releases.values())
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: r["created_at"])
    limit, offset = envelope.paginate(rows, request.args)[1:3]
    return envelope.list_response(
        [models.set_release_view(r) for r in rows], limit, offset)


# --------------------------------------------------------------------------
# POST /op/set-releases/{id}/transition
# --------------------------------------------------------------------------

@bp.route("/op/set-releases/<release_id>/transition", methods=["POST"])
def transition_set_release(release_id):
    require_role(request, (ROLE_OPS_ADMIN,))
    body = check_body(request, required=("action",), types={"action": STRING})
    require_action(body, RELEASE_ACTIONS)

    row = store.db.set_releases.get(release_id)
    if row is None:
        fail("ERR_NOT_FOUND", "SetRelease %s does not exist." % release_id)

    if row["status"] != "RELEASED":
        fail("ERR_INVALID_STATE", "Only a RELEASED set release may be retired.")

    store.touch(row, status="RETIRED")
    cascade.retire_set_release(row)
    return envelope.object_response(models.set_release_view(row))