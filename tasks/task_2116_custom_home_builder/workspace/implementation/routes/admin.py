"""Logical clock and PlatformAdmin reference-data registration."""
from decimal import Decimal

from flask import Blueprint

from store import db, base_row, set_clock, now
from util import (
    authorize, parse_body, ok, fmt_iso,
    req_str, req_enum, req_int, req_money, opt_bool, req_dt,
)
from services.constants import STAFF_FUNCTIONS, TRADES

bp = Blueprint("admin", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authorize(["PlatformAdmin"])
    body = parse_body()
    instant = req_dt(body, "to_iso8601")
    set_clock(instant)
    return ok({"current_utc": fmt_iso(now())}, 200)


@bp.post("/clients")
def create_client():
    authorize(["PlatformAdmin"])
    body = parse_body()
    full_name = req_str(body, "full_name")
    email = req_str(body, "email")
    portal_enabled = opt_bool(body, "portal_enabled", True)

    row = base_row()
    row.update({
        "full_name": full_name,
        "email": email,
        "portal_enabled": portal_enabled,
    })
    db.clients[row["id"]] = row
    return ok(row, 201)


@bp.post("/lenders")
def create_lender():
    authorize(["PlatformAdmin"])
    body = parse_body()
    name = req_str(body, "name")
    retainage_pct = req_money(body, "retainage_pct", minimum=Decimal("0"),
                              maximum=Decimal("0.20"), max_dp=4)
    max_cumulative_draw_pct = req_money(body, "max_cumulative_draw_pct",
                                        minimum=Decimal("0"), exclusive_min=True,
                                        maximum=Decimal("1"), max_dp=4)
    review_window_days = req_int(body, "review_window_days", minimum=1)

    row = base_row()
    row.update({
        "name": name,
        "retainage_pct": retainage_pct,
        "max_cumulative_draw_pct": max_cumulative_draw_pct,
        "review_window_days": review_window_days,
    })
    db.lenders[row["id"]] = row
    return ok(row, 201)


@bp.post("/staff-members")
def create_staff_member():
    authorize(["PlatformAdmin"])
    body = parse_body()
    full_name = req_str(body, "full_name")
    staff_function = req_enum(body, "staff_function", STAFF_FUNCTIONS)

    row = base_row()
    row.update({"full_name": full_name, "staff_function": staff_function})
    db.staff_members[row["id"]] = row
    return ok(row, 201)


@bp.post("/subcontractors")
def create_subcontractor():
    authorize(["PlatformAdmin"])
    body = parse_body()
    company_name = req_str(body, "company_name")
    trade = req_enum(body, "trade", TRADES)
    lead_time_days = req_int(body, "lead_time_days", minimum=0)
    crew_capacity = req_int(body, "crew_capacity", minimum=1)
    waiver_required = opt_bool(body, "waiver_required", True)

    row = base_row()
    row.update({
        "company_name": company_name,
        "trade": trade,
        "lead_time_days": lead_time_days,
        "crew_capacity": crew_capacity,
        "waiver_required": waiver_required,
    })
    db.subcontractors[row["id"]] = row
    return ok(row, 201)
