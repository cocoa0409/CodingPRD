"""API client: one method per endpoint defined in the PRD.

Every resource is mounted under the /lending prefix.
"""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/lending"


class ApiClient(GenericApiClient):
    # --- Logical clock ----------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # --- Dealers ----------------------------------------------------------
    def create_dealer(self, payload, headers):
        return self._request("POST", f"{PREFIX}/dealers", payload, headers)

    def get_dealer(self, dealer_id, headers):
        return self._request("GET", f"{PREFIX}/dealers/{dealer_id}", headers=headers)

    def dealer_status_action(self, dealer_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/dealers/{dealer_id}/status", payload, headers,
        )

    def create_reserve_adjustment(self, dealer_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/dealers/{dealer_id}/reserve-adjustments", payload, headers,
        )

    def create_scorecard(self, dealer_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/dealers/{dealer_id}/scorecards", payload, headers,
        )

    def list_dealer_scorecards(self, dealer_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/dealers/{dealer_id}/scorecards", headers=headers, params=params,
        )

    def finalize_scorecard(self, scorecard_id, headers):
        return self._request(
            "POST", f"{PREFIX}/scorecards/{scorecard_id}/finalize", {}, headers,
        )

    # --- Dealer agreements ------------------------------------------------
    def create_agreement(self, payload, headers):
        return self._request("POST", f"{PREFIX}/dealer-agreements", payload, headers)

    def get_agreement(self, agreement_id, headers):
        return self._request(
            "GET", f"{PREFIX}/dealer-agreements/{agreement_id}", headers=headers,
        )

    def list_agreements(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/dealer-agreements", headers=headers, params=params,
        )

    def countersign_agreement(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/dealer-agreements/{agreement_id}/countersign", payload, headers,
        )

    # --- Rate sheets ------------------------------------------------------
    def create_rate_sheet(self, payload, headers):
        return self._request("POST", f"{PREFIX}/rate-sheets", payload, headers)

    def create_tier(self, rate_sheet_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/rate-sheets/{rate_sheet_id}/tiers", payload, headers,
        )

    def list_tiers(self, rate_sheet_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/rate-sheets/{rate_sheet_id}/tiers", headers=headers, params=params,
        )

    def get_rate_sheet(self, rate_sheet_id, headers):
        return self._request(
            "GET", f"{PREFIX}/rate-sheets/{rate_sheet_id}", headers=headers,
        )

    def publish_rate_sheet(self, rate_sheet_id, headers):
        return self._request(
            "POST", f"{PREFIX}/rate-sheets/{rate_sheet_id}/publish", {}, headers,
        )

    # --- Credit applications ----------------------------------------------
    def create_application(self, payload, headers):
        return self._request("POST", f"{PREFIX}/applications", payload, headers)

    def get_application(self, application_id, headers):
        return self._request(
            "GET", f"{PREFIX}/applications/{application_id}", headers=headers,
        )

    def list_applications(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/applications", headers=headers, params=params,
        )

    def decision_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/applications/{application_id}/decision", payload, headers,
        )

    def resubmit_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/applications/{application_id}/resubmit", payload, headers,
        )

    # --- Retail contracts -------------------------------------------------
    def create_contract(self, payload, headers):
        return self._request("POST", f"{PREFIX}/contracts", payload, headers)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"{PREFIX}/contracts/{contract_id}", headers=headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/contracts", headers=headers, params=params)

    def upload_document(self, contract_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/contracts/{contract_id}/documents", payload, headers,
        )

    def list_contract_documents(self, contract_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/contracts/{contract_id}/documents", headers=headers, params=params,
        )

    def verify_document(self, document_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/documents/{document_id}/verify", payload, headers,
        )

    def fund_contract(self, contract_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/contracts/{contract_id}/fund", payload, headers,
        )

    def create_chargeback_event(self, contract_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/contracts/{contract_id}/chargeback-events", payload, headers,
        )

    def list_chargeback_events(self, contract_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/contracts/{contract_id}/chargeback-events",
            headers=headers, params=params,
        )

    # --- Reserve ledger ---------------------------------------------------
    def list_reserve_entries(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/reserve-entries", headers=headers, params=params,
        )

    def get_reserve_entry(self, entry_id, headers):
        return self._request(
            "GET", f"{PREFIX}/reserve-entries/{entry_id}", headers=headers,
        )

    # --- Repurchase demands -----------------------------------------------
    def create_buyback_demand(self, payload, headers):
        return self._request("POST", f"{PREFIX}/buyback-demands", payload, headers)

    def get_buyback_demand(self, demand_id, headers):
        return self._request(
            "GET", f"{PREFIX}/buyback-demands/{demand_id}", headers=headers,
        )

    def list_buyback_demands(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/buyback-demands", headers=headers, params=params,
        )

    def buyback_demand_action(self, demand_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/buyback-demands/{demand_id}/actions", payload, headers,
        )

    # --- Fair lending reviews ---------------------------------------------
    def create_fair_lending_review(self, payload, headers):
        return self._request("POST", f"{PREFIX}/fair-lending-reviews", payload, headers)

    def get_fair_lending_review(self, review_id, headers):
        return self._request(
            "GET", f"{PREFIX}/fair-lending-reviews/{review_id}", headers=headers,
        )

    def list_fair_lending_reviews(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/fair-lending-reviews", headers=headers, params=params,
        )

    def transition_fair_lending_review(self, review_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/fair-lending-reviews/{review_id}/transition", payload, headers,
        )

    # --- Raw path helper (used for not-found probes) -----------------------
    def get_path(self, path, headers, params=None):
        return self._request("GET", f"{PREFIX}{path}", headers=headers, params=params)


api_client = ApiClient()
