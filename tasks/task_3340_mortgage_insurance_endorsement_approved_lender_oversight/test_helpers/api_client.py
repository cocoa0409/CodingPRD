"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock -------------------------------------------------------
    def set_current_utc(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --- Lenders -------------------------------------------------------------
    def create_lender(self, payload, headers):
        return self._request("POST", "/mi/lenders", payload, headers)

    def get_lender(self, lender_id, headers):
        return self._request("GET", f"/mi/lenders/{lender_id}", headers=headers)

    def lender_status_change(self, lender_id, payload, headers):
        return self._request(
            "POST", f"/mi/lenders/{lender_id}/status-change", payload, headers
        )

    # --- Financial filings ---------------------------------------------------
    def create_financial_filing(self, lender_id, payload, headers):
        return self._request(
            "POST", f"/mi/lenders/{lender_id}/financial-filings", payload, headers
        )

    def list_financial_filings(self, lender_id, headers, params=None):
        return self._request(
            "GET",
            f"/mi/lenders/{lender_id}/financial-filings",
            headers=headers,
            params=params,
        )

    def decide_financial_filing(self, filing_id, payload, headers):
        return self._request(
            "POST", f"/mi/financial-filings/{filing_id}/decide", payload, headers
        )

    # --- Loan cases ----------------------------------------------------------
    def create_loan_case(self, payload, headers):
        return self._request("POST", "/mi/loan-cases", payload, headers)

    def list_loan_cases(self, headers, params=None):
        return self._request("GET", "/mi/loan-cases", headers=headers, params=params)

    def get_loan_case(self, loan_case_id, headers):
        return self._request("GET", f"/mi/loan-cases/{loan_case_id}", headers=headers)

    def submit_underwriting(self, loan_case_id, headers, payload=None):
        return self._request(
            "POST",
            f"/mi/loan-cases/{loan_case_id}/submit-underwriting",
            payload if payload is not None else {},
            headers,
        )

    def endorsement_review(self, loan_case_id, payload, headers):
        return self._request(
            "POST", f"/mi/loan-cases/{loan_case_id}/endorsement-review", payload, headers
        )

    def void_endorsement(self, loan_case_id, payload, headers):
        return self._request(
            "POST", f"/mi/loan-cases/{loan_case_id}/void-endorsement", payload, headers
        )

    def declare_default(self, loan_case_id, headers, payload=None):
        return self._request(
            "POST",
            f"/mi/loan-cases/{loan_case_id}/declare-default",
            payload if payload is not None else {},
            headers,
        )

    # --- Appraisals ----------------------------------------------------------
    def create_appraisal(self, loan_case_id, payload, headers):
        return self._request(
            "POST", f"/mi/loan-cases/{loan_case_id}/appraisals", payload, headers
        )

    def list_appraisals(self, loan_case_id, headers, params=None):
        return self._request(
            "GET",
            f"/mi/loan-cases/{loan_case_id}/appraisals",
            headers=headers,
            params=params,
        )

    def decide_appraisal(self, appraisal_id, payload, headers):
        return self._request(
            "POST", f"/mi/appraisals/{appraisal_id}/decide", payload, headers
        )

    def transfer_appraisal(self, appraisal_id, payload, headers):
        return self._request(
            "POST", f"/mi/appraisals/{appraisal_id}/transfer", payload, headers
        )

    # --- Repair escrows ------------------------------------------------------
    def create_repair_escrow(self, loan_case_id, payload, headers):
        return self._request(
            "POST", f"/mi/loan-cases/{loan_case_id}/repair-escrows", payload, headers
        )

    def list_repair_escrows(self, loan_case_id, headers, params=None):
        return self._request(
            "GET",
            f"/mi/loan-cases/{loan_case_id}/repair-escrows",
            headers=headers,
            params=params,
        )

    def disburse_escrow(self, escrow_id, payload, headers):
        return self._request(
            "POST", f"/mi/repair-escrows/{escrow_id}/disburse", payload, headers
        )

    # --- MIP ------------------------------------------------------------------
    def list_mip_ledger_entries(self, loan_case_id, headers, params=None):
        return self._request(
            "GET",
            f"/mi/loan-cases/{loan_case_id}/mip-ledger-entries",
            headers=headers,
            params=params,
        )

    def mip_event(self, loan_case_id, payload, headers):
        return self._request(
            "POST", f"/mi/loan-cases/{loan_case_id}/mip-events", payload, headers
        )

    # --- Post-endorsement reviews and defects ---------------------------------
    def create_post_endorsement_review(self, loan_case_id, payload, headers):
        return self._request(
            "POST",
            f"/mi/loan-cases/{loan_case_id}/post-endorsement-reviews",
            payload,
            headers,
        )

    def list_post_endorsement_reviews(self, loan_case_id, headers, params=None):
        return self._request(
            "GET",
            f"/mi/loan-cases/{loan_case_id}/post-endorsement-reviews",
            headers=headers,
            params=params,
        )

    def create_defect(self, review_id, payload, headers):
        return self._request(
            "POST", f"/mi/post-endorsement-reviews/{review_id}/defects", payload, headers
        )

    def list_defects(self, review_id, headers, params=None):
        return self._request(
            "GET",
            f"/mi/post-endorsement-reviews/{review_id}/defects",
            headers=headers,
            params=params,
        )

    def close_review(self, review_id, headers, payload=None):
        return self._request(
            "POST",
            f"/mi/post-endorsement-reviews/{review_id}/close",
            payload if payload is not None else {},
            headers,
        )

    def confirm_defect(self, defect_id, payload, headers):
        return self._request(
            "POST", f"/mi/defects/{defect_id}/confirm", payload, headers
        )

    # --- Indemnification agreements -------------------------------------------
    def create_indemnification_agreement(self, loan_case_id, payload, headers):
        return self._request(
            "POST",
            f"/mi/loan-cases/{loan_case_id}/indemnification-agreements",
            payload,
            headers,
        )

    def list_indemnification_agreements(self, loan_case_id, headers, params=None):
        return self._request(
            "GET",
            f"/mi/loan-cases/{loan_case_id}/indemnification-agreements",
            headers=headers,
            params=params,
        )

    def execute_indemnification(self, agreement_id, headers, payload=None):
        return self._request(
            "POST",
            f"/mi/indemnification-agreements/{agreement_id}/execute",
            payload if payload is not None else {},
            headers,
        )

    def record_recovery(self, agreement_id, payload, headers):
        return self._request(
            "POST",
            f"/mi/indemnification-agreements/{agreement_id}/record-recovery",
            payload,
            headers,
        )

    # --- Loss mitigation -------------------------------------------------------
    def create_loss_mitigation_action(self, loan_case_id, payload, headers):
        return self._request(
            "POST",
            f"/mi/loan-cases/{loan_case_id}/loss-mitigation-actions",
            payload,
            headers,
        )

    def list_loss_mitigation_actions(self, loan_case_id, headers, params=None):
        return self._request(
            "GET",
            f"/mi/loan-cases/{loan_case_id}/loss-mitigation-actions",
            headers=headers,
            params=params,
        )

    def evaluate_loss_mitigation_action(self, action_id, payload, headers):
        return self._request(
            "POST",
            f"/mi/loss-mitigation-actions/{action_id}/evaluate",
            payload,
            headers,
        )

    # --- Insurance claims ------------------------------------------------------
    def create_claim(self, loan_case_id, payload, headers):
        return self._request(
            "POST", f"/mi/loan-cases/{loan_case_id}/claims", payload, headers
        )

    def list_claims(self, loan_case_id, headers, params=None):
        return self._request(
            "GET", f"/mi/loan-cases/{loan_case_id}/claims", headers=headers, params=params
        )

    def decide_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/mi/claims/{claim_id}/decide", payload, headers
        )


api_client = ApiClient()
