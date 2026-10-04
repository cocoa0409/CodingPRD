"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """PRD-specific endpoint methods; HTTP plumbing lives in GenericApiClient."""

    # --- logical clock (test-driving) ---
    def set_clock(self, current_utc, headers):
        return self._request("POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers)

    # --- jurisdictions ---
    def create_jurisdiction(self, payload, headers):
        return self._request("POST", "/stewardship/jurisdictions", payload, headers)

    def get_jurisdiction(self, jurisdiction_id, headers):
        return self._request("GET", f"/stewardship/jurisdictions/{jurisdiction_id}", headers=headers)

    # --- substances ---
    def create_substance(self, payload, headers):
        return self._request("POST", "/stewardship/substances", payload, headers)

    def get_substance(self, substance_id, headers):
        return self._request("GET", f"/stewardship/substances/{substance_id}", headers=headers)

    # --- formulations ---
    def create_formulation(self, payload, headers):
        return self._request("POST", "/stewardship/formulations", payload, headers)

    def get_formulation(self, formulation_id, headers):
        return self._request("GET", f"/stewardship/formulations/{formulation_id}", headers=headers)

    def list_formulations(self, headers, params=None):
        return self._request("GET", "/stewardship/formulations", headers=headers, params=params)

    def create_successor(self, formulation_id, payload, headers):
        return self._request("POST", f"/stewardship/formulations/{formulation_id}/successors", payload, headers)

    def discontinue_formulation(self, formulation_id, payload, headers):
        return self._request("POST", f"/stewardship/formulations/{formulation_id}/discontinue", payload, headers)

    # --- formulation components ---
    def create_formulation_component(self, payload, headers):
        return self._request("POST", "/stewardship/formulation-components", payload, headers)

    def get_formulation_component(self, component_id, headers):
        return self._request("GET", f"/stewardship/formulation-components/{component_id}", headers=headers)

    def list_formulation_components(self, headers, params=None):
        return self._request("GET", "/stewardship/formulation-components", headers=headers, params=params)

    # --- clearances ---
    def create_clearance(self, payload, headers):
        return self._request("POST", "/stewardship/clearances", payload, headers)

    def get_clearance(self, clearance_id, headers):
        return self._request("GET", f"/stewardship/clearances/{clearance_id}", headers=headers)

    def list_clearances(self, headers, params=None):
        return self._request("GET", "/stewardship/clearances", headers=headers, params=params)

    def decide_clearance(self, clearance_id, payload, headers):
        return self._request("POST", f"/stewardship/clearances/{clearance_id}/decision", payload, headers)

    # --- converters ---
    def create_converter(self, payload, headers):
        return self._request("POST", "/stewardship/converters", payload, headers)

    def get_converter(self, converter_id, headers):
        return self._request("GET", f"/stewardship/converters/{converter_id}", headers=headers)

    def record_audit(self, converter_id, payload, headers):
        return self._request("POST", f"/stewardship/converters/{converter_id}/record-audit", payload, headers)

    def authorize_converter(self, converter_id, headers):
        return self._request("POST", f"/stewardship/converters/{converter_id}/authorize", {}, headers)

    def suspend_converter(self, converter_id, headers):
        return self._request("POST", f"/stewardship/converters/{converter_id}/suspend", {}, headers)

    def reinstate_converter(self, converter_id, headers):
        return self._request("POST", f"/stewardship/converters/{converter_id}/reinstate", {}, headers)

    # --- distributors ---
    def create_distributor(self, payload, headers):
        return self._request("POST", "/stewardship/distributors", payload, headers)

    def get_distributor(self, distributor_id, headers):
        return self._request("GET", f"/stewardship/distributors/{distributor_id}", headers=headers)

    # --- converter authorizations ---
    def create_converter_authorization(self, payload, headers):
        return self._request("POST", "/stewardship/converter-authorizations", payload, headers)

    def get_converter_authorization(self, authorization_id, headers):
        return self._request("GET", f"/stewardship/converter-authorizations/{authorization_id}", headers=headers)

    def list_converter_authorizations(self, headers, params=None):
        return self._request("GET", "/stewardship/converter-authorizations", headers=headers, params=params)

    # --- application cases ---
    def create_application_case(self, payload, headers):
        return self._request("POST", "/stewardship/application-cases", payload, headers)

    def get_application_case(self, case_id, headers):
        return self._request("GET", f"/stewardship/application-cases/{case_id}", headers=headers)

    def list_application_cases(self, headers, params=None):
        return self._request("GET", "/stewardship/application-cases", headers=headers, params=params)

    def book_lab(self, case_id, payload, headers):
        return self._request("POST", f"/stewardship/application-cases/{case_id}/book-lab", payload, headers)

    def record_result(self, case_id, payload, headers):
        return self._request("POST", f"/stewardship/application-cases/{case_id}/record-result", payload, headers)

    # --- price agreements ---
    def create_price_agreement(self, payload, headers):
        return self._request("POST", "/stewardship/price-agreements", payload, headers)

    def get_price_agreement(self, agreement_id, headers):
        return self._request("GET", f"/stewardship/price-agreements/{agreement_id}", headers=headers)

    def list_price_agreements(self, headers, params=None):
        return self._request("GET", "/stewardship/price-agreements", headers=headers, params=params)

    # --- orders ---
    def create_order(self, payload, headers):
        return self._request("POST", "/stewardship/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/stewardship/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/stewardship/orders", headers=headers, params=params)

    def advance_order(self, order_id, headers):
        return self._request("POST", f"/stewardship/orders/{order_id}/advance", {}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/stewardship/orders/{order_id}/cancel", {}, headers)

    # --- rebate programs ---
    def create_rebate_program(self, payload, headers):
        return self._request("POST", "/stewardship/rebate-programs", payload, headers)

    def get_rebate_program(self, program_id, headers):
        return self._request("GET", f"/stewardship/rebate-programs/{program_id}", headers=headers)

    def list_rebate_programs(self, headers, params=None):
        return self._request("GET", "/stewardship/rebate-programs", headers=headers, params=params)

    def advance_rebate_program(self, program_id, headers):
        return self._request("POST", f"/stewardship/rebate-programs/{program_id}/advance", {}, headers)

    # --- rebate accruals ---
    def get_rebate_accrual(self, accrual_id, headers):
        return self._request("GET", f"/stewardship/rebate-accruals/{accrual_id}", headers=headers)

    def list_rebate_accruals(self, headers, params=None):
        return self._request("GET", "/stewardship/rebate-accruals", headers=headers, params=params)

    def claim_accrual(self, accrual_id, headers):
        return self._request("POST", f"/stewardship/rebate-accruals/{accrual_id}/claim", {}, headers)

    def pay_accrual(self, accrual_id, headers):
        return self._request("POST", f"/stewardship/rebate-accruals/{accrual_id}/pay", {}, headers)

    # --- phase-out programs ---
    def create_phase_out_program(self, payload, headers):
        return self._request("POST", "/stewardship/phase-out-programs", payload, headers)

    def get_phase_out_program(self, program_id, headers):
        return self._request("GET", f"/stewardship/phase-out-programs/{program_id}", headers=headers)

    def list_phase_out_programs(self, headers, params=None):
        return self._request("GET", "/stewardship/phase-out-programs", headers=headers, params=params)

    def advance_phase_out_program(self, program_id, payload, headers):
        return self._request("POST", f"/stewardship/phase-out-programs/{program_id}/advance", payload, headers)

    def record_qualification(self, program_id, payload, headers):
        return self._request("POST", f"/stewardship/phase-out-programs/{program_id}/record-qualification", payload, headers)

    # --- counterfeit reports ---
    def create_counterfeit_report(self, payload, headers):
        return self._request("POST", "/stewardship/counterfeit-reports", payload, headers)

    def get_counterfeit_report(self, report_id, headers):
        return self._request("GET", f"/stewardship/counterfeit-reports/{report_id}", headers=headers)

    def list_counterfeit_reports(self, headers, params=None):
        return self._request("GET", "/stewardship/counterfeit-reports", headers=headers, params=params)

    def disposition_report(self, report_id, payload, headers):
        return self._request("POST", f"/stewardship/counterfeit-reports/{report_id}/disposition", payload, headers)


api_client = ApiClient()
