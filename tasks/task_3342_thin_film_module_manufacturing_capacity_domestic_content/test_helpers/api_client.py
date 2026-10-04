"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Customers ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/v1/customers", payload, headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/v1/customers", headers=headers, params=params)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/v1/customers/{customer_id}", headers=headers)

    def list_customer_recycling_obligations(self, customer_id, headers):
        return self._request(
            "GET", f"/v1/customers/{customer_id}/recycling-obligations", headers=headers
        )

    def list_customer_capacity_reservations(self, customer_id, headers):
        return self._request(
            "GET", f"/v1/customers/{customer_id}/capacity-reservations", headers=headers
        )

    # --- Module series ---
    def create_module_series(self, payload, headers):
        return self._request("POST", "/v1/module-series", payload, headers)

    def get_module_series(self, series_id, headers):
        return self._request("GET", f"/v1/module-series/{series_id}", headers=headers)

    def get_energy_model(self, series_id, headers):
        return self._request(
            "GET", f"/v1/module-series/{series_id}/energy-model", headers=headers
        )

    def list_series_capacity_reservations(self, series_id, headers):
        return self._request(
            "GET", f"/v1/module-series/{series_id}/capacity-reservations", headers=headers
        )

    def list_series_production_runs(self, series_id, headers):
        return self._request(
            "GET", f"/v1/module-series/{series_id}/production-runs", headers=headers
        )

    # --- Production lines ---
    def create_production_line(self, payload, headers):
        return self._request("POST", "/v1/production-lines", payload, headers)

    def get_production_line(self, line_id, headers):
        return self._request("GET", f"/v1/production-lines/{line_id}", headers=headers)

    def commission_line(self, line_id, headers):
        return self._request(
            "POST", f"/v1/production-lines/{line_id}/commission", {}, headers
        )

    def reintroduce_line(self, line_id, payload, headers):
        return self._request(
            "POST", f"/v1/production-lines/{line_id}/reintroduce", payload, headers
        )

    def suspend_line(self, line_id, headers):
        return self._request(
            "POST", f"/v1/production-lines/{line_id}/suspend", {}, headers
        )

    def resume_line(self, line_id, headers):
        return self._request(
            "POST", f"/v1/production-lines/{line_id}/resume", {}, headers
        )

    def decommission_line(self, line_id, headers):
        return self._request(
            "POST", f"/v1/production-lines/{line_id}/decommission", {}, headers
        )

    def list_line_capacity_reservations(self, line_id, headers):
        return self._request(
            "GET", f"/v1/production-lines/{line_id}/capacity-reservations",
            headers=headers,
        )

    def list_line_production_runs(self, line_id, headers):
        return self._request(
            "GET", f"/v1/production-lines/{line_id}/production-runs", headers=headers
        )

    def list_line_compliance_attestations(self, line_id, headers):
        return self._request(
            "GET", f"/v1/production-lines/{line_id}/compliance-attestations",
            headers=headers,
        )

    # --- Production runs ---
    def create_production_run(self, payload, headers):
        return self._request("POST", "/v1/production-runs", payload, headers)

    # --- Capacity reservations ---
    def create_reservation(self, payload, headers):
        return self._request("POST", "/v1/capacity-reservations", payload, headers)

    def get_reservation(self, reservation_id, headers):
        return self._request(
            "GET", f"/v1/capacity-reservations/{reservation_id}", headers=headers
        )

    def post_deposit(self, reservation_id, headers):
        return self._request(
            "POST", f"/v1/capacity-reservations/{reservation_id}/post-deposit",
            {}, headers,
        )

    def activate_reservation(self, reservation_id, headers):
        return self._request(
            "POST", f"/v1/capacity-reservations/{reservation_id}/activate", {}, headers
        )

    def cancel_reservation(self, reservation_id, headers):
        return self._request(
            "POST", f"/v1/capacity-reservations/{reservation_id}/cancel", {}, headers
        )

    def list_reservation_deliveries(self, reservation_id, headers):
        return self._request(
            "GET", f"/v1/capacity-reservations/{reservation_id}/deliveries",
            headers=headers,
        )

    def list_reservation_warranty_claims(self, reservation_id, headers):
        return self._request(
            "GET", f"/v1/capacity-reservations/{reservation_id}/warranty-claims",
            headers=headers,
        )

    # --- Deliveries ---
    def create_delivery(self, payload, headers):
        return self._request("POST", "/v1/deliveries", payload, headers)

    def get_delivery(self, delivery_id, headers):
        return self._request("GET", f"/v1/deliveries/{delivery_id}", headers=headers)

    def reschedule_delivery(self, delivery_id, payload, headers):
        return self._request("PATCH", f"/v1/deliveries/{delivery_id}", payload, headers)

    def confirm_delivery(self, delivery_id, headers):
        return self._request(
            "POST", f"/v1/deliveries/{delivery_id}/confirm", {}, headers
        )

    def cancel_delivery(self, delivery_id, headers):
        return self._request(
            "POST", f"/v1/deliveries/{delivery_id}/cancel", {}, headers
        )

    # --- Component lots ---
    def create_component_lot(self, payload, headers):
        return self._request("POST", "/v1/component-lots", payload, headers)

    def verify_lot(self, lot_id, headers):
        return self._request("POST", f"/v1/component-lots/{lot_id}/verify", {}, headers)

    def quarantine_lot(self, lot_id, headers):
        return self._request(
            "POST", f"/v1/component-lots/{lot_id}/quarantine", {}, headers
        )

    # --- Compliance attestations ---
    def create_attestation(self, payload, headers):
        return self._request("POST", "/v1/compliance-attestations", payload, headers)

    def submit_attestation(self, attestation_id, headers):
        return self._request(
            "POST", f"/v1/compliance-attestations/{attestation_id}/submit", {}, headers
        )

    def adjudicate_attestation(self, attestation_id, payload, headers):
        return self._request(
            "POST", f"/v1/compliance-attestations/{attestation_id}/adjudicate",
            payload, headers,
        )

    # --- Recycling obligations ---
    def create_recycling_obligation(self, payload, headers):
        return self._request("POST", "/v1/recycling-obligations", payload, headers)

    def record_collection(self, obligation_id, payload, headers):
        return self._request(
            "POST", f"/v1/recycling-obligations/{obligation_id}/collections",
            payload, headers,
        )

    def settle_obligation(self, obligation_id, headers):
        return self._request(
            "POST", f"/v1/recycling-obligations/{obligation_id}/settle", {}, headers
        )

    # --- Warranty claims ---
    def create_warranty_claim(self, payload, headers):
        return self._request("POST", "/v1/warranty-claims", payload, headers)

    def review_claim(self, claim_id, headers):
        return self._request(
            "POST", f"/v1/warranty-claims/{claim_id}/review", {}, headers
        )

    def request_info_claim(self, claim_id, headers):
        return self._request(
            "POST", f"/v1/warranty-claims/{claim_id}/request-info", {}, headers
        )

    def adjudicate_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/v1/warranty-claims/{claim_id}/adjudicate", payload, headers
        )

    def pay_claim(self, claim_id, headers):
        return self._request("POST", f"/v1/warranty-claims/{claim_id}/pay", {}, headers)

    def withdraw_claim(self, claim_id, headers):
        return self._request(
            "POST", f"/v1/warranty-claims/{claim_id}/withdraw", {}, headers
        )

    # --- Test-driving operations ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/v1/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    def close_quarter(self, headers):
        return self._request("POST", "/v1/_ops/close_quarter", {}, headers)


api_client = ApiClient()
