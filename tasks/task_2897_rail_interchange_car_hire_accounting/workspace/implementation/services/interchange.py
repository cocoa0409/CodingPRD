"""Interchange event capture and its custody / segment consequences
(PRD section 3.3, plus the routing judgement of section 3.6)."""
import db
from services import pricing


def mint_event(
    car_id,
    junction_id,
    event_type,
    delivering_road_id,
    receiving_road_id,
    interchange_at,
    odometer_miles,
    load_status,
    recorded_by_road_id,
    source="CLERK_CAPTURE",
    corrects_event_id=None,
):
    row = db.base_row(versioned=False)
    row.update(
        {
            "car_id": car_id,
            "junction_id": junction_id,
            "event_type": event_type,
            "delivering_road_id": delivering_road_id,
            "receiving_road_id": receiving_road_id,
            "interchange_at": interchange_at,
            "odometer_miles": int(odometer_miles),
            "load_status": load_status,
            "corrects_event_id": corrects_event_id,
            "recorded_by_road_id": recorded_by_road_id,
            "status": "RECORDED",
            "source": source,
        }
    )
    db.events[row["id"]] = row
    return row


def car_events(car_id, status=None):
    rows = [e for e in db.events.values() if e["car_id"] == car_id]
    if status is not None:
        rows = [e for e in rows if e["status"] == status]
    rows.sort(key=lambda e: (e["interchange_at"], e["created_at"], e["_seq"]))
    return rows


def latest_recorded_event(car_id):
    rows = car_events(car_id, status="RECORDED")
    return rows[-1] if rows else None


def recorded_deliveries(car_id):
    return [e for e in car_events(car_id, "RECORDED") if e["event_type"] == "INTERCHANGE_DELIVERY"]


def capture_delivery(car, event):
    """Close the outgoing segment, move custody, open the incoming segment."""
    closing = pricing.open_movement_for(car)
    if closing is not None:
        pricing.close_movement(closing, event)

    car["current_handling_road_id"] = event["receiving_road_id"]

    violated = False
    if event["load_status"] == "EMPTY" and car["routing_status"] == "OBLIGATION_ACTIVE":
        met = (
            event["junction_id"] == car["prescribed_return_junction_id"]
            and event["receiving_road_id"] == car["owner_road_id"]
            and car["obligation_due_at"] is not None
            and event["interchange_at"] <= car["obligation_due_at"]
        )
        if met:
            car["routing_status"] = "OBLIGATION_MET"
            car["prescribed_return_junction_id"] = None
            car["obligation_issued_at"] = None
            car["obligation_due_at"] = None
        else:
            car["routing_status"] = "OBLIGATION_VIOLATED"
            violated = True
    db.touch(car)

    opened = pricing.open_movement(
        car,
        event["receiving_road_id"],
        event["interchange_at"],
        event["odometer_miles"],
        event["load_status"],
        event["id"],
    )

    if violated and closing is not None:
        pricing.apply_reverse_route_penalty(closing)

    return closing, opened


def capture_rejection(car, event):
    """A refused car changes no custody and closes no segment; it bad orders
    the car and stamps the delivering road's still open segment."""
    if car["mechanical_status"] == "SERVICEABLE":
        car["mechanical_status"] = "BAD_ORDER"
        car["bad_order_since"] = event["interchange_at"]
        db.touch(car)

    segment = pricing.open_movement_for(car)
    if (
        segment is not None
        and segment["handling_road_id"] == event["delivering_road_id"]
        and segment["bad_order_from"] is None
    ):
        segment["bad_order_from"] = event["interchange_at"]
        segment["bad_order_to"] = None
        db.touch(segment)
    return segment
