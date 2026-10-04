"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/compliance/_clock/set_current_utc", payload, headers)

    def advance_clock(self, payload, headers):
        return self._request("POST", "/compliance/_clock/advance", payload, headers)

    # --- Registrations ---
    def create_registration(self, payload, headers):
        return self._request("POST", "/compliance/registrations", payload, headers)

    def list_registrations(self, headers, params=None):
        return self._request("GET", "/compliance/registrations", headers=headers, params=params)

    def get_registration(self, entity_id, headers):
        return self._request("GET", f"/compliance/registrations/{entity_id}", headers=headers)

    def patch_registration(self, entity_id, payload, headers):
        return self._request("PATCH", f"/compliance/registrations/{entity_id}", payload, headers)

    # --- Engagements ---
    def create_engagement(self, payload, headers):
        return self._request("POST", "/compliance/engagements", payload, headers)

    def list_engagements(self, headers, params=None):
        return self._request("GET", "/compliance/engagements", headers=headers, params=params)

    def get_engagement(self, engagement_id, headers):
        return self._request("GET", f"/compliance/engagements/{engagement_id}", headers=headers)

    def start_engagement(self, engagement_id, headers, payload=None):
        return self._request("POST", f"/compliance/engagements/{engagement_id}/start", payload or {}, headers)

    def complete_engagement(self, engagement_id, headers, payload=None):
        return self._request("POST", f"/compliance/engagements/{engagement_id}/complete", payload or {}, headers)

    def cancel_engagement(self, engagement_id, headers, payload=None):
        return self._request("POST", f"/compliance/engagements/{engagement_id}/cancel", payload or {}, headers)

    # --- Evidence ---
    def create_evidence(self, payload, headers):
        return self._request("POST", "/compliance/evidence", payload, headers)

    def list_evidence(self, headers, params=None):
        return self._request("GET", "/compliance/evidence", headers=headers, params=params)

    def get_evidence(self, evidence_id, headers):
        return self._request("GET", f"/compliance/evidence/{evidence_id}", headers=headers)

    def accept_evidence(self, evidence_id, headers, payload=None):
        return self._request("POST", f"/compliance/evidence/{evidence_id}/accept", payload or {}, headers)

    def reject_evidence(self, evidence_id, headers, payload=None):
        return self._request("POST", f"/compliance/evidence/{evidence_id}/reject", payload or {}, headers)

    # --- Self-reports ---
    def create_self_report(self, payload, headers):
        return self._request("POST", "/compliance/self-reports", payload, headers)

    def list_self_reports(self, headers, params=None):
        return self._request("GET", "/compliance/self-reports", headers=headers, params=params)

    def get_self_report(self, self_report_id, headers):
        return self._request("GET", f"/compliance/self-reports/{self_report_id}", headers=headers)

    def triage_self_report(self, self_report_id, headers, payload=None):
        return self._request("POST", f"/compliance/self-reports/{self_report_id}/triage", payload or {}, headers)

    def confirm_self_report(self, self_report_id, headers, payload=None):
        return self._request("POST", f"/compliance/self-reports/{self_report_id}/confirm", payload or {}, headers)

    def dismiss_self_report(self, self_report_id, headers, payload=None):
        return self._request("POST", f"/compliance/self-reports/{self_report_id}/dismiss", payload or {}, headers)

    # --- Violations ---
    def create_violation(self, payload, headers):
        return self._request("POST", "/compliance/violations", payload, headers)

    def list_violations(self, headers, params=None):
        return self._request("GET", "/compliance/violations", headers=headers, params=params)

    def get_violation(self, violation_id, headers):
        return self._request("GET", f"/compliance/violations/{violation_id}", headers=headers)

    def create_mitigation_plan(self, violation_id, payload, headers):
        return self._request("POST", f"/compliance/violations/{violation_id}/mitigation-plans", payload, headers)

    def complete_mitigation(self, violation_id, headers, payload=None):
        return self._request("POST", f"/compliance/violations/{violation_id}/complete-mitigation", payload or {}, headers)

    def create_appeal(self, violation_id, payload, headers):
        return self._request("POST", f"/compliance/violations/{violation_id}/appeals", payload, headers)

    # --- Mitigation plans ---
    def list_mitigation_plans(self, headers, params=None):
        return self._request("GET", "/compliance/mitigation-plans", headers=headers, params=params)

    def get_mitigation_plan(self, plan_id, headers):
        return self._request("GET", f"/compliance/mitigation-plans/{plan_id}", headers=headers)

    def approve_plan(self, plan_id, headers, payload=None):
        return self._request("POST", f"/compliance/mitigation-plans/{plan_id}/approve", payload or {}, headers)

    def reject_plan(self, plan_id, headers, payload=None):
        return self._request("POST", f"/compliance/mitigation-plans/{plan_id}/reject", payload or {}, headers)

    def resubmit_plan(self, plan_id, headers, payload=None):
        return self._request("POST", f"/compliance/mitigation-plans/{plan_id}/resubmit", payload or {}, headers)

    def verify_plan(self, plan_id, headers, payload=None):
        return self._request("POST", f"/compliance/mitigation-plans/{plan_id}/verify", payload or {}, headers)

    # --- Milestones ---
    def create_milestone(self, plan_id, payload, headers):
        return self._request("POST", f"/compliance/mitigation-plans/{plan_id}/milestones", payload, headers)

    def list_milestones(self, plan_id, headers, params=None):
        return self._request("GET", f"/compliance/mitigation-plans/{plan_id}/milestones", headers=headers, params=params)

    def get_milestone(self, milestone_id, headers):
        return self._request("GET", f"/compliance/milestones/{milestone_id}", headers=headers)

    def complete_milestone(self, milestone_id, headers, payload=None):
        return self._request("POST", f"/compliance/milestones/{milestone_id}/complete", payload or {}, headers)

    # --- Self-log entries ---
    def create_self_log_entry(self, payload, headers):
        return self._request("POST", "/compliance/self-log-entries", payload, headers)

    def list_self_log_entries(self, headers, params=None):
        return self._request("GET", "/compliance/self-log-entries", headers=headers, params=params)

    def get_self_log_entry(self, entry_id, headers):
        return self._request("GET", f"/compliance/self-log-entries/{entry_id}", headers=headers)

    def list_period_entries(self, period_id, headers, params=None):
        return self._request("GET", f"/compliance/review-periods/{period_id}/entries", headers=headers, params=params)

    def review_self_log_entry(self, entry_id, payload, headers):
        return self._request("POST", f"/compliance/self-log-entries/{entry_id}/review", payload, headers)

    # --- Review periods ---
    def create_review_period(self, headers, payload=None):
        return self._request("POST", "/compliance/review-periods", payload or {}, headers)

    def list_review_periods(self, headers, params=None):
        return self._request("GET", "/compliance/review-periods", headers=headers, params=params)

    def get_review_period(self, period_id, headers):
        return self._request("GET", f"/compliance/review-periods/{period_id}", headers=headers)

    def start_review_period(self, period_id, headers, payload=None):
        return self._request("POST", f"/compliance/review-periods/{period_id}/start-review", payload or {}, headers)

    def close_review_period(self, period_id, headers, payload=None):
        return self._request("POST", f"/compliance/review-periods/{period_id}/close", payload or {}, headers)

    # --- CIP assets ---
    def create_cip_asset(self, payload, headers):
        return self._request("POST", "/compliance/cip-assets", payload, headers)

    def list_cip_assets(self, headers, params=None):
        return self._request("GET", "/compliance/cip-assets", headers=headers, params=params)

    def get_cip_asset(self, asset_id, headers):
        return self._request("GET", f"/compliance/cip-assets/{asset_id}", headers=headers)

    def decommission_cip_asset(self, asset_id, headers, payload=None):
        return self._request("POST", f"/compliance/cip-assets/{asset_id}/decommission", payload or {}, headers)

    # --- Access grants ---
    def create_access_grant(self, payload, headers):
        return self._request("POST", "/compliance/access-grants", payload, headers)

    def list_access_grants(self, headers, params=None):
        return self._request("GET", "/compliance/access-grants", headers=headers, params=params)

    def get_access_grant(self, grant_id, headers):
        return self._request("GET", f"/compliance/access-grants/{grant_id}", headers=headers)

    def revoke_access_grant(self, grant_id, headers, payload=None):
        return self._request("POST", f"/compliance/access-grants/{grant_id}/revoke", payload or {}, headers)

    # --- Penalties ---
    def create_penalty(self, payload, headers):
        return self._request("POST", "/compliance/penalties", payload, headers)

    def list_penalties(self, headers, params=None):
        return self._request("GET", "/compliance/penalties", headers=headers, params=params)

    def get_penalty(self, penalty_id, headers):
        return self._request("GET", f"/compliance/penalties/{penalty_id}", headers=headers)

    def confirm_penalty(self, penalty_id, headers, payload=None):
        return self._request("POST", f"/compliance/penalties/{penalty_id}/confirm", payload or {}, headers)

    def settle_penalty(self, penalty_id, headers, payload=None):
        return self._request("POST", f"/compliance/penalties/{penalty_id}/settle", payload or {}, headers)

    def waive_penalty(self, penalty_id, headers, payload=None):
        return self._request("POST", f"/compliance/penalties/{penalty_id}/waive", payload or {}, headers)

    # --- Appeals ---
    def list_appeals(self, headers, params=None):
        return self._request("GET", "/compliance/appeals", headers=headers, params=params)

    def get_appeal(self, appeal_id, headers):
        return self._request("GET", f"/compliance/appeals/{appeal_id}", headers=headers)

    def grant_appeal(self, appeal_id, headers, payload=None):
        return self._request("POST", f"/compliance/appeals/{appeal_id}/grant", payload or {}, headers)

    def deny_appeal(self, appeal_id, headers, payload=None):
        return self._request("POST", f"/compliance/appeals/{appeal_id}/deny", payload or {}, headers)

    def request_federal_review(self, appeal_id, headers, payload=None):
        return self._request("POST", f"/compliance/appeals/{appeal_id}/request-federal-review", payload or {}, headers)


api_client = ApiClient()
