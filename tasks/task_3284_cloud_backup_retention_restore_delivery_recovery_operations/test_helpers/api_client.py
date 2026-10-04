"""API client: one method per endpoint defined in the PRD."""
from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient

from .settings import API_PREFIX


class ApiClient(GenericApiClient):
    """Typed wrappers around every endpoint the PRD exposes."""

    # --- Logical clock ------------------------------------------------------
    def set_clock(self, current_utc, headers):
        return self._request(
            "POST", f"{API_PREFIX}/_clock/set_current_utc",
            {"current_utc": current_utc}, headers,
        )

    # --- Accounts -----------------------------------------------------------
    def create_account(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/accounts", payload, headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/accounts", params, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"{API_PREFIX}/accounts/{account_id}", headers=headers)

    def reinstate_account(self, account_id, headers):
        return self._request(
            "POST", f"{API_PREFIX}/accounts/{account_id}/reinstate", {}, headers)

    def close_account(self, account_id, headers):
        return self._request("POST", f"{API_PREFIX}/accounts/{account_id}/close", {}, headers)

    # --- Backup groups ------------------------------------------------------
    def create_backup_group(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/backup-groups", payload, headers)

    def list_backup_groups(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/backup-groups", params, headers)

    def get_backup_group(self, group_id, headers):
        return self._request("GET", f"{API_PREFIX}/backup-groups/{group_id}", headers=headers)

    def suspend_backup_group(self, group_id, headers):
        return self._request("POST", f"{API_PREFIX}/backup-groups/{group_id}/suspend", {}, headers)

    def resume_backup_group(self, group_id, headers):
        return self._request("POST", f"{API_PREFIX}/backup-groups/{group_id}/resume", {}, headers)

    # --- Group policies -----------------------------------------------------
    def create_group_policy(self, group_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/backup-groups/{group_id}/policies", payload, headers)

    def list_group_policies(self, group_id, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/backup-groups/{group_id}/policies", params, headers)

    def get_group_policy(self, policy_id, headers):
        return self._request("GET", f"{API_PREFIX}/group-policies/{policy_id}", headers=headers)

    # --- Agents -------------------------------------------------------------
    def create_agent(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/agents", payload, headers)

    def list_agents(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/agents", params, headers)

    def get_agent(self, agent_id, headers):
        return self._request("GET", f"{API_PREFIX}/agents/{agent_id}", headers=headers)

    def activate_agent(self, agent_id, headers):
        return self._request("POST", f"{API_PREFIX}/agents/{agent_id}/activate", {}, headers)

    def retire_agent(self, agent_id, headers):
        return self._request("POST", f"{API_PREFIX}/agents/{agent_id}/retire", {}, headers)

    def block_agent(self, agent_id, headers):
        return self._request("POST", f"{API_PREFIX}/agents/{agent_id}/block", {}, headers)

    def unblock_agent(self, agent_id, headers):
        return self._request("POST", f"{API_PREFIX}/agents/{agent_id}/unblock", {}, headers)

    # --- Backup sets and file versions --------------------------------------
    def create_backup_set(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/backup-sets", payload, headers)

    def list_backup_sets(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/backup-sets", params, headers)

    def get_backup_set(self, set_id, headers):
        return self._request("GET", f"{API_PREFIX}/backup-sets/{set_id}", headers=headers)

    def create_file_version(self, set_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/backup-sets/{set_id}/file-versions", payload, headers)

    def list_file_versions(self, set_id, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/backup-sets/{set_id}/file-versions", params, headers)

    def get_file_version(self, file_version_id, headers):
        return self._request("GET", f"{API_PREFIX}/file-versions/{file_version_id}", headers=headers)

    def complete_initial_backup(self, set_id, headers):
        return self._request(
            "POST", f"{API_PREFIX}/backup-sets/{set_id}/complete-initial", {}, headers)

    def suspend_backup_set(self, set_id, headers):
        return self._request("POST", f"{API_PREFIX}/backup-sets/{set_id}/suspend", {}, headers)

    def delete_backup_set(self, set_id, headers):
        return self._request("POST", f"{API_PREFIX}/backup-sets/{set_id}/delete", {}, headers)

    # --- Restore requests ---------------------------------------------------
    def create_restore_request(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/restore-requests", payload, headers)

    def list_restore_requests(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/restore-requests", params, headers)

    def get_restore_request(self, restore_id, headers):
        return self._request("GET", f"{API_PREFIX}/restore-requests/{restore_id}", headers=headers)

    def validate_restore_request(self, restore_id, headers, payload=None):
        return self._request(
            "POST", f"{API_PREFIX}/restore-requests/{restore_id}/validate", payload or {}, headers)

    def return_restore_to_draft(self, restore_id, headers):
        return self._request(
            "POST", f"{API_PREFIX}/restore-requests/{restore_id}/return-to-draft", {}, headers)

    def begin_restore(self, restore_id, headers):
        return self._request(
            "POST", f"{API_PREFIX}/restore-requests/{restore_id}/begin", {}, headers)

    def prepare_restore(self, restore_id, headers):
        return self._request(
            "POST", f"{API_PREFIX}/restore-requests/{restore_id}/prepare", {}, headers)

    def complete_restore(self, restore_id, headers):
        return self._request(
            "POST", f"{API_PREFIX}/restore-requests/{restore_id}/complete", {}, headers)

    def fail_restore(self, restore_id, headers):
        return self._request(
            "POST", f"{API_PREFIX}/restore-requests/{restore_id}/fail", {}, headers)

    def cancel_restore(self, restore_id, headers):
        return self._request(
            "POST", f"{API_PREFIX}/restore-requests/{restore_id}/cancel", {}, headers)

    def reverse_restore(self, restore_id, headers):
        return self._request(
            "POST", f"{API_PREFIX}/restore-requests/{restore_id}/reverse", {}, headers)

    # --- Drive shipments ----------------------------------------------------
    def list_drive_shipments(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/drive-shipments", params, headers)

    def get_drive_shipment(self, shipment_id, headers):
        return self._request("GET", f"{API_PREFIX}/drive-shipments/{shipment_id}", headers=headers)

    def ship_drive_shipment(self, shipment_id, headers):
        return self._request(
            "POST", f"{API_PREFIX}/drive-shipments/{shipment_id}/ship", {}, headers)

    def deliver_drive_shipment(self, shipment_id, headers):
        return self._request(
            "POST", f"{API_PREFIX}/drive-shipments/{shipment_id}/deliver", {}, headers)

    def open_return_window(self, shipment_id, headers):
        return self._request(
            "POST", f"{API_PREFIX}/drive-shipments/{shipment_id}/open-return-window", {}, headers)

    def receive_return(self, shipment_id, headers):
        return self._request(
            "POST", f"{API_PREFIX}/drive-shipments/{shipment_id}/receive-return", {}, headers)

    def mark_shipment_delinquent(self, shipment_id, headers):
        return self._request(
            "POST", f"{API_PREFIX}/drive-shipments/{shipment_id}/mark-delinquent", {}, headers)

    def close_drive_shipment(self, shipment_id, headers):
        return self._request(
            "POST", f"{API_PREFIX}/drive-shipments/{shipment_id}/close", {}, headers)

    # --- Billing periods ----------------------------------------------------
    def create_billing_period(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/billing-periods", payload, headers)

    def list_billing_periods(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/billing-periods", params, headers)

    def get_billing_period(self, period_id, headers):
        return self._request("GET", f"{API_PREFIX}/billing-periods/{period_id}", headers=headers)

    def close_billing_period(self, period_id, headers):
        return self._request(
            "POST", f"{API_PREFIX}/billing-periods/{period_id}/close", {}, headers)

    # --- Retention change requests ------------------------------------------
    def create_retention_change_request(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/retention-change-requests", payload, headers)

    def list_retention_change_requests(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/retention-change-requests", params, headers)

    def get_retention_change_request(self, request_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/retention-change-requests/{request_id}", headers=headers)

    def begin_cooling_off(self, request_id, headers):
        return self._request(
            "POST", f"{API_PREFIX}/retention-change-requests/{request_id}/begin-cooling-off",
            {}, headers)

    def apply_retention_change(self, request_id, headers):
        return self._request(
            "POST", f"{API_PREFIX}/retention-change-requests/{request_id}/apply", {}, headers)

    def reject_retention_change(self, request_id, headers):
        return self._request(
            "POST", f"{API_PREFIX}/retention-change-requests/{request_id}/reject", {}, headers)

    def resubmit_retention_change(self, request_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/retention-change-requests/{request_id}/resubmit",
            payload, headers)

    def expire_retention_change(self, request_id, headers):
        return self._request(
            "POST", f"{API_PREFIX}/retention-change-requests/{request_id}/expire", {}, headers)

    # --- Data deletion requests ---------------------------------------------
    def create_data_deletion_request(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/data-deletion-requests", payload, headers)

    def list_data_deletion_requests(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/data-deletion-requests", params, headers)

    def get_data_deletion_request(self, request_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/data-deletion-requests/{request_id}", headers=headers)

    def approve_data_deletion_request(self, request_id, headers):
        return self._request(
            "POST", f"{API_PREFIX}/data-deletion-requests/{request_id}/approve", {}, headers)

    def reject_data_deletion_request(self, request_id, headers):
        return self._request(
            "POST", f"{API_PREFIX}/data-deletion-requests/{request_id}/reject", {}, headers)

    def execute_data_deletion_request(self, request_id, headers):
        return self._request(
            "POST", f"{API_PREFIX}/data-deletion-requests/{request_id}/execute", {}, headers)

    def complete_data_deletion_request(self, request_id, headers):
        return self._request(
            "POST", f"{API_PREFIX}/data-deletion-requests/{request_id}/complete", {}, headers)

    # --- Storage pods -------------------------------------------------------
    def create_storage_pod(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/storage-pods", payload, headers)

    def list_storage_pods(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/storage-pods", params, headers)

    def get_storage_pod(self, pod_id, headers):
        return self._request("GET", f"{API_PREFIX}/storage-pods/{pod_id}", headers=headers)

    def fail_storage_pod_shards(self, pod_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/storage-pods/{pod_id}/shards/fail", payload, headers)

    def restore_storage_pod_shards(self, pod_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/storage-pods/{pod_id}/shards/restore", payload, headers)

    def begin_pod_repair(self, pod_id, headers):
        return self._request(
            "POST", f"{API_PREFIX}/storage-pods/{pod_id}/begin-repair", {}, headers)

    def complete_pod_repair(self, pod_id, headers):
        return self._request(
            "POST", f"{API_PREFIX}/storage-pods/{pod_id}/complete-repair", {}, headers)


api_client = ApiClient()