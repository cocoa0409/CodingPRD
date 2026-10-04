"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Plan catalog ---
    def create_plan_catalog_entry(self, payload, headers):
        return self._request("POST", "/v1/plan-catalog", payload, headers)

    def list_plan_catalog(self, headers, params=None):
        return self._request("GET", "/v1/plan-catalog", headers=headers, params=params)

    # --- Teams ---
    def create_team(self, payload, headers):
        return self._request("POST", "/v1/teams", payload, headers)

    def list_teams(self, headers, params=None):
        return self._request("GET", "/v1/teams", headers=headers, params=params)

    def get_team(self, team_id, headers):
        return self._request("GET", f"/v1/teams/{team_id}", headers=headers)

    def update_team(self, team_id, payload, headers):
        return self._request("PATCH", f"/v1/teams/{team_id}", payload, headers)

    # --- Members ---
    def add_member(self, team_id, payload, headers):
        return self._request("POST", f"/v1/teams/{team_id}/members", payload, headers)

    def list_team_members(self, team_id, headers, params=None):
        return self._request("GET", f"/v1/teams/{team_id}/members", headers=headers, params=params)

    def get_team_member(self, team_id, member_id, headers):
        return self._request("GET", f"/v1/teams/{team_id}/members/{member_id}", headers=headers)

    def delete_member(self, team_id, member_id, headers):
        return self._request("DELETE", f"/v1/teams/{team_id}/members/{member_id}", headers=headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/v1/members", headers=headers, params=params)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/v1/members/{member_id}", headers=headers)

    # --- Projects ---
    def create_project(self, team_id, payload, headers):
        return self._request("POST", f"/v1/teams/{team_id}/projects", payload, headers)

    def list_team_projects(self, team_id, headers, params=None):
        return self._request("GET", f"/v1/teams/{team_id}/projects", headers=headers, params=params)

    def list_projects(self, headers, params=None):
        return self._request("GET", "/v1/projects", headers=headers, params=params)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/v1/projects/{project_id}", headers=headers)

    def update_project(self, project_id, payload, headers):
        return self._request("PATCH", f"/v1/projects/{project_id}", payload, headers)

    def archive_project(self, project_id, headers):
        return self._request("POST", f"/v1/projects/{project_id}/archive", {}, headers)

    def resume_project(self, project_id, headers):
        return self._request("POST", f"/v1/projects/{project_id}/resume", {}, headers)

    def rollback_project(self, project_id, headers):
        return self._request("POST", f"/v1/projects/{project_id}/rollback", {}, headers)

    # --- Deployments ---
    def create_git_event(self, payload, headers):
        return self._request("POST", "/v1/git-events", payload, headers)

    def list_deployments(self, headers, params=None):
        return self._request("GET", "/v1/deployments", headers=headers, params=params)

    def get_deployment(self, deployment_id, headers):
        return self._request("GET", f"/v1/deployments/{deployment_id}", headers=headers)

    def build_start(self, deployment_id, headers):
        return self._request("POST", f"/v1/deployments/{deployment_id}/build-start", {}, headers)

    def build_complete(self, deployment_id, payload, headers):
        return self._request("POST", f"/v1/deployments/{deployment_id}/build-complete", payload, headers)

    def cancel_deployment(self, deployment_id, headers):
        return self._request("POST", f"/v1/deployments/{deployment_id}/cancel", {}, headers)

    def promote_deployment(self, deployment_id, headers):
        return self._request("POST", f"/v1/deployments/{deployment_id}/promote", {}, headers)

    # --- Environment variables ---
    def create_env_var(self, project_id, payload, headers):
        return self._request("POST", f"/v1/projects/{project_id}/env-vars", payload, headers)

    def list_env_vars(self, project_id, headers, params=None):
        return self._request("GET", f"/v1/projects/{project_id}/env-vars", headers=headers, params=params)

    def get_env_var(self, env_var_id, headers):
        return self._request("GET", f"/v1/env-vars/{env_var_id}", headers=headers)

    def update_env_var(self, env_var_id, payload, headers):
        return self._request("PATCH", f"/v1/env-vars/{env_var_id}", payload, headers)

    def delete_env_var(self, env_var_id, headers):
        return self._request("DELETE", f"/v1/env-vars/{env_var_id}", headers=headers)

    # --- Domains ---
    def create_domain(self, project_id, payload, headers):
        return self._request("POST", f"/v1/projects/{project_id}/domains", payload, headers)

    def list_domains(self, project_id, headers, params=None):
        return self._request("GET", f"/v1/projects/{project_id}/domains", headers=headers, params=params)

    def get_domain(self, domain_id, headers):
        return self._request("GET", f"/v1/domains/{domain_id}", headers=headers)

    def update_domain(self, domain_id, payload, headers):
        return self._request("PATCH", f"/v1/domains/{domain_id}", payload, headers)

    def verify_domain(self, domain_id, payload, headers):
        return self._request("POST", f"/v1/domains/{domain_id}/verify", payload, headers)

    def reverify_domain(self, domain_id, headers):
        return self._request("POST", f"/v1/domains/{domain_id}/reverify", {}, headers)

    def delete_domain(self, domain_id, headers):
        return self._request("DELETE", f"/v1/domains/{domain_id}", headers=headers)

    # --- Certificates ---
    def list_certificates(self, domain_id, headers, params=None):
        return self._request("GET", f"/v1/domains/{domain_id}/certificates", headers=headers, params=params)

    def get_certificate(self, certificate_id, headers):
        return self._request("GET", f"/v1/certificates/{certificate_id}", headers=headers)

    def complete_certificate(self, certificate_id, headers):
        return self._request("POST", f"/v1/certificates/{certificate_id}/complete", {}, headers)

    def revoke_certificate(self, certificate_id, headers):
        return self._request("POST", f"/v1/certificates/{certificate_id}/revoke", {}, headers)

    # --- Redirects ---
    def create_redirect(self, project_id, payload, headers):
        return self._request("POST", f"/v1/projects/{project_id}/redirects", payload, headers)

    def list_redirects(self, project_id, headers, params=None):
        return self._request("GET", f"/v1/projects/{project_id}/redirects", headers=headers, params=params)

    def get_redirect(self, redirect_id, headers):
        return self._request("GET", f"/v1/redirects/{redirect_id}", headers=headers)

    def delete_redirect(self, redirect_id, headers):
        return self._request("DELETE", f"/v1/redirects/{redirect_id}", headers=headers)

    # --- Usage periods & events ---
    def create_usage_period(self, team_id, payload, headers):
        return self._request("POST", f"/v1/teams/{team_id}/usage-periods", payload, headers)

    def list_team_usage_periods(self, team_id, headers, params=None):
        return self._request("GET", f"/v1/teams/{team_id}/usage-periods", headers=headers, params=params)

    def list_usage_periods(self, headers, params=None):
        return self._request("GET", "/v1/usage-periods", headers=headers, params=params)

    def get_usage_period(self, period_id, headers):
        return self._request("GET", f"/v1/usage-periods/{period_id}", headers=headers)

    def close_usage_period(self, period_id, headers):
        return self._request("POST", f"/v1/usage-periods/{period_id}/close", {}, headers)

    def invoice_usage_period(self, period_id, headers):
        return self._request("POST", f"/v1/usage-periods/{period_id}/invoice", {}, headers)

    def ingest_usage_event(self, team_id, payload, headers):
        return self._request("POST", f"/v1/teams/{team_id}/usage-events", payload, headers)

    def list_period_usage_events(self, period_id, headers, params=None):
        return self._request("GET", f"/v1/usage-periods/{period_id}/usage-events", headers=headers, params=params)

    def list_usage_events(self, headers, params=None):
        return self._request("GET", "/v1/usage-events", headers=headers, params=params)

    def get_usage_event(self, event_id, headers):
        return self._request("GET", f"/v1/usage-events/{event_id}", headers=headers)

    # --- Alert rules ---
    def create_alert_rule(self, team_id, payload, headers):
        return self._request("POST", f"/v1/teams/{team_id}/alert-rules", payload, headers)

    def list_team_alert_rules(self, team_id, headers, params=None):
        return self._request("GET", f"/v1/teams/{team_id}/alert-rules", headers=headers, params=params)

    def list_alert_rules(self, headers, params=None):
        return self._request("GET", "/v1/alert-rules", headers=headers, params=params)

    def get_alert_rule(self, rule_id, headers):
        return self._request("GET", f"/v1/alert-rules/{rule_id}", headers=headers)

    def delete_alert_rule(self, rule_id, headers):
        return self._request("DELETE", f"/v1/alert-rules/{rule_id}", headers=headers)

    # --- Spend caps ---
    def create_spend_cap(self, team_id, payload, headers):
        return self._request("POST", f"/v1/teams/{team_id}/spend-caps", payload, headers)

    def list_team_spend_caps(self, team_id, headers, params=None):
        return self._request("GET", f"/v1/teams/{team_id}/spend-caps", headers=headers, params=params)

    def list_spend_caps(self, headers, params=None):
        return self._request("GET", "/v1/spend-caps", headers=headers, params=params)

    def get_spend_cap(self, cap_id, headers):
        return self._request("GET", f"/v1/spend-caps/{cap_id}", headers=headers)

    def update_spend_cap(self, cap_id, payload, headers):
        return self._request("PATCH", f"/v1/spend-caps/{cap_id}", payload, headers)

    def delete_spend_cap(self, cap_id, headers):
        return self._request("DELETE", f"/v1/spend-caps/{cap_id}", headers=headers)

    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/v1/_clock/set_current_utc", payload, headers)

    # --- Usage summary ---
    def get_usage_summary(self, team_id, headers):
        return self._request("GET", f"/v1/teams/{team_id}/usage-summary", headers=headers)


api_client = ApiClient()
