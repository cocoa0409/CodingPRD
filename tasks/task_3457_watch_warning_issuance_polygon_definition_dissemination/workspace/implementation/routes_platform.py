"""Platform test-driving capabilities, mounted OUTSIDE the /alerts prefix
(PRD §2.4): the logical clock and dissemination settlement.

One clock advance runs three transition families in a fixed order (PRD §3.7):
  1. expire ISSUED products whose expires_at has been reached;
  2. expire REQUESTED coordination requests past deadline_at, reverting their
     products to DRAFT where the rules say so;
  3. dispatch QUEUED dissemination records.
All of it commits atomically within the clock-setting request.
"""
from flask import Blueprint

from auth import authenticate, require_role
from constants import MAX_RETRIES, SETTLE_OUTCOMES
from db import STORE, now, set_now
from errors import api_error
from routes_dissemination import get_record_or_404
from serialize import serialize
from util import envelope, fmt_dt, get_body, parse_dt, touch

bp = Blueprint("platform", __name__)  # no url_prefix: these live outside /alerts

ADMIN = ["PlatformAdmin"]


def _expire_products(stamp):
    for product in sorted(STORE["products"].values(), key=lambda p: p["_seq"]):
        if product["status"] == "ISSUED" and stamp >= product["expires_at"]:
            product["status"] = "EXPIRED"
            product["expired_at"] = product["expires_at"]
            touch(product)
            for record in STORE["records"].values():
                if record["product_id"] == product["id"] and record["status"] == "QUEUED":
                    record["status"] = "WITHDRAWN"
                    touch(record)


def _expire_coordinations(stamp):
    for coord in sorted(STORE["coordinations"].values(), key=lambda c: c["_seq"]):
        if coord["status"] == "REQUESTED" and stamp >= coord["deadline_at"]:
            coord["status"] = "EXPIRED"
            touch(coord)
    # revert affected products: still pending, no REQUESTED remain in the
    # current round, and the round's requests are not all ACKNOWLEDGED
    for product in sorted(STORE["products"].values(), key=lambda p: p["_seq"]):
        if product["status"] != "PENDING_COORDINATION":
            continue
        current = [
            c for c in STORE["coordinations"].values()
            if c["product_id"] == product["id"] and c.get("_round") == product["_coord_round"]
        ]
        if not current:
            continue
        if any(c["status"] == "REQUESTED" for c in current):
            continue
        if all(c["status"] == "ACKNOWLEDGED" for c in current):
            continue
        product["status"] = "DRAFT"
        touch(product)
        for sibling in current:
            if sibling["status"] == "REQUESTED":
                sibling["status"] = "CANCELLED"
                touch(sibling)


def _dispatch_records(stamp):
    for record in sorted(STORE["records"].values(), key=lambda r: r["_seq"]):
        if record["status"] != "QUEUED":
            continue
        product = STORE["products"].get(record["product_id"])
        if product is not None and product["status"] == "ISSUED":
            record["status"] = "SENT"
            record["sent_at"] = stamp
            touch(record)
            channel = STORE["channels"].get(record["channel_id"])
            if channel is not None and not channel["requires_confirmation"]:
                record["status"] = "CONFIRMED"
                record["confirmed_at"] = stamp
                touch(record)
        else:
            record["status"] = "WITHDRAWN"
            touch(record)


@bp.post("/_clock/set_current_utc")
def set_clock():
    role, _uid, _fc = authenticate()
    require_role(role, ADMIN)
    body = get_body()
    target = parse_dt(body.get("to_iso8601"))
    if target is None:
        raise api_error("ERR_INVALID_REQUEST", "to_iso8601 is required and must be ISO 8601.")
    set_now(target)
    stamp = now()
    _expire_products(stamp)
    _expire_coordinations(stamp)
    _dispatch_records(stamp)
    return envelope({"current_utc": fmt_dt(stamp)}, "object", 200)


@bp.post("/_dissemination/settle")
def settle_record():
    role, _uid, _fc = authenticate()
    require_role(role, ADMIN)
    body = get_body()
    record_id = body.get("record_id")
    if not isinstance(record_id, str) or not record_id:
        raise api_error("ERR_INVALID_REQUEST", "record_id is required.")
    outcome = body.get("outcome")
    if outcome not in SETTLE_OUTCOMES:
        raise api_error("ERR_INVALID_REQUEST", "outcome must be one of %s" % SETTLE_OUTCOMES)
    record = get_record_or_404(record_id)
    if record["status"] != "SENT":
        raise api_error("ERR_RECORD_NOT_SETTLABLE", "Only a SENT record is settleable.")
    stamp = now()
    if outcome == "CONFIRMED":
        record["status"] = "CONFIRMED"
        record["confirmed_at"] = stamp
    else:  # FAILED -> retry cycle
        record["retry_count"] += 1
        if record["retry_count"] < MAX_RETRIES:
            record["status"] = "QUEUED"
            record["queued_at"] = stamp
        else:
            record["status"] = "DEAD"
    touch(record)
    return envelope(serialize(record), "object", 200)
