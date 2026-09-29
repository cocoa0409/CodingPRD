"""API client: one method per endpoint defined in the PRD."""

from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Typed wrapper over the School Bus Manufacturing API surface."""

    # ---------------------------------------------------------------- clock
    def set_clock(self, current_utc: str, headers: dict):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    def set_clock_raw(self, payload: dict, headers: dict):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------- state spec profiles
    def create_state_spec_profile(self, payload: dict, headers: dict):
        return self._request("POST", "/state-spec-profiles", payload, headers)

    def list_state_spec_profiles(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/state-spec-profiles", headers=headers, params=params)

    def get_state_spec_profile(self, profile_id: str, headers: dict):
        return self._request("GET", f"/state-spec-profiles/{profile_id}", headers=headers)

    def publish_state_spec_profile(self, profile_id: str, headers: dict):
        return self._request(
            "POST", f"/state-spec-profiles/{profile_id}/publish", {}, headers
        )

    # ------------------------------------------------------------ bus models
    def create_bus_model(self, payload: dict, headers: dict):
        return self._request("POST", "/bus-models", payload, headers)

    def list_bus_models(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/bus-models", headers=headers, params=params)

    def get_bus_model(self, model_id: str, headers: dict):
        return self._request("GET", f"/bus-models/{model_id}", headers=headers)

    # -------------------------------------------------- propulsion packages
    def create_propulsion_package(self, payload: dict, headers: dict):
        return self._request("POST", "/propulsion-packages", payload, headers)

    def list_propulsion_packages(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/propulsion-packages", headers=headers, params=params)

    def get_propulsion_package(self, package_id: str, headers: dict):
        return self._request("GET", f"/propulsion-packages/{package_id}", headers=headers)

    # ------------------------------------------------------ production lines
    def create_production_line(self, payload: dict, headers: dict):
        return self._request("POST", "/production-lines", payload, headers)

    def list_production_lines(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/production-lines", headers=headers, params=params)

    def get_production_line(self, line_id: str, headers: dict):
        return self._request("GET", f"/production-lines/{line_id}", headers=headers)

    def set_production_line_status(self, line_id: str, status: str, headers: dict):
        return self._request(
            "POST", f"/production-lines/{line_id}/status", {"status": status}, headers
        )

    # ------------------------------------------------------------- test bays
    def create_test_bay(self, payload: dict, headers: dict):
        return self._request("POST", "/test-bays", payload, headers)

    def list_test_bays(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/test-bays", headers=headers, params=params)

    def get_test_bay(self, bay_id: str, headers: dict):
        return self._request("GET", f"/test-bays/{bay_id}", headers=headers)

    # --------------------------------------------------------------- dealers
    def create_dealer(self, payload: dict, headers: dict):
        return self._request("POST", "/dealers", payload, headers)

    def list_dealers(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/dealers", headers=headers, params=params)

    def get_dealer(self, dealer_id: str, headers: dict):
        return self._request("GET", f"/dealers/{dealer_id}", headers=headers)

    def create_legacy_fleet_record(self, dealer_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/dealers/{dealer_id}/legacy-fleet-records", payload, headers
        )

    # --------------------------------------------------------- solicitations
    def create_solicitation(self, payload: dict, headers: dict):
        return self._request("POST", "/solicitations", payload, headers)

    def list_solicitations(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/solicitations", headers=headers, params=params)

    def get_solicitation(self, solicitation_id: str, headers: dict):
        return self._request("GET", f"/solicitations/{solicitation_id}", headers=headers)

    def close_solicitation(self, solicitation_id: str, headers: dict):
        return self._request(
            "POST", f"/solicitations/{solicitation_id}/close", {}, headers
        )

    # ------------------------------------------------------------------ bids
    def create_bid(self, payload: dict, headers: dict):
        return self._request("POST", "/bids", payload, headers)

    def list_bids(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/bids", headers=headers, params=params)

    def get_bid(self, bid_id: str, headers: dict):
        return self._request("GET", f"/bids/{bid_id}", headers=headers)

    def create_bid_revision(self, bid_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/bids/{bid_id}/revisions", payload, headers)

    def list_bid_revisions(self, bid_id: str, headers: dict, params: Optional[dict] = None):
        return self._request(
            "GET", f"/bids/{bid_id}/revisions", headers=headers, params=params
        )

    def submit_bid(self, bid_id: str, headers: dict):
        return self._request("POST", f"/bids/{bid_id}/submit", {}, headers)

    def request_bid_revision(self, bid_id: str, headers: dict):
        return self._request("POST", f"/bids/{bid_id}/request-revision", {}, headers)

    def award_bid(self, bid_id: str, promised_delivery_date: str, headers: dict):
        return self._request(
            "POST",
            f"/bids/{bid_id}/award",
            {"promised_delivery_date": promised_delivery_date},
            headers,
        )

    def award_bid_raw(self, bid_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/bids/{bid_id}/award", payload, headers)

    # -------------------------------------------------------- contract orders
    def list_contract_orders(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/contract-orders", headers=headers, params=params)

    def get_contract_order(self, order_id: str, headers: dict):
        return self._request("GET", f"/contract-orders/{order_id}", headers=headers)

    def mint_bus_unit(self, order_id: str, vin: str, headers: dict):
        return self._request(
            "POST", f"/contract-orders/{order_id}/units", {"vin": vin}, headers
        )

    def mint_bus_unit_raw(self, order_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/contract-orders/{order_id}/units", payload, headers)

    # ------------------------------------------------------------- bus units
    def list_bus_units(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/bus-units", headers=headers, params=params)

    def get_bus_unit(self, unit_id: str, headers: dict):
        return self._request("GET", f"/bus-units/{unit_id}", headers=headers)

    def advance_build(self, unit_id: str, to_status: str, headers: dict):
        return self._request(
            "POST",
            f"/bus-units/{unit_id}/advance-build",
            {"to_status": to_status},
            headers,
        )

    def certify_bus_unit(self, unit_id: str, headers: dict):
        return self._request("POST", f"/bus-units/{unit_id}/certify", {}, headers)

    def waive_nonconformance(self, unit_id: str, waiver_justification: str, headers: dict):
        return self._request(
            "POST",
            f"/bus-units/{unit_id}/waive-nonconformance",
            {"waiver_justification": waiver_justification},
            headers,
        )

    def waive_nonconformance_raw(self, unit_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/bus-units/{unit_id}/waive-nonconformance", payload, headers
        )

    def assign_dealer(self, unit_id: str, dealer_id: str, headers: dict):
        return self._request(
            "POST",
            f"/bus-units/{unit_id}/assign-dealer",
            {"dealer_id": dealer_id},
            headers,
        )

    def complete_driver_training(self, unit_id: str, headers: dict):
        return self._request(
            "POST", f"/bus-units/{unit_id}/complete-driver-training", {}, headers
        )

    def deliver_bus_unit(self, unit_id: str, headers: dict):
        return self._request("POST", f"/bus-units/{unit_id}/deliver", {}, headers)

    # ----------------------------------------------------------- build slots
    def create_build_slot(self, payload: dict, headers: dict):
        return self._request("POST", "/build-slots", payload, headers)

    def list_build_slots(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/build-slots", headers=headers, params=params)

    def get_build_slot(self, slot_id: str, headers: dict):
        return self._request("GET", f"/build-slots/{slot_id}", headers=headers)

    def commit_build_slot(self, slot_id: str, headers: dict):
        return self._request("POST", f"/build-slots/{slot_id}/commit", {}, headers)

    def release_build_slot(self, slot_id: str, headers: dict):
        return self._request("POST", f"/build-slots/{slot_id}/release", {}, headers)

    # --------------------------------------------------------- quality tests
    def create_quality_test(self, payload: dict, headers: dict):
        return self._request("POST", "/quality-tests", payload, headers)

    def list_quality_tests(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/quality-tests", headers=headers, params=params)

    def get_quality_test(self, test_id: str, headers: dict):
        return self._request("GET", f"/quality-tests/{test_id}", headers=headers)

    def record_test_result(self, test_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/quality-tests/{test_id}/record-result", payload, headers
        )

    # ------------------------------------------------------ recall campaigns
    def create_recall_campaign(self, payload: dict, headers: dict):
        return self._request("POST", "/recall-campaigns", payload, headers)

    def list_recall_campaigns(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/recall-campaigns", headers=headers, params=params)

    def get_recall_campaign(self, campaign_id: str, headers: dict):
        return self._request("GET", f"/recall-campaigns/{campaign_id}", headers=headers)

    def launch_recall_campaign(self, campaign_id: str, headers: dict):
        return self._request(
            "POST", f"/recall-campaigns/{campaign_id}/launch", {}, headers
        )

    # ---------------------------------------------------------- remedy tasks
    def list_remedy_tasks(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/remedy-tasks", headers=headers, params=params)

    def get_remedy_task(self, task_id: str, headers: dict):
        return self._request("GET", f"/remedy-tasks/{task_id}", headers=headers)

    def start_remedy_task(self, task_id: str, headers: dict):
        return self._request("POST", f"/remedy-tasks/{task_id}/start", {}, headers)

    def complete_remedy_task(self, task_id: str, headers: dict):
        return self._request("POST", f"/remedy-tasks/{task_id}/complete", {}, headers)

    def cancel_remedy_task(self, task_id: str, headers: dict):
        return self._request("POST", f"/remedy-tasks/{task_id}/cancel", {}, headers)


api_client = ApiClient()
