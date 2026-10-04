"""Bookings, package bundles, ancillaries."""

from flask import Blueprint, request

import db
from common import (
    new_entity,
    get_or_404,
    body,
    require_field,
    require_enum,
    require_positive_int,
    check_occ,
    touch,
    parse_date,
)
from errors import ApiError
from middleware import require_role, require_any_authenticated
from response import ok, paginate
from routes.flight_instances import _get_flight_or_404
from routes.supplier_offers import _get_offer_or_404

bp = Blueprint("bookings", __name__)

BOOKING_KINDS = {"AIR_ONLY", "PACKAGE"}
ANCILLARY_KINDS = {
    "SEAT_ASSIGNMENT",
    "CHECKED_BAG",
    "CARRY_ON_BAG",
    "PRIORITY_BOARDING",
}
BUNDLE_SLOT_KINDS = {
    "hotel_offer_id": "HOTEL",
    "rental_car_offer_id": "RENTAL_CAR",
    "attraction_offer_id": "ATTRACTION_TICKET",
}


def _get_booking_or_404(booking_id):
    return get_or_404(db.bookings, booking_id, "ERR_BOOKING_NOT_FOUND", "Booking")


def _get_bundle_or_404(bundle_id):
    return get_or_404(
        db.package_bundles, bundle_id, "ERR_BUNDLE_NOT_FOUND", "PackageBundle"
    )


def _get_ancillary_or_404(purchase_id):
    return get_or_404(
        db.ancillary_purchases,
        purchase_id,
        "ERR_ANCILLARY_NOT_FOUND",
        "AncillaryPurchase",
    )


def _recompute_seats_sold(flight):
    count = 0
    for b in db.bookings.values():
        if b["flight_instance_id"] == flight["id"] and b["booking_status"] in (
            "CONFIRMED",
            "STRANDED",
            "STRANDED_REBOOKED",
        ):
            count += b["passenger_count"]
    flight["seats_sold"] = count


def _recompute_ancillary_total(booking):
    total = 0
    for p in db.ancillary_purchases.values():
        if p["booking_id"] == booking["id"] and p["purchase_status"] == "ACTIVE":
            total += p["amount_cents"]
    booking["ancillary_total_cents"] = total


def _apply_bundle_cancellation_clawback(bundle):
    """For each supplier consumed by the bundle, find covering PROVISIONAL
    settlements and increment clawback + set CLAWED_BACK."""
    booking = db.bookings.get(bundle["booking_id"])
    if booking is None:
        return
    flight = db.flight_instances.get(booking["flight_instance_id"])
    if flight is None:
        return
    flight_date = flight["flight_date"]

    supplier_net_costs = {}
    for field in ("hotel_offer_id", "rental_car_offer_id", "attraction_offer_id"):
        offer_id = bundle.get(field)
        if not offer_id:
            continue
        offer = db.supplier_offers.get(offer_id)
        if offer is None:
            continue
        supplier_net_costs[offer["supplier_code"]] = (
            supplier_net_costs.get(offer["supplier_code"], 0)
            + offer["net_cost_cents"]
        )

    for settlement in db.supplier_settlements.values():
        if settlement["settlement_status"] != "PROVISIONAL":
            continue
        supplier_code = settlement["supplier_code"]
        if supplier_code not in supplier_net_costs:
            continue
        if not (
            settlement["period_start_date"]
            <= flight_date
            <= settlement["period_end_date"]
        ):
            continue
        settlement["clawback_cents"] = settlement.get("clawback_cents", 0) + supplier_net_costs[supplier_code]
        settlement["settlement_status"] = "CLAWED_BACK"
        touch(settlement)


def _maybe_recover_disruption(disruption_id):
    """When every booking stranded by a disruption is rebooked or cancelled,
    the disruption moves to RECOVERED."""
    dis = db.disruption_events.get(disruption_id)
    if dis is None or dis["disruption_status"] != "DECLARED":
        return
    flight_id = dis["flight_instance_id"]
    for b in db.bookings.values():
        if b.get("_stranded_by_disruption_id") == disruption_id and b[
            "booking_status"
        ] not in ("STRANDED_REBOOKED", "CANCELLED"):
            return
    dis["disruption_status"] = "RECOVERED"
    touch(dis)


def _cancel_booking(booking):
    """Cancel a booking with all cascades: ancillaries, bundle, clawback, seats."""
    if booking["booking_status"] not in (
        "CONFIRMED",
        "STRANDED",
        "STRANDED_REBOOKED",
    ):
        raise ApiError(
            "ERR_BOOKING_NOT_CANCELLABLE",
            "Cancel requires CONFIRMED, STRANDED, or STRANDED_REBOOKED booking",
            409,
        )

    old_flight_id = booking["flight_instance_id"]

    booking["booking_status"] = "CANCELLED"
    touch(booking)

    for p in db.ancillary_purchases.values():
        if p["booking_id"] == booking["id"] and p["purchase_status"] == "ACTIVE":
            p["purchase_status"] = "VOIDED"
            touch(p)
    _recompute_ancillary_total(booking)

    if booking.get("package_bundle_id"):
        bundle = db.package_bundles.get(booking["package_bundle_id"])
        if bundle is not None and bundle["bundle_status"] == "ACTIVE":
            bundle["bundle_status"] = "CANCELLED"
            touch(bundle)
            _apply_bundle_cancellation_clawback(bundle)

    flight = db.flight_instances.get(old_flight_id)
    if flight is not None:
        _recompute_seats_sold(flight)
        touch(flight)

    dis_id = booking.get("_stranded_by_disruption_id")
    if dis_id:
        _maybe_recover_disruption(dis_id)


@bp.route("/bookings", methods=["POST"])
def create_booking():
    require_role("CustomerService")
    data = body()
    flight_id = require_field(data, "flight_instance_id", str)
    flight = db.flight_instances.get(flight_id)
    if flight is None:
        raise ApiError("ERR_FLIGHT_NOT_FOUND", "FlightInstance id does not exist", 404)
    passenger_count = require_positive_int(data, "passenger_count", minimum=1)
    kind = require_enum(data, "booking_kind", BOOKING_KINDS)

    if flight["flight_status"] != "SCHEDULED":
        raise ApiError(
            "ERR_FLIGHT_NOT_SCHEDULED",
            "Operation requires SCHEDULED flight",
            409,
        )

    route = db.routes.get(flight["route_id"])

    bundle_fields = {}
    if kind == "PACKAGE":
        for slot_field in ("hotel_offer_id", "rental_car_offer_id", "attraction_offer_id"):
            offer_id = data.get(slot_field)
            if offer_id is None:
                if slot_field == "hotel_offer_id":
                    raise ApiError(
                        "ERR_VALIDATION",
                        "hotel_offer_id is required for PACKAGE bookings",
                        422,
                    )
                bundle_fields[slot_field] = None
                continue
            offer = db.supplier_offers.get(offer_id)
            if offer is None:
                raise ApiError(
                    "ERR_OFFER_NOT_FOUND", "SupplierOffer id does not exist", 404
                )
            expected_kind = BUNDLE_SLOT_KINDS[slot_field]
            if offer["component_kind"] != expected_kind:
                raise ApiError(
                    "ERR_OFFER_WRONG_KIND",
                    "SupplierOffer component_kind does not match the bundle slot",
                    422,
                )
            if offer["destination_station_id"] != route["destination_station_id"]:
                raise ApiError(
                    "ERR_OFFER_WRONG_DESTINATION",
                    "SupplierOffer destination station differs from the route destination",
                    422,
                )
            if offer["offer_status"] != "OPEN":
                raise ApiError(
                    "ERR_OFFER_NOT_OPEN", "SupplierOffer not OPEN", 422
                )
            bundle_fields[slot_field] = offer_id

    # OCC — checked last
    check_occ(data, "expected_flight_version", flight)

    base_fare_total = passenger_count * route["base_fare_cents"]

    booking = new_entity(
        {
            "flight_instance_id": flight_id,
            "passenger_count": passenger_count,
            "booking_kind": kind,
            "base_fare_total_cents": base_fare_total,
            "ancillary_total_cents": 0,
            "package_bundle_id": None,
            "stranded_until_date": None,
            "booking_status": "CONFIRMED",
        }
    )
    db.bookings[booking["id"]] = booking

    if kind == "PACKAGE":
        price = 0
        for slot_field in ("hotel_offer_id", "rental_car_offer_id", "attraction_offer_id"):
            offer_id = bundle_fields.get(slot_field)
            if offer_id:
                offer = db.supplier_offers[offer_id]
                price += offer["sell_price_cents"]
        bundle = new_entity(
            {
                "booking_id": booking["id"],
                "hotel_offer_id": bundle_fields.get("hotel_offer_id"),
                "rental_car_offer_id": bundle_fields.get("rental_car_offer_id"),
                "attraction_offer_id": bundle_fields.get("attraction_offer_id"),
                "bundle_price_cents": price,
                "bundle_status": "ACTIVE",
            }
        )
        db.package_bundles[bundle["id"]] = bundle
        booking["package_bundle_id"] = bundle["id"]
        touch(booking)

    flight["seats_sold"] = flight.get("seats_sold", 0) + passenger_count
    touch(flight)

    return ok(booking, 201)


@bp.route("/bookings", methods=["GET"])
def list_bookings():
    require_any_authenticated()
    items = list(db.bookings.values())
    fid = request.args.get("flight_instance_id")
    if fid:
        items = [b for b in items if b["flight_instance_id"] == fid]
    bid = request.args.get("package_bundle_id")
    if bid:
        items = [b for b in items if b["package_bundle_id"] == bid]
    status = request.args.get("booking_status")
    if status:
        items = [b for b in items if b["booking_status"] == status]
    kind = request.args.get("booking_kind")
    if kind:
        items = [b for b in items if b["booking_kind"] == kind]
    items.sort(key=lambda b: (b["created_at"], b["id"]))
    page, meta = paginate(items)
    return ok(page, 200, pagination=meta)


@bp.route("/bookings/<booking_id>", methods=["GET"])
def get_booking(booking_id):
    require_any_authenticated()
    ent = _get_booking_or_404(booking_id)
    return ok(ent)


@bp.route("/bookings/<booking_id>/rebook", methods=["POST"])
def rebook_booking(booking_id):
    require_role("CustomerService")
    booking = _get_booking_or_404(booking_id)
    if booking["booking_status"] != "STRANDED":
        raise ApiError(
            "ERR_BOOKING_NOT_STRANDED",
            "Rebook requires STRANDED booking",
            409,
        )
    data = body()
    target_id = require_field(data, "target_flight_instance_id", str)
    target = db.flight_instances.get(target_id)
    if target is None:
        raise ApiError("ERR_FLIGHT_NOT_FOUND", "FlightInstance id does not exist", 404)

    original_flight = db.flight_instances.get(booking["flight_instance_id"])
    if (
        target["flight_status"] != "SCHEDULED"
        or target["route_id"] != original_flight["route_id"]
    ):
        raise ApiError(
            "ERR_REBOOK_FLIGHT_INVALID",
            "Rebook target not SCHEDULED on the same route",
            409,
        )
    if target["aircraft_id"] is None:
        raise ApiError(
            "ERR_REBOOK_NO_AIRCRAFT",
            "Rebook target has no aircraft assigned",
            409,
        )
    aircraft = db.aircraft.get(target["aircraft_id"])
    projected = target["seats_sold"] + booking["passenger_count"]
    if aircraft is not None and projected > aircraft["seat_capacity"]:
        raise ApiError(
            "ERR_REBOOK_CAPACITY_EXCEEDED",
            "Rebook would exceed aircraft seat_capacity",
            409,
        )

    # OCC — checked last
    check_occ(data, "expected_booking_version", booking)

    old_flight_id = booking["flight_instance_id"]
    booking["flight_instance_id"] = target_id
    booking["stranded_until_date"] = None
    booking["booking_status"] = "STRANDED_REBOOKED"
    touch(booking)

    old_flight = db.flight_instances.get(old_flight_id)
    if old_flight is not None:
        _recompute_seats_sold(old_flight)
        touch(old_flight)
    _recompute_seats_sold(target)
    touch(target)

    dis_id = booking.get("_stranded_by_disruption_id")
    if dis_id:
        _maybe_recover_disruption(dis_id)

    return ok(booking)


@bp.route("/bookings/<booking_id>/cancel", methods=["POST"])
def cancel_booking(booking_id):
    require_role("CustomerService")
    booking = _get_booking_or_404(booking_id)
    _cancel_booking(booking)
    return ok(booking)


@bp.route("/bookings/<booking_id>/bundle", methods=["GET"])
def get_booking_bundle(booking_id):
    require_any_authenticated()
    booking = _get_booking_or_404(booking_id)
    bundle_id = booking.get("package_bundle_id")
    if bundle_id and bundle_id in db.package_bundles:
        return ok([db.package_bundles[bundle_id]])
    return ok([])


@bp.route("/package-bundles", methods=["GET"])
def list_bundles():
    require_any_authenticated()
    items = list(db.package_bundles.values())
    bid = request.args.get("booking_id")
    if bid:
        items = [b for b in items if b["booking_id"] == bid]
    hid = request.args.get("hotel_offer_id")
    if hid:
        items = [b for b in items if b["hotel_offer_id"] == hid]
    rid = request.args.get("rental_car_offer_id")
    if rid:
        items = [b for b in items if b["rental_car_offer_id"] == rid]
    aid = request.args.get("attraction_offer_id")
    if aid:
        items = [b for b in items if b["attraction_offer_id"] == aid]
    status = request.args.get("bundle_status")
    if status:
        items = [b for b in items if b["bundle_status"] == status]
    items.sort(key=lambda b: (b["created_at"], b["id"]))
    page, meta = paginate(items)
    return ok(page, 200, pagination=meta)


@bp.route("/package-bundles/<bundle_id>", methods=["GET"])
def get_bundle(bundle_id):
    require_any_authenticated()
    ent = _get_bundle_or_404(bundle_id)
    return ok(ent)


@bp.route("/bookings/<booking_id>/ancillaries", methods=["POST"])
def create_ancillary(booking_id):
    require_role("CustomerService")
    booking = _get_booking_or_404(booking_id)
    data = body()
    kind = require_enum(data, "ancillary_kind", ANCILLARY_KINDS)
    amount = require_positive_int(data, "amount_cents", minimum=1)
    ent = new_entity(
        {
            "booking_id": booking_id,
            "ancillary_kind": kind,
            "amount_cents": amount,
            "purchase_status": "ACTIVE",
        }
    )
    db.ancillary_purchases[ent["id"]] = ent
    _recompute_ancillary_total(booking)
    touch(booking)
    return ok(ent, 201)


@bp.route("/bookings/<booking_id>/ancillaries", methods=["GET"])
def list_ancillaries(booking_id):
    require_any_authenticated()
    _get_booking_or_404(booking_id)
    items = [
        p for p in db.ancillary_purchases.values() if p["booking_id"] == booking_id
    ]
    status = request.args.get("purchase_status")
    if status:
        items = [p for p in items if p["purchase_status"] == status]
    items.sort(key=lambda p: (p["created_at"], p["id"]))
    page, meta = paginate(items)
    return ok(page, 200, pagination=meta)


@bp.route("/bookings/<booking_id>/ancillaries/<purchase_id>/void", methods=["POST"])
def void_ancillary(booking_id, purchase_id):
    require_role("CustomerService")
    booking = _get_booking_or_404(booking_id)
    purchase = _get_ancillary_or_404(purchase_id)
    if purchase["booking_id"] != booking_id:
        raise ApiError(
            "ERR_ANCILLARY_NOT_FOUND", "AncillaryPurchase id does not exist", 404
        )
    if purchase["purchase_status"] != "ACTIVE":
        raise ApiError(
            "ERR_ANCILLARY_NOT_ACTIVE",
            "Void requires ACTIVE ancillary",
            409,
        )
    purchase["purchase_status"] = "VOIDED"
    touch(purchase)
    _recompute_ancillary_total(booking)
    touch(booking)
    return ok(purchase)


@bp.route("/ancillary-purchases", methods=["GET"])
def list_ancillaries_flat():
    require_any_authenticated()
    items = list(db.ancillary_purchases.values())
    bid = request.args.get("booking_id")
    if bid:
        items = [p for p in items if p["booking_id"] == bid]
    status = request.args.get("purchase_status")
    if status:
        items = [p for p in items if p["purchase_status"] == status]
    kind = request.args.get("ancillary_kind")
    if kind:
        items = [p for p in items if p["ancillary_kind"] == kind]
    items.sort(key=lambda p: (p["created_at"], p["id"]))
    page, meta = paginate(items)
    return ok(page, 200, pagination=meta)


@bp.route("/ancillary-purchases/<purchase_id>", methods=["GET"])
def get_ancillary_flat(purchase_id):
    require_any_authenticated()
    ent = _get_ancillary_or_404(purchase_id)
    return ok(ent)
