"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- test-driving / ops endpoints ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/tax/_clock/set_current_utc",
            payload={"to_iso8601": to_iso8601}, headers=headers,
        )

    def filing_callback(self, filing_attempt_id, outcome, headers, rejection_code=None):
        payload = {"filing_attempt_id": filing_attempt_id, "outcome": outcome}
        if rejection_code is not None:
            payload["rejection_code"] = rejection_code
        return self._request("POST", "/tax/_authority/filing-callback", payload, headers)

    def seed_tier(self, payload, headers):
        return self._request("POST", "/tax/_tiers/seed", payload, headers)

    def seed_form(self, payload, headers):
        return self._request("POST", "/tax/_forms/seed", payload, headers)

    def suspend_account(self, account_id, headers):
        return self._request("POST", f"/tax/accounts/{account_id}/suspend", headers=headers)

    # --- accounts ---
    def create_account(self, payload, headers):
        return self._request("POST", "/tax/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/tax/accounts/{account_id}", headers=headers)

    # --- catalog reads ---
    def list_tiers(self, headers, params=None):
        return self._request("GET", "/tax/tiers", headers=headers, params=params)

    def list_form_specs(self, headers, params=None):
        return self._request("GET", "/tax/form-specs", headers=headers, params=params)

    # --- prior-year snapshots ---
    def create_snapshot(self, account_id, payload, headers):
        return self._request(
            "POST", f"/tax/accounts/{account_id}/prior-year-snapshots", payload, headers
        )

    def list_snapshots(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/tax/accounts/{account_id}/prior-year-snapshots",
            headers=headers, params=params,
        )

    def get_snapshot(self, account_id, snapshot_id, headers):
        return self._request(
            "GET",
            f"/tax/accounts/{account_id}/prior-year-snapshots/{snapshot_id}",
            headers=headers,
        )

    def import_snapshot(self, account_id, snapshot_id, return_id, expected_return_version, headers):
        payload = {
            "return_id": return_id,
            "expected_return_version": expected_return_version,
        }
        return self._request(
            "POST",
            f"/tax/accounts/{account_id}/prior-year-snapshots/{snapshot_id}/import",
            payload,
            headers,
        )

    # --- returns ---
    def create_return(self, account_id, payload, headers):
        return self._request("POST", f"/tax/accounts/{account_id}/returns", payload, headers)

    def list_returns(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/tax/accounts/{account_id}/returns", headers=headers, params=params
        )

    def get_return(self, return_id, headers):
        return self._request("GET", f"/tax/returns/{return_id}", headers=headers)

    def select_tier(self, return_id, target_tier, expected_return_version, headers):
        payload = {
            "target_tier": target_tier,
            "expected_return_version": expected_return_version,
        }
        return self._request("POST", f"/tax/returns/{return_id}/select-tier", payload, headers)

    def add_form(self, return_id, form_code, amount_cents, expected_return_version, headers):
        payload = {
            "form_code": form_code,
            "amount_cents": amount_cents,
            "expected_return_version": expected_return_version,
        }
        return self._request("POST", f"/tax/returns/{return_id}/forms", payload, headers)

    def list_forms(self, return_id, headers, params=None):
        return self._request(
            "GET", f"/tax/returns/{return_id}/forms", headers=headers, params=params
        )

    def remove_form(self, return_id, form_id, expected_return_version, headers):
        payload = {"expected_return_version": expected_return_version}
        return self._request(
            "POST", f"/tax/returns/{return_id}/forms/{form_id}/remove", payload, headers
        )

    def submit_review(self, return_id, expected_return_version, headers):
        payload = {"expected_return_version": expected_return_version}
        return self._request("POST", f"/tax/returns/{return_id}/submit-review", payload, headers)

    def reopen_return(self, return_id, expected_return_version, headers):
        payload = {"expected_return_version": expected_return_version}
        return self._request("POST", f"/tax/returns/{return_id}/reopen", payload, headers)

    def file_return(self, return_id, transmission_payload_hash, expected_return_version, headers):
        payload = {
            "transmission_payload_hash": transmission_payload_hash,
            "expected_return_version": expected_return_version,
        }
        return self._request("POST", f"/tax/returns/{return_id}/file", payload, headers)

    def amend_return(self, return_id, expected_return_version, headers):
        payload = {"expected_return_version": expected_return_version}
        return self._request("POST", f"/tax/returns/{return_id}/amend", payload, headers)

    def list_filing_attempts(self, return_id, headers, params=None):
        return self._request(
            "GET", f"/tax/returns/{return_id}/filing-attempts",
            headers=headers, params=params,
        )

    # --- upgrade prompts ---
    def list_upgrade_prompts(self, return_id, headers, params=None):
        return self._request(
            "GET", f"/tax/returns/{return_id}/upgrade-prompts",
            headers=headers, params=params,
        )

    def acknowledge_prompt(self, return_id, prompt_id, expected_return_version, headers):
        payload = {"expected_return_version": expected_return_version}
        return self._request(
            "POST",
            f"/tax/returns/{return_id}/upgrade-prompts/{prompt_id}/acknowledge",
            payload,
            headers,
        )

    def decline_prompt(self, return_id, prompt_id, expected_return_version, headers):
        payload = {"expected_return_version": expected_return_version}
        return self._request(
            "POST",
            f"/tax/returns/{return_id}/upgrade-prompts/{prompt_id}/decline",
            payload,
            headers,
        )

    # --- state returns ---
    def add_state_return(self, return_id, payload, headers):
        return self._request("POST", f"/tax/returns/{return_id}/state-returns", payload, headers)

    def list_state_returns(self, return_id, headers, params=None):
        return self._request(
            "GET", f"/tax/returns/{return_id}/state-returns",
            headers=headers, params=params,
        )

    def ready_state_return(self, return_id, state_return_id, expected_return_version, headers):
        payload = {"expected_return_version": expected_return_version}
        return self._request(
            "POST",
            f"/tax/returns/{return_id}/state-returns/{state_return_id}/ready",
            payload,
            headers,
        )

    def remove_state_return(self, return_id, state_return_id, expected_return_version, headers):
        payload = {"expected_return_version": expected_return_version}
        return self._request(
            "POST",
            f"/tax/returns/{return_id}/state-returns/{state_return_id}/remove",
            payload,
            headers,
        )

    # --- refund transfer ---
    def create_refund_transfer(self, return_id, bank_partner_code, expected_return_version, headers):
        payload = {
            "bank_partner_code": bank_partner_code,
            "expected_return_version": expected_return_version,
        }
        return self._request("POST", f"/tax/returns/{return_id}/refund-transfer", payload, headers)

    def list_refund_transfers(self, return_id, headers, params=None):
        return self._request(
            "GET", f"/tax/returns/{return_id}/refund-transfer",
            headers=headers, params=params,
        )

    def accept_disclosure(self, return_id, expected_return_version, headers):
        payload = {"expected_return_version": expected_return_version}
        return self._request(
            "POST", f"/tax/returns/{return_id}/refund-transfer/accept-disclosure",
            payload, headers,
        )

    def void_refund_transfer(self, return_id, expected_return_version, headers):
        payload = {"expected_return_version": expected_return_version}
        return self._request(
            "POST", f"/tax/returns/{return_id}/refund-transfer/void", payload, headers
        )

    # --- accuracy claims ---
    def create_claim(self, return_id, claimed_error_amount_cents, headers):
        payload = {"claimed_error_amount_cents": claimed_error_amount_cents}
        return self._request("POST", f"/tax/returns/{return_id}/claims", payload, headers)

    def list_claims(self, return_id, headers, params=None):
        return self._request(
            "GET", f"/tax/returns/{return_id}/claims", headers=headers, params=params
        )

    def start_claim_review(self, claim_id, headers):
        return self._request("POST", f"/tax/claims/{claim_id}/start-review", headers=headers)

    def adjudicate_claim(self, claim_id, reviewed_error_amount_cents, headers):
        payload = {"reviewed_error_amount_cents": reviewed_error_amount_cents}
        return self._request("POST", f"/tax/claims/{claim_id}/adjudicate", payload, headers)

    def reopen_claim_review(self, claim_id, headers):
        return self._request("POST", f"/tax/claims/{claim_id}/reopen-review", headers=headers)

    def pay_claim(self, claim_id, headers):
        return self._request("POST", f"/tax/claims/{claim_id}/pay", headers=headers)


api_client = ApiClient()
