"""Flask application entry point."""
from __future__ import annotations

import os

from flask import Flask

import routes
from db import db
from errors import ApiError, err_not_found
from utils import error_body

app = Flask(__name__)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return error_body(exc)


@app.errorhandler(404)
def handle_404(e):
    return error_body(err_not_found("route not found"))


@app.errorhandler(405)
def handle_405(e):
    return error_body(err_not_found("method not allowed"))


@app.errorhandler(Exception)
def handle_generic(e):
    if isinstance(e, ApiError):
        return error_body(e)
    app.logger.exception("unhandled error")
    return error_body(ApiError("ERR_VALIDATION", 500, str(e)))


P = "/ops"

# Stations
app.add_url_rule(f"{P}/stations", "create_station", routes.create_station, methods=["POST"])
app.add_url_rule(f"{P}/stations", "list_stations", routes.list_stations, methods=["GET"])
app.add_url_rule(f"{P}/stations/<station_id>", "get_station", routes.get_station, methods=["GET"])
app.add_url_rule(f"{P}/stations/<station_id>/status", "station_status", routes.station_status, methods=["POST"])

# Fare classes
app.add_url_rule(f"{P}/fare-classes", "create_fare_class", routes.create_fare_class, methods=["POST"])
app.add_url_rule(f"{P}/fare-classes", "list_fare_classes", routes.list_fare_classes, methods=["GET"])
app.add_url_rule(f"{P}/fare-classes/<fare_class_id>", "get_fare_class", routes.get_fare_class, methods=["GET"])

# Passengers
app.add_url_rule(f"{P}/passengers", "create_passenger", routes.create_passenger, methods=["POST"])
app.add_url_rule(f"{P}/passengers/<passenger_id>", "get_passenger", routes.get_passenger, methods=["GET"])

# Aircraft
app.add_url_rule(f"{P}/aircraft", "create_aircraft", routes.create_aircraft, methods=["POST"])
app.add_url_rule(f"{P}/aircraft", "list_aircraft", routes.list_aircraft, methods=["GET"])
app.add_url_rule(f"{P}/aircraft/<aircraft_id>", "get_aircraft", routes.get_aircraft, methods=["GET"])
app.add_url_rule(f"{P}/aircraft/<aircraft_id>/maintenance", "aircraft_maintenance", routes.aircraft_maintenance, methods=["POST"])

# Crew members
app.add_url_rule(f"{P}/crew-members", "create_crew_member", routes.create_crew_member, methods=["POST"])
app.add_url_rule(f"{P}/crew-members/<crew_member_id>", "get_crew_member", routes.get_crew_member, methods=["GET"])
app.add_url_rule(f"{P}/crew-members/<crew_member_id>/availability", "crew_availability", routes.crew_availability, methods=["POST"])

# Flight legs
app.add_url_rule(f"{P}/flight-legs", "create_flight_leg", routes.create_flight_leg, methods=["POST"])
app.add_url_rule(f"{P}/flight-legs", "list_flight_legs", routes.list_flight_legs, methods=["GET"])
app.add_url_rule(f"{P}/flight-legs/<leg_id>", "get_flight_leg", routes.get_flight_leg, methods=["GET"])
app.add_url_rule(f"{P}/flight-legs/<leg_id>/journeys", "leg_journeys", routes.leg_journeys, methods=["GET"])
app.add_url_rule(f"{P}/flight-legs/<leg_id>/boarding-assignments", "leg_boarding_assignments", routes.leg_boarding_assignments, methods=["GET"])
app.add_url_rule(f"{P}/flight-legs/<leg_id>/disruptions", "leg_disruptions", routes.leg_disruptions, methods=["GET"])
app.add_url_rule(f"{P}/flight-legs/<leg_id>/disruptions", "post_disruption", routes.post_disruption, methods=["POST"])
app.add_url_rule(f"{P}/flight-legs/<leg_id>/boarding/open", "boarding_open", routes.boarding_open, methods=["POST"])
app.add_url_rule(f"{P}/flight-legs/<leg_id>/no-show-sweep", "no_show_sweep", routes.no_show_sweep, methods=["POST"])
app.add_url_rule(f"{P}/flight-legs/<leg_id>/depart", "depart_leg", routes.depart_leg, methods=["POST"])
app.add_url_rule(f"{P}/flight-legs/<leg_id>/arrive", "arrive_leg", routes.arrive_leg, methods=["POST"])
app.add_url_rule(f"{P}/flight-legs/<leg_id>/check-ins", "leg_check_in", routes.leg_check_in, methods=["POST"])
app.add_url_rule(f"{P}/flight-legs/<leg_id>/upgrades", "leg_upgrade_purchase", routes.leg_upgrade_purchase, methods=["POST"])
app.add_url_rule(f"{P}/flight-legs/<leg_id>/turn-projection", "turn_projection_route", routes.turn_projection_route, methods=["GET"])
app.add_url_rule(f"{P}/flight-legs/<leg_id>/staffing-check", "staffing_check_route", routes.staffing_check_route, methods=["GET"])

# Routings / pairings
app.add_url_rule(f"{P}/aircraft-routings", "create_routing", routes.create_routing, methods=["POST"])
app.add_url_rule(f"{P}/aircraft-routings", "list_routings", routes.list_routings, methods=["GET"])
app.add_url_rule(f"{P}/aircraft-routings/<routing_id>", "get_routing", routes.get_routing, methods=["GET"])
app.add_url_rule(f"{P}/crew-pairings", "create_pairing", routes.create_pairing, methods=["POST"])
app.add_url_rule(f"{P}/crew-pairings", "list_pairings", routes.list_pairings, methods=["GET"])
app.add_url_rule(f"{P}/crew-pairings/<pairing_id>", "get_pairing", routes.get_pairing, methods=["GET"])

# Bookings / journeys
app.add_url_rule(f"{P}/bookings", "create_booking", routes.create_booking, methods=["POST"])
app.add_url_rule(f"{P}/bookings/<booking_id>", "get_booking", routes.get_booking, methods=["GET"])
app.add_url_rule(f"{P}/bookings/<booking_id>/journeys", "booking_journeys", routes.booking_journeys, methods=["GET"])
app.add_url_rule(f"{P}/journeys", "list_journeys", routes.list_journeys, methods=["GET"])
app.add_url_rule(f"{P}/journeys/<journey_id>", "get_journey_route", routes.get_journey_route, methods=["GET"])
app.add_url_rule(f"{P}/journeys/<journey_id>/boarding-assignments", "journey_assignments", routes.journey_assignments, methods=["GET"])
app.add_url_rule(f"{P}/journeys/<journey_id>/upgrades", "journey_upgrades", routes.journey_upgrades, methods=["GET"])
app.add_url_rule(f"{P}/journeys/<journey_id>/bags", "journey_bags", routes.journey_bags, methods=["GET"])
app.add_url_rule(f"{P}/journeys/<journey_id>/bags", "accept_bag", routes.accept_bag, methods=["POST"])
app.add_url_rule(f"{P}/journeys/<journey_id>/check-in", "journey_check_in", routes.journey_check_in, methods=["POST"])
app.add_url_rule(f"{P}/journeys/<journey_id>/cancel", "cancel_journey_route", routes.cancel_journey_route, methods=["POST"])
app.add_url_rule(f"{P}/journeys/<journey_id>/change", "change_journey_route", routes.change_journey_route, methods=["POST"])

# Bags
app.add_url_rule(f"{P}/bags", "list_bags", routes.list_bags, methods=["GET"])
app.add_url_rule(f"{P}/bags/<bag_id>", "get_bag", routes.get_bag, methods=["GET"])
app.add_url_rule(f"{P}/bags/<bag_id>/offload", "offload_bag", routes.offload_bag, methods=["POST"])

# Boarding scan
app.add_url_rule(f"{P}/boarding/scan", "boarding_scan", routes.boarding_scan, methods=["POST"])

# Upgrades
app.add_url_rule(f"{P}/boarding-upgrades", "list_upgrades", routes.list_upgrades, methods=["GET"])
app.add_url_rule(f"{P}/boarding-upgrades/<upgrade_id>", "get_upgrade", routes.get_upgrade, methods=["GET"])
app.add_url_rule(f"{P}/boarding-upgrades/<upgrade_id>/refund", "refund_upgrade", routes.refund_upgrade, methods=["POST"])

# Credits
app.add_url_rule(f"{P}/credits", "list_credits", routes.list_credits, methods=["GET"])
app.add_url_rule(f"{P}/credits/<credit_id>", "get_credit", routes.get_credit, methods=["GET"])
app.add_url_rule(f"{P}/credits/<credit_id>/redeem", "redeem_credit", routes.redeem_credit, methods=["POST"])
app.add_url_rule(f"{P}/credits/<credit_id>/void", "void_credit", routes.void_credit, methods=["POST"])
app.add_url_rule(f"{P}/credits/<credit_id>/redemptions", "credit_redemptions_list", routes.credit_redemptions_list, methods=["GET"])
app.add_url_rule(f"{P}/credit-redemptions", "list_redemptions", routes.list_redemptions, methods=["GET"])
app.add_url_rule(f"{P}/credit-redemptions/<redemption_id>", "get_redemption", routes.get_redemption, methods=["GET"])

# Assignments / disruption events
app.add_url_rule(f"{P}/boarding-assignments", "list_assignments", routes.list_assignments, methods=["GET"])
app.add_url_rule(f"{P}/boarding-assignments/<assignment_id>", "get_assignment", routes.get_assignment, methods=["GET"])
app.add_url_rule(f"{P}/disruption-events", "list_disruption_events", routes.list_disruption_events, methods=["GET"])
app.add_url_rule(f"{P}/disruption-events/<event_id>", "get_disruption_event", routes.get_disruption_event, methods=["GET"])

# Clock
app.add_url_rule(f"{P}/_clock/set_current_utc", "set_clock", routes.set_clock, methods=["POST"])


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
