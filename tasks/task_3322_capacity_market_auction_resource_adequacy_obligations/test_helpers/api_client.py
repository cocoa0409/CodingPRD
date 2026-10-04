"""API client: one method per endpoint defined in the PRD (§4 index)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/capacity-market/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # --- delivery years ---
    def create_delivery_year(self, payload, headers):
        return self._request("POST", "/capacity-market/delivery-years", payload, headers)

    def list_delivery_years(self, headers, params=None):
        return self._request("GET", "/capacity-market/delivery-years", headers=headers, params=params)

    def get_delivery_year(self, dy_id, headers):
        return self._request("GET", f"/capacity-market/delivery-years/{dy_id}", headers=headers)

    def lock_forecast(self, dy_id, headers):
        return self._request("POST", f"/capacity-market/delivery-years/{dy_id}/lock-forecast", {}, headers)

    def settle_delivery_year(self, dy_id, headers):
        return self._request("POST", f"/capacity-market/delivery-years/{dy_id}/settle", {}, headers)

    def close_delivery_year(self, dy_id, headers):
        return self._request("POST", f"/capacity-market/delivery-years/{dy_id}/close", {}, headers)

    # --- zones ---
    def create_zone(self, dy_id, payload, headers):
        return self._request("POST", f"/capacity-market/delivery-years/{dy_id}/zones", payload, headers)

    def list_zones_of_delivery_year(self, dy_id, headers, params=None):
        return self._request("GET", f"/capacity-market/delivery-years/{dy_id}/zones", headers=headers, params=params)

    def list_zones(self, headers, params=None):
        return self._request("GET", "/capacity-market/zones", headers=headers, params=params)

    def get_zone(self, zone_id, headers):
        return self._request("GET", f"/capacity-market/zones/{zone_id}", headers=headers)

    # --- forecasts ---
    def create_forecast(self, dy_id, payload, headers):
        return self._request("POST", f"/capacity-market/delivery-years/{dy_id}/forecasts", payload, headers)

    def list_forecasts(self, dy_id, headers, params=None):
        return self._request("GET", f"/capacity-market/delivery-years/{dy_id}/forecasts", headers=headers, params=params)

    # --- owners ---
    def create_owner(self, payload, headers):
        return self._request("POST", "/capacity-market/owners", payload, headers)

    def get_owner(self, owner_id, headers):
        return self._request("GET", f"/capacity-market/owners/{owner_id}", headers=headers)

    def suspend_owner(self, owner_id, headers):
        return self._request("POST", f"/capacity-market/owners/{owner_id}/suspend", {}, headers)

    # --- resources ---
    def create_resource(self, payload, headers):
        return self._request("POST", "/capacity-market/resources", payload, headers)

    def list_resources(self, headers, params=None):
        return self._request("GET", "/capacity-market/resources", headers=headers, params=params)

    def get_resource(self, resource_id, headers):
        return self._request("GET", f"/capacity-market/resources/{resource_id}", headers=headers)

    def retire_resource(self, resource_id, headers):
        return self._request("POST", f"/capacity-market/resources/{resource_id}/retire", {}, headers)

    # --- accreditations ---
    def create_accreditation(self, payload, headers):
        return self._request("POST", "/capacity-market/accreditations", payload, headers)

    def list_accreditations(self, headers, params=None):
        return self._request("GET", "/capacity-market/accreditations", headers=headers, params=params)

    def get_accreditation(self, acc_id, headers):
        return self._request("GET", f"/capacity-market/accreditations/{acc_id}", headers=headers)

    def approve_accreditation(self, acc_id, headers):
        return self._request("POST", f"/capacity-market/accreditations/{acc_id}/approve", {}, headers)

    def reject_accreditation(self, acc_id, headers):
        return self._request("POST", f"/capacity-market/accreditations/{acc_id}/reject", {}, headers)

    # --- auction runs ---
    def create_auction_run(self, payload, headers):
        return self._request("POST", "/capacity-market/auction-runs", payload, headers)

    def list_auction_runs(self, headers, params=None):
        return self._request("GET", "/capacity-market/auction-runs", headers=headers, params=params)

    def get_auction_run(self, run_id, headers):
        return self._request("GET", f"/capacity-market/auction-runs/{run_id}", headers=headers)

    def open_auction_run(self, run_id, headers):
        return self._request("POST", f"/capacity-market/auction-runs/{run_id}/open", {}, headers)

    def seal_auction_run(self, run_id, headers):
        return self._request("POST", f"/capacity-market/auction-runs/{run_id}/seal", {}, headers)

    def clear_auction_run(self, run_id, headers):
        return self._request("POST", f"/capacity-market/auction-runs/{run_id}/clear", {}, headers)

    # --- offers ---
    def create_offer(self, payload, headers):
        return self._request("POST", "/capacity-market/offers", payload, headers)

    def list_offers(self, headers, params=None):
        return self._request("GET", "/capacity-market/offers", headers=headers, params=params)

    def get_offer(self, offer_id, headers):
        return self._request("GET", f"/capacity-market/offers/{offer_id}", headers=headers)

    def withdraw_offer(self, offer_id, expected_auction_run_version, headers):
        return self._request(
            "POST", f"/capacity-market/offers/{offer_id}/withdraw",
            {"expected_auction_run_version": expected_auction_run_version}, headers,
        )

    # --- mitigation reviews ---
    def list_mitigation_reviews(self, headers, params=None):
        return self._request("GET", "/capacity-market/mitigation-reviews", headers=headers, params=params)

    def get_offer_mitigation_review(self, offer_id, headers):
        return self._request("GET", f"/capacity-market/offers/{offer_id}/mitigation-review", headers=headers)

    def resolve_mitigation_review(self, review_id, payload, headers):
        return self._request("POST", f"/capacity-market/mitigation-reviews/{review_id}/resolve", payload, headers)

    # --- commitments ---
    def list_commitments(self, headers, params=None):
        return self._request("GET", "/capacity-market/commitments", headers=headers, params=params)

    def get_commitment(self, commitment_id, headers):
        return self._request("GET", f"/capacity-market/commitments/{commitment_id}", headers=headers)

    def default_commitment(self, commitment_id, headers):
        return self._request("POST", f"/capacity-market/commitments/{commitment_id}/default", {}, headers)

    # --- replacement transactions ---
    def create_replacement_transaction(self, payload, headers):
        return self._request("POST", "/capacity-market/replacement-transactions", payload, headers)

    def list_replacement_transactions(self, headers, params=None):
        return self._request("GET", "/capacity-market/replacement-transactions", headers=headers, params=params)

    def get_replacement_transaction(self, rt_id, headers):
        return self._request("GET", f"/capacity-market/replacement-transactions/{rt_id}", headers=headers)

    def approve_replacement(self, rt_id, headers):
        return self._request("POST", f"/capacity-market/replacement-transactions/{rt_id}/approve", {}, headers)

    def reject_replacement(self, rt_id, headers):
        return self._request("POST", f"/capacity-market/replacement-transactions/{rt_id}/reject", {}, headers)

    # --- emergency events / assessments ---
    def create_emergency_event(self, payload, headers):
        return self._request("POST", "/capacity-market/emergency-events", payload, headers)

    def list_emergency_events(self, headers, params=None):
        return self._request("GET", "/capacity-market/emergency-events", headers=headers, params=params)

    def get_emergency_event(self, ev_id, headers):
        return self._request("GET", f"/capacity-market/emergency-events/{ev_id}", headers=headers)

    def begin_assessment(self, ev_id, headers):
        return self._request("POST", f"/capacity-market/emergency-events/{ev_id}/begin-assessment", {}, headers)

    def list_event_assessments(self, ev_id, headers, params=None):
        return self._request("GET", f"/capacity-market/emergency-events/{ev_id}/assessments", headers=headers, params=params)

    def list_assessments(self, headers, params=None):
        return self._request("GET", "/capacity-market/assessments", headers=headers, params=params)

    def get_assessment(self, a_id, headers):
        return self._request("GET", f"/capacity-market/assessments/{a_id}", headers=headers)

    def record_actual(self, a_id, expected_mw, actual_mw, headers):
        return self._request(
            "POST", f"/capacity-market/assessments/{a_id}/record-actual",
            {"expected_mw": expected_mw, "actual_mw": actual_mw}, headers,
        )

    def finalize_assessments(self, ev_id, headers):
        return self._request("POST", f"/capacity-market/emergency-events/{ev_id}/finalize-assessments", {}, headers)

    # --- measurement reports ---
    def create_measurement_report(self, payload, headers):
        return self._request("POST", "/capacity-market/measurement-reports", payload, headers)

    def list_measurement_reports(self, headers, params=None):
        return self._request("GET", "/capacity-market/measurement-reports", headers=headers, params=params)

    def get_measurement_report(self, mr_id, headers):
        return self._request("GET", f"/capacity-market/measurement-reports/{mr_id}", headers=headers)

    def start_measurement_review(self, mr_id, headers):
        return self._request("POST", f"/capacity-market/measurement-reports/{mr_id}/start-review", {}, headers)

    def verify_measurement_report(self, mr_id, headers):
        return self._request("POST", f"/capacity-market/measurement-reports/{mr_id}/verify", {}, headers)

    def reject_measurement_report(self, mr_id, headers):
        return self._request("POST", f"/capacity-market/measurement-reports/{mr_id}/reject", {}, headers)

    # --- settlement entries ---
    def list_settlement_entries(self, headers, params=None):
        return self._request("GET", "/capacity-market/settlement-entries", headers=headers, params=params)

    def get_settlement_entry(self, se_id, headers):
        return self._request("GET", f"/capacity-market/settlement-entries/{se_id}", headers=headers)


api_client = ApiClient()
