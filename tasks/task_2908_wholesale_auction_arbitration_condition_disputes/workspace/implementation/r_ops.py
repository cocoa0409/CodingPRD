"""The two internal test-driving capabilities: the logical clock and the sweep."""
from flask import Blueprint

import services as S
from authz import authenticate
from envelope import obj
from errors import fail
from store import store
from validators import json_body, req_dt

bp = Blueprint("ops", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authenticate(["AuctionAdmin"])
    body = json_body()
    target = req_dt(body, "to_iso8601")
    if target < store.now():
        fail("ERR_CLOCK_NOT_MONOTONIC")
    store.clock = target
    return obj({"current_utc": store.now_iso()})


@bp.route("/_ops/run-arbitration-sweep", methods=["POST"])
def run_sweep():
    authenticate(["AuctionAdmin"])
    return obj(S.run_sweep())
