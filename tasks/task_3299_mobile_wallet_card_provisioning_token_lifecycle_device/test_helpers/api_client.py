"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- logical clock ---------------------------------------------------
    def set_clock(self, current_utc, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    # ---- cardholders ------------------------------------------------------
    def create_cardholder(self, payload, headers=None):
        return self._request("POST", "/cardholders", payload, headers)

    def get_cardholder(self, cardholder_id, headers=None):
        return self._request("GET", f"/cardholders/{cardholder_id}", headers=headers)

    # ---- devices ----------------------------------------------------------
    def create_device(self, payload, headers):
        return self._request("POST", "/devices", payload, headers)

    def get_device(self, device_id, headers=None):
        return self._request("GET", f"/devices/{device_id}", headers=headers)

    def list_cardholder_devices(self, cardholder_id, headers=None, params=None):
        return self._request(
            "GET", f"/cardholders/{cardholder_id}/devices", headers=headers, params=params
        )

    def set_device_security(self, device_id, payload, headers):
        return self._request(
            "POST", f"/devices/{device_id}/set-security", payload, headers
        )

    def report_device_lost(self, device_id, headers):
        return self._request("POST", f"/devices/{device_id}/report_lost", {}, headers)

    def report_device_found(self, device_id, headers):
        return self._request("POST", f"/devices/{device_id}/report_found", {}, headers)

    # ---- issuers / agreements ---------------------------------------------
    def create_issuer(self, payload, headers):
        return self._request("POST", "/issuers", payload, headers)

    def get_issuer(self, issuer_id, headers=None):
        return self._request("GET", f"/issuers/{issuer_id}", headers=headers)

    def activate_issuer(self, issuer_id, headers):
        return self._request("POST", f"/issuers/{issuer_id}/activate", {}, headers)

    def suspend_issuer(self, issuer_id, headers):
        return self._request("POST", f"/issuers/{issuer_id}/suspend", {}, headers)

    def offboard_issuer(self, issuer_id, headers):
        return self._request("POST", f"/issuers/{issuer_id}/offboard", {}, headers)

    def get_fee_projection(self, issuer_id, headers):
        return self._request(
            "GET", f"/issuers/{issuer_id}/fee-projection", headers=headers
        )

    def create_agreement(self, payload, headers):
        return self._request("POST", "/issuer-agreements", payload, headers)

    def get_agreement(self, agreement_id, headers=None):
        return self._request(
            "GET", f"/issuer-agreements/{agreement_id}", headers=headers
        )

    def list_issuer_agreements(self, issuer_id, headers=None, params=None):
        return self._request(
            "GET", f"/issuers/{issuer_id}/agreements", headers=headers, params=params
        )

    def activate_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"/issuer-agreements/{agreement_id}/activate", {}, headers
        )

    def supersede_agreement(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/issuer-agreements/{agreement_id}/supersede", payload, headers
        )

    def terminate_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"/issuer-agreements/{agreement_id}/terminate", {}, headers
        )

    # ---- card accounts / artifacts ----------------------------------------
    def create_card_account(self, payload, headers):
        return self._request("POST", "/card-accounts", payload, headers)

    def get_card_account(self, account_id, headers=None):
        return self._request("GET", f"/card-accounts/{account_id}", headers=headers)

    def list_card_accounts(self, headers=None, params=None):
        return self._request("GET", "/card-accounts", headers=headers, params=params)

    def reissue_card_account(self, account_id, headers):
        return self._request("POST", f"/card-accounts/{account_id}/reissue", {}, headers)

    def close_card_account(self, account_id, headers):
        return self._request("POST", f"/card-accounts/{account_id}/close", {}, headers)

    def get_account_risk(self, account_id, headers):
        return self._request("GET", f"/card-accounts/{account_id}/risk", headers=headers)

    def create_card_artifact(self, payload, headers):
        return self._request("POST", "/card-artifacts", payload, headers)

    def get_card_artifact(self, artifact_id, headers=None):
        return self._request("GET", f"/card-artifacts/{artifact_id}", headers=headers)

    def list_card_artifacts(self, headers=None, params=None):
        return self._request("GET", "/card-artifacts", headers=headers, params=params)

    def list_account_artifacts(self, account_id, headers=None, params=None):
        return self._request(
            "GET", f"/card-accounts/{account_id}/artifacts", headers=headers, params=params
        )

    def suspend_artifact(self, artifact_id, headers):
        return self._request("POST", f"/card-artifacts/{artifact_id}/suspend", {}, headers)

    def resume_artifact(self, artifact_id, headers):
        return self._request("POST", f"/card-artifacts/{artifact_id}/resume", {}, headers)

    def deactivate_artifact(self, artifact_id, headers):
        return self._request(
            "POST", f"/card-artifacts/{artifact_id}/deactivate", {}, headers
        )

    # ---- provisioning ------------------------------------------------------
    def create_provisioning_session(self, device_id, payload, headers):
        return self._request(
            "POST", f"/devices/{device_id}/provisioning-sessions", payload, headers
        )

    def list_device_sessions(self, device_id, headers=None, params=None):
        return self._request(
            "GET",
            f"/devices/{device_id}/provisioning-sessions",
            headers=headers,
            params=params,
        )

    def list_provisioning_sessions(self, headers=None, params=None):
        return self._request(
            "GET", "/provisioning-sessions", headers=headers, params=params
        )

    def get_provisioning_session(self, session_id, headers=None):
        return self._request(
            "GET", f"/provisioning-sessions/{session_id}", headers=headers
        )

    def verify_session(self, device_id, session_id, payload, headers):
        return self._request(
            "POST",
            f"/devices/{device_id}/provisioning-sessions/{session_id}/verify",
            payload,
            headers,
        )

    def tokenize_session(self, device_id, session_id, payload, headers):
        return self._request(
            "POST",
            f"/devices/{device_id}/provisioning-sessions/{session_id}/tokenize",
            payload,
            headers,
        )

    # ---- tokens -------------------------------------------------------------
    def list_device_tokens(self, device_id, headers=None, params=None):
        return self._request(
            "GET", f"/devices/{device_id}/tokens", headers=headers, params=params
        )

    def get_payment_token(self, token_id, headers=None):
        return self._request("GET", f"/payment-tokens/{token_id}", headers=headers)

    def list_payment_tokens(self, headers=None, params=None):
        return self._request("GET", "/payment-tokens", headers=headers, params=params)

    def suspend_token(self, device_id, token_id, headers):
        return self._request(
            "POST", f"/devices/{device_id}/tokens/{token_id}/suspend", {}, headers
        )

    def resume_token(self, device_id, token_id, headers):
        return self._request(
            "POST", f"/devices/{device_id}/tokens/{token_id}/resume", {}, headers
        )

    def deactivate_token(self, device_id, token_id, headers):
        return self._request(
            "POST", f"/devices/{device_id}/tokens/{token_id}/deactivate", {}, headers
        )

    def set_default_card(self, device_id, payload, headers):
        return self._request(
            "POST", f"/devices/{device_id}/default-card", payload, headers
        )

    def list_token_events(self, token_id, headers=None, params=None):
        return self._request(
            "GET", f"/payment-tokens/{token_id}/events", headers=headers, params=params
        )

    def list_token_event_stream(self, headers=None, params=None):
        return self._request("GET", "/token-events", headers=headers, params=params)

    # ---- authorizations ------------------------------------------------------
    def authorize(self, token_id, payload, headers):
        return self._request(
            "POST", f"/payment-tokens/{token_id}/authorizations", payload, headers
        )

    def list_token_authorizations(self, token_id, headers=None, params=None):
        return self._request(
            "GET",
            f"/payment-tokens/{token_id}/authorizations",
            headers=headers,
            params=params,
        )

    def list_authorizations(self, headers=None, params=None):
        return self._request("GET", "/authorizations", headers=headers, params=params)

    # ---- disputes -------------------------------------------------------------
    def open_dispute(self, authorization_id, payload, headers):
        return self._request(
            "POST", f"/authorizations/{authorization_id}/disputes", payload, headers
        )

    def get_dispute(self, dispute_id, headers=None):
        return self._request("GET", f"/disputes/{dispute_id}", headers=headers)

    def list_token_disputes(self, token_id, headers=None, params=None):
        return self._request(
            "GET", f"/payment-tokens/{token_id}/disputes", headers=headers, params=params
        )

    def list_disputes(self, headers=None, params=None):
        return self._request("GET", "/disputes", headers=headers, params=params)

    def resolve_dispute(self, dispute_id, payload, headers):
        return self._request(
            "POST", f"/disputes/{dispute_id}/resolve-dispute", payload, headers
        )

    # ---- merchant programs ------------------------------------------------------
    def create_merchant_program(self, payload, headers):
        return self._request("POST", "/merchant-programs", payload, headers)

    def get_merchant_program(self, program_id, headers=None):
        return self._request("GET", f"/merchant-programs/{program_id}", headers=headers)

    def list_merchant_programs(self, headers=None, params=None):
        return self._request("GET", "/merchant-programs", headers=headers, params=params)

    def enroll_merchant_card_program(self, payload, headers):
        return self._request("POST", "/merchant-card-programs", payload, headers)

    def get_merchant_card_program(self, enrollment_id, headers=None):
        return self._request(
            "GET", f"/merchant-card-programs/{enrollment_id}", headers=headers
        )

    def list_merchant_card_programs(self, headers=None, params=None):
        return self._request(
            "GET", "/merchant-card-programs", headers=headers, params=params
        )

    def list_account_enrollments(self, account_id, headers=None, params=None):
        return self._request(
            "GET",
            f"/card-accounts/{account_id}/merchant-enrollments",
            headers=headers,
            params=params,
        )

    def list_program_enrollments(self, program_id, headers=None, params=None):
        return self._request(
            "GET",
            f"/merchant-programs/{program_id}/enrollments",
            headers=headers,
            params=params,
        )

    # ---- transit ------------------------------------------------------------------
    def create_transit_operator(self, payload, headers):
        return self._request("POST", "/transit-operators", payload, headers)

    def get_transit_operator(self, operator_id, headers=None):
        return self._request("GET", f"/transit-operators/{operator_id}", headers=headers)

    def add_transit_allowlist(self, payload, headers):
        return self._request("POST", "/transit-allowlist", payload, headers)

    def get_transit_allowlist_entry(self, entry_id, headers=None):
        return self._request("GET", f"/transit-allowlist/{entry_id}", headers=headers)

    def list_operator_allowlist(self, operator_id, headers=None, params=None):
        return self._request(
            "GET",
            f"/transit-operators/{operator_id}/allowlist",
            headers=headers,
            params=params,
        )

    def list_account_allowlist(self, account_id, headers=None, params=None):
        return self._request(
            "GET",
            f"/card-accounts/{account_id}/transit-allowlist",
            headers=headers,
            params=params,
        )

    def list_transit_allowlist(self, headers=None, params=None):
        return self._request("GET", "/transit-allowlist", headers=headers, params=params)


api_client = ApiClient()
