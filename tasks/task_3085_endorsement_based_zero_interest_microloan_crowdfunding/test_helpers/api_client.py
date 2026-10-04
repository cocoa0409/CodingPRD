"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Typed endpoint methods over the endorsement-microloan API surface."""

    # --- logical clock / maintenance sweep ---------------------------------
    def set_clock(self, current_utc, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    def run_sweeps(self, headers):
        return self._request("POST", "/_sweeps/run", {}, headers)

    # --- borrowers ----------------------------------------------------------
    def create_borrower(self, payload, headers):
        return self._request("POST", "/borrowers", payload, headers)

    def get_borrower(self, borrower_id, headers):
        return self._request("GET", f"/borrowers/{borrower_id}", headers=headers)

    def update_borrower(self, borrower_id, payload, headers):
        return self._request("PATCH", f"/borrowers/{borrower_id}", payload, headers)

    def list_borrower_invites(self, borrower_id, headers):
        return self._request(
            "GET", f"/borrowers/{borrower_id}/underwriting-invites", headers=headers
        )

    def list_borrower_applications(self, borrower_id, headers):
        return self._request(
            "GET", f"/borrowers/{borrower_id}/loan-applications", headers=headers
        )

    def list_borrower_loans(self, borrower_id, headers):
        return self._request("GET", f"/borrowers/{borrower_id}/loans", headers=headers)

    def list_borrower_impact_reports(self, borrower_id, headers):
        return self._request(
            "GET", f"/borrowers/{borrower_id}/impact-reports", headers=headers
        )

    def list_borrower_payments(self, borrower_id, headers):
        return self._request(
            "GET", f"/borrowers/{borrower_id}/payments", headers=headers
        )

    # --- underwriting invites ----------------------------------------------
    def create_invite(self, borrower_id, payload, headers):
        return self._request(
            "POST", f"/borrowers/{borrower_id}/underwriting-invites", payload, headers
        )

    def accept_invite(self, token, headers=None):
        return self._request(
            "POST", f"/underwriting-invites/{token}/accept", {}, headers
        )

    def decline_invite(self, token, headers=None):
        return self._request(
            "POST", f"/underwriting-invites/{token}/decline", {}, headers
        )

    # --- lenders ------------------------------------------------------------
    def create_lender(self, payload, headers):
        return self._request("POST", "/lenders", payload, headers)

    def get_lender(self, lender_id, headers):
        return self._request("GET", f"/lenders/{lender_id}", headers=headers)

    def deposit(self, lender_id, payload, headers):
        return self._request(
            "POST", f"/lenders/{lender_id}/deposits", payload, headers
        )

    def list_lender_endorsements(self, lender_id, headers):
        return self._request(
            "GET", f"/lenders/{lender_id}/endorsements", headers=headers
        )

    def list_lender_contributions(self, lender_id, headers):
        return self._request(
            "GET", f"/lenders/{lender_id}/contributions", headers=headers
        )

    def get_lender_impact(self, lender_id, headers):
        return self._request("GET", f"/lenders/{lender_id}/impact", headers=headers)

    # --- trustees -----------------------------------------------------------
    def create_trustee(self, payload, headers):
        return self._request("POST", "/trustees", payload, headers)

    def get_trustee(self, trustee_id, headers):
        return self._request("GET", f"/trustees/{trustee_id}", headers=headers)

    def suspend_trustee(self, trustee_id, headers):
        return self._request("POST", f"/trustees/{trustee_id}/suspend", {}, headers)

    def reinstate_trustee(self, trustee_id, headers):
        return self._request("POST", f"/trustees/{trustee_id}/reinstate", {}, headers)

    def create_trustee_endorsement(self, trustee_id, payload, headers):
        return self._request(
            "POST", f"/trustees/{trustee_id}/endorsements", payload, headers
        )

    def list_trustee_endorsements(self, trustee_id, headers):
        return self._request(
            "GET", f"/trustees/{trustee_id}/endorsements", headers=headers
        )

    def list_trustee_applications(self, trustee_id, headers):
        return self._request(
            "GET", f"/trustees/{trustee_id}/loan-applications", headers=headers
        )

    # --- loan applications --------------------------------------------------
    def create_application(self, payload, headers):
        return self._request("POST", "/loan-applications", payload, headers)

    def get_application(self, application_id, headers):
        return self._request(
            "GET", f"/loan-applications/{application_id}", headers=headers
        )

    def list_applications(self, headers, params=None):
        return self._request(
            "GET", "/loan-applications", headers=headers, params=params
        )

    def update_application(self, application_id, payload, headers):
        return self._request(
            "PATCH", f"/loan-applications/{application_id}", payload, headers
        )

    def submit_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"/loan-applications/{application_id}/submit", payload, headers
        )

    def approve_application(self, application_id, headers, payload=None):
        return self._request(
            "POST",
            f"/loan-applications/{application_id}/approve",
            payload or {},
            headers,
        )

    def reject_application(self, application_id, headers, payload=None):
        return self._request(
            "POST",
            f"/loan-applications/{application_id}/reject",
            payload or {},
            headers,
        )

    def request_changes(self, application_id, headers, payload=None):
        return self._request(
            "POST",
            f"/loan-applications/{application_id}/request-changes",
            payload or {},
            headers,
        )

    def open_private(self, application_id, headers):
        return self._request(
            "POST", f"/loan-applications/{application_id}/open-private", {}, headers
        )

    def open_public(self, application_id, headers):
        return self._request(
            "POST", f"/loan-applications/{application_id}/open-public", {}, headers
        )

    def withdraw_application(self, application_id, headers):
        return self._request(
            "POST", f"/loan-applications/{application_id}/withdraw", {}, headers
        )

    def cancel_application(self, application_id, headers):
        return self._request(
            "POST", f"/loan-applications/{application_id}/cancel", {}, headers
        )

    def disburse_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"/loan-applications/{application_id}/disburse", payload, headers
        )

    def list_application_endorsements(self, application_id, headers, params=None):
        return self._request(
            "GET",
            f"/loan-applications/{application_id}/endorsements",
            headers=headers,
            params=params,
        )

    def list_application_contributions(self, application_id, headers):
        return self._request(
            "GET",
            f"/loan-applications/{application_id}/contributions",
            headers=headers,
        )

    def list_application_loan(self, application_id, headers):
        return self._request(
            "GET", f"/loan-applications/{application_id}/loan", headers=headers
        )

    # --- endorsements / contributions --------------------------------------
    def create_endorsement(self, application_id, payload, headers):
        return self._request(
            "POST", f"/loan-applications/{application_id}/endorsements", payload, headers
        )

    def create_contribution(self, application_id, payload, headers):
        return self._request(
            "POST",
            f"/loan-applications/{application_id}/contributions",
            payload,
            headers,
        )

    # --- loans --------------------------------------------------------------
    def get_loan(self, loan_id, headers):
        return self._request("GET", f"/loans/{loan_id}", headers=headers)

    def finalize_schedule(self, loan_id, payload, headers):
        return self._request(
            "POST", f"/loans/{loan_id}/finalize-schedule", payload, headers
        )

    def make_payment(self, loan_id, payload, headers):
        return self._request("POST", f"/loans/{loan_id}/payments", payload, headers)

    def list_installments(self, loan_id, headers):
        return self._request(
            "GET",
            f"/loans/{loan_id}/installments",
            headers=headers,
            params={"limit": 100},
        )

    def list_loan_payments(self, loan_id, headers):
        return self._request("GET", f"/loans/{loan_id}/payments", headers=headers)

    def list_loan_impact_reports(self, loan_id, headers):
        return self._request(
            "GET", f"/loans/{loan_id}/impact-reports", headers=headers
        )

    def create_impact_report(self, loan_id, payload, headers):
        return self._request(
            "POST", f"/loans/{loan_id}/impact-reports", payload, headers
        )


api_client = ApiClient()
