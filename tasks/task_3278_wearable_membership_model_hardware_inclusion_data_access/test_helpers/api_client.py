"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --- members ---
    def create_member(self, payload, headers):
        return self._request("POST", "/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def acknowledge_algorithm(self, member_id, payload, headers):
        return self._request(
            "POST", f"/members/{member_id}/acknowledge-algorithm", payload, headers
        )

    def list_member_terms(self, member_id, headers, params=None):
        return self._request(
            "GET", f"/members/{member_id}/terms", headers=headers, params=params
        )

    def list_member_metric_sets(self, member_id, headers, params=None):
        return self._request(
            "GET", f"/members/{member_id}/metric-sets", headers=headers, params=params
        )

    def list_member_merch_orders(self, member_id, headers, params=None):
        return self._request(
            "GET", f"/members/{member_id}/merch-orders", headers=headers, params=params
        )

    def list_member_research_enrollments(self, member_id, headers, params=None):
        return self._request(
            "GET",
            f"/members/{member_id}/research-enrollments",
            headers=headers,
            params=params,
        )

    def create_term(self, member_id, payload, headers):
        return self._request("POST", f"/members/{member_id}/terms", payload, headers)

    def place_merch_order(self, member_id, payload, headers):
        return self._request(
            "POST", f"/members/{member_id}/merch-orders", payload, headers
        )

    # --- terms ---
    def pause_term(self, term_id, payload, headers):
        return self._request("POST", f"/terms/{term_id}/pause", payload, headers)

    def resume_term(self, term_id, headers):
        return self._request("POST", f"/terms/{term_id}/resume", {}, headers)

    def record_payment(self, term_id, payload, headers):
        return self._request(
            "POST", f"/terms/{term_id}/record-payment", payload, headers
        )

    def cancel_term(self, term_id, headers):
        return self._request("POST", f"/terms/{term_id}/cancel", {}, headers)

    def upgrade_term(self, term_id, payload, headers):
        return self._request("POST", f"/terms/{term_id}/upgrade", payload, headers)

    # --- devices ---
    def provision_device(self, payload, headers):
        return self._request("POST", "/devices", payload, headers)

    def get_device(self, device_id, headers):
        return self._request("GET", f"/devices/{device_id}", headers=headers)

    def list_devices(self, headers, params=None):
        return self._request("GET", "/devices", headers=headers, params=params)

    def activate_device(self, device_id, headers):
        return self._request("POST", f"/devices/{device_id}/activate", {}, headers)

    def ingest_metrics(self, device_id, payload, headers):
        return self._request("POST", f"/devices/{device_id}/ingest", payload, headers)

    def open_replacement_request(self, device_id, payload, headers):
        return self._request(
            "POST", f"/devices/{device_id}/replacement-requests", payload, headers
        )

    def list_device_replacement_requests(self, device_id, headers, params=None):
        return self._request(
            "GET",
            f"/devices/{device_id}/replacement-requests",
            headers=headers,
            params=params,
        )

    # --- replacement requests ---
    def decide_replacement_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"/replacement-requests/{request_id}/decide", payload, headers
        )

    def receive_return(self, request_id, headers):
        return self._request(
            "POST", f"/replacement-requests/{request_id}/receive-return", {}, headers
        )

    # --- algorithm releases ---
    def create_algorithm_release(self, payload, headers):
        return self._request("POST", "/algorithm-releases", payload, headers)

    def publish_algorithm_release(self, release_id, headers):
        return self._request(
            "POST", f"/algorithm-releases/{release_id}/publish", {}, headers
        )

    # --- teams ---
    def create_team(self, payload, headers):
        return self._request("POST", "/teams", payload, headers)

    def add_team_membership(self, team_id, payload, headers):
        return self._request("POST", f"/teams/{team_id}/memberships", payload, headers)

    def get_team_dashboard(self, team_id, headers):
        return self._request("GET", f"/teams/{team_id}/dashboard", headers=headers)

    # --- team memberships ---
    def get_team_membership(self, membership_id, headers):
        return self._request(
            "GET", f"/team-memberships/{membership_id}", headers=headers
        )

    def list_team_memberships(self, headers, params=None):
        return self._request("GET", "/team-memberships", headers=headers, params=params)

    def grant_or_revoke_consent(self, membership_id, payload, headers):
        return self._request(
            "POST", f"/team-memberships/{membership_id}/consents", payload, headers
        )

    def remove_team_membership(self, membership_id, headers):
        return self._request(
            "POST", f"/team-memberships/{membership_id}/remove", {}, headers
        )

    # --- research studies ---
    def create_research_study(self, payload, headers):
        return self._request("POST", "/research-studies", payload, headers)

    def get_research_study(self, study_id, headers):
        return self._request("GET", f"/research-studies/{study_id}", headers=headers)

    def enroll_in_study(self, study_id, payload, headers):
        return self._request(
            "POST", f"/research-studies/{study_id}/enroll", payload, headers
        )

    def list_study_enrollments(self, study_id, headers, params=None):
        return self._request(
            "GET", f"/research-studies/{study_id}/enrollments", headers=headers, params=params
        )

    def get_contribution_dataset(self, study_id, headers):
        return self._request(
            "GET", f"/research-studies/{study_id}/contribution-dataset", headers=headers
        )

    def withdraw_enrollment(self, enrollment_id, headers):
        return self._request(
            "POST", f"/research-enrollments/{enrollment_id}/withdraw", {}, headers
        )

    # --- merch orders ---
    def cancel_merch_order(self, order_id, headers):
        return self._request("POST", f"/merch-orders/{order_id}/cancel", {}, headers)


api_client = ApiClient()
