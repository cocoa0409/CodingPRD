"""Ops routes: logical clock, epoch checkpoint, circulation driver."""
from flask import Blueprint
from db import stores
from middleware import require_roles
from response import success
from timeutil import CLOCK, fmt_ts, parse_iso
from engine import (
    new_id, now, require_body, req_field, serialize, select_license, write_event,
    sync_patron_counters, fund_covering, recompute_fund, discounted_cpc_charge,
    touch_common,
)
from lending import run_epoch
from errors import err, ERR_INVALID_REQUEST, ERR_REFERENCE_NOT_FOUND, ERR_NO_LICENSE_AVAILABLE

bp = Blueprint("ops", __name__)


@bp.post("/lending/_clock/set_current_utc")
def set_clock():
    body = require_body()
    raw = req_field(body, "to_iso8601", (str,))
    try:
        dt = parse_iso(raw)
    except ValueError:
        raise err(ERR_INVALID_REQUEST, "to_iso8601 must be ISO-8601 datetime")
    require_roles({"ConsortiumAdmin"})
    CLOCK.set(dt)
    return success({"current_utc": fmt_ts(CLOCK.now())})


@bp.post("/lending/_ops/run_epoch")
def epoch():
    require_roles({"ConsortiumAdmin"})
    res = run_epoch()
    return success(res)


@bp.post("/lending/_events/drive_circulation")
def drive_circulation():
    body = require_body()
    title_id = req_field(body, "title_id", (str,))
    by_library = req_field(body, "by_library", (list,))
    require_roles({"ConsortiumAdmin"})
    title = stores["titles"].get(title_id)
    if title is None:
        raise err(ERR_REFERENCE_NOT_FOUND, "title_id does not resolve")
    for entry in by_library:
        if not isinstance(entry, dict):
            raise err(ERR_INVALID_REQUEST, "by_library entries must be objects")
        req_field(entry, "library_id", (str,))
        req_field(entry, "patron_id", (str,))
        req_field(entry, "checkouts", (int,))
    cycles = 0
    events_written = 0
    for entry in by_library:
        library = stores["libraries"].get(entry["library_id"])
        patron = stores["patrons"].get(entry["patron_id"])
        if library is None or patron is None:
            raise err(ERR_REFERENCE_NOT_FOUND, "by_library reference does not resolve")
        for _ in range(entry["checkouts"]):
            lic = select_license(title, library["id"])
            if lic is None:
                raise err(ERR_NO_LICENSE_AVAILABLE, "no eligible license available")
            charge = 0
            if lic["model"] == "COST_PER_CIRC":
                charge = discounted_cpc_charge(title)
                if lic["balance_cents"] >= charge:
                    lic["balance_cents"] -= charge
                    fund = fund_covering(library["id"], now())
                    if fund is not None:
                        recompute_fund(fund)
            if lic["model"] == "OCOU":
                lic["copies_on_loan"] += 1
            elif lic["model"] == "METERED_CIRC":
                lic["circs_consumed"] += 1
            loan = {
                "id": new_id(),
                "license_id": lic["id"],
                "patron_id": patron["id"],
                "hold_id": None,
                "is_skip_the_line": False,
                "checkout_at": fmt_ts(now()),
                "due_at": fmt_ts(now()),
                "returned_at": fmt_ts(now()),
                "renewals_used": 0,
                "circ_price_charged_cents": charge,
                "status": "RETURNED",
                "_library_id": library["id"],
                "_title_id": title["id"],
            }
            touch_common(loan, created=True)
            loan["_seq"] = len(stores["loans"])
            loan["_due_dt"] = now()
            loan["_checkout_dt"] = now()
            stores["loans"][loan["id"]] = loan
            write_event(library["id"], title["id"], patron["id"], loan["id"], None,
                        lic["id"], "CHECKOUT", charge)
            write_event(library["id"], title["id"], patron["id"], loan["id"], None,
                        lic["id"], "RETURN")
            events_written += 2
            cycles += 1
            if lic["model"] == "OCOU":
                lic["copies_on_loan"] = max(0, lic["copies_on_loan"] - 1)
            sync_patron_counters(patron["id"])
    return success({"cycles_completed": cycles, "events_written": events_written})
