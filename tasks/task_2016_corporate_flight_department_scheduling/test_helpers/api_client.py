"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/flight-ops/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Aircraft
    # ------------------------------------------------------------------
    def create_aircraft(self, payload, headers):
        return self._request("POST", "/flight-ops/aircraft", payload, headers)

    def list_aircraft(self, headers, params=None):
        return self._request("GET", "/flight-ops/aircraft", headers=headers, params=params)

    def get_aircraft(self, aircraft_id, headers):
        return self._request("GET", f"/flight-ops/aircraft/{aircraft_id}", headers=headers)

    def ground_aircraft(self, aircraft_id, headers):
        return self._request("POST", f"/flight-ops/aircraft/{aircraft_id}/ground", {}, headers)

    def return_aircraft_to_service(self, aircraft_id, headers):
        return self._request("POST", f"/flight-ops/aircraft/{aircraft_id}/return-to-service", {}, headers)

    def retire_aircraft(self, aircraft_id, headers):
        return self._request("POST", f"/flight-ops/aircraft/{aircraft_id}/retire", {}, headers)

    # ------------------------------------------------------------------
    # DocumentPermit
    # ------------------------------------------------------------------
    def create_document(self, aircraft_id, payload, headers):
        return self._request("POST", f"/flight-ops/aircraft/{aircraft_id}/documents", payload, headers)

    def list_documents(self, aircraft_id, headers, params=None):
        return self._request("GET", f"/flight-ops/aircraft/{aircraft_id}/documents",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # CrewMember
    # ------------------------------------------------------------------
    def create_crew_member(self, payload, headers):
        return self._request("POST", "/flight-ops/crew-members", payload, headers)

    def list_crew_members(self, headers, params=None):
        return self._request("GET", "/flight-ops/crew-members", headers=headers, params=params)

    def get_crew_member(self, crew_id, headers):
        return self._request("GET", f"/flight-ops/crew-members/{crew_id}", headers=headers)

    # ------------------------------------------------------------------
    # BusinessUnit
    # ------------------------------------------------------------------
    def create_business_unit(self, payload, headers):
        return self._request("POST", "/flight-ops/business-units", payload, headers)

    def list_business_units(self, headers, params=None):
        return self._request("GET", "/flight-ops/business-units", headers=headers, params=params)

    def get_business_unit(self, bu_id, headers):
        return self._request("GET", f"/flight-ops/business-units/{bu_id}", headers=headers)

    # ------------------------------------------------------------------
    # PassengerProfile
    # ------------------------------------------------------------------
    def create_passenger_profile(self, payload, headers):
        return self._request("POST", "/flight-ops/passenger-profiles", payload, headers)

    def list_passenger_profiles(self, headers, params=None):
        return self._request("GET", "/flight-ops/passenger-profiles", headers=headers, params=params)

    def get_passenger_profile(self, pax_id, headers):
        return self._request("GET", f"/flight-ops/passenger-profiles/{pax_id}", headers=headers)

    # ------------------------------------------------------------------
    # TripRequest
    # ------------------------------------------------------------------
    def create_trip_request(self, payload, headers):
        return self._request("POST", "/flight-ops/trip-requests", payload, headers)

    def list_trip_requests(self, headers, params=None):
        return self._request("GET", "/flight-ops/trip-requests", headers=headers, params=params)

    def get_trip_request(self, trip_id, headers):
        return self._request("GET", f"/flight-ops/trip-requests/{trip_id}", headers=headers)

    def submit_trip(self, trip_id, headers):
        return self._request("POST", f"/flight-ops/trip-requests/{trip_id}/submit", {}, headers)

    def approve_trip(self, trip_id, headers):
        return self._request("POST", f"/flight-ops/trip-requests/{trip_id}/approve", {}, headers)

    def reject_trip(self, trip_id, headers):
        return self._request("POST", f"/flight-ops/trip-requests/{trip_id}/reject", {}, headers)

    def assign_aircraft(self, trip_id, expected_trip_request_version, headers):
        return self._request("POST", f"/flight-ops/trip-requests/{trip_id}/assign-aircraft",
                             {"expected_trip_request_version": expected_trip_request_version}, headers)

    def assign_aircraft_raw(self, trip_id, payload, headers):
        """assign-aircraft with a caller-controlled body (e.g. missing version)."""
        return self._request("POST", f"/flight-ops/trip-requests/{trip_id}/assign-aircraft",
                             payload, headers)

    def dispatch_trip(self, trip_id, headers):
        return self._request("POST", f"/flight-ops/trip-requests/{trip_id}/dispatch", {}, headers)

    def cancel_trip(self, trip_id, headers):
        return self._request("POST", f"/flight-ops/trip-requests/{trip_id}/cancel", {}, headers)

    def approve_personal_use(self, trip_id, headers):
        return self._request("POST", f"/flight-ops/trip-requests/{trip_id}/approve-personal-use",
                             {}, headers)

    def settle_trip(self, trip_id, expected_trip_request_version, headers):
        return self._request("POST", f"/flight-ops/trip-requests/{trip_id}/settle",
                             {"expected_trip_request_version": expected_trip_request_version}, headers)

    def sifl_preview(self, trip_id, headers):
        return self._request("GET", f"/flight-ops/trip-requests/{trip_id}/sifl-preview",
                             headers=headers)

    # ------------------------------------------------------------------
    # FlightLeg
    # ------------------------------------------------------------------
    def create_flight_leg(self, trip_id, payload, headers):
        return self._request("POST", f"/flight-ops/trip-requests/{trip_id}/flight-legs",
                             payload, headers)

    def list_trip_flight_legs(self, trip_id, headers, params=None):
        return self._request("GET", f"/flight-ops/trip-requests/{trip_id}/flight-legs",
                             headers=headers, params=params)

    def list_flight_legs(self, headers, params=None):
        return self._request("GET", "/flight-ops/flight-legs", headers=headers, params=params)

    def get_flight_leg(self, leg_id, headers):
        return self._request("GET", f"/flight-ops/flight-legs/{leg_id}", headers=headers)

    def assign_crew(self, leg_id, pic_crew_id, sic_crew_id, headers):
        return self._request("POST", f"/flight-ops/flight-legs/{leg_id}/assign-crew",
                             {"pic_crew_id": pic_crew_id, "sic_crew_id": sic_crew_id}, headers)

    def release_leg(self, leg_id, headers):
        return self._request("POST", f"/flight-ops/flight-legs/{leg_id}/release", {}, headers)

    def complete_leg(self, leg_id, headers):
        return self._request("POST", f"/flight-ops/flight-legs/{leg_id}/complete", {}, headers)

    def cancel_leg(self, leg_id, headers):
        return self._request("POST", f"/flight-ops/flight-legs/{leg_id}/cancel", {}, headers)

    # ------------------------------------------------------------------
    # MaintenanceWindow
    # ------------------------------------------------------------------
    def create_maintenance_window(self, aircraft_id, payload, headers):
        return self._request("POST", f"/flight-ops/aircraft/{aircraft_id}/maintenance-windows",
                             payload, headers)

    def list_maintenance_windows(self, aircraft_id, headers, params=None):
        return self._request("GET", f"/flight-ops/aircraft/{aircraft_id}/maintenance-windows",
                             headers=headers, params=params)

    def cancel_maintenance_window(self, window_id, headers):
        return self._request("POST", f"/flight-ops/maintenance-windows/{window_id}/cancel",
                             {}, headers)

    def complete_maintenance_window(self, window_id, headers):
        return self._request("POST", f"/flight-ops/maintenance-windows/{window_id}/complete",
                             {}, headers)

    # ------------------------------------------------------------------
    # CateringOrder
    # ------------------------------------------------------------------
    def create_catering_order(self, leg_id, payload, headers):
        return self._request("POST", f"/flight-ops/flight-legs/{leg_id}/catering-orders",
                             payload, headers)

    def list_catering_orders(self, leg_id, headers, params=None):
        return self._request("GET", f"/flight-ops/flight-legs/{leg_id}/catering-orders",
                             headers=headers, params=params)

    def confirm_catering_order(self, order_id, headers):
        return self._request("POST", f"/flight-ops/catering-orders/{order_id}/confirm", {}, headers)

    def deliver_catering_order(self, order_id, headers):
        return self._request("POST", f"/flight-ops/catering-orders/{order_id}/deliver", {}, headers)

    def cancel_catering_order(self, order_id, headers):
        return self._request("POST", f"/flight-ops/catering-orders/{order_id}/cancel", {}, headers)

    # ------------------------------------------------------------------
    # GroundTransport
    # ------------------------------------------------------------------
    def create_ground_transport(self, leg_id, payload, headers):
        return self._request("POST", f"/flight-ops/flight-legs/{leg_id}/ground-transports",
                             payload, headers)

    def list_ground_transports(self, leg_id, headers, params=None):
        return self._request("GET", f"/flight-ops/flight-legs/{leg_id}/ground-transports",
                             headers=headers, params=params)

    def confirm_ground_transport(self, transport_id, headers):
        return self._request("POST", f"/flight-ops/ground-transports/{transport_id}/confirm",
                             {}, headers)

    def complete_ground_transport(self, transport_id, headers):
        return self._request("POST", f"/flight-ops/ground-transports/{transport_id}/complete",
                             {}, headers)

    def cancel_ground_transport(self, transport_id, headers):
        return self._request("POST", f"/flight-ops/ground-transports/{transport_id}/cancel",
                             {}, headers)

    # ------------------------------------------------------------------
    # CharterSupplement
    # ------------------------------------------------------------------
    def create_charter_supplement(self, payload, headers):
        return self._request("POST", "/flight-ops/charter-supplements", payload, headers)

    def list_charter_supplements(self, headers, params=None):
        return self._request("GET", "/flight-ops/charter-supplements",
                             headers=headers, params=params)

    def get_charter_supplement(self, charter_id, headers):
        return self._request("GET", f"/flight-ops/charter-supplements/{charter_id}",
                             headers=headers)

    def accept_charter(self, charter_id, headers):
        return self._request("POST", f"/flight-ops/charter-supplements/{charter_id}/accept",
                             {}, headers)

    def decline_charter(self, charter_id, headers):
        return self._request("POST", f"/flight-ops/charter-supplements/{charter_id}/decline",
                             {}, headers)

    # ------------------------------------------------------------------
    # SiflRatePeriod
    # ------------------------------------------------------------------
    def create_sifl_rate_period(self, payload, headers):
        return self._request("POST", "/flight-ops/sifl-rate-periods", payload, headers)

    def list_sifl_rate_periods(self, headers, params=None):
        return self._request("GET", "/flight-ops/sifl-rate-periods",
                             headers=headers, params=params)

    def get_sifl_rate_period(self, period_id, headers):
        return self._request("GET", f"/flight-ops/sifl-rate-periods/{period_id}",
                             headers=headers)


api_client = ApiClient()
