"""Routes: logical clock and month advance."""

from datetime import datetime, timezone

from flask import Blueprint

import calc
from db import db, new_id, now_iso, get_clock, set_clock
from errors import invalid_request, lender_report_overdue
from middleware import month_of, parse_iso, require_roles
from response import body, ok_object

bp = Blueprint("clock", __name__)


def _format_clock(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


@bp.post("/mgmt/_clock/set_current_utc")
def set_current_utc():
    require_roles("PortfolioManager")
    data = body()
    to_iso8601 = data.get("to_iso8601")
    dt = parse_iso(to_iso8601)
    if dt is None:
        raise invalid_request("to_iso8601 must be a valid ISO8601 timestamp")
    set_clock(to_iso8601)
    return ok_object({"current_utc": _format_clock(get_clock())})


@bp.post("/mgmt/advance_month")
def advance_month():
    require_roles("PortfolioManager")
    clock = get_clock()
    # Advance the logical clock to the first day of the next month
    y, m = clock.year, clock.month
    if m == 12:
        y += 1
        m = 1
    else:
        m += 1
    new_clock = datetime(y, m, 1, tzinfo=timezone.utc)
    set_clock(new_clock.strftime("%Y-%m-%dT%H:%M:%SZ"))
    new_month = f"{y:04d}-{m:02d}"

    now = now_iso()

    # 1. Agreement expiry: ACTIVE agreements whose term_end_date has been reached
    for a in db.agreements.values():
        if a["status"] != "ACTIVE":
            continue
        end = parse_iso(a["term_end_date"])
        if end is not None and get_clock() >= end:
            a["status"] = "EXPIRED"
            a["updated_at"] = now
            a["version"] += 1
            prop = db.properties.get(a.get("property_id"))
            if prop is not None:
                prop["management_posture"] = "UNMANAGED"
                prop["updated_at"] = now
                prop["version"] += 1

    # 2. Annual NOI incentive when the closing period is December.
    #    The closing period is the month that just ended, i.e. the previous month.
    prev_m = m - 1 if m > 1 else 12
    prev_y = y if m > 1 else y - 1
    if prev_m == 12:
        for prop in db.properties.values():
            incentive = calc.annual_noi_incentive_cents(prop, prev_y)
            if incentive > 0:
                # The annual incentive is paid to the manager from property cash
                prop["cash_available_cents"] = prop.get("cash_available_cents", 0) - incentive
                prop["updated_at"] = now
                prop["version"] += 1
                e = {
                    "id": new_id(),
                    "property_id": prop["id"],
                    "resident_id": None,
                    "kind": "EXPENSE",
                    "amount_cents": incentive,
                    "accrual_month": f"{prev_y:04d}-12",
                    "collected_month": new_month,
                    "status": "POSTED",
                    "created_at": now,
                    "updated_at": now,
                    "version": 1,
                }
                db.ledger[e["id"]] = e

    # 3. LENDER report overdue check for disposition-listed properties
    overdue = []
    for prop in db.properties.values():
        if prop.get("disposition_listed_at") is None:
            continue
        for r in db.reports.values():
            if (
                r["property_id"] == prop["id"]
                and r["package_type"] == "LENDER"
                and r["status"] != "DELIVERED"
                and r["period_month"] < new_month
            ):
                overdue.append(r)
    if overdue:
        raise lender_report_overdue()

    return ok_object({"epoch_month": new_month})
