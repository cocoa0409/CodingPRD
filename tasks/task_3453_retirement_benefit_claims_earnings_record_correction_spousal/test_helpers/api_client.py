"""API client: one method per endpoint defined in the PRD (§4).

Business resources live under the /ssa prefix; the logical clock and the
monthly batch cycle are intentionally unprefixed (PRD §4: "All business
resources are mounted under the `/ssa` prefix; the two platform capabilities —
the logical clock and the monthly batch cycle — are intentionally unprefixed.").
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- platform: logical clock (unprefixed) ------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---- platform: monthly batch cycle (unprefixed) -------------------------
    def run_monthly_cycle(self, headers, run_month=None):
        payload = {} if run_month is None else {"run_month": run_month}
        return self._request("POST", "/_batch/run-monthly-cycle", payload, headers)

    # ---- workers ------------------------------------------------------------
    def create_worker(self, payload, headers):
        return self._request("POST", "/ssa/workers", payload, headers)

    def get_worker(self, worker_id, headers):
        return self._request("GET", f"/ssa/workers/{worker_id}", headers=headers)

    def patch_worker(self, worker_id, payload, headers):
        return self._request("PATCH", f"/ssa/workers/{worker_id}", payload, headers)

    def report_death(self, worker_id, death_date, headers):
        return self._request(
            "POST", f"/ssa/workers/{worker_id}/report-death",
            {"death_date": death_date}, headers,
        )

    def list_earnings_years(self, worker_id, headers, params=None):
        return self._request(
            "GET", f"/ssa/workers/{worker_id}/earnings-years", headers=headers, params=params
        )

    def list_worker_relationships(self, worker_id, headers, params=None):
        return self._request(
            "GET", f"/ssa/workers/{worker_id}/relationships", headers=headers, params=params
        )

    def list_worker_wage_reports(self, worker_id, headers, params=None):
        return self._request(
            "GET", f"/ssa/workers/{worker_id}/wage-reports", headers=headers, params=params
        )

    def list_worker_correction_requests(self, worker_id, headers, params=None):
        return self._request(
            "GET", f"/ssa/workers/{worker_id}/correction-requests", headers=headers, params=params
        )

    # ---- wage reports --------------------------------------------------------
    def create_wage_report(self, payload, headers):
        return self._request("POST", "/ssa/wage-reports", payload, headers)

    # ---- correction requests --------------------------------------------------
    def create_correction_request(self, payload, headers):
        return self._request("POST", "/ssa/correction-requests", payload, headers)

    def request_evidence(self, correction_id, headers, payload=None):
        return self._request(
            "POST", f"/ssa/correction-requests/{correction_id}/request-evidence",
            payload or {}, headers,
        )

    def submit_evidence(self, correction_id, payload, headers):
        return self._request(
            "POST", f"/ssa/correction-requests/{correction_id}/submit-evidence",
            payload, headers,
        )

    def approve_correction(self, correction_id, headers):
        return self._request(
            "POST", f"/ssa/correction-requests/{correction_id}/approve", {}, headers
        )

    def deny_correction(self, correction_id, denial_reason, headers):
        return self._request(
            "POST", f"/ssa/correction-requests/{correction_id}/deny",
            {"denial_reason": denial_reason}, headers,
        )

    def reopen_correction(self, correction_id, reopen_reason, headers):
        return self._request(
            "POST", f"/ssa/correction-requests/{correction_id}/reopen",
            {"reopen_reason": reopen_reason}, headers,
        )

    # ---- benefit claims -------------------------------------------------------
    def create_claim(self, payload, headers):
        return self._request("POST", "/ssa/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/ssa/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/ssa/claims", headers=headers, params=params)

    def approve_claim(self, claim_id, headers):
        return self._request("POST", f"/ssa/claims/{claim_id}/approve", {}, headers)

    def deny_claim(self, claim_id, denial_reason, headers):
        return self._request(
            "POST", f"/ssa/claims/{claim_id}/deny", {"denial_reason": denial_reason}, headers
        )

    def reopen_claim(self, claim_id, reopen_reason, headers):
        return self._request(
            "POST", f"/ssa/claims/{claim_id}/reopen", {"reopen_reason": reopen_reason}, headers
        )

    def withdraw_claim(self, claim_id, repaid_amount_cents, headers):
        return self._request(
            "POST", f"/ssa/claims/{claim_id}/withdraw",
            {"repaid_amount_cents": repaid_amount_cents}, headers,
        )

    def suspend_claim(self, claim_id, expected_claim_version, headers):
        return self._request(
            "POST", f"/ssa/claims/{claim_id}/suspend",
            {"expected_claim_version": expected_claim_version}, headers,
        )

    def resume_claim(self, claim_id, headers):
        return self._request("POST", f"/ssa/claims/{claim_id}/resume", {}, headers)

    def list_claim_payments(self, claim_id, headers, params=None):
        return self._request(
            "GET", f"/ssa/claims/{claim_id}/payments", headers=headers, params=params
        )

    def list_claim_overpayment_cases(self, claim_id, headers, params=None):
        return self._request(
            "GET", f"/ssa/claims/{claim_id}/overpayment-cases", headers=headers, params=params
        )

    def list_claim_payee_cases(self, claim_id, headers, params=None):
        return self._request(
            "GET", f"/ssa/claims/{claim_id}/payee-cases", headers=headers, params=params
        )

    def list_claim_recomputation_events(self, claim_id, headers, params=None):
        return self._request(
            "GET", f"/ssa/claims/{claim_id}/recomputation-events", headers=headers, params=params
        )

    # ---- overpayment cases ----------------------------------------------------
    def create_overpayment_case(self, payload, headers):
        return self._request("POST", "/ssa/overpayment-cases", payload, headers)

    def request_waiver(self, case_id, expected_overpayment_version, waiver_grounds, headers):
        return self._request(
            "POST", f"/ssa/overpayment-cases/{case_id}/request-waiver",
            {
                "expected_overpayment_version": expected_overpayment_version,
                "waiver_grounds": waiver_grounds,
            },
            headers,
        )

    def decide_waiver(self, case_id, outcome, headers):
        return self._request(
            "POST", f"/ssa/overpayment-cases/{case_id}/decide-waiver",
            {"outcome": outcome}, headers,
        )

    def begin_recovery(self, case_id, recovery_mode, headers, monthly_rate_cents=None):
        payload = {"recovery_mode": recovery_mode}
        if monthly_rate_cents is not None:
            payload["monthly_rate_cents"] = monthly_rate_cents
        return self._request(
            "POST", f"/ssa/overpayment-cases/{case_id}/begin-recovery", payload, headers
        )

    # ---- relationships ---------------------------------------------------------
    def create_relationship(self, payload, headers):
        return self._request("POST", "/ssa/relationships", payload, headers)

    def verify_relationship(self, relationship_id, headers):
        return self._request(
            "POST", f"/ssa/relationships/{relationship_id}/verify", {}, headers
        )

    def reject_relationship(self, relationship_id, rejection_reason, headers):
        return self._request(
            "POST", f"/ssa/relationships/{relationship_id}/reject",
            {"rejection_reason": rejection_reason}, headers,
        )

    # ---- payee cases -------------------------------------------------------------
    def create_payee_case(self, payload, headers):
        return self._request("POST", "/ssa/payee-cases", payload, headers)

    def decide_payee_case(self, case_id, outcome, headers):
        return self._request(
            "POST", f"/ssa/payee-cases/{case_id}/decide", {"outcome": outcome}, headers
        )


api_client = ApiClient()
