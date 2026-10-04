"""API client: one method per operation the PRD declares (PRD §4).

Only the operations listed in the routing table exist; child resources that
have no single-resource read are observed through their owning environment's
list endpoint or through the response of the mutating call.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Environment ---------------------------------------------------------
    def create_environment(self, payload, headers):
        return self._request("POST", "/platform/environments", payload, headers)

    def get_environment(self, environment_id, headers):
        return self._request("GET", f"/platform/environments/{environment_id}", headers=headers)

    def list_sandboxes(self, environment_id, headers, params=None):
        return self._request("GET", f"/platform/environments/{environment_id}/sandboxes",
                             headers=headers, params=params)

    def list_refresh_jobs_of_environment(self, environment_id, headers, params=None):
        return self._request("GET", f"/platform/environments/{environment_id}/refresh-jobs",
                             headers=headers, params=params)

    def list_package_installations(self, environment_id, headers, params=None):
        return self._request("GET", f"/platform/environments/{environment_id}/package-installations",
                             headers=headers, params=params)

    def list_change_sets_of_environment(self, environment_id, headers, params=None):
        return self._request("GET", f"/platform/environments/{environment_id}/change-sets",
                             headers=headers, params=params)

    def list_governor_limit_requests_of_environment(self, environment_id, headers, params=None):
        return self._request("GET", f"/platform/environments/{environment_id}/governor-limit-requests",
                             headers=headers, params=params)

    def list_storage_ledgers(self, environment_id, headers, params=None):
        return self._request("GET", f"/platform/environments/{environment_id}/storage-ledgers",
                             headers=headers, params=params)

    def list_permissions(self, environment_id, headers, params=None):
        return self._request("GET", f"/platform/environments/{environment_id}/permissions",
                             headers=headers, params=params)

    def list_access_audits_of_environment(self, environment_id, headers, params=None):
        return self._request("GET", f"/platform/environments/{environment_id}/access-audits",
                             headers=headers, params=params)

    def schedule_release(self, environment_id, payload, headers):
        return self._request("POST", f"/platform/environments/{environment_id}/schedule-release",
                             payload, headers)

    def apply_release(self, environment_id, headers, payload=None):
        return self._request("POST", f"/platform/environments/{environment_id}/apply-release",
                             payload or {}, headers)

    def open_release_window(self, environment_id, headers, payload=None):
        return self._request("POST", f"/platform/environments/{environment_id}/open-release-window",
                             payload or {}, headers)

    def install_package(self, environment_id, payload, headers):
        return self._request("POST", f"/platform/environments/{environment_id}/package-installations",
                             payload, headers)

    def grant_permission(self, environment_id, payload, headers):
        return self._request("POST", f"/platform/environments/{environment_id}/permissions",
                             payload, headers)

    def create_storage_ledger(self, environment_id, payload, headers):
        return self._request("POST", f"/platform/environments/{environment_id}/storage-ledgers",
                             payload, headers)

    def archive_storage(self, environment_id, payload, headers):
        return self._request("POST", f"/platform/environments/{environment_id}/storage/archive",
                             payload, headers)

    def create_governor_limit_request(self, environment_id, payload, headers):
        return self._request("POST", f"/platform/environments/{environment_id}/governor-limit-requests",
                             payload, headers)

    # --- RefreshJob ----------------------------------------------------------
    def create_refresh_job(self, payload, headers):
        return self._request("POST", "/platform/refresh-jobs", payload, headers)

    def complete_masking(self, refresh_job_id, headers, payload=None):
        return self._request("POST", f"/platform/refresh-jobs/{refresh_job_id}/complete-masking",
                             payload or {}, headers)

    def complete_refresh(self, refresh_job_id, headers, payload=None):
        return self._request("POST", f"/platform/refresh-jobs/{refresh_job_id}/complete-refresh",
                             payload or {}, headers)

    def fail_refresh_job(self, refresh_job_id, headers, payload=None):
        return self._request("POST", f"/platform/refresh-jobs/{refresh_job_id}/fail",
                             payload or {}, headers)

    # --- PackageVersion ------------------------------------------------------
    def create_package_version(self, payload, headers):
        return self._request("POST", "/platform/package-versions", payload, headers)

    def get_package_version(self, package_version_id, headers):
        return self._request("GET", f"/platform/package-versions/{package_version_id}", headers=headers)

    def list_package_version_installations(self, package_version_id, headers, params=None):
        return self._request("GET", f"/platform/package-versions/{package_version_id}/installations",
                             headers=headers, params=params)

    def list_package_version_successors(self, package_version_id, headers, params=None):
        return self._request("GET", f"/platform/package-versions/{package_version_id}/successors",
                             headers=headers, params=params)

    # --- InstalledPackage ----------------------------------------------------
    def upgrade_installed_package(self, installed_package_id, payload, headers):
        return self._request("POST", f"/platform/installed-packages/{installed_package_id}/upgrade",
                             payload, headers)

    def uninstall_package(self, installed_package_id, headers, payload=None):
        return self._request("POST", f"/platform/installed-packages/{installed_package_id}/uninstall",
                             payload or {}, headers)

    # --- MetadataChangeSet ---------------------------------------------------
    def create_change_set(self, payload, headers):
        return self._request("POST", "/platform/change-sets", payload, headers)

    def get_change_set(self, change_set_id, headers):
        return self._request("GET", f"/platform/change-sets/{change_set_id}", headers=headers)

    def edit_change_set(self, change_set_id, payload, headers):
        return self._request("PATCH", f"/platform/change-sets/{change_set_id}", payload, headers)

    def validate_change_set(self, change_set_id, headers, payload=None):
        return self._request("POST", f"/platform/change-sets/{change_set_id}/validate",
                             payload or {}, headers)

    def approve_change_set(self, change_set_id, headers, payload=None):
        return self._request("POST", f"/platform/change-sets/{change_set_id}/approve",
                             payload or {}, headers)

    def reopen_change_set(self, change_set_id, headers, payload=None):
        return self._request("POST", f"/platform/change-sets/{change_set_id}/reopen",
                             payload or {}, headers)

    def deploy_change_set(self, change_set_id, payload, headers):
        return self._request("POST", f"/platform/change-sets/{change_set_id}/deploy", payload, headers)

    def list_change_set_deployments(self, change_set_id, headers, params=None):
        return self._request("GET", f"/platform/change-sets/{change_set_id}/deployments",
                             headers=headers, params=params)

    # --- DeploymentJob -------------------------------------------------------
    def complete_deployment_job(self, deployment_job_id, headers, payload=None):
        return self._request("POST", f"/platform/deployment-jobs/{deployment_job_id}/complete",
                             payload or {}, headers)

    def fail_deployment_job(self, deployment_job_id, headers, payload=None):
        return self._request("POST", f"/platform/deployment-jobs/{deployment_job_id}/fail",
                             payload or {}, headers)

    # --- GovernorLimitRequest ------------------------------------------------
    def submit_governor_request(self, governor_request_id, headers, payload=None):
        return self._request("POST", f"/platform/governor-limit-requests/{governor_request_id}/submit",
                             payload or {}, headers)

    def approve_governor_request(self, governor_request_id, headers, payload=None):
        return self._request("POST", f"/platform/governor-limit-requests/{governor_request_id}/approve",
                             payload or {}, headers)

    def reject_governor_request(self, governor_request_id, headers, payload=None):
        return self._request("POST", f"/platform/governor-limit-requests/{governor_request_id}/reject",
                             payload or {}, headers)

    def reopen_governor_request(self, governor_request_id, headers, payload=None):
        return self._request("POST", f"/platform/governor-limit-requests/{governor_request_id}/reopen",
                             payload or {}, headers)

    # --- StorageLedger -------------------------------------------------------
    def restore_storage_ledger(self, storage_ledger_id, headers, payload=None):
        return self._request("POST", f"/platform/storage-ledgers/{storage_ledger_id}/restore",
                             payload or {}, headers)

    # --- AccessAudit ---------------------------------------------------------
    def create_access_audit(self, payload, headers):
        return self._request("POST", "/platform/access-audits", payload, headers)

    def close_access_audit(self, audit_id, payload, headers):
        return self._request("POST", f"/platform/access-audits/{audit_id}/close", payload, headers)

    # --- Test-driving --------------------------------------------------------
    def set_current_utc(self, current_utc, headers):
        return self._request("POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers)


api_client = ApiClient()