"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/care-network"


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- networks ---
    def create_network(self, payload, headers):
        return self._request("POST", f"{PREFIX}/networks", payload, headers)

    def get_network(self, network_id, headers):
        return self._request("GET", f"{PREFIX}/networks/{network_id}", headers=headers)

    # --- taxonomy ---
    def create_taxonomy_category(self, payload, headers):
        return self._request("POST", f"{PREFIX}/taxonomy", payload, headers)

    def list_taxonomy_categories(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/taxonomy", headers=headers, params=params)

    def get_taxonomy_category(self, category_id, headers):
        return self._request("GET", f"{PREFIX}/taxonomy/{category_id}", headers=headers)

    def retire_taxonomy_category(self, category_id, headers):
        return self._request("POST", f"{PREFIX}/taxonomy/{category_id}/retire", {}, headers)

    # --- organizations ---
    def create_organization(self, payload, headers):
        return self._request("POST", f"{PREFIX}/organizations", payload, headers)

    def list_organizations(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/organizations", headers=headers, params=params)

    def get_organization(self, org_id, headers):
        return self._request("GET", f"{PREFIX}/organizations/{org_id}", headers=headers)

    def activate_organization(self, org_id, headers):
        return self._request("POST", f"{PREFIX}/organizations/{org_id}/activate", {}, headers)

    def suspend_organization(self, org_id, payload, headers):
        return self._request("POST", f"{PREFIX}/organizations/{org_id}/suspend",
                             payload, headers)

    def terminate_organization(self, org_id, headers):
        return self._request("POST", f"{PREFIX}/organizations/{org_id}/terminate", {}, headers)

    # --- service offerings ---
    def create_offering(self, org_id, payload, headers):
        return self._request("POST", f"{PREFIX}/organizations/{org_id}/offerings",
                             payload, headers)

    def list_org_offerings(self, org_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/organizations/{org_id}/offerings",
                             headers=headers, params=params)

    def get_offering(self, offering_id, headers):
        return self._request("GET", f"{PREFIX}/offerings/{offering_id}", headers=headers)

    def pause_offering(self, offering_id, headers):
        return self._request("POST", f"{PREFIX}/offerings/{offering_id}/pause", {}, headers)

    def resume_offering(self, offering_id, headers):
        return self._request("POST", f"{PREFIX}/offerings/{offering_id}/resume", {}, headers)

    def list_offering_referrals(self, offering_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/offerings/{offering_id}/referrals",
                             headers=headers, params=params)

    # --- clients ---
    def create_client(self, payload, headers):
        return self._request("POST", f"{PREFIX}/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"{PREFIX}/clients/{client_id}", headers=headers)

    def list_client_referrals(self, client_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/clients/{client_id}/referrals",
                             headers=headers, params=params)

    # --- agreements ---
    def create_agreement(self, payload, headers):
        return self._request("POST", f"{PREFIX}/agreements", payload, headers)

    def list_agreements(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/agreements", headers=headers, params=params)

    def list_org_agreements(self, org_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/organizations/{org_id}/agreements",
                             headers=headers, params=params)

    def approve_agreement(self, agreement_id, headers):
        return self._request("POST", f"{PREFIX}/agreements/{agreement_id}/approve", {}, headers)

    def expire_agreement(self, agreement_id, headers):
        return self._request("POST", f"{PREFIX}/agreements/{agreement_id}/expire", {}, headers)

    def terminate_agreement(self, agreement_id, headers):
        return self._request("POST", f"{PREFIX}/agreements/{agreement_id}/terminate", {}, headers)

    # --- consents ---
    def create_consent(self, client_id, payload, headers):
        return self._request("POST", f"{PREFIX}/clients/{client_id}/consents", payload, headers)

    def list_consents(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/consents", headers=headers, params=params)

    def list_client_consents(self, client_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/clients/{client_id}/consents",
                             headers=headers, params=params)

    def get_consent(self, consent_id, headers):
        return self._request("GET", f"{PREFIX}/consents/{consent_id}", headers=headers)

    def revoke_consent(self, consent_id, headers):
        return self._request("POST", f"{PREFIX}/consents/{consent_id}/revoke", {}, headers)

    # --- referrals ---
    def create_referral(self, payload, headers):
        return self._request("POST", f"{PREFIX}/referrals", payload, headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/referrals", headers=headers, params=params)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"{PREFIX}/referrals/{referral_id}", headers=headers)

    def route_referral(self, referral_id, headers):
        return self._request("POST", f"{PREFIX}/referrals/{referral_id}/route", {}, headers)

    def accept_referral(self, referral_id, headers):
        return self._request("POST", f"{PREFIX}/referrals/{referral_id}/accept", {}, headers)

    def decline_referral(self, referral_id, payload, headers):
        return self._request("POST", f"{PREFIX}/referrals/{referral_id}/decline",
                             payload, headers)

    def reassign_referral(self, referral_id, payload, headers):
        return self._request("POST", f"{PREFIX}/referrals/{referral_id}/reassign",
                             payload, headers)

    def escalate_referral(self, referral_id, headers):
        return self._request("POST", f"{PREFIX}/referrals/{referral_id}/escalate", {}, headers)

    def start_service(self, referral_id, headers):
        return self._request("POST", f"{PREFIX}/referrals/{referral_id}/start-service",
                             {}, headers)

    def confirm_outcome(self, referral_id, payload, headers):
        return self._request("POST", f"{PREFIX}/referrals/{referral_id}/confirm-outcome",
                             payload, headers)

    def cancel_referral(self, referral_id, payload, headers):
        return self._request("POST", f"{PREFIX}/referrals/{referral_id}/cancel",
                             payload, headers)

    def run_aging_sweep(self, headers):
        return self._request("POST", f"{PREFIX}/referrals/aging-sweep", {}, headers)

    # --- referral notes ---
    def create_referral_note(self, referral_id, payload, headers):
        return self._request("POST", f"{PREFIX}/referrals/{referral_id}/notes",
                             payload, headers)

    def list_referral_notes(self, referral_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/referrals/{referral_id}/notes",
                             headers=headers, params=params)

    def list_org_notes(self, org_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/organizations/{org_id}/notes",
                             headers=headers, params=params)

    # --- outcome records ---
    def get_referral_outcome(self, referral_id, headers):
        return self._request("GET", f"{PREFIX}/referrals/{referral_id}/outcome",
                             headers=headers)

    def list_org_outcomes(self, org_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/organizations/{org_id}/outcomes",
                             headers=headers, params=params)

    # --- rate cards ---
    def create_rate_card(self, funder_org_id, payload, headers):
        return self._request("POST", f"{PREFIX}/organizations/{funder_org_id}/rate-cards",
                             payload, headers)

    def list_rate_cards(self, funder_org_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/organizations/{funder_org_id}/rate-cards",
                             headers=headers, params=params)

    def get_rate_card(self, rate_card_id, headers):
        return self._request("GET", f"{PREFIX}/rate-cards/{rate_card_id}", headers=headers)

    # --- claims ---
    def create_claim(self, payload, headers):
        return self._request("POST", f"{PREFIX}/claims", payload, headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/claims", headers=headers, params=params)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"{PREFIX}/claims/{claim_id}", headers=headers)

    def review_claim(self, claim_id, headers):
        return self._request("POST", f"{PREFIX}/claims/{claim_id}/review", {}, headers)

    def approve_claim(self, claim_id, payload, headers):
        return self._request("POST", f"{PREFIX}/claims/{claim_id}/approve", payload, headers)

    def deny_claim(self, claim_id, payload, headers):
        return self._request("POST", f"{PREFIX}/claims/{claim_id}/deny", payload, headers)

    def void_claim(self, claim_id, payload, headers):
        return self._request("POST", f"{PREFIX}/claims/{claim_id}/void", payload, headers)

    # --- disbursements ---
    def create_disbursement(self, payload, headers):
        return self._request("POST", f"{PREFIX}/disbursements", payload, headers)

    def list_disbursements(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/disbursements", headers=headers, params=params)

    def get_disbursement(self, disbursement_id, headers):
        return self._request("GET", f"{PREFIX}/disbursements/{disbursement_id}",
                             headers=headers)

    def run_disbursement(self, disbursement_id, payload, headers):
        return self._request("POST", f"{PREFIX}/disbursements/{disbursement_id}/run",
                             payload, headers)

    # --- reports ---
    def create_report(self, funder_org_id, payload, headers):
        return self._request("POST", f"{PREFIX}/organizations/{funder_org_id}/reports",
                             payload, headers)

    def get_report(self, report_id, headers):
        return self._request("GET", f"{PREFIX}/reports/{report_id}", headers=headers)

    def list_reports(self, funder_org_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/organizations/{funder_org_id}/reports",
                             headers=headers, params=params)

    def seal_report(self, report_id, headers):
        return self._request("POST", f"{PREFIX}/reports/{report_id}/seal", {}, headers)


api_client = ApiClient()
