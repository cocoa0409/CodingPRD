"""API client: one method per endpoint defined in PRD §4.

Paths are PRD-exact. Creates (POST that mint a resource) return HTTP 201;
every other successful operation returns HTTP 200 — callers assert the exact
status via validate_success(response, expected_status).
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Dealers ---
    def create_dealer(self, payload, headers):
        return self._request("POST", "/dealers", payload, headers)

    def update_dealer(self, dealer_id, payload, headers):
        return self._request("PATCH", f"/dealers/{dealer_id}", payload, headers)

    # --- End users ---
    def create_end_user(self, payload, headers):
        return self._request("POST", "/end-users", payload, headers)

    # --- Volume agreements ---
    def create_volume_agreement(self, payload, headers):
        return self._request("POST", "/volume-agreements", payload, headers)

    def get_volume_agreement(self, agreement_id, headers):
        return self._request(
            "GET", f"/volume-agreements/{agreement_id}", headers=headers
        )

    def list_volume_agreements(self, headers, params=None):
        return self._request(
            "GET", "/volume-agreements", headers=headers, params=params
        )

    def activate_volume_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"/volume-agreements/{agreement_id}/activate", {}, headers
        )

    # --- Product families ---
    def create_product_family(self, payload, headers):
        return self._request("POST", "/product-families", payload, headers)

    def update_product_family(self, family_id, payload, headers):
        return self._request(
            "PATCH", f"/product-families/{family_id}", payload, headers
        )

    # --- Configurations ---
    def create_configuration(self, payload, headers):
        return self._request("POST", "/configurations", payload, headers)

    def get_configuration(self, configuration_id, headers):
        return self._request(
            "GET", f"/configurations/{configuration_id}", headers=headers
        )

    def list_configurations(self, headers, params=None):
        return self._request(
            "GET", "/configurations", headers=headers, params=params
        )

    def lock_configuration(self, configuration_id, payload, headers):
        return self._request(
            "POST", f"/configurations/{configuration_id}/lock", payload, headers
        )

    def revise_configuration(self, configuration_id, headers):
        return self._request(
            "POST", f"/configurations/{configuration_id}/revise", {}, headers
        )

    def get_configuration_bom(self, configuration_id, headers):
        return self._request(
            "GET", f"/configurations/{configuration_id}/bom", headers=headers
        )

    # --- Project orders ---
    def create_project_order(self, payload, headers):
        return self._request("POST", "/project-orders", payload, headers)

    def get_project_order(self, order_id, headers):
        return self._request(
            "GET", f"/project-orders/{order_id}", headers=headers
        )

    def list_project_orders(self, headers, params=None):
        return self._request(
            "GET", "/project-orders", headers=headers, params=params
        )

    def submit_project_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/project-orders/{order_id}/submit", payload, headers
        )

    def acknowledge_project_order(self, order_id, headers):
        return self._request(
            "POST", f"/project-orders/{order_id}/acknowledge", {}, headers
        )

    def cancel_project_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/project-orders/{order_id}/cancel", payload, headers
        )

    def create_phase(self, order_id, payload, headers):
        return self._request(
            "POST", f"/project-orders/{order_id}/phases", payload, headers
        )

    def list_phases(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/project-orders/{order_id}/phases",
            headers=headers, params=params,
        )

    # --- Phase actions ---
    def reserve_slot(self, phase_id, payload, headers):
        return self._request(
            "POST", f"/phases/{phase_id}/reserve-slot", payload, headers
        )

    def start_install(self, phase_id, headers):
        return self._request(
            "POST", f"/phases/{phase_id}/start-install", {}, headers
        )

    def complete_phase(self, phase_id, headers):
        return self._request(
            "POST", f"/phases/{phase_id}/complete", {}, headers
        )

    # --- Install windows ---
    def create_install_window(self, payload, headers):
        return self._request("POST", "/install-windows", payload, headers)

    def list_install_windows(self, headers, params=None):
        return self._request(
            "GET", "/install-windows", headers=headers, params=params
        )

    def get_install_window(self, window_id, headers):
        return self._request(
            "GET", f"/install-windows/{window_id}", headers=headers
        )

    def cancel_install_window(self, window_id, headers):
        return self._request(
            "POST", f"/install-windows/{window_id}/cancel", {}, headers
        )

    # --- Punch tickets ---
    def create_punch_ticket(self, payload, headers):
        return self._request("POST", "/punch-tickets", payload, headers)

    def list_punch_tickets(self, headers, params=None):
        return self._request(
            "GET", "/punch-tickets", headers=headers, params=params
        )

    def get_punch_ticket(self, ticket_id, headers):
        return self._request(
            "GET", f"/punch-tickets/{ticket_id}", headers=headers
        )

    def resolve_punch_ticket(self, ticket_id, payload, headers):
        return self._request(
            "POST", f"/punch-tickets/{ticket_id}/resolve", payload, headers
        )

    def verify_punch_ticket(self, ticket_id, payload, headers):
        return self._request(
            "POST", f"/punch-tickets/{ticket_id}/verify", payload, headers
        )

    # --- Warranty claims ---
    def create_warranty_claim(self, payload, headers):
        return self._request("POST", "/warranty-claims", payload, headers)

    def get_warranty_claim(self, claim_id, headers):
        return self._request(
            "GET", f"/warranty-claims/{claim_id}", headers=headers
        )

    def list_warranty_claims(self, headers, params=None):
        return self._request(
            "GET", "/warranty-claims", headers=headers, params=params
        )

    def review_warranty_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/warranty-claims/{claim_id}/review", payload, headers
        )

    # --- Logical clock (test-driving) ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )


api_client = ApiClient()
