"""API client: one method per endpoint declared in the PRD §4 table.

Every operation is mounted under ``/dealer-network``. Methods return the raw
``requests.Response`` so tests can assert status codes.
"""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/dealer-network"


class ApiClient(GenericApiClient):
    # ─── Logical clock ────────────────────────────────
    def set_current_utc(self, to_iso8601, headers):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # ─── Dealers ──────────────────────────────────────
    def create_dealer(self, payload, headers):
        return self._request("POST", f"{PREFIX}/dealers", payload, headers)

    def list_dealers(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/dealers", headers=headers, params=params)

    def get_dealer(self, dealer_id, headers):
        return self._request("GET", f"{PREFIX}/dealers/{dealer_id}", headers=headers)

    def terminate_dealer(self, dealer_id, headers):
        return self._request(
            "POST", f"{PREFIX}/dealers/{dealer_id}/terminate", {}, headers,
        )

    # ─── Dealer agreements ────────────────────────────
    def create_agreement(self, payload, headers):
        return self._request("POST", f"{PREFIX}/dealer-agreements", payload, headers)

    def list_agreements(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/dealer-agreements", headers=headers, params=params,
        )

    def get_agreement(self, agreement_id, headers):
        return self._request(
            "GET", f"{PREFIX}/dealer-agreements/{agreement_id}", headers=headers,
        )

    def list_dealer_agreements(self, dealer_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/dealers/{dealer_id}/dealer-agreements",
            headers=headers, params=params,
        )

    def submit_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"{PREFIX}/dealer-agreements/{agreement_id}/submit", {}, headers,
        )

    def activate_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"{PREFIX}/dealer-agreements/{agreement_id}/activate", {}, headers,
        )

    def mark_agreement_underperforming(self, agreement_id, headers):
        return self._request(
            "POST", f"{PREFIX}/dealer-agreements/{agreement_id}/mark-underperforming",
            {}, headers,
        )

    def suspend_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"{PREFIX}/dealer-agreements/{agreement_id}/suspend", {}, headers,
        )

    def reinstate_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"{PREFIX}/dealer-agreements/{agreement_id}/reinstate", {}, headers,
        )

    def terminate_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"{PREFIX}/dealer-agreements/{agreement_id}/terminate", {}, headers,
        )

    # ─── Performance reviews ──────────────────────────
    def create_review(self, payload, headers):
        return self._request("POST", f"{PREFIX}/performance-reviews", payload, headers)

    def list_reviews(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/performance-reviews", headers=headers, params=params,
        )

    def get_review(self, review_id, headers):
        return self._request(
            "GET", f"{PREFIX}/performance-reviews/{review_id}", headers=headers,
        )

    def list_agreement_reviews(self, agreement_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/dealer-agreements/{agreement_id}/performance-reviews",
            headers=headers, params=params,
        )

    def record_review_results(self, review_id, headers):
        return self._request(
            "POST", f"{PREFIX}/performance-reviews/{review_id}/record-results",
            {}, headers,
        )

    def evaluate_review(self, review_id, headers):
        return self._request(
            "POST", f"{PREFIX}/performance-reviews/{review_id}/evaluate", {}, headers,
        )

    def request_review_circumstance(self, review_id, headers):
        return self._request(
            "POST", f"{PREFIX}/performance-reviews/{review_id}/request-circumstance",
            {}, headers,
        )

    def set_review_remediation(self, review_id, headers):
        return self._request(
            "POST", f"{PREFIX}/performance-reviews/{review_id}/set-remediation",
            {}, headers,
        )

    # ─── Parts commitments ────────────────────────────
    def create_commitment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/parts-commitments", payload, headers)

    def list_commitments(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/parts-commitments", headers=headers, params=params,
        )

    def get_commitment(self, commitment_id, headers):
        return self._request(
            "GET", f"{PREFIX}/parts-commitments/{commitment_id}", headers=headers,
        )

    def list_agreement_commitments(self, agreement_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/dealer-agreements/{agreement_id}/parts-commitments",
            headers=headers, params=params,
        )

    def list_dealer_commitments(self, dealer_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/dealers/{dealer_id}/parts-commitments",
            headers=headers, params=params,
        )

    def submit_commitment(self, commitment_id, headers):
        return self._request(
            "POST", f"{PREFIX}/parts-commitments/{commitment_id}/submit", {}, headers,
        )

    def ready_commitment_for_orders(self, commitment_id, headers):
        return self._request(
            "POST", f"{PREFIX}/parts-commitments/{commitment_id}/ready-for-orders",
            {}, headers,
        )

    def suspend_commitment(self, commitment_id, headers):
        return self._request(
            "POST", f"{PREFIX}/parts-commitments/{commitment_id}/suspend", {}, headers,
        )

    def suspend_commitment_core_credit(self, commitment_id, headers):
        return self._request(
            "POST", f"{PREFIX}/parts-commitments/{commitment_id}/suspend-core-credit",
            {}, headers,
        )

    def settle_commitment_core_credit(self, commitment_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/parts-commitments/{commitment_id}/settle-core-credit",
            payload, headers,
        )

    def reinstate_commitment(self, commitment_id, headers):
        return self._request(
            "POST", f"{PREFIX}/parts-commitments/{commitment_id}/reinstate",
            {}, headers,
        )

    # ─── Parts order batches ──────────────────────────
    def create_batch(self, payload, headers):
        return self._request("POST", f"{PREFIX}/parts-order-batches", payload, headers)

    def list_batches(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/parts-order-batches", headers=headers, params=params,
        )

    def get_batch(self, batch_id, headers):
        return self._request(
            "GET", f"{PREFIX}/parts-order-batches/{batch_id}", headers=headers,
        )

    def list_commitment_batches(self, commitment_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/parts-commitments/{commitment_id}/parts-order-batches",
            headers=headers, params=params,
        )

    def place_batch_order(self, batch_id, headers):
        return self._request(
            "POST", f"{PREFIX}/parts-order-batches/{batch_id}/place-order", {}, headers,
        )

    def receive_batch(self, batch_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/parts-order-batches/{batch_id}/receive", payload, headers,
        )

    def return_batch_core(self, batch_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/parts-order-batches/{batch_id}/return-core",
            payload, headers,
        )

    def batch_core_return(self, batch_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/parts-order-batches/{batch_id}/core-return",
            payload, headers,
        )

    def cancel_batch_core_return(self, batch_id, headers):
        return self._request(
            "POST", f"{PREFIX}/parts-order-batches/{batch_id}/cancel-core-return",
            {}, headers,
        )

    def close_batch(self, batch_id, headers):
        return self._request(
            "POST", f"{PREFIX}/parts-order-batches/{batch_id}/close", {}, headers,
        )

    def cancel_batch(self, batch_id, headers):
        return self._request(
            "POST", f"{PREFIX}/parts-order-batches/{batch_id}/cancel", {}, headers,
        )

    # ─── Rebuild claims ───────────────────────────────
    def create_rebuild_claim(self, payload, headers):
        return self._request("POST", f"{PREFIX}/rebuild-claims", payload, headers)

    def list_rebuild_claims(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/rebuild-claims", headers=headers, params=params,
        )

    def get_rebuild_claim(self, claim_id, headers):
        return self._request(
            "GET", f"{PREFIX}/rebuild-claims/{claim_id}", headers=headers,
        )

    def list_dealer_rebuild_claims(self, dealer_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/dealers/{dealer_id}/rebuild-claims",
            headers=headers, params=params,
        )

    def approve_rebuild_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/rebuild-claims/{claim_id}/approve", payload, headers,
        )

    def deny_rebuild_claim(self, claim_id, headers):
        return self._request(
            "POST", f"{PREFIX}/rebuild-claims/{claim_id}/deny", {}, headers,
        )

    def decline_rebuild_claim(self, claim_id, headers):
        return self._request(
            "POST", f"{PREFIX}/rebuild-claims/{claim_id}/decline", {}, headers,
        )

    def request_rebuild_core_return(self, claim_id, headers):
        return self._request(
            "POST", f"{PREFIX}/rebuild-claims/{claim_id}/request-core-return",
            {}, headers,
        )

    def return_rebuild_core(self, claim_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/rebuild-claims/{claim_id}/core-return", payload, headers,
        )

    def deliver_rebuild_claim(self, claim_id, headers):
        return self._request(
            "POST", f"{PREFIX}/rebuild-claims/{claim_id}/deliver", {}, headers,
        )

    def certify_rebuild_claim(self, claim_id, headers):
        return self._request(
            "POST", f"{PREFIX}/rebuild-claims/{claim_id}/certify", {}, headers,
        )

    # ─── Equipment orders ─────────────────────────────
    def create_equipment_order(self, payload, headers):
        return self._request("POST", f"{PREFIX}/equipment-orders", payload, headers)

    def list_equipment_orders(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/equipment-orders", headers=headers, params=params,
        )

    def get_equipment_order(self, order_id, headers):
        return self._request(
            "GET", f"{PREFIX}/equipment-orders/{order_id}", headers=headers,
        )

    def list_dealer_equipment_orders(self, dealer_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/dealers/{dealer_id}/equipment-orders",
            headers=headers, params=params,
        )

    def submit_equipment_order(self, order_id, headers):
        return self._request(
            "POST", f"{PREFIX}/equipment-orders/{order_id}/submit", {}, headers,
        )

    def approve_equipment_financing(self, order_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/equipment-orders/{order_id}/approve-financing",
            payload, headers,
        )

    def deliver_equipment_order(self, order_id, headers):
        return self._request(
            "POST", f"{PREFIX}/equipment-orders/{order_id}/deliver", {}, headers,
        )

    def cancel_equipment_order(self, order_id, headers):
        return self._request(
            "POST", f"{PREFIX}/equipment-orders/{order_id}/cancel", {}, headers,
        )

    def list_order_trade_ins(self, order_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/equipment-orders/{order_id}/trade-ins",
            headers=headers, params=params,
        )

    def list_trade_in_units(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/trade-in-units", headers=headers, params=params,
        )

    # ─── Support agreements ───────────────────────────
    def create_support_agreement(self, payload, headers):
        return self._request("POST", f"{PREFIX}/support-agreements", payload, headers)

    def list_support_agreements(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/support-agreements", headers=headers, params=params,
        )

    def get_support_agreement(self, support_id, headers):
        return self._request(
            "GET", f"{PREFIX}/support-agreements/{support_id}", headers=headers,
        )

    def list_dealer_support_agreements(self, dealer_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/dealers/{dealer_id}/support-agreements",
            headers=headers, params=params,
        )

    def suspend_support_agreement(self, support_id, headers):
        return self._request(
            "POST", f"{PREFIX}/support-agreements/{support_id}/suspend", {}, headers,
        )

    def reinstate_support_agreement(self, support_id, headers):
        return self._request(
            "POST", f"{PREFIX}/support-agreements/{support_id}/reinstate", {}, headers,
        )

    def terminate_support_agreement(self, support_id, headers):
        return self._request(
            "POST", f"{PREFIX}/support-agreements/{support_id}/terminate", {}, headers,
        )

    # ─── Market share observations ────────────────────
    def create_observation(self, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/market-share-observations", payload, headers,
        )

    def list_observations(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/market-share-observations", headers=headers, params=params,
        )

    def get_observation(self, observation_id, headers):
        return self._request(
            "GET", f"{PREFIX}/market-share-observations/{observation_id}",
            headers=headers,
        )

    def list_dealer_observations(self, dealer_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/dealers/{dealer_id}/market-share-observations",
            headers=headers, params=params,
        )

    # ─── Service orders ───────────────────────────────
    def create_service_order(self, payload, headers):
        return self._request("POST", f"{PREFIX}/service-orders", payload, headers)

    def list_service_orders(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/service-orders", headers=headers, params=params,
        )

    def get_service_order(self, service_order_id, headers):
        return self._request(
            "GET", f"{PREFIX}/service-orders/{service_order_id}", headers=headers,
        )

    def list_commitment_service_orders(self, commitment_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/parts-commitments/{commitment_id}/service-orders",
            headers=headers, params=params,
        )

    def list_dealer_service_orders(self, dealer_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/dealers/{dealer_id}/service-orders",
            headers=headers, params=params,
        )

    def begin_service_order(self, service_order_id, headers):
        return self._request(
            "POST", f"{PREFIX}/service-orders/{service_order_id}/begin", {}, headers,
        )

    def record_emergency_fill(self, service_order_id, headers):
        return self._request(
            "POST", f"{PREFIX}/service-orders/{service_order_id}/record-emergency-fill",
            {}, headers,
        )

    def escalate_service_order(self, service_order_id, headers):
        return self._request(
            "POST", f"{PREFIX}/service-orders/{service_order_id}/escalate", {}, headers,
        )

    def fill_service_order(self, service_order_id, headers):
        return self._request(
            "POST", f"{PREFIX}/service-orders/{service_order_id}/fill", {}, headers,
        )

    def reopen_service_order(self, service_order_id, headers):
        return self._request(
            "POST", f"{PREFIX}/service-orders/{service_order_id}/reopen", {}, headers,
        )

    def raise_service_restriction(self, service_order_id, headers):
        return self._request(
            "POST", f"{PREFIX}/service-orders/{service_order_id}/raise-restriction",
            {}, headers,
        )

    def lower_service_restriction(self, service_order_id, headers):
        return self._request(
            "POST", f"{PREFIX}/service-orders/{service_order_id}/lower-restriction",
            {}, headers,
        )

    def resolve_service_order(self, service_order_id, headers):
        return self._request(
            "POST", f"{PREFIX}/service-orders/{service_order_id}/resolve", {}, headers,
        )

    # ─── Machine population records ───────────────────
    def create_population_record(self, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/machine-population-records", payload, headers,
        )

    def list_population_records(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/machine-population-records",
            headers=headers, params=params,
        )

    def get_population_record(self, record_id, headers):
        return self._request(
            "GET", f"{PREFIX}/machine-population-records/{record_id}", headers=headers,
        )

    def list_dealer_population_records(self, dealer_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/dealers/{dealer_id}/machine-population-records",
            headers=headers, params=params,
        )

    def get_forecast(self, dealer_id, headers):
        return self._request(
            "GET", f"{PREFIX}/machine-population-records/forecast",
            headers=headers, params={"dealer_id": dealer_id},
        )

    def get_coverage_snapshot(self, record_id, headers):
        return self._request(
            "GET", f"{PREFIX}/machine-population-records/{record_id}/coverage-snapshot",
            headers=headers,
        )

    def get_sweep_metrics(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/machine-population-records/sweep-metrics",
            headers=headers, params=params,
        )

    def read_meter(self, record_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/machine-population-records/{record_id}/read-meter",
            payload, headers,
        )

    def retire_population_record(self, record_id, headers):
        return self._request(
            "POST", f"{PREFIX}/machine-population-records/{record_id}/retire",
            {}, headers,
        )

    def reinstate_population_record(self, record_id, headers):
        return self._request(
            "POST", f"{PREFIX}/machine-population-records/{record_id}/reinstate",
            {}, headers,
        )

    # ─── Certification records ────────────────────────
    def create_certification(self, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/certification-records", payload, headers,
        )

    def list_certifications(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/certification-records", headers=headers, params=params,
        )

    def get_certification(self, certification_id, headers):
        return self._request(
            "GET", f"{PREFIX}/certification-records/{certification_id}",
            headers=headers,
        )

    def list_dealer_certifications(self, dealer_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/dealers/{dealer_id}/certification-records",
            headers=headers, params=params,
        )

    def revoke_certification(self, certification_id, headers):
        return self._request(
            "POST", f"{PREFIX}/certification-records/{certification_id}/revoke",
            {}, headers,
        )

    # ─── Party registrations ──────────────────────────
    def create_party_registration(self, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/party-registrations", payload, headers,
        )

    def list_party_registrations(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/party-registrations", headers=headers, params=params,
        )

    def get_party_registration(self, registration_id, headers):
        return self._request(
            "GET", f"{PREFIX}/party-registrations/{registration_id}", headers=headers,
        )


api_client = ApiClient()

__all__ = ["ApiClient", "api_client", "PREFIX"]