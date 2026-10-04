"""API client: one method per endpoint defined in the PRD section 4 table.

The logical clock endpoint lives OUTSIDE the /enforcement prefix
(PRD section 2.5): POST /_clock/set_current_utc.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Platform: logical clock (UNPREFIXED path, PRD section 2.5) ----------
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Subject companies ----------------------------------------------------
    def create_subject_company(self, payload, headers):
        return self._request("POST", "/enforcement/subject-companies", payload, headers)

    def get_subject_company(self, company_id, headers):
        return self._request("GET", f"/enforcement/subject-companies/{company_id}", headers=headers)

    # --- Investigations -------------------------------------------------------
    def create_investigation(self, payload, headers):
        return self._request("POST", "/enforcement/investigations", payload, headers)

    def list_investigations(self, headers, params=None):
        return self._request("GET", "/enforcement/investigations", headers=headers, params=params)

    def get_investigation(self, investigation_id, headers):
        return self._request("GET", f"/enforcement/investigations/{investigation_id}", headers=headers)

    def transition_investigation(self, investigation_id, payload, headers):
        return self._request("POST", f"/enforcement/investigations/{investigation_id}/transition", payload, headers)

    # --- Civil investigative demands ------------------------------------------
    def create_cid(self, investigation_id, payload, headers):
        return self._request("POST", f"/enforcement/investigations/{investigation_id}/cids", payload, headers)

    def list_cids(self, investigation_id, headers, params=None):
        return self._request("GET", f"/enforcement/investigations/{investigation_id}/cids", headers=headers, params=params)

    def transition_cid(self, cid_id, payload, headers):
        return self._request("POST", f"/enforcement/cids/{cid_id}/transition", payload, headers)

    # --- Consent orders -------------------------------------------------------
    def create_consent_order(self, investigation_id, payload, headers):
        return self._request("POST", f"/enforcement/investigations/{investigation_id}/consent-orders", payload, headers)

    def list_consent_orders(self, investigation_id, headers, params=None):
        return self._request("GET", f"/enforcement/investigations/{investigation_id}/consent-orders", headers=headers, params=params)

    def get_consent_order(self, order_id, headers):
        return self._request("GET", f"/enforcement/consent-orders/{order_id}", headers=headers)

    def transition_consent_order(self, order_id, payload, headers):
        return self._request("POST", f"/enforcement/consent-orders/{order_id}/transition", payload, headers)

    # --- Public comment periods ------------------------------------------------
    def list_comment_periods(self, order_id, headers, params=None):
        return self._request("GET", f"/enforcement/consent-orders/{order_id}/comment-periods", headers=headers, params=params)

    def post_comment(self, period_id, payload, headers):
        return self._request("POST", f"/enforcement/comment-periods/{period_id}/comments", payload, headers)

    # --- Compliance reports -----------------------------------------------------
    def create_compliance_report(self, order_id, payload, headers):
        return self._request("POST", f"/enforcement/consent-orders/{order_id}/compliance-reports", payload, headers)

    def list_compliance_reports(self, order_id, headers, params=None):
        return self._request("GET", f"/enforcement/consent-orders/{order_id}/compliance-reports", headers=headers, params=params)

    def transition_compliance_report(self, report_id, payload, headers):
        return self._request("POST", f"/enforcement/compliance-reports/{report_id}/transition", payload, headers)

    # --- Violation penalties -----------------------------------------------------
    def create_violation_penalty(self, order_id, payload, headers):
        return self._request("POST", f"/enforcement/consent-orders/{order_id}/violation-penalties", payload, headers)

    def list_violation_penalties(self, order_id, headers, params=None):
        return self._request("GET", f"/enforcement/consent-orders/{order_id}/violation-penalties", headers=headers, params=params)

    def transition_violation_penalty(self, penalty_id, payload, headers):
        return self._request("POST", f"/enforcement/violation-penalties/{penalty_id}/transition", payload, headers)

    # --- Monetary judgments -------------------------------------------------------
    def create_judgment(self, order_id, payload, headers):
        return self._request("POST", f"/enforcement/consent-orders/{order_id}/judgment", payload, headers)

    def get_order_judgment(self, order_id, headers):
        return self._request("GET", f"/enforcement/consent-orders/{order_id}/judgment", headers=headers)

    def get_judgment(self, judgment_id, headers):
        return self._request("GET", f"/enforcement/judgments/{judgment_id}", headers=headers)

    def create_payment(self, judgment_id, payload, headers):
        return self._request("POST", f"/enforcement/judgments/{judgment_id}/payments", payload, headers)

    def transition_judgment(self, judgment_id, payload, headers):
        return self._request("POST", f"/enforcement/judgments/{judgment_id}/transition", payload, headers)

    def create_asset_trace(self, judgment_id, payload, headers):
        return self._request("POST", f"/enforcement/judgments/{judgment_id}/asset-traces", payload, headers)

    # --- Redress funds --------------------------------------------------------------
    def get_judgment_redress_fund(self, judgment_id, headers):
        return self._request("GET", f"/enforcement/judgments/{judgment_id}/redress-fund", headers=headers)

    def get_redress_fund(self, fund_id, headers):
        return self._request("GET", f"/enforcement/redress-funds/{fund_id}", headers=headers)

    def transition_redress_fund(self, fund_id, payload, headers):
        return self._request("POST", f"/enforcement/redress-funds/{fund_id}/transition", payload, headers)

    # --- Claimants ----------------------------------------------------------------------
    def create_claimant(self, fund_id, payload, headers):
        return self._request("POST", f"/enforcement/redress-funds/{fund_id}/claimants", payload, headers)

    def list_claimants(self, fund_id, headers, params=None):
        return self._request("GET", f"/enforcement/redress-funds/{fund_id}/claimants", headers=headers, params=params)

    # --- Claims ---------------------------------------------------------------------------
    def create_claim(self, payload, headers):
        return self._request("POST", "/enforcement/claims", payload, headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/enforcement/claims", headers=headers, params=params)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/enforcement/claims/{claim_id}", headers=headers)

    def transition_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/enforcement/claims/{claim_id}/transition", payload, headers)

    # --- Refund checks ----------------------------------------------------------------------
    def issue_refund_check(self, claim_id, payload, headers):
        return self._request("POST", f"/enforcement/claims/{claim_id}/checks", payload or {}, headers)

    def list_claim_checks(self, claim_id, headers, params=None):
        return self._request("GET", f"/enforcement/claims/{claim_id}/checks", headers=headers, params=params)

    def transition_refund_check(self, check_id, payload, headers):
        return self._request("POST", f"/enforcement/refund-checks/{check_id}/transition", payload, headers)


api_client = ApiClient()
