"""API client: one method per endpoint the PRD exposes."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- ReductionPlan --------------------------------------------------
    def create_reduction_plan(self, payload, headers):
        return self._request("POST", "/reduction-plans", payload, headers)

    def get_reduction_plan(self, plan_id, headers):
        return self._request("GET", f"/reduction-plans/{plan_id}", headers=headers)

    def lock_criteria(self, plan_id, headers, payload=None):
        return self._request(
            "POST", f"/reduction-plans/{plan_id}/lock-criteria", payload or {}, headers
        )

    def submit_legal_review(self, plan_id, headers, payload=None):
        return self._request(
            "POST",
            f"/reduction-plans/{plan_id}/submit-legal-review",
            payload or {},
            headers,
        )

    def legal_decision(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/reduction-plans/{plan_id}/legal-decision", payload, headers
        )

    def execute_plan(self, plan_id, headers, payload=None):
        return self._request(
            "POST", f"/reduction-plans/{plan_id}/execute", payload or {}, headers
        )

    def selection_batch(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/reduction-plans/{plan_id}/selection-batch", payload, headers
        )

    def decide_batch(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/reduction-plans/{plan_id}/decide-batch", payload, headers
        )

    # ---- Site -----------------------------------------------------------
    def create_site(self, payload, headers):
        return self._request("POST", "/sites", payload, headers)

    def get_site(self, site_id, headers):
        return self._request("GET", f"/sites/{site_id}", headers=headers)

    def roster_import(self, site_id, payload, headers):
        return self._request(
            "POST", f"/sites/{site_id}/roster-import", payload, headers
        )

    # ---- Employee -------------------------------------------------------
    def create_employee(self, payload, headers):
        return self._request("POST", "/employees", payload, headers)

    def get_employee(self, employee_id, headers):
        return self._request("GET", f"/employees/{employee_id}", headers=headers)

    def list_employees(self, headers, params=None):
        return self._request("GET", "/employees", headers=headers, params=params)

    # ---- Selection ------------------------------------------------------
    def create_selection(self, payload, headers):
        return self._request("POST", "/selections", payload, headers)

    def get_selection(self, selection_id, headers):
        return self._request("GET", f"/selections/{selection_id}", headers=headers)

    def list_selections(self, headers, params=None):
        return self._request("GET", "/selections", headers=headers, params=params)

    def decide_selection(self, selection_id, payload, headers):
        return self._request(
            "POST", f"/selections/{selection_id}/decide", payload, headers
        )

    def rescind_selection(self, selection_id, payload, headers):
        return self._request(
            "POST", f"/selections/{selection_id}/rescind", payload, headers
        )

    def deliver_notice(self, selection_id, payload, headers):
        return self._request(
            "POST", f"/selections/{selection_id}/deliver-notice", payload, headers
        )

    # ---- WarnRule -------------------------------------------------------
    def create_warn_rule(self, payload, headers):
        return self._request("POST", "/warn-rules", payload, headers)

    def get_warn_rule(self, rule_id, headers):
        return self._request("GET", f"/warn-rules/{rule_id}", headers=headers)

    # ---- AdverseImpactAnalysis ------------------------------------------
    def create_analysis(self, payload, headers):
        return self._request("POST", "/adverse-impact-analyses", payload, headers)

    def get_analysis(self, analysis_id, headers):
        return self._request(
            "GET", f"/adverse-impact-analyses/{analysis_id}", headers=headers
        )

    def list_analyses(self, headers, params=None):
        return self._request(
            "GET", "/adverse-impact-analyses", headers=headers, params=params
        )

    def clear_analysis(self, analysis_id, payload, headers):
        return self._request(
            "POST", f"/adverse-impact-analyses/{analysis_id}/clear", payload, headers
        )

    # ---- OwbpaDisclosure ------------------------------------------------
    def create_disclosure(self, payload, headers):
        return self._request("POST", "/owbpa-disclosures", payload, headers)

    def get_disclosure(self, disclosure_id, headers):
        return self._request(
            "GET", f"/owbpa-disclosures/{disclosure_id}", headers=headers
        )

    def list_disclosures(self, headers, params=None):
        return self._request(
            "GET", "/owbpa-disclosures", headers=headers, params=params
        )

    # ---- WarnNotice -----------------------------------------------------
    def create_warn_notice(self, payload, headers):
        return self._request("POST", "/warn-notices", payload, headers)

    def get_warn_notice(self, notice_id, headers):
        return self._request("GET", f"/warn-notices/{notice_id}", headers=headers)

    def list_warn_notices(self, headers, params=None):
        return self._request("GET", "/warn-notices", headers=headers, params=params)

    def issue_warn_notice(self, notice_id, headers, payload=None):
        return self._request(
            "POST", f"/warn-notices/{notice_id}/issue", payload or {}, headers
        )

    # ---- SeveranceOffer -------------------------------------------------
    def create_severance_offer(self, payload, headers):
        return self._request("POST", "/severance-offers", payload, headers)

    def get_severance_offer(self, offer_id, headers):
        return self._request("GET", f"/severance-offers/{offer_id}", headers=headers)

    def list_severance_offers(self, headers, params=None):
        return self._request(
            "GET", "/severance-offers", headers=headers, params=params
        )

    def issue_severance_offer(self, offer_id, headers, payload=None):
        return self._request(
            "POST", f"/severance-offers/{offer_id}/issue", payload or {}, headers
        )

    def sign_severance_offer(self, offer_id, headers, payload=None):
        return self._request(
            "POST", f"/severance-offers/{offer_id}/sign", payload or {}, headers
        )

    def revoke_severance_offer(self, offer_id, payload, headers):
        return self._request(
            "POST", f"/severance-offers/{offer_id}/revoke", payload, headers
        )

    # ---- PositionRestriction --------------------------------------------
    def get_position_restriction(self, restriction_id, headers):
        return self._request(
            "GET", f"/position-restrictions/{restriction_id}", headers=headers
        )

    def list_position_restrictions(self, headers, params=None):
        return self._request(
            "GET", "/position-restrictions", headers=headers, params=params
        )

    def waive_position_restriction(self, restriction_id, payload, headers):
        return self._request(
            "POST", f"/position-restrictions/{restriction_id}/waive", payload, headers
        )

    # ---- Logical clock --------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ---- Raw helpers used by header-omission tests ----------------------
    def raw_get(self, path, headers=None, params=None):
        return self._request("GET", path, headers=headers, params=params)

    def raw_post(self, path, payload=None, headers=None):
        return self._request("POST", path, payload or {}, headers)


api_client = ApiClient()
