"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/api/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    # --- smart accounts ---
    def create_smart_account(self, payload, headers):
        return self._request("POST", "/api/smart-accounts", payload, headers)

    def list_smart_accounts(self, headers, params=None):
        return self._request("GET", "/api/smart-accounts", headers=headers, params=params)

    def get_smart_account(self, account_id, headers):
        return self._request("GET", f"/api/smart-accounts/{account_id}", headers=headers)

    def suspend_smart_account(self, account_id, headers):
        return self._request("POST", f"/api/smart-accounts/{account_id}/suspend", headers=headers)

    def reactivate_smart_account(self, account_id, headers):
        return self._request("POST", f"/api/smart-accounts/{account_id}/reactivate", headers=headers)

    def close_smart_account(self, account_id, headers):
        return self._request("POST", f"/api/smart-accounts/{account_id}/close", headers=headers)

    def list_virtual_accounts_of_account(self, account_id, headers, params=None):
        return self._request("GET", f"/api/smart-accounts/{account_id}/virtual-accounts", headers=headers, params=params)

    def list_service_contracts_of_account(self, account_id, headers, params=None):
        return self._request("GET", f"/api/smart-accounts/{account_id}/service-contracts", headers=headers, params=params)

    # --- partner orgs & delegations ---
    def create_partner_org(self, payload, headers):
        return self._request("POST", "/api/partner-orgs", payload, headers)

    def get_partner_org(self, partner_org_id, headers):
        return self._request("GET", f"/api/partner-orgs/{partner_org_id}", headers=headers)

    def list_delegations_of_partner(self, partner_org_id, headers, params=None):
        return self._request("GET", f"/api/partner-orgs/{partner_org_id}/delegations", headers=headers, params=params)

    def create_partner_delegation(self, payload, headers):
        return self._request("POST", "/api/partner-delegations", payload, headers)

    def list_partner_delegations(self, headers, params=None):
        return self._request("GET", "/api/partner-delegations", headers=headers, params=params)

    def get_partner_delegation(self, delegation_id, headers):
        return self._request("GET", f"/api/partner-delegations/{delegation_id}", headers=headers)

    def revoke_partner_delegation(self, delegation_id, headers):
        return self._request("POST", f"/api/partner-delegations/{delegation_id}/revoke", headers=headers)

    # --- virtual accounts ---
    def create_virtual_account(self, payload, headers):
        return self._request("POST", "/api/virtual-accounts", payload, headers)

    def get_virtual_account(self, va_id, headers):
        return self._request("GET", f"/api/virtual-accounts/{va_id}", headers=headers)

    def archive_virtual_account(self, va_id, headers):
        return self._request("POST", f"/api/virtual-accounts/{va_id}/archive", headers=headers)

    def list_license_pools_of_va(self, va_id, headers, params=None):
        return self._request("GET", f"/api/virtual-accounts/{va_id}/license-pools", headers=headers, params=params)

    def list_devices_of_va(self, va_id, headers, params=None):
        return self._request("GET", f"/api/virtual-accounts/{va_id}/devices", headers=headers, params=params)

    # --- license pools ---
    def create_license_pool(self, payload, headers):
        return self._request("POST", "/api/license-pools", payload, headers)

    def get_license_pool(self, pool_id, headers):
        return self._request("GET", f"/api/license-pools/{pool_id}", headers=headers)

    def purchase_adjustment(self, pool_id, payload, headers):
        return self._request("POST", f"/api/license-pools/{pool_id}/purchase-adjustment", payload, headers)

    def tier_upgrade(self, pool_id, payload, headers):
        return self._request("POST", f"/api/license-pools/{pool_id}/tier-upgrade", payload, headers)

    def list_compliance_events(self, pool_id, headers, params=None):
        return self._request("GET", f"/api/license-pools/{pool_id}/compliance-events", headers=headers, params=params)

    def list_assignments_of_pool(self, pool_id, headers, params=None):
        return self._request("GET", f"/api/license-pools/{pool_id}/assignments", headers=headers, params=params)

    # --- devices ---
    def create_device(self, payload, headers):
        return self._request("POST", "/api/devices", payload, headers)

    def get_device(self, device_id, headers):
        return self._request("GET", f"/api/devices/{device_id}", headers=headers)

    def activate_device(self, device_id, headers):
        return self._request("POST", f"/api/devices/{device_id}/activate", headers=headers)

    def deregister_device(self, device_id, headers):
        return self._request("POST", f"/api/devices/{device_id}/deregister", headers=headers)

    def retire_device(self, device_id, headers):
        return self._request("POST", f"/api/devices/{device_id}/retire", headers=headers)

    def list_assignments_of_device(self, device_id, headers, params=None):
        return self._request("GET", f"/api/devices/{device_id}/assignments", headers=headers, params=params)

    def list_usage_reports_of_device(self, device_id, headers, params=None):
        return self._request("GET", f"/api/devices/{device_id}/usage-reports", headers=headers, params=params)

    def list_coverages_of_device(self, device_id, headers, params=None):
        return self._request("GET", f"/api/devices/{device_id}/coverages", headers=headers, params=params)

    def list_rma_cases_of_device(self, device_id, headers, params=None):
        return self._request("GET", f"/api/devices/{device_id}/rma-cases", headers=headers, params=params)

    def submit_usage_report(self, device_id, payload, headers):
        return self._request("POST", f"/api/devices/{device_id}/usage-reports", payload, headers)

    # --- license assignments ---
    def create_license_assignment(self, payload, headers):
        return self._request("POST", "/api/license-assignments", payload, headers)

    def release_license_assignment(self, assignment_id, headers):
        return self._request("POST", f"/api/license-assignments/{assignment_id}/release", headers=headers)

    # --- lifecycle milestones ---
    def create_lifecycle_milestone(self, payload, headers):
        return self._request("POST", "/api/lifecycle-milestones", payload, headers)

    def list_lifecycle_milestones(self, headers, params=None):
        return self._request("GET", "/api/lifecycle-milestones", headers=headers, params=params)

    # --- service contracts ---
    def create_service_contract(self, payload, headers):
        return self._request("POST", "/api/service-contracts", payload, headers)

    def get_service_contract(self, contract_id, headers):
        return self._request("GET", f"/api/service-contracts/{contract_id}", headers=headers)

    def cancel_service_contract(self, contract_id, headers):
        return self._request("POST", f"/api/service-contracts/{contract_id}/cancel", headers=headers)

    def list_coverages_of_contract(self, contract_id, headers, params=None):
        return self._request("GET", f"/api/service-contracts/{contract_id}/coverages", headers=headers, params=params)

    # --- contract coverages ---
    def create_contract_coverage(self, payload, headers):
        return self._request("POST", "/api/contract-coverages", payload, headers)

    def get_contract_coverage(self, coverage_id, headers):
        return self._request("GET", f"/api/contract-coverages/{coverage_id}", headers=headers)

    def list_rma_cases_of_coverage(self, coverage_id, headers, params=None):
        return self._request("GET", f"/api/contract-coverages/{coverage_id}/rma-cases", headers=headers, params=params)

    def release_contract_coverage(self, coverage_id, headers):
        return self._request("POST", f"/api/contract-coverages/{coverage_id}/release", headers=headers)

    # --- RMA cases ---
    def create_rma_case(self, payload, headers):
        return self._request("POST", "/api/rma-cases", payload, headers)

    def get_rma_case(self, rma_id, headers):
        return self._request("GET", f"/api/rma-cases/{rma_id}", headers=headers)

    def ship_replacement(self, rma_id, headers):
        return self._request("POST", f"/api/rma-cases/{rma_id}/ship-replacement", headers=headers)

    def confirm_delivery(self, rma_id, headers):
        return self._request("POST", f"/api/rma-cases/{rma_id}/confirm-delivery", headers=headers)

    def receive_defective(self, rma_id, headers):
        return self._request("POST", f"/api/rma-cases/{rma_id}/receive-defective", headers=headers)

    def close_rma_case(self, rma_id, headers):
        return self._request("POST", f"/api/rma-cases/{rma_id}/close", headers=headers)

    def cancel_rma_case(self, rma_id, headers):
        return self._request("POST", f"/api/rma-cases/{rma_id}/cancel", headers=headers)

    # --- license transfer requests ---
    def create_license_transfer_request(self, payload, headers):
        return self._request("POST", "/api/license-transfer-requests", payload, headers)

    def get_license_transfer_request(self, transfer_id, headers):
        return self._request("GET", f"/api/license-transfer-requests/{transfer_id}", headers=headers)

    def list_license_transfer_requests(self, headers, params=None):
        return self._request("GET", "/api/license-transfer-requests", headers=headers, params=params)

    def approve_license_transfer_request(self, transfer_id, payload, headers):
        return self._request("POST", f"/api/license-transfer-requests/{transfer_id}/approve", payload, headers)

    def reject_license_transfer_request(self, transfer_id, headers):
        return self._request("POST", f"/api/license-transfer-requests/{transfer_id}/reject", headers=headers)

    def cancel_license_transfer_request(self, transfer_id, headers):
        return self._request("POST", f"/api/license-transfer-requests/{transfer_id}/cancel", headers=headers)

    def execute_license_transfer_request(self, transfer_id, headers):
        return self._request("POST", f"/api/license-transfer-requests/{transfer_id}/execute", headers=headers)


api_client = ApiClient()
