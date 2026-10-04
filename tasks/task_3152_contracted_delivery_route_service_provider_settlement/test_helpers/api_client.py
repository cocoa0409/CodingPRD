"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient

BASE = "/route-settlement"


class ApiClient(GenericApiClient):
    # ── Service providers ─────────────────────────────────────────
    def create_service_provider(self, payload, headers):
        return self._request("POST", f"{BASE}/service-providers", payload, headers)

    def list_service_providers(self, headers, params=None):
        return self._request("GET", f"{BASE}/service-providers", headers=headers, params=params)

    def get_service_provider(self, provider_id, headers):
        return self._request("GET", f"{BASE}/service-providers/{provider_id}", headers=headers)

    def approve_service_provider(self, provider_id, headers, payload=None):
        return self._request("POST", f"{BASE}/service-providers/{provider_id}/approve", payload or {}, headers)

    def reopen_provider_review(self, provider_id, headers):
        return self._request("POST", f"{BASE}/service-providers/{provider_id}/reopen-review", {}, headers)

    def suspend_service_provider(self, provider_id, headers):
        return self._request("POST", f"{BASE}/service-providers/{provider_id}/suspend", {}, headers)

    def list_provider_service_areas(self, provider_id, headers):
        return self._request("GET", f"{BASE}/service-providers/{provider_id}/service-areas", headers=headers)

    def list_provider_route_assignments(self, provider_id, headers):
        return self._request("GET", f"{BASE}/service-providers/{provider_id}/route-assignments", headers=headers)

    def list_provider_agreements(self, provider_id, headers):
        return self._request("GET", f"{BASE}/service-providers/{provider_id}/agreements", headers=headers)

    def list_provider_vehicles(self, provider_id, headers):
        return self._request("GET", f"{BASE}/service-providers/{provider_id}/vehicles", headers=headers)

    def list_provider_drivers(self, provider_id, headers):
        return self._request("GET", f"{BASE}/service-providers/{provider_id}/drivers", headers=headers)

    def list_provider_insurance_policies(self, provider_id, headers):
        return self._request("GET", f"{BASE}/service-providers/{provider_id}/insurance-policies", headers=headers)

    def list_provider_settlement_periods(self, provider_id, headers):
        return self._request("GET", f"{BASE}/service-providers/{provider_id}/settlement-periods", headers=headers)

    def list_provider_performance_metrics(self, provider_id, headers):
        return self._request("GET", f"{BASE}/service-providers/{provider_id}/performance-metrics", headers=headers)

    def list_provider_chargeback_claims(self, provider_id, headers):
        return self._request("GET", f"{BASE}/service-providers/{provider_id}/chargeback-claims", headers=headers)

    # ── Service areas ─────────────────────────────────────────────
    def create_service_area(self, payload, headers):
        return self._request("POST", f"{BASE}/service-areas", payload, headers)

    def list_service_areas(self, headers, params=None):
        return self._request("GET", f"{BASE}/service-areas", headers=headers, params=params)

    def get_service_area(self, area_id, headers):
        return self._request("GET", f"{BASE}/service-areas/{area_id}", headers=headers)

    def decommission_service_area(self, area_id, headers):
        return self._request("POST", f"{BASE}/service-areas/{area_id}/decommission", {}, headers)

    def list_area_route_assignments(self, area_id, headers, params=None):
        return self._request("GET", f"{BASE}/service-areas/{area_id}/route-assignments", headers=headers, params=params)

    def list_area_settlement_periods(self, area_id, headers):
        return self._request("GET", f"{BASE}/service-areas/{area_id}/settlement-periods", headers=headers)

    def list_area_vehicles(self, area_id, headers):
        return self._request("GET", f"{BASE}/service-areas/{area_id}/vehicles", headers=headers)

    def list_area_drivers(self, area_id, headers):
        return self._request("GET", f"{BASE}/service-areas/{area_id}/drivers", headers=headers)

    def list_area_agreements(self, area_id, headers):
        return self._request("GET", f"{BASE}/service-areas/{area_id}/agreements", headers=headers)

    def list_area_peak_declarations(self, area_id, headers):
        return self._request("GET", f"{BASE}/service-areas/{area_id}/peak-season-declarations", headers=headers)

    def list_area_providers(self, area_id, headers):
        return self._request("GET", f"{BASE}/service-areas/{area_id}/service-providers", headers=headers)

    # ── Route assignments ─────────────────────────────────────────
    def create_route_assignment(self, payload, headers):
        return self._request("POST", f"{BASE}/route-assignments", payload, headers)

    def list_route_assignments(self, headers, params=None):
        return self._request("GET", f"{BASE}/route-assignments", headers=headers, params=params)

    def get_route_assignment(self, assignment_id, headers):
        return self._request("GET", f"{BASE}/route-assignments/{assignment_id}", headers=headers)

    def activate_route_assignment(self, assignment_id, headers):
        return self._request("POST", f"{BASE}/route-assignments/{assignment_id}/activate", {}, headers)

    def terminate_route_assignment(self, assignment_id, headers):
        return self._request("POST", f"{BASE}/route-assignments/{assignment_id}/terminate", {}, headers)

    def request_transfer(self, assignment_id, payload, headers):
        return self._request("POST", f"{BASE}/route-assignments/{assignment_id}/request-transfer", payload, headers)

    def approve_transfer(self, assignment_id, payload, headers):
        return self._request("POST", f"{BASE}/route-assignments/{assignment_id}/approve-transfer", payload, headers)

    def withdraw_transfer(self, assignment_id, headers):
        return self._request("POST", f"{BASE}/route-assignments/{assignment_id}/withdraw-transfer", {}, headers)

    def reaffirm_route_assignment(self, assignment_id, headers):
        return self._request("POST", f"{BASE}/route-assignments/{assignment_id}/reaffirm", {}, headers)

    def list_assignment_successors(self, assignment_id, headers):
        return self._request("GET", f"{BASE}/route-assignments/{assignment_id}/successors", headers=headers)

    # ── Agreements ────────────────────────────────────────────────
    def create_agreement(self, payload, headers):
        return self._request("POST", f"{BASE}/agreements", payload, headers)

    def list_agreements(self, headers, params=None):
        return self._request("GET", f"{BASE}/agreements", headers=headers, params=params)

    def get_agreement(self, agreement_id, headers):
        return self._request("GET", f"{BASE}/agreements/{agreement_id}", headers=headers)

    def submit_agreement(self, agreement_id, headers):
        return self._request("POST", f"{BASE}/agreements/{agreement_id}/submit", {}, headers)

    def sign_agreement(self, agreement_id, headers):
        return self._request("POST", f"{BASE}/agreements/{agreement_id}/sign", {}, headers)

    def renegotiate_agreement(self, agreement_id, headers):
        return self._request("POST", f"{BASE}/agreements/{agreement_id}/renegotiate", {}, headers)

    def amend_agreement(self, agreement_id, headers):
        return self._request("POST", f"{BASE}/agreements/{agreement_id}/amend", {}, headers)

    def expire_agreement(self, agreement_id, headers):
        return self._request("POST", f"{BASE}/agreements/{agreement_id}/expire", {}, headers)

    def terminate_agreement(self, agreement_id, headers):
        return self._request("POST", f"{BASE}/agreements/{agreement_id}/terminate", {}, headers)

    def get_renewal_recommendation(self, agreement_id, headers):
        return self._request("GET", f"{BASE}/agreements/{agreement_id}/renewal-recommendation", headers=headers)

    def get_negotiation_rounds(self, agreement_id, headers):
        return self._request("GET", f"{BASE}/agreements/{agreement_id}/negotiation-rounds", headers=headers)

    # ── Vehicles ──────────────────────────────────────────────────
    def create_vehicle(self, payload, headers):
        return self._request("POST", f"{BASE}/vehicles", payload, headers)

    def list_vehicles(self, headers, params=None):
        return self._request("GET", f"{BASE}/vehicles", headers=headers, params=params)

    def get_vehicle(self, vehicle_id, headers):
        return self._request("GET", f"{BASE}/vehicles/{vehicle_id}", headers=headers)

    def branding_check(self, vehicle_id, payload, headers):
        return self._request("POST", f"{BASE}/vehicles/{vehicle_id}/branding-check", payload, headers)

    def activate_vehicle(self, vehicle_id, headers):
        return self._request("POST", f"{BASE}/vehicles/{vehicle_id}/activate", {}, headers)

    def list_vehicle_chargeback_claims(self, vehicle_id, headers):
        return self._request("GET", f"{BASE}/vehicles/{vehicle_id}/chargeback-claims", headers=headers)

    # ── Drivers ───────────────────────────────────────────────────
    def create_driver(self, payload, headers):
        return self._request("POST", f"{BASE}/drivers", payload, headers)

    def list_drivers(self, headers, params=None):
        return self._request("GET", f"{BASE}/drivers", headers=headers, params=params)

    def get_driver(self, driver_id, headers):
        return self._request("GET", f"{BASE}/drivers/{driver_id}", headers=headers)

    def qualify_driver(self, driver_id, payload, headers):
        return self._request("POST", f"{BASE}/drivers/{driver_id}/qualify", payload, headers)

    def suspend_driver(self, driver_id, headers):
        return self._request("POST", f"{BASE}/drivers/{driver_id}/suspend", {}, headers)

    def create_duty_shift(self, driver_id, payload, headers):
        return self._request("POST", f"{BASE}/drivers/{driver_id}/duty-shifts", payload, headers)

    def list_duty_shifts(self, driver_id, headers):
        return self._request("GET", f"{BASE}/drivers/{driver_id}/duty-shifts", headers=headers)

    # ── Insurance policies ────────────────────────────────────────
    def create_insurance_policy(self, payload, headers):
        return self._request("POST", f"{BASE}/insurance-policies", payload, headers)

    def list_insurance_policies(self, headers, params=None):
        return self._request("GET", f"{BASE}/insurance-policies", headers=headers, params=params)

    def get_insurance_policy(self, policy_id, headers):
        return self._request("GET", f"{BASE}/insurance-policies/{policy_id}", headers=headers)

    def verify_insurance_policy(self, policy_id, headers):
        return self._request("POST", f"{BASE}/insurance-policies/{policy_id}/verify", {}, headers)

    # ── Settlement periods ────────────────────────────────────────
    def create_settlement_period(self, payload, headers):
        return self._request("POST", f"{BASE}/settlement-periods", payload, headers)

    def list_settlement_periods(self, headers, params=None):
        return self._request("GET", f"{BASE}/settlement-periods", headers=headers, params=params)

    def get_settlement_period(self, period_id, headers):
        return self._request("GET", f"{BASE}/settlement-periods/{period_id}", headers=headers)

    def create_stop_observation(self, period_id, payload, headers):
        return self._request("POST", f"{BASE}/settlement-periods/{period_id}/stop-observations", payload, headers)

    def list_stop_observations(self, period_id, headers):
        return self._request("GET", f"{BASE}/settlement-periods/{period_id}/stop-observations", headers=headers)

    def create_deduction(self, period_id, payload, headers):
        return self._request("POST", f"{BASE}/settlement-periods/{period_id}/deductions", payload, headers)

    def list_deductions(self, period_id, headers):
        return self._request("GET", f"{BASE}/settlement-periods/{period_id}/deductions", headers=headers)

    def list_period_disputes(self, period_id, headers):
        return self._request("GET", f"{BASE}/settlement-periods/{period_id}/disputes", headers=headers)

    def list_period_chargeback_claims(self, period_id, headers):
        return self._request("GET", f"{BASE}/settlement-periods/{period_id}/chargeback-claims", headers=headers)

    def get_period_summary(self, period_id, headers):
        return self._request("GET", f"{BASE}/settlement-periods/{period_id}/summary", headers=headers)

    def close_accrual(self, period_id, headers):
        return self._request("POST", f"{BASE}/settlement-periods/{period_id}/close-accrual", {}, headers)

    def reconcile_period(self, period_id, payload, headers):
        return self._request("POST", f"{BASE}/settlement-periods/{period_id}/reconcile", payload or {}, headers)

    def dispute_period(self, period_id, payload, headers):
        return self._request("POST", f"{BASE}/settlement-periods/{period_id}/dispute", payload, headers)

    def release_period(self, period_id, headers):
        return self._request("POST", f"{BASE}/settlement-periods/{period_id}/release", {}, headers)

    # ── Performance metrics ───────────────────────────────────────
    def create_performance_metric(self, payload, headers):
        return self._request("POST", f"{BASE}/performance-metrics", payload, headers)

    def list_performance_metrics(self, headers, params=None):
        return self._request("GET", f"{BASE}/performance-metrics", headers=headers, params=params)

    def get_performance_metric(self, metric_id, headers):
        return self._request("GET", f"{BASE}/performance-metrics/{metric_id}", headers=headers)

    def compose_performance_metric(self, metric_id, headers):
        return self._request("POST", f"{BASE}/performance-metrics/{metric_id}/compose", {}, headers)

    # ── Charge-back claims ────────────────────────────────────────
    def create_chargeback_claim(self, payload, headers):
        return self._request("POST", f"{BASE}/chargeback-claims", payload, headers)

    def list_chargeback_claims(self, headers, params=None):
        return self._request("GET", f"{BASE}/chargeback-claims", headers=headers, params=params)

    def get_chargeback_claim(self, claim_id, headers):
        return self._request("GET", f"{BASE}/chargeback-claims/{claim_id}", headers=headers)

    def approve_chargeback_claim(self, claim_id, headers):
        return self._request("POST", f"{BASE}/chargeback-claims/{claim_id}/approve", {}, headers)

    def settle_chargeback_claim(self, claim_id, headers):
        return self._request("POST", f"{BASE}/chargeback-claims/{claim_id}/settle", {}, headers)

    def reject_chargeback_claim(self, claim_id, headers):
        return self._request("POST", f"{BASE}/chargeback-claims/{claim_id}/reject", {}, headers)

    # ── Disputes ──────────────────────────────────────────────────
    def submit_dispute_evidence(self, dispute_id, headers):
        return self._request("POST", f"{BASE}/disputes/{dispute_id}/submit-evidence", {}, headers)

    def counter_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"{BASE}/disputes/{dispute_id}/counter", payload, headers)

    def resubmit_dispute_evidence(self, dispute_id, headers):
        return self._request("POST", f"{BASE}/disputes/{dispute_id}/resubmit-evidence", {}, headers)

    def escalate_dispute(self, dispute_id, headers):
        return self._request("POST", f"{BASE}/disputes/{dispute_id}/escalate", {}, headers)

    def resolve_dispute(self, dispute_id, headers):
        return self._request("POST", f"{BASE}/disputes/{dispute_id}/resolve", {}, headers)

    def withdraw_dispute(self, dispute_id, headers):
        return self._request("POST", f"{BASE}/disputes/{dispute_id}/withdraw", {}, headers)

    # ── Peak-season declarations ──────────────────────────────────
    def create_peak_declaration(self, payload, headers):
        return self._request("POST", f"{BASE}/peak-season-declarations", payload, headers)

    def list_peak_declarations(self, headers, params=None):
        return self._request("GET", f"{BASE}/peak-season-declarations", headers=headers, params=params)

    def get_peak_declaration(self, declaration_id, headers):
        return self._request("GET", f"{BASE}/peak-season-declarations/{declaration_id}", headers=headers)

    def activate_peak_declaration(self, declaration_id, headers):
        return self._request("POST", f"{BASE}/peak-season-declarations/{declaration_id}/activate", {}, headers)

    def end_peak_declaration(self, declaration_id, headers):
        return self._request("POST", f"{BASE}/peak-season-declarations/{declaration_id}/end", {}, headers)

    def cancel_peak_declaration(self, declaration_id, headers):
        return self._request("POST", f"{BASE}/peak-season-declarations/{declaration_id}/cancel", {}, headers)

    # ── Fuel index rates ──────────────────────────────────────────
    def create_fuel_index_rate(self, payload, headers):
        return self._request("POST", f"{BASE}/fuel-index-rates", payload, headers)

    def list_fuel_index_rates(self, headers, params=None):
        return self._request("GET", f"{BASE}/fuel-index-rates", headers=headers, params=params)

    def get_fuel_index_rate(self, rate_id, headers):
        return self._request("GET", f"{BASE}/fuel-index-rates/{rate_id}", headers=headers)

    # ── Logical clock ─────────────────────────────────────────────
    def set_current_utc(self, to_iso8601, headers):
        return self._request("POST", f"{BASE}/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    def get_current_utc(self, headers):
        return self._request("GET", f"{BASE}/_clock/current_utc", headers=headers)


api_client = ApiClient()