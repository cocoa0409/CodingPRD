"""Hire segment lifecycle and pricing (PRD sections 3.2, 3.4, 3.5, 3.6)."""
from decimal import Decimal

import db
from services import ledger, money, settlement


def car_type_of(movement):
    car = db.cars.get(movement["car_id"])
    if car is None:
        return None
    return db.car_types.get(car["car_type_id"])


def open_movement(car, handling_road_id, start_at, start_odometer, load_status, received_event_id):
    row = db.base_row()
    row.update(
        {
            "car_id": car["id"],
            "handling_road_id": handling_road_id,
            "owner_road_id": car["owner_road_id"],
            "received_event_id": received_event_id,
            "delivered_event_id": None,
            "settlement_cycle_id": None,
            "start_at": start_at,
            "end_at": None,
            "load_status": load_status,
            "start_odometer_miles": int(start_odometer),
            "end_odometer_miles": None,
            "hire_liable": handling_road_id != car["owner_road_id"],
            "chargeable_hours": Decimal("0.00"),
            "chargeable_days": 0,
            "time_component_cents": 0,
            "mileage_component_cents": 0,
            "gross_hire_cents": 0,
            "reclaim_credit_cents": 0,
            "reverse_route_penalty_cents": 0,
            "net_hire_cents": 0,
            "adjusted_net_hire_cents": 0,
            "bad_order_from": None,
            "bad_order_to": None,
            "reclaim_locked": False,
            "recompute_count": 0,
            "status": "OPEN",
        }
    )
    db.movements[row["id"]] = row
    return row


def open_movement_for(car):
    """The car's single still-open segment, if any."""
    rows = [
        m for m in db.movements.values() if m["car_id"] == car["id"] and m["status"] == "OPEN"
    ]
    rows.sort(key=db.order_key)
    return rows[-1] if rows else None


def price(movement):
    """Recompute the derived money of a CLOSED segment."""
    car_type = car_type_of(movement)
    if car_type is None or movement["end_at"] is None:
        return
    elapsed = money.elapsed_hours(movement["start_at"], movement["end_at"])
    charge_hours = money.chargeable_hours(elapsed, car_type["free_time_hours"])
    day_count, time_cents = money.time_component(car_type, charge_hours)
    miles = int(movement["end_odometer_miles"] or 0) - int(movement["start_odometer_miles"] or 0)
    mileage_cents = money.mileage_component(car_type, miles, movement["load_status"])
    if not movement["hire_liable"]:
        # A segment that is not hire liable accrues no time, mileage or penalty.
        time_cents = 0
        mileage_cents = 0
        movement["reverse_route_penalty_cents"] = 0
    movement["chargeable_hours"] = charge_hours
    movement["chargeable_days"] = day_count
    movement["time_component_cents"] = time_cents
    movement["mileage_component_cents"] = mileage_cents
    movement["gross_hire_cents"] = time_cents + mileage_cents
    apply_waterfall(movement)
    recompute_net(movement)


def allowed_claims(movement):
    rows = [
        c
        for c in db.claims.values()
        if c["movement_id"] == movement["id"] and c["status"] == "ALLOWED"
    ]
    # window_from ASC, created_at ASC, claimed_hours DESC
    rows.sort(key=lambda c: (c["window_from"], c["created_at"], -Decimal(c["claimed_hours"])))
    return rows


def apply_waterfall(movement):
    """Allowed credits are drawn against the segment's time component only,
    in filing order, until the pot is empty (PRD section 3.5)."""
    remaining = int(movement["time_component_cents"] or 0)
    total = 0
    for claim in allowed_claims(movement):
        if remaining <= 0:
            continue
        take = min(int(claim["credit_cents"] or 0), remaining)
        if take < 0:
            take = 0
        total += take
        remaining -= take
    movement["reclaim_credit_cents"] = total
    return total


def accepted_dispute_for(movement):
    rows = [
        d
        for d in db.disputes.values()
        if d["movement_id"] == movement["id"] and d["status"] == "ACCEPTED"
    ]
    rows.sort(key=db.order_key)
    return rows[-1] if rows else None


def recompute_net(movement):
    net = (
        int(movement["gross_hire_cents"] or 0)
        - int(movement["reclaim_credit_cents"] or 0)
        + int(movement["reverse_route_penalty_cents"] or 0)
    )
    movement["net_hire_cents"] = net
    dispute = accepted_dispute_for(movement)
    if dispute is not None:
        movement["adjusted_net_hire_cents"] = net - int(dispute["resolution_amount_cents"] or 0)
    else:
        movement["adjusted_net_hire_cents"] = net
    return net


def close_movement(movement, event):
    """Close a segment on a delivery event and price it immediately."""
    movement["end_at"] = event["interchange_at"]
    movement["delivered_event_id"] = event["id"]
    movement["end_odometer_miles"] = int(event["odometer_miles"])
    movement["status"] = "CLOSED"
    if movement["bad_order_from"] is not None and movement["bad_order_to"] is None:
        movement["bad_order_to"] = event["interchange_at"]
    price(movement)
    db.touch(movement)
    return movement


def apply_reverse_route_penalty(movement):
    """Charge the just closed segment a quarter of its time component and lock
    it against reclaims (PRD section 3.6)."""
    old_net = int(movement["net_hire_cents"] or 0)
    if movement["hire_liable"]:
        movement["reverse_route_penalty_cents"] = money.reverse_route_penalty_cents(
            movement["time_component_cents"]
        )
    else:
        movement["reverse_route_penalty_cents"] = 0
    movement["reclaim_locked"] = True
    new_net = recompute_net(movement)
    db.touch(movement)
    cycle_id = movement["settlement_cycle_id"]
    if cycle_id:
        cycle = db.cycles.get(cycle_id)
        if cycle is not None and cycle["status"] in ("COMPUTED", "EXCHANGED", "SETTLED"):
            delta = new_net - old_net
            ledger.mint(
                "CORRECTION_ADJUSTMENT",
                delta,
                cycle["payer_road_id"],
                cycle["payee_road_id"],
                "POST /car-hire/interchange-events charged a reverse route penalty to movement %s"
                % movement["id"],
                settlement_cycle_id=cycle["id"],
                movement_id=movement["id"],
            )
            settlement.recompute(cycle)
    return movement
