"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- clock / cycle ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def run_cycle(self, headers):
        return self._request("POST", "/_cycle/run", {}, headers)

    # --- product categories ---
    def create_product_category(self, payload, headers):
        return self._request("POST", "/product-categories", payload, headers)

    def get_product_category(self, category_id, headers):
        return self._request("GET", f"/product-categories/{category_id}", headers=headers)

    # --- test programs ---
    def create_test_program(self, payload, headers):
        return self._request("POST", "/test-programs", payload, headers)

    def list_test_programs(self, headers, params=None):
        return self._request("GET", "/test-programs", headers=headers, params=params)

    def get_test_program(self, program_id, headers):
        return self._request("GET", f"/test-programs/{program_id}", headers=headers)

    def transition_test_program(self, program_id, payload, headers):
        return self._request("POST", f"/test-programs/{program_id}/transitions", payload, headers)

    # --- lab protocols ---
    def create_lab_protocol(self, payload, headers):
        return self._request("POST", "/lab-protocols", payload, headers)

    def list_lab_protocols(self, headers, params=None):
        return self._request("GET", "/lab-protocols", headers=headers, params=params)

    def get_lab_protocol(self, protocol_id, headers):
        return self._request("GET", f"/lab-protocols/{protocol_id}", headers=headers)

    def transition_lab_protocol(self, protocol_id, payload, headers):
        return self._request("POST", f"/lab-protocols/{protocol_id}/transitions", payload, headers)

    # --- test samples ---
    def create_test_sample(self, payload, headers):
        return self._request("POST", "/test-samples", payload, headers)

    def list_test_samples(self, headers, params=None):
        return self._request("GET", "/test-samples", headers=headers, params=params)

    def get_test_sample(self, sample_id, headers):
        return self._request("GET", f"/test-samples/{sample_id}", headers=headers)

    def list_sample_measurements(self, sample_id, headers):
        return self._request("GET", f"/test-samples/{sample_id}/measurements", headers=headers)

    # --- purchase orders ---
    def create_purchase_order(self, payload, headers):
        return self._request("POST", "/purchase-orders", payload, headers)

    def list_purchase_orders(self, headers, params=None):
        return self._request("GET", "/purchase-orders", headers=headers, params=params)

    def get_purchase_order(self, po_id, headers):
        return self._request("GET", f"/purchase-orders/{po_id}", headers=headers)

    def transition_purchase_order(self, po_id, payload, headers):
        return self._request("POST", f"/purchase-orders/{po_id}/transitions", payload, headers)

    # --- measurements ---
    def create_measurement(self, payload, headers):
        return self._request("POST", "/measurements", payload, headers)

    # --- survey waves ---
    def create_survey_wave(self, payload, headers):
        return self._request("POST", "/survey-waves", payload, headers)

    def list_survey_waves(self, headers, params=None):
        return self._request("GET", "/survey-waves", headers=headers, params=params)

    def get_survey_wave(self, wave_id, headers):
        return self._request("GET", f"/survey-waves/{wave_id}", headers=headers)

    def transition_survey_wave(self, wave_id, payload, headers):
        return self._request("POST", f"/survey-waves/{wave_id}/transitions", payload, headers)

    # --- rating publications ---
    def create_rating_publication(self, payload, headers):
        return self._request("POST", "/rating-publications", payload, headers)

    def list_rating_publications(self, headers, params=None):
        return self._request("GET", "/rating-publications", headers=headers, params=params)

    def get_rating_publication(self, publication_id, headers):
        return self._request("GET", f"/rating-publications/{publication_id}", headers=headers)

    def transition_rating_publication(self, publication_id, payload, headers):
        return self._request("POST", f"/rating-publications/{publication_id}/transitions", payload, headers)

    # --- safety findings ---
    def create_safety_finding(self, payload, headers):
        return self._request("POST", "/safety-findings", payload, headers)

    def list_safety_findings(self, headers, params=None):
        return self._request("GET", "/safety-findings", headers=headers, params=params)

    def get_safety_finding(self, finding_id, headers):
        return self._request("GET", f"/safety-findings/{finding_id}", headers=headers)

    def transition_safety_finding(self, finding_id, payload, headers):
        return self._request("POST", f"/safety-findings/{finding_id}/transitions", payload, headers)

    # --- members ---
    def create_member(self, payload, headers):
        return self._request("POST", "/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def transition_member(self, member_id, payload, headers):
        return self._request("POST", f"/members/{member_id}/transitions", payload, headers)


api_client = ApiClient()
