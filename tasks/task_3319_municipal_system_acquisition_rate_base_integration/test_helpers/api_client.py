"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- AcquisitionTarget ---
    def create_target(self, payload, headers):
        return self._request("POST", "/acquisitions/targets", payload, headers)

    def get_target(self, target_id, headers):
        return self._request("GET", f"/acquisitions/targets/{target_id}", headers=headers)

    def list_targets(self, headers, params=None):
        return self._request("GET", "/acquisitions/targets", headers=headers, params=params)

    def close_target(self, target_id, headers):
        return self._request("POST", f"/acquisitions/targets/{target_id}/close", {}, headers)

    # --- ConditionAssessment ---
    def create_assessment(self, target_id, payload, headers):
        return self._request("POST", f"/acquisitions/targets/{target_id}/assessments", payload, headers)

    def list_assessments(self, target_id, headers, params=None):
        return self._request("GET", f"/acquisitions/targets/{target_id}/assessments", headers=headers, params=params)

    def get_assessment(self, assessment_id, headers):
        return self._request("GET", f"/acquisitions/assessments/{assessment_id}", headers=headers)

    def submit_assessment(self, assessment_id, headers):
        return self._request("POST", f"/acquisitions/assessments/{assessment_id}/submit", {}, headers)

    def accept_assessment(self, assessment_id, headers):
        return self._request("POST", f"/acquisitions/assessments/{assessment_id}/accept", {}, headers)

    def reject_assessment(self, assessment_id, headers):
        return self._request("POST", f"/acquisitions/assessments/{assessment_id}/reject", {}, headers)

    # --- CapitalNeedItem ---
    def create_capital_item(self, assessment_id, payload, headers):
        return self._request("POST", f"/acquisitions/assessments/{assessment_id}/capital-items", payload, headers)

    def list_capital_items(self, assessment_id, headers, params=None):
        return self._request("GET", f"/acquisitions/assessments/{assessment_id}/capital-items", headers=headers, params=params)

    def get_capital_item(self, item_id, headers):
        return self._request("GET", f"/acquisitions/capital-items/{item_id}", headers=headers)

    def schedule_capital_item(self, item_id, payload, headers):
        return self._request("POST", f"/acquisitions/capital-items/{item_id}/schedule", payload, headers)

    def execute_capital_item(self, item_id, headers):
        return self._request("POST", f"/acquisitions/capital-items/{item_id}/execute", {}, headers)

    def split_capital_item(self, item_id, payload, headers):
        return self._request("POST", f"/acquisitions/capital-items/{item_id}/split", payload, headers)

    def cancel_capital_item(self, item_id, headers):
        return self._request("POST", f"/acquisitions/capital-items/{item_id}/cancel", {}, headers)

    # --- ValuationCase / ValuationEntry ---
    def create_valuation_case(self, target_id, payload, headers):
        return self._request("POST", f"/acquisitions/targets/{target_id}/valuation-cases", payload, headers)

    def list_valuation_cases(self, target_id, headers, params=None):
        return self._request("GET", f"/acquisitions/targets/{target_id}/valuation-cases", headers=headers, params=params)

    def get_valuation_case(self, case_id, headers):
        return self._request("GET", f"/acquisitions/valuation-cases/{case_id}", headers=headers)

    def create_valuation_entry(self, case_id, payload, headers):
        return self._request("POST", f"/acquisitions/valuation-cases/{case_id}/entries", payload, headers)

    def list_valuation_entries(self, case_id, headers, params=None):
        return self._request("GET", f"/acquisitions/valuation-cases/{case_id}/entries", headers=headers, params=params)

    def finalize_valuation_case(self, case_id, payload, headers):
        return self._request("POST", f"/acquisitions/valuation-cases/{case_id}/finalize", payload, headers)

    # --- CouncilEvent ---
    def create_council_event(self, target_id, payload, headers):
        return self._request("POST", f"/acquisitions/targets/{target_id}/council-events", payload, headers)

    def list_council_events(self, target_id, headers, params=None):
        return self._request("GET", f"/acquisitions/targets/{target_id}/council-events", headers=headers, params=params)

    def get_council_event(self, event_id, headers):
        return self._request("GET", f"/acquisitions/council-events/{event_id}", headers=headers)

    def record_council_outcome(self, event_id, payload, headers):
        return self._request("POST", f"/acquisitions/council-events/{event_id}/record-outcome", payload, headers)

    # --- RegulatoryApplication ---
    def create_regulatory_application(self, target_id, payload, headers):
        return self._request("POST", f"/acquisitions/targets/{target_id}/regulatory-applications", payload, headers)

    def list_regulatory_applications(self, target_id, headers, params=None):
        return self._request("GET", f"/acquisitions/targets/{target_id}/regulatory-applications", headers=headers, params=params)

    def get_regulatory_application(self, application_id, headers):
        return self._request("GET", f"/acquisitions/regulatory-applications/{application_id}", headers=headers)

    def decide_regulatory_application(self, application_id, payload, headers):
        return self._request("POST", f"/acquisitions/regulatory-applications/{application_id}/decide", payload, headers)

    def refile_regulatory_application(self, application_id, payload, headers):
        return self._request("POST", f"/acquisitions/regulatory-applications/{application_id}/refile", payload, headers)

    # --- CustomerAccount ---
    def create_customer_account(self, target_id, payload, headers):
        return self._request("POST", f"/acquisitions/targets/{target_id}/customer-accounts", payload, headers)

    def list_customer_accounts(self, target_id, headers, params=None):
        return self._request("GET", f"/acquisitions/targets/{target_id}/customer-accounts", headers=headers, params=params)

    def get_customer_account(self, account_id, headers):
        return self._request("GET", f"/acquisitions/customer-accounts/{account_id}", headers=headers)

    def migrate_customer_account(self, account_id, headers):
        return self._request("POST", f"/acquisitions/customer-accounts/{account_id}/migrate", {}, headers)

    def consolidate_customer_account(self, account_id, headers):
        return self._request("POST", f"/acquisitions/customer-accounts/{account_id}/consolidate", {}, headers)

    def orphan_customer_account(self, account_id, headers):
        return self._request("POST", f"/acquisitions/customer-accounts/{account_id}/orphan", {}, headers)

    # --- TransitionItem ---
    def list_transition_items(self, target_id, headers, params=None):
        return self._request("GET", f"/acquisitions/targets/{target_id}/transition-items", headers=headers, params=params)

    def get_transition_item(self, item_id, headers):
        return self._request("GET", f"/acquisitions/transition-items/{item_id}", headers=headers)

    def resolve_transition_item(self, item_id, payload, headers):
        return self._request("POST", f"/acquisitions/transition-items/{item_id}/resolve", payload, headers)

    # --- EmployeeTransition ---
    def create_employee_transition(self, target_id, payload, headers):
        return self._request("POST", f"/acquisitions/targets/{target_id}/employee-transitions", payload, headers)

    def list_employee_transitions(self, target_id, headers, params=None):
        return self._request("GET", f"/acquisitions/targets/{target_id}/employee-transitions", headers=headers, params=params)

    def get_employee_transition(self, employee_id, headers):
        return self._request("GET", f"/acquisitions/employee-transitions/{employee_id}", headers=headers)

    def respond_to_offer(self, employee_id, payload, headers):
        return self._request("POST", f"/acquisitions/employee-transitions/{employee_id}/offer-response", payload, headers)

    # --- TariffCase ---
    def create_tariff_case(self, target_id, payload, headers):
        return self._request("POST", f"/acquisitions/targets/{target_id}/tariff-cases", payload, headers)

    def list_tariff_cases(self, target_id, headers, params=None):
        return self._request("GET", f"/acquisitions/targets/{target_id}/tariff-cases", headers=headers, params=params)

    def get_tariff_case(self, case_id, headers):
        return self._request("GET", f"/acquisitions/tariff-cases/{case_id}", headers=headers)

    def adopt_tariff_case(self, case_id, headers):
        return self._request("POST", f"/acquisitions/tariff-cases/{case_id}/adopt", {}, headers)


api_client = ApiClient()
