"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- tenants ---
    def create_tenant(self, payload, headers):
        return self._request("POST", "/tenants", payload, headers)

    def list_tenants(self, headers, params=None):
        return self._request("GET", "/tenants", headers=headers, params=params)

    def get_tenant(self, tenant_id, headers):
        return self._request("GET", f"/tenants/{tenant_id}", headers=headers)

    def update_tenant(self, tenant_id, payload, headers):
        return self._request("PUT", f"/tenants/{tenant_id}", payload, headers)

    def suspend_tenant(self, tenant_id, headers):
        return self._request("POST", f"/tenants/{tenant_id}/suspend", {}, headers)

    def resume_tenant(self, tenant_id, headers):
        return self._request("POST", f"/tenants/{tenant_id}/resume", {}, headers)

    def retire_tenant(self, tenant_id, headers):
        return self._request("POST", f"/tenants/{tenant_id}/retire", {}, headers)

    def acknowledge_weekly_update(self, tenant_id, headers):
        return self._request(
            "POST", f"/tenants/{tenant_id}/acknowledge-weekly-update", {}, headers
        )

    def handoff_advance(self, tenant_id, headers):
        return self._request("POST", f"/tenants/{tenant_id}/handoff/advance", {}, headers)

    def get_adoption_health(self, tenant_id, headers):
        return self._request("GET", f"/tenants/{tenant_id}/adoption-health", headers=headers)

    # --- organization units ---
    def create_org_unit(self, tid, payload, headers):
        return self._request("POST", f"/tenants/{tid}/organization-units", payload, headers)

    def list_org_units(self, tid, headers, params=None):
        return self._request("GET", f"/tenants/{tid}/organization-units", headers=headers, params=params)

    def get_org_unit(self, tid, unit_id, headers):
        return self._request("GET", f"/tenants/{tid}/organization-units/{unit_id}", headers=headers)

    def deactivate_org_unit(self, tid, unit_id, headers):
        return self._request(
            "POST", f"/tenants/{tid}/organization-units/{unit_id}/deactivate", {}, headers
        )

    # --- workers ---
    def create_worker(self, tid, payload, headers):
        return self._request("POST", f"/tenants/{tid}/workers", payload, headers)

    def list_workers(self, tid, headers, params=None):
        return self._request("GET", f"/tenants/{tid}/workers", headers=headers, params=params)

    def get_worker(self, tid, worker_id, headers):
        return self._request("GET", f"/tenants/{tid}/workers/{worker_id}", headers=headers)

    def terminate_worker(self, tid, worker_id, headers):
        return self._request("POST", f"/tenants/{tid}/workers/{worker_id}/terminate", {}, headers)

    # --- security groups & memberships ---
    def create_security_group(self, tid, payload, headers):
        return self._request("POST", f"/tenants/{tid}/security-groups", payload, headers)

    def list_security_groups(self, tid, headers, params=None):
        return self._request("GET", f"/tenants/{tid}/security-groups", headers=headers, params=params)

    def get_security_group(self, tid, group_id, headers):
        return self._request("GET", f"/tenants/{tid}/security-groups/{group_id}", headers=headers)

    def disable_security_group(self, tid, group_id, headers):
        return self._request(
            "POST", f"/tenants/{tid}/security-groups/{group_id}/disable", {}, headers
        )

    def create_membership(self, tid, gid, payload, headers):
        return self._request(
            "POST", f"/tenants/{tid}/security-groups/{gid}/memberships", payload, headers
        )

    def list_memberships(self, tid, gid, headers, params=None):
        return self._request(
            "GET", f"/tenants/{tid}/security-groups/{gid}/memberships", headers=headers, params=params
        )

    def delete_membership(self, tid, gid, membership_id, headers):
        return self._request(
            "DELETE", f"/tenants/{tid}/security-groups/{gid}/memberships/{membership_id}", headers=headers
        )

    def get_membership_flat(self, membership_id, headers):
        return self._request("GET", f"/security-group-memberships/{membership_id}", headers=headers)

    # --- business process definitions & steps ---
    def create_definition(self, tid, payload, headers):
        return self._request("POST", f"/tenants/{tid}/business-process-definitions", payload, headers)

    def list_definitions(self, tid, headers, params=None):
        return self._request(
            "GET", f"/tenants/{tid}/business-process-definitions", headers=headers, params=params
        )

    def get_definition(self, tid, definition_id, headers):
        return self._request(
            "GET", f"/tenants/{tid}/business-process-definitions/{definition_id}", headers=headers
        )

    def create_step(self, tid, definition_id, payload, headers):
        return self._request(
            "POST", f"/tenants/{tid}/business-process-definitions/{definition_id}/steps", payload, headers
        )

    def list_steps(self, tid, definition_id, headers, params=None):
        return self._request(
            "GET", f"/tenants/{tid}/business-process-definitions/{definition_id}/steps",
            headers=headers, params=params,
        )

    def activate_definition(self, tid, definition_id, payload, headers):
        return self._request(
            "POST", f"/tenants/{tid}/business-process-definitions/{definition_id}/activate",
            payload, headers,
        )

    def retire_definition(self, tid, definition_id, headers):
        return self._request(
            "POST", f"/tenants/{tid}/business-process-definitions/{definition_id}/retire", {}, headers
        )

    # --- transaction instances ---
    def create_transaction(self, tid, payload, headers):
        return self._request("POST", f"/tenants/{tid}/transaction-instances", payload, headers)

    def list_transactions(self, tid, headers, params=None):
        return self._request("GET", f"/tenants/{tid}/transaction-instances", headers=headers, params=params)

    def get_transaction(self, tid, instance_id, headers):
        return self._request("GET", f"/tenants/{tid}/transaction-instances/{instance_id}", headers=headers)

    def preview_chain(self, tid, instance_id, headers):
        return self._request(
            "GET", f"/tenants/{tid}/transaction-instances/{instance_id}/preview-chain", headers=headers
        )

    def list_events(self, tid, instance_id, headers, params=None):
        return self._request(
            "GET", f"/tenants/{tid}/transaction-instances/{instance_id}/events",
            headers=headers, params=params,
        )

    def approve_step(self, tid, instance_id, step_order, payload, headers):
        return self._request(
            "POST",
            f"/tenants/{tid}/transaction-instances/{instance_id}/steps/{step_order}/approve",
            payload, headers,
        )

    def return_step(self, tid, instance_id, step_order, payload, headers):
        return self._request(
            "POST",
            f"/tenants/{tid}/transaction-instances/{instance_id}/steps/{step_order}/return",
            payload, headers,
        )

    def cancel_transaction(self, tid, instance_id, headers):
        return self._request(
            "POST", f"/tenants/{tid}/transaction-instances/{instance_id}/cancel", {}, headers
        )

    # --- release trains & feature adoption ---
    def create_release_train(self, payload, headers):
        return self._request("POST", "/release-trains", payload, headers)

    def list_release_trains(self, headers, params=None):
        return self._request("GET", "/release-trains", headers=headers, params=params)

    def get_release_train(self, train_id, headers):
        return self._request("GET", f"/release-trains/{train_id}", headers=headers)

    def retire_release_train(self, train_id, headers):
        return self._request("POST", f"/release-trains/{train_id}/retire", {}, headers)

    def create_feature_adoption(self, tid, payload, headers):
        return self._request("POST", f"/tenants/{tid}/feature-adoptions", payload, headers)

    def list_feature_adoptions(self, tid, headers, params=None):
        return self._request("GET", f"/tenants/{tid}/feature-adoptions", headers=headers, params=params)

    def get_feature_adoption(self, tid, adoption_id, headers):
        return self._request("GET", f"/tenants/{tid}/feature-adoptions/{adoption_id}", headers=headers)

    def record_testing(self, tid, adoption_id, payload, headers):
        return self._request(
            "POST", f"/tenants/{tid}/feature-adoptions/{adoption_id}/record-testing", payload, headers
        )

    def adopt_feature(self, tid, adoption_id, headers):
        return self._request("POST", f"/tenants/{tid}/feature-adoptions/{adoption_id}/adopt", {}, headers)

    def defer_feature(self, tid, adoption_id, headers):
        return self._request("POST", f"/tenants/{tid}/feature-adoptions/{adoption_id}/defer", {}, headers)

    # --- integration connectors & runs ---
    def create_connector(self, tid, payload, headers):
        return self._request("POST", f"/tenants/{tid}/integration-connectors", payload, headers)

    def list_connectors(self, tid, headers, params=None):
        return self._request("GET", f"/tenants/{tid}/integration-connectors", headers=headers, params=params)

    def get_connector(self, tid, connector_id, headers):
        return self._request("GET", f"/tenants/{tid}/integration-connectors/{connector_id}", headers=headers)

    def activate_connector(self, tid, connector_id, headers):
        return self._request(
            "POST", f"/tenants/{tid}/integration-connectors/{connector_id}/activate", {}, headers
        )

    def suspend_connector(self, tid, connector_id, headers):
        return self._request(
            "POST", f"/tenants/{tid}/integration-connectors/{connector_id}/suspend", {}, headers
        )

    def resume_connector(self, tid, connector_id, headers):
        return self._request(
            "POST", f"/tenants/{tid}/integration-connectors/{connector_id}/resume", {}, headers
        )

    def retire_connector(self, tid, connector_id, headers):
        return self._request(
            "POST", f"/tenants/{tid}/integration-connectors/{connector_id}/retire", {}, headers
        )

    def create_run(self, tid, cid, payload, headers):
        return self._request(
            "POST", f"/tenants/{tid}/integration-connectors/{cid}/runs", payload, headers
        )

    def list_runs(self, tid, cid, headers, params=None):
        return self._request(
            "GET", f"/tenants/{tid}/integration-connectors/{cid}/runs", headers=headers, params=params
        )

    def get_run_flat(self, run_id, headers):
        return self._request("GET", f"/integration-runs/{run_id}", headers=headers)

    def complete_run(self, tid, cid, run_id, payload, headers):
        return self._request(
            "POST", f"/tenants/{tid}/integration-connectors/{cid}/runs/{run_id}/complete",
            payload, headers,
        )

    def fail_run(self, tid, cid, run_id, headers):
        return self._request(
            "POST", f"/tenants/{tid}/integration-connectors/{cid}/runs/{run_id}/fail", {}, headers
        )

    def retry_run(self, tid, cid, run_id, headers):
        return self._request(
            "POST", f"/tenants/{tid}/integration-connectors/{cid}/runs/{run_id}/retry", {}, headers
        )

    def dead_letter_run(self, tid, cid, run_id, headers):
        return self._request(
            "POST", f"/tenants/{tid}/integration-connectors/{cid}/runs/{run_id}/dead-letter", {}, headers
        )

    # --- tenant refresh ---
    def create_refresh_job(self, tid, payload, headers):
        return self._request("POST", f"/tenants/{tid}/refresh-jobs", payload, headers)

    def list_refresh_jobs(self, tid, headers, params=None):
        return self._request("GET", f"/tenants/{tid}/refresh-jobs", headers=headers, params=params)

    def get_refresh_job(self, tid, job_id, headers):
        return self._request("GET", f"/tenants/{tid}/refresh-jobs/{job_id}", headers=headers)

    def start_refresh_job(self, tid, job_id, headers):
        return self._request("POST", f"/tenants/{tid}/refresh-jobs/{job_id}/start", {}, headers)

    def complete_refresh_job(self, tid, job_id, headers):
        return self._request("POST", f"/tenants/{tid}/refresh-jobs/{job_id}/complete", {}, headers)

    def fail_refresh_job(self, tid, job_id, headers):
        return self._request("POST", f"/tenants/{tid}/refresh-jobs/{job_id}/fail", {}, headers)

    def cancel_refresh_job(self, tid, job_id, headers):
        return self._request("POST", f"/tenants/{tid}/refresh-jobs/{job_id}/cancel", {}, headers)

    # --- notifications ---
    def list_notifications(self, tid, headers, params=None):
        return self._request("GET", f"/tenants/{tid}/notifications", headers=headers, params=params)


api_client = ApiClient()
