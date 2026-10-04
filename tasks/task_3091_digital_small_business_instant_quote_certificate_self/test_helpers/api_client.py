"""API client: one method per endpoint defined in the PRD (mounted under /ins)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/ins/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # --- Appetite rules ---
    def create_appetite_rule(self, payload, headers):
        return self._request("POST", "/ins/appetite-rules", payload, headers)

    def list_appetite_rules(self, headers, params=None):
        return self._request("GET", "/ins/appetite-rules", headers=headers, params=params)

    def patch_appetite_rule(self, rule_id, payload, headers):
        return self._request("PATCH", f"/ins/appetite-rules/{rule_id}", payload, headers)

    # --- Class codes ---
    def create_class_code(self, payload, headers):
        return self._request("POST", "/ins/class-codes", payload, headers)

    def list_class_codes(self, headers, params=None):
        return self._request("GET", "/ins/class-codes", headers=headers, params=params)

    def get_class_code(self, class_code_id, headers):
        return self._request("GET", f"/ins/class-codes/{class_code_id}", headers=headers)

    def list_class_code_appetite_rules(self, class_code_id, headers):
        return self._request(
            "GET", f"/ins/class-codes/{class_code_id}/appetite-rules", headers=headers
        )

    def list_class_code_policies(self, class_code_id, headers):
        return self._request(
            "GET", f"/ins/class-codes/{class_code_id}/policies", headers=headers
        )

    def patch_class_code(self, class_code_id, payload, headers):
        return self._request("PATCH", f"/ins/class-codes/{class_code_id}", payload, headers)

    # --- Business accounts ---
    def create_business_account(self, payload, headers):
        return self._request("POST", "/ins/business-accounts", payload, headers)

    def list_business_accounts(self, headers, params=None):
        return self._request("GET", "/ins/business-accounts", headers=headers, params=params)

    def get_business_account(self, account_id, headers):
        return self._request("GET", f"/ins/business-accounts/{account_id}", headers=headers)

    def list_account_risk_signals(self, account_id, headers):
        return self._request(
            "GET", f"/ins/business-accounts/{account_id}/risk-signals", headers=headers
        )

    def list_account_quotes(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/ins/business-accounts/{account_id}/quotes",
            headers=headers, params=params,
        )

    def list_account_policies(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/ins/business-accounts/{account_id}/policies",
            headers=headers, params=params,
        )

    def list_account_claims(self, account_id, headers):
        return self._request(
            "GET", f"/ins/business-accounts/{account_id}/claims", headers=headers
        )

    # --- Risk signals ---
    def create_risk_signal(self, payload, headers):
        return self._request("POST", "/ins/risk-signals", payload, headers)

    # --- Quotes ---
    def list_quotes(self, headers, params=None):
        return self._request("GET", "/ins/quotes", headers=headers, params=params)

    def create_quote(self, payload, headers):
        return self._request("POST", "/ins/quotes", payload, headers)

    def get_quote(self, quote_id, headers):
        return self._request("GET", f"/ins/quotes/{quote_id}", headers=headers)

    def bind_quote(self, quote_id, payload, headers):
        return self._request("POST", f"/ins/quotes/{quote_id}/bind", payload, headers)

    def get_quote_referral(self, quote_id, headers):
        return self._request("GET", f"/ins/quotes/{quote_id}/referral", headers=headers)

    def get_quote_policy(self, quote_id, headers):
        return self._request("GET", f"/ins/quotes/{quote_id}/policy", headers=headers)

    # --- Referrals ---
    def get_referral(self, referral_id, headers):
        return self._request("GET", f"/ins/referrals/{referral_id}", headers=headers)

    def approve_referral(self, referral_id, headers):
        return self._request(
            "POST", f"/ins/referrals/{referral_id}/approve", {}, headers
        )

    def decline_referral(self, referral_id, headers):
        return self._request(
            "POST", f"/ins/referrals/{referral_id}/decline", {}, headers
        )

    # --- Policies ---
    def get_policy(self, policy_id, headers):
        return self._request("GET", f"/ins/policies/{policy_id}", headers=headers)

    def cancel_policy(self, policy_id, headers):
        return self._request("POST", f"/ins/policies/{policy_id}/cancel", {}, headers)

    def renew_policy(self, policy_id, payload, headers):
        return self._request("POST", f"/ins/policies/{policy_id}/renew", payload, headers)

    def create_non_renewal_notice(self, policy_id, payload, headers):
        return self._request(
            "POST", f"/ins/policies/{policy_id}/non-renewal-notices", payload, headers
        )

    def list_non_renewal_notices(self, policy_id, headers):
        return self._request(
            "GET", f"/ins/policies/{policy_id}/non-renewal-notices", headers=headers
        )

    def list_policy_endorsements(self, policy_id, headers, params=None):
        return self._request(
            "GET", f"/ins/policies/{policy_id}/endorsements",
            headers=headers, params=params,
        )

    def create_endorsement(self, policy_id, payload, headers):
        return self._request(
            "POST", f"/ins/policies/{policy_id}/endorsements", payload, headers
        )

    def list_policy_certificates(self, policy_id, headers, params=None):
        return self._request(
            "GET", f"/ins/policies/{policy_id}/certificates",
            headers=headers, params=params,
        )

    def list_policy_claims(self, policy_id, headers, params=None):
        return self._request(
            "GET", f"/ins/policies/{policy_id}/claims", headers=headers, params=params
        )

    # --- Certificates / endorsements (top level) ---
    def create_certificate(self, payload, headers):
        return self._request("POST", "/ins/certificates", payload, headers)

    def get_endorsement(self, endorsement_id, headers):
        return self._request("GET", f"/ins/endorsements/{endorsement_id}", headers=headers)

    def list_endorsement_certificates(self, endorsement_id, headers):
        return self._request(
            "GET", f"/ins/endorsements/{endorsement_id}/certificates", headers=headers
        )

    def get_certificate(self, certificate_id, headers):
        return self._request("GET", f"/ins/certificates/{certificate_id}", headers=headers)

    # --- Claims ---
    def create_claim(self, payload, headers):
        return self._request("POST", "/ins/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/ins/claims/{claim_id}", headers=headers)

    def attach_evidence(self, claim_id, payload, headers):
        return self._request("POST", f"/ins/claims/{claim_id}/evidence", payload, headers)

    def list_evidence(self, claim_id, headers):
        return self._request("GET", f"/ins/claims/{claim_id}/evidence", headers=headers)

    def triage_claim(self, claim_id, headers):
        return self._request("POST", f"/ins/claims/{claim_id}/triage", {}, headers)

    def approve_claim(self, claim_id, headers):
        return self._request("POST", f"/ins/claims/{claim_id}/approve", {}, headers)

    def deny_claim(self, claim_id, headers):
        return self._request("POST", f"/ins/claims/{claim_id}/deny", {}, headers)

    def payout_claim(self, claim_id, headers):
        return self._request("POST", f"/ins/claims/{claim_id}/payout", {}, headers)

    def close_claim(self, claim_id, headers):
        return self._request("POST", f"/ins/claims/{claim_id}/close", {}, headers)

    # --- Audit ---
    def list_audit_events(self, headers, params=None):
        return self._request("GET", "/ins/audit-events", headers=headers, params=params)


api_client = ApiClient()
