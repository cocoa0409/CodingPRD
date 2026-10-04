"""API client: one method per endpoint the PRD defines.

All resource operations are mounted under the /smart-rent prefix.
"""

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/smart-rent"


class ApiClient(GenericApiClient):
    # --- Logical clock -----------------------------------------------------
    def set_clock(self, current_utc, headers):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc",
            {"current_utc": current_utc}, headers,
        )

    # --- Property / Building / Unit ---------------------------------------
    def create_property(self, payload, headers):
        return self._request("POST", f"{PREFIX}/properties", payload, headers)

    def get_property(self, property_id, headers):
        return self._request(
            "GET", f"{PREFIX}/properties/{property_id}", headers=headers
        )

    def create_building(self, property_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/properties/{property_id}/buildings", payload, headers
        )

    def list_buildings(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/buildings", headers=headers, params=params)

    def create_unit(self, property_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/properties/{property_id}/units", payload, headers
        )

    def list_units(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/units", headers=headers, params=params)

    # --- Devices -----------------------------------------------------------
    def create_device(self, payload, headers):
        return self._request("POST", f"{PREFIX}/devices", payload, headers)

    def list_devices(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/devices", headers=headers, params=params)

    def replace_battery(self, device_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/devices/{device_id}/replace_battery",
            payload or {}, headers,
        )

    def record_lock_event(self, device_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/devices/{device_id}/lock-events", payload, headers
        )

    def run_device_scan(self, building_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/buildings/{building_id}/device-scans", payload, headers
        )

    # --- Residents / credentials ------------------------------------------
    def create_resident(self, payload, headers):
        return self._request("POST", f"{PREFIX}/residents", payload, headers)

    def list_residents(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/residents", headers=headers, params=params)

    def onboard_resident(self, resident_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/residents/{resident_id}/onboard",
            payload or {}, headers,
        )

    def deactivate_resident(self, resident_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/residents/{resident_id}/deactivate", payload, headers
        )

    def list_resident_status_events(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/resident-status-events", headers=headers, params=params
        )

    def list_access_credentials(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/access-credentials", headers=headers, params=params
        )

    # --- Guest passes ------------------------------------------------------
    def issue_guest_pass(self, unit_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/units/{unit_id}/guest-passes", payload, headers
        )

    def extend_guest_pass(self, guest_pass_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/guest-passes/{guest_pass_id}/extend", payload, headers
        )

    def list_guest_passes(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/guest-passes", headers=headers, params=params
        )

    # --- Tours -------------------------------------------------------------
    def request_tour_session(self, unit_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/units/{unit_id}/tour-sessions", payload, headers
        )

    def verify_tour_session(self, tour_session_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/tour-sessions/{tour_session_id}/verify", payload, headers
        )

    def list_tour_sessions(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/tour-sessions", headers=headers, params=params
        )

    # --- Maintenance -------------------------------------------------------
    def request_maintenance_visit(self, unit_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/units/{unit_id}/maintenance-visits", payload, headers
        )

    def certify_notice(self, visit_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/maintenance-visits/{visit_id}/certify_notice",
            payload, headers,
        )

    def complete_maintenance_visit(self, visit_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/maintenance-visits/{visit_id}/complete", payload, headers
        )

    def list_maintenance_visits(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/maintenance-visits", headers=headers, params=params
        )

    # --- Installation jobs -------------------------------------------------
    def create_installation_job(self, building_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/buildings/{building_id}/installation-jobs",
            payload, headers,
        )

    def schedule_installation_job(self, job_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/installation-jobs/{job_id}/schedule", payload, headers
        )

    def complete_installation_job(self, job_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/installation-jobs/{job_id}/complete",
            payload or {}, headers,
        )

    def list_installation_jobs(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/installation-jobs", headers=headers, params=params
        )

    # --- Alerts / work orders ---------------------------------------------
    def list_device_alerts(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/device-alerts", headers=headers, params=params
        )

    def create_work_order(self, alert_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/device-alerts/{alert_id}/work-orders", payload, headers
        )

    def assign_work_order(self, work_order_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/work-orders/{work_order_id}/assign", payload, headers
        )

    def list_work_orders(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/work-orders", headers=headers, params=params
        )

    # --- Vacant automation -------------------------------------------------
    def run_vacant_automation(self, unit_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/units/{unit_id}/vacant-automation", payload, headers
        )


api_client = ApiClient()