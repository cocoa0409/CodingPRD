"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- logical clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)

    # ---- billing orgs ----
    def create_billing_org(self, payload, headers):
        return self._request("POST", "/api/billing-orgs", payload, headers)

    def get_billing_org(self, org_id, headers):
        return self._request("GET", f"/api/billing-orgs/{org_id}", headers=headers)

    def list_billing_orgs(self, headers, params=None):
        return self._request("GET", "/api/billing-orgs", headers=headers, params=params)

    def run_period_close(self, org_id, headers):
        return self._request("POST", f"/api/billing-orgs/{org_id}/run-period-close", {}, headers)

    # ---- linked accounts ----
    def create_linked_account(self, payload, headers):
        return self._request("POST", "/api/linked-accounts", payload, headers)

    def get_linked_account(self, account_id, headers):
        return self._request("GET", f"/api/linked-accounts/{account_id}", headers=headers)

    def list_linked_accounts(self, headers, params=None):
        return self._request("GET", "/api/linked-accounts", headers=headers, params=params)

    def suspend_linked_account(self, account_id, headers):
        return self._request("POST", f"/api/linked-accounts/{account_id}/suspend", {}, headers)

    def reactivate_linked_account(self, account_id, headers):
        return self._request("POST", f"/api/linked-accounts/{account_id}/reactivate", {}, headers)

    # ---- enterprise agreements ----
    def create_enterprise_agreement(self, payload, headers):
        return self._request("POST", "/api/enterprise-agreements", payload, headers)

    def get_enterprise_agreement(self, agreement_id, headers):
        return self._request("GET", f"/api/enterprise-agreements/{agreement_id}", headers=headers)

    def list_enterprise_agreements(self, headers, params=None):
        return self._request("GET", "/api/enterprise-agreements", headers=headers, params=params)

    def activate_agreement(self, agreement_id, headers):
        return self._request("POST", f"/api/enterprise-agreements/{agreement_id}/activate", {}, headers)

    def suspend_agreement(self, agreement_id, headers):
        return self._request("POST", f"/api/enterprise-agreements/{agreement_id}/suspend", {}, headers)

    def resume_agreement(self, agreement_id, headers):
        return self._request("POST", f"/api/enterprise-agreements/{agreement_id}/resume", {}, headers)

    def terminate_agreement(self, agreement_id, headers):
        return self._request("POST", f"/api/enterprise-agreements/{agreement_id}/terminate", {}, headers)

    def open_renewal_review(self, agreement_id, headers):
        return self._request("POST", f"/api/enterprise-agreements/{agreement_id}/open-renewal-review", {}, headers)

    def close_renewal_review(self, agreement_id, payload, headers):
        return self._request("POST", f"/api/enterprise-agreements/{agreement_id}/close-renewal-review", payload, headers)

    # ---- discount tiers ----
    def create_discount_tier(self, payload, headers):
        return self._request("POST", "/api/discount-tiers", payload, headers)

    def get_discount_tier(self, tier_id, headers):
        return self._request("GET", f"/api/discount-tiers/{tier_id}", headers=headers)

    def list_discount_tiers(self, headers, params=None):
        return self._request("GET", "/api/discount-tiers", headers=headers, params=params)

    # ---- pricing amendments ----
    def create_pricing_amendment(self, payload, headers):
        return self._request("POST", "/api/pricing-amendments", payload, headers)

    def get_pricing_amendment(self, amendment_id, headers):
        return self._request("GET", f"/api/pricing-amendments/{amendment_id}", headers=headers)

    def list_pricing_amendments(self, headers, params=None):
        return self._request("GET", "/api/pricing-amendments", headers=headers, params=params)

    # ---- commitment plans ----
    def create_commitment_plan(self, payload, headers):
        return self._request("POST", "/api/commitment-plans", payload, headers)

    def get_commitment_plan(self, plan_id, headers):
        return self._request("GET", f"/api/commitment-plans/{plan_id}", headers=headers)

    def list_commitment_plans(self, headers, params=None):
        return self._request("GET", "/api/commitment-plans", headers=headers, params=params)

    def terminate_commitment_plan(self, plan_id, headers):
        return self._request("POST", f"/api/commitment-plans/{plan_id}/terminate", {}, headers)

    def get_plan_coverage(self, plan_id, headers, params=None):
        return self._request("GET", f"/api/commitment-plans/{plan_id}/coverage", headers=headers, params=params)

    # ---- usage records ----
    def create_usage_record(self, payload, headers):
        return self._request("POST", "/api/usage-records", payload, headers)

    def get_usage_record(self, usage_id, headers):
        return self._request("GET", f"/api/usage-records/{usage_id}", headers=headers)

    def list_usage_records(self, headers, params=None):
        return self._request("GET", "/api/usage-records", headers=headers, params=params)

    # ---- credit grants ----
    def create_credit_grant(self, payload, headers):
        return self._request("POST", "/api/credit-grants", payload, headers)

    def get_credit_grant(self, grant_id, headers):
        return self._request("GET", f"/api/credit-grants/{grant_id}", headers=headers)

    def list_credit_grants(self, headers, params=None):
        return self._request("GET", "/api/credit-grants", headers=headers, params=params)

    def revoke_credit_grant(self, grant_id, headers):
        return self._request("POST", f"/api/credit-grants/{grant_id}/revoke", {}, headers)

    # ---- invoices ----
    def generate_invoice(self, payload, headers):
        return self._request("POST", "/api/invoices/generate", payload, headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/api/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/api/invoices", headers=headers, params=params)

    def list_invoice_lines(self, invoice_id, headers, params=None):
        return self._request("GET", f"/api/invoices/{invoice_id}/lines", headers=headers, params=params)

    def get_invoice_line(self, line_id, headers):
        return self._request("GET", f"/api/invoice-lines/{line_id}", headers=headers)

    def finalize_invoice(self, invoice_id, headers):
        return self._request("POST", f"/api/invoices/{invoice_id}/finalize", {}, headers)

    def dispute_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/api/invoices/{invoice_id}/dispute", payload, headers)

    def resolve_dispute(self, invoice_id, headers):
        return self._request("POST", f"/api/invoices/{invoice_id}/resolve-dispute", {}, headers)

    def settle_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/api/invoices/{invoice_id}/settle", payload, headers)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/api/invoices/{invoice_id}/void", {}, headers)

    # ---- true-up charges ----
    def assess_trueup(self, payload, headers):
        return self._request("POST", "/api/true-up-charges/assess", payload, headers)

    def get_trueup_charge(self, charge_id, headers):
        return self._request("GET", f"/api/true-up-charges/{charge_id}", headers=headers)

    def list_trueup_charges(self, headers, params=None):
        return self._request("GET", "/api/true-up-charges", headers=headers, params=params)

    def bill_trueup_charge(self, charge_id, headers):
        return self._request("POST", f"/api/true-up-charges/{charge_id}/bill", {}, headers)

    def waive_trueup_charge(self, charge_id, payload, headers):
        return self._request("POST", f"/api/true-up-charges/{charge_id}/waive", payload, headers)

    # ---- renewal forecasts ----
    def create_renewal_forecast(self, payload, headers):
        return self._request("POST", "/api/renewal-forecasts", payload, headers)

    def get_renewal_forecast(self, forecast_id, headers):
        return self._request("GET", f"/api/renewal-forecasts/{forecast_id}", headers=headers)

    def list_renewal_forecasts(self, headers, params=None):
        return self._request("GET", "/api/renewal-forecasts", headers=headers, params=params)


api_client = ApiClient()
