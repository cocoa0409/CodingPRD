"""API client: one method per endpoint defined in the PRD."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Docks and stops ------------------------------------------------
    def create_dock(self, payload, headers):
        return self._request("POST", "/harbor/docks", payload, headers)

    def get_dock(self, dock_id, headers):
        return self._request("GET", f"/harbor/docks/{dock_id}", headers=headers)

    def create_stop(self, dock_id, payload, headers):
        return self._request("POST", f"/harbor/docks/{dock_id}/stops", payload, headers)

    def list_stops(self, dock_id, headers, params=None):
        return self._request("GET", f"/harbor/docks/{dock_id}/stops", headers=headers,
                             params=params)

    # ---- Vessels and inspections ----------------------------------------
    def create_vessel(self, payload, headers):
        return self._request("POST", "/harbor/vessels", payload, headers)

    def get_vessel(self, vessel_id, headers):
        return self._request("GET", f"/harbor/vessels/{vessel_id}", headers=headers)

    def create_inspection(self, vessel_id, payload, headers):
        return self._request("POST", f"/harbor/vessels/{vessel_id}/inspections",
                             payload, headers)

    def list_inspections(self, vessel_id, headers, params=None):
        return self._request("GET", f"/harbor/vessels/{vessel_id}/inspections",
                             headers=headers, params=params)

    # ---- Crew -------------------------------------------------------------
    def create_crew_member(self, payload, headers):
        return self._request("POST", "/harbor/crew-members", payload, headers)

    def get_crew_member(self, crew_id, headers):
        return self._request("GET", f"/harbor/crew-members/{crew_id}", headers=headers)

    # ---- Service days -----------------------------------------------------
    def create_service_day(self, payload, headers):
        return self._request("POST", "/harbor/service-days", payload, headers)

    def get_service_day(self, service_day_id, headers):
        return self._request("GET", f"/harbor/service-days/{service_day_id}",
                             headers=headers)

    def update_service_day(self, service_day_id, payload, headers):
        return self._request("PATCH", f"/harbor/service-days/{service_day_id}",
                             payload, headers)

    def create_interruption(self, service_day_id, payload, headers):
        return self._request("POST", f"/harbor/service-days/{service_day_id}/interruptions",
                             payload, headers)

    def list_interruptions(self, service_day_id, headers, params=None):
        return self._request("GET", f"/harbor/service-days/{service_day_id}/interruptions",
                             headers=headers, params=params)

    # ---- Trips ------------------------------------------------------------
    def create_trip(self, payload, headers):
        return self._request("POST", "/harbor/trips", payload, headers)

    def get_trip(self, trip_id, headers):
        return self._request("GET", f"/harbor/trips/{trip_id}", headers=headers)

    def list_trips(self, headers, params=None):
        return self._request("GET", "/harbor/trips", headers=headers, params=params)

    def create_dock_slot(self, trip_id, payload, headers):
        return self._request("POST", f"/harbor/trips/{trip_id}/dock-slots", payload,
                             headers)

    def get_dock_slot(self, dock_slot_id, headers):
        return self._request("GET", f"/harbor/dock-slots/{dock_slot_id}", headers=headers)

    def list_dock_slots(self, headers, params=None):
        return self._request("GET", "/harbor/dock-slots", headers=headers, params=params)

    def board_trip(self, trip_id, payload, headers):
        return self._request("POST", f"/harbor/trips/{trip_id}/board", payload, headers)

    def depart_trip(self, trip_id, headers):
        return self._request("POST", f"/harbor/trips/{trip_id}/depart", {}, headers)

    def complete_trip(self, trip_id, headers):
        return self._request("POST", f"/harbor/trips/{trip_id}/complete", {}, headers)

    # ---- Ride passes ------------------------------------------------------
    def create_ride_pass(self, payload, headers):
        return self._request("POST", "/harbor/ride-passes", payload, headers)

    def get_ride_pass(self, ride_pass_id, headers):
        return self._request("GET", f"/harbor/ride-passes/{ride_pass_id}", headers=headers)

    def refund_ride_pass(self, ride_pass_id, payload, headers):
        return self._request("POST", f"/harbor/ride-passes/{ride_pass_id}/refund",
                             payload, headers)

    # ---- Bookings ---------------------------------------------------------
    def create_booking(self, payload, headers):
        return self._request("POST", "/harbor/bookings", payload, headers)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/harbor/bookings/{booking_id}", headers=headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/harbor/bookings", headers=headers, params=params)

    def dispatch_booking(self, booking_id, headers):
        return self._request("POST", f"/harbor/bookings/{booking_id}/dispatch", {}, headers)

    def decline_booking(self, booking_id, headers):
        return self._request("POST", f"/harbor/bookings/{booking_id}/decline", {}, headers)

    def confirm_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/harbor/bookings/{booking_id}/confirm", payload,
                             headers)

    # ---- Refund claims ----------------------------------------------------
    def get_refund_claim(self, refund_claim_id, headers):
        return self._request("GET", f"/harbor/refund-claims/{refund_claim_id}",
                             headers=headers)

    def list_refund_claims(self, headers, params=None):
        return self._request("GET", "/harbor/refund-claims", headers=headers, params=params)

    def approve_refund_claim(self, refund_claim_id, payload, headers):
        return self._request("POST", f"/harbor/refund-claims/{refund_claim_id}/approve",
                             payload, headers)

    # ---- Logical clock ----------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
