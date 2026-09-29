"""Applying a confirmed correction request: the five layer cascade of
PRD section 3.9 (event log, segment boundaries, derived money, dependent
reclaims, ledger and cycles)."""
from decimal import Decimal

import db
from services import interchange, ledger, money, pricing, serialize, settlement

SIGNATURE_FIELDS = (
    "handling_road_id",
    "received_event_id",
    "delivered_event_id",
    "start_at",
    "end_at",
    "load_status",
    "start_odometer_miles",
    "end_odometer_miles",
    "hire_liable",
    "chargeable_hours",
    "chargeable_days",
    "time_component_cents",
    "mileage_component_cents",
    "gross_hire_cents",
    "reclaim_credit_cents",
    "reverse_route_penalty_cents",
    "net_hire_cents",
    "adjusted_net_hire_cents",
    "bad_order_from",
    "bad_order_to",
    "status",
)


def _signature(movement):
    return tuple(movement.get(name) for name in SIGNATURE_FIELDS)


def car_segments(car_id):
    rows = [m for m in db.movements.values() if m["car_id"] == car_id]
    rows.sort(key=db.order_key)
    return rows


def _reset_open_money(movement):
    movement["chargeable_hours"] = Decimal("0.00")
    movement["chargeable_days"] = 0
    movement["time_component_cents"] = 0
    movement["mileage_component_cents"] = 0
    movement["gross_hire_cents"] = 0
    movement["reclaim_credit_cents"] = 0
    movement["net_hire_cents"] = 0
    movement["adjusted_net_hire_cents"] = 0


def _void_money(movement):
    _reset_open_money(movement)
    movement["reverse_route_penalty_cents"] = 0


def apply_correction(request):
    car = db.cars[request["car_id"]]
    before = {m["id"]: _signature(m) for m in car_segments(car["id"])}
    old_nets = {m["id"]: int(m["net_hire_cents"] or 0) for m in car_segments(car["id"])}
    old_cycles = {m["id"]: m["settlement_cycle_id"] for m in car_segments(car["id"])}

    # ---------------- layer 1: the event log ----------------
    resulting = None
    ctype = request["correction_type"]
    if ctype == "MISSED_EVENT_INSERT":
        if request["direction"] == "FILER_DELIVERS":
            delivering = request["filed_by_road_id"]
            receiving = request["counterparty_road_id"]
        else:
            delivering = request["counterparty_road_id"]
            receiving = request["filed_by_road_id"]
        resulting = interchange.mint_event(
            car["id"],
            request["junction_id"],
            "INTERCHANGE_DELIVERY",
            delivering,
            receiving,
            request["proposed_interchange_at"],
            request["proposed_odometer_miles"],
            request["proposed_load_status"],
            request["filed_by_road_id"],
            source="CORRECTION_APPLY",
        )
    elif ctype == "TIMESTAMP_AMEND":
        target = db.events[request["target_event_id"]]
        target["status"] = "SUPERSEDED"
        resulting = interchange.mint_event(
            target["car_id"],
            target["junction_id"],
            target["event_type"],
            target["delivering_road_id"],
            target["receiving_road_id"],
            request["proposed_interchange_at"],
            target["odometer_miles"],
            target["load_status"],
            request["filed_by_road_id"],
            source="CORRECTION_APPLY",
            corrects_event_id=target["id"],
        )
        for m in car_segments(car["id"]):
            if m["received_event_id"] == target["id"]:
                m["received_event_id"] = resulting["id"]
            if m["delivered_event_id"] == target["id"]:
                m["delivered_event_id"] = resulting["id"]
    else:  # ERRONEOUS_EVENT_VOID
        target = db.events[request["target_event_id"]]
        target["status"] = "VOID"
        # voiding a rejection erases the bad order stamp it wrote
        for m in car_segments(car["id"]):
            if m["bad_order_from"] == target["interchange_at"]:
                m["bad_order_from"] = None
                m["bad_order_to"] = None

    request["resulting_event_id"] = resulting["id"] if resulting else None

    # ---------------- layer 2: segment boundaries ----------------
    _rebuild_segments(car, request)

    # ---------------- layer 3: derived money ----------------
    for m in car_segments(car["id"]):
        if m["status"] == "CLOSED":
            pricing.price(m)
        elif m["status"] == "OPEN":
            _reset_open_money(m)
        else:
            _void_money(m)

    # ---------------- layer 4: dependent reclaims ----------------
    for m in car_segments(car["id"]):
        _disallow_orphaned_reclaims(m)
        if m["status"] == "CLOSED":
            pricing.apply_waterfall(m)
            pricing.recompute_net(m)

    # ---------------- bookkeeping: bump only what really moved ----------------
    changed = []
    for m in car_segments(car["id"]):
        sig = _signature(m)
        if m["id"] not in before:
            changed.append(m)
            continue
        if sig != before[m["id"]]:
            m["recompute_count"] = int(m["recompute_count"] or 0) + 1
            db.touch(m)
            changed.append(m)

    # the car's custody follows the surviving open segment
    open_segment = pricing.open_movement_for(car)
    if open_segment is not None and car["current_handling_road_id"] != open_segment["handling_road_id"]:
        car["current_handling_road_id"] = open_segment["handling_road_id"]
        db.touch(car)

    # ---------------- layer 5: ledger and cycles ----------------
    touched_cycles = []
    for m in changed:
        cycle_id = m["settlement_cycle_id"] or old_cycles.get(m["id"])
        if not cycle_id:
            continue
        cycle = db.cycles.get(cycle_id)
        if cycle is None or cycle["status"] == "ARCHIVED":
            continue
        delta = int(m["net_hire_cents"] or 0) - int(old_nets.get(m["id"], 0))
        if delta != 0:
            ledger.mint(
                "CORRECTION_ADJUSTMENT",
                delta,
                cycle["payer_road_id"],
                cycle["payee_road_id"],
                "POST /car-hire/correction-requests/{id}/apply rewrote movement %s" % m["id"],
                settlement_cycle_id=cycle["id"],
                movement_id=m["id"],
            )
        if cycle["id"] not in [c["id"] for c in touched_cycles]:
            touched_cycles.append(cycle)
    for cycle in touched_cycles:
        settlement.recompute(cycle)

    request["status"] = "APPLIED"
    request["applied_at"] = db.now()
    db.touch(request)
    return request


def _rebuild_segments(car, request):
    """Re-derive the segment chain from the surviving RECORDED delivery events."""
    deliveries = interchange.recorded_deliveries(car["id"])
    live = [m for m in car_segments(car["id"]) if m["status"] != "VOID"]
    by_event = {m["received_event_id"]: m for m in live if m["received_event_id"]}
    bootstrap = next((m for m in live if m["received_event_id"] is None), None)

    pairs = []
    if bootstrap is not None:
        pairs.append([bootstrap, None])
    chained = set()
    if bootstrap is not None:
        chained.add(bootstrap["id"])
    for event in deliveries:
        if pairs:
            pairs[-1][1] = event
        segment = by_event.get(event["id"])
        if segment is None:
            segment = pricing.open_movement(
                car,
                event["receiving_road_id"],
                event["interchange_at"],
                event["odometer_miles"],
                event["load_status"],
                event["id"],
            )
        else:
            segment["handling_road_id"] = event["receiving_road_id"]
            segment["start_at"] = event["interchange_at"]
            segment["start_odometer_miles"] = int(event["odometer_miles"])
            segment["load_status"] = event["load_status"]
            segment["hire_liable"] = event["receiving_road_id"] != car["owner_road_id"]
        chained.add(segment["id"])
        pairs.append([segment, None])

    for segment, closer in pairs:
        if closer is None:
            segment["end_at"] = None
            segment["delivered_event_id"] = None
            segment["end_odometer_miles"] = None
            segment["status"] = "OPEN"
        else:
            segment["end_at"] = closer["interchange_at"]
            segment["delivered_event_id"] = closer["id"]
            segment["end_odometer_miles"] = int(closer["odometer_miles"])
            segment["status"] = "CLOSED"

    # a segment whose opening event has been erased no longer exists
    for segment in live:
        if segment["id"] not in chained and _voidable(segment):
            segment["status"] = "VOID"

    # a segment left with zero length is void
    for segment, _closer in pairs:
        if (
            segment["end_at"] is not None
            and segment["end_at"] <= segment["start_at"]
            and _voidable(segment)
        ):
            segment["status"] = "VOID"


def _voidable(segment):
    """A segment held by an ARCHIVED cycle whose hire charge was already
    reversed cannot be voided again (PRD section 3.9 layer 2)."""
    cycle_id = segment["settlement_cycle_id"]
    if not cycle_id:
        return True
    cycle = db.cycles.get(cycle_id)
    if cycle is None or cycle["status"] != "ARCHIVED":
        return True
    reversed_already = any(
        e["entry_type"] == "CORRECTION_ADJUSTMENT" and e["movement_id"] == segment["id"]
        for e in db.ledger.values()
    )
    return not reversed_already


def _disallow_orphaned_reclaims(movement):
    """An ALLOWED reclaim whose supporting bad order stamp has disappeared is
    driven to DISALLOWED with the literal reason SUPPORTING_EVENT_VOIDED."""
    for claim in list(db.claims.values()):
        if claim["movement_id"] != movement["id"] or claim["status"] != "ALLOWED":
            continue
        if claim["reason"] != "BAD_ORDER":
            continue
        if movement["bad_order_from"] is not None and movement["status"] != "VOID":
            continue
        claim["status"] = "DISALLOWED"
        claim["disallow_reason"] = "SUPPORTING_EVENT_VOIDED"
        claim["credit_cents"] = 0
        claim["allowed_hours"] = None
        claim["split_pct_applied"] = None
        claim["decided_at"] = db.now()
        db.touch(claim)
