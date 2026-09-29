"""API client: one method per endpoint defined in the PRD (§4).

All resources live under the `/packaging-oem` prefix.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

BASE = "/packaging-oem"


class ApiClient(GenericApiClient):
    # --- Customers -------------------------------------------------------
    def create_customer(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/customers", payload, headers)

    def get_customer(self, customer_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{BASE}/customers/{customer_id}", headers=headers)

    def suspend_customer(self, customer_id: str, headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/customers/{customer_id}/suspend", {}, headers)

    # --- Machine models --------------------------------------------------
    def create_machine_model(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/machine-models", payload, headers)

    def get_machine_model(self, machine_model_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{BASE}/machine-models/{machine_model_id}", headers=headers)

    def obsolete_machine_model(self, machine_model_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{BASE}/machine-models/{machine_model_id}/obsolete", {}, headers
        )

    # --- Production lines ------------------------------------------------
    def create_production_line(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/production-lines", payload, headers)

    def get_production_line(self, production_line_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{BASE}/production-lines/{production_line_id}", headers=headers
        )

    def maintenance_hold_production_line(self, production_line_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{BASE}/production-lines/{production_line_id}/maintenance-hold", {}, headers
        )

    # --- Field engineers -------------------------------------------------
    def create_field_engineer(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/field-engineers", payload, headers)

    def get_field_engineer(self, field_engineer_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{BASE}/field-engineers/{field_engineer_id}", headers=headers
        )

    def field_engineer_leave(self, field_engineer_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{BASE}/field-engineers/{field_engineer_id}/leave", {}, headers
        )

    # --- Logical clock ---------------------------------------------------
    def set_clock(self, to_iso8601: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{BASE}/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --- Product trials --------------------------------------------------
    def create_product_trial(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/product-trials", payload, headers)

    def list_product_trials(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{BASE}/product-trials", headers=headers, params=params)

    def get_product_trial(self, product_trial_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{BASE}/product-trials/{product_trial_id}", headers=headers)

    def start_testing_product_trial(self, product_trial_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{BASE}/product-trials/{product_trial_id}/start-testing", {}, headers
        )

    def record_result_product_trial(
        self, product_trial_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{BASE}/product-trials/{product_trial_id}/record-result", payload, headers
        )

    # --- Machine orders --------------------------------------------------
    def create_machine_order(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/machine-orders", payload, headers)

    def list_machine_orders(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{BASE}/machine-orders", headers=headers, params=params)

    def get_machine_order(self, machine_order_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{BASE}/machine-orders/{machine_order_id}", headers=headers)

    def engineer_machine_order(self, machine_order_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{BASE}/machine-orders/{machine_order_id}/engineer", {}, headers
        )

    def commercial_advance_machine_order(
        self, machine_order_id: str, target_status: str, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{BASE}/machine-orders/{machine_order_id}/commercial-advance",
            {"target_status": target_status},
            headers,
        )

    def ship_machine_order(self, machine_order_id: str, headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/machine-orders/{machine_order_id}/ship", {}, headers)

    # --- Long-lead components -------------------------------------------
    def create_long_lead_component(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/long-lead-components", payload, headers)

    def list_long_lead_components(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{BASE}/long-lead-components", headers=headers, params=params)

    def get_long_lead_component(self, long_lead_component_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{BASE}/long-lead-components/{long_lead_component_id}", headers=headers
        )

    def release_po_long_lead_component(self, long_lead_component_id: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"{BASE}/long-lead-components/{long_lead_component_id}/release-po",
            {},
            headers,
        )

    def receive_long_lead_component(self, long_lead_component_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{BASE}/long-lead-components/{long_lead_component_id}/receive", {}, headers
        )

    # --- Build slots -----------------------------------------------------
    def create_build_slot(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/build-slots", payload, headers)

    def list_build_slots(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{BASE}/build-slots", headers=headers, params=params)

    def get_build_slot(self, build_slot_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{BASE}/build-slots/{build_slot_id}", headers=headers)

    def confirm_build_slot(self, build_slot_id: str, headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/build-slots/{build_slot_id}/confirm", {}, headers)

    def start_build_build_slot(self, build_slot_id: str, headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/build-slots/{build_slot_id}/start-build", {}, headers)

    def release_build_slot(self, build_slot_id: str, headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/build-slots/{build_slot_id}/release", {}, headers)

    # --- Acceptance tests ------------------------------------------------
    def create_acceptance_test(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/acceptance-tests", payload, headers)

    def list_acceptance_tests(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{BASE}/acceptance-tests", headers=headers, params=params)

    def get_acceptance_test(self, acceptance_test_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{BASE}/acceptance-tests/{acceptance_test_id}", headers=headers
        )

    def start_acceptance_test(
        self, acceptance_test_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{BASE}/acceptance-tests/{acceptance_test_id}/start", payload, headers
        )

    def finalize_acceptance_test(
        self, acceptance_test_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"{BASE}/acceptance-tests/{acceptance_test_id}/finalize", payload, headers
        )

    # --- Installed machines ----------------------------------------------
    def create_installed_machine(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/installed-machines", payload, headers)

    def list_installed_machines(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{BASE}/installed-machines", headers=headers, params=params)

    def get_installed_machine(self, installed_machine_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{BASE}/installed-machines/{installed_machine_id}", headers=headers
        )

    # --- Format kits -----------------------------------------------------
    def create_format_kit(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/format-kits", payload, headers)

    def list_format_kits(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{BASE}/format-kits", headers=headers, params=params)

    def get_format_kit(self, format_kit_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{BASE}/format-kits/{format_kit_id}", headers=headers)

    def quote_format_kit(self, format_kit_id: str, headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/format-kits/{format_kit_id}/quote", {}, headers)

    def order_format_kit(self, format_kit_id: str, headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/format-kits/{format_kit_id}/order", {}, headers)

    def deliver_format_kit(self, format_kit_id: str, headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/format-kits/{format_kit_id}/deliver", {}, headers)

    # --- Service contracts -----------------------------------------------
    def create_service_contract(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/service-contracts", payload, headers)

    def list_service_contracts(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{BASE}/service-contracts", headers=headers, params=params)

    def get_service_contract(self, service_contract_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{BASE}/service-contracts/{service_contract_id}", headers=headers
        )

    def activate_service_contract(self, service_contract_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{BASE}/service-contracts/{service_contract_id}/activate", {}, headers
        )

    def expire_service_contract(self, service_contract_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{BASE}/service-contracts/{service_contract_id}/expire", {}, headers
        )

    def terminate_service_contract(self, service_contract_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{BASE}/service-contracts/{service_contract_id}/terminate", {}, headers
        )

    # --- Maintenance visits ----------------------------------------------
    def create_pm_visit(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/pm-visits", payload, headers)

    def list_pm_visits(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{BASE}/pm-visits", headers=headers, params=params)

    def get_pm_visit(self, pm_visit_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{BASE}/pm-visits/{pm_visit_id}", headers=headers)

    def complete_pm_visit(
        self, pm_visit_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"{BASE}/pm-visits/{pm_visit_id}/complete", payload, headers)

    def cancel_pm_visit(self, pm_visit_id: str, headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/pm-visits/{pm_visit_id}/cancel", {}, headers)

    # --- Warranty claims -------------------------------------------------
    def create_warranty_claim(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/warranty-claims", payload, headers)

    def list_warranty_claims(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{BASE}/warranty-claims", headers=headers, params=params)

    def get_warranty_claim(self, warranty_claim_id: str, headers: Dict[str, str]):
        return self._request("GET", f"{BASE}/warranty-claims/{warranty_claim_id}", headers=headers)

    def create_warranty_claim_line(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/warranty-claim-lines", payload, headers)

    def list_warranty_claim_lines(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"{BASE}/warranty-claim-lines", headers=headers, params=params)

    def get_warranty_claim_line(self, claim_line_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"{BASE}/warranty-claim-lines/{claim_line_id}", headers=headers
        )

    def review_product_variation_warranty_claim(
        self, warranty_claim_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{BASE}/warranty-claims/{warranty_claim_id}/reviews/product-variation",
            {},
            headers,
        )

    def review_defect_warranty_claim(self, warranty_claim_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{BASE}/warranty-claims/{warranty_claim_id}/reviews/defect", {}, headers
        )

    def adjudicate_warranty_claim(
        self, warranty_claim_id: str, resolution: str, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{BASE}/warranty-claims/{warranty_claim_id}/adjudicate",
            {"resolution": resolution},
            headers,
        )

    def void_warranty_claim(self, warranty_claim_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"{BASE}/warranty-claims/{warranty_claim_id}/void", {}, headers
        )

    # --- Stocking recommendations ----------------------------------------
    def create_stocking_recommendation(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"{BASE}/stocking-recommendations", payload, headers)

    def list_stocking_recommendations(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"{BASE}/stocking-recommendations", headers=headers, params=params
        )

    def get_stocking_recommendation(
        self, stocking_recommendation_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "GET",
            f"{BASE}/stocking-recommendations/{stocking_recommendation_id}",
            headers=headers,
        )

    def obsolescence_notice_stocking_recommendation(
        self, stocking_recommendation_id: str, notice_type: str, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"{BASE}/stocking-recommendations/{stocking_recommendation_id}/obsolescence-notice",
            {"notice_type": notice_type},
            headers,
        )


api_client = ApiClient()
