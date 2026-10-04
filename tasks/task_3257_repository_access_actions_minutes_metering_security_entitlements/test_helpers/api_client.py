"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- logical clock ------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---- enterprises --------------------------------------------------------
    def create_enterprise(self, payload, headers):
        return self._request("POST", "/enterprises", payload, headers)

    def get_enterprise(self, enterprise_id, headers):
        return self._request("GET", f"/enterprises/{enterprise_id}", headers=headers)

    def get_seat_usage(self, enterprise_id, headers, mode=None):
        params = {"mode": mode} if mode is not None else None
        return self._request(
            "GET", f"/enterprises/{enterprise_id}/seat-usage",
            headers=headers, params=params,
        )

    def sso_transition(self, enterprise_id, action, headers):
        return self._request(
            "POST", f"/enterprises/{enterprise_id}/sso/transition",
            {"action": action}, headers,
        )

    def billing_cycle_reset(self, enterprise_id, headers):
        return self._request(
            "POST", f"/enterprises/{enterprise_id}/billing-cycle/reset", {}, headers
        )

    def audit_log_stream_toggle(self, enterprise_id, headers):
        return self._request(
            "POST", f"/enterprises/{enterprise_id}/audit-log-stream/toggle", {}, headers
        )

    def list_audit_log_events(self, enterprise_id, headers, params=None):
        return self._request(
            "GET", f"/enterprises/{enterprise_id}/audit-log-events",
            headers=headers, params=params,
        )

    # ---- organizations ------------------------------------------------------
    def create_organization(self, payload, headers):
        return self._request("POST", "/organizations", payload, headers)

    def get_organization(self, org_id, headers):
        return self._request("GET", f"/organizations/{org_id}", headers=headers)

    def org_transition(self, org_id, action, headers):
        return self._request(
            "POST", f"/organizations/{org_id}/transition", {"action": action}, headers
        )

    # ---- users & commit events ----------------------------------------------
    def create_user(self, payload, headers):
        return self._request("POST", "/users", payload, headers)

    def get_user(self, user_id, headers):
        return self._request("GET", f"/users/{user_id}", headers=headers)

    def user_transition(self, user_id, action, headers):
        return self._request(
            "POST", f"/users/{user_id}/transition", {"action": action}, headers
        )

    def create_commit_event(self, payload, headers):
        return self._request("POST", "/commit-events", payload, headers)

    # ---- teams & memberships --------------------------------------------------
    def create_team(self, payload, headers):
        return self._request("POST", "/teams", payload, headers)

    def list_teams(self, org_id, headers, params=None):
        return self._request(
            "GET", f"/organizations/{org_id}/teams", headers=headers, params=params
        )

    def create_membership(self, team_id, payload, headers):
        return self._request(
            "POST", f"/teams/{team_id}/memberships", payload, headers
        )

    # ---- repositories ---------------------------------------------------------
    def create_repository(self, payload, headers):
        return self._request("POST", "/repositories", payload, headers)

    def get_repository(self, repo_id, headers):
        return self._request("GET", f"/repositories/{repo_id}", headers=headers)

    def update_repository(self, repo_id, payload, headers):
        return self._request("PATCH", f"/repositories/{repo_id}", payload, headers)

    # ---- outside collaborators --------------------------------------------------
    def create_outside_collaborator(self, org_id, payload, headers):
        return self._request(
            "POST", f"/organizations/{org_id}/outside-collaborators", payload, headers
        )

    def accept_outside_collaborator(self, collab_id, headers):
        return self._request(
            "POST", f"/outside-collaborators/{collab_id}/accept", {}, headers
        )

    def delete_outside_collaborator(self, collab_id, headers):
        return self._request(
            "DELETE", f"/outside-collaborators/{collab_id}", headers=headers
        )

    # ---- self-hosted runners ------------------------------------------------
    def create_runner(self, org_id, payload, headers):
        return self._request(
            "POST", f"/organizations/{org_id}/runners", payload, headers
        )

    def runner_heartbeat(self, runner_id, headers):
        return self._request(
            "POST", f"/runners/{runner_id}/heartbeat", {}, headers
        )

    def delete_runner(self, runner_id, headers):
        return self._request("DELETE", f"/runners/{runner_id}", headers=headers)

    # ---- workflow runs ------------------------------------------------------
    def create_workflow_run(self, repo_id, payload, headers):
        return self._request(
            "POST", f"/repositories/{repo_id}/workflow-runs", payload, headers
        )

    def list_workflow_runs(self, repo_id, headers, params=None):
        return self._request(
            "GET", f"/repositories/{repo_id}/workflow-runs",
            headers=headers, params=params,
        )

    def workflow_run_transition(self, run_id, action, headers):
        return self._request(
            "POST", f"/workflow-runs/{run_id}/transition", {"action": action}, headers
        )

    # ---- storage artifacts --------------------------------------------------
    def create_artifact(self, repo_id, payload, headers):
        return self._request(
            "POST", f"/repositories/{repo_id}/artifacts", payload, headers
        )

    def list_artifacts(self, repo_id, headers, params=None):
        return self._request(
            "GET", f"/repositories/{repo_id}/artifacts",
            headers=headers, params=params,
        )

    def delete_artifact(self, artifact_id, headers):
        return self._request("DELETE", f"/artifacts/{artifact_id}", headers=headers)

    # ---- security entitlements ----------------------------------------------
    def create_security_entitlement(self, org_id, payload, headers):
        return self._request(
            "POST", f"/organizations/{org_id}/security-entitlements", payload, headers
        )

    def entitlement_transition(self, entitlement_id, action, headers):
        return self._request(
            "POST", f"/security-entitlements/{entitlement_id}/transition",
            {"action": action}, headers,
        )

    # ---- personal access tokens ---------------------------------------------
    def create_personal_access_token(self, user_id, payload, headers):
        return self._request(
            "POST", f"/users/{user_id}/personal-access-tokens", payload, headers
        )

    def list_personal_access_tokens(self, user_id, headers, params=None):
        return self._request(
            "GET", f"/users/{user_id}/personal-access-tokens",
            headers=headers, params=params,
        )

    def token_transition(self, token_id, action, headers):
        return self._request(
            "POST", f"/personal-access-tokens/{token_id}/transition",
            {"action": action}, headers,
        )

    # ---- marketplace app installations --------------------------------------
    def create_app_installation(self, org_id, payload, headers):
        return self._request(
            "POST", f"/organizations/{org_id}/app-installations", payload, headers
        )

    def app_installation_transition(self, installation_id, action, headers):
        return self._request(
            "POST", f"/app-installations/{installation_id}/transition",
            {"action": action}, headers,
        )


api_client = ApiClient()
