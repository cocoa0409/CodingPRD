"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/api/v1/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ---- regions ----
    def create_region(self, payload, headers):
        return self._request("POST", "/api/v1/regions", payload, headers)

    def get_region(self, region_id, headers, params=None):
        return self._request("GET", f"/api/v1/regions/{region_id}", headers=headers, params=params)

    def list_region_operations(self, region_id, headers, params=None):
        return self._request("GET", f"/api/v1/regions/{region_id}/disaster-relief-operations",
                             headers=headers, params=params)

    def list_region_shelter_sites(self, region_id, headers, params=None):
        return self._request("GET", f"/api/v1/regions/{region_id}/shelter-sites",
                             headers=headers, params=params)

    def list_region_volunteers(self, region_id, headers, params=None):
        return self._request("GET", f"/api/v1/regions/{region_id}/volunteers",
                             headers=headers, params=params)

    def list_region_fund_pools(self, region_id, headers, params=None):
        return self._request("GET", f"/api/v1/regions/{region_id}/fund-pools",
                             headers=headers, params=params)

    def list_region_blood_drives(self, region_id, headers, params=None):
        return self._request("GET", f"/api/v1/regions/{region_id}/blood-drives",
                             headers=headers, params=params)

    def list_region_clients(self, region_id, headers, params=None):
        return self._request("GET", f"/api/v1/regions/{region_id}/clients",
                             headers=headers, params=params)

    # ---- disaster relief operations ----
    def create_operation(self, payload, headers):
        return self._request("POST", "/api/v1/disaster-relief-operations", payload, headers)

    def get_operation(self, operation_id, headers):
        return self._request("GET", f"/api/v1/disaster-relief-operations/{operation_id}",
                             headers=headers)

    def advance_operation_phase(self, operation_id, headers):
        return self._request("POST", f"/api/v1/disaster-relief-operations/{operation_id}/advance-phase",
                             {}, headers)

    def list_deployment_candidates(self, operation_id, headers, params=None):
        return self._request("GET", f"/api/v1/disaster-relief-operations/{operation_id}/deployment-candidates",
                             headers=headers, params=params)

    def create_cost_ledger_entry(self, operation_id, payload, headers):
        return self._request("POST", f"/api/v1/disaster-relief-operations/{operation_id}/cost-ledger-entries",
                             payload, headers)

    # ---- shelter sites ----
    def create_shelter_site(self, payload, headers):
        return self._request("POST", "/api/v1/shelter-sites", payload, headers)

    def get_shelter_site(self, site_id, headers):
        return self._request("GET", f"/api/v1/shelter-sites/{site_id}", headers=headers)

    def record_inspection(self, site_id, payload, headers):
        return self._request("POST", f"/api/v1/shelter-sites/{site_id}/inspections", payload, headers)

    def list_site_shelter_operations(self, site_id, headers, params=None):
        return self._request("GET", f"/api/v1/shelter-sites/{site_id}/shelter-operations",
                             headers=headers, params=params)

    # ---- shelter operations ----
    def create_shelter_operation(self, payload, headers):
        return self._request("POST", "/api/v1/shelter-operations", payload, headers)

    def get_shelter_operation(self, shelter_operation_id, headers, params=None):
        return self._request("GET", f"/api/v1/shelter-operations/{shelter_operation_id}",
                             headers=headers, params=params)

    def list_shelter_operations(self, headers, params=None):
        return self._request("GET", "/api/v1/shelter-operations", headers=headers, params=params)

    def open_shelter(self, shelter_operation_id, headers):
        return self._request("POST", f"/api/v1/shelter-operations/{shelter_operation_id}/open",
                             {}, headers)

    def close_shelter(self, shelter_operation_id, headers):
        return self._request("POST", f"/api/v1/shelter-operations/{shelter_operation_id}/close",
                             {}, headers)

    def register_client(self, shelter_operation_id, payload, headers):
        return self._request("POST", f"/api/v1/shelter-operations/{shelter_operation_id}/registrations",
                             payload, headers)

    def record_feeding_service(self, shelter_operation_id, payload, headers):
        return self._request("POST", f"/api/v1/shelter-operations/{shelter_operation_id}/feeding-services",
                             payload, headers)

    def record_health_service(self, shelter_operation_id, payload, headers):
        return self._request("POST", f"/api/v1/shelter-operations/{shelter_operation_id}/health-services",
                             payload, headers)

    # ---- volunteers ----
    def create_volunteer(self, payload, headers):
        return self._request("POST", "/api/v1/volunteers", payload, headers)

    def get_volunteer(self, volunteer_id, headers):
        return self._request("GET", f"/api/v1/volunteers/{volunteer_id}", headers=headers)

    def refresh_credentials(self, volunteer_id, headers):
        return self._request("POST", f"/api/v1/volunteers/{volunteer_id}/credential-refresh",
                             {}, headers)

    # ---- volunteer deployments ----
    def create_deployment(self, payload, headers):
        return self._request("POST", "/api/v1/volunteer-deployments", payload, headers)

    def get_deployment(self, deployment_id, headers):
        return self._request("GET", f"/api/v1/volunteer-deployments/{deployment_id}",
                             headers=headers)

    def list_deployments(self, headers, params=None):
        return self._request("GET", "/api/v1/volunteer-deployments", headers=headers, params=params)

    def approve_deployment(self, deployment_id, headers):
        return self._request("POST", f"/api/v1/volunteer-deployments/{deployment_id}/approve",
                             {}, headers)

    def end_rotation(self, deployment_id, headers):
        return self._request("POST", f"/api/v1/volunteer-deployments/{deployment_id}/end-rotation",
                             {}, headers)

    def recall_deployment(self, deployment_id, headers):
        return self._request("POST", f"/api/v1/volunteer-deployments/{deployment_id}/recall",
                             {}, headers)

    # ---- shift assignments ----
    def create_shift(self, payload, headers):
        return self._request("POST", "/api/v1/shift-assignments", payload, headers)

    def get_shift(self, shift_id, headers):
        return self._request("GET", f"/api/v1/shift-assignments/{shift_id}", headers=headers)

    def list_shifts(self, headers, params=None):
        return self._request("GET", "/api/v1/shift-assignments", headers=headers, params=params)

    def check_in_shift(self, shift_id, headers):
        return self._request("POST", f"/api/v1/shift-assignments/{shift_id}/check-in", {}, headers)

    # ---- clients ----
    def create_client(self, payload, headers):
        return self._request("POST", "/api/v1/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/api/v1/clients/{client_id}", headers=headers)

    def list_clients(self, headers, params=None):
        return self._request("GET", "/api/v1/clients", headers=headers, params=params)

    # ---- shelter registrations ----
    def get_registration(self, registration_id, headers):
        return self._request("GET", f"/api/v1/shelter-registrations/{registration_id}",
                             headers=headers)

    def list_registrations(self, headers, params=None):
        return self._request("GET", "/api/v1/shelter-registrations", headers=headers, params=params)

    def check_out_registration(self, registration_id, payload, headers):
        return self._request("POST", f"/api/v1/shelter-registrations/{registration_id}/check-out",
                             payload, headers)

    # ---- client cases ----
    def create_client_case(self, payload, headers):
        return self._request("POST", "/api/v1/client-cases", payload, headers)

    def get_client_case(self, case_id, headers):
        return self._request("GET", f"/api/v1/client-cases/{case_id}", headers=headers)

    def list_client_cases(self, headers, params=None):
        return self._request("GET", "/api/v1/client-cases", headers=headers, params=params)

    def verify_eligibility(self, case_id, payload, headers):
        return self._request("POST", f"/api/v1/client-cases/{case_id}/verify-eligibility",
                             payload, headers)

    def write_recovery_plan(self, case_id, payload, headers):
        return self._request("POST", f"/api/v1/client-cases/{case_id}/recovery-plans",
                             payload, headers)

    def create_referral(self, case_id, payload, headers):
        return self._request("POST", f"/api/v1/client-cases/{case_id}/referrals", payload, headers)

    def list_case_referrals(self, case_id, headers, params=None):
        return self._request("GET", f"/api/v1/client-cases/{case_id}/referrals",
                             headers=headers, params=params)

    def create_assistance_request(self, case_id, payload, headers):
        return self._request("POST", f"/api/v1/client-cases/{case_id}/assistance-requests",
                             payload, headers)

    # ---- referrals ----
    def resolve_referral(self, referral_id, decision, headers):
        return self._request("POST", f"/api/v1/referrals/{referral_id}/resolve",
                             {"decision": decision}, headers)

    # ---- assistance requests ----
    def get_assistance_request(self, request_id, headers):
        return self._request("GET", f"/api/v1/assistance-requests/{request_id}", headers=headers)

    def list_assistance_requests(self, headers, params=None):
        return self._request("GET", "/api/v1/assistance-requests", headers=headers, params=params)

    def approve_assistance_request(self, request_id, headers):
        return self._request("POST", f"/api/v1/assistance-requests/{request_id}/approve",
                             {}, headers)

    def issue_card(self, request_id, headers):
        return self._request("POST", f"/api/v1/assistance-requests/{request_id}/issue-card",
                             {}, headers)

    def redeem_card(self, request_id, headers):
        return self._request("POST", f"/api/v1/assistance-requests/{request_id}/redeem-card",
                             {}, headers)

    def reverse_assistance(self, request_id, headers):
        return self._request("POST", f"/api/v1/assistance-requests/{request_id}/reverse",
                             {}, headers)

    # ---- fund pools ----
    def create_fund_pool(self, payload, headers):
        return self._request("POST", "/api/v1/fund-pools", payload, headers)

    def get_fund_pool(self, pool_id, headers):
        return self._request("GET", f"/api/v1/fund-pools/{pool_id}", headers=headers)

    # ---- cost ledger ----
    def get_cost_ledger_entry(self, entry_id, headers):
        return self._request("GET", f"/api/v1/cost-ledger-entries/{entry_id}", headers=headers)

    def list_cost_ledger_entries(self, headers, params=None):
        return self._request("GET", "/api/v1/cost-ledger-entries", headers=headers, params=params)

    # ---- blood drives ----
    def create_blood_drive(self, payload, headers):
        return self._request("POST", "/api/v1/blood-drives", payload, headers)

    def get_blood_drive(self, drive_id, headers):
        return self._request("GET", f"/api/v1/blood-drives/{drive_id}", headers=headers)

    def list_blood_drives(self, headers, params=None):
        return self._request("GET", "/api/v1/blood-drives", headers=headers, params=params)

    def record_collection(self, drive_id, units, headers):
        return self._request("POST", f"/api/v1/blood-drives/{drive_id}/collections",
                             {"units": units}, headers)

    def cancel_blood_drive(self, drive_id, headers):
        return self._request("POST", f"/api/v1/blood-drives/{drive_id}/cancel", {}, headers)


api_client = ApiClient()
