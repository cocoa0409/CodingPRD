"""API client: one method per endpoint defined in the PRD (mounted under /tax)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- offices ---
    def create_office(self, payload, headers):
        return self._request("POST", "/tax/offices", payload, headers)

    def list_offices(self, headers, params=None):
        return self._request("GET", "/tax/offices", headers=headers, params=params)

    def get_office(self, office_id, headers):
        return self._request("GET", f"/tax/offices/{office_id}", headers=headers)

    def quality_close_office(self, office_id, payload, headers):
        return self._request("POST", f"/tax/offices/{office_id}/quality-close", payload, headers)

    def list_office_snapshots(self, office_id, headers, params=None):
        return self._request("GET", f"/tax/offices/{office_id}/snapshots", headers=headers, params=params)

    # --- preparers ---
    def create_preparer(self, payload, headers):
        return self._request("POST", "/tax/preparers", payload, headers)

    def list_preparers(self, headers, params=None):
        return self._request("GET", "/tax/preparers", headers=headers, params=params)

    def get_preparer(self, preparer_id, headers):
        return self._request("GET", f"/tax/preparers/{preparer_id}", headers=headers)

    def upgrade_preparer(self, preparer_id, payload, headers):
        return self._request("POST", f"/tax/preparers/{preparer_id}/upgrade", payload, headers)

    # --- clients ---
    def create_client(self, payload, headers):
        return self._request("POST", "/tax/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/tax/clients/{client_id}", headers=headers)

    def list_client_returns(self, client_id, headers, params=None):
        return self._request("GET", f"/tax/clients/{client_id}/returns", headers=headers, params=params)

    # --- returns ---
    def create_return(self, payload, headers):
        return self._request("POST", "/tax/returns", payload, headers)

    def get_return(self, return_id, headers):
        return self._request("GET", f"/tax/returns/{return_id}", headers=headers)

    def list_returns(self, headers, params=None):
        return self._request("GET", "/tax/returns", headers=headers, params=params)

    def list_return_products(self, return_id, headers, params=None):
        return self._request("GET", f"/tax/returns/{return_id}/products", headers=headers, params=params)

    def list_return_notices(self, return_id, headers, params=None):
        return self._request("GET", f"/tax/returns/{return_id}/notices", headers=headers, params=params)

    def patch_return(self, return_id, payload, headers):
        return self._request("PATCH", f"/tax/returns/{return_id}", payload, headers)

    def file_return(self, return_id, headers):
        return self._request("POST", f"/tax/returns/{return_id}/file", {}, headers)

    # --- products ---
    def create_product(self, payload, headers):
        return self._request("POST", "/tax/products", payload, headers)

    def void_product(self, product_id, headers):
        return self._request("POST", f"/tax/products/{product_id}/void", {}, headers)

    # --- notices ---
    def create_notice(self, payload, headers):
        return self._request("POST", "/tax/notices", payload, headers)

    def get_notice(self, notice_id, headers):
        return self._request("GET", f"/tax/notices/{notice_id}", headers=headers)

    def list_notices(self, headers, params=None):
        return self._request("GET", "/tax/notices", headers=headers, params=params)

    def pay_notice(self, notice_id, headers):
        return self._request("POST", f"/tax/notices/{notice_id}/pay", {}, headers)

    def abate_notice(self, notice_id, headers):
        return self._request("POST", f"/tax/notices/{notice_id}/abate", {}, headers)

    def withdraw_notice(self, notice_id, headers):
        return self._request("POST", f"/tax/notices/{notice_id}/withdraw", {}, headers)

    # --- claims ---
    def create_claim(self, payload, headers):
        return self._request("POST", "/tax/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/tax/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/tax/claims", headers=headers, params=params)

    def list_claim_poas(self, claim_id, headers, params=None):
        return self._request("GET", f"/tax/claims/{claim_id}/poas", headers=headers, params=params)

    def list_claim_assignments(self, claim_id, headers, params=None):
        return self._request("GET", f"/tax/claims/{claim_id}/assignments", headers=headers, params=params)

    def scope_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/tax/claims/{claim_id}/scope", payload, headers)

    def request_info_claim(self, claim_id, headers):
        return self._request("POST", f"/tax/claims/{claim_id}/request-info", {}, headers)

    def provide_info_claim(self, claim_id, headers):
        return self._request("POST", f"/tax/claims/{claim_id}/provide-info", {}, headers)

    def assign_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/tax/claims/{claim_id}/assign", payload, headers)

    def create_poa(self, claim_id, payload, headers):
        return self._request("POST", f"/tax/claims/{claim_id}/poa", payload, headers)

    def execute_poa(self, claim_id, payload, headers):
        return self._request("POST", f"/tax/claims/{claim_id}/poa/execute", payload, headers)

    def resolve_claim(self, claim_id, headers):
        return self._request("POST", f"/tax/claims/{claim_id}/resolve", {}, headers)

    def reopen_claim(self, claim_id, headers):
        return self._request("POST", f"/tax/claims/{claim_id}/reopen", {}, headers)

    # --- assignments / poas ---
    def cancel_assignment(self, assignment_id, headers):
        return self._request("POST", f"/tax/assignments/{assignment_id}/cancel", {}, headers)

    def get_poa(self, poa_id, headers):
        return self._request("GET", f"/tax/poas/{poa_id}", headers=headers)

    def list_poas(self, headers, params=None):
        return self._request("GET", "/tax/poas", headers=headers, params=params)

    def revoke_poa(self, poa_id, headers):
        return self._request("POST", f"/tax/poas/{poa_id}/revoke", {}, headers)

    # --- agents ---
    def create_agent(self, payload, headers):
        return self._request("POST", "/tax/agents", payload, headers)

    def get_agent(self, agent_id, headers):
        return self._request("GET", f"/tax/agents/{agent_id}", headers=headers)

    def list_agent_assignments(self, agent_id, headers, params=None):
        return self._request("GET", f"/tax/agents/{agent_id}/assignments", headers=headers, params=params)

    # --- remediations ---
    def create_remediation(self, payload, headers):
        return self._request("POST", "/tax/remediations", payload, headers)

    def list_remediations(self, headers, params=None):
        return self._request("GET", "/tax/remediations", headers=headers, params=params)

    def get_remediation(self, remediation_id, headers):
        return self._request("GET", f"/tax/remediations/{remediation_id}", headers=headers)

    def complete_remediation(self, remediation_id, headers):
        return self._request("POST", f"/tax/remediations/{remediation_id}/complete", {}, headers)

    # --- escrows ---
    def create_escrow(self, payload, headers):
        return self._request("POST", "/tax/escrows", payload, headers)

    def get_escrow(self, escrow_id, headers):
        return self._request("GET", f"/tax/escrows/{escrow_id}", headers=headers)

    def list_escrows(self, headers, params=None):
        return self._request("GET", "/tax/escrows", headers=headers, params=params)

    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/tax/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
