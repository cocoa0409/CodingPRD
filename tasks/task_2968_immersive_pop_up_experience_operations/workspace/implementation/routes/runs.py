"""ExperienceRun — capacity bottleneck, two parallel standings, demand,
extension and the four-hop closure cascade (PRD §3.3 and §3.8)."""

from datetime import timedelta

from flask import Blueprint, request

from db import db, new_row, now_iso, public, today, touch
from errors import ApiError
from middleware import EP, GSA, LM, LR, SO, VOM, caller_id, roles
from response import list_response, object_response
from services import calc, derive
from services.validate import Body

bp = Blueprint("runs", __name__)

RUN_OPEN_STATUSES = ("OPEN", "EXTENDED")
CLOSURE_DECISIONS = ("START_CLOSING", "CLOSE")
SLOT_LIVE_STATUSES = ("OPEN", "SOLD_OUT", "HELD_FOR_BUYOUT", "SUSPENDED")
RELEASED_SLOT_STATUSES = ("OPEN", "SOLD_OUT", "SUSPENDED", "CLOSED_OUT")
COUNTED_ORDER_STATUSES = ("CONFIRMED", "CHECKED_IN", "NO_SHOW",
                          "REFUND_DUE", "REFUNDED")
REFUNDED_ORDER_STATUSES = ("REFUND_DUE", "REFUNDED")
STAFF_RELEASABLE = ("CANDIDATE", "TRAINING", "CLEARED", "SUSPENDED")


def _demand(run_row):
    slots = [s for s in derive.slots_of(run_row)
             if s["status"] in RELEASED_SLOT_STATUSES]
    released_total = sum(s["released_capacity"] for s in slots)
    sold_total = sum(s["sold_capacity"] for s in slots)
    counted = [o for o in derive.orders_of_run(run_row)
               if o["status"] in COUNTED_ORDER_STATUSES]
    refunded = [o for o in counted if o["status"] in REFUNDED_ORDER_STATUSES]
    utilisation, refund_share, index = calc.demand_figures(
        released_total, sold_total, len(counted), len(refunded))
    return {
        "run_id": run_row["id"],
        "demand_index": float(index),
        "utilisation_pct": float(utilisation),
        "refund_share_pct": float(refund_share),
        "released_total": released_total,
        "sold_total": sold_total,
        "counted_order_count": len(counted),
        "refunded_order_count": len(refunded),
        "_index": index,
    }


@bp.post("/experience-runs")
@roles(EP)
def create_run():
    body = Body(require_body=True)
    venue_id = body.reference("venue_id")
    agreement_id = body.reference("license_agreement_id")
    kit_id = body.reference("build_kit_id")
    run_name = body.string("run_name", min_len=1, max_len=120)
    open_date, open_raw = body.date_field("scheduled_open_date")
    close_date, close_raw = body.date_field("scheduled_close_date")
    base_price = body.integer("base_ticket_price_cents", minimum=1, maximum=100000)
    slot_minutes = body.integer("timed_slot_minutes", minimum=15, maximum=120)
    max_group = body.integer("max_group_size", required=False, default=12,
                             minimum=1, maximum=60)

    # rung 5 — body foreign keys, left to right
    venue_row = derive.venue(venue_id)
    agreement = derive.agreement(agreement_id)
    kit_row = derive.kit(kit_id)

    # rung 9 — cross-entity state
    if venue_row["status"] not in ("PERMIT_ISSUED", "LEASE_ACTIVE"):
        raise ApiError("ERR_VENUE_INVALID_STATE")
    if agreement["status"] != "ACTIVE":
        raise ApiError("ERR_AGREEMENT_NOT_ACTIVE")
    if kit_row["status"] != "READY":
        raise ApiError("ERR_KIT_NOT_READY")

    # rung 11 — interval and calendar bounds
    if close_date <= open_date:
        raise ApiError("ERR_INVALID_WINDOW")
    if open_date < venue_row["_lease_start"] or close_date > venue_row["_lease_end"]:
        raise ApiError("ERR_SLOT_OUTSIDE_RUN_WINDOW")

    # rung 16 — eligibility
    if venue_row["city_code"] not in agreement["territory_city_codes"]:
        raise ApiError("ERR_CITY_NOT_IN_TERRITORY")
    if (calc.dec(kit_row["condition_score"]) < calc.KIT_CONDITION_RUN_MIN
            or kit_row["localization_status"] != "LOCALIZED"):
        raise ApiError("ERR_KIT_CONDITION_BELOW_THRESHOLD")

    row = new_row()
    row.update({
        "venue_id": venue_row["id"],
        "license_agreement_id": agreement["id"],
        "build_kit_id": kit_row["id"],
        "run_name": run_name,
        "created_by_user_id": caller_id(),
        "scheduled_open_date": open_raw,
        "scheduled_close_date": close_raw,
        "base_ticket_price_cents": base_price,
        "timed_slot_minutes": slot_minutes,
        "max_group_size": max_group,
        "effective_capacity": 0,
        "effective_capacity_cap": 0,
        "royalty_statement_count": 0,
        "extension_days_granted": 0,
        "demand_index": 0.00,
        "demand_index_at_extension": None,
        "opened_at": None,
        "closing_started_at": None,
        "closed_at": None,
        "suspended_at": None,
        "suspending_inspection_id": None,
        "run_status": "PLANNED",
        "clearance_status": "UNCLEARED",
        "_open_date": open_date,
        "_close_date": close_date,
    })
    db.runs[row["id"]] = row

    # the kit leaves the shelf, taking its own version increment
    kit_row["status"] = "DEPLOYED"
    touch(kit_row)
    return object_response(public(row), 201)


@bp.get("/experience-runs/<run_id>")
@roles(EP, VOM, LM, LR, SO, GSA)
def read_run(run_id):
    return object_response(public(derive.run(run_id)))


@bp.get("/experience-runs")
@roles(EP, VOM, LM, LR, SO)
def list_runs():
    rows = list(db.runs.values())
    for field in ("venue_id", "license_agreement_id", "build_kit_id",
                  "suspending_inspection_id", "run_status", "clearance_status"):
        value = request.args.get(field)
        if value:
            rows = [r for r in rows if r[field] == value]
    return list_response(rows)


@bp.get("/experience-runs/<run_id>/demand-index")
@roles(EP, VOM, LM)
def read_demand(run_id):
    figures = _demand(derive.run(run_id))
    figures.pop("_index")
    return object_response(figures)


@bp.post("/experience-runs/<run_id>/open")
@roles(EP)
def open_run(run_id):
    run_row = derive.run(run_id)
    venue_row = derive.venue(run_row["venue_id"])

    # rung 8 — own state
    if run_row["run_status"] != "PLANNED":
        raise ApiError("ERR_RUN_INVALID_STATE")
    # rung 9 — cross-entity state
    if venue_row["status"] != "LEASE_ACTIVE":
        raise ApiError("ERR_VENUE_LEASE_NOT_ACTIVE")
    if run_row["clearance_status"] != "CLEARED":
        raise ApiError("ERR_RUN_NOT_CLEARED")
    # rung 15 — a roomless run has no capacity figure at all
    capacity = derive.refresh_effective_capacity(run_row)
    if capacity <= 0:
        raise ApiError("ERR_RUN_INVALID_STATE")
    # a run with no released window cannot admit anybody
    if not any(s["status"] == "OPEN" for s in derive.slots_of(run_row)):
        raise ApiError("ERR_RUN_INVALID_STATE")

    run_row["run_status"] = "OPEN"
    run_row["opened_at"] = now_iso()
    touch(run_row)
    return object_response(public(run_row))


@bp.post("/experience-runs/<run_id>/extensions")
@roles(EP)
def extend_run(run_id):
    run_row = derive.run(run_id)
    body = Body(require_body=True)
    days = body.integer("requested_extension_days", minimum=1)
    body.string("memo", required=False, default=None, min_len=1, max_len=500)

    # rung 8 — both dimensions of the run's own parallel state
    if run_row["run_status"] not in RUN_OPEN_STATUSES:
        raise ApiError("ERR_RUN_INVALID_STATE")
    if run_row["clearance_status"] != "CLEARED":
        raise ApiError("ERR_RUN_INVALID_STATE")
    # rung 10 — SoD-3: the creator may not grant the extension
    if caller_id() == run_row["created_by_user_id"]:
        raise ApiError("ERR_SOD_EXTENSION_SAME_USER")

    venue_row = derive.venue(run_row["venue_id"])
    # rung 17 — demand floor first, lease budget second
    figures = _demand(run_row)
    if figures["_index"] < calc.EXTENSION_DEMAND_MIN:
        raise ApiError("ERR_DEMAND_BELOW_THRESHOLD")
    if (venue_row["lease_extension_days_consumed"] + days
            > venue_row["lease_extension_option_days"]):
        raise ApiError("ERR_LEASE_EXTENSION_EXHAUSTED")

    run_row["demand_index"] = float(figures["_index"])
    run_row["demand_index_at_extension"] = float(figures["_index"])
    run_row["_close_date"] = run_row["_close_date"] + timedelta(days=days)
    run_row["scheduled_close_date"] = run_row["_close_date"].isoformat()
    run_row["extension_days_granted"] += days
    run_row["run_status"] = "EXTENDED"
    touch(run_row)

    venue_row["lease_extension_days_consumed"] += days
    touch(venue_row)
    return object_response(public(run_row))


def _start_closing(run_row):
    """Stop admission: the shop front closes, and the holds it carried die
    with the windows they sat on."""
    run_row["run_status"] = "CLOSING"
    run_row["closing_started_at"] = now_iso()
    touch(run_row)
    for slot_row in derive.slots_of(run_row):
        if slot_row["status"] in SLOT_LIVE_STATUSES:
            slot_row["status"] = "CLOSED_OUT"
            slot_row["held_capacity"] = 0
            slot_row["available_capacity"] = 0
            touch(slot_row)
    # caused by the windows leaving the sellable states, not by the run itself
    for order_row in derive.orders_of_run(run_row):
        if order_row["status"] == "PENDING":
            order_row["status"] = "CANCELLED"
            order_row["refund_pct"] = 0.00
            order_row["refunded_cents"] = 0
            order_row["credit_issued_cents"] = 0
            touch(order_row)


def _close(run_row):
    # hop 1
    run_row["run_status"] = "CLOSED"
    run_row["closed_at"] = now_iso()
    touch(run_row)

    venue_row = derive.venue(run_row["venue_id"])
    kit_row = db.kits.get(run_row["build_kit_id"])
    if kit_row is not None:
        # hop 2 — the kit is struck; the city-move charge reads the OLD city
        moved = (kit_row["last_city_code"] is not None
                 and kit_row["last_city_code"] != venue_row["city_code"])
        wear = calc.kit_wear(kit_row["module_count"], moved)
        decayed = calc.kit_decayed_score(kit_row["condition_score"], wear)
        kit_row["condition_score"] = float(decayed)
        kit_row["reuse_cycle_count"] += 1
        kit_row["last_city_code"] = venue_row["city_code"]
        # hop 3 — routed on the decayed score
        if decayed < calc.REFURB_THRESHOLD:
            kit_row["status"] = "REFURB_REQUIRED"
            # hop 4 — a rebuilt kit must be localised again
            kit_row["localization_status"] = "PENDING"
            kit_row["localization_cost_cents"] = 0
        else:
            kit_row["status"] = "IN_TRANSIT"
        touch(kit_row)

    # independent of the kit hops: the roster is released
    for member in derive.staff_of(run_row):
        if member["status"] in STAFF_RELEASABLE:
            member["status"] = "RELEASED"
            touch(member)
            derive.cancel_scheduled_shifts(member)


@bp.post("/experience-runs/<run_id>/closure-decisions")
@roles(EP)
def closure_decision(run_id):
    run_row = derive.run(run_id)
    body = Body(require_body=True)
    decision = body.enum("decision", CLOSURE_DECISIONS)
    body.string("memo", required=False, default=None, min_len=1, max_len=500)

    if decision == "START_CLOSING":
        # rung 8 — own state
        if run_row["run_status"] not in RUN_OPEN_STATUSES:
            raise ApiError("ERR_RUN_INVALID_STATE")
        _start_closing(run_row)
        return object_response(public(run_row))

    if run_row["run_status"] != "CLOSING":
        raise ApiError("ERR_RUN_INVALID_STATE")
    # the books must be clean before the run may close
    for order_row in derive.orders_of_run(run_row):
        if order_row["status"] in ("CONFIRMED", "REFUND_DUE"):
            raise ApiError("ERR_ORDER_INVALID_STATE")
    for shift_row in derive.shifts_of_run(run_row):
        if shift_row["status"] == "SCHEDULED":
            raise ApiError("ERR_SHIFT_INVALID_STATE")
    _close(run_row)
    return object_response(public(run_row))


def _finalisation_order(inspection_row):
    """Ordering key for 'finalized later than'. The logical clock can stamp two
    finalisations identically, so creation order breaks the tie."""
    return (inspection_row.get("_finalized_at"), inspection_row["_seq"])


@bp.post("/experience-runs/<run_id>/lift-suspension")
@roles(SO)
def lift_suspension(run_id):
    run_row = derive.run(run_id)
    body = Body(require_body=True)
    clearing_id = body.reference("clearing_inspection_id")
    body.string("note", required=False, default=None, min_len=1, max_len=500)

    # rung 5 — body foreign key
    clearing = derive.inspection(clearing_id)

    # rung 8 — own state (compliance dimension)
    if run_row["clearance_status"] != "SUSPENDED":
        raise ApiError("ERR_RUN_INVALID_STATE")

    suspending = db.inspections.get(run_row["suspending_inspection_id"])
    # rung 10 — SoD-1: the officer who closed the run may not reopen it
    if suspending is not None and caller_id() == suspending["finalized_by_user_id"]:
        raise ApiError("ERR_SOD_SUSPENSION_LIFT_SAME_USER")

    # rung 16 — the clearing evidence must actually clear
    if (suspending is None
            or clearing["run_id"] != run_row["id"]
            or clearing["inspection_type"] != suspending["inspection_type"]
            or clearing["status"] != "FINALIZED"
            or clearing["outcome"] != "PASS"
            or _finalisation_order(clearing) <= _finalisation_order(suspending)):
        raise ApiError("ERR_INSPECTION_PASS_MISSING")

    run_row["suspended_at"] = None
    run_row["suspending_inspection_id"] = None
    run_row["clearance_status"] = ("CLEARED" if derive.clearance_gate_holds(run_row)
                                  else "UNCLEARED")
    touch(run_row)

    for slot_row in derive.slots_of(run_row):
        if slot_row["status"] == "SUSPENDED":
            derive.recompute_available(slot_row)
            slot_row["status"] = ("SOLD_OUT" if slot_row["available_capacity"] == 0
                                 else "OPEN")
            touch(slot_row)
    return object_response(public(run_row))
