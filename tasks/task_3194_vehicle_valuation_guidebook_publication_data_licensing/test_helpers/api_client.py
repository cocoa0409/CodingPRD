"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Clock (test-driving) ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # --- Regions ---
    def create_region(self, payload, headers):
        return self._request("POST", "/regions", payload, headers)

    def list_regions(self, headers, params=None):
        return self._request("GET", "/regions", headers=headers, params=params)

    def get_region(self, region_id, headers):
        return self._request("GET", f"/regions/{region_id}", headers=headers)

    def patch_region(self, region_id, payload, headers):
        return self._request("PATCH", f"/regions/{region_id}", payload, headers)

    # --- Sources ---
    def create_source(self, payload, headers):
        return self._request("POST", "/sources", payload, headers)

    def list_sources(self, headers, params=None):
        return self._request("GET", "/sources", headers=headers, params=params)

    def get_source(self, source_id, headers):
        return self._request("GET", f"/sources/{source_id}", headers=headers)

    def activate_source(self, source_id, headers):
        return self._request("POST", f"/sources/{source_id}/activate", {}, headers)

    def reinstate_source(self, source_id, headers):
        return self._request("POST", f"/sources/{source_id}/reinstate", {}, headers)

    # --- Configurations ---
    def create_configuration(self, payload, headers):
        return self._request("POST", "/configurations", payload, headers)

    def list_configurations(self, headers, params=None):
        return self._request("GET", "/configurations", headers=headers, params=params)

    def get_configuration(self, configuration_id, headers):
        return self._request("GET", f"/configurations/{configuration_id}", headers=headers)

    def patch_configuration(self, configuration_id, payload, headers):
        return self._request("PATCH", f"/configurations/{configuration_id}", payload, headers)

    # --- Option packages ---
    def create_option_package(self, payload, headers):
        return self._request("POST", "/option-packages", payload, headers)

    def list_option_packages(self, headers, params=None):
        return self._request("GET", "/option-packages", headers=headers, params=params)

    def create_configuration_option_package(self, configuration_id, payload, headers):
        return self._request(
            "POST", f"/configurations/{configuration_id}/option-packages",
            payload, headers,
        )

    def list_configuration_option_packages(self, configuration_id, headers, params=None):
        return self._request(
            "GET", f"/configurations/{configuration_id}/option-packages",
            headers=headers, params=params,
        )

    # --- Batches ---
    def create_batch(self, payload, headers):
        return self._request("POST", "/batches", payload, headers)

    def list_batches(self, headers, params=None):
        return self._request("GET", "/batches", headers=headers, params=params)

    def get_batch(self, batch_id, headers):
        return self._request("GET", f"/batches/{batch_id}", headers=headers)

    def validate_batch(self, batch_id, headers):
        return self._request("POST", f"/batches/{batch_id}/validate", {}, headers)

    def accept_batch(self, batch_id, headers):
        return self._request("POST", f"/batches/{batch_id}/accept", {}, headers)

    def reject_batch(self, batch_id, headers):
        return self._request("POST", f"/batches/{batch_id}/reject", {}, headers)

    def list_batch_corrections(self, batch_id, headers, params=None):
        return self._request(
            "GET", f"/batches/{batch_id}/corrections", headers=headers, params=params,
        )

    # --- Corrections ---
    def create_correction(self, payload, headers):
        return self._request("POST", "/corrections", payload, headers)

    # --- Valuation series ---
    def create_valuation_series(self, payload, headers):
        return self._request("POST", "/valuation-series", payload, headers)

    def list_valuation_series(self, headers, params=None):
        return self._request("GET", "/valuation-series", headers=headers, params=params)

    def get_valuation_series(self, series_id, headers):
        return self._request("GET", f"/valuation-series/{series_id}", headers=headers)

    def activate_valuation_series(self, series_id, headers):
        return self._request("POST", f"/valuation-series/{series_id}/activate", {}, headers)

    # --- Valuation editions ---
    def create_valuation_edition(self, payload, headers):
        return self._request("POST", "/valuation-editions", payload, headers)

    def list_valuation_editions(self, headers, params=None):
        return self._request("GET", "/valuation-editions", headers=headers, params=params)

    def get_valuation_edition(self, edition_id, headers, params=None):
        return self._request(
            "GET", f"/valuation-editions/{edition_id}", headers=headers, params=params,
        )

    def publish_valuation_edition(self, edition_id, headers):
        return self._request("POST", f"/valuation-editions/{edition_id}/publish", {}, headers)

    def withdraw_valuation_edition(self, edition_id, headers):
        return self._request("POST", f"/valuation-editions/{edition_id}/withdraw", {}, headers)

    # --- Market shifts ---
    def create_market_shift(self, payload, headers):
        return self._request("POST", "/market-shifts", payload, headers)

    def list_market_shifts(self, headers, params=None):
        return self._request("GET", "/market-shifts", headers=headers, params=params)

    def list_region_market_shifts(self, region_id, headers, params=None):
        return self._request(
            "GET", f"/regions/{region_id}/market-shifts", headers=headers, params=params,
        )

    def activate_market_shift(self, shift_id, headers):
        return self._request("POST", f"/market-shifts/{shift_id}/activate", {}, headers)

    def rescind_market_shift(self, shift_id, headers):
        return self._request("POST", f"/market-shifts/{shift_id}/rescind", {}, headers)

    # --- Consumer profiles ---
    def create_consumer_profile(self, payload, headers):
        return self._request("POST", "/consumer-profiles", payload, headers)

    def list_consumer_profiles(self, headers, params=None):
        return self._request("GET", "/consumer-profiles", headers=headers, params=params)

    def get_consumer_profile(self, profile_id, headers):
        return self._request("GET", f"/consumer-profiles/{profile_id}", headers=headers)

    # --- Cash offers ---
    def create_cash_offer(self, payload, headers):
        return self._request("POST", "/cash-offers", payload, headers)

    def list_cash_offers(self, headers, params=None):
        return self._request("GET", "/cash-offers", headers=headers, params=params)

    def get_cash_offer(self, offer_id, headers):
        return self._request("GET", f"/cash-offers/{offer_id}", headers=headers)

    def list_offer_disputes(self, offer_id, headers, params=None):
        return self._request(
            "GET", f"/cash-offers/{offer_id}/disputes", headers=headers, params=params,
        )

    def inspect_cash_offer(self, offer_id, payload, headers):
        return self._request("POST", f"/cash-offers/{offer_id}/inspect", payload, headers)

    def redeem_cash_offer(self, offer_id, headers):
        return self._request("POST", f"/cash-offers/{offer_id}/redeem", {}, headers)

    def void_cash_offer(self, offer_id, headers):
        return self._request("POST", f"/cash-offers/{offer_id}/void", {}, headers)

    # --- License agreements ---
    def create_license_agreement(self, payload, headers):
        return self._request("POST", "/license-agreements", payload, headers)

    def list_license_agreements(self, headers, params=None):
        return self._request("GET", "/license-agreements", headers=headers, params=params)

    def get_license_agreement(self, agreement_id, headers):
        return self._request("GET", f"/license-agreements/{agreement_id}", headers=headers)

    def patch_license_agreement(self, agreement_id, payload, headers):
        return self._request("PATCH", f"/license-agreements/{agreement_id}", payload, headers)

    def activate_license_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"/license-agreements/{agreement_id}/activate", {}, headers,
        )

    def suspend_license_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"/license-agreements/{agreement_id}/suspend", {}, headers,
        )

    def reactivate_license_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"/license-agreements/{agreement_id}/reactivate", {}, headers,
        )

    def terminate_license_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"/license-agreements/{agreement_id}/terminate", {}, headers,
        )

    def list_agreement_events(self, agreement_id, headers, params=None):
        return self._request(
            "GET", f"/license-agreements/{agreement_id}/events",
            headers=headers, params=params,
        )

    def list_agreement_snapshots(self, agreement_id, headers, params=None):
        return self._request(
            "GET", f"/license-agreements/{agreement_id}/snapshots",
            headers=headers, params=params,
        )

    # --- Methodologies ---
    def create_methodology(self, payload, headers):
        return self._request("POST", "/methodologies", payload, headers)

    def list_methodologies(self, headers, params=None):
        return self._request("GET", "/methodologies", headers=headers, params=params)

    def publish_methodology(self, methodology_id, headers):
        return self._request("POST", f"/methodologies/{methodology_id}/publish", {}, headers)

    # --- Condition standards ---
    def create_condition_standard(self, payload, headers):
        return self._request("POST", "/condition-standards", payload, headers)

    def list_condition_standards(self, headers, params=None):
        return self._request("GET", "/condition-standards", headers=headers, params=params)

    # --- Disputes ---
    def create_dispute(self, payload, headers):
        return self._request("POST", "/disputes", payload, headers)

    def list_disputes(self, headers, params=None):
        return self._request("GET", "/disputes", headers=headers, params=params)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/disputes/{dispute_id}", headers=headers)

    def resolve_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/disputes/{dispute_id}/resolve", payload, headers)

    def withdraw_dispute(self, dispute_id, headers):
        return self._request("POST", f"/disputes/{dispute_id}/withdraw", {}, headers)


api_client = ApiClient()
