"""API client: one method per endpoint defined in the PRD."""
from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Deal Desk & Pricing Approval endpoints. The service is mounted at the root."""

    # ---------------------------------------------------------------- policies
    def create_desk_policy(self, payload: dict, headers: dict):
        return self._request("POST", "/desk-policies", payload, headers)

    def activate_desk_policy(self, policy_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST", f"/desk-policies/{policy_id}/activate", payload if payload is not None else {}, headers
        )

    def get_desk_policy(self, policy_id: str, headers: dict):
        return self._request("GET", f"/desk-policies/{policy_id}", headers=headers)

    def create_approval_tier(self, payload: dict, headers: dict):
        return self._request("POST", "/approval-tiers", payload, headers)

    def list_approval_tiers(self, policy_id: str, headers: dict, params: Optional[dict] = None):
        return self._request(
            "GET", f"/desk-policies/{policy_id}/approval-tiers", headers=headers, params=params
        )

    # --------------------------------------------------------------- catalogue
    def create_product(self, payload: dict, headers: dict):
        return self._request("POST", "/products", payload, headers)

    def get_product(self, product_id: str, headers: dict):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    def create_volume_tier(self, payload: dict, headers: dict):
        return self._request("POST", "/volume-tiers", payload, headers)

    def list_volume_tiers(self, product_id: str, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"/products/{product_id}/volume-tiers", headers=headers, params=params)

    def create_bundle_rule(self, payload: dict, headers: dict):
        return self._request("POST", "/bundle-rules", payload, headers)

    def list_bundle_rules(self, product_id: str, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"/products/{product_id}/bundle-rules", headers=headers, params=params)

    def list_product_quote_lines(self, product_id: str, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"/products/{product_id}/quote-lines", headers=headers, params=params)

    def list_product_price_holds(self, product_id: str, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"/products/{product_id}/price-holds", headers=headers, params=params)

    # ---------------------------------------------------------------- accounts
    def create_account(self, payload: dict, headers: dict):
        return self._request("POST", "/accounts", payload, headers)

    def get_account(self, account_id: str, headers: dict):
        return self._request("GET", f"/accounts/{account_id}", headers=headers)

    def create_credit_decision(self, account_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/accounts/{account_id}/credit-decisions", payload, headers)

    # ------------------------------------------------------------------ quotes
    def create_quote(self, payload: dict, headers: dict):
        return self._request("POST", "/quotes", payload, headers)

    def update_quote(self, quote_id: str, payload: dict, headers: dict):
        return self._request("PATCH", f"/quotes/{quote_id}", payload, headers)

    def get_quote(self, quote_id: str, headers: dict):
        return self._request("GET", f"/quotes/{quote_id}", headers=headers)

    def list_quotes(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/quotes", headers=headers, params=params)

    def create_quote_line(self, payload: dict, headers: dict):
        return self._request("POST", "/quote-lines", payload, headers)

    def update_quote_line(self, line_id: str, payload: dict, headers: dict):
        return self._request("PATCH", f"/quote-lines/{line_id}", payload, headers)

    def delete_quote_line(self, line_id: str, headers: dict):
        return self._request("DELETE", f"/quote-lines/{line_id}", headers=headers)

    def list_quote_lines(self, quote_id: str, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"/quotes/{quote_id}/lines", headers=headers, params=params)

    def get_pricing_preview(self, quote_id: str, headers: dict):
        return self._request("GET", f"/quotes/{quote_id}/pricing-preview", headers=headers)

    # ------------------------------------------------------- nonstandard terms
    def create_nonstandard_term(self, payload: dict, headers: dict):
        return self._request("POST", "/nonstandard-terms", payload, headers)

    def list_quote_nonstandard_terms(self, quote_id: str, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"/quotes/{quote_id}/nonstandard-terms", headers=headers, params=params)

    def review_nonstandard_term(self, term_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/nonstandard-terms/{term_id}/review", payload, headers)

    # -------------------------------------------------- competitive exceptions
    def create_competitive_exception(self, payload: dict, headers: dict):
        return self._request("POST", "/competitive-exceptions", payload, headers)

    def list_quote_competitive_exceptions(self, quote_id: str, headers: dict, params: Optional[dict] = None):
        return self._request(
            "GET", f"/quotes/{quote_id}/competitive-exceptions", headers=headers, params=params
        )

    def decide_competitive_exception(self, exception_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/competitive-exceptions/{exception_id}/decide", payload, headers)

    def revoke_competitive_exception(self, exception_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/competitive-exceptions/{exception_id}/revoke", payload, headers)

    # ------------------------------------------------------- revenue recognition
    def create_revrec_assessment(self, payload: dict, headers: dict):
        return self._request("POST", "/revrec-assessments", payload, headers)

    def list_quote_revrec_assessments(self, quote_id: str, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"/quotes/{quote_id}/revrec-assessments", headers=headers, params=params)

    def assess_revrec_assessment(self, assessment_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/revrec-assessments/{assessment_id}/assess", payload, headers)

    # ---------------------------------------------------------------- approval
    def submit_quote(self, quote_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST", f"/quotes/{quote_id}/submit", payload if payload is not None else {}, headers
        )

    def list_quote_approval_requests(self, quote_id: str, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"/quotes/{quote_id}/approval-requests", headers=headers, params=params)

    def list_approval_steps(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/approval-steps", headers=headers, params=params)

    def get_approval_step(self, step_id: str, headers: dict):
        return self._request("GET", f"/approval-steps/{step_id}", headers=headers)

    def decide_approval_step(self, step_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/approval-steps/{step_id}/decide", payload, headers)

    def reopen_quote(self, quote_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST", f"/quotes/{quote_id}/reopen", payload if payload is not None else {}, headers
        )

    def renegotiate_quote(self, quote_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/quotes/{quote_id}/renegotiate", payload, headers)

    # ------------------------------------------------------- delegation grants
    def create_delegation_grant(self, payload: dict, headers: dict):
        return self._request("POST", "/delegation-grants", payload, headers)

    def list_delegation_grants(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/delegation-grants", headers=headers, params=params)

    def revoke_delegation_grant(self, grant_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST", f"/delegation-grants/{grant_id}/revoke", payload if payload is not None else {}, headers
        )

    # ------------------------------------------------------------- order forms
    def create_order_form(self, payload: dict, headers: dict):
        return self._request("POST", "/order-forms", payload, headers)

    def get_order_form(self, form_id: str, headers: dict):
        return self._request("GET", f"/order-forms/{form_id}", headers=headers)

    def list_quote_order_forms(self, quote_id: str, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"/quotes/{quote_id}/order-forms", headers=headers, params=params)

    def send_order_form(self, form_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST", f"/order-forms/{form_id}/send", payload if payload is not None else {}, headers
        )

    def record_order_form_signature(self, form_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/order-forms/{form_id}/signature", payload, headers)

    def book_order_form(self, form_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST", f"/order-forms/{form_id}/book", payload if payload is not None else {}, headers
        )

    def reverse_order_form_booking(self, form_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/order-forms/{form_id}/reverse-booking", payload, headers)

    # ------------------------------------------------------- sweeps and clock
    def run_expiry_sweep(self, headers: dict, payload: Optional[dict] = None):
        return self._request("POST", "/expiry-sweeps", payload if payload is not None else {}, headers)

    def run_sla_escalation_sweep(self, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST", "/sla-escalation-sweeps", payload if payload is not None else {}, headers
        )

    def set_clock(self, to_iso8601: str, headers: dict):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
