"""API client: one method per endpoint defined in the PRD (§4).

All resources are mounted under the `/wetland-permits` prefix except the
platform logical-clock capability, which lives outside the prefix at
`/_clock/set_current_utc` (PRD §1/§2.5/§4).
"""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/wetland-permits"


class ApiClient(GenericApiClient):
    # ---- platform logical clock (OUTSIDE the /wetland-permits prefix) ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---- applicants ------------------------------------------------------
    def create_applicant(self, payload, headers):
        return self._request("POST", f"{PREFIX}/applicants", payload, headers)

    def get_applicant(self, applicant_id, headers):
        return self._request("GET", f"{PREFIX}/applicants/{applicant_id}", headers=headers)

    # ---- waters sites ------------------------------------------------------
    def create_site(self, payload, headers):
        return self._request("POST", f"{PREFIX}/sites", payload, headers)

    def list_sites(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/sites", headers=headers, params=params)

    def get_site(self, site_id, headers):
        return self._request("GET", f"{PREFIX}/sites/{site_id}", headers=headers)

    # ---- jurisdictional determinations -------------------------------------
    def create_jd(self, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/jurisdictional-determinations", payload, headers
        )

    def list_jds(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/jurisdictional-determinations", headers=headers, params=params
        )

    def get_jd(self, jd_id, headers):
        return self._request(
            "GET", f"{PREFIX}/jurisdictional-determinations/{jd_id}", headers=headers
        )

    def issue_jd(self, jd_id, headers):
        return self._request(
            "POST", f"{PREFIX}/jurisdictional-determinations/{jd_id}/issue", {}, headers
        )

    # ---- appeals -----------------------------------------------------------
    def create_appeal(self, payload, headers):
        return self._request("POST", f"{PREFIX}/appeals", payload, headers)

    def list_appeals(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/appeals", headers=headers, params=params)

    def get_appeal(self, appeal_id, headers):
        return self._request("GET", f"{PREFIX}/appeals/{appeal_id}", headers=headers)

    def decide_appeal(self, appeal_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/appeals/{appeal_id}/decide", payload, headers
        )

    # ---- permit applications -------------------------------------------------
    def create_application(self, payload, headers):
        return self._request("POST", f"{PREFIX}/applications", payload, headers)

    def list_applications(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/applications", headers=headers, params=params
        )

    def get_application(self, application_id, headers):
        return self._request(
            "GET", f"{PREFIX}/applications/{application_id}", headers=headers
        )

    def patch_application(self, application_id, payload, headers):
        return self._request(
            "PATCH", f"{PREFIX}/applications/{application_id}", payload, headers
        )

    def submit_application(self, application_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/applications/{application_id}/submit",
            payload if payload is not None else {},
            headers,
        )

    def screening_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/applications/{application_id}/screening", payload, headers
        )

    def publish_notice(self, application_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/applications/{application_id}/publish-notice",
            payload if payload is not None else {},
            headers,
        )

    def advance_to_decision(self, application_id, headers):
        return self._request(
            "POST",
            f"{PREFIX}/applications/{application_id}/advance-to-decision",
            {},
            headers,
        )

    def render_decision(self, application_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/applications/{application_id}/render-decision", payload, headers
        )

    def withdraw_application(self, application_id, headers):
        return self._request(
            "POST", f"{PREFIX}/applications/{application_id}/withdraw", {}, headers
        )

    # ---- alternatives analyses ---------------------------------------------
    def create_alternatives_analysis(self, payload, headers):
        return self._request("POST", f"{PREFIX}/alternatives-analyses", payload, headers)

    def list_alternatives_analyses(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/alternatives-analyses", headers=headers, params=params
        )

    def get_alternatives_analysis(self, aa_id, headers):
        return self._request(
            "GET", f"{PREFIX}/alternatives-analyses/{aa_id}", headers=headers
        )

    def patch_alternatives_analysis(self, aa_id, payload, headers):
        return self._request(
            "PATCH", f"{PREFIX}/alternatives-analyses/{aa_id}", payload, headers
        )

    def review_alternatives_analysis(self, aa_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/alternatives-analyses/{aa_id}/review", payload, headers
        )

    # ---- agency comments -----------------------------------------------------
    def create_agency_comment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/agency-comments", payload, headers)

    def list_agency_comments(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/agency-comments", headers=headers, params=params
        )

    def get_agency_comment(self, comment_id, headers):
        return self._request("GET", f"{PREFIX}/agency-comments/{comment_id}", headers=headers)

    def resolve_agency_comment(self, comment_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/agency-comments/{comment_id}/resolve", payload, headers
        )

    # ---- mitigation plans ----------------------------------------------------
    def create_mitigation_plan(self, payload, headers):
        return self._request("POST", f"{PREFIX}/mitigation-plans", payload, headers)

    def list_mitigation_plans(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/mitigation-plans", headers=headers, params=params
        )

    def get_mitigation_plan(self, plan_id, headers):
        return self._request(
            "GET", f"{PREFIX}/mitigation-plans/{plan_id}", headers=headers
        )

    def patch_mitigation_plan(self, plan_id, payload, headers):
        return self._request(
            "PATCH", f"{PREFIX}/mitigation-plans/{plan_id}", payload, headers
        )

    def submit_mitigation_plan(self, plan_id, headers):
        return self._request(
            "POST", f"{PREFIX}/mitigation-plans/{plan_id}/submit", {}, headers
        )

    def review_mitigation_plan(self, plan_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/mitigation-plans/{plan_id}/review", payload, headers
        )

    def secure_credits(self, plan_id, headers):
        return self._request(
            "POST", f"{PREFIX}/mitigation-plans/{plan_id}/secure-credits", {}, headers
        )

    def pay_in_lieu_fee(self, plan_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/mitigation-plans/{plan_id}/pay-in-lieu-fee", payload, headers
        )

    # ---- mitigation banks ----------------------------------------------------
    def create_mitigation_bank(self, payload, headers):
        return self._request("POST", f"{PREFIX}/mitigation-banks", payload, headers)

    def list_mitigation_banks(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/mitigation-banks", headers=headers, params=params
        )

    def get_mitigation_bank(self, bank_id, headers):
        return self._request(
            "GET", f"{PREFIX}/mitigation-banks/{bank_id}", headers=headers
        )

    def approve_mitigation_bank(self, bank_id, headers):
        return self._request(
            "POST", f"{PREFIX}/mitigation-banks/{bank_id}/approve", {}, headers
        )

    def suspend_mitigation_bank(self, bank_id, headers):
        return self._request(
            "POST", f"{PREFIX}/mitigation-banks/{bank_id}/suspend", {}, headers
        )

    # ---- credit transactions -------------------------------------------------
    def create_credit_transaction(self, payload, headers):
        return self._request("POST", f"{PREFIX}/credit-transactions", payload, headers)

    def list_credit_transactions(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/credit-transactions", headers=headers, params=params
        )

    def get_credit_transaction(self, txn_id, headers):
        return self._request(
            "GET", f"{PREFIX}/credit-transactions/{txn_id}", headers=headers
        )

    def purchase_credit_transaction(self, txn_id, headers):
        return self._request(
            "POST", f"{PREFIX}/credit-transactions/{txn_id}/purchase", {}, headers
        )

    def release_credit_transaction(self, txn_id, headers):
        return self._request(
            "POST", f"{PREFIX}/credit-transactions/{txn_id}/release", {}, headers
        )

    # ---- permits ---------------------------------------------------------------
    def list_permits(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/permits", headers=headers, params=params)

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"{PREFIX}/permits/{permit_id}", headers=headers)

    def commence_work(self, permit_id, headers):
        return self._request(
            "POST", f"{PREFIX}/permits/{permit_id}/commence-work", {}, headers
        )

    def reinstate_permit(self, permit_id, headers):
        return self._request(
            "POST", f"{PREFIX}/permits/{permit_id}/reinstate", {}, headers
        )

    def close_permit(self, permit_id, headers):
        return self._request("POST", f"{PREFIX}/permits/{permit_id}/close", {}, headers)

    # ---- monitoring reports ----------------------------------------------------
    def list_monitoring_reports(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/monitoring-reports", headers=headers, params=params
        )

    def get_monitoring_report(self, report_id, headers):
        return self._request(
            "GET", f"{PREFIX}/monitoring-reports/{report_id}", headers=headers
        )

    def submit_monitoring_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/monitoring-reports/{report_id}/submit", payload, headers
        )

    def review_monitoring_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/monitoring-reports/{report_id}/review", payload, headers
        )

    # ---- enforcement cases -------------------------------------------------------
    def create_enforcement_case(self, payload, headers):
        return self._request("POST", f"{PREFIX}/enforcement-cases", payload, headers)

    def list_enforcement_cases(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/enforcement-cases", headers=headers, params=params
        )

    def get_enforcement_case(self, case_id, headers):
        return self._request(
            "GET", f"{PREFIX}/enforcement-cases/{case_id}", headers=headers
        )

    def confirm_violation(self, case_id, headers):
        return self._request(
            "POST", f"{PREFIX}/enforcement-cases/{case_id}/confirm-violation", {}, headers
        )

    def set_resolution(self, case_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/enforcement-cases/{case_id}/set-resolution", payload, headers
        )

    def verify_restoration(self, case_id, headers):
        return self._request(
            "POST", f"{PREFIX}/enforcement-cases/{case_id}/verify-restoration", {}, headers
        )

    def grant_extension(self, case_id, headers):
        return self._request(
            "POST", f"{PREFIX}/enforcement-cases/{case_id}/grant-extension", {}, headers
        )


api_client = ApiClient()
