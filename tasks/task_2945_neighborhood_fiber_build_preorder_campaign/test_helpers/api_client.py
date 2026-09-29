"""API client: one method per endpoint the PRD declares.

Every endpoint is mounted at the service root, so the paths below are the
literal request paths.
"""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock -------------------------------------------------------
    def set_clock(self, current_utc, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    # --- Campaigns -----------------------------------------------------------
    def create_campaign(self, payload, headers):
        return self._request("POST", "/campaigns", payload, headers)

    def get_campaign(self, campaign_id, headers):
        return self._request("GET", f"/campaigns/{campaign_id}", headers=headers)

    def list_campaigns(self, headers, params=None):
        return self._request("GET", "/campaigns", headers=headers, params=params)

    def qualification_run(self, campaign_id, headers, payload=None):
        return self._request(
            "POST", f"/campaigns/{campaign_id}/qualification-run", payload or {}, headers
        )

    def sequencing_run(self, campaign_id, headers, payload=None):
        return self._request(
            "POST", f"/campaigns/{campaign_id}/sequencing-run", payload or {}, headers
        )

    # --- Build zones ---------------------------------------------------------
    def create_build_zone(self, payload, headers):
        return self._request("POST", "/build-zones", payload, headers)

    def get_build_zone(self, build_zone_id, headers):
        return self._request("GET", f"/build-zones/{build_zone_id}", headers=headers)

    def list_build_zones(self, headers, params=None):
        return self._request("GET", "/build-zones", headers=headers, params=params)

    def update_build_zone_threshold(self, build_zone_id, payload, headers):
        return self._request(
            "PATCH", f"/build-zones/{build_zone_id}/threshold", payload, headers
        )

    def extend_build_zone_deadline(self, build_zone_id, headers, payload=None):
        return self._request(
            "POST",
            f"/build-zones/{build_zone_id}/extend-deadline",
            payload or {},
            headers,
        )

    def start_construction(self, build_zone_id, headers, payload=None):
        return self._request(
            "POST",
            f"/build-zones/{build_zone_id}/construction-start",
            payload or {},
            headers,
        )

    def complete_construction(self, build_zone_id, headers, payload=None):
        return self._request(
            "POST",
            f"/build-zones/{build_zone_id}/construction-complete",
            payload or {},
            headers,
        )

    def set_build_zone_suspension(self, build_zone_id, payload, headers):
        return self._request(
            "POST", f"/build-zones/{build_zone_id}/suspension", payload, headers
        )

    # --- Service addresses ---------------------------------------------------
    def create_service_address(self, payload, headers):
        return self._request("POST", "/service-addresses", payload, headers)

    def get_service_address(self, service_address_id, headers):
        return self._request(
            "GET", f"/service-addresses/{service_address_id}", headers=headers
        )

    def list_service_addresses(self, headers, params=None):
        return self._request("GET", "/service-addresses", headers=headers, params=params)

    def determine_serviceability(self, service_address_id, payload, headers):
        return self._request(
            "POST",
            f"/service-addresses/{service_address_id}/serviceability-determination",
            payload,
            headers,
        )

    def unserved_exception(self, service_address_id, payload, headers):
        return self._request(
            "POST",
            f"/service-addresses/{service_address_id}/unserved-exception",
            payload,
            headers,
        )

    def create_fallback_offer(self, service_address_id, payload, headers):
        return self._request(
            "POST",
            f"/service-addresses/{service_address_id}/fallback-offers",
            payload,
            headers,
        )

    # --- Accounts ------------------------------------------------------------
    def create_account(self, payload, headers):
        return self._request("POST", "/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/accounts/{account_id}", headers=headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/accounts", headers=headers, params=params)

    # --- MDU owner agreements ------------------------------------------------
    def create_mdu_agreement(self, payload, headers):
        return self._request("POST", "/mdu-agreements", payload, headers)

    def get_mdu_agreement(self, agreement_id, headers):
        return self._request("GET", f"/mdu-agreements/{agreement_id}", headers=headers)

    def list_mdu_agreements(self, headers, params=None):
        return self._request("GET", "/mdu-agreements", headers=headers, params=params)

    def create_mdu_offer(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/mdu-agreements/{agreement_id}/offers", payload, headers
        )

    def mdu_owner_response(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/mdu-agreements/{agreement_id}/owner-response", payload, headers
        )

    # --- Permit applications -------------------------------------------------
    def create_permit_application(self, payload, headers):
        return self._request("POST", "/permit-applications", payload, headers)

    def get_permit_application(self, permit_application_id, headers):
        return self._request(
            "GET", f"/permit-applications/{permit_application_id}", headers=headers
        )

    def list_permit_applications(self, headers, params=None):
        return self._request(
            "GET", "/permit-applications", headers=headers, params=params
        )

    def submit_permit_application(self, permit_application_id, headers, payload=None):
        return self._request(
            "POST",
            f"/permit-applications/{permit_application_id}/submit",
            payload or {},
            headers,
        )

    def decide_permit_application(self, permit_application_id, payload, headers):
        return self._request(
            "POST",
            f"/permit-applications/{permit_application_id}/decision",
            payload,
            headers,
        )

    # --- Pole attachment requests --------------------------------------------
    def create_pole_attachment_request(self, payload, headers):
        return self._request("POST", "/pole-attachment-requests", payload, headers)

    def get_pole_attachment_request(self, pole_request_id, headers):
        return self._request(
            "GET", f"/pole-attachment-requests/{pole_request_id}", headers=headers
        )

    def list_pole_attachment_requests(self, headers, params=None):
        return self._request(
            "GET", "/pole-attachment-requests", headers=headers, params=params
        )

    def survey_pole_attachment_request(self, pole_request_id, payload, headers):
        return self._request(
            "POST", f"/pole-attachment-requests/{pole_request_id}/survey", payload, headers
        )

    def decide_pole_attachment_request(self, pole_request_id, payload, headers):
        return self._request(
            "POST",
            f"/pole-attachment-requests/{pole_request_id}/decision",
            payload,
            headers,
        )

    def attach_pole_attachment_request(self, pole_request_id, headers, payload=None):
        return self._request(
            "POST",
            f"/pole-attachment-requests/{pole_request_id}/attachment",
            payload or {},
            headers,
        )

    # --- Preorders -----------------------------------------------------------
    def create_preorder(self, payload, headers):
        return self._request("POST", "/preorders", payload, headers)

    def get_preorder(self, preorder_id, headers):
        return self._request("GET", f"/preorders/{preorder_id}", headers=headers)

    def list_preorders(self, headers, params=None):
        return self._request("GET", "/preorders", headers=headers, params=params)

    def cancel_preorder(self, preorder_id, headers, payload=None):
        return self._request(
            "POST", f"/preorders/{preorder_id}/cancel", payload or {}, headers
        )

    def convert_preorder(self, preorder_id, payload, headers):
        return self._request(
            "POST", f"/preorders/{preorder_id}/conversion", payload, headers
        )

    # --- Install crews -------------------------------------------------------
    def create_install_crew(self, payload, headers):
        return self._request("POST", "/install-crews", payload, headers)

    def get_install_crew(self, crew_id, headers):
        return self._request("GET", f"/install-crews/{crew_id}", headers=headers)

    def list_install_crews(self, headers, params=None):
        return self._request("GET", "/install-crews", headers=headers, params=params)

    # --- Install appointments ------------------------------------------------
    def create_install_appointment(self, payload, headers):
        return self._request("POST", "/install-appointments", payload, headers)

    def get_install_appointment(self, appointment_id, headers):
        return self._request(
            "GET", f"/install-appointments/{appointment_id}", headers=headers
        )

    def list_install_appointments(self, headers, params=None):
        return self._request(
            "GET", "/install-appointments", headers=headers, params=params
        )

    def record_appointment_outcome(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"/install-appointments/{appointment_id}/outcome", payload, headers
        )

    # --- Damage claims -------------------------------------------------------
    def create_damage_claim(self, payload, headers):
        return self._request("POST", "/damage-claims", payload, headers)

    def get_damage_claim(self, claim_id, headers):
        return self._request("GET", f"/damage-claims/{claim_id}", headers=headers)

    def list_damage_claims(self, headers, params=None):
        return self._request("GET", "/damage-claims", headers=headers, params=params)

    def assess_damage_claim(self, claim_id, headers, payload=None):
        return self._request(
            "POST", f"/damage-claims/{claim_id}/assessment", payload or {}, headers
        )

    def decide_damage_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/damage-claims/{claim_id}/decision", payload, headers
        )

    def appeal_damage_claim(self, claim_id, headers, payload=None):
        return self._request(
            "POST", f"/damage-claims/{claim_id}/appeal", payload or {}, headers
        )

    # --- Fallback options and offers -----------------------------------------
    def create_fallback_option(self, payload, headers):
        return self._request("POST", "/fallback-options", payload, headers)

    def get_fallback_option(self, option_id, headers):
        return self._request("GET", f"/fallback-options/{option_id}", headers=headers)

    def list_fallback_options(self, headers, params=None):
        return self._request("GET", "/fallback-options", headers=headers, params=params)

    def get_fallback_offer(self, offer_id, headers):
        return self._request("GET", f"/fallback-offers/{offer_id}", headers=headers)

    def list_fallback_offers(self, headers, params=None):
        return self._request("GET", "/fallback-offers", headers=headers, params=params)

    def respond_to_fallback_offer(self, offer_id, payload, headers):
        return self._request(
            "POST", f"/fallback-offers/{offer_id}/response", payload, headers
        )

    # --- Ledger entries ------------------------------------------------------
    def get_ledger_entry(self, entry_id, headers):
        return self._request("GET", f"/ledger-entries/{entry_id}", headers=headers)

    def list_ledger_entries(self, headers, params=None):
        return self._request("GET", "/ledger-entries", headers=headers, params=params)


api_client = ApiClient()
