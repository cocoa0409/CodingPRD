"""API client: one method per endpoint defined in the PRD (§4)."""
from typing import Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Clock (test-driving) ---
    def set_clock(self, current_utc: str, headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    # --- Station ---
    def create_station(self, payload, headers):
        return self._request("POST", "/stations", payload, headers)

    def list_stations(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/stations", headers=headers, params=params)

    def get_station(self, station_id, headers):
        return self._request("GET", f"/stations/{station_id}", headers=headers)

    # --- Route ---
    def create_route(self, payload, headers):
        return self._request("POST", "/routes", payload, headers)

    def list_routes(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/routes", headers=headers, params=params)

    def get_route(self, route_id, headers):
        return self._request("GET", f"/routes/{route_id}", headers=headers)

    def activate_route(self, route_id, headers):
        return self._request("POST", f"/routes/{route_id}/activate", {}, headers)

    def suspend_route(self, route_id, headers):
        return self._request("POST", f"/routes/{route_id}/suspend", {}, headers)

    def reactivate_route(self, route_id, headers):
        return self._request("POST", f"/routes/{route_id}/reactivate", {}, headers)

    def close_route(self, route_id, headers):
        return self._request("POST", f"/routes/{route_id}/close", {}, headers)

    # --- SeasonWindow ---
    def create_season_window(self, route_id, payload, headers):
        return self._request(
            "POST", f"/routes/{route_id}/season-windows", payload, headers
        )

    def list_season_windows(self, route_id, headers, params: Optional[Dict] = None):
        return self._request(
            "GET", f"/routes/{route_id}/season-windows", headers=headers, params=params
        )

    def get_season_window(self, route_id, window_id, headers):
        return self._request(
            "GET", f"/routes/{route_id}/season-windows/{window_id}", headers=headers
        )

    def suspend_season_window(self, route_id, window_id, headers, payload=None):
        return self._request(
            "POST",
            f"/routes/{route_id}/season-windows/{window_id}/suspend",
            payload or {},
            headers,
        )

    def close_season_window(self, route_id, window_id, headers):
        return self._request(
            "POST", f"/routes/{route_id}/season-windows/{window_id}/close", {}, headers
        )

    def list_all_season_windows(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/season-windows", headers=headers, params=params)

    def get_season_window_flat(self, window_id, headers):
        return self._request("GET", f"/season-windows/{window_id}", headers=headers)

    # --- SchedulePublication ---
    def create_publication(self, route_id, payload, headers):
        return self._request(
            "POST", f"/routes/{route_id}/publications", payload, headers
        )

    def list_publications(self, route_id, headers, params: Optional[Dict] = None):
        return self._request(
            "GET", f"/routes/{route_id}/publications", headers=headers, params=params
        )

    def get_publication(self, route_id, publication_id, headers):
        return self._request(
            "GET", f"/routes/{route_id}/publications/{publication_id}", headers=headers
        )

    def retire_publication(self, route_id, publication_id, headers):
        return self._request(
            "POST",
            f"/routes/{route_id}/publications/{publication_id}/retire",
            {},
            headers,
        )

    def list_all_publications(self, headers, params: Optional[Dict] = None):
        return self._request(
            "GET", "/schedule-publications", headers=headers, params=params
        )

    def get_publication_flat(self, publication_id, headers):
        return self._request(
            "GET", f"/schedule-publications/{publication_id}", headers=headers
        )

    # --- Aircraft ---
    def create_aircraft(self, payload, headers):
        return self._request("POST", "/aircraft", payload, headers)

    def list_aircraft(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/aircraft", headers=headers, params=params)

    def get_aircraft(self, aircraft_id, headers):
        return self._request("GET", f"/aircraft/{aircraft_id}", headers=headers)

    def retire_aircraft(self, aircraft_id, headers):
        return self._request("POST", f"/aircraft/{aircraft_id}/retire", {}, headers)

    # --- FlightInstance ---
    def list_flights(self, headers, params: Optional[Dict] = None):
        return self._request(
            "GET", "/flight-instances", headers=headers, params=params
        )

    def get_flight(self, flight_id, headers):
        return self._request(
            "GET", f"/flight-instances/{flight_id}", headers=headers
        )

    def assign_aircraft(self, flight_id, payload, headers):
        return self._request(
            "POST", f"/flight-instances/{flight_id}/assign-aircraft", payload, headers
        )

    def mark_operated(self, flight_id, headers):
        return self._request(
            "POST", f"/flight-instances/{flight_id}/mark-operated", {}, headers
        )

    # --- CrewBase / CrewMember / CrewAssignment ---
    def create_crew_base(self, payload, headers):
        return self._request("POST", "/crew-bases", payload, headers)

    def list_crew_bases(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/crew-bases", headers=headers, params=params)

    def get_crew_base(self, crew_base_id, headers):
        return self._request("GET", f"/crew-bases/{crew_base_id}", headers=headers)

    def create_crew_member(self, crew_base_id, payload, headers):
        return self._request(
            "POST", f"/crew-bases/{crew_base_id}/members", payload, headers
        )

    def list_crew_base_members(self, crew_base_id, headers, params: Optional[Dict] = None):
        return self._request(
            "GET", f"/crew-bases/{crew_base_id}/members", headers=headers, params=params
        )

    def list_crew_members(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/crew-members", headers=headers, params=params)

    def get_crew_member(self, crew_member_id, headers):
        return self._request("GET", f"/crew-members/{crew_member_id}", headers=headers)

    def create_crew_assignment(self, flight_id, payload, headers):
        return self._request(
            "POST", f"/flight-instances/{flight_id}/crew-assignments", payload, headers
        )

    def list_crew_assignments_for_flight(self, flight_id, headers, params: Optional[Dict] = None):
        return self._request(
            "GET",
            f"/flight-instances/{flight_id}/crew-assignments",
            headers=headers,
            params=params,
        )

    def release_crew_assignment(self, flight_id, assignment_id, headers):
        return self._request(
            "DELETE",
            f"/flight-instances/{flight_id}/crew-assignments/{assignment_id}",
            headers=headers,
        )

    def list_all_crew_assignments(self, headers, params: Optional[Dict] = None):
        return self._request(
            "GET", "/crew-assignments", headers=headers, params=params
        )

    def get_crew_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"/crew-assignments/{assignment_id}", headers=headers
        )

    # --- SupplierOffer ---
    def create_supplier_offer(self, payload, headers):
        return self._request("POST", "/supplier-offers", payload, headers)

    def list_supplier_offers(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/supplier-offers", headers=headers, params=params)

    def get_supplier_offer(self, offer_id, headers):
        return self._request("GET", f"/supplier-offers/{offer_id}", headers=headers)

    # --- Booking / PackageBundle / AncillaryPurchase ---
    def create_booking(self, payload, headers):
        return self._request("POST", "/bookings", payload, headers)

    def list_bookings(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/bookings", headers=headers, params=params)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/bookings/{booking_id}", headers=headers)

    def rebook_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/rebook", payload, headers)

    def cancel_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/cancel", {}, headers)

    def get_booking_bundle(self, booking_id, headers):
        return self._request("GET", f"/bookings/{booking_id}/bundle", headers=headers)

    def list_package_bundles(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/package-bundles", headers=headers, params=params)

    def get_package_bundle(self, bundle_id, headers):
        return self._request("GET", f"/package-bundles/{bundle_id}", headers=headers)

    def create_ancillary(self, booking_id, payload, headers):
        return self._request(
            "POST", f"/bookings/{booking_id}/ancillaries", payload, headers
        )

    def list_ancillaries(self, booking_id, headers, params: Optional[Dict] = None):
        return self._request(
            "GET", f"/bookings/{booking_id}/ancillaries", headers=headers, params=params
        )

    def void_ancillary(self, booking_id, purchase_id, headers):
        return self._request(
            "POST",
            f"/bookings/{booking_id}/ancillaries/{purchase_id}/void",
            {},
            headers,
        )

    def list_all_ancillaries(self, headers, params: Optional[Dict] = None):
        return self._request(
            "GET", "/ancillary-purchases", headers=headers, params=params
        )

    def get_ancillary(self, purchase_id, headers):
        return self._request(
            "GET", f"/ancillary-purchases/{purchase_id}", headers=headers
        )

    # --- DisruptionEvent ---
    def declare_disruption(self, route_id, payload, headers):
        return self._request(
            "POST", f"/routes/{route_id}/disruptions", payload, headers
        )

    def list_route_disruptions(self, route_id, headers, params: Optional[Dict] = None):
        return self._request(
            "GET", f"/routes/{route_id}/disruptions", headers=headers, params=params
        )

    def list_all_disruptions(self, headers, params: Optional[Dict] = None):
        return self._request("GET", "/disruptions", headers=headers, params=params)

    def get_disruption(self, disruption_id, headers):
        return self._request("GET", f"/disruptions/{disruption_id}", headers=headers)

    # --- SupplierSettlement ---
    def create_supplier_settlement(self, payload, headers):
        return self._request("POST", "/supplier-settlements", payload, headers)

    def list_supplier_settlements(self, headers, params: Optional[Dict] = None):
        return self._request(
            "GET", "/supplier-settlements", headers=headers, params=params
        )

    def get_supplier_settlement(self, settlement_id, headers):
        return self._request(
            "GET", f"/supplier-settlements/{settlement_id}", headers=headers
        )

    def finalize_supplier_settlement(self, settlement_id, headers):
        return self._request(
            "POST", f"/supplier-settlements/{settlement_id}/finalize", {}, headers
        )


api_client = ApiClient()
