"""Center endpoints: create, get, run_ops checkpoint, cost report."""

from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint

from helpers import (
    authn,
    base_entity,
    err,
    get_center,
    now,
    paginate,
    req_int,
    req_str,
    body,
    require_role,
    serialize,
    success_list,
    success_object,
)
from services import run_ops
from storage import STORE

bp = Blueprint("centers", __name__)

READ_ROLES = ("PlatformAdmin", "CenterManager", "Volunteer", "Guest")


@bp.route("/centers", methods=["POST"])
def create_center():
    _, role = authn()
    require_role(role, ("PlatformAdmin",))
    b = body()
    name = req_str(b, "name")
    airport_code = req_str(b, "airport_code")
    occupancy_cap = req_int(b, "occupancy_cap", minimum=1)
    required = req_int(b, "required_daily_confirmed_assignments", minimum=1)

    center = base_entity()
    center.update({
        "name": name,
        "airport_code": airport_code,
        "occupancy_cap": occupancy_cap,
        "required_daily_confirmed_assignments": required,
        "posture": "CLOSED",
        "current_occupancy": 0,
        "coverage_ratio": 0,
        "active_agreement_id": None,
        "expense_ledger": [],
        "ops_run_count": 0,
    })
    STORE.centers[center["id"]] = center
    return success_object(serialize(center), status=201)


@bp.route("/centers/<cid>", methods=["GET"])
def get_center_route(cid):
    _, role = authn()
    require_role(role, READ_ROLES)
    center = get_center(cid)
    return success_object(serialize(center))


@bp.route("/centers/<cid>/run_ops", methods=["POST"])
def run_ops_route(cid):
    _, role = authn()
    require_role(role, ("CenterManager",))
    center = get_center(cid)
    run_ops(center)
    return success_object(serialize(center))


@bp.route("/centers/<cid>/cost-report", methods=["GET"])
def cost_report(cid):
    _, role = authn()
    require_role(role, READ_ROLES)
    center = get_center(cid)

    ref_now = now()
    year, month = ref_now.year, ref_now.month

    def in_month(dt):
        return dt.year == year and dt.month == month

    month_expenses = sum(
        e["amount_cents"] for e in center["expense_ledger"] if in_month(e["posted_at"])
    )
    month_visits = sum(
        1
        for ci in STORE.checkins.values()
        if ci["center_id"] == cid and in_month(ci["checked_in_at"])
    )
    committed_budget = sum(
        ev["event_budget_cents"]
        for ev in STORE.events.values()
        if ev["center_id"] == cid
        and ev["status"] in ("CONFIRMED", "EXECUTED")
        and in_month(ev["start_at"])
    )

    if month_visits == 0:
        actual = None
        loaded = None
    else:
        actual = int(
            (Decimal(month_expenses) / Decimal(month_visits)).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
        )
        loaded = int(
            (Decimal(month_expenses + committed_budget) / Decimal(month_visits)).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
        )

    donation_total = 0
    partner_match_total = 0
    for lot in STORE.lots.values():
        if lot["center_id"] != cid:
            continue
        if lot["status"] not in ("AVAILABLE", "DEPLETED"):
            continue
        donation_total += lot["declared_value_cents"]
        partner_match_total += lot["partner_match_cents"]

    report = {
        "center_id": cid,
        "posture": center["posture"],
        "current_occupancy": center["current_occupancy"],
        "coverage_ratio": center["coverage_ratio"],
        "month_expenses_cents": month_expenses,
        "month_visits": month_visits,
        "cost_per_visit_actual_cents": actual,
        "cost_per_visit_loaded_cents": loaded,
        "donation_value_total_cents": donation_total,
        "partner_match_total_cents": partner_match_total,
    }
    return success_object(report)
