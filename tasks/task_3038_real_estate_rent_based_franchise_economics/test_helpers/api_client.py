"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/franchise-system/_clock/set_current_utc", payload, headers)

    # --- sites ---
    def create_site(self, payload, headers):
        return self._request("POST", "/franchise-system/sites", payload, headers)

    def list_sites(self, headers, params=None):
        return self._request("GET", "/franchise-system/sites", headers=headers, params=params)

    def get_site(self, site_id, headers):
        return self._request("GET", f"/franchise-system/sites/{site_id}", headers=headers)

    def divest_site(self, site_id, headers):
        return self._request("POST", f"/franchise-system/sites/{site_id}/divest", headers=headers)

    def list_site_stores(self, site_id, headers, params=None):
        return self._request("GET", f"/franchise-system/sites/{site_id}/stores", headers=headers, params=params)

    # --- operators ---
    def create_operator(self, payload, headers):
        return self._request("POST", "/franchise-system/operators", payload, headers)

    def list_operators(self, headers, params=None):
        return self._request("GET", "/franchise-system/operators", headers=headers, params=params)

    def get_operator(self, operator_id, headers):
        return self._request("GET", f"/franchise-system/operators/{operator_id}", headers=headers)

    def approve_operator(self, operator_id, headers):
        return self._request("POST", f"/franchise-system/operators/{operator_id}/approve", headers=headers)

    def suspend_operator(self, operator_id, headers):
        return self._request("POST", f"/franchise-system/operators/{operator_id}/suspend", headers=headers)

    def reinstate_operator(self, operator_id, headers):
        return self._request("POST", f"/franchise-system/operators/{operator_id}/reinstate", headers=headers)

    def update_fiscal_snapshot(self, operator_id, payload, headers):
        return self._request("PUT", f"/franchise-system/operators/{operator_id}/fiscal-snapshot", payload, headers)

    def deposit_escrow(self, operator_id, payload, headers):
        return self._request("POST", f"/franchise-system/operators/{operator_id}/escrow-deposits", payload, headers)

    # --- capacity reviews ---
    def create_capacity_review(self, payload, headers):
        return self._request("POST", "/franchise-system/capacity-reviews", payload, headers)

    def list_capacity_reviews(self, headers, params=None):
        return self._request("GET", "/franchise-system/capacity-reviews", headers=headers, params=params)

    def get_capacity_review(self, review_id, headers):
        return self._request("GET", f"/franchise-system/capacity-reviews/{review_id}", headers=headers)

    def submit_capacity_review(self, review_id, headers):
        return self._request("POST", f"/franchise-system/capacity-reviews/{review_id}/submit", headers=headers)

    # --- stores ---
    def create_store(self, payload, headers):
        return self._request("POST", "/franchise-system/stores", payload, headers)

    def list_stores(self, headers, params=None):
        return self._request("GET", "/franchise-system/stores", headers=headers, params=params)

    def get_store(self, store_id, headers):
        return self._request("GET", f"/franchise-system/stores/{store_id}", headers=headers)

    def open_store(self, store_id, headers):
        return self._request("POST", f"/franchise-system/stores/{store_id}/open", headers=headers)

    # --- franchise agreements ---
    def create_agreement(self, payload, headers):
        return self._request("POST", "/franchise-system/agreements", payload, headers)

    def list_agreements(self, headers, params=None):
        return self._request("GET", "/franchise-system/agreements", headers=headers, params=params)

    def get_agreement(self, agreement_id, headers):
        return self._request("GET", f"/franchise-system/agreements/{agreement_id}", headers=headers)

    def submit_agreement(self, agreement_id, headers):
        return self._request("POST", f"/franchise-system/agreements/{agreement_id}/submit", headers=headers)

    def record_fee_payment(self, agreement_id, payload, headers):
        return self._request("POST", f"/franchise-system/agreements/{agreement_id}/record-fee-payment", payload, headers)

    # --- subleases ---
    def create_sublease(self, payload, headers):
        return self._request("POST", "/franchise-system/subleases", payload, headers)

    def list_subleases(self, headers, params=None):
        return self._request("GET", "/franchise-system/subleases", headers=headers, params=params)

    def get_sublease(self, sublease_id, headers):
        return self._request("GET", f"/franchise-system/subleases/{sublease_id}", headers=headers)

    def activate_sublease(self, sublease_id, headers):
        return self._request("POST", f"/franchise-system/subleases/{sublease_id}/activate", headers=headers)

    def declare_default(self, sublease_id, payload, headers):
        return self._request("POST", f"/franchise-system/subleases/{sublease_id}/declare-default", payload, headers)

    def reinstate_sublease(self, sublease_id, headers):
        return self._request("POST", f"/franchise-system/subleases/{sublease_id}/reinstate", headers=headers)

    # --- default events ---
    def list_default_events(self, headers, params=None):
        return self._request("GET", "/franchise-system/default-events", headers=headers, params=params)

    def get_default_event(self, default_id, headers):
        return self._request("GET", f"/franchise-system/default-events/{default_id}", headers=headers)

    def cure_default(self, default_id, headers):
        return self._request("POST", f"/franchise-system/default-events/{default_id}/cure", headers=headers)

    def repossess_default(self, default_id, headers):
        return self._request("POST", f"/franchise-system/default-events/{default_id}/repossess", headers=headers)

    # --- sales reports ---
    def create_sales_report(self, payload, headers):
        return self._request("POST", "/franchise-system/sales-reports", payload, headers)

    def list_sales_reports(self, headers, params=None):
        return self._request("GET", "/franchise-system/sales-reports", headers=headers, params=params)

    def get_sales_report(self, report_id, headers):
        return self._request("GET", f"/franchise-system/sales-reports/{report_id}", headers=headers)

    def submit_sales_report(self, report_id, headers):
        return self._request("POST", f"/franchise-system/sales-reports/{report_id}/submit", headers=headers)

    # --- rent charges ---
    def create_rent_charge(self, payload, headers):
        return self._request("POST", "/franchise-system/rent-charges", payload, headers)

    def list_rent_charges(self, headers, params=None):
        return self._request("GET", "/franchise-system/rent-charges", headers=headers, params=params)

    def get_rent_charge(self, charge_id, headers):
        return self._request("GET", f"/franchise-system/rent-charges/{charge_id}", headers=headers)

    def pay_rent_charge(self, charge_id, payload, headers):
        return self._request("POST", f"/franchise-system/rent-charges/{charge_id}/pay", payload, headers)

    # --- billing runs ---
    def post_billing_run(self, payload, headers):
        return self._request("POST", "/franchise-system/billing-runs", payload, headers)

    # --- fund assessments ---
    def list_fund_assessments(self, headers, params=None):
        return self._request("GET", "/franchise-system/fund-assessments", headers=headers, params=params)

    def get_fund_assessment(self, assessment_id, headers):
        return self._request("GET", f"/franchise-system/fund-assessments/{assessment_id}", headers=headers)

    def pay_fund_assessment(self, assessment_id, headers):
        return self._request("POST", f"/franchise-system/fund-assessments/{assessment_id}/pay", headers=headers)

    def annual_reconciliation(self, store_id, payload, headers):
        return self._request("POST", f"/franchise-system/stores/{store_id}/annual-reconciliation", payload, headers)

    # --- reinvestment obligations ---
    def create_reinvestment_obligation(self, payload, headers):
        return self._request("POST", "/franchise-system/reinvestment-obligations", payload, headers)

    def list_reinvestment_obligations(self, headers, params=None):
        return self._request("GET", "/franchise-system/reinvestment-obligations", headers=headers, params=params)

    def get_reinvestment_obligation(self, obligation_id, headers):
        return self._request("GET", f"/franchise-system/reinvestment-obligations/{obligation_id}", headers=headers)

    def submit_spend(self, obligation_id, payload, headers):
        return self._request("POST", f"/franchise-system/reinvestment-obligations/{obligation_id}/submit-spend", payload, headers)

    def verify_spend(self, obligation_id, headers):
        return self._request("POST", f"/franchise-system/reinvestment-obligations/{obligation_id}/verify-spend", headers=headers)

    def reject_spend(self, obligation_id, headers):
        return self._request("POST", f"/franchise-system/reinvestment-obligations/{obligation_id}/reject-spend", headers=headers)

    # --- advertising funds ---
    def create_advertising_fund(self, payload, headers):
        return self._request("POST", "/franchise-system/advertising-funds", payload, headers)

    def list_advertising_funds(self, headers, params=None):
        return self._request("GET", "/franchise-system/advertising-funds", headers=headers, params=params)

    def get_advertising_fund(self, fund_id, headers):
        return self._request("GET", f"/franchise-system/advertising-funds/{fund_id}", headers=headers)

    def freeze_fund(self, fund_id, headers):
        return self._request("POST", f"/franchise-system/advertising-funds/{fund_id}/freeze", headers=headers)

    def unfreeze_fund(self, fund_id, headers):
        return self._request("POST", f"/franchise-system/advertising-funds/{fund_id}/unfreeze", headers=headers)

    def disburse_fund(self, fund_id, payload, headers):
        return self._request("POST", f"/franchise-system/advertising-funds/{fund_id}/disburse", payload, headers)

    # --- co-op assessments ---
    def create_coop_assessment(self, payload, headers):
        return self._request("POST", "/franchise-system/coop-assessments", payload, headers)

    def list_coop_assessments(self, headers, params=None):
        return self._request("GET", "/franchise-system/coop-assessments", headers=headers, params=params)

    def get_coop_assessment(self, assessment_id, headers):
        return self._request("GET", f"/franchise-system/coop-assessments/{assessment_id}", headers=headers)

    def pay_coop_assessment(self, assessment_id, headers):
        return self._request("POST", f"/franchise-system/coop-assessments/{assessment_id}/pay", headers=headers)


api_client = ApiClient()
