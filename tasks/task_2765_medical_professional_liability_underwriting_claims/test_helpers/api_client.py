"""API client: one method per endpoint defined in the PRD.

All routes are mounted beneath the /mpl prefix.
"""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/mpl"


class ApiClient(GenericApiClient):
    # ---------------------------------------------------------------- clock
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # ------------------------------------------------------ specialty class
    def create_specialty_class(self, payload, headers):
        return self._request("POST", f"{PREFIX}/specialty-classes", payload, headers)

    def get_specialty_class(self, specialty_class_id, headers):
        return self._request(
            "GET", f"{PREFIX}/specialty-classes/{specialty_class_id}", headers=headers
        )

    def list_specialty_classes(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/specialty-classes", headers=headers, params=params
        )

    # ------------------------------------------------------------- insured
    def create_insured(self, payload, headers):
        return self._request("POST", f"{PREFIX}/insureds", payload, headers)

    def get_insured(self, insured_id, headers):
        return self._request("GET", f"{PREFIX}/insureds/{insured_id}", headers=headers)

    def list_insureds(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/insureds", headers=headers, params=params)

    def record_credentialing_decision(self, insured_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/insureds/{insured_id}/credentialing-decision",
            payload, headers,
        )

    # ---------------------------------------------------------- enrollments
    def create_enrollment(self, insured_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/insureds/{insured_id}/enrollments", payload, headers
        )

    def get_enrollment(self, enrollment_id, headers):
        return self._request(
            "GET", f"{PREFIX}/enrollments/{enrollment_id}", headers=headers
        )

    def list_enrollments(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/enrollments", headers=headers, params=params
        )

    def complete_enrollment(self, enrollment_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/enrollments/{enrollment_id}/completion", payload, headers
        )

    # ---------------------------------------------------- peer review cases
    def create_peer_review_case(self, payload, headers):
        return self._request("POST", f"{PREFIX}/peer-review-cases", payload, headers)

    def get_peer_review_case(self, case_id, headers):
        return self._request(
            "GET", f"{PREFIX}/peer-review-cases/{case_id}", headers=headers
        )

    def list_peer_review_cases(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/peer-review-cases", headers=headers, params=params
        )

    def record_review_track(self, case_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/peer-review-cases/{case_id}/reviews", payload, headers
        )

    def record_committee_vote(self, case_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/peer-review-cases/{case_id}/committee-vote",
            payload, headers,
        )

    # -------------------------------------------------------------- policy
    def create_policy(self, payload, headers):
        return self._request("POST", f"{PREFIX}/policies", payload, headers)

    def get_policy(self, policy_id, headers):
        return self._request("GET", f"{PREFIX}/policies/{policy_id}", headers=headers)

    def list_policies(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/policies", headers=headers, params=params)

    # --------------------------------------------------------- policy terms
    def create_policy_term(self, policy_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/policies/{policy_id}/terms", payload, headers
        )

    def get_policy_term(self, term_id, headers):
        return self._request(
            "GET", f"{PREFIX}/policy-terms/{term_id}", headers=headers
        )

    def list_policy_terms(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/policy-terms", headers=headers, params=params
        )

    def issue_policy_term(self, term_id, headers):
        return self._request(
            "POST", f"{PREFIX}/policy-terms/{term_id}/issuance", {}, headers
        )

    def cancel_policy_term(self, term_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/policy-terms/{term_id}/cancellation", payload, headers
        )

    # ---------------------------------------------------- tail endorsements
    def create_tail_endorsement(self, policy_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/policies/{policy_id}/tail-endorsements", payload, headers
        )

    def get_tail_endorsement(self, tail_id, headers):
        return self._request(
            "GET", f"{PREFIX}/tail-endorsements/{tail_id}", headers=headers
        )

    def list_tail_endorsements(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/tail-endorsements", headers=headers, params=params
        )

    def issue_tail_endorsement(self, tail_id, headers):
        return self._request(
            "POST", f"{PREFIX}/tail-endorsements/{tail_id}/issuance", {}, headers
        )

    # --------------------------------------------------------------- claims
    def create_claim(self, payload, headers):
        return self._request("POST", f"{PREFIX}/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"{PREFIX}/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/claims", headers=headers, params=params)

    def record_coverage_decision(self, claim_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/claims/{claim_id}/coverage-decision", payload, headers
        )

    def create_reserve_entry(self, claim_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/claims/{claim_id}/reserve-entries", payload, headers
        )

    def list_reserve_entries(self, claim_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/claims/{claim_id}/reserve-entries",
            headers=headers, params=params,
        )

    def record_litigation(self, claim_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/claims/{claim_id}/litigation", payload, headers
        )

    def pay_expense(self, claim_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/claims/{claim_id}/expense-payments", payload, headers
        )

    def record_disposition(self, claim_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/claims/{claim_id}/disposition", payload, headers
        )

    # ------------------------------------------------------- counsel firms
    def create_counsel_firm(self, payload, headers):
        return self._request("POST", f"{PREFIX}/counsel-firms", payload, headers)

    def get_counsel_firm(self, firm_id, headers):
        return self._request(
            "GET", f"{PREFIX}/counsel-firms/{firm_id}", headers=headers
        )

    def list_counsel_firms(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/counsel-firms", headers=headers, params=params
        )

    def change_panel_status(self, firm_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/counsel-firms/{firm_id}/panel-status", payload, headers
        )

    # -------------------------------------------------- counsel assignments
    def create_counsel_assignment(self, claim_id, headers):
        return self._request(
            "POST", f"{PREFIX}/claims/{claim_id}/counsel-assignments", {}, headers
        )

    def get_counsel_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"{PREFIX}/counsel-assignments/{assignment_id}", headers=headers
        )

    def list_counsel_assignments(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/counsel-assignments", headers=headers, params=params
        )

    def decline_counsel_assignment(self, assignment_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/counsel-assignments/{assignment_id}/decline",
            payload, headers,
        )

    # ---------------------------------------------- settlement negotiations
    def create_settlement_negotiation(self, claim_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/claims/{claim_id}/settlement-negotiations",
            payload, headers,
        )

    def get_settlement_negotiation(self, negotiation_id, headers):
        return self._request(
            "GET", f"{PREFIX}/settlement-negotiations/{negotiation_id}", headers=headers
        )

    def list_settlement_negotiations(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/settlement-negotiations", headers=headers, params=params
        )

    def record_authority_decision(self, negotiation_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/settlement-negotiations/{negotiation_id}/authority-decision",
            payload, headers,
        )

    def request_consent(self, negotiation_id, headers):
        return self._request(
            "POST", f"{PREFIX}/settlement-negotiations/{negotiation_id}/consent-request",
            {}, headers,
        )

    def record_consent_response(self, negotiation_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/settlement-negotiations/{negotiation_id}/consent-response",
            payload, headers,
        )

    def revise_negotiation(self, negotiation_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/settlement-negotiations/{negotiation_id}/revision",
            payload, headers,
        )

    def invoke_hammer(self, negotiation_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/settlement-negotiations/{negotiation_id}/hammer-invocation",
            payload, headers,
        )

    def pay_settlement(self, negotiation_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/settlement-negotiations/{negotiation_id}/payment",
            payload, headers,
        )

    # ---------------------------------------------------------- npdb reports
    def get_npdb_report(self, report_id, headers):
        return self._request(
            "GET", f"{PREFIX}/npdb-reports/{report_id}", headers=headers
        )

    def list_npdb_reports(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/npdb-reports", headers=headers, params=params
        )

    def submit_npdb_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/npdb-reports/{report_id}/submission", payload, headers
        )

    def void_npdb_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/npdb-reports/{report_id}/void", payload, headers
        )

    # ----------------------------------------------------------- rate filings
    def create_rate_filing(self, payload, headers):
        return self._request("POST", f"{PREFIX}/rate-filings", payload, headers)

    def get_rate_filing(self, filing_id, headers):
        return self._request(
            "GET", f"{PREFIX}/rate-filings/{filing_id}", headers=headers
        )

    def list_rate_filings(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/rate-filings", headers=headers, params=params
        )

    def submit_rate_filing(self, filing_id, headers):
        return self._request(
            "POST", f"{PREFIX}/rate-filings/{filing_id}/submission", {}, headers
        )

    def decide_rate_filing(self, filing_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/rate-filings/{filing_id}/decision", payload, headers
        )

    # -------------------------------------------------------------- analytics
    def get_severity_trend(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/analytics/severity-trend", headers=headers, params=params
        )

    # ----------------------------------------------------- raw escape hatches
    def raw_get(self, path, headers, params=None):
        """Addresses an arbitrary path — used by not-found and RBAC probes."""
        return self._request("GET", path, headers=headers, params=params)

    def raw_post(self, path, payload, headers):
        return self._request("POST", path, payload, headers)


api_client = ApiClient()
