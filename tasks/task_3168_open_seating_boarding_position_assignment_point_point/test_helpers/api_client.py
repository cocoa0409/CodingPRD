"""API client: one method per endpoint in the PRD's endpoint table (§4).

All paths are mounted under the /ops prefix.
"""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/ops"


class ApiClient(GenericApiClient):

    # ─── Logical clock ────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ─── Station ──────────────────────────────────────
    def create_station(self, payload, headers):
        return self._request("POST", f"{PREFIX}/stations", payload, headers)

    def get_station(self, station_id, headers):
        return self._request("GET", f"{PREFIX}/stations/{station_id}",
                             headers=headers)

    def list_stations(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/stations", headers=headers,
                             params=params)

    def set_station_status(self, station_id, action, headers):
        return self._request("POST", f"{PREFIX}/stations/{station_id}/status",
                             {"action": action}, headers)

    # ─── FareClass ────────────────────────────────────
    def create_fare_class(self, payload, headers):
        return self._request("POST", f"{PREFIX}/fare-classes", payload, headers)

    def get_fare_class(self, fare_class_id, headers):
        return self._request("GET", f"{PREFIX}/fare-classes/{fare_class_id}",
                             headers=headers)

    def list_fare_classes(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/fare-classes", headers=headers,
                             params=params)

    # ─── Passenger ────────────────────────────────────
    def create_passenger(self, payload, headers):
        return self._request("POST", f"{PREFIX}/passengers", payload, headers)

    def get_passenger(self, passenger_id, headers):
        return self._request("GET", f"{PREFIX}/passengers/{passenger_id}",
                             headers=headers)

    # ─── Aircraft ─────────────────────────────────────
    def create_aircraft(self, payload, headers):
        return self._request("POST", f"{PREFIX}/aircraft", payload, headers)

    def get_aircraft(self, aircraft_id, headers):
        return self._request("GET", f"{PREFIX}/aircraft/{aircraft_id}",
                             headers=headers)

    def list_aircraft(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/aircraft", headers=headers,
                             params=params)

    def set_aircraft_maintenance(self, aircraft_id, action, headers):
        return self._request("POST",
                             f"{PREFIX}/aircraft/{aircraft_id}/maintenance",
                             {"action": action}, headers)

    # ─── CrewMember ───────────────────────────────────
    def create_crew_member(self, payload, headers):
        return self._request("POST", f"{PREFIX}/crew-members", payload, headers)

    def get_crew_member(self, crew_member_id, headers):
        return self._request("GET", f"{PREFIX}/crew-members/{crew_member_id}",
                             headers=headers)

    def set_crew_availability(self, crew_member_id, action, headers):
        return self._request(
            "POST", f"{PREFIX}/crew-members/{crew_member_id}/availability",
            {"action": action}, headers)

    # ─── FlightLeg ────────────────────────────────────
    def create_flight_leg(self, payload, headers):
        return self._request("POST", f"{PREFIX}/flight-legs", payload, headers)

    def get_flight_leg(self, leg_id, headers):
        return self._request("GET", f"{PREFIX}/flight-legs/{leg_id}",
                             headers=headers)

    def list_flight_legs(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/flight-legs", headers=headers,
                             params=params)

    def list_leg_journeys(self, leg_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/flight-legs/{leg_id}/journeys",
                             headers=headers, params=params)

    def list_leg_boarding_assignments(self, leg_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/flight-legs/{leg_id}/boarding-assignments",
            headers=headers, params=params)

    def list_leg_disruptions(self, leg_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/flight-legs/{leg_id}/disruptions",
            headers=headers, params=params)

    def post_disruption(self, leg_id, payload, headers):
        return self._request("POST",
                             f"{PREFIX}/flight-legs/{leg_id}/disruptions",
                             payload, headers)

    def open_boarding(self, leg_id, headers):
        return self._request("POST",
                             f"{PREFIX}/flight-legs/{leg_id}/boarding/open",
                             {}, headers)

    def no_show_sweep(self, leg_id, headers):
        return self._request("POST",
                             f"{PREFIX}/flight-legs/{leg_id}/no-show-sweep",
                             {}, headers)

    def depart_leg(self, leg_id, headers):
        return self._request("POST", f"{PREFIX}/flight-legs/{leg_id}/depart",
                             {}, headers)

    def arrive_leg(self, leg_id, headers):
        return self._request("POST", f"{PREFIX}/flight-legs/{leg_id}/arrive",
                             {}, headers)

    def leg_check_in(self, leg_id, payload, headers):
        return self._request("POST",
                             f"{PREFIX}/flight-legs/{leg_id}/check-ins",
                             payload, headers)

    def purchase_upgrade(self, leg_id, payload, headers):
        return self._request("POST",
                             f"{PREFIX}/flight-legs/{leg_id}/upgrades",
                             payload, headers)

    def get_turn_projection(self, leg_id, headers):
        return self._request("GET",
                             f"{PREFIX}/flight-legs/{leg_id}/turn-projection",
                             headers=headers)

    def get_staffing_check(self, leg_id, headers):
        return self._request("GET",
                             f"{PREFIX}/flight-legs/{leg_id}/staffing-check",
                             headers=headers)

    # ─── AircraftRouting ──────────────────────────────
    def create_routing(self, payload, headers):
        return self._request("POST", f"{PREFIX}/aircraft-routings", payload,
                             headers)

    def get_routing(self, routing_id, headers):
        return self._request("GET",
                             f"{PREFIX}/aircraft-routings/{routing_id}",
                             headers=headers)

    def list_routings(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/aircraft-routings",
                             headers=headers, params=params)

    # ─── CrewPairing ──────────────────────────────────
    def create_pairing(self, payload, headers):
        return self._request("POST", f"{PREFIX}/crew-pairings", payload,
                             headers)

    def get_pairing(self, pairing_id, headers):
        return self._request("GET", f"{PREFIX}/crew-pairings/{pairing_id}",
                             headers=headers)

    def list_pairings(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/crew-pairings", headers=headers,
                             params=params)

    # ─── Booking / PassengerJourney ───────────────────
    def create_booking(self, payload, headers):
        return self._request("POST", f"{PREFIX}/bookings", payload, headers)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"{PREFIX}/bookings/{booking_id}",
                             headers=headers)

    def list_booking_journeys(self, booking_id, headers, params=None):
        return self._request("GET",
                             f"{PREFIX}/bookings/{booking_id}/journeys",
                             headers=headers, params=params)

    def get_journey(self, journey_id, headers):
        return self._request("GET", f"{PREFIX}/journeys/{journey_id}",
                             headers=headers)

    def list_journeys(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/journeys", headers=headers,
                             params=params)

    def list_journey_assignments(self, journey_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/journeys/{journey_id}/boarding-assignments",
            headers=headers, params=params)

    def list_journey_upgrades(self, journey_id, headers, params=None):
        return self._request("GET",
                             f"{PREFIX}/journeys/{journey_id}/upgrades",
                             headers=headers, params=params)

    def list_journey_bags(self, journey_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/journeys/{journey_id}/bags",
                             headers=headers, params=params)

    def journey_check_in(self, journey_id, headers):
        return self._request("POST",
                             f"{PREFIX}/journeys/{journey_id}/check-in",
                             {}, headers)

    def cancel_journey(self, journey_id, headers):
        return self._request("POST",
                             f"{PREFIX}/journeys/{journey_id}/cancel",
                             {}, headers)

    def change_journey(self, journey_id, payload, headers):
        return self._request("POST",
                             f"{PREFIX}/journeys/{journey_id}/change",
                             payload, headers)

    def check_bag(self, journey_id, payload, headers):
        return self._request("POST", f"{PREFIX}/journeys/{journey_id}/bags",
                             payload, headers)

    # ─── Bag ──────────────────────────────────────────
    def get_bag(self, bag_id, headers):
        return self._request("GET", f"{PREFIX}/bags/{bag_id}", headers=headers)

    def list_bags(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/bags", headers=headers,
                             params=params)

    def offload_bag(self, bag_id, headers):
        return self._request("POST", f"{PREFIX}/bags/{bag_id}/offload",
                             {}, headers)

    # ─── Boarding scan / assignments / upgrades ───────
    def scan_boarding(self, journey_id, headers):
        return self._request("POST", f"{PREFIX}/boarding/scan",
                             {"journey_id": journey_id}, headers)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET",
                             f"{PREFIX}/boarding-assignments/{assignment_id}",
                             headers=headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/boarding-assignments",
                             headers=headers, params=params)

    def get_upgrade(self, upgrade_id, headers):
        return self._request("GET",
                             f"{PREFIX}/boarding-upgrades/{upgrade_id}",
                             headers=headers)

    def list_upgrades(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/boarding-upgrades",
                             headers=headers, params=params)

    def refund_upgrade(self, upgrade_id, headers):
        return self._request("POST",
                             f"{PREFIX}/boarding-upgrades/{upgrade_id}/refund",
                             {}, headers)

    # ─── TravelCredit / CreditRedemption ──────────────
    def get_credit(self, credit_id, headers):
        return self._request("GET", f"{PREFIX}/credits/{credit_id}",
                             headers=headers)

    def list_credits(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/credits", headers=headers,
                             params=params)

    def redeem_credit(self, credit_id, payload, headers):
        return self._request("POST", f"{PREFIX}/credits/{credit_id}/redeem",
                             payload, headers)

    def void_credit(self, credit_id, headers):
        return self._request("POST", f"{PREFIX}/credits/{credit_id}/void",
                             {}, headers)

    def list_credit_redemptions(self, credit_id, headers, params=None):
        return self._request("GET",
                             f"{PREFIX}/credits/{credit_id}/redemptions",
                             headers=headers, params=params)

    def get_redemption(self, redemption_id, headers):
        return self._request("GET",
                             f"{PREFIX}/credit-redemptions/{redemption_id}",
                             headers=headers)

    def list_redemptions(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/credit-redemptions",
                             headers=headers, params=params)

    # ─── DisruptionEvent ──────────────────────────────
    def get_disruption_event(self, event_id, headers):
        return self._request("GET",
                             f"{PREFIX}/disruption-events/{event_id}",
                             headers=headers)

    def list_disruption_events(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/disruption-events",
                             headers=headers, params=params)


api_client = ApiClient()
