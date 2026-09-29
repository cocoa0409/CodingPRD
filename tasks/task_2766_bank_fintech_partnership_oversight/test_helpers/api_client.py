"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/oversight"


class ApiClient(GenericApiClient):
    # ---------------- logical clock ----------------
    def set_current_utc(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---------------- partners ----------------
    def create_partner(self, payload, headers):
        return self._request("POST", f"{PREFIX}/partners", payload, headers)

    def list_partners(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/partners", headers=headers, params=params)

    def get_partner(self, partner_id, headers):
        return self._request("GET", f"{PREFIX}/partners/{partner_id}", headers=headers)

    def get_oversight_summary(self, partner_id, headers):
        return self._request(
            "GET", f"{PREFIX}/partners/{partner_id}/oversight-summary", headers=headers
        )

    def report_account_census(self, partner_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/partners/{partner_id}/account-census", payload, headers
        )

    def go_live(self, partner_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/partners/{partner_id}/go-live", payload or {}, headers
        )

    # ---------------- diligence reviews ----------------
    def create_diligence_review(self, payload, headers):
        return self._request("POST", f"{PREFIX}/diligence-reviews", payload, headers)

    def list_diligence_reviews(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/diligence-reviews", headers=headers, params=params
        )

    def get_diligence_review(self, review_id, headers):
        return self._request(
            "GET", f"{PREFIX}/diligence-reviews/{review_id}", headers=headers
        )

    def submit_diligence_review(self, review_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/diligence-reviews/{review_id}/submit", payload or {}, headers
        )

    def decide_diligence_review(self, review_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/diligence-reviews/{review_id}/decide", payload, headers
        )

    # ---------------- program agreements ----------------
    def create_agreement(self, payload, headers):
        return self._request("POST", f"{PREFIX}/agreements", payload, headers)

    def list_agreements(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/agreements", headers=headers, params=params)

    def get_agreement(self, agreement_id, headers):
        return self._request("GET", f"{PREFIX}/agreements/{agreement_id}", headers=headers)

    def submit_agreement_for_approval(self, agreement_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/agreements/{agreement_id}/submit-for-approval",
            payload or {},
            headers,
        )

    def decide_agreement_risk(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/agreements/{agreement_id}/risk-decision", payload, headers
        )

    def terminate_agreement(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/agreements/{agreement_id}/terminate", payload, headers
        )

    # ---------------- marketing reviews ----------------
    def create_marketing_review(self, payload, headers):
        return self._request("POST", f"{PREFIX}/marketing-reviews", payload, headers)

    def list_marketing_reviews(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/marketing-reviews", headers=headers, params=params
        )

    def get_marketing_review(self, review_id, headers):
        return self._request(
            "GET", f"{PREFIX}/marketing-reviews/{review_id}", headers=headers
        )

    def decide_marketing_review(self, review_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/marketing-reviews/{review_id}/decide", payload, headers
        )

    def resubmit_marketing_review(self, review_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/marketing-reviews/{review_id}/resubmit", payload, headers
        )

    # ---------------- custody accounts ----------------
    def list_custody_accounts(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/custody-accounts", headers=headers, params=params
        )

    def get_custody_account(self, account_id, headers):
        return self._request(
            "GET", f"{PREFIX}/custody-accounts/{account_id}", headers=headers
        )

    # ---------------- settlement batches ----------------
    def create_settlement_batch(self, payload, headers):
        return self._request("POST", f"{PREFIX}/settlement-batches", payload, headers)

    def list_settlement_batches(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/settlement-batches", headers=headers, params=params
        )

    def get_settlement_batch(self, batch_id, headers):
        return self._request(
            "GET", f"{PREFIX}/settlement-batches/{batch_id}", headers=headers
        )

    def reconcile_settlement_batch(self, batch_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/settlement-batches/{batch_id}/reconcile", payload, headers
        )

    def clear_settlement_variance(self, batch_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/settlement-batches/{batch_id}/clear-variance",
            payload,
            headers,
        )

    def fund_settlement_batch(self, batch_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/settlement-batches/{batch_id}/fund", payload, headers
        )

    def clawback_settlement_batch(self, batch_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/settlement-batches/{batch_id}/clawback", payload, headers
        )

    # ---------------- ledger entries ----------------
    def create_ledger_entry(self, payload, headers):
        return self._request("POST", f"{PREFIX}/ledger-entries", payload, headers)

    def list_ledger_entries(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/ledger-entries", headers=headers, params=params
        )

    def get_ledger_entry(self, entry_id, headers):
        return self._request("GET", f"{PREFIX}/ledger-entries/{entry_id}", headers=headers)

    # ---------------- complaints ----------------
    def create_complaint(self, payload, headers):
        return self._request("POST", f"{PREFIX}/complaints", payload, headers)

    def list_complaints(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/complaints", headers=headers, params=params)

    def get_complaint(self, complaint_id, headers):
        return self._request("GET", f"{PREFIX}/complaints/{complaint_id}", headers=headers)

    def assign_complaint_root_cause(self, complaint_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/complaints/{complaint_id}/assign-root-cause", payload, headers
        )

    def dispose_complaint(self, complaint_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/complaints/{complaint_id}/disposition", payload, headers
        )

    # ---------------- monitoring alerts ----------------
    def create_alert(self, payload, headers):
        return self._request("POST", f"{PREFIX}/alerts", payload, headers)

    def list_alerts(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/alerts", headers=headers, params=params)

    def get_alert(self, alert_id, headers):
        return self._request("GET", f"{PREFIX}/alerts/{alert_id}", headers=headers)

    def dispose_alert(self, alert_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/alerts/{alert_id}/dispose", payload, headers
        )

    # ---------------- oversight cycles ----------------
    def create_cycle(self, payload, headers):
        return self._request("POST", f"{PREFIX}/cycles", payload, headers)

    def list_cycles(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/cycles", headers=headers, params=params)

    def get_cycle(self, cycle_id, headers):
        return self._request("GET", f"{PREFIX}/cycles/{cycle_id}", headers=headers)

    def close_cycle(self, cycle_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/cycles/{cycle_id}/close", payload or {}, headers
        )

    # ---------------- wind-down plans ----------------
    def create_wind_down_plan(self, payload, headers):
        return self._request("POST", f"{PREFIX}/wind-down-plans", payload, headers)

    def list_wind_down_plans(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/wind-down-plans", headers=headers, params=params
        )

    def get_wind_down_plan(self, plan_id, headers):
        return self._request(
            "GET", f"{PREFIX}/wind-down-plans/{plan_id}", headers=headers
        )

    def submit_wind_down_plan(self, plan_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/wind-down-plans/{plan_id}/submit", payload or {}, headers
        )

    def decide_wind_down_plan(self, plan_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/wind-down-plans/{plan_id}/decide", payload, headers
        )

    def execute_wind_down_plan(self, plan_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/wind-down-plans/{plan_id}/execute", payload or {}, headers
        )


api_client = ApiClient()
