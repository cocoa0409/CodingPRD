"""API client: one method per endpoint defined in PRD §4.

Every resource endpoint lives under the /network prefix. The single exception
is the logical-clock test driver, POST /_clock/set_current_utc, which is a
platform endpoint mounted OUTSIDE /network (PRD §2.4) — it must not be
reachable under /network, so this client sends it unprefixed.

All write methods take a full payload dict (built by factories.py) so tests can
also send deliberately malformed bodies (missing fields, extra fields, bad
enums). All methods return the raw requests.Response for status assertions.
"""

from prd_bench_local_runner.testing import GenericApiClient

NETWORK = "/network"


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Platform: logical clock (UNPREFIXED — PRD §2.4)
    # ------------------------------------------------------------------
    def set_clock(self, payload, headers):
        """POST /_clock/set_current_utc — payload {"to_iso8601": <iso>}.

        Accepts a plain ISO string for convenience and wraps it.
        """
        if isinstance(payload, str):
            payload = {"to_iso8601": payload}
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # Participants
    # ------------------------------------------------------------------
    def create_participant(self, payload, headers):
        return self._request("POST", f"{NETWORK}/participants", payload, headers)

    def get_participant(self, participant_id, headers):
        return self._request("GET", f"{NETWORK}/participants/{participant_id}", headers=headers)

    def list_participants(self, headers, params=None):
        return self._request("GET", f"{NETWORK}/participants", headers=headers, params=params)

    def transition_participant(self, participant_id, payload, headers):
        return self._request(
            "POST", f"{NETWORK}/participants/{participant_id}/transition", payload, headers
        )

    def list_participant_returns(self, participant_id, headers, params=None):
        return self._request(
            "GET", f"{NETWORK}/participants/{participant_id}/returns", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Originators
    # ------------------------------------------------------------------
    def create_originator(self, payload, headers):
        return self._request("POST", f"{NETWORK}/originators", payload, headers)

    def get_originator(self, originator_id, headers):
        return self._request("GET", f"{NETWORK}/originators/{originator_id}", headers=headers)

    def list_originators(self, headers, params=None):
        return self._request("GET", f"{NETWORK}/originators", headers=headers, params=params)

    def transition_originator(self, originator_id, payload, headers):
        return self._request(
            "POST", f"{NETWORK}/originators/{originator_id}/transition", payload, headers
        )

    def update_exposure_limit(self, originator_id, payload, headers):
        return self._request(
            "PATCH", f"{NETWORK}/originators/{originator_id}/exposure-limit", payload, headers
        )

    # ------------------------------------------------------------------
    # Transaction codes
    # ------------------------------------------------------------------
    def create_transaction_code(self, payload, headers):
        return self._request("POST", f"{NETWORK}/transaction-codes", payload, headers)

    def get_transaction_code(self, transaction_code_id, headers):
        return self._request(
            "GET", f"{NETWORK}/transaction-codes/{transaction_code_id}", headers=headers
        )

    def list_transaction_codes(self, headers, params=None):
        return self._request("GET", f"{NETWORK}/transaction-codes", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Rule proposals and ballots
    # ------------------------------------------------------------------
    def create_rule_proposal(self, payload, headers):
        return self._request("POST", f"{NETWORK}/rule-proposals", payload, headers)

    def get_rule_proposal(self, rule_proposal_id, headers):
        return self._request(
            "GET", f"{NETWORK}/rule-proposals/{rule_proposal_id}", headers=headers
        )

    def list_rule_proposals(self, headers, params=None):
        return self._request("GET", f"{NETWORK}/rule-proposals", headers=headers, params=params)

    def transition_rule_proposal(self, rule_proposal_id, payload, headers):
        return self._request(
            "POST", f"{NETWORK}/rule-proposals/{rule_proposal_id}/transition", payload, headers
        )

    def close_ballot(self, rule_proposal_id, headers):
        return self._request(
            "POST", f"{NETWORK}/rule-proposals/{rule_proposal_id}/close-ballot", {}, headers
        )

    def cast_ballot(self, rule_proposal_id, payload, headers):
        return self._request(
            "POST", f"{NETWORK}/rule-proposals/{rule_proposal_id}/ballots", payload, headers
        )

    def recast_ballot(self, ballot_id, payload, headers):
        return self._request("PATCH", f"{NETWORK}/ballots/{ballot_id}", payload, headers)

    def get_ballot(self, ballot_id, headers):
        return self._request("GET", f"{NETWORK}/ballots/{ballot_id}", headers=headers)

    def list_ballots(self, headers, params=None):
        return self._request("GET", f"{NETWORK}/ballots", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Guidance documents
    # ------------------------------------------------------------------
    def create_guidance_document(self, payload, headers):
        return self._request("POST", f"{NETWORK}/guidance-documents", payload, headers)

    def get_guidance_document(self, guidance_document_id, headers):
        return self._request(
            "GET", f"{NETWORK}/guidance-documents/{guidance_document_id}", headers=headers
        )

    def list_guidance_documents(self, headers, params=None):
        return self._request("GET", f"{NETWORK}/guidance-documents", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Settlement windows and the settlement run
    # ------------------------------------------------------------------
    def create_settlement_window(self, payload, headers):
        return self._request("POST", f"{NETWORK}/settlement-windows", payload, headers)

    def list_settlement_windows(self, headers, params=None):
        return self._request("GET", f"{NETWORK}/settlement-windows", headers=headers, params=params)

    def run_settlement(self, settlement_window_id, headers):
        return self._request(
            "POST", f"{NETWORK}/settlement-windows/{settlement_window_id}/run-settlement", {}, headers
        )

    # ------------------------------------------------------------------
    # Payment entries and returns
    # ------------------------------------------------------------------
    def create_payment_entry(self, payload, headers):
        return self._request("POST", f"{NETWORK}/payment-entries", payload, headers)

    def get_payment_entry(self, payment_entry_id, headers):
        return self._request(
            "GET", f"{NETWORK}/payment-entries/{payment_entry_id}", headers=headers
        )

    def list_payment_entries(self, headers, params=None):
        return self._request("GET", f"{NETWORK}/payment-entries", headers=headers, params=params)

    def cancel_payment_entry(self, payment_entry_id, headers):
        return self._request(
            "POST", f"{NETWORK}/payment-entries/{payment_entry_id}/cancel", {}, headers
        )

    def create_return(self, payment_entry_id, payload, headers):
        return self._request(
            "POST", f"{NETWORK}/payment-entries/{payment_entry_id}/returns", payload, headers
        )

    def list_entry_returns(self, payment_entry_id, headers, params=None):
        return self._request(
            "GET",
            f"{NETWORK}/payment-entries/{payment_entry_id}/returns",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Account validations
    # ------------------------------------------------------------------
    def create_account_validation(self, payload, headers):
        return self._request("POST", f"{NETWORK}/account-validations", payload, headers)

    def get_account_validation(self, account_validation_id, headers):
        return self._request(
            "GET", f"{NETWORK}/account-validations/{account_validation_id}", headers=headers
        )

    def list_account_validations(self, headers, params=None):
        return self._request(
            "GET", f"{NETWORK}/account-validations", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Return-rate snapshots
    # ------------------------------------------------------------------
    def create_return_rate_snapshot(self, payload, headers):
        return self._request("POST", f"{NETWORK}/return-rate-snapshots", payload, headers)

    def get_return_rate_snapshot(self, snapshot_id, headers):
        return self._request(
            "GET", f"{NETWORK}/return-rate-snapshots/{snapshot_id}", headers=headers
        )

    def list_return_rate_snapshots(self, headers, params=None):
        return self._request(
            "GET", f"{NETWORK}/return-rate-snapshots", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Inquiry cases
    # ------------------------------------------------------------------
    def get_inquiry_case(self, inquiry_case_id, headers):
        return self._request("GET", f"{NETWORK}/inquiry-cases/{inquiry_case_id}", headers=headers)

    def list_inquiry_cases(self, headers, params=None):
        return self._request("GET", f"{NETWORK}/inquiry-cases", headers=headers, params=params)

    def respond_inquiry(self, inquiry_case_id, payload, headers):
        return self._request(
            "POST", f"{NETWORK}/inquiry-cases/{inquiry_case_id}/respond", payload, headers
        )

    def resolve_inquiry(self, inquiry_case_id, headers):
        return self._request(
            "POST", f"{NETWORK}/inquiry-cases/{inquiry_case_id}/resolve", {}, headers
        )

    def escalate_inquiry(self, inquiry_case_id, headers):
        return self._request(
            "POST", f"{NETWORK}/inquiry-cases/{inquiry_case_id}/escalate", {}, headers
        )

    # ------------------------------------------------------------------
    # Enforcement actions
    # ------------------------------------------------------------------
    def create_enforcement_action(self, payload, headers):
        return self._request("POST", f"{NETWORK}/enforcement-actions", payload, headers)

    def get_enforcement_action(self, enforcement_action_id, headers):
        return self._request(
            "GET", f"{NETWORK}/enforcement-actions/{enforcement_action_id}", headers=headers
        )

    def list_enforcement_actions(self, headers, params=None):
        return self._request(
            "GET", f"{NETWORK}/enforcement-actions", headers=headers, params=params
        )

    def transition_enforcement_action(self, enforcement_action_id, payload, headers):
        return self._request(
            "POST",
            f"{NETWORK}/enforcement-actions/{enforcement_action_id}/transition",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Compliance attestations
    # ------------------------------------------------------------------
    def create_attestation(self, payload, headers):
        return self._request("POST", f"{NETWORK}/attestations", payload, headers)

    def get_attestation(self, attestation_id, headers):
        return self._request("GET", f"{NETWORK}/attestations/{attestation_id}", headers=headers)

    def list_attestations(self, headers, params=None):
        return self._request("GET", f"{NETWORK}/attestations", headers=headers, params=params)

    def transition_attestation(self, attestation_id, payload, headers):
        return self._request(
            "POST", f"{NETWORK}/attestations/{attestation_id}/transition", payload, headers
        )

    # ------------------------------------------------------------------
    # Audit reports
    # ------------------------------------------------------------------
    def create_audit(self, payload, headers):
        return self._request("POST", f"{NETWORK}/audits", payload, headers)

    def get_audit(self, audit_id, headers):
        return self._request("GET", f"{NETWORK}/audits/{audit_id}", headers=headers)

    def list_audits(self, headers, params=None):
        return self._request("GET", f"{NETWORK}/audits", headers=headers, params=params)

    def transition_audit(self, audit_id, payload, headers):
        return self._request(
            "POST", f"{NETWORK}/audits/{audit_id}/transition", payload, headers
        )


# Shared client instance. NOTE: intentionally NOT re-exported from
# test_helpers/__init__.py under the module name "api_client" — that would
# shadow the api_client submodule on `import test_helpers.api_client`.
default_client = ApiClient()
