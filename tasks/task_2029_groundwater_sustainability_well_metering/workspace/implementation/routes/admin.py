"""Admin / test-driving endpoints: close-water-year and the logical clock."""
from flask import Blueprint

from db import store, touch
from errors import err
from middleware import require_roles, body
from response import ok
from services import (CARRYOVER_CAP_FRACTION, effective_allocation,
                      sweep_expired_transfers)
from util import D0, num_out, round3, is_int, parse_iso_datetime

bp = Blueprint("admin", __name__)


@bp.post("/admin/close-water-year")
def close_water_year():
    require_roles("WaterMaster")
    b = body()
    wy = b.get("water_year")
    if not is_int(wy):
        raise err("ERR_INVALID_REQUEST", "water_year must be an integer")
    unresolved = any(r["water_year"] == wy and r["status"] in ("SUBMITTED", "DISPUTED")
                     for r in store.reports.values())
    if unresolved:
        raise err("ERR_CLOSE_YEAR_UNRESOLVED_REPORTS",
                  "SUBMITTED or DISPUTED reports exist for the closing water year")
    rolled = 0
    total = D0
    for acct in store.accounts.values():
        if acct["status"] in ("ACTIVE", "SUSPENDED") and acct["current_water_year"] == wy:
            eff = effective_allocation(acct)
            unused = eff - acct["extracted_af_ytd"] - acct["transfer_out_af_ytd"]
            if unused < 0:
                unused = D0
            unused = round3(unused)
            carry = round3(min(unused, CARRYOVER_CAP_FRACTION * acct["base_allocation_af"]))
            acct["credit_balance_af"] = round3(acct["credit_balance_af"] + carry)
            acct["extracted_af_ytd"] = D0
            acct["pending_extraction_af"] = D0
            acct["transfer_out_af_ytd"] = D0
            acct["current_water_year"] += 1
            acct["version"] += 1
            touch(acct)
            rolled += 1
            total += carry
    store.closed_years.add(wy)
    return ok({
        "closed_water_year": wy,
        "accounts_rolled": rolled,
        "total_carryover_af": num_out(round3(total)),
    })


@bp.post("/_clock/set_current_utc")
def set_clock():
    require_roles("WaterMaster")
    b = body()
    raw = b.get("to_iso8601")
    dt = parse_iso_datetime(raw)
    if dt is None:
        raise err("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO 8601 timestamp")
    store.clock = dt
    sweep_expired_transfers(dt)
    return ok({"current_utc": raw})
