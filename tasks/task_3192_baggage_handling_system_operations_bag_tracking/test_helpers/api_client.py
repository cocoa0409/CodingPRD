"""API client: one method per endpoint defined in the PRD (PRD §4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock -----------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- stations ----------------------------------------------------------
    def create_station(self, payload, headers):
        return self._request("POST", "/baggage/stations", payload, headers)

    def list_stations(self, headers, params=None):
        return self._request("GET", "/baggage/stations", headers=headers, params=params)

    def get_station(self, station_id, headers):
        return self._request("GET", f"/baggage/stations/{station_id}", headers=headers)

    def declare_outage(self, station_id, headers):
        return self._request("POST", f"/baggage/stations/{station_id}/outage", {}, headers)

    def clear_outage(self, station_id, headers):
        return self._request("POST", f"/baggage/stations/{station_id}/outage/clear", {}, headers)

    def run_ops(self, station_id, headers):
        return self._request("POST", f"/baggage/stations/{station_id}/run_ops", {}, headers)

    def list_station_makeup_areas(self, station_id, headers, params=None):
        return self._request("GET", f"/baggage/stations/{station_id}/makeup-areas",
                             headers=headers, params=params)

    def list_station_flights(self, station_id, headers, params=None):
        return self._request("GET", f"/baggage/stations/{station_id}/flights",
                             headers=headers, params=params)

    def list_station_bags(self, station_id, headers, params=None):
        return self._request("GET", f"/baggage/stations/{station_id}/bags",
                             headers=headers, params=params)

    def list_station_inspections(self, station_id, headers, params=None):
        return self._request("GET", f"/baggage/stations/{station_id}/inspections",
                             headers=headers, params=params)

    def list_station_reports(self, station_id, headers, params=None):
        return self._request("GET", f"/baggage/stations/{station_id}/reports",
                             headers=headers, params=params)

    # --- airlines ----------------------------------------------------------
    def create_airline(self, payload, headers):
        return self._request("POST", "/baggage/airlines", payload, headers)

    def list_airlines(self, headers, params=None):
        return self._request("GET", "/baggage/airlines", headers=headers, params=params)

    def get_airline(self, airline_id, headers):
        return self._request("GET", f"/baggage/airlines/{airline_id}", headers=headers)

    def list_airline_flights(self, airline_id, headers, params=None):
        return self._request("GET", f"/baggage/airlines/{airline_id}/flights",
                             headers=headers, params=params)

    def list_airline_bags(self, airline_id, headers, params=None):
        return self._request("GET", f"/baggage/airlines/{airline_id}/bags",
                             headers=headers, params=params)

    # --- make-up areas -----------------------------------------------------
    def create_makeup_area(self, payload, headers):
        return self._request("POST", "/baggage/makeup-areas", payload, headers)

    def list_makeup_areas(self, headers, params=None):
        return self._request("GET", "/baggage/makeup-areas", headers=headers, params=params)

    def get_makeup_area(self, area_id, headers):
        return self._request("GET", f"/baggage/makeup-areas/{area_id}", headers=headers)

    def list_makeup_area_flights(self, area_id, headers, params=None):
        return self._request("GET", f"/baggage/makeup-areas/{area_id}/flights",
                             headers=headers, params=params)

    def list_makeup_area_bags(self, area_id, headers, params=None):
        return self._request("GET", f"/baggage/makeup-areas/{area_id}/bags",
                             headers=headers, params=params)

    # --- screening lanes ---------------------------------------------------
    def create_screening_lane(self, payload, headers):
        return self._request("POST", "/baggage/screening-lanes", payload, headers)

    def list_screening_lanes(self, headers, params=None):
        return self._request("GET", "/baggage/screening-lanes", headers=headers, params=params)

    def get_screening_lane(self, lane_id, headers):
        return self._request("GET", f"/baggage/screening-lanes/{lane_id}", headers=headers)

    def take_lane_offline(self, lane_id, headers):
        return self._request("POST", f"/baggage/screening-lanes/{lane_id}/offline", {}, headers)

    def bring_lane_online(self, lane_id, headers):
        return self._request("POST", f"/baggage/screening-lanes/{lane_id}/online", {}, headers)

    def list_lane_screenings(self, lane_id, headers, params=None):
        return self._request("GET", f"/baggage/screening-lanes/{lane_id}/screenings",
                             headers=headers, params=params)

    # --- flights -----------------------------------------------------------
    def create_flight(self, payload, headers):
        return self._request("POST", "/baggage/flights", payload, headers)

    def list_flights(self, headers, params=None):
        return self._request("GET", "/baggage/flights", headers=headers, params=params)

    def get_flight(self, flight_id, headers):
        return self._request("GET", f"/baggage/flights/{flight_id}", headers=headers)

    def reschedule_flight(self, flight_id, scheduled_departure_utc, headers):
        return self._request("POST", f"/baggage/flights/{flight_id}/reschedule",
                             {"scheduled_departure_utc": scheduled_departure_utc}, headers)

    def depart_flight(self, flight_id, headers):
        return self._request("POST", f"/baggage/flights/{flight_id}/depart", {}, headers)

    def cancel_flight(self, flight_id, headers):
        return self._request("POST", f"/baggage/flights/{flight_id}/cancel", {}, headers)

    def list_flight_bags(self, flight_id, headers, params=None):
        return self._request("GET", f"/baggage/flights/{flight_id}/bags",
                             headers=headers, params=params)

    def list_flight_connections(self, flight_id, headers, params=None):
        return self._request("GET", f"/baggage/flights/{flight_id}/connections",
                             headers=headers, params=params)

    # --- bags --------------------------------------------------------------
    def create_bag(self, payload, headers):
        return self._request("POST", "/baggage/bags", payload, headers)

    def list_bags(self, headers, params=None):
        return self._request("GET", "/baggage/bags", headers=headers, params=params)

    def get_bag(self, bag_id, headers):
        return self._request("GET", f"/baggage/bags/{bag_id}", headers=headers)

    def update_bag(self, bag_id, payload, headers):
        return self._request("PUT", f"/baggage/bags/{bag_id}", payload, headers)

    def weigh_bag(self, bag_id, scale_weight_lb, headers):
        return self._request("POST", f"/baggage/bags/{bag_id}/weigh",
                             {"scale_weight_lb": scale_weight_lb}, headers)

    def assign_makeup(self, bag_id, payload, headers):
        return self._request("POST", f"/baggage/bags/{bag_id}/assign-makeup", payload, headers)

    def bulk_assign_makeup(self, assignments, headers):
        return self._request("POST", "/baggage/bags/bulk-assign-makeup",
                             {"assignments": assignments}, headers)

    def load_bag(self, bag_id, headers):
        return self._request("POST", f"/baggage/bags/{bag_id}/load", {}, headers)

    def deliver_bag(self, bag_id, headers):
        return self._request("POST", f"/baggage/bags/{bag_id}/deliver", {}, headers)

    def offload_bag(self, bag_id, headers):
        return self._request("POST", f"/baggage/bags/{bag_id}/offload", {}, headers)

    def add_scan(self, bag_id, payload, headers):
        return self._request("POST", f"/baggage/bags/{bag_id}/scans", payload, headers)

    def list_bag_scans(self, bag_id, headers, params=None):
        return self._request("GET", f"/baggage/bags/{bag_id}/scans",
                             headers=headers, params=params)

    def list_scans(self, headers, params=None):
        return self._request("GET", "/baggage/scans", headers=headers, params=params)

    def add_special_item(self, bag_id, payload, headers):
        return self._request("POST", f"/baggage/bags/{bag_id}/special-items", payload, headers)

    def list_bag_special_items(self, bag_id, headers, params=None):
        return self._request("GET", f"/baggage/bags/{bag_id}/special-items",
                             headers=headers, params=params)

    def list_special_items(self, headers, params=None):
        return self._request("GET", "/baggage/special-items", headers=headers, params=params)

    def waive_handling_fee(self, bag_id, item_id, payload, headers):
        return self._request(
            "POST", f"/baggage/bags/{bag_id}/special-items/{item_id}/waive-handling-fee",
            payload, headers)

    def list_bag_reports(self, bag_id, headers, params=None):
        return self._request("GET", f"/baggage/bags/{bag_id}/reports",
                             headers=headers, params=params)

    def list_bag_deliveries(self, bag_id, headers, params=None):
        return self._request("GET", f"/baggage/bags/{bag_id}/deliveries",
                             headers=headers, params=params)

    def list_bag_connections(self, bag_id, headers, params=None):
        return self._request("GET", f"/baggage/bags/{bag_id}/connections",
                             headers=headers, params=params)

    def list_bag_screenings(self, bag_id, headers, params=None):
        return self._request("GET", f"/baggage/bags/{bag_id}/screenings",
                             headers=headers, params=params)

    # --- screenings --------------------------------------------------------
    def create_screening(self, payload, headers):
        return self._request("POST", "/baggage/screenings", payload, headers)

    def list_screenings(self, headers, params=None):
        return self._request("GET", "/baggage/screenings", headers=headers, params=params)

    def get_screening(self, screening_id, headers):
        return self._request("GET", f"/baggage/screenings/{screening_id}", headers=headers)

    def resolve_screening(self, screening_id, outcome, headers):
        return self._request("POST", f"/baggage/screenings/{screening_id}/resolve",
                             {"outcome": outcome}, headers)

    def reopen_screening(self, screening_id, headers):
        return self._request("POST", f"/baggage/screenings/{screening_id}/reopen", {}, headers)

    def list_screening_inspections(self, screening_id, headers, params=None):
        return self._request("GET", f"/baggage/screenings/{screening_id}/inspections",
                             headers=headers, params=params)

    # --- manual inspections ------------------------------------------------
    def list_inspections(self, headers, params=None):
        return self._request("GET", "/baggage/inspections", headers=headers, params=params)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/baggage/inspections/{inspection_id}", headers=headers)

    def claim_inspection(self, inspection_id, headers):
        return self._request("POST", f"/baggage/inspections/{inspection_id}/claim", {}, headers)

    def resolve_inspection(self, inspection_id, resolution, headers):
        return self._request("POST", f"/baggage/inspections/{inspection_id}/resolve",
                             {"resolution": resolution}, headers)

    # --- connections -------------------------------------------------------
    def create_connection(self, payload, headers):
        return self._request("POST", "/baggage/connections", payload, headers)

    def list_connections(self, headers, params=None):
        return self._request("GET", "/baggage/connections", headers=headers, params=params)

    def get_connection(self, connection_id, headers):
        return self._request("GET", f"/baggage/connections/{connection_id}", headers=headers)

    def confirm_connection(self, connection_id, headers):
        return self._request("POST", f"/baggage/connections/{connection_id}/confirm", {}, headers)

    def declare_rush(self, connection_id, headers):
        return self._request("POST", f"/baggage/connections/{connection_id}/declare-rush",
                             {}, headers)

    def reaccommodate_connection(self, connection_id, onward_flight_id, headers):
        return self._request("POST", f"/baggage/connections/{connection_id}/reaccommodate",
                             {"onward_flight_id": onward_flight_id}, headers)

    # --- reports -----------------------------------------------------------
    def create_report(self, payload, headers):
        return self._request("POST", "/baggage/reports", payload, headers)

    def list_reports(self, headers, params=None):
        return self._request("GET", "/baggage/reports", headers=headers, params=params)

    def get_report(self, report_id, headers):
        return self._request("GET", f"/baggage/reports/{report_id}", headers=headers)

    def investigate_report(self, report_id, headers):
        return self._request("POST", f"/baggage/reports/{report_id}/investigate", {}, headers)

    def arrange_delivery(self, report_id, payload, headers):
        return self._request("POST", f"/baggage/reports/{report_id}/arrange-delivery",
                             payload, headers)

    def mark_report_delivered(self, report_id, headers):
        return self._request("POST", f"/baggage/reports/{report_id}/mark-delivered", {}, headers)

    def compensate_report(self, report_id, headers):
        return self._request("POST", f"/baggage/reports/{report_id}/compensate", {}, headers)

    def close_report(self, report_id, headers):
        return self._request("POST", f"/baggage/reports/{report_id}/close", {}, headers)

    def reopen_report(self, report_id, expected_report_version, headers):
        return self._request("POST", f"/baggage/reports/{report_id}/reopen",
                             {"expected_report_version": expected_report_version}, headers)

    def loss_settlement(self, report_id, paid_cents, headers):
        return self._request("POST", f"/baggage/reports/{report_id}/loss-settlement",
                             {"paid_cents": paid_cents}, headers)

    def file_claim(self, report_id, requested_amount_cents, headers):
        return self._request("POST", f"/baggage/reports/{report_id}/claims",
                             {"requested_amount_cents": requested_amount_cents}, headers)

    def list_report_claims(self, report_id, headers, params=None):
        return self._request("GET", f"/baggage/reports/{report_id}/claims",
                             headers=headers, params=params)

    def list_report_deliveries(self, report_id, headers, params=None):
        return self._request("GET", f"/baggage/reports/{report_id}/deliveries",
                             headers=headers, params=params)

    def decide_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/baggage/claims/{claim_id}/decide", payload, headers)

    # --- deliveries --------------------------------------------------------
    def list_deliveries(self, headers, params=None):
        return self._request("GET", "/baggage/deliveries", headers=headers, params=params)

    def get_delivery(self, delivery_id, headers):
        return self._request("GET", f"/baggage/deliveries/{delivery_id}", headers=headers)

    def dispatch_delivery(self, delivery_id, courier_ref, headers):
        return self._request("POST", f"/baggage/deliveries/{delivery_id}/dispatch",
                             {"courier_ref": courier_ref}, headers)

    def complete_delivery(self, delivery_id, payload, headers):
        return self._request("POST", f"/baggage/deliveries/{delivery_id}/complete",
                             payload, headers)

    # --- passenger tracking ------------------------------------------------
    def tracking_lookup(self, tag_number, headers):
        return self._request("GET", f"/baggage/tracking/{tag_number}", headers=headers)


api_client = ApiClient()