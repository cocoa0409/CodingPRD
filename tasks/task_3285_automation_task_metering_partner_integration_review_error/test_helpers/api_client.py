"""API client: one method per endpoint defined in the PRD (paths under /zapier)."""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/zapier"


class ApiClient(GenericApiClient):
    # ── Clock ─────────────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc", payload, headers)

    # ── Accounts ──────────────────────────────────────────
    def create_account(self, payload, headers):
        return self._request("POST", f"{PREFIX}/accounts", payload, headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/accounts", headers=headers, params=params)

    def get_account(self, account_id, headers):
        return self._request("GET", f"{PREFIX}/accounts/{account_id}", headers=headers)

    def get_account_usage(self, account_id, headers):
        return self._request("GET", f"{PREFIX}/accounts/{account_id}/usage", headers=headers)

    def create_lapse_incident(self, account_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/accounts/{account_id}/lapse-incidents", payload, headers
        )

    # ── Simulation / injection ────────────────────────────
    def simulate_action_charge(self, payload, headers):
        return self._request("POST", f"{PREFIX}/_simulate/action-charge", payload, headers)

    def expire_token(self, payload, headers):
        return self._request("POST", f"{PREFIX}/_lapse/tokens/expire", payload, headers)

    def downstream_recover(self, payload, headers):
        return self._request("POST", f"{PREFIX}/_simulate/downstream-recover", payload, headers)

    # ── Members ───────────────────────────────────────────
    def register_member(self, payload, headers):
        return self._request("POST", f"{PREFIX}/members/register", payload, headers)

    def list_members(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/members", headers=headers, params=params)

    def get_member(self, member_id, headers):
        return self._request("GET", f"{PREFIX}/members/{member_id}", headers=headers)

    def list_member_grants(self, member_id, headers):
        return self._request("GET", f"{PREFIX}/members/{member_id}/grants", headers=headers)

    # ── Folders & grants ──────────────────────────────────
    def create_folder(self, payload, headers):
        return self._request("POST", f"{PREFIX}/folders", payload, headers)

    def list_folders(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/folders", headers=headers, params=params)

    def get_folder(self, folder_id, headers):
        return self._request("GET", f"{PREFIX}/folders/{folder_id}", headers=headers)

    def create_folder_grant(self, folder_id, payload, headers):
        return self._request("POST", f"{PREFIX}/folders/{folder_id}/grants", payload, headers)

    def list_folder_grants(self, folder_id, headers):
        return self._request("GET", f"{PREFIX}/folders/{folder_id}/grants", headers=headers)

    def list_folder_grants_all(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/folder-grants", headers=headers, params=params)

    def get_folder_grant(self, grant_id, headers):
        return self._request("GET", f"{PREFIX}/folder-grants/{grant_id}", headers=headers)

    def list_folder_folder_grants(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/folder-folder-grants", headers=headers, params=params
        )

    def get_folder_folder_grant(self, join_id, headers):
        return self._request("GET", f"{PREFIX}/folder-folder-grants/{join_id}", headers=headers)

    # ── Workflows ─────────────────────────────────────────
    def create_workflow(self, payload, headers):
        return self._request("POST", f"{PREFIX}/workflows", payload, headers)

    def list_workflows(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/workflows", headers=headers, params=params)

    def get_workflow(self, workflow_id, headers):
        return self._request("GET", f"{PREFIX}/workflows/{workflow_id}", headers=headers)

    def create_action(self, workflow_id, payload, headers):
        return self._request("POST", f"{PREFIX}/workflows/{workflow_id}/actions", payload, headers)

    def list_workflow_actions(self, workflow_id, headers):
        return self._request("GET", f"{PREFIX}/workflows/{workflow_id}/actions", headers=headers)

    def list_actions(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/actions", headers=headers, params=params)

    def get_action(self, action_id, headers):
        return self._request("GET", f"{PREFIX}/actions/{action_id}", headers=headers)

    def activate_workflow(self, workflow_id, headers):
        return self._request("POST", f"{PREFIX}/workflows/{workflow_id}/activate", headers=headers)

    def pause_workflow(self, workflow_id, headers):
        return self._request("POST", f"{PREFIX}/workflows/{workflow_id}/pause", headers=headers)

    def resume_workflow(self, workflow_id, headers):
        return self._request("POST", f"{PREFIX}/workflows/{workflow_id}/resume", headers=headers)

    def disable_workflow(self, workflow_id, headers):
        return self._request("POST", f"{PREFIX}/workflows/{workflow_id}/disable", headers=headers)

    def dispatch_run(self, workflow_id, payload, headers):
        return self._request("POST", f"{PREFIX}/workflows/{workflow_id}/runs", payload, headers)

    def list_workflow_versions(self, workflow_id, headers):
        return self._request("GET", f"{PREFIX}/workflows/{workflow_id}/versions", headers=headers)

    def migrate_workflow_version(self, workflow_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/workflows/{workflow_id}/migrate-version", payload, headers
        )

    # ── Workflow version snapshots ────────────────────────
    def create_workflow_version(self, payload, headers):
        return self._request("POST", f"{PREFIX}/workflow-versions", payload, headers)

    def list_workflow_versions_all(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/workflow-versions", headers=headers, params=params)

    def get_workflow_version(self, version_id, headers):
        return self._request("GET", f"{PREFIX}/workflow-versions/{version_id}", headers=headers)

    # ── Runs ──────────────────────────────────────────────
    def list_workflow_runs(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/workflow-runs", headers=headers, params=params)

    def get_workflow_run(self, run_id, headers):
        return self._request("GET", f"{PREFIX}/workflow-runs/{run_id}", headers=headers)

    # ── Actions: replay & events ──────────────────────────
    def replay_action(self, action_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/actions/{action_id}/replay", payload, headers)

    def list_action_events(self, action_id, headers):
        return self._request("GET", f"{PREFIX}/actions/{action_id}/events", headers=headers)

    # ── Job events ────────────────────────────────────────
    def list_job_events(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/job-events", headers=headers, params=params)

    def get_job_event(self, event_id, headers):
        return self._request("GET", f"{PREFIX}/job-events/{event_id}", headers=headers)

    # ── Connections ───────────────────────────────────────
    def create_connection(self, payload, headers):
        return self._request("POST", f"{PREFIX}/connections", payload, headers)

    def list_connections(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/connections", headers=headers, params=params)

    def get_connection(self, connection_id, headers):
        return self._request("GET", f"{PREFIX}/connections/{connection_id}", headers=headers)

    def refresh_connection(self, connection_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/connections/{connection_id}/refresh", payload, headers
        )

    def reauthorize_connection(self, connection_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/connections/{connection_id}/reauthorize", payload, headers
        )

    def disconnect_connection(self, connection_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/connections/{connection_id}/disconnect", payload, headers
        )

    # ── Refund grants ─────────────────────────────────────
    def list_refund_grants(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/refund-grants", headers=headers, params=params)

    def get_refund_grant(self, grant_id, headers):
        return self._request("GET", f"{PREFIX}/refund-grants/{grant_id}", headers=headers)

    # ── Integrations ──────────────────────────────────────
    def create_integration(self, payload, headers):
        return self._request("POST", f"{PREFIX}/integrations", payload, headers)

    def list_integrations(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/integrations", headers=headers, params=params)

    def get_integration(self, integration_id, headers):
        return self._request("GET", f"{PREFIX}/integrations/{integration_id}", headers=headers)

    def submit_integration(self, integration_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/integrations/{integration_id}/submit", payload, headers
        )

    def review_decision(self, integration_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/integrations/{integration_id}/review/decision", payload, headers
        )

    def create_integration_endpoint(self, integration_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/integrations/{integration_id}/endpoints", payload, headers
        )

    def list_integration_endpoints(self, integration_id, headers):
        return self._request(
            "GET", f"{PREFIX}/integrations/{integration_id}/endpoints", headers=headers
        )

    def publish_integration_version(self, integration_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/integrations/{integration_id}/versions", payload, headers
        )

    def list_integration_versions(self, integration_id, headers):
        return self._request(
            "GET", f"{PREFIX}/integrations/{integration_id}/versions", headers=headers
        )

    def list_integration_connections(self, integration_id, headers):
        return self._request(
            "GET", f"{PREFIX}/integrations/{integration_id}/connections", headers=headers
        )

    def list_integration_refund_grants(self, integration_id, headers):
        return self._request(
            "GET", f"{PREFIX}/integrations/{integration_id}/refund-grants", headers=headers
        )

    # ── Integration versions & endpoints (collection reads) ─
    def list_integration_versions_all(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/integration-versions", headers=headers, params=params
        )

    def get_integration_version(self, version_id, headers):
        return self._request(
            "GET", f"{PREFIX}/integration-versions/{version_id}", headers=headers
        )

    def list_integration_endpoints_all(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/integration-endpoints", headers=headers, params=params
        )

    def get_integration_endpoint(self, endpoint_id, headers):
        return self._request(
            "GET", f"{PREFIX}/integration-endpoints/{endpoint_id}", headers=headers
        )


api_client = ApiClient()