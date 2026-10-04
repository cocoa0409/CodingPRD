"""Epoch share grants and the test-driving logical clock."""

import re

from flask import Blueprint

import auth
import clock
import envelope
import serializers
import store
from errors import (
    ERR_INVALID_REQUEST,
    ERR_MEMBER_NOT_FOUND,
    ERR_STALE_VERSION,
    fail,
)
from services import grants as grant_svc
from services import ledger

bp = Blueprint("misc", __name__)

EPOCH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


@bp.route("/network/share-ledger/grants", methods=["POST"])
def create_grant():
    auth.require_roles("NetworkAdmin")
    data = auth.json_body()

    member_id = auth.req_str(data, "member_id")
    epoch = auth.req_str(data, "epoch")
    if not EPOCH_RE.match(epoch):
        fail(ERR_INVALID_REQUEST, "epoch must be a YYYY-MM label")
    activity_basis = auth.opt_raw(data, "activity_basis")
    expected_version = auth.req_int(data, "expected_member_version")

    member = store.members.get(member_id)
    if member is None:
        fail(ERR_MEMBER_NOT_FOUND, "no member food bank matches id %s" % member_id)
    if expected_version != member["version"]:
        fail(ERR_STALE_VERSION,
             "expected_member_version does not match the member's current version")

    forward_looking = activity_basis == "FORWARD_LOOKING"
    grants = grant_svc.compute_epoch_grants(clock.prior_epoch(epoch), forward_looking)
    amount = grants.get(member["id"], 0)

    member["last_grant_epoch"] = epoch
    entry = ledger.append_entry(member, "GRANT", amount, reference_id=None, epoch=epoch)
    return envelope.ok_object(serializers.ledger_entry(entry), 201)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    auth.require_roles("NetworkAdmin")
    data = auth.json_body()
    current = clock.parse_iso(auth.req_str(data, "current_utc"))
    clock.set_now(current)
    return envelope.ok_empty()
