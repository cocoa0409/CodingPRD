"""API client: one method per operation declared in the PRD.

Mutations that accept a JSON body take it as ``payload``; reads take optional
``params`` for paging and filtering.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- clock / support desk / events -----------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def monitor_sweep(self, payload, headers):
        return self._request(
            "POST", "/_support-center/monitor-sweep", payload, headers
        )

    def emit_event(self, payload, headers):
        return self._request("POST", "/_events/emit", payload, headers)

    # --- District ---------------------------------------------------------
    def create_district(self, payload, headers):
        return self._request("POST", "/student-rides/districts", payload, headers)

    def get_district(self, district_id, headers):
        return self._request(
            "GET", f"/student-rides/districts/{district_id}", headers=headers
        )

    def list_district_riders(self, district_id, headers, params=None):
        return self._request(
            "GET", f"/student-rides/districts/{district_id}/riders",
            headers=headers, params=params,
        )

    def list_district_ride_requests(self, district_id, headers, params=None):
        return self._request(
            "GET", f"/student-rides/districts/{district_id}/ride-requests",
            headers=headers, params=params,
        )

    def list_district_contracts(self, district_id, headers, params=None):
        return self._request(
            "GET", f"/student-rides/districts/{district_id}/contracts",
            headers=headers, params=params,
        )

    def list_district_trips(self, district_id, headers, params=None):
        return self._request(
            "GET", f"/student-rides/districts/{district_id}/trips",
            headers=headers, params=params,
        )

    def list_district_billing_statements(self, district_id, headers, params=None):
        return self._request(
            "GET", f"/student-rides/districts/{district_id}/billing-statements",
            headers=headers, params=params,
        )

    def list_district_geofences(self, district_id, headers, params=None):
        return self._request(
            "GET", f"/student-rides/districts/{district_id}/geofences",
            headers=headers, params=params,
        )

    def run_billing(self, district_id, payload, headers):
        return self._request(
            "POST", f"/student-rides/districts/{district_id}/billing-runs",
            payload, headers,
        )

    def get_supply_plan(self, district_id, headers, params=None):
        return self._request(
            "GET", f"/student-rides/districts/{district_id}/supply-plans",
            headers=headers, params=params,
        )

    def block_driver_availability(self, district_id, payload, headers):
        return self._request(
            "POST",
            f"/student-rides/districts/{district_id}/driver-availability-blocks",
            payload, headers,
        )

    def run_driver_supply(self, district_id, payload, headers):
        return self._request(
            "POST", f"/student-rides/districts/{district_id}/driver-supply-runs",
            payload, headers,
        )

    def adjust_credit(self, district_id, payload, headers):
        return self._request(
            "POST", f"/student-rides/districts/{district_id}/credit-adjustments",
            payload, headers,
        )

    # --- Rider ------------------------------------------------------------
    def create_rider(self, payload, headers):
        return self._request("POST", "/student-rides/riders", payload, headers)

    def get_rider(self, rider_id, headers):
        return self._request(
            "GET", f"/student-rides/riders/{rider_id}", headers=headers
        )

    def update_rider(self, rider_id, payload, headers):
        return self._request(
            "PUT", f"/student-rides/riders/{rider_id}", payload, headers
        )

    def list_rider_ride_requests(self, rider_id, headers, params=None):
        return self._request(
            "GET", f"/student-rides/riders/{rider_id}/ride-requests",
            headers=headers, params=params,
        )

    def list_rider_trips(self, rider_id, headers, params=None):
        return self._request(
            "GET", f"/student-rides/riders/{rider_id}/trips",
            headers=headers, params=params,
        )

    # --- Driver -----------------------------------------------------------
    def create_driver(self, payload, headers):
        return self._request("POST", "/student-rides/drivers", payload, headers)

    def get_driver(self, driver_id, headers):
        return self._request(
            "GET", f"/student-rides/drivers/{driver_id}", headers=headers
        )

    def open_background_check(self, driver_id, payload, headers):
        return self._request(
            "POST", f"/student-rides/drivers/{driver_id}/background-checks",
            payload, headers,
        )

    def list_driver_background_checks(self, driver_id, headers, params=None):
        return self._request(
            "GET", f"/student-rides/drivers/{driver_id}/background-checks",
            headers=headers, params=params,
        )

    def record_inspection(self, driver_id, payload, headers):
        return self._request(
            "POST", f"/student-rides/drivers/{driver_id}/inspections",
            payload, headers,
        )

    def list_driver_inspections(self, driver_id, headers, params=None):
        return self._request(
            "GET", f"/student-rides/drivers/{driver_id}/inspections",
            headers=headers, params=params,
        )

    def list_driver_trips(self, driver_id, headers, params=None):
        return self._request(
            "GET", f"/student-rides/drivers/{driver_id}/trips",
            headers=headers, params=params,
        )

    def list_driver_safety_incidents(self, driver_id, headers, params=None):
        return self._request(
            "GET", f"/student-rides/drivers/{driver_id}/safety-incidents",
            headers=headers, params=params,
        )

    def reactivate_driver(self, driver_id, headers):
        return self._request(
            "POST", f"/student-rides/drivers/{driver_id}/reactivate",
            {}, headers,
        )

    def deactivate_driver(self, driver_id, headers):
        return self._request(
            "POST", f"/student-rides/drivers/{driver_id}/deactivate",
            {}, headers,
        )

    # --- BackgroundCheck --------------------------------------------------
    def clear_background_check(self, check_id, headers):
        return self._request(
            "POST", f"/student-rides/background-checks/{check_id}/clear",
            {}, headers,
        )

    def fail_background_check(self, check_id, headers):
        return self._request(
            "POST", f"/student-rides/background-checks/{check_id}/fail",
            {}, headers,
        )

    # --- VehicleInspection ------------------------------------------------
    def attest_inspection(self, inspection_id, headers):
        return self._request(
            "POST", f"/student-rides/vehicle-inspections/{inspection_id}/attest",
            {}, headers,
        )

    def reject_inspection(self, inspection_id, headers):
        return self._request(
            "POST", f"/student-rides/vehicle-inspections/{inspection_id}/reject",
            {}, headers,
        )

    # --- Contract ---------------------------------------------------------
    def create_contract(self, payload, headers):
        return self._request("POST", "/student-rides/contracts", payload, headers)

    def get_contract(self, contract_id, headers):
        return self._request(
            "GET", f"/student-rides/contracts/{contract_id}", headers=headers
        )

    def activate_contract(self, contract_id, headers):
        return self._request(
            "POST", f"/student-rides/contracts/{contract_id}/activate", {}, headers
        )

    def suspend_contract(self, contract_id, headers):
        return self._request(
            "POST", f"/student-rides/contracts/{contract_id}/suspend", {}, headers
        )

    def reactivate_contract(self, contract_id, headers):
        return self._request(
            "POST", f"/student-rides/contracts/{contract_id}/reactivate", {},
            headers,
        )

    # --- RideRequest ------------------------------------------------------
    def create_ride_request(self, payload, headers):
        return self._request(
            "POST", "/student-rides/ride-requests", payload, headers
        )

    def get_ride_request(self, request_id, headers):
        return self._request(
            "GET", f"/student-rides/ride-requests/{request_id}", headers=headers
        )

    def list_ride_request_trips(self, request_id, headers, params=None):
        return self._request(
            "GET", f"/student-rides/ride-requests/{request_id}/trips",
            headers=headers, params=params,
        )

    def submit_ride_request(self, request_id, headers):
        return self._request(
            "POST", f"/student-rides/ride-requests/{request_id}/submit", {},
            headers,
        )

    def request_revision(self, request_id, payload, headers):
        return self._request(
            "POST", f"/student-rides/ride-requests/{request_id}/request-revision",
            payload, headers,
        )

    def resubmit_ride_request(self, request_id, headers):
        return self._request(
            "POST", f"/student-rides/ride-requests/{request_id}/resubmit", {},
            headers,
        )

    def approve_ride_request(self, request_id, headers):
        return self._request(
            "POST", f"/student-rides/ride-requests/{request_id}/approve", {},
            headers,
        )

    def reject_ride_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"/student-rides/ride-requests/{request_id}/reject",
            payload, headers,
        )

    def schedule_ride_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"/student-rides/ride-requests/{request_id}/schedule",
            payload, headers,
        )

    def suspend_series(self, request_id, headers):
        return self._request(
            "POST", f"/student-rides/ride-requests/{request_id}/suspend-series",
            {}, headers,
        )

    def resume_series(self, request_id, headers):
        return self._request(
            "POST", f"/student-rides/ride-requests/{request_id}/resume-series",
            {}, headers,
        )

    def cancel_ride_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"/student-rides/ride-requests/{request_id}/cancel",
            payload, headers,
        )

    # --- Trip -------------------------------------------------------------
    def create_trip(self, payload, headers):
        return self._request("POST", "/student-rides/trips", payload, headers)

    def get_trip(self, trip_id, headers):
        return self._request(
            "GET", f"/student-rides/trips/{trip_id}", headers=headers
        )

    def list_trip_alerts(self, trip_id, headers, params=None):
        return self._request(
            "GET", f"/student-rides/trips/{trip_id}/alerts",
            headers=headers, params=params,
        )

    def list_trip_handoffs(self, trip_id, headers, params=None):
        return self._request(
            "GET", f"/student-rides/trips/{trip_id}/handoffs",
            headers=headers, params=params,
        )

    def list_trip_safety_incidents(self, trip_id, headers, params=None):
        return self._request(
            "GET", f"/student-rides/trips/{trip_id}/safety-incidents",
            headers=headers, params=params,
        )

    def list_trip_geofence_checks(self, trip_id, headers, params=None):
        return self._request(
            "GET", f"/student-rides/trips/{trip_id}/geofence-checks",
            headers=headers, params=params,
        )

    def dispatch_candidate(self, trip_id, headers):
        return self._request(
            "POST", f"/student-rides/trips/{trip_id}/dispatch-candidate", {},
            headers,
        )

    def accept_trip(self, trip_id, headers):
        return self._request(
            "POST", f"/student-rides/trips/{trip_id}/accept", {}, headers
        )

    def arrive_trip(self, trip_id, headers):
        return self._request(
            "POST", f"/student-rides/trips/{trip_id}/arrive", {}, headers
        )

    def depart_trip(self, trip_id, headers):
        return self._request(
            "POST", f"/student-rides/trips/{trip_id}/depart", {}, headers
        )

    def record_handoff(self, trip_id, payload, headers):
        return self._request(
            "POST", f"/student-rides/trips/{trip_id}/handoffs", payload, headers
        )

    def report_exception(self, trip_id, payload, headers):
        return self._request(
            "POST", f"/student-rides/trips/{trip_id}/exceptions", payload, headers
        )

    def cancel_trip(self, trip_id, payload, headers):
        return self._request(
            "POST", f"/student-rides/trips/{trip_id}/cancel", payload, headers
        )

    def restore_trip(self, trip_id, headers):
        return self._request(
            "POST", f"/student-rides/trips/{trip_id}/restore", {}, headers
        )

    def resolve_discrepancy(self, trip_id, headers):
        return self._request(
            "POST", f"/student-rides/trips/{trip_id}/resolve-discrepancy", {},
            headers,
        )

    def release_lock(self, trip_id, headers):
        return self._request(
            "POST", f"/student-rides/trips/{trip_id}/release-lock", {}, headers
        )

    def check_geofences(self, trip_id, payload, headers):
        return self._request(
            "POST", f"/student-rides/trips/{trip_id}/geofence-checks",
            payload, headers,
        )

    # --- SafetyIncident ---------------------------------------------------
    def get_incident(self, incident_id, headers):
        return self._request(
            "GET", f"/student-rides/safety-incidents/{incident_id}",
            headers=headers,
        )

    def list_incident_alerts(self, incident_id, headers, params=None):
        return self._request(
            "GET", f"/student-rides/safety-incidents/{incident_id}/alerts",
            headers=headers, params=params,
        )

    def review_incident(self, incident_id, headers):
        return self._request(
            "POST", f"/student-rides/safety-incidents/{incident_id}/review", {},
            headers,
        )

    def resolve_incident(self, incident_id, payload, headers):
        return self._request(
            "POST", f"/student-rides/safety-incidents/{incident_id}/resolve",
            payload, headers,
        )

    def reopen_incident(self, incident_id, payload, headers):
        return self._request(
            "POST", f"/student-rides/safety-incidents/{incident_id}/reopen",
            payload, headers,
        )

    def void_incident(self, incident_id, payload, headers):
        return self._request(
            "POST", f"/student-rides/safety-incidents/{incident_id}/void",
            payload, headers,
        )

    # --- TripAlert --------------------------------------------------------
    def resolve_alert(self, alert_id, headers):
        return self._request(
            "POST", f"/student-rides/trip-alerts/{alert_id}/resolve", {}, headers
        )

    # --- Geofence ---------------------------------------------------------
    def create_geofence(self, payload, headers):
        return self._request("POST", "/student-rides/geofences", payload, headers)

    def get_geofence(self, geofence_id, headers):
        return self._request(
            "GET", f"/student-rides/geofences/{geofence_id}", headers=headers
        )

    def list_geofence_checks(self, geofence_id, headers, params=None):
        return self._request(
            "GET", f"/student-rides/geofences/{geofence_id}/checks",
            headers=headers, params=params,
        )

    # --- BillingStatement -------------------------------------------------
    def list_billing_statements(self, headers, params=None):
        return self._request(
            "GET", "/student-rides/billing-statements", headers=headers,
            params=params,
        )

    def issue_statement(self, statement_id, headers):
        return self._request(
            "POST", f"/student-rides/billing-statements/{statement_id}/issue", {},
            headers,
        )

    def approve_statement_payment(self, statement_id, payload, headers):
        return self._request(
            "POST",
            f"/student-rides/billing-statements/{statement_id}/approve-payment",
            payload, headers,
        )

    def void_statement(self, statement_id, headers):
        return self._request(
            "POST", f"/student-rides/billing-statements/{statement_id}/void", {},
            headers,
        )


api_client = ApiClient()

__all__ = ["ApiClient", "api_client"]