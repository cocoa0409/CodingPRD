"""API client: one method per endpoint declared in the PRD endpoint table.

Every path is mounted under the /film-sales prefix.  GET methods take an
optional `params` dict for the pagination window and the declared filters.
"""

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/film-sales"


class ApiClient(GenericApiClient):
    # ---- convenience ----------------------------------------------------
    def patch(self, path, json=None, headers=None, **kwargs):
        return self._request("PATCH", path, payload=json, headers=headers)

    # ---- logical clock --------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc", payload, headers)

    # ---- films ----------------------------------------------------------
    def create_film(self, payload, headers):
        return self._request("POST", f"{PREFIX}/films", payload, headers)

    def list_films(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/films", params or {}, headers)

    def get_film(self, film_id, headers):
        return self._request("GET", f"{PREFIX}/films/{film_id}", headers=headers)

    def patch_film(self, film_id, payload, headers):
        return self._request("PATCH", f"{PREFIX}/films/{film_id}", payload, headers)

    def set_film_state(self, film_id, payload, headers):
        return self._request("POST", f"{PREFIX}/films/{film_id}/state", payload, headers)

    # ---- agency agreements ---------------------------------------------
    def create_agency_agreement(self, film_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/films/{film_id}/agency-agreements", payload, headers
        )

    def list_agency_agreements(self, film_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/films/{film_id}/agency-agreements", params or {}, headers
        )

    def set_agency_agreement_state(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/agency-agreements/{agreement_id}/state", payload, headers
        )

    def log_expense(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/agency-agreements/{agreement_id}/expenses", payload, headers
        )

    # ---- banking facilities --------------------------------------------
    def create_banking_facility(self, film_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/films/{film_id}/banking-facilities", payload, headers
        )

    def list_banking_facilities(self, film_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/films/{film_id}/banking-facilities", params or {}, headers
        )

    def set_facility_state(self, facility_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/banking-facilities/{facility_id}/state", payload, headers
        )

    def post_completion_bond(self, facility_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/banking-facilities/{facility_id}/completion-bond",
            payload,
            headers,
        )

    # ---- collection accounts -------------------------------------------
    def create_collection_account(self, film_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/films/{film_id}/collection-accounts", payload, headers
        )

    def list_collection_accounts(self, film_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/films/{film_id}/collection-accounts", params or {}, headers
        )

    def get_collection_account(self, account_id, headers):
        return self._request(
            "GET", f"{PREFIX}/collection-accounts/{account_id}", headers=headers
        )

    def set_account_state(self, account_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/collection-accounts/{account_id}/state", payload, headers
        )

    def create_waterfall_tier(self, account_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/collection-accounts/{account_id}/waterfall-tiers",
            payload,
            headers,
        )

    def list_waterfall_tiers(self, account_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/collection-accounts/{account_id}/waterfall-tiers",
            params or {},
            headers,
        )

    def distribute(self, account_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/collection-accounts/{account_id}/distribute", payload, headers
        )

    def list_distribution_runs(self, account_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/collection-accounts/{account_id}/distribution-runs",
            params or {},
            headers,
        )

    # ---- territories, comparables, buyers ------------------------------
    def create_territory(self, payload, headers):
        return self._request("POST", f"{PREFIX}/territories", payload, headers)

    def list_territories(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/territories", params or {}, headers)

    def get_territory(self, territory_id, headers):
        return self._request("GET", f"{PREFIX}/territories/{territory_id}", headers=headers)

    def create_comparable_title(self, territory_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/territories/{territory_id}/comparable-titles", payload, headers
        )

    def list_comparable_titles(self, territory_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/territories/{territory_id}/comparable-titles",
            params or {},
            headers,
        )

    def create_buyer(self, territory_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/territories/{territory_id}/buyers", payload, headers
        )

    def list_territory_buyers(self, territory_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/territories/{territory_id}/buyers", params or {}, headers
        )

    def get_buyer(self, buyer_id, headers):
        return self._request("GET", f"{PREFIX}/buyers/{buyer_id}", headers=headers)

    def patch_buyer(self, buyer_id, payload, headers):
        return self._request("PATCH", f"{PREFIX}/buyers/{buyer_id}", payload, headers)

    # ---- territory valuations ------------------------------------------
    def create_valuation(self, payload, headers):
        return self._request("POST", f"{PREFIX}/territory-valuations", payload, headers)

    def list_valuations(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/territory-valuations", params or {}, headers)

    def get_valuation(self, valuation_id, headers):
        return self._request(
            "GET", f"{PREFIX}/territory-valuations/{valuation_id}", headers=headers
        )

    def publish_valuation(self, valuation_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/territory-valuations/{valuation_id}/publish", payload, headers
        )

    # ---- markets --------------------------------------------------------
    def create_market(self, payload, headers):
        return self._request("POST", f"{PREFIX}/markets", payload, headers)

    def list_markets(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/markets", params or {}, headers)

    def get_market(self, market_id, headers):
        return self._request("GET", f"{PREFIX}/markets/{market_id}", headers=headers)

    def set_market_state(self, market_id, payload, headers):
        return self._request("POST", f"{PREFIX}/markets/{market_id}/state", payload, headers)

    # ---- screening slots ------------------------------------------------
    def create_screening_slot(self, payload, headers):
        return self._request("POST", f"{PREFIX}/screening-slots", payload, headers)

    def list_screening_slots(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/screening-slots", params or {}, headers)

    def get_screening_slot(self, slot_id, headers):
        return self._request("GET", f"{PREFIX}/screening-slots/{slot_id}", headers=headers)

    def set_screening_slot_state(self, slot_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/screening-slots/{slot_id}/state", payload, headers
        )

    # ---- buyer meetings -------------------------------------------------
    def create_buyer_meeting(self, payload, headers):
        return self._request("POST", f"{PREFIX}/buyer-meetings", payload, headers)

    def list_buyer_meetings(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/buyer-meetings", params or {}, headers)

    def get_buyer_meeting(self, meeting_id, headers):
        return self._request("GET", f"{PREFIX}/buyer-meetings/{meeting_id}", headers=headers)

    def set_buyer_meeting_state(self, meeting_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/buyer-meetings/{meeting_id}/state", payload, headers
        )

    # ---- pre-sale contracts ---------------------------------------------
    def create_contract(self, payload, headers):
        return self._request("POST", f"{PREFIX}/pre-sale-contracts", payload, headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/pre-sale-contracts", params or {}, headers)

    def get_contract(self, contract_id, headers):
        return self._request(
            "GET", f"{PREFIX}/pre-sale-contracts/{contract_id}", headers=headers
        )

    def counter_contract(self, contract_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/pre-sale-contracts/{contract_id}/counter", payload, headers
        )

    def revise_offer(self, contract_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/pre-sale-contracts/{contract_id}/revise-offer", payload, headers
        )

    def accept_contract(self, contract_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/pre-sale-contracts/{contract_id}/accept",
            payload if payload is not None else {},
            headers,
        )

    def execute_contract(self, contract_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/pre-sale-contracts/{contract_id}/execute",
            payload if payload is not None else {},
            headers,
        )

    def lapse_contract(self, contract_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/pre-sale-contracts/{contract_id}/lapse", payload, headers
        )

    def revert_contract(self, contract_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/pre-sale-contracts/{contract_id}/revert",
            payload if payload is not None else {},
            headers,
        )

    # ---- payment milestones ---------------------------------------------
    def create_milestone(self, contract_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/pre-sale-contracts/{contract_id}/payment-milestones",
            payload,
            headers,
        )

    def list_milestones(self, contract_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/pre-sale-contracts/{contract_id}/payment-milestones",
            params or {},
            headers,
        )

    def post_receipt(self, milestone_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/payment-milestones/{milestone_id}/receipt", payload, headers
        )

    def reverse_receipt(self, milestone_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/payment-milestones/{milestone_id}/reverse-receipt",
            payload,
            headers,
        )

    # ---- deliverable packages -------------------------------------------
    def create_deliverable_package(self, contract_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/pre-sale-contracts/{contract_id}/deliverable-packages",
            payload,
            headers,
        )

    def list_deliverable_packages(self, contract_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/pre-sale-contracts/{contract_id}/deliverable-packages",
            params or {},
            headers,
        )

    def post_qc_result(self, package_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/deliverable-packages/{package_id}/qc-result", payload, headers
        )


api_client = ApiClient()
