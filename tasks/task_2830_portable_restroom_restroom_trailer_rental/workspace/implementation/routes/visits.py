"""ServiceVisit endpoints: planning, dispatch, completion, missed service and
the route re-run."""
from flask import Blueprint

from auth import ALL_ROLES, endpoint
import calculations as calc
import clock
import constants as C
from db import db, insert, ordered, serialize, touch
from errors import fail
from responses import created, ok
from routes.common import list_response, resolve
import services
import validation as V

bp = Blueprint("visits", __name__)


def _window_gates(schedule, scheduled_date, window_start_minute,
                  window_end_minute, exclude_visit_ids=()):
    site = services.site_of_schedule(schedule)
    if site is not None and not services.gate_window_contained(
            site, window_start_minute, window_end_minute):
        fail("ERR_ACCESS_WINDOW_VIOLATION")
    if services.route_window_conflict(
            schedule["route_id"], scheduled_date, window_start_minute,
            window_end_minute, exclude_visit_ids):
        fail("ERR_ROUTE_WINDOW_CONFLICT")


@bp.post("/service-visits")
@endpoint(["DispatchPlanner"])
def create_visit():
    body = V.body()
    schedule_id = V.str_field(body, "schedule_id", 1)
    visit_kind = V.enum_field(body, "visit_kind", C.CLIENT_VISIT_KINDS)
    scheduled_date = V.date_field(body, "scheduled_date")
    window_start_minute = V.int_field(body, "window_start_minute", 0, 1439)
    window_end_minute = V.int_field(body, "window_end_minute", 1, 1440)
    V.ordering(window_start_minute, window_end_minute,
               "window_start_minute", "window_end_minute", strict=True)

    schedule = resolve("service_schedules", schedule_id)
    site = services.site_of_schedule(schedule)

    if site is not None and site["site_posture"] == "BLOCKED":
        fail("ERR_SITE_POSTURE_BLOCKED")
    if site is not None and site["site_posture"] == "RESTRICTED":
        fail("ERR_SITE_POSTURE_RESTRICTED")
    _window_gates(schedule, scheduled_date, window_start_minute, window_end_minute)

    row = insert("service_visits", {
        "schedule_id": schedule["id"],
        "route_id": schedule["route_id"],
        "visit_kind": visit_kind,
        "scheduled_date": scheduled_date,
        "window_start_minute": window_start_minute,
        "window_end_minute": window_end_minute,
        "state": "PLANNED",
        "gallons_pumped": 0,
        "units_serviced": 0,
        "missed_reason": None,
        "rerun_of_visit_id": None,
    })
    return created(serialize(row))


@bp.get("/service-visits/<visit_id>")
@endpoint(ALL_ROLES)
def read_visit(visit_id):
    return ok(serialize(resolve("service_visits", visit_id)))


@bp.get("/service-visits")
@endpoint(ALL_ROLES)
def list_visits():
    limit, offset = V.pagination()
    schedule_id = V.q_str("schedule_id")
    route_id = V.q_str("route_id")
    rerun_of_visit_id = V.q_str("rerun_of_visit_id")
    state = V.q_enum("state", C.VISIT_STATES)
    scheduled_date = V.q_date("scheduled_date")
    visit_kind = V.q_enum("visit_kind", C.VISIT_KINDS)
    rows = ordered(db.service_visits.values())
    if schedule_id is not None:
        rows = [r for r in rows if r["schedule_id"] == schedule_id]
    if route_id is not None:
        rows = [r for r in rows if r["route_id"] == route_id]
    if rerun_of_visit_id is not None:
        rows = [r for r in rows if r["rerun_of_visit_id"] == rerun_of_visit_id]
    if state is not None:
        rows = [r for r in rows if r["state"] == state]
    if scheduled_date is not None:
        rows = [r for r in rows if r["scheduled_date"] == scheduled_date]
    if visit_kind is not None:
        rows = [r for r in rows if r["visit_kind"] == visit_kind]
    return list_response(rows, limit, offset)


@bp.post("/service-visits/<visit_id>/dispatch")
@endpoint(["DriverOperator"])
def dispatch_visit(visit_id):
    V.body()
    visit = resolve("service_visits", visit_id)
    schedule = db.service_schedules.get(visit["schedule_id"])
    route = db.routes.get(visit["route_id"])

    if visit["state"] != "PLANNED":
        fail("ERR_INVALID_STATE_TRANSITION")
    if schedule is None or schedule["state"] != "ACTIVE":
        fail("ERR_INVALID_STATE_TRANSITION",
             "The governing schedule is no longer ACTIVE.")
    if route is not None and route["status"] != "ACTIVE":
        fail("ERR_ROUTE_SUSPENDED")

    visit["state"] = "EN_ROUTE"
    touch(visit)
    if route is not None:
        current = route["last_run_date"]
        if current is None or visit["scheduled_date"] > current:
            route["last_run_date"] = visit["scheduled_date"]
            touch(route)
    return ok(serialize(visit))


@bp.post("/service-visits/<visit_id>/complete")
@endpoint(["DriverOperator"])
def complete_visit(visit_id):
    body = V.body()
    gallons_pumped = V.int_field(body, "gallons_pumped", 0, 6000)
    visit = resolve("service_visits", visit_id)
    schedule = db.service_schedules.get(visit["schedule_id"])

    if visit["state"] != "EN_ROUTE":
        fail("ERR_INVALID_STATE_TRANSITION")

    visit["state"] = "SERVICED"
    visit["gallons_pumped"] = gallons_pumped
    visit["units_serviced"] = 0 if schedule is None else schedule["units_on_route"]
    touch(visit)

    route = db.routes.get(visit["route_id"])
    if route is not None:
        services.recompute_route_realized(route)
    services.refresh_open_manifests(visit["route_id"], visit["scheduled_date"])
    return ok(serialize(visit))


@bp.post("/service-visits/<visit_id>/mark-missed")
@endpoint(["DispatchPlanner"])
def mark_visit_missed(visit_id):
    body = V.body()
    missed_reason = V.str_field(body, "missed_reason", 1)
    visit = resolve("service_visits", visit_id)
    schedule = db.service_schedules.get(visit["schedule_id"])

    if visit["state"] not in ("PLANNED", "EN_ROUTE"):
        fail("ERR_INVALID_STATE_TRANSITION")
    if visit["state"] == "PLANNED" and (schedule is None
                                       or schedule["state"] != "ACTIVE"):
        fail("ERR_INVALID_STATE_TRANSITION",
             "The governing schedule is no longer ACTIVE.")

    route = db.routes.get(visit["route_id"])
    # step 1: snapshot the PLANNED density before the visit's state is written
    density_snapshot_pct = 0 if route is None else route["density_planned_pct"]

    visit["state"] = "MISSED"
    visit["missed_reason"] = missed_reason
    touch(visit)

    contract = None
    if schedule is not None:
        contract = db.rental_contracts.get(schedule["contract_id"])
    if contract is not None:
        lines = services.active_quote_lines(contract["id"])
        amount_cents = calc.missed_service_credit_cents(density_snapshot_pct, lines)
        insert("charge_events", {
            "contract_id": contract["id"],
            "asset_unit_id": None,
            "source_visit_id": visit["id"],
            "charge_kind": "MISSED_SERVICE_CREDIT",
            "severity": None,
            "amount_cents": amount_cents,
            "state": "ASSESSED",
            "assessed_by_user_id": "SYSTEM",
            "resolved_by_user_id": None,
            "assessed_at": clock.now_iso(),
            "dispute_reason": None,
            "resolution_note": None,
        })
        services.recompute_contract_ledger(contract)
        services.flag_rebill_required(contract)
        account = db.rental_accounts.get(contract["account_id"])
        if account is not None:
            services.recompute_account(account)
    if route is not None:
        services.recompute_route_realized(route)
    return ok(serialize(visit))


@bp.post("/service-visits/<visit_id>/schedule-rerun")
@endpoint(["DispatchPlanner"])
def schedule_visit_rerun(visit_id):
    body = V.body()
    rerun_date = V.date_field(body, "rerun_date")
    window_start_minute = V.int_field(body, "window_start_minute", 0, 1439)
    window_end_minute = V.int_field(body, "window_end_minute", 1, 1440)
    V.ordering(window_start_minute, window_end_minute,
               "window_start_minute", "window_end_minute", strict=True)

    visit = resolve("service_visits", visit_id)
    schedule = db.service_schedules.get(visit["schedule_id"])

    if visit["state"] != "MISSED":
        fail("ERR_INVALID_STATE_TRANSITION")
    if schedule is None or schedule["state"] != "ACTIVE":
        fail("ERR_INVALID_STATE_TRANSITION",
             "The governing schedule is no longer ACTIVE.")
    _window_gates(schedule, rerun_date, window_start_minute, window_end_minute,
                  exclude_visit_ids=(visit["id"],))

    visit["state"] = "RERUN_SCHEDULED"
    touch(visit)
    rerun = insert("service_visits", {
        "schedule_id": visit["schedule_id"],
        "route_id": visit["route_id"],
        "visit_kind": "RERUN",
        "scheduled_date": rerun_date,
        "window_start_minute": window_start_minute,
        "window_end_minute": window_end_minute,
        "state": "PLANNED",
        "gallons_pumped": 0,
        "units_serviced": 0,
        "missed_reason": None,
        "rerun_of_visit_id": visit["id"],
    })
    return created(serialize(rerun))
