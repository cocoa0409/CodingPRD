"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/api/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --- families ---
    def create_family(self, payload, headers):
        return self._request("POST", "/api/families", payload, headers)

    def get_family(self, family_id, headers):
        return self._request("GET", f"/api/families/{family_id}", headers=headers)

    def set_family_state(self, family_id, payload, headers):
        return self._request("POST", f"/api/families/{family_id}/state", payload, headers)

    def change_subscription(self, family_id, payload, headers):
        return self._request(
            "POST", f"/api/families/{family_id}/subscription/changes", payload, headers
        )

    def list_parents(self, family_id, headers, params=None):
        return self._request(
            "GET", f"/api/families/{family_id}/parents", headers=headers, params=params
        )

    def list_children(self, family_id, headers, params=None):
        return self._request(
            "GET", f"/api/families/{family_id}/children", headers=headers, params=params
        )

    # --- children ---
    def create_child(self, payload, headers):
        return self._request("POST", "/api/children", payload, headers)

    def get_child(self, child_id, headers):
        return self._request("GET", f"/api/children/{child_id}", headers=headers)

    def patch_child(self, child_id, payload, headers):
        return self._request("PATCH", f"/api/children/{child_id}", payload, headers)

    def list_connections_of_child(self, child_id, headers, params=None):
        return self._request(
            "GET", f"/api/children/{child_id}/connections", headers=headers, params=params
        )

    def create_connection(self, child_id, payload, headers):
        return self._request(
            "POST", f"/api/children/{child_id}/connections", payload, headers
        )

    def list_filter_rules(self, child_id, headers, params=None):
        return self._request(
            "GET", f"/api/children/{child_id}/filter-rules", headers=headers, params=params
        )

    def create_filter_rule(self, child_id, payload, headers):
        return self._request(
            "POST", f"/api/children/{child_id}/filter-rules", payload, headers
        )

    def list_district_links_of_child(self, child_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/children/{child_id}/district-links",
            headers=headers,
            params=params,
        )

    def list_devices_of_child(self, child_id, headers, params=None):
        return self._request(
            "GET", f"/api/children/{child_id}/devices", headers=headers, params=params
        )

    def pair_device(self, child_id, payload, headers):
        return self._request(
            "POST", f"/api/children/{child_id}/devices/pair", payload, headers
        )

    # --- connections ---
    def get_connection(self, connection_id, headers):
        return self._request("GET", f"/api/connections/{connection_id}", headers=headers)

    def list_content_items_of_connection(self, connection_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/connections/{connection_id}/content-items",
            headers=headers,
            params=params,
        )

    def set_connection_state(self, connection_id, payload, headers):
        return self._request(
            "POST", f"/api/connections/{connection_id}/state", payload, headers
        )

    # --- devices ---
    def get_device(self, device_id, headers):
        return self._request("GET", f"/api/devices/{device_id}", headers=headers)

    def unpair_device(self, device_id, headers):
        return self._request("POST", f"/api/devices/{device_id}/unpair", {}, headers)

    def create_screen_time_window(self, device_id, payload, headers):
        return self._request(
            "POST", f"/api/devices/{device_id}/screen-time-windows", payload, headers
        )

    def list_screen_time_windows(self, device_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/devices/{device_id}/screen-time-windows",
            headers=headers,
            params=params,
        )

    def set_screen_time_window_state(self, window_id, payload, headers):
        return self._request(
            "POST", f"/api/screen-time-windows/{window_id}/state", payload, headers
        )

    def report_bypass_event(self, device_id, payload, headers):
        return self._request(
            "POST", f"/api/devices/{device_id}/bypass-events", payload, headers
        )

    def list_bypass_events(self, device_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/devices/{device_id}/bypass-events",
            headers=headers,
            params=params,
        )

    def create_access_grant(self, device_id, payload, headers):
        return self._request(
            "POST", f"/api/devices/{device_id}/access-grants", payload, headers
        )

    def list_access_grants(self, device_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/devices/{device_id}/access-grants",
            headers=headers,
            params=params,
        )

    # --- content items / alerts / escalation cases ---
    def ingest_content_item(self, payload, headers):
        return self._request("POST", "/api/content-items", payload, headers)

    def get_content_item(self, content_item_id, headers):
        return self._request(
            "GET", f"/api/content-items/{content_item_id}", headers=headers
        )

    def get_alert(self, alert_id, headers):
        return self._request("GET", f"/api/alerts/{alert_id}", headers=headers)

    def list_alerts(self, headers, params=None):
        return self._request("GET", "/api/alerts", headers=headers, params=params)

    def set_alert_state(self, alert_id, payload, headers):
        return self._request("POST", f"/api/alerts/{alert_id}/state", payload, headers)

    def get_escalation_case(self, case_id, headers):
        return self._request("GET", f"/api/escalation-cases/{case_id}", headers=headers)

    def list_escalation_cases(self, headers, params=None):
        return self._request("GET", "/api/escalation-cases", headers=headers, params=params)

    def set_escalation_case_state(self, case_id, payload, headers):
        return self._request(
            "POST", f"/api/escalation-cases/{case_id}/state", payload, headers
        )

    # --- districts / links ---
    def create_district(self, payload, headers):
        return self._request("POST", "/api/districts", payload, headers)

    def get_district(self, district_id, headers):
        return self._request("GET", f"/api/districts/{district_id}", headers=headers)

    def create_district_link(self, district_id, payload, headers):
        return self._request(
            "POST", f"/api/districts/{district_id}/links", payload, headers
        )

    def list_district_links(self, district_id, headers, params=None):
        return self._request(
            "GET", f"/api/districts/{district_id}/links", headers=headers, params=params
        )

    def set_district_link_state(self, link_id, payload, headers):
        return self._request(
            "POST", f"/api/district-links/{link_id}/state", payload, headers
        )


api_client = ApiClient()
