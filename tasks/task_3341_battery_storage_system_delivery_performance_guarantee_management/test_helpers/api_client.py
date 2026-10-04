"""API client: one method per endpoint from PRD §4.

Every method returns the raw ``requests.Response`` so tests can assert on
status codes and envelopes directly. All endpoints are mounted under the
root path ``/``.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Thin endpoint-shaped facade over the shared HTTP client."""

    # ─── Logical clock ──────────────────────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ─── Projects ───────────────────────────────────────────────────────
    def create_project(self, payload, headers):
        return self._request("POST", "/projects", payload, headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", "/projects", headers=headers, params=params)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/projects/{project_id}", headers=headers)

    def recompute_projection(self, project_id, payload, headers):
        return self._request(
            "POST", f"/projects/{project_id}/recompute-projection", payload, headers
        )

    # ─── Equipment supply agreements ────────────────────────────────────
    def create_esa(self, payload, headers):
        return self._request("POST", "/equipment-supply-agreements", payload, headers)

    def list_esas(self, headers, params=None):
        return self._request(
            "GET", "/equipment-supply-agreements", headers=headers, params=params
        )

    def get_esa(self, esa_id, headers):
        return self._request(
            "GET", f"/equipment-supply-agreements/{esa_id}", headers=headers
        )

    def execute_esa(self, esa_id, payload, headers):
        return self._request(
            "POST", f"/equipment-supply-agreements/{esa_id}/execute", payload, headers
        )

    def complete_esa(self, esa_id, headers):
        return self._request(
            "POST", f"/equipment-supply-agreements/{esa_id}/complete", {}, headers
        )

    def waive_ld(self, esa_id, payload, headers):
        return self._request(
            "POST", f"/equipment-supply-agreements/{esa_id}/waive-ld", payload, headers
        )

    # ─── Delivery milestones ────────────────────────────────────────────
    def create_milestone(self, payload, headers):
        return self._request("POST", "/delivery-milestones", payload, headers)

    def list_milestones(self, headers, params=None):
        return self._request(
            "GET", "/delivery-milestones", headers=headers, params=params
        )

    def get_milestone(self, milestone_id, headers):
        return self._request(
            "GET", f"/delivery-milestones/{milestone_id}", headers=headers
        )

    def record_milestone_outcome(self, milestone_id, payload, headers):
        return self._request(
            "POST",
            f"/delivery-milestones/{milestone_id}/record-outcome",
            payload,
            headers,
        )

    def cancel_milestone(self, milestone_id, headers):
        return self._request(
            "POST", f"/delivery-milestones/{milestone_id}/cancel", {}, headers
        )

    # ─── Safety permits ─────────────────────────────────────────────────
    def create_permit(self, payload, headers):
        return self._request("POST", "/safety-permits", payload, headers)

    def list_permits(self, headers, params=None):
        return self._request("GET", "/safety-permits", headers=headers, params=params)

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"/safety-permits/{permit_id}", headers=headers)

    def decide_permit(self, permit_id, payload, headers):
        return self._request(
            "POST", f"/safety-permits/{permit_id}/decide", payload, headers
        )

    def resubmit_permit(self, permit_id, headers):
        return self._request(
            "POST", f"/safety-permits/{permit_id}/resubmit", {}, headers
        )

    # ─── Performance tests ──────────────────────────────────────────────
    def create_performance_test(self, payload, headers):
        return self._request("POST", "/performance-tests", payload, headers)

    def list_performance_tests(self, headers, params=None):
        return self._request(
            "GET", "/performance-tests", headers=headers, params=params
        )

    def get_performance_test(self, test_id, headers):
        return self._request(
            "GET", f"/performance-tests/{test_id}", headers=headers
        )

    def record_test_results(self, test_id, payload, headers):
        return self._request(
            "POST", f"/performance-tests/{test_id}/record-results", payload, headers
        )

    def cancel_performance_test(self, test_id, headers):
        return self._request(
            "POST", f"/performance-tests/{test_id}/cancel", {}, headers
        )

    # ─── Augmentation events ────────────────────────────────────────────
    def create_augmentation(self, payload, headers):
        return self._request("POST", "/augmentation-events", payload, headers)

    def list_augmentations(self, headers, params=None):
        return self._request(
            "GET", "/augmentation-events", headers=headers, params=params
        )

    def get_augmentation(self, augmentation_id, headers):
        return self._request(
            "GET", f"/augmentation-events/{augmentation_id}", headers=headers
        )

    def execute_augmentation(self, augmentation_id, payload, headers):
        return self._request(
            "POST",
            f"/augmentation-events/{augmentation_id}/execute",
            payload,
            headers,
        )

    def cancel_augmentation(self, augmentation_id, headers):
        return self._request(
            "POST", f"/augmentation-events/{augmentation_id}/cancel", {}, headers
        )

    # ─── Service agreements (LTSA) ──────────────────────────────────────
    def create_service_agreement(self, payload, headers):
        return self._request("POST", "/service-agreements", payload, headers)

    def list_service_agreements(self, headers, params=None):
        return self._request(
            "GET", "/service-agreements", headers=headers, params=params
        )

    def get_service_agreement(self, ltsa_id, headers):
        return self._request(
            "GET", f"/service-agreements/{ltsa_id}", headers=headers
        )

    def activate_service_agreement(self, ltsa_id, headers):
        return self._request(
            "POST", f"/service-agreements/{ltsa_id}/activate", {}, headers
        )

    def suspend_service_agreement(self, ltsa_id, headers):
        return self._request(
            "POST", f"/service-agreements/{ltsa_id}/suspend", {}, headers
        )

    def reactivate_service_agreement(self, ltsa_id, headers):
        return self._request(
            "POST", f"/service-agreements/{ltsa_id}/reactivate", {}, headers
        )

    # ─── Spare part orders ──────────────────────────────────────────────
    def create_spare_part_order(self, payload, headers):
        return self._request("POST", "/spare-part-orders", payload, headers)

    def list_spare_part_orders(self, headers, params=None):
        return self._request(
            "GET", "/spare-part-orders", headers=headers, params=params
        )

    def get_spare_part_order(self, order_id, headers):
        return self._request("GET", f"/spare-part-orders/{order_id}", headers=headers)

    def ship_order(self, order_id, headers):
        return self._request(
            "POST", f"/spare-part-orders/{order_id}/ship", {}, headers
        )

    def deliver_order(self, order_id, headers):
        return self._request(
            "POST", f"/spare-part-orders/{order_id}/deliver", {}, headers
        )

    def install_order(self, order_id, headers):
        return self._request(
            "POST", f"/spare-part-orders/{order_id}/install", {}, headers
        )

    def cancel_order(self, order_id, headers):
        return self._request(
            "POST", f"/spare-part-orders/{order_id}/cancel", {}, headers
        )

    # ─── Warranty claims ────────────────────────────────────────────────
    def create_warranty_claim(self, payload, headers):
        return self._request("POST", "/warranty-claims", payload, headers)

    def list_warranty_claims(self, headers, params=None):
        return self._request("GET", "/warranty-claims", headers=headers, params=params)

    def get_warranty_claim(self, claim_id, headers):
        return self._request("GET", f"/warranty-claims/{claim_id}", headers=headers)

    def start_claim_review(self, claim_id, headers):
        return self._request(
            "POST", f"/warranty-claims/{claim_id}/start-review", {}, headers
        )

    def decide_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/warranty-claims/{claim_id}/decide", payload, headers
        )

    # ─── Bid sessions ───────────────────────────────────────────────────
    def create_bid_session(self, payload, headers):
        return self._request("POST", "/bid-sessions", payload, headers)

    def list_bid_sessions(self, headers, params=None):
        return self._request("GET", "/bid-sessions", headers=headers, params=params)

    def get_bid_session(self, session_id, headers):
        return self._request("GET", f"/bid-sessions/{session_id}", headers=headers)

    def record_bid_clearing(self, session_id, payload, headers):
        return self._request(
            "POST", f"/bid-sessions/{session_id}/record-clearing", payload, headers
        )

    def settle_bid_session(self, session_id, headers):
        return self._request(
            "POST", f"/bid-sessions/{session_id}/settle", {}, headers
        )

    def cancel_bid_session(self, session_id, headers):
        return self._request(
            "POST", f"/bid-sessions/{session_id}/cancel", {}, headers
        )


api_client = ApiClient()
