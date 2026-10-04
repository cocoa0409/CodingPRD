"""API client: one method per endpoint defined in the PRD (section 4).

Inherits base-url injection from GenericApiClient: the runner sets
API_BASE_URL in the environment before pytest starts, and the base class
picks it up. All methods return the raw requests.Response; envelope shape
(meta / response_type / data, error_id on errors, pagination fields on lists)
is validated by the framework validators.

Action endpoints whose PRD input list is empty send an empty JSON object body
(matching the {} payloads used throughout the PRD workflow narratives).
"""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/drinkware"


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, payload, headers):
        """POST /drinkware/_clock/set_current_utc — payload: {to_iso8601}."""
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # Dealers
    # ------------------------------------------------------------------
    def create_dealer(self, payload, headers):
        return self._request("POST", f"{PREFIX}/dealers", payload, headers)

    def get_dealer(self, dealer_id, headers):
        return self._request("GET", f"{PREFIX}/dealers/{dealer_id}", headers=headers)

    def list_dealers(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/dealers", headers=headers, params=params)

    def suspend_dealer(self, dealer_id, payload, headers):
        return self._request("POST", f"{PREFIX}/dealers/{dealer_id}/suspend",
                             payload, headers)

    def reinstate_dealer(self, dealer_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/dealers/{dealer_id}/reinstate",
                             payload if payload is not None else {}, headers)

    def terminate_dealer(self, dealer_id, payload, headers):
        return self._request("POST", f"{PREFIX}/dealers/{dealer_id}/terminate",
                             payload, headers)

    # ------------------------------------------------------------------
    # Dealer applications
    # ------------------------------------------------------------------
    def create_dealer_application(self, payload, headers):
        return self._request("POST", f"{PREFIX}/dealer-applications", payload, headers)

    def get_dealer_application(self, application_id, headers):
        return self._request("GET", f"{PREFIX}/dealer-applications/{application_id}",
                             headers=headers)

    def list_dealer_applications(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/dealer-applications",
                             headers=headers, params=params)

    def schedule_inspection(self, application_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/dealer-applications/{application_id}/schedule-inspection",
            payload, headers)

    def record_inspection(self, application_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/dealer-applications/{application_id}/record-inspection",
            payload, headers)

    def verify_documents(self, application_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/dealer-applications/{application_id}/verify-documents",
            payload, headers)

    def decide_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/dealer-applications/{application_id}/decide",
            payload, headers)

    # ------------------------------------------------------------------
    # Enforcement cases
    # ------------------------------------------------------------------
    def create_enforcement_case(self, payload, headers):
        return self._request("POST", f"{PREFIX}/enforcement-cases", payload, headers)

    def get_enforcement_case(self, case_id, headers):
        return self._request("GET", f"{PREFIX}/enforcement-cases/{case_id}",
                             headers=headers)

    def list_enforcement_cases(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/enforcement-cases",
                             headers=headers, params=params)

    def resolve_enforcement_case(self, case_id, payload, headers):
        return self._request("POST", f"{PREFIX}/enforcement-cases/{case_id}/resolve",
                             payload, headers)

    def overturn_enforcement_case(self, case_id, payload, headers):
        return self._request("POST", f"{PREFIX}/enforcement-cases/{case_id}/overturn",
                             payload, headers)

    # ------------------------------------------------------------------
    # Product lines
    # ------------------------------------------------------------------
    def create_product_line(self, payload, headers):
        return self._request("POST", f"{PREFIX}/product-lines", payload, headers)

    def get_product_line(self, product_line_id, headers):
        return self._request("GET", f"{PREFIX}/product-lines/{product_line_id}",
                             headers=headers)

    def list_product_lines(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/product-lines",
                             headers=headers, params=params)

    def discontinue_product_line(self, product_line_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/product-lines/{product_line_id}/discontinue",
            payload if payload is not None else {}, headers)

    # ------------------------------------------------------------------
    # Colorway drops
    # ------------------------------------------------------------------
    def create_colorway_drop(self, payload, headers):
        return self._request("POST", f"{PREFIX}/colorway-drops", payload, headers)

    def get_colorway_drop(self, drop_id, headers):
        return self._request("GET", f"{PREFIX}/colorway-drops/{drop_id}", headers=headers)

    def list_colorway_drops(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/colorway-drops",
                             headers=headers, params=params)

    def open_allocation(self, drop_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/colorway-drops/{drop_id}/open-allocation",
                             payload if payload is not None else {}, headers)

    def lock_allocation(self, drop_id, payload, headers):
        """Lock allocation — payload: {expected_drop_version}."""
        return self._request("POST", f"{PREFIX}/colorway-drops/{drop_id}/lock-allocation",
                             payload, headers)

    # ------------------------------------------------------------------
    # Launch allocations
    # ------------------------------------------------------------------
    def create_launch_allocation(self, payload, headers):
        return self._request("POST", f"{PREFIX}/launch-allocations", payload, headers)

    def get_launch_allocation(self, allocation_id, headers):
        return self._request("GET", f"{PREFIX}/launch-allocations/{allocation_id}",
                             headers=headers)

    def list_launch_allocations(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/launch-allocations",
                             headers=headers, params=params)

    def forfeit_launch_allocation(self, allocation_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/launch-allocations/{allocation_id}/forfeit",
            payload if payload is not None else {}, headers)

    # ------------------------------------------------------------------
    # Customization orders
    # ------------------------------------------------------------------
    def create_customization_order(self, payload, headers):
        return self._request("POST", f"{PREFIX}/customization-orders", payload, headers)

    def get_customization_order(self, order_id, headers):
        return self._request("GET", f"{PREFIX}/customization-orders/{order_id}",
                             headers=headers)

    def list_customization_orders(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/customization-orders",
                             headers=headers, params=params)

    def submit_order(self, order_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/customization-orders/{order_id}/submit",
                             payload if payload is not None else {}, headers)

    def cancel_order(self, order_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/customization-orders/{order_id}/cancel",
                             payload if payload is not None else {}, headers)

    def reserve_slot(self, order_id, payload, headers):
        """Reserve capacity — payload: {slot_id}."""
        return self._request(
            "POST", f"{PREFIX}/customization-orders/{order_id}/reserve-slot",
            payload, headers)

    def release_slot(self, order_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/customization-orders/{order_id}/release-slot",
            payload if payload is not None else {}, headers)

    def start_production(self, order_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/customization-orders/{order_id}/start-production",
            payload if payload is not None else {}, headers)

    def complete_production(self, order_id, payload, headers):
        """Complete a production run — payload: {qc_outcome}."""
        return self._request(
            "POST", f"{PREFIX}/customization-orders/{order_id}/complete-production",
            payload, headers)

    def request_return(self, order_id, payload, headers):
        """Request a return — payload: {reason, affected_unit_count}."""
        return self._request(
            "POST", f"{PREFIX}/customization-orders/{order_id}/request-return",
            payload, headers)

    def decide_return(self, order_id, payload, headers):
        """Decide a return — payload: {decision, resolution?, decision_notes?}."""
        return self._request(
            "POST", f"{PREFIX}/customization-orders/{order_id}/decide-return",
            payload, headers)

    # ------------------------------------------------------------------
    # Artwork proofs
    # ------------------------------------------------------------------
    def create_artwork_proof(self, payload, headers):
        return self._request("POST", f"{PREFIX}/artwork-proofs", payload, headers)

    def get_artwork_proof(self, proof_id, headers):
        return self._request("GET", f"{PREFIX}/artwork-proofs/{proof_id}", headers=headers)

    def list_artwork_proofs(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/artwork-proofs",
                             headers=headers, params=params)

    def approve_proof(self, proof_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/artwork-proofs/{proof_id}/approve",
                             payload if payload is not None else {}, headers)

    def request_proof_changes(self, proof_id, payload, headers):
        """Request changes — payload: {review_notes}."""
        return self._request(
            "POST", f"{PREFIX}/artwork-proofs/{proof_id}/request-changes",
            payload, headers)

    # ------------------------------------------------------------------
    # Print slots
    # ------------------------------------------------------------------
    def create_print_slot(self, payload, headers):
        return self._request("POST", f"{PREFIX}/print-slots", payload, headers)

    def get_print_slot(self, slot_id, headers):
        return self._request("GET", f"{PREFIX}/print-slots/{slot_id}", headers=headers)

    def list_print_slots(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/print-slots",
                             headers=headers, params=params)

    def lock_print_slot(self, slot_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/print-slots/{slot_id}/lock",
                             payload if payload is not None else {}, headers)

    # ------------------------------------------------------------------
    # Warranty claims
    # ------------------------------------------------------------------
    def create_warranty_claim(self, payload, headers):
        return self._request("POST", f"{PREFIX}/warranty-claims", payload, headers)

    def get_warranty_claim(self, claim_id, headers):
        return self._request("GET", f"{PREFIX}/warranty-claims/{claim_id}",
                             headers=headers)

    def list_warranty_claims(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/warranty-claims",
                             headers=headers, params=params)

    def start_claim_review(self, claim_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/warranty-claims/{claim_id}/start-review",
                             payload if payload is not None else {}, headers)

    def decide_warranty_claim(self, claim_id, payload, headers):
        """Decide a claim — payload: {outcome, decision_reason}."""
        return self._request("POST", f"{PREFIX}/warranty-claims/{claim_id}/decide",
                             payload, headers)


api_client = ApiClient()
