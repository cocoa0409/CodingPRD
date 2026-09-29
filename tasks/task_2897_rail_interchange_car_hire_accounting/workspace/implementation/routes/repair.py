"""Repair bills: drafting, responsibility, pricing and negotiation
(PRD section 3.7)."""
from decimal import Decimal

from flask import Blueprint

import db
import middleware
import response
import shapes
from errors import fail
from middleware import endpoint
from services import ledger, money, serialize

bp = Blueprint("repair", __name__)


def covering_segment(car_id, instant):
    """The segment whose half-open custody window contains the instant; an
    open segment is treated as extending to the logical clock."""
    rows = [
        m
        for m in db.movements.values()
        if m["car_id"] == car_id and m["status"] in ("OPEN", "CLOSED")
    ]
    rows.sort(key=lambda m: (m["start_at"], m["created_at"], m["_seq"]))
    now = db.now()
    for m in rows:
        end = m["end_at"] if m["end_at"] is not None else now
        if m["start_at"] <= instant < end:
            return m
    return None


def _bill_action_standing(bill):
    """Negotiation belongs to the responsible road once one is known."""
    if bill["responsible_road_id"]:
        middleware.require_party(bill["responsible_road_id"])
    else:
        middleware.require_party(bill["billing_road_id"])


@bp.post("/car-hire/repair-bills")
@endpoint(roles=[db.ROLE_REPAIR_AGENT])
def draft_bill():
    body = shapes.body()
    car_id = shapes.s_id(body, "car_id")
    billing_road_id = shapes.s_id(body, "billing_road_id")
    defect_code = shapes.s_str(body, "defect_code")
    defect_class = shapes.s_str(body, "defect_class")
    defect_occurred_at = shapes.s_dt(body, "defect_occurred_at")
    labor_hours = shapes.s_num(body, "labor_hours", minimum=0)
    material_cents = shapes.s_int(body, "material_cents", minimum=0)
    discovery_event_id = shapes.s_id(body, "discovery_event_id", required=False)
    pre_auth = shapes.s_str(body, "pre_authorization_reference", required=False, allow_empty=True)
    labor_hours = money.half_up_2(labor_hours)
    if labor_hours == 0 and material_cents == 0:
        fail("ERR_INVALID_REQUEST", "labor_hours and material_cents must not both be zero.")
    shapes.check_enum("defect_class", defect_class, db.DEFECT_CLASS)

    car = db.lookup("car", car_id)
    db.lookup("railroad", billing_road_id)
    discovery = None
    if discovery_event_id is not None:
        discovery = db.lookup("event", discovery_event_id)
        if discovery["car_id"] != car["id"] or discovery["status"] != "RECORDED":
            fail("ERR_INVALID_REQUEST", "discovery_event_id must be a RECORDED event of this car.")

    middleware.require_party(billing_road_id)
    middleware.require_active(middleware.acting(), billing_road_id)
    if car["mechanical_status"] != "BAD_ORDER":
        fail("ERR_CAR_NOT_BAD_ORDERED")

    row = db.base_row()
    row.update(
        {
            "car_id": car["id"],
            "discovery_event_id": discovery_event_id,
            "billing_road_id": billing_road_id,
            "responsible_road_id": None,
            "settlement_cycle_id": None,
            "defect_code": defect_code,
            "defect_class": defect_class,
            "defect_occurred_at": defect_occurred_at,
            "labor_hours": labor_hours,
            "material_cents": material_cents,
            "pre_authorization_reference": pre_auth,
            "labor_cents": None,
            "subtotal_cents": None,
            "handling_fee_cents": None,
            "total_cents": None,
            "responsibility_rule_applied": None,
            "counter_bill_round": 0,
            "status": "DRAFT",
            "submitted_at": None,
            "accepted_at": None,
            "rejected_at": None,
            "settled_at": None,
            "last_counter_at": None,
        }
    )
    db.bills[row["id"]] = row
    return response.ok(serialize.bill(row), 201)


@bp.get("/car-hire/repair-bills")
@endpoint(roles=db.ALL_ROLES)
def list_bills():
    response.page_params()
    status = shapes.q_enum("status", db.REPAIR_BILL_STATUS)
    defect_class = shapes.q_enum("defect_class", db.DEFECT_CLASS)
    car_id = shapes.q_str("car_id")
    discovery_event_id = shapes.q_str("discovery_event_id")
    billing = shapes.q_str("billing_road_id")
    responsible = shapes.q_str("responsible_road_id")
    cycle_id = shapes.q_str("settlement_cycle_id")
    rows = list(db.bills.values())
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if defect_class is not None:
        rows = [r for r in rows if r["defect_class"] == defect_class]
    if car_id is not None:
        rows = [r for r in rows if r["car_id"] == car_id]
    if discovery_event_id is not None:
        rows = [r for r in rows if r["discovery_event_id"] == discovery_event_id]
    if billing is not None:
        rows = [r for r in rows if r["billing_road_id"] == billing]
    if responsible is not None:
        rows = [r for r in rows if r["responsible_road_id"] == responsible]
    if cycle_id is not None:
        rows = [r for r in rows if r["settlement_cycle_id"] == cycle_id]
    rows.sort(key=db.order_key)
    return response.paginate(rows, serialize.bill)


@bp.get("/car-hire/repair-bills/<repair_bill_id>")
@endpoint(roles=db.ALL_ROLES, path_params=[("repair_bill_id", "bill")])
def read_bill(bill):
    middleware.party_bill(bill)
    return response.ok(serialize.bill(bill))


@bp.post("/car-hire/repair-bills/<repair_bill_id>/submit")
@endpoint(roles=[db.ROLE_REPAIR_AGENT], path_params=[("repair_bill_id", "bill")])
def submit_bill(bill):
    car = db.cars[bill["car_id"]]
    middleware.require_party(bill["billing_road_id"])
    if bill["status"] != "DRAFT":
        fail("ERR_INVALID_STATE_TRANSITION")
    middleware.require_active(middleware.acting(), bill["billing_road_id"])

    if bill["defect_class"] == "HANDLING_DAMAGE":
        segment = covering_segment(car["id"], bill["defect_occurred_at"])
        if segment is None:
            fail("ERR_NO_CUSTODY_AT_DEFECT_TIME")
        responsible = segment["handling_road_id"]
        rule = "HANDLING_LINE_RULE"
    else:
        responsible = car["owner_road_id"]
        rule = "OWNER_RESPONSIBILITY_RULE"

    labor_cents = money.repair_labor_cents(bill["labor_hours"])
    subtotal = labor_cents + int(bill["material_cents"])
    fee = money.repair_handling_fee_cents(subtotal, responsible, bill["billing_road_id"])
    total = subtotal + fee

    pre_auth = bill["pre_authorization_reference"]
    if total > db.REPAIR_PREAUTH_THRESHOLD_CENTS and (pre_auth is None or not pre_auth.strip()):
        fail("ERR_REPAIR_PREAUTH_REQUIRED")

    bill["responsible_road_id"] = responsible
    bill["responsibility_rule_applied"] = rule
    bill["labor_cents"] = labor_cents
    bill["subtotal_cents"] = subtotal
    bill["handling_fee_cents"] = fee
    bill["total_cents"] = total
    bill["status"] = "SUBMITTED"
    bill["submitted_at"] = db.now()
    bill["counter_bill_round"] = 0
    db.touch(bill)

    if car["mechanical_status"] == "BAD_ORDER":
        car["mechanical_status"] = "UNDER_REPAIR"
        db.touch(car)
    return response.ok(serialize.bill(bill))


@bp.post("/car-hire/repair-bills/<repair_bill_id>/counter-bill")
@endpoint(roles=[db.ROLE_REPAIR_AGENT], path_params=[("repair_bill_id", "bill")])
def counter_bill(bill):
    body = shapes.body()
    counter_total_cents = shapes.s_int(body, "counter_total_cents", required=False)
    reject = shapes.s_bool(body, "reject", required=False, default=False)
    shapes.s_str(body, "counter_note", required=False)

    _bill_action_standing(bill)
    if bill["status"] != "SUBMITTED":
        fail("ERR_REPAIR_BILL_NOT_SUBMITTED")
    middleware.require_active(
        middleware.acting(), bill["billing_road_id"], bill["responsible_road_id"]
    )

    if reject and counter_total_cents is None:
        bill["status"] = "REJECTED"
        bill["rejected_at"] = db.now()
        db.touch(bill)
        return response.ok(serialize.bill(bill))

    if int(bill["counter_bill_round"] or 0) >= db.MAX_COUNTER_BILL_ROUNDS:
        fail("ERR_COUNTER_BILL_ROUNDS_EXHAUSTED")
    if counter_total_cents is None:
        fail("ERR_REPAIR_AMOUNT_INVALID")
    if not (0 < counter_total_cents < int(bill["total_cents"] or 0)):
        fail("ERR_REPAIR_AMOUNT_INVALID")

    bill["total_cents"] = counter_total_cents
    bill["counter_bill_round"] = int(bill["counter_bill_round"] or 0) + 1
    bill["last_counter_at"] = db.now()
    db.touch(bill)
    return response.ok(serialize.bill(bill))


@bp.post("/car-hire/repair-bills/<repair_bill_id>/accept")
@endpoint(roles=[db.ROLE_REPAIR_AGENT], path_params=[("repair_bill_id", "bill")])
def accept_bill(bill):
    _bill_action_standing(bill)
    if bill["status"] != "SUBMITTED":
        fail("ERR_REPAIR_BILL_NOT_SUBMITTED")
    middleware.require_active(
        middleware.acting(), bill["billing_road_id"], bill["responsible_road_id"]
    )

    bill["status"] = "ACCEPTED"
    bill["accepted_at"] = db.now()
    db.touch(bill)
    ledger.mint(
        "REPAIR_CHARGE",
        int(bill["total_cents"] or 0),
        bill["responsible_road_id"],
        bill["billing_road_id"],
        "POST /car-hire/repair-bills/{id}/accept accepted repair bill %s" % bill["id"],
        settlement_cycle_id=bill["settlement_cycle_id"],
        repair_bill_id=bill["id"],
    )
    return response.ok(serialize.bill(bill))


@bp.post("/car-hire/repair-bills/<repair_bill_id>/settle")
@endpoint(roles=[db.ROLE_ADMIN], path_params=[("repair_bill_id", "bill")])
def settle_bill(bill):
    if bill["status"] != "ACCEPTED":
        fail("ERR_INVALID_STATE_TRANSITION")
    bill["status"] = "SETTLED"
    bill["settled_at"] = db.now()
    db.touch(bill)

    car = db.cars.get(bill["car_id"])
    if car is not None and car["mechanical_status"] == "UNDER_REPAIR":
        car["mechanical_status"] = "SERVICEABLE"
        car["bad_order_since"] = None
        car["bad_order_cleared_at"] = db.now()
        db.touch(car)
        from services import pricing

        segment = pricing.open_movement_for(car)
        if segment is not None and segment["bad_order_from"] is not None and segment["bad_order_to"] is None:
            segment["bad_order_to"] = db.now()
            db.touch(segment)
    return response.ok(serialize.bill(bill))
