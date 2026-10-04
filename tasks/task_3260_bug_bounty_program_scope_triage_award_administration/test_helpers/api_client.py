"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Programs ---
    def create_program(self, payload, headers):
        return self._request("POST", "/api/programs", payload, headers)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/api/programs/{program_id}", headers=headers)

    def patch_program(self, program_id, payload, headers):
        return self._request("PATCH", f"/api/programs/{program_id}", payload, headers)

    def activate_program(self, program_id, headers):
        return self._request("POST", f"/api/programs/{program_id}/activate", {}, headers)

    def pause_program(self, program_id, headers):
        return self._request("POST", f"/api/programs/{program_id}/pause", {}, headers)

    def close_program(self, program_id, headers):
        return self._request("POST", f"/api/programs/{program_id}/close", {}, headers)

    # --- Scope assets ---
    def create_asset(self, payload, headers):
        return self._request("POST", "/api/assets", payload, headers)

    def list_assets(self, headers, params=None):
        return self._request("GET", "/api/assets", headers=headers, params=params)

    def get_asset(self, asset_id, headers):
        return self._request("GET", f"/api/assets/{asset_id}", headers=headers)

    def retire_asset(self, asset_id, headers):
        return self._request("POST", f"/api/assets/{asset_id}/retire", {}, headers)

    # --- Scope versions ---
    def create_scope_version(self, payload, headers):
        return self._request("POST", "/api/scope-versions", payload, headers)

    def get_scope_version(self, scope_version_id, headers):
        return self._request("GET", f"/api/scope-versions/{scope_version_id}", headers=headers)

    def list_scope_versions(self, headers, params=None):
        return self._request("GET", "/api/scope-versions", headers=headers, params=params)

    # --- Researchers ---
    def create_researcher(self, payload, headers):
        return self._request("POST", "/api/researchers", payload, headers)

    def get_researcher(self, researcher_id, headers):
        return self._request("GET", f"/api/researchers/{researcher_id}", headers=headers)

    def submit_tax_document(self, researcher_id, payload, headers):
        return self._request("POST", f"/api/researchers/{researcher_id}/tax-documents", payload, headers)

    def conduct_action(self, researcher_id, payload, headers):
        return self._request("POST", f"/api/researchers/{researcher_id}/conduct-actions", payload, headers)

    # --- Invitations ---
    def create_invitation(self, payload, headers):
        return self._request("POST", "/api/invitations", payload, headers)

    def get_invitation(self, invitation_id, headers):
        return self._request("GET", f"/api/invitations/{invitation_id}", headers=headers)

    def list_invitations(self, headers, params=None):
        return self._request("GET", "/api/invitations", headers=headers, params=params)

    def respond_invitation(self, invitation_id, payload, headers):
        return self._request("POST", f"/api/invitations/{invitation_id}/respond", payload, headers)

    # --- Reports ---
    def create_report(self, payload, headers):
        return self._request("POST", "/api/reports", payload, headers)

    def get_report(self, report_id, headers):
        return self._request("GET", f"/api/reports/{report_id}", headers=headers)

    def list_reports(self, headers, params=None):
        return self._request("GET", "/api/reports", headers=headers, params=params)

    def triage_report(self, report_id, payload, headers):
        return self._request("POST", f"/api/reports/{report_id}/triage", payload, headers)

    def provide_info(self, report_id, payload, headers):
        return self._request("POST", f"/api/reports/{report_id}/provide-info", payload, headers)

    def validate_report(self, report_id, payload, headers):
        return self._request("POST", f"/api/reports/{report_id}/validate", payload, headers)

    # --- Awards ---
    def create_award(self, payload, headers):
        return self._request("POST", "/api/awards", payload, headers)

    def get_award(self, award_id, headers):
        return self._request("GET", f"/api/awards/{award_id}", headers=headers)

    def list_awards(self, headers, params=None):
        return self._request("GET", "/api/awards", headers=headers, params=params)

    def approve_award(self, award_id, headers):
        return self._request("POST", f"/api/awards/{award_id}/approve", {}, headers)

    def pay_award(self, award_id, headers):
        return self._request("POST", f"/api/awards/{award_id}/pay", {}, headers)

    def void_award(self, award_id, headers):
        return self._request("POST", f"/api/awards/{award_id}/void", {}, headers)

    # --- Disclosure requests ---
    def create_disclosure_request(self, payload, headers):
        return self._request("POST", "/api/disclosure-requests", payload, headers)

    def get_disclosure_request(self, disclosure_request_id, headers):
        return self._request("GET", f"/api/disclosure-requests/{disclosure_request_id}", headers=headers)

    def list_disclosure_requests(self, headers, params=None):
        return self._request("GET", "/api/disclosure-requests", headers=headers, params=params)

    def respond_disclosure_request(self, disclosure_request_id, payload, headers):
        return self._request(
            "POST", f"/api/disclosure-requests/{disclosure_request_id}/respond", payload, headers
        )

    # --- Remediation tickets ---
    def create_remediation_ticket(self, payload, headers):
        return self._request("POST", "/api/remediation-tickets", payload, headers)

    def get_remediation_ticket(self, remediation_ticket_id, headers):
        return self._request(
            "GET", f"/api/remediation-tickets/{remediation_ticket_id}", headers=headers
        )

    def list_remediation_tickets(self, headers, params=None):
        return self._request("GET", "/api/remediation-tickets", headers=headers, params=params)

    def transition_remediation_ticket(self, remediation_ticket_id, payload, headers):
        return self._request(
            "POST", f"/api/remediation-tickets/{remediation_ticket_id}/transition", payload, headers
        )

    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
