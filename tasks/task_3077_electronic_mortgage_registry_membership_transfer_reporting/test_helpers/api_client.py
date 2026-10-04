"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/registry"


class ApiClient(GenericApiClient):
    # ---------------- logical clock ----------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---------------- members ----------------
    def create_member(self, payload, headers):
        return self._request("POST", f"{PREFIX}/members", payload, headers)

    def list_members(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/members", headers=headers, params=params)

    def get_member(self, member_id, headers):
        return self._request("GET", f"{PREFIX}/members/{member_id}", headers=headers)

    def activate_member(self, member_id, headers):
        return self._request(
            "POST", f"{PREFIX}/members/{member_id}/activate", {}, headers
        )

    def suspend_member(self, member_id, headers):
        return self._request(
            "POST", f"{PREFIX}/members/{member_id}/suspend", {}, headers
        )

    def reinstate_member(self, member_id, headers):
        return self._request(
            "POST", f"{PREFIX}/members/{member_id}/reinstate", {}, headers
        )

    def terminate_member(self, member_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/members/{member_id}/terminate", payload, headers
        )

    # ---------------- authorized signers ----------------
    def create_signer(self, member_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/members/{member_id}/signers", payload, headers
        )

    def list_signers(self, member_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/members/{member_id}/signers", headers=headers, params=params
        )

    def get_signer_nested(self, member_id, signer_id, headers):
        return self._request(
            "GET",
            f"{PREFIX}/members/{member_id}/signers/{signer_id}",
            headers=headers,
        )

    def get_signer(self, signer_id, headers):
        return self._request("GET", f"{PREFIX}/signers/{signer_id}", headers=headers)

    def list_signers_flat(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/signers", headers=headers, params=params)

    def revoke_signer(self, member_id, signer_id, headers):
        return self._request(
            "POST",
            f"{PREFIX}/members/{member_id}/signers/{signer_id}/revoke",
            {},
            headers,
        )

    # ---------------- loans ----------------
    def create_loan(self, payload, headers):
        return self._request("POST", f"{PREFIX}/loans", payload, headers)

    def list_loans(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/loans", headers=headers, params=params)

    def get_loan(self, loan_id, headers):
        return self._request("GET", f"{PREFIX}/loans/{loan_id}", headers=headers)

    def foreclose_loan(self, loan_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/loans/{loan_id}/foreclose", payload, headers
        )

    def rescind_foreclosure(self, loan_id, headers):
        return self._request(
            "POST", f"{PREFIX}/loans/{loan_id}/rescind-foreclosure", {}, headers
        )

    def satisfy_loan(self, loan_id, headers):
        return self._request("POST", f"{PREFIX}/loans/{loan_id}/satisfy", {}, headers)

    # ---------------- transfers ----------------
    def create_transfer(self, payload, headers):
        return self._request("POST", f"{PREFIX}/transfers", payload, headers)

    def list_transfers(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/transfers", headers=headers, params=params)

    def get_transfer(self, transfer_id, headers):
        return self._request("GET", f"{PREFIX}/transfers/{transfer_id}", headers=headers)

    def match_confirm(self, transfer_id, headers):
        return self._request(
            "POST", f"{PREFIX}/transfers/{transfer_id}/match-confirm", {}, headers
        )

    def reject_match(self, transfer_id, headers):
        return self._request(
            "POST", f"{PREFIX}/transfers/{transfer_id}/reject-match", {}, headers
        )

    def list_transfer_matches(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/transfer-matches", headers=headers, params=params
        )

    def get_transfer_match(self, match_id, headers):
        return self._request(
            "GET", f"{PREFIX}/transfer-matches/{match_id}", headers=headers
        )

    # ---------------- borrower inquiry ----------------
    def borrower_inquiry(self, min_value, headers):
        return self._request(
            "GET", f"{PREFIX}/borrower-inquiries/{min_value}", headers=headers
        )

    # ---------------- QA reviews / findings ----------------
    def create_qa_review(self, payload, headers):
        return self._request("POST", f"{PREFIX}/qa-reviews", payload, headers)

    def list_qa_reviews(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/qa-reviews", headers=headers, params=params)

    def get_qa_review(self, review_id, headers):
        return self._request("GET", f"{PREFIX}/qa-reviews/{review_id}", headers=headers)

    def create_finding(self, review_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/qa-reviews/{review_id}/findings", payload, headers
        )

    def list_findings(self, review_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/qa-reviews/{review_id}/findings",
            headers=headers,
            params=params,
        )

    def get_finding_nested(self, review_id, finding_id, headers):
        return self._request(
            "GET",
            f"{PREFIX}/qa-reviews/{review_id}/findings/{finding_id}",
            headers=headers,
        )

    def get_finding(self, finding_id, headers):
        return self._request("GET", f"{PREFIX}/qa-findings/{finding_id}", headers=headers)

    def list_findings_flat(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/qa-findings", headers=headers, params=params)

    def issue_review(self, review_id, headers):
        return self._request(
            "POST", f"{PREFIX}/qa-reviews/{review_id}/issue", {}, headers
        )

    def reopen_review(self, review_id, headers):
        return self._request(
            "POST", f"{PREFIX}/qa-reviews/{review_id}/reopen", {}, headers
        )

    def settle_review(self, review_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/qa-reviews/{review_id}/settle", payload, headers
        )

    # ---------------- sanctions ----------------
    def list_sanctions(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/sanctions", headers=headers, params=params)

    def get_sanction(self, sanction_id, headers):
        return self._request("GET", f"{PREFIX}/sanctions/{sanction_id}", headers=headers)

    def appeal_sanction(self, sanction_id, headers):
        return self._request(
            "POST", f"{PREFIX}/sanctions/{sanction_id}/appeal", {}, headers
        )

    def adjudicate_sanction(self, sanction_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/sanctions/{sanction_id}/adjudicate", payload, headers
        )

    def pay_sanction(self, sanction_id, headers):
        return self._request("POST", f"{PREFIX}/sanctions/{sanction_id}/pay", {}, headers)

    # ---------------- annual reports ----------------
    def create_annual_report(self, member_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/members/{member_id}/annual-reports", payload, headers
        )

    def list_annual_reports(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/annual-reports", headers=headers, params=params
        )

    def get_annual_report(self, report_id, headers):
        return self._request(
            "GET", f"{PREFIX}/annual-reports/{report_id}", headers=headers
        )

    # ---------------- SOR reconciliation ----------------
    def create_sor_run(self, payload, headers):
        return self._request("POST", f"{PREFIX}/sor-reconciliation-runs", payload, headers)

    def list_sor_runs(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/sor-reconciliation-runs", headers=headers, params=params
        )

    def get_sor_run(self, run_id, headers):
        return self._request(
            "GET", f"{PREFIX}/sor-reconciliation-runs/{run_id}", headers=headers
        )

    def list_sor_exceptions(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/sor-exceptions", headers=headers, params=params
        )

    def get_sor_exception(self, exception_id, headers):
        return self._request(
            "GET", f"{PREFIX}/sor-exceptions/{exception_id}", headers=headers
        )

    def resolve_sor_exception(self, exception_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/sor-exceptions/{exception_id}/resolve",
            payload or {},
            headers,
        )


api_client = ApiClient()
