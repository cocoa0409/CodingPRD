"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- logical clock --------------------------------------------------
    def set_clock(self, current_utc, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    # ---- campaigns ------------------------------------------------------
    def create_campaign(self, payload, headers):
        return self._request("POST", "/campaigns", payload, headers)

    def get_campaign(self, campaign_id, headers):
        return self._request("GET", f"/campaigns/{campaign_id}", headers=headers)

    def transition_campaign(self, campaign_id, payload, headers):
        return self._request(
            "POST", f"/campaigns/{campaign_id}/transition", payload, headers
        )

    # ---- pledges --------------------------------------------------------
    def create_pledge(self, payload, headers):
        return self._request("POST", "/pledges", payload, headers)

    def get_pledge(self, pledge_id, headers):
        return self._request("GET", f"/pledges/{pledge_id}", headers=headers)

    def list_pledges(self, headers, params=None):
        return self._request("GET", "/pledges", headers=headers, params=params)

    def transition_pledge(self, pledge_id, payload, headers):
        return self._request(
            "POST", f"/pledges/{pledge_id}/transition", payload, headers
        )

    # ---- manufacturing quotes -------------------------------------------
    def create_manufacturing_quote(self, payload, headers):
        return self._request("POST", "/manufacturing-quotes", payload, headers)

    def get_manufacturing_quote(self, quote_id, headers):
        return self._request(
            "GET", f"/manufacturing-quotes/{quote_id}", headers=headers
        )

    def list_manufacturing_quotes(self, headers, params=None):
        return self._request(
            "GET", "/manufacturing-quotes", headers=headers, params=params
        )

    def transition_manufacturing_quote(self, quote_id, payload, headers):
        return self._request(
            "POST", f"/manufacturing-quotes/{quote_id}/transition", payload, headers
        )

    # ---- production runs --------------------------------------------------
    def create_production_run(self, payload, headers):
        return self._request("POST", "/production-runs", payload, headers)

    def get_production_run(self, run_id, headers):
        return self._request("GET", f"/production-runs/{run_id}", headers=headers)

    def list_production_runs(self, headers, params=None):
        return self._request("GET", "/production-runs", headers=headers, params=params)

    def transition_production_run(self, run_id, payload, headers):
        return self._request(
            "POST", f"/production-runs/{run_id}/transition", payload, headers
        )

    # ---- freight shipments ------------------------------------------------
    def create_freight_shipment(self, payload, headers):
        return self._request("POST", "/freight-shipments", payload, headers)

    def get_freight_shipment(self, shipment_id, headers):
        return self._request(
            "GET", f"/freight-shipments/{shipment_id}", headers=headers
        )

    def list_freight_shipments(self, headers, params=None):
        return self._request(
            "GET", "/freight-shipments", headers=headers, params=params
        )

    def transition_freight_shipment(self, shipment_id, payload, headers):
        return self._request(
            "POST", f"/freight-shipments/{shipment_id}/transition", payload, headers
        )

    # ---- waves ------------------------------------------------------------
    def create_wave(self, payload, headers):
        return self._request("POST", "/waves", payload, headers)

    def get_wave(self, wave_id, headers):
        return self._request("GET", f"/waves/{wave_id}", headers=headers)

    def list_waves(self, headers, params=None):
        return self._request("GET", "/waves", headers=headers, params=params)

    def transition_wave(self, wave_id, payload, headers):
        return self._request("POST", f"/waves/{wave_id}/transition", payload, headers)

    # ---- distributor allocations ------------------------------------------
    def create_distributor_allocation(self, payload, headers):
        return self._request("POST", "/distributor-allocations", payload, headers)

    def get_distributor_allocation(self, allocation_id, headers):
        return self._request(
            "GET", f"/distributor-allocations/{allocation_id}", headers=headers
        )

    def list_distributor_allocations(self, headers, params=None):
        return self._request(
            "GET", "/distributor-allocations", headers=headers, params=params
        )

    def transition_distributor_allocation(self, allocation_id, payload, headers):
        return self._request(
            "POST",
            f"/distributor-allocations/{allocation_id}/transition",
            payload,
            headers,
        )

    # ---- replacement requests ---------------------------------------------
    def create_replacement_request(self, payload, headers):
        return self._request("POST", "/replacement-requests", payload, headers)

    def get_replacement_request(self, request_id, headers):
        return self._request(
            "GET", f"/replacement-requests/{request_id}", headers=headers
        )

    def list_replacement_requests(self, headers, params=None):
        return self._request(
            "GET", "/replacement-requests", headers=headers, params=params
        )

    def transition_replacement_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"/replacement-requests/{request_id}/transition", payload, headers
        )

    # ---- localization agreements ------------------------------------------
    def create_localization_agreement(self, payload, headers):
        return self._request("POST", "/localization-agreements", payload, headers)

    def get_localization_agreement(self, agreement_id, headers):
        return self._request(
            "GET", f"/localization-agreements/{agreement_id}", headers=headers
        )

    def list_localization_agreements(self, headers, params=None):
        return self._request(
            "GET", "/localization-agreements", headers=headers, params=params
        )

    def transition_localization_agreement(self, agreement_id, payload, headers):
        return self._request(
            "POST",
            f"/localization-agreements/{agreement_id}/transition",
            payload,
            headers,
        )

    # ---- reprint decisions --------------------------------------------------
    def create_reprint_decision(self, payload, headers):
        return self._request("POST", "/reprint-decisions", payload, headers)

    def get_reprint_decision(self, decision_id, headers):
        return self._request(
            "GET", f"/reprint-decisions/{decision_id}", headers=headers
        )

    def list_reprint_decisions(self, headers, params=None):
        return self._request(
            "GET", "/reprint-decisions", headers=headers, params=params
        )

    def transition_reprint_decision(self, decision_id, payload, headers):
        return self._request(
            "POST", f"/reprint-decisions/{decision_id}/transition", payload, headers
        )


api_client = ApiClient()
