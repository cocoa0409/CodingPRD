"""API client: one method per endpoint in the Wholesale Broker Channel API."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Clock ---------------------------------------------------------------
    def set_current_utc(self, to_iso8601, headers):
        return self._request(
            "POST",
            "/wholesale-channel/_clock/set_current_utc",
            {"to_iso8601": to_iso8601},
            headers,
        )

    # --- Brokers -------------------------------------------------------------
    def create_broker(self, payload, headers):
        return self._request("POST", "/wholesale-channel/brokers", payload, headers)

    def list_brokers(self, headers, params=None):
        return self._request("GET", "/wholesale-channel/brokers", headers=headers, params=params)

    def get_broker(self, broker_id, headers):
        return self._request("GET", f"/wholesale-channel/brokers/{broker_id}", headers=headers)

    def get_broker_reconciliation(self, broker_id, headers):
        return self._request(
            "GET", f"/wholesale-channel/brokers/{broker_id}/reconciliation", headers=headers
        )

    def approve_broker(self, broker_id, headers, payload=None):
        return self._request(
            "POST", f"/wholesale-channel/brokers/{broker_id}/approve", payload if payload is not None else {}, headers
        )

    def reinstate_broker(self, broker_id, headers, payload=None):
        return self._request(
            "POST", f"/wholesale-channel/brokers/{broker_id}/reinstate", payload if payload is not None else {}, headers
        )

    def suspend_broker(self, broker_id, payload, headers):
        return self._request("POST", f"/wholesale-channel/brokers/{broker_id}/suspend", payload, headers)

    def terminate_broker(self, broker_id, headers, payload=None):
        return self._request(
            "POST", f"/wholesale-channel/brokers/{broker_id}/terminate", payload if payload is not None else {}, headers
        )

    # --- Licenses ------------------------------------------------------------
    def create_license(self, broker_id, payload, headers):
        return self._request("POST", f"/wholesale-channel/brokers/{broker_id}/licenses", payload, headers)

    def list_licenses(self, broker_id, headers, params=None):
        return self._request(
            "GET", f"/wholesale-channel/brokers/{broker_id}/licenses", headers=headers, params=params
        )

    def revoke_license(self, broker_id, license_id, headers, payload=None):
        return self._request(
            "POST",
            f"/wholesale-channel/brokers/{broker_id}/licenses/{license_id}/revoke",
            payload if payload is not None else {},
            headers,
        )

    # --- Financial reviews ---------------------------------------------------
    def create_financial_review(self, broker_id, payload, headers):
        return self._request("POST", f"/wholesale-channel/brokers/{broker_id}/financial-reviews", payload, headers)

    def list_financial_reviews(self, broker_id, headers, params=None):
        return self._request(
            "GET", f"/wholesale-channel/brokers/{broker_id}/financial-reviews", headers=headers, params=params
        )

    def decide_financial_review(self, review_id, payload, headers):
        return self._request("POST", f"/wholesale-channel/financial-reviews/{review_id}/decision", payload, headers)

    # --- Product eligibility -------------------------------------------------
    def create_product_eligibility(self, broker_id, payload, headers):
        return self._request("POST", f"/wholesale-channel/brokers/{broker_id}/product-eligibilities", payload, headers)

    def list_product_eligibilities(self, broker_id, headers, params=None):
        return self._request(
            "GET", f"/wholesale-channel/brokers/{broker_id}/product-eligibilities", headers=headers, params=params
        )

    def decide_product_eligibility(self, eligibility_id, payload, headers):
        return self._request(
            "POST", f"/wholesale-channel/product-eligibilities/{eligibility_id}/decision", payload, headers
        )

    # --- Exclusivity ---------------------------------------------------------
    def create_exclusivity_policy(self, payload, headers):
        return self._request("POST", "/wholesale-channel/exclusivity-policies", payload, headers)

    def list_exclusivity_policies(self, broker_id, headers, params=None):
        return self._request(
            "GET", f"/wholesale-channel/brokers/{broker_id}/exclusivity-policies", headers=headers, params=params
        )

    def void_exclusivity_policy(self, policy_id, payload, headers):
        return self._request("POST", f"/wholesale-channel/exclusivity-policies/{policy_id}/void", payload, headers)

    # --- Compensation plans --------------------------------------------------
    def create_compensation_plan(self, payload, headers):
        return self._request("POST", "/wholesale-channel/compensation-plans", payload, headers)

    def list_compensation_plans(self, broker_id, headers, params=None):
        return self._request(
            "GET", f"/wholesale-channel/brokers/{broker_id}/compensation-plans", headers=headers, params=params
        )

    def get_compensation_plan(self, plan_id, headers):
        return self._request("GET", f"/wholesale-channel/compensation-plans/{plan_id}", headers=headers)

    def update_compensation_plan(self, plan_id, payload, headers):
        return self._request("PUT", f"/wholesale-channel/compensation-plans/{plan_id}", payload, headers)

    # --- Rate sheets ---------------------------------------------------------
    def publish_rate_sheet(self, broker_id, payload, headers):
        return self._request("POST", f"/wholesale-channel/brokers/{broker_id}/rate-sheets", payload, headers)

    def list_broker_rate_sheets(self, broker_id, headers, params=None):
        return self._request(
            "GET", f"/wholesale-channel/brokers/{broker_id}/rate-sheets", headers=headers, params=params
        )

    def retire_rate_sheet(self, broker_id, sheet_id, headers, payload=None):
        return self._request(
            "POST",
            f"/wholesale-channel/brokers/{broker_id}/rate-sheets/{sheet_id}/retire",
            payload if payload is not None else {},
            headers,
        )

    def list_rate_sheets(self, headers, params=None):
        return self._request("GET", "/wholesale-channel/rate-sheets", headers=headers, params=params)

    def get_rate_sheet(self, sheet_id, headers):
        return self._request("GET", f"/wholesale-channel/rate-sheets/{sheet_id}", headers=headers)

    # --- Pricing quotes ------------------------------------------------------
    def create_pricing_quote(self, sheet_id, payload, headers):
        return self._request("POST", f"/wholesale-channel/rate-sheets/{sheet_id}/pricing-quotes", payload, headers)

    def list_sheet_pricing_quotes(self, sheet_id, headers, params=None):
        return self._request(
            "GET", f"/wholesale-channel/rate-sheets/{sheet_id}/pricing-quotes", headers=headers, params=params
        )

    def get_pricing_quote(self, quote_id, headers):
        return self._request("GET", f"/wholesale-channel/pricing-quotes/{quote_id}", headers=headers)

    def list_pricing_quotes(self, headers, params=None):
        return self._request("GET", "/wholesale-channel/pricing-quotes", headers=headers, params=params)

    # --- Loan submissions ----------------------------------------------------
    def create_loan_submission(self, payload, headers):
        return self._request("POST", "/wholesale-channel/loan-submissions", payload, headers)

    def list_loan_submissions(self, headers, params=None):
        return self._request("GET", "/wholesale-channel/loan-submissions", headers=headers, params=params)

    def get_loan_submission(self, loan_id, headers):
        return self._request("GET", f"/wholesale-channel/loan-submissions/{loan_id}", headers=headers)

    def elect_compensation(self, loan_id, payload, headers):
        return self._request(
            "POST", f"/wholesale-channel/loan-submissions/{loan_id}/compensation-election", payload, headers
        )

    def underwrite_loan(self, loan_id, payload, headers):
        return self._request("POST", f"/wholesale-channel/loan-submissions/{loan_id}/underwrite", payload, headers)

    def resubmit_loan(self, loan_id, payload, headers):
        return self._request("POST", f"/wholesale-channel/loan-submissions/{loan_id}/resubmit", payload, headers)

    def withdraw_loan(self, loan_id, headers, payload=None):
        return self._request(
            "POST", f"/wholesale-channel/loan-submissions/{loan_id}/withdraw", payload if payload is not None else {}, headers
        )

    def clear_to_close_loan(self, loan_id, headers, payload=None):
        return self._request(
            "POST",
            f"/wholesale-channel/loan-submissions/{loan_id}/clear-to-close",
            payload if payload is not None else {},
            headers,
        )

    def fund_loan(self, loan_id, headers, payload=None):
        return self._request(
            "POST", f"/wholesale-channel/loan-submissions/{loan_id}/fund", payload if payload is not None else {}, headers
        )

    def get_closing_pipeline(self, headers, params=None):
        return self._request("GET", "/wholesale-channel/closing-pipeline", headers=headers, params=params)

    # --- Underwriting decisions ---------------------------------------------
    def create_underwriting_decision(self, payload, headers):
        return self._request("POST", "/wholesale-channel/underwriting-decisions", payload, headers)

    def list_loan_underwriting_decisions(self, loan_id, headers, params=None):
        return self._request(
            "GET", f"/wholesale-channel/loan-submissions/{loan_id}/underwriting-decisions", headers=headers, params=params
        )

    def list_broker_underwriting_decisions(self, broker_id, headers, params=None):
        return self._request(
            "GET", f"/wholesale-channel/brokers/{broker_id}/underwriting-decisions", headers=headers, params=params
        )

    # --- Turn-time escalations ----------------------------------------------
    def list_loan_escalations(self, loan_id, headers, params=None):
        return self._request(
            "GET", f"/wholesale-channel/loan-submissions/{loan_id}/turn-time-escalations", headers=headers, params=params
        )

    def list_broker_escalations(self, broker_id, headers, params=None):
        return self._request(
            "GET", f"/wholesale-channel/brokers/{broker_id}/turn-time-escalations", headers=headers, params=params
        )

    def resolve_escalation(self, escalation_id, payload, headers):
        return self._request("POST", f"/wholesale-channel/turn-time-escalations/{escalation_id}/resolve", payload, headers)

    # --- Quality control -----------------------------------------------------
    def create_quality_control_review(self, payload, headers):
        return self._request("POST", "/wholesale-channel/quality-control-reviews", payload, headers)

    def list_broker_quality_control_reviews(self, broker_id, headers, params=None):
        return self._request(
            "GET", f"/wholesale-channel/brokers/{broker_id}/quality-control-reviews", headers=headers, params=params
        )

    def list_loan_quality_control_reviews(self, loan_id, headers, params=None):
        return self._request(
            "GET", f"/wholesale-channel/loan-submissions/{loan_id}/quality-control-reviews", headers=headers, params=params
        )

    def list_quality_control_reviews(self, headers, params=None):
        return self._request("GET", "/wholesale-channel/quality-control-reviews", headers=headers, params=params)

    def resolve_quality_control_review(self, review_id, payload, headers):
        return self._request("POST", f"/wholesale-channel/quality-control-reviews/{review_id}/resolve", payload, headers)

    def repurchase_quality_control_review(self, review_id, headers, payload=None):
        return self._request(
            "POST",
            f"/wholesale-channel/quality-control-reviews/{review_id}/repurchase",
            payload if payload is not None else {},
            headers,
        )


api_client = ApiClient()