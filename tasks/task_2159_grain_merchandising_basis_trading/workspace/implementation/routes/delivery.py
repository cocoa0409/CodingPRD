"""Delivery tickets (grading, apply, reject, reverse) and freight bookings."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

from aggregates import derive_delivery_status, recompute_desk
from auth import ALL_ROLES, endpoint
from calc import (FLEET_TURNAROUND_HOURS, net_bushels_for,
                  quality_discount_total, settlement_figures)
from errors import fail
from response import ok, paged
from routes.contracts import maybe_settle
from serializers import booking_out, ticket_out
from store import (D, apply_changes, db, new_row, r2, sort_rows, touch)
from validate import (body, guard_payload, lookup, lookup_fk, req_int, req_num,
                      req_str, req_ts)

bp = Blueprint("delivery", __name__)


# --------------------------------------------------------------------------
# DeliveryTicket
# --------------------------------------------------------------------------
@bp.post("/grain/delivery-tickets")
@endpoint(["GrainInspector"])
def grade_ticket(actor):
    payload = guard_payload(body())
    contract = lookup_fk(payload, "contract_id", "purchase_contracts")   # ladder 4
    location = lookup_fk(payload, "location_id", "elevator_locations")
    booking = lookup_fk(payload, "freight_booking_id", "freight_bookings")
    if contract is None or location is None:
        fail("ERR_INVALID_REQUEST")

    gross_bushels = req_num(payload, "gross_bushels", minimum=0,          # ladder 5
                            exclusive_min=True)
    moisture = req_num(payload, "moisture_pct", minimum=0)
    test_weight = req_num(payload, "test_weight_lbs", minimum=0,
                          exclusive_min=True)
    foreign_material = req_num(payload, "foreign_material_pct", minimum=0)
    damage = req_num(payload, "damage_pct", minimum=0)

    if contract["status"] != "ACTIVE":                                    # ladder 9
        fail("ERR_CONTRACT_NOT_ACTIVE")
    if location["id"] != contract["location_id"]:                         # ladder 15
        fail("ERR_LOCATION_MISMATCH")

    schedule = None                                                       # ladder 29
    for row in sort_rows(db.discount_schedules.values()):
        if row["commodity_code"] == contract["commodity_code"] \
                and row["status"] == "ACTIVE":
            schedule = row
            break
    if schedule is None:
        fail("ERR_NO_ACTIVE_DISCOUNT_SCHEDULE")

    measurements = {
        "moisture_pct": moisture,
        "test_weight_lbs": test_weight,
        "foreign_material_pct": foreign_material,
        "damage_pct": damage,
    }
    shrink_pct, net_bushels = net_bushels_for(
        contract["settlement_basis"], gross_bushels, moisture, schedule)
    discount_total = quality_discount_total(
        contract["settlement_basis"], measurements, schedule, net_bushels)
    gross_value, fee, net_unit_price, settlement_value = settlement_figures(
        contract["gross_unit_price_cents"], net_bushels, discount_total)

    row = new_row()
    row.update({
        "contract_id": contract["id"],
        "location_id": location["id"],
        "freight_booking_id": booking["id"] if booking is not None else None,
        "discount_schedule_id": schedule["id"],
        "gross_bushels": D(gross_bushels),
        "moisture_pct": D(moisture),
        "test_weight_lbs": D(test_weight),
        "foreign_material_pct": D(foreign_material),
        "damage_pct": D(damage),
        "shrink_pct": shrink_pct,
        "net_bushels": net_bushels,
        "discount_total_usd": discount_total,
        "gross_contract_value_usd": gross_value,
        "service_fee_cents_per_bushel": fee,
        "net_unit_price_cents": net_unit_price,
        "settlement_value_usd": settlement_value,
        "disposition_reason": None,
        "graded_by_user_id": actor["user_id"],
        "status": "GRADED",
    })
    db.delivery_tickets[row["id"]] = row
    return ok(ticket_out(row), 201)


@bp.post("/grain/delivery-tickets/<ticket_id>/apply")
@endpoint(["Merchandiser"])
def apply_ticket(actor, ticket_id):
    ticket = lookup("delivery_tickets", ticket_id)                        # ladder 3
    contract = db.purchase_contracts.get(ticket["contract_id"])
    if contract is None or contract["status"] != "ACTIVE":                # ladder 9
        fail("ERR_CONTRACT_NOT_ACTIVE")
    if ticket["status"] != "GRADED":                                      # ladder 10
        fail("ERR_TICKET_NOT_GRADED")

    booking = None
    if ticket["freight_booking_id"]:                                      # ladder 13
        booking = db.freight_bookings.get(ticket["freight_booking_id"])
        if booking is None or booking["status"] != "CONFIRMED":
            fail("ERR_FREIGHT_BOOKING_NOT_CONFIRMED")

    remaining = D(contract["bushels"]) - D(contract["delivered_bushels"])
    if D(ticket["net_bushels"]) > remaining:                              # ladder 36
        fail("ERR_BUSHELS_EXCEEDED")

    apply_changes(ticket, {"status": "APPLIED"})

    settlement = ticket["settlement_value_usd"]
    delivered = D(contract["delivered_bushels"]) + D(ticket["net_bushels"])
    apply_changes(contract, {
        "delivered_bushels": delivered,
        "settled_value_usd": r2(D(contract["settled_value_usd"])
                                + (D(settlement) if settlement is not None
                                   else Decimal(0))),
        "delivery_status": derive_delivery_status(contract["bushels"], delivered),
    })

    if booking is not None:
        apply_changes(booking, {"status": "COMPLETED"})

    if not maybe_settle(contract):
        recompute_desk(db.trading_desks[contract["desk_id"]])
    return ok(ticket_out(ticket))


@bp.post("/grain/delivery-tickets/<ticket_id>/reject")
@endpoint(["GrainInspector"])
def reject_ticket(actor, ticket_id):
    ticket = lookup("delivery_tickets", ticket_id)
    payload = guard_payload(body())
    reason = req_str(payload, "rejection_reason")                         # ladder 5
    if ticket["status"] != "GRADED":                                      # ladder 10
        fail("ERR_TICKET_NOT_GRADED")
    apply_changes(ticket, {"status": "REJECTED", "disposition_reason": reason})
    return ok(ticket_out(ticket))


@bp.post("/grain/delivery-tickets/<ticket_id>/reverse")
@endpoint(["GrainInspector"])
def reverse_ticket(actor, ticket_id):
    ticket = lookup("delivery_tickets", ticket_id)
    payload = guard_payload(body())
    reason = req_str(payload, "reversal_reason")                          # ladder 5
    contract = db.purchase_contracts.get(ticket["contract_id"])
    if contract is None or contract["status"] != "ACTIVE":                # ladder 9
        fail("ERR_CONTRACT_NOT_ACTIVE")
    if ticket["status"] != "APPLIED":                                     # ladder 10
        fail("ERR_TICKET_NOT_GRADED")

    apply_changes(ticket, {"status": "REVERSED", "disposition_reason": reason})

    settlement = ticket["settlement_value_usd"]
    delivered = D(contract["delivered_bushels"]) - D(ticket["net_bushels"])
    apply_changes(contract, {
        "delivered_bushels": delivered,
        "settled_value_usd": r2(D(contract["settled_value_usd"])
                                - (D(settlement) if settlement is not None
                                   else Decimal(0))),
        "delivery_status": derive_delivery_status(contract["bushels"], delivered),
    })
    recompute_desk(db.trading_desks[contract["desk_id"]])
    return ok(ticket_out(ticket))


@bp.get("/grain/delivery-tickets")
@endpoint(ALL_ROLES)
def list_tickets(actor):
    rows = list(db.delivery_tickets.values())
    for field in ("contract_id", "location_id", "freight_booking_id",
                  "discount_schedule_id", "status"):
        value = request.args.get(field)
        if value:
            rows = [r for r in rows if r[field] == value]
    return paged(sort_rows(rows), ticket_out)


@bp.get("/grain/delivery-tickets/<ticket_id>")
@endpoint(ALL_ROLES)
def read_ticket(actor, ticket_id):
    return ok(ticket_out(lookup("delivery_tickets", ticket_id)))


# --------------------------------------------------------------------------
# FreightBooking
# --------------------------------------------------------------------------
def _intersects(fleet_id, start, end, exclude_id=None):
    for booking in db.freight_bookings.values():
        if booking["fleet_id"] != fleet_id:
            continue
        if booking["status"] not in ("REQUESTED", "CONFIRMED"):
            continue
        if exclude_id is not None and booking["id"] == exclude_id:
            continue
        if start < booking["occupancy_end_at"] and booking["placement_at"] < end:
            return True
    return False


@bp.post("/grain/freight-bookings")
@endpoint(["FreightCoordinator"])
def create_booking(actor):
    payload = guard_payload(body())
    fleet = lookup_fk(payload, "fleet_id", "rail_fleets")                 # ladder 4
    contract = lookup_fk(payload, "contract_id", "purchase_contracts")
    if fleet is None or contract is None:
        fail("ERR_INVALID_REQUEST")

    cars = req_int(payload, "cars_requested", minimum=0, exclusive_min=True)
    placement_at = req_ts(payload, "placement_at")                        # ladder 5
    release_at = req_ts(payload, "release_at")
    if not (release_at > placement_at):
        fail("ERR_INVALID_REQUEST", "release_at must be strictly after placement_at.")
    expected = req_int(payload, "expected_fleet_version")
    if expected != fleet["version"]:                                      # ladder 7
        fail("ERR_STALE_FLEET_VERSION")

    if contract["status"] != "ACTIVE":                                    # ladder 9
        fail("ERR_CONTRACT_NOT_ACTIVE")

    location = db.elevator_locations.get(contract["location_id"])         # ladder 16
    if not location["rail_served"] or fleet["home_location_id"] != location["id"]:
        fail("ERR_LOCATION_NOT_RAIL_SERVED")

    occupancy_end = release_at + timedelta(hours=FLEET_TURNAROUND_HOURS)
    if _intersects(fleet["id"], placement_at, occupancy_end):             # ladder 27
        fail("ERR_FLEET_UNAVAILABLE")
    if cars > fleet["car_count"]:                                         # ladder 32
        fail("ERR_CARS_EXCEED_FLEET")

    row = new_row()
    row.update({
        "fleet_id": fleet["id"],
        "contract_id": contract["id"],
        "cars_requested": cars,
        "placement_at": placement_at,
        "release_at": release_at,
        "occupancy_end_at": occupancy_end,
        "substitution_count": 0,
        "cancellation_reason": None,
        "status": "REQUESTED",
    })
    db.freight_bookings[row["id"]] = row
    touch(fleet)
    return ok(booking_out(row), 201)


@bp.post("/grain/freight-bookings/<booking_id>/confirm")
@endpoint(["FreightCoordinator"])
def confirm_booking(actor, booking_id):
    booking = lookup("freight_bookings", booking_id)
    if booking["status"] != "REQUESTED":                                  # ladder 8
        fail("ERR_INVALID_STATE")
    apply_changes(booking, {"status": "CONFIRMED"})
    return ok(booking_out(booking))


@bp.post("/grain/freight-bookings/<booking_id>/substitute")
@endpoint(["FreightCoordinator"])
def substitute_booking(actor, booking_id):
    booking = lookup("freight_bookings", booking_id)                      # ladder 3
    payload = guard_payload(body())
    fleet = lookup_fk(payload, "new_fleet_id", "rail_fleets")             # ladder 4
    if fleet is None:
        fail("ERR_INVALID_REQUEST")
    if booking["status"] != "REQUESTED":                                  # ladder 8
        fail("ERR_INVALID_STATE")

    contract = db.purchase_contracts.get(booking["contract_id"])
    location = db.elevator_locations.get(contract["location_id"])
    if not location["rail_served"] or fleet["home_location_id"] != location["id"]:
        fail("ERR_LOCATION_NOT_RAIL_SERVED")                              # ladder 16

    if _intersects(fleet["id"], booking["placement_at"],                  # ladder 27
                   booking["occupancy_end_at"], exclude_id=booking["id"]):
        fail("ERR_FLEET_UNAVAILABLE")
    if booking["cars_requested"] > fleet["car_count"]:                    # ladder 32
        fail("ERR_CARS_EXCEED_FLEET")

    apply_changes(booking, {
        "fleet_id": fleet["id"],
        "substitution_count": booking["substitution_count"] + 1,
    })
    touch(fleet)
    return ok(booking_out(booking))


@bp.post("/grain/freight-bookings/<booking_id>/cancel")
@endpoint(["FreightCoordinator"])
def cancel_booking(actor, booking_id):
    booking = lookup("freight_bookings", booking_id)
    payload = guard_payload(body())
    reason = req_str(payload, "cancellation_reason")                      # ladder 5
    if booking["status"] not in ("REQUESTED", "CONFIRMED"):               # ladder 8
        fail("ERR_INVALID_STATE")
    apply_changes(booking, {"status": "CANCELLED", "cancellation_reason": reason})
    return ok(booking_out(booking))


@bp.get("/grain/freight-bookings")
@endpoint(ALL_ROLES)
def list_bookings(actor):
    rows = list(db.freight_bookings.values())
    for field in ("fleet_id", "contract_id", "status"):
        value = request.args.get(field)
        if value:
            rows = [r for r in rows if r[field] == value]
    return paged(sort_rows(rows), booking_out)


@bp.get("/grain/freight-bookings/<booking_id>")
@endpoint(ALL_ROLES)
def read_booking(actor, booking_id):
    return ok(booking_out(lookup("freight_bookings", booking_id)))
