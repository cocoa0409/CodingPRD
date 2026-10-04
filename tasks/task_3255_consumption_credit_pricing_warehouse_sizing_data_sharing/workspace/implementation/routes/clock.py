"""Test-driving logical clock (the one endpoint exempt from auth checks)."""
from decimal import Decimal

from flask import Blueprint

from db import db
from errors import err
from response import success
from services import engine
from util import parse_iso, set_clock, now

from routes.common import body, required

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    data = body()
    raw = required(data, "to_iso8601")
    try:
        instant = parse_iso(raw, "to_iso8601")
    except ValueError:
        raise err("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO 8601 timestamp.")
    set_clock(instant)
    expire_contracts()
    engine.complete_drains()
    resweep_monitors()
    return success({})


def expire_contracts():
    """Every ACTIVE contract whose term_end is at or before now moves to EXPIRED."""
    for contract in db.contracts:
        if contract["status"] != "ACTIVE":
            continue
        if contract["term_end"] <= now():
            rolled = engine.rollover_at_expiry(contract)
            contract["rolled_over_credits"] = rolled
            contract["status"] = "EXPIRED"
            engine.recompute_contract(contract)
            engine.touch(contract)
            engine.post_ledger(contract["account_id"], "ROLLOVER", "CapacityContract",
                               contract["id"], amount_credits=rolled,
                               amount_usd=Decimal("0"))


def resweep_monitors():
    """Every monitor recomputes its window against the new clock."""
    for monitor in db.monitors:
        engine.evaluate_monitor(monitor)
    for account in db.accounts:
        engine.derive_posture(account)
