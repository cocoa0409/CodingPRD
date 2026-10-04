"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # --- HostBusiness -----------------------------------------------------
    def create_host(self, payload, headers):
        return self._request("POST", "/api/hosts", payload, headers)

    def list_hosts(self, headers, params=None):
        return self._request("GET", "/api/hosts", headers=headers, params=params)

    def get_host(self, host_id, headers):
        return self._request("GET", f"/api/hosts/{host_id}", headers=headers)

    def get_host_capacity_summary(self, host_id, headers):
        return self._request(
            "GET", f"/api/hosts/{host_id}/capacity_summary", headers=headers
        )

    def decide_host(self, host_id, payload, headers):
        return self._request(
            "POST", f"/api/hosts/{host_id}/decisions", payload, headers
        )

    def update_host(self, host_id, payload, headers):
        return self._request("PATCH", f"/api/hosts/{host_id}", payload, headers)

    # --- HostParkingSite --------------------------------------------------
    def create_parking_site(self, host_id, payload, headers):
        return self._request(
            "POST", f"/api/hosts/{host_id}/parking-sites", payload, headers
        )

    def list_parking_sites(self, host_id, headers, params=None):
        return self._request(
            "GET", f"/api/hosts/{host_id}/parking-sites", headers=headers, params=params
        )

    def update_parking_site(self, host_id, site_id, payload, headers):
        return self._request(
            "PATCH",
            f"/api/hosts/{host_id}/parking-sites/{site_id}",
            payload,
            headers,
        )

    def get_site_availability(self, host_id, site_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/hosts/{host_id}/parking-sites/{site_id}/availability",
            headers=headers,
            params=params,
        )

    # --- Member -----------------------------------------------------------
    def register_member(self, payload, headers):
        return self._request("POST", "/api/members", payload, headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/api/members", headers=headers, params=params)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/api/members/{member_id}", headers=headers)

    def member_subscription_action(self, member_id, payload, headers):
        return self._request(
            "POST", f"/api/members/{member_id}/subscription_actions", payload, headers
        )

    def cancel_member_subscription(self, member_id, headers):
        return self._request(
            "POST", f"/api/members/{member_id}/cancellations", {}, headers
        )

    # --- MemberVehicle ----------------------------------------------------
    def create_vehicle(self, member_id, payload, headers):
        return self._request(
            "POST", f"/api/members/{member_id}/vehicles", payload, headers
        )

    def list_vehicles(self, member_id, headers, params=None):
        return self._request(
            "GET", f"/api/members/{member_id}/vehicles", headers=headers, params=params
        )

    def update_vehicle(self, member_id, vehicle_id, payload, headers):
        return self._request(
            "PATCH",
            f"/api/members/{member_id}/vehicles/{vehicle_id}",
            payload,
            headers,
        )

    # --- HostAvailabilityWindow -------------------------------------------
    def create_window(self, payload, headers):
        return self._request("POST", "/api/availability-windows", payload, headers)

    def list_windows_for_host(self, host_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/hosts/{host_id}/availability-windows",
            headers=headers,
            params=params,
        )

    def get_window(self, window_id, headers):
        return self._request(
            "GET", f"/api/availability-windows/{window_id}", headers=headers
        )

    def amend_window(self, window_id, payload, headers):
        return self._request(
            "POST", f"/api/availability-windows/{window_id}/amend", payload, headers
        )

    def cancel_window(self, window_id, headers):
        return self._request(
            "POST", f"/api/availability-windows/{window_id}/cancellations", {}, headers
        )

    # --- StayRequest ------------------------------------------------------
    def create_stay_request(self, payload, headers):
        return self._request("POST", "/api/stay-requests", payload, headers)

    def list_stay_requests(self, headers, params=None):
        return self._request(
            "GET", "/api/stay-requests", headers=headers, params=params
        )

    def get_stay_request(self, request_id, headers):
        return self._request(
            "GET", f"/api/stay-requests/{request_id}", headers=headers
        )

    def decide_stay_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"/api/stay-requests/{request_id}/decisions", payload, headers
        )

    def cancel_stay_request(self, request_id, headers):
        return self._request(
            "POST", f"/api/stay-requests/{request_id}/cancellations", {}, headers
        )

    def counter_stay_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"/api/stay-requests/{request_id}/counter_requests", payload, headers
        )

    def check_in_stay(self, request_id, headers):
        return self._request(
            "POST", f"/api/stay-requests/{request_id}/check_ins", {}, headers
        )

    def check_out_stay(self, request_id, headers):
        return self._request(
            "POST", f"/api/stay-requests/{request_id}/check_outs", {}, headers
        )

    def record_no_show(self, request_id, payload, headers):
        return self._request(
            "POST", f"/api/stay-requests/{request_id}/no_show_records", payload, headers
        )

    # --- HostReview -------------------------------------------------------
    def create_review(self, payload, headers):
        return self._request("POST", "/api/reviews", payload, headers)

    def list_reviews(self, headers, params=None):
        return self._request("GET", "/api/reviews", headers=headers, params=params)

    def get_review(self, review_id, headers):
        return self._request("GET", f"/api/reviews/{review_id}", headers=headers)

    def withdraw_review(self, review_id, headers):
        return self._request(
            "POST", f"/api/reviews/{review_id}/withdrawals", {}, headers
        )

    # --- Incident ---------------------------------------------------------
    def create_incident(self, payload, headers):
        return self._request("POST", "/api/incidents", payload, headers)

    def list_incidents(self, headers, params=None):
        return self._request("GET", "/api/incidents", headers=headers, params=params)

    def get_incident(self, incident_id, headers):
        return self._request("GET", f"/api/incidents/{incident_id}", headers=headers)

    def create_disposition(self, incident_id, payload, headers):
        return self._request(
            "POST", f"/api/incidents/{incident_id}/dispositions", payload, headers
        )

    def list_member_dispositions(self, member_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/members/{member_id}/dispositions",
            headers=headers,
            params=params,
        )

    def list_incident_dispositions(self, incident_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/incidents/{incident_id}/dispositions",
            headers=headers,
            params=params,
        )

    # --- HostPatronizationRecord -----------------------------------------
    def create_patronization_record(self, payload, headers):
        return self._request("POST", "/api/patronization-records", payload, headers)

    def list_patronization_records(self, headers, params=None):
        return self._request(
            "GET", "/api/patronization-records", headers=headers, params=params
        )

    def get_patronization_record(self, record_id, headers):
        return self._request(
            "GET", f"/api/patronization-records/{record_id}", headers=headers
        )

    def verify_patronization_record(self, record_id, payload, headers):
        return self._request(
            "POST", f"/api/patronization-records/{record_id}/verification", payload, headers
        )

    # --- PlatformAdmin test-driving namespace ----------------------------
    def set_current_utc(self, to_iso8601, headers):
        return self._request(
            "POST", "/api/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    def conduct_injection(self, member_id, payload, headers):
        return self._request(
            "POST", f"/api/_members/{member_id}/conduct_injections", payload, headers
        )


api_client = ApiClient()