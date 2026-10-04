"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- identity actors ---
    def create_owner_rep(self, payload, headers):
        return self._request("POST", "/owner-reps", payload, headers)

    def get_owner_rep(self, owner_rep_id, headers):
        return self._request("GET", f"/owner-reps/{owner_rep_id}", headers=headers)

    def get_attested_reports(self, owner_rep_id, headers, params=None):
        return self._request(
            "GET", f"/owner-reps/{owner_rep_id}/attested-reports",
            headers=headers, params=params,
        )

    def create_esco_engineer(self, payload, headers):
        return self._request("POST", "/esco-engineers", payload, headers)

    def get_esco_engineer(self, engineer_id, headers):
        return self._request("GET", f"/esco-engineers/{engineer_id}", headers=headers)

    # --- PerformanceContract ---
    def create_contract(self, payload, headers):
        return self._request("POST", "/performance-contracts", payload, headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/performance-contracts", headers=headers, params=params)

    def get_contract(self, contract_id, headers):
        return self._request(
            "GET", f"/performance-contracts/{contract_id}", headers=headers
        )

    def complete_audit(self, contract_id, headers):
        return self._request(
            "POST", f"/performance-contracts/{contract_id}/complete-audit",
            {}, headers,
        )

    def execute_contract(self, contract_id, headers):
        return self._request(
            "POST", f"/performance-contracts/{contract_id}/execute", {}, headers
        )

    def mobilize_contract(self, contract_id, headers):
        return self._request(
            "POST", f"/performance-contracts/{contract_id}/mobilize", {}, headers
        )

    def commence_performance(self, contract_id, headers):
        return self._request(
            "POST", f"/performance-contracts/{contract_id}/commence-performance",
            {}, headers,
        )

    def close_contract(self, contract_id, headers):
        return self._request(
            "POST", f"/performance-contracts/{contract_id}/close", {}, headers
        )

    def terminate_contract(self, contract_id, headers):
        return self._request(
            "POST", f"/performance-contracts/{contract_id}/terminate", {}, headers
        )

    # --- Baseline ---
    def create_baseline(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/performance-contracts/{contract_id}/baselines",
            payload, headers,
        )

    def list_baselines(self, contract_id, headers, params=None):
        return self._request(
            "GET", f"/performance-contracts/{contract_id}/baselines",
            headers=headers, params=params,
        )

    def get_baseline(self, contract_id, baseline_id, headers):
        return self._request(
            "GET",
            f"/performance-contracts/{contract_id}/baselines/{baseline_id}",
            headers=headers,
        )

    def submit_baseline(self, contract_id, baseline_id, headers):
        return self._request(
            "POST",
            f"/performance-contracts/{contract_id}/baselines/{baseline_id}/submit",
            {}, headers,
        )

    def approve_baseline(self, contract_id, baseline_id, headers):
        return self._request(
            "POST",
            f"/performance-contracts/{contract_id}/baselines/{baseline_id}/approve",
            {}, headers,
        )

    def reject_baseline(self, contract_id, baseline_id, headers):
        return self._request(
            "POST",
            f"/performance-contracts/{contract_id}/baselines/{baseline_id}/reject",
            {}, headers,
        )

    # --- MeasureBundle ---
    def create_bundle(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/performance-contracts/{contract_id}/bundles",
            payload, headers,
        )

    def list_bundles(self, contract_id, headers, params=None):
        return self._request(
            "GET", f"/performance-contracts/{contract_id}/bundles",
            headers=headers, params=params,
        )

    def get_bundle(self, contract_id, bundle_id, headers):
        return self._request(
            "GET",
            f"/performance-contracts/{contract_id}/bundles/{bundle_id}",
            headers=headers,
        )

    def propose_bundle(self, contract_id, bundle_id, headers):
        return self._request(
            "POST",
            f"/performance-contracts/{contract_id}/bundles/{bundle_id}/propose",
            {}, headers,
        )

    def approve_bundle(self, contract_id, bundle_id, headers):
        return self._request(
            "POST",
            f"/performance-contracts/{contract_id}/bundles/{bundle_id}/approve",
            {}, headers,
        )

    def withdraw_bundle(self, contract_id, bundle_id, headers):
        return self._request(
            "POST",
            f"/performance-contracts/{contract_id}/bundles/{bundle_id}/withdraw",
            {}, headers,
        )

    # --- Measure ---
    def create_measure(self, contract_id, bundle_id, payload, headers):
        return self._request(
            "POST",
            f"/performance-contracts/{contract_id}/bundles/{bundle_id}/measures",
            payload, headers,
        )

    def list_measures(self, contract_id, bundle_id, headers, params=None):
        return self._request(
            "GET",
            f"/performance-contracts/{contract_id}/bundles/{bundle_id}/measures",
            headers=headers, params=params,
        )

    def get_measure(self, contract_id, bundle_id, measure_id, headers):
        return self._request(
            "GET",
            f"/performance-contracts/{contract_id}/bundles/{bundle_id}/measures/{measure_id}",
            headers=headers,
        )

    def list_contract_measures(self, contract_id, headers, params=None):
        return self._request(
            "GET", f"/performance-contracts/{contract_id}/measures",
            headers=headers, params=params,
        )

    def exclude_measure(self, contract_id, bundle_id, measure_id, headers):
        return self._request(
            "POST",
            f"/performance-contracts/{contract_id}/bundles/{bundle_id}/measures/{measure_id}/exclude",
            {}, headers,
        )

    def install_measure(self, contract_id, bundle_id, measure_id, headers):
        return self._request(
            "POST",
            f"/performance-contracts/{contract_id}/bundles/{bundle_id}/measures/{measure_id}/install",
            {}, headers,
        )

    def verify_measure(self, contract_id, bundle_id, measure_id, headers):
        return self._request(
            "POST",
            f"/performance-contracts/{contract_id}/bundles/{bundle_id}/measures/{measure_id}/verify",
            {}, headers,
        )

    # --- FinancingFacility ---
    def create_facility(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/performance-contracts/{contract_id}/financing-facilities",
            payload, headers,
        )

    def list_facilities(self, contract_id, headers, params=None):
        return self._request(
            "GET", f"/performance-contracts/{contract_id}/financing-facilities",
            headers=headers, params=params,
        )

    def get_facility(self, contract_id, facility_id, headers):
        return self._request(
            "GET",
            f"/performance-contracts/{contract_id}/financing-facilities/{facility_id}",
            headers=headers,
        )

    def submit_facility(self, contract_id, facility_id, headers):
        return self._request(
            "POST",
            f"/performance-contracts/{contract_id}/financing-facilities/{facility_id}/submit",
            {}, headers,
        )

    def approve_facility(self, contract_id, facility_id, headers):
        return self._request(
            "POST",
            f"/performance-contracts/{contract_id}/financing-facilities/{facility_id}/approve",
            {}, headers,
        )

    def cancel_facility(self, contract_id, facility_id, headers):
        return self._request(
            "POST",
            f"/performance-contracts/{contract_id}/financing-facilities/{facility_id}/cancel",
            {}, headers,
        )

    def payoff_facility(self, contract_id, facility_id, headers):
        return self._request(
            "POST",
            f"/performance-contracts/{contract_id}/financing-facilities/{facility_id}/payoff",
            {}, headers,
        )

    # --- FinancingDraw ---
    def create_draw(self, contract_id, facility_id, payload, headers):
        return self._request(
            "POST",
            f"/performance-contracts/{contract_id}/financing-facilities/{facility_id}/draws",
            payload, headers,
        )

    def list_draws(self, contract_id, facility_id, headers, params=None):
        return self._request(
            "GET",
            f"/performance-contracts/{contract_id}/financing-facilities/{facility_id}/draws",
            headers=headers, params=params,
        )

    def approve_draw(self, contract_id, facility_id, draw_id, headers):
        return self._request(
            "POST",
            f"/performance-contracts/{contract_id}/financing-facilities/{facility_id}/draws/{draw_id}/approve",
            {}, headers,
        )

    def release_draw(self, contract_id, facility_id, draw_id, headers):
        return self._request(
            "POST",
            f"/performance-contracts/{contract_id}/financing-facilities/{facility_id}/draws/{draw_id}/release",
            {}, headers,
        )

    def reject_draw(self, contract_id, facility_id, draw_id, headers):
        return self._request(
            "POST",
            f"/performance-contracts/{contract_id}/financing-facilities/{facility_id}/draws/{draw_id}/reject",
            {}, headers,
        )

    # --- WorkPhase ---
    def create_phase(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/performance-contracts/{contract_id}/phases",
            payload, headers,
        )

    def list_phases(self, contract_id, headers, params=None):
        return self._request(
            "GET", f"/performance-contracts/{contract_id}/phases",
            headers=headers, params=params,
        )

    def get_phase(self, contract_id, phase_id, headers):
        return self._request(
            "GET", f"/performance-contracts/{contract_id}/phases/{phase_id}",
            headers=headers,
        )

    def mobilize_phase(self, contract_id, phase_id, headers):
        return self._request(
            "POST",
            f"/performance-contracts/{contract_id}/phases/{phase_id}/mobilize",
            {}, headers,
        )

    def start_phase(self, contract_id, phase_id, headers):
        return self._request(
            "POST",
            f"/performance-contracts/{contract_id}/phases/{phase_id}/start",
            {}, headers,
        )

    def complete_phase(self, contract_id, phase_id, headers):
        return self._request(
            "POST",
            f"/performance-contracts/{contract_id}/phases/{phase_id}/complete",
            {}, headers,
        )

    def suspend_phase(self, contract_id, phase_id, headers):
        return self._request(
            "POST",
            f"/performance-contracts/{contract_id}/phases/{phase_id}/suspend",
            {}, headers,
        )

    # --- DisruptionLog ---
    def create_disruption(self, contract_id, phase_id, payload, headers):
        return self._request(
            "POST",
            f"/performance-contracts/{contract_id}/phases/{phase_id}/disruptions",
            payload, headers,
        )

    def list_disruptions(self, contract_id, phase_id, headers, params=None):
        return self._request(
            "GET",
            f"/performance-contracts/{contract_id}/phases/{phase_id}/disruptions",
            headers=headers, params=params,
        )

    # --- SavingsReport ---
    def create_report(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/performance-contracts/{contract_id}/reports",
            payload, headers,
        )

    def list_reports(self, contract_id, headers, params=None):
        return self._request(
            "GET", f"/performance-contracts/{contract_id}/reports",
            headers=headers, params=params,
        )

    def get_report(self, contract_id, report_id, headers):
        return self._request(
            "GET", f"/performance-contracts/{contract_id}/reports/{report_id}",
            headers=headers,
        )

    def submit_report(self, contract_id, report_id, headers):
        return self._request(
            "POST",
            f"/performance-contracts/{contract_id}/reports/{report_id}/submit",
            {}, headers,
        )

    def attest_report(self, contract_id, report_id, headers):
        return self._request(
            "POST",
            f"/performance-contracts/{contract_id}/reports/{report_id}/attest",
            {}, headers,
        )

    def reconcile_report(self, contract_id, report_id, payload, headers):
        return self._request(
            "POST",
            f"/performance-contracts/{contract_id}/reports/{report_id}/reconcile",
            payload, headers,
        )

    def file_dispute(self, contract_id, report_id, payload, headers):
        return self._request(
            "POST",
            f"/performance-contracts/{contract_id}/reports/{report_id}/disputes",
            payload, headers,
        )

    # --- BaselineAdjustment ---
    def create_adjustment(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/performance-contracts/{contract_id}/baseline-adjustments",
            payload, headers,
        )

    def list_adjustments(self, contract_id, headers, params=None):
        return self._request(
            "GET", f"/performance-contracts/{contract_id}/baseline-adjustments",
            headers=headers, params=params,
        )

    def get_adjustment(self, contract_id, adjustment_id, headers):
        return self._request(
            "GET",
            f"/performance-contracts/{contract_id}/baseline-adjustments/{adjustment_id}",
            headers=headers,
        )

    def approve_adjustment(self, contract_id, adjustment_id, payload, headers):
        return self._request(
            "POST",
            f"/performance-contracts/{contract_id}/baseline-adjustments/{adjustment_id}/approve",
            payload, headers,
        )

    def reject_adjustment(self, contract_id, adjustment_id, headers):
        return self._request(
            "POST",
            f"/performance-contracts/{contract_id}/baseline-adjustments/{adjustment_id}/reject",
            {}, headers,
        )

    # --- DisputeNotice ---
    def list_disputes(self, contract_id, headers, params=None):
        return self._request(
            "GET", f"/performance-contracts/{contract_id}/disputes",
            headers=headers, params=params,
        )

    def get_dispute(self, contract_id, dispute_id, headers):
        return self._request(
            "GET", f"/performance-contracts/{contract_id}/disputes/{dispute_id}",
            headers=headers,
        )

    def escalate_dispute(self, contract_id, dispute_id, headers):
        return self._request(
            "POST",
            f"/performance-contracts/{contract_id}/disputes/{dispute_id}/escalate",
            {}, headers,
        )

    def resolve_dispute(self, contract_id, dispute_id, payload, headers):
        return self._request(
            "POST",
            f"/performance-contracts/{contract_id}/disputes/{dispute_id}/resolve",
            payload, headers,
        )

    def withdraw_dispute(self, contract_id, dispute_id, headers):
        return self._request(
            "POST",
            f"/performance-contracts/{contract_id}/disputes/{dispute_id}/withdraw",
            {}, headers,
        )


api_client = ApiClient()
