"""API client: one method per endpoint declared in the PRD (§4).

`GenericApiClient` supplies `_request`, the session and the base URL. Every
business endpoint lives under the `/ebt` prefix. The single exception is the
test-driving logical clock: `POST /_clock/set_current_utc` is mounted OUTSIDE
`/ebt` (PRD §2.4), so `set_clock` below deliberately does not carry the prefix.

The module-level singleton is named `default_client` (NOT `api_client`) so that
`import test_helpers.api_client` always binds this module, never an instance.
"""
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (PRD §2.4 — mounted OUTSIDE /ebt) --------------------
    def set_clock(self, to_iso8601: str, headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --- State contracts (PRD §3.1) -----------------------------------------
    def create_contract(self, payload, headers):
        return self._request("POST", "/ebt/contracts", payload, headers)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/ebt/contracts/{contract_id}", headers=headers)

    def set_contract_status(self, contract_id, payload, headers):
        return self._request("POST", f"/ebt/contracts/{contract_id}/status", payload, headers)

    def list_contract_programs(self, contract_id, headers, params=None):
        return self._request("GET", f"/ebt/contracts/{contract_id}/programs", headers=headers, params=params)

    def run_allotment(self, contract_id, payload, headers):
        return self._request("POST", f"/ebt/contracts/{contract_id}/allotment-runs", payload, headers)

    def list_data_deliveries(self, contract_id, headers, params=None):
        return self._request("GET", f"/ebt/contracts/{contract_id}/data-deliveries", headers=headers, params=params)

    # --- Benefit programs (PRD §3.1) ----------------------------------------
    def create_program(self, payload, headers):
        return self._request("POST", "/ebt/programs", payload, headers)

    # --- Retailers and item files (PRD §3.2) --------------------------------
    def create_retailer(self, payload, headers):
        return self._request("POST", "/ebt/retailers", payload, headers)

    def get_retailer(self, retailer_id, headers):
        return self._request("GET", f"/ebt/retailers/{retailer_id}", headers=headers)

    def list_contract_retailers(self, contract_id, headers, params=None):
        return self._request("GET", f"/ebt/contracts/{contract_id}/retailers", headers=headers, params=params)

    def set_retailer_status(self, retailer_id, payload, headers):
        return self._request("POST", f"/ebt/retailers/{retailer_id}/status", payload, headers)

    def upload_item_file(self, retailer_id, payload, headers):
        return self._request("POST", f"/ebt/retailers/{retailer_id}/item-files", payload, headers)

    def list_retailer_items(self, retailer_id, headers, params=None):
        return self._request("GET", f"/ebt/retailers/{retailer_id}/items", headers=headers, params=params)

    # --- Point-of-sale authorizations (PRD §3.7) ----------------------------
    def create_authorization(self, retailer_id, payload, headers):
        return self._request("POST", f"/ebt/retailers/{retailer_id}/authorizations", payload, headers)

    def list_retailer_authorizations(self, retailer_id, headers, params=None):
        return self._request("GET", f"/ebt/retailers/{retailer_id}/authorizations", headers=headers, params=params)

    def void_authorization(self, txn_id, headers):
        return self._request("POST", f"/ebt/authorizations/{txn_id}/void", {}, headers)

    # --- Case accounts (PRD §3.3) -------------------------------------------
    def list_case_accounts(self, headers, params=None):
        return self._request("GET", "/ebt/case-accounts", headers=headers, params=params)

    def create_case_account(self, payload, headers):
        return self._request("POST", "/ebt/case-accounts", payload, headers)

    def get_case_account(self, case_id, headers):
        return self._request("GET", f"/ebt/case-accounts/{case_id}", headers=headers)

    def set_case_status(self, case_id, payload, headers):
        return self._request("POST", f"/ebt/case-accounts/{case_id}/status", payload, headers)

    def list_case_cards(self, case_id, headers, params=None):
        return self._request("GET", f"/ebt/case-accounts/{case_id}/cards", headers=headers, params=params)

    def list_case_claims(self, case_id, headers, params=None):
        return self._request("GET", f"/ebt/case-accounts/{case_id}/claims", headers=headers, params=params)

    # --- Purses, ledger, postings (PRD §3.3) --------------------------------
    def list_purses(self, headers, params=None):
        return self._request("GET", "/ebt/purses", headers=headers, params=params)

    def get_purse(self, purse_id, headers):
        return self._request("GET", f"/ebt/purses/{purse_id}", headers=headers)

    def list_purse_ledger(self, purse_id, headers, params=None):
        return self._request("GET", f"/ebt/purses/{purse_id}/ledger", headers=headers, params=params)

    def list_purse_postings(self, purse_id, headers, params=None):
        return self._request("GET", f"/ebt/purses/{purse_id}/postings", headers=headers, params=params)

    # --- Cards (PRD §3.6) ---------------------------------------------------
    def create_card(self, payload, headers):
        return self._request("POST", "/ebt/cards", payload, headers)

    def get_card(self, card_id, headers):
        return self._request("GET", f"/ebt/cards/{card_id}", headers=headers)

    def activate_card(self, card_id, payload, headers):
        return self._request("POST", f"/ebt/cards/{card_id}/activate", payload, headers)

    def replace_card(self, card_id, headers):
        return self._request("POST", f"/ebt/cards/{card_id}/replace", {}, headers)

    def reset_pin(self, card_id, payload, headers):
        return self._request("POST", f"/ebt/cards/{card_id}/pin-reset", payload, headers)

    # --- Skimming claims (PRD §3.8) -----------------------------------------
    def file_claim(self, payload, headers):
        return self._request("POST", "/ebt/claims", payload, headers)

    def set_claim_status(self, claim_id, payload, headers):
        return self._request("POST", f"/ebt/claims/{claim_id}/status", payload, headers)

    # --- Settlement, disputes, reconciliation (PRD §3.9) --------------------
    def list_settlement_batches(self, headers, params=None):
        return self._request("GET", "/ebt/settlement-batches", headers=headers, params=params)

    def get_settlement_batch(self, batch_id, headers):
        return self._request("GET", f"/ebt/settlement-batches/{batch_id}", headers=headers)

    def reconcile_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/ebt/settlement-batches/{batch_id}/reconcile", payload, headers)

    def file_dispute(self, payload, headers):
        return self._request("POST", "/ebt/disputes", payload, headers)

    def list_batch_disputes(self, batch_id, headers, params=None):
        return self._request("GET", f"/ebt/settlement-batches/{batch_id}/disputes", headers=headers, params=params)

    def set_dispute_status(self, dispute_id, payload, headers):
        return self._request("POST", f"/ebt/disputes/{dispute_id}/status", payload, headers)


# Singleton client. Tests obtain it through the test_suite conftest `api`
# fixture; fixtures.py composites accept any ApiClient instance as `api`.
default_client = ApiClient()
