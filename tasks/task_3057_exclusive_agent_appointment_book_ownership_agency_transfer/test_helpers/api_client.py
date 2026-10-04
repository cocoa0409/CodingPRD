"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Administrative / diagnostics ───────────────────
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/agency-network/_clock/set_current_utc", payload, headers)

    def inject_agent(self, payload, headers):
        return self._request("POST", "/agency-network/_inject/agent", payload, headers)

    def envelope_echo(self, headers):
        return self._request("GET", "/agency-network/_envelopes/echo", headers=headers)

    # ─── Agencies ───────────────────────────────────────
    def create_agency(self, payload, headers):
        return self._request("POST", "/agency-network/agencies", payload, headers)

    def list_agencies(self, headers, params=None):
        return self._request("GET", "/agency-network/agencies", headers=headers, params=params)

    def get_agency(self, agency_id, headers):
        return self._request("GET", f"/agency-network/agencies/{agency_id}", headers=headers)

    def activate_agency(self, agency_id, payload, headers):
        return self._request(
            "POST", f"/agency-network/agencies/{agency_id}/activate", payload, headers
        )

    def terminate_agency(self, agency_id, headers):
        return self._request(
            "POST", f"/agency-network/agencies/{agency_id}/terminate", headers=headers
        )

    def run_ops(self, agency_id, headers):
        return self._request(
            "POST", f"/agency-network/agencies/{agency_id}/run_ops", {}, headers
        )

    def get_agency_performance(self, agency_id, headers):
        return self._request(
            "GET", f"/agency-network/agencies/{agency_id}/performance", headers=headers
        )

    def book_settlement(self, agency_id, payload, headers):
        return self._request(
            "POST", f"/agency-network/agencies/{agency_id}/book-settlement", payload, headers
        )

    def list_agency_policies(self, agency_id, headers, params=None):
        return self._request(
            "GET", f"/agency-network/agencies/{agency_id}/policies", headers=headers, params=params
        )

    def list_agency_agents(self, agency_id, headers, params=None):
        return self._request(
            "GET", f"/agency-network/agencies/{agency_id}/agents", headers=headers, params=params
        )

    # ─── Marketing campaigns ────────────────────────────
    def create_campaign(self, agency_id, payload, headers):
        return self._request(
            "POST", f"/agency-network/agencies/{agency_id}/marketing-campaigns", payload, headers
        )

    def list_campaigns(self, agency_id, headers, params=None):
        return self._request(
            "GET", f"/agency-network/agencies/{agency_id}/marketing-campaigns",
            headers=headers, params=params,
        )

    def get_campaign(self, agency_id, campaign_id, headers):
        return self._request(
            "GET", f"/agency-network/agencies/{agency_id}/marketing-campaigns/{campaign_id}",
            headers=headers,
        )

    def update_campaign(self, agency_id, campaign_id, payload, headers):
        return self._request(
            "PUT", f"/agency-network/agencies/{agency_id}/marketing-campaigns/{campaign_id}",
            payload, headers,
        )

    def participate_campaign(self, agency_id, campaign_id, payload, headers):
        return self._request(
            "POST",
            f"/agency-network/agencies/{agency_id}/marketing-campaigns/{campaign_id}/participate",
            payload, headers,
        )

    def delete_campaign(self, agency_id, campaign_id, headers):
        return self._request(
            "DELETE", f"/agency-network/agencies/{agency_id}/marketing-campaigns/{campaign_id}",
            headers=headers,
        )

    # ─── Appointment applications ───────────────────────
    def create_application(self, payload, headers):
        return self._request("POST", "/agency-network/appointment-applications", payload, headers)

    def list_applications(self, headers, params=None):
        return self._request(
            "GET", "/agency-network/appointment-applications", headers=headers, params=params
        )

    def get_application(self, application_id, headers):
        return self._request(
            "GET", f"/agency-network/appointment-applications/{application_id}", headers=headers
        )

    def assess_application(self, application_id, headers):
        return self._request(
            "POST", f"/agency-network/appointment-applications/{application_id}/assess", {}, headers
        )

    def approve_application(self, application_id, headers):
        return self._request(
            "POST", f"/agency-network/appointment-applications/{application_id}/approve", {}, headers
        )

    def reject_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"/agency-network/appointment-applications/{application_id}/reject",
            payload, headers,
        )

    def appoint_application(self, application_id, headers):
        return self._request(
            "POST", f"/agency-network/appointment-applications/{application_id}/appoint", {}, headers
        )

    # ─── Agents ─────────────────────────────────────────
    def list_agents(self, headers, params=None):
        return self._request("GET", "/agency-network/agents", headers=headers, params=params)

    def get_agent(self, agent_id, headers):
        return self._request("GET", f"/agency-network/agents/{agent_id}", headers=headers)

    def read_license(self, agent_id, payload, headers):
        return self._request(
            "POST", f"/agency-network/agents/{agent_id}/read-license", payload, headers
        )

    def transition_book(self, agent_id, payload, headers):
        return self._request(
            "POST", f"/agency-network/agents/{agent_id}/transition-book", payload, headers
        )

    def cessation(self, agent_id, payload, headers):
        return self._request(
            "POST", f"/agency-network/agents/{agent_id}/cessation", payload, headers
        )

    def reassign_policy(self, agent_id, policy_id, payload, headers):
        return self._request(
            "POST", f"/agency-network/agents/{agent_id}/policies/{policy_id}/cessation",
            payload, headers,
        )

    def complete_reassignment(self, agent_id, headers):
        return self._request(
            "POST", f"/agency-network/agents/{agent_id}/complete-reassignment", {}, headers
        )

    def list_agent_staff(self, agent_id, headers, params=None):
        return self._request(
            "GET", f"/agency-network/agents/{agent_id}/staff", headers=headers, params=params
        )

    def create_book_transfer(self, agent_id, payload, headers):
        return self._request(
            "POST", f"/agency-network/agents/{agent_id}/book-transfer", payload, headers
        )

    def list_agent_book_transfers(self, agent_id, headers, params=None):
        return self._request(
            "GET", f"/agency-network/agents/{agent_id}/book-transfers",
            headers=headers, params=params,
        )

    # ─── Agreements ─────────────────────────────────────
    def create_agreement(self, payload, headers):
        return self._request("POST", "/agency-network/agreements", payload, headers)

    def list_agreements(self, headers, params=None):
        return self._request("GET", "/agency-network/agreements", headers=headers, params=params)

    def get_agreement(self, agreement_id, headers):
        return self._request("GET", f"/agency-network/agreements/{agreement_id}", headers=headers)

    def transcribe_agreement(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/agency-network/agreements/{agreement_id}/transcribe", payload, headers
        )

    # ─── Staff ──────────────────────────────────────────
    def create_staff(self, payload, headers):
        return self._request("POST", "/agency-network/staff", payload, headers)

    def list_staff(self, headers, params=None):
        return self._request("GET", "/agency-network/staff", headers=headers, params=params)

    def get_staff(self, staff_id, headers):
        return self._request("GET", f"/agency-network/staff/{staff_id}", headers=headers)

    def appoint_staff(self, staff_id, headers):
        return self._request("POST", f"/agency-network/staff/{staff_id}/appoint", {}, headers)

    # ─── Policies ───────────────────────────────────────
    def create_policy(self, payload, headers):
        return self._request("POST", "/agency-network/policies", payload, headers)

    def list_policies(self, headers, params=None):
        return self._request("GET", "/agency-network/policies", headers=headers, params=params)

    def get_policy(self, policy_id, headers):
        return self._request("GET", f"/agency-network/policies/{policy_id}", headers=headers)

    def cancel_policy(self, policy_id, headers):
        return self._request("POST", f"/agency-network/policies/{policy_id}/cancel", {}, headers)

    # ─── Claims ─────────────────────────────────────────
    def create_claim(self, payload, headers):
        return self._request("POST", "/agency-network/claims", payload, headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/agency-network/claims", headers=headers, params=params)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/agency-network/claims/{claim_id}", headers=headers)

    def settle_claim(self, claim_id, headers):
        return self._request("POST", f"/agency-network/claims/{claim_id}/settle", {}, headers)

    def resolve_claim(self, claim_id, headers):
        return self._request("POST", f"/agency-network/claims/{claim_id}/resolve", {}, headers)

    def deny_claim(self, claim_id, headers):
        return self._request("POST", f"/agency-network/claims/{claim_id}/deny", {}, headers)

    # ─── License records ────────────────────────────────
    def create_license_record(self, payload, headers):
        return self._request("POST", "/agency-network/license-records", payload, headers)

    def list_license_records(self, headers, params=None):
        return self._request(
            "GET", "/agency-network/license-records", headers=headers, params=params
        )

    # ─── Book transfers ─────────────────────────────────
    def list_book_transfers(self, headers, params=None):
        return self._request(
            "GET", "/agency-network/book-transfers", headers=headers, params=params
        )

    def get_book_transfer(self, transfer_id, headers):
        return self._request(
            "GET", f"/agency-network/book-transfers/{transfer_id}", headers=headers
        )


api_client = ApiClient()