"""API client: one method per endpoint declared in the PRD §4 table."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Thin endpoint wrapper over the platform's flat REST surface."""

    # --- Region -------------------------------------------------------------

    def create_region(self, payload, headers):
        return self._request("POST", "/regions", payload, headers)

    def get_region(self, region_id, headers):
        return self._request("GET", f"/regions/{region_id}", headers=headers)

    def list_region_agents(self, region_id, headers, params=None):
        return self._request("GET", f"/regions/{region_id}/agents", params=params, headers=headers)

    def run_region_ops(self, region_id, headers):
        return self._request("POST", f"/regions/{region_id}/run-ops", {}, headers)

    def list_region_referrals(self, region_id, headers, params=None):
        return self._request("GET", f"/regions/{region_id}/referrals", params=params, headers=headers)

    def list_region_activity_audits(self, region_id, headers, params=None):
        return self._request("GET", f"/regions/{region_id}/activity-audits", params=params, headers=headers)

    # --- Agent --------------------------------------------------------------

    def create_agent(self, payload, headers):
        return self._request("POST", "/agents", payload, headers)

    def get_agent(self, agent_id, headers):
        return self._request("GET", f"/agents/{agent_id}", headers=headers)

    def list_agents(self, headers, params=None):
        return self._request("GET", "/agents", params=params, headers=headers)

    def set_agent_status(self, agent_id, payload, headers):
        return self._request("POST", f"/agents/{agent_id}/status", payload, headers)

    def get_open_client_counts(self, agent_id, headers):
        return self._request("GET", f"/agents/{agent_id}/open-client-counts", headers=headers)

    def get_lead_capacity(self, agent_id, headers):
        return self._request("GET", f"/agents/{agent_id}/lead-capacity", headers=headers)

    # --- Client -------------------------------------------------------------

    def create_client(self, payload, headers):
        return self._request("POST", "/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/clients/{client_id}", headers=headers)

    def list_clients(self, headers, params=None):
        return self._request("GET", "/clients", params=params, headers=headers)

    def assign_agent(self, client_id, payload, headers):
        return self._request("POST", f"/clients/{client_id}/assign-agent", payload, headers)

    # --- Transaction --------------------------------------------------------

    def open_transaction(self, client_id, payload, headers):
        return self._request("POST", f"/clients/{client_id}/transactions", payload, headers)

    def get_transaction(self, transaction_id, headers):
        return self._request("GET", f"/transactions/{transaction_id}", headers=headers)

    def list_client_transactions(self, client_id, headers, params=None):
        return self._request("GET", f"/clients/{client_id}/transactions", params=params, headers=headers)

    def list_transactions(self, headers, params=None):
        return self._request("GET", "/transactions", params=params, headers=headers)

    def set_coordination(self, transaction_id, payload, headers):
        return self._request("POST", f"/transactions/{transaction_id}/coordination", payload, headers)

    def close_transaction(self, transaction_id, headers):
        return self._request("POST", f"/transactions/{transaction_id}/close", {}, headers)

    def close_client_transaction(self, client_id, transaction_id, headers):
        return self._request("POST", f"/clients/{client_id}/transactions/{transaction_id}/close", {}, headers)

    def cancel_transaction(self, transaction_id, headers):
        return self._request("POST", f"/transactions/{transaction_id}/cancel", {}, headers)

    # --- Survey -------------------------------------------------------------

    def create_survey(self, transaction_id, payload, headers):
        return self._request("POST", f"/transactions/{transaction_id}/surveys", payload, headers)

    def list_transaction_surveys(self, transaction_id, headers, params=None):
        return self._request("GET", f"/transactions/{transaction_id}/surveys", params=params, headers=headers)

    def respond_survey(self, survey_id, payload, headers):
        return self._request("POST", f"/surveys/{survey_id}/respond", payload, headers)

    def get_survey(self, survey_id, headers):
        return self._request("GET", f"/surveys/{survey_id}", headers=headers)

    def list_surveys(self, headers, params=None):
        return self._request("GET", "/surveys", params=params, headers=headers)

    # --- ListingAgreement ---------------------------------------------------

    def create_listing_agreement(self, payload, headers):
        return self._request("POST", "/listing-agreements", payload, headers)

    def get_listing_agreement(self, agreement_id, headers):
        return self._request("GET", f"/listing-agreements/{agreement_id}", headers=headers)

    def list_listing_agreements(self, headers, params=None):
        return self._request("GET", "/listing-agreements", params=params, headers=headers)

    def publish_listing(self, agreement_id, headers):
        return self._request("POST", f"/listing-agreements/{agreement_id}/publish", {}, headers)

    def accept_offer(self, agreement_id, payload, headers):
        return self._request("POST", f"/listing-agreements/{agreement_id}/accept-offer", payload, headers)

    def revert_listing_to_active(self, agreement_id, headers):
        return self._request("POST", f"/listing-agreements/{agreement_id}/revert-to-active", {}, headers)

    def withdraw_listing(self, agreement_id, headers):
        return self._request("POST", f"/listing-agreements/{agreement_id}/withdraw", {}, headers)

    def register_listing_window(self, agreement_id, payload, headers):
        return self._request("POST", f"/listing-agreements/{agreement_id}/register", payload, headers)

    # --- Tour ---------------------------------------------------------------

    def create_tour(self, payload, headers):
        return self._request("POST", "/tours", payload, headers)

    def list_tours(self, headers, params=None):
        return self._request("GET", "/tours", params=params, headers=headers)

    def get_tour(self, tour_id, headers):
        return self._request("GET", f"/tours/{tour_id}", headers=headers)

    def confirm_tour(self, tour_id, headers):
        return self._request("POST", f"/tours/{tour_id}/confirm", {}, headers)

    def complete_tour(self, tour_id, payload, headers):
        return self._request("POST", f"/tours/{tour_id}/complete", payload, headers)

    def no_show_tour(self, tour_id, headers):
        return self._request("POST", f"/tours/{tour_id}/no-show", {}, headers)

    def cancel_tour(self, tour_id, headers):
        return self._request("POST", f"/tours/{tour_id}/cancel", {}, headers)

    # --- AgentReferral ------------------------------------------------------

    def create_referral(self, payload, headers):
        return self._request("POST", "/referrals", payload, headers)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"/referrals/{referral_id}", headers=headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", "/referrals", params=params, headers=headers)

    def reconcile_referral(self, referral_id, payload, headers):
        return self._request("POST", f"/referrals/{referral_id}/reconcile", payload, headers)

    def settle_referral(self, referral_id, payload, headers):
        return self._request("POST", f"/referrals/{referral_id}/settle", payload, headers)

    def manual_referral(self, referral_id, payload, headers):
        return self._request("POST", f"/referrals/{referral_id}/manual-referral", payload, headers)

    def accept_referral(self, referral_id, payload, headers):
        return self._request("POST", f"/referrals/{referral_id}/accept", payload, headers)

    # --- ActivityAudit ------------------------------------------------------

    def list_activity_audits(self, headers, params=None):
        return self._request("GET", "/activity-audits", params=params, headers=headers)

    # --- Logical clock ------------------------------------------------------

    def set_current_utc(self, current_utc, headers):
        return self._request("POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers)


api_client = ApiClient()