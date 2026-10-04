"""API client: one method per endpoint defined in the PRD §4 table."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Thin wrapper over the platform's REST surface."""

    # -- logical clock ------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # -- licenses -----------------------------------------------------------
    def create_license(self, payload, headers):
        return self._request("POST", "/api/licenses", payload, headers)

    def list_licenses(self, headers, params=None):
        return self._request("GET", "/api/licenses", headers=headers, params=params)

    def get_license(self, license_id, headers):
        return self._request("GET", f"/api/licenses/{license_id}", headers=headers)

    def activate_license(self, license_id, headers):
        return self._request(
            "POST", f"/api/licenses/{license_id}/activate", {}, headers
        )

    def suspend_license(self, license_id, headers):
        return self._request("POST", f"/api/licenses/{license_id}/suspend", {}, headers)

    def expire_license(self, license_id, headers):
        return self._request("POST", f"/api/licenses/{license_id}/expire", {}, headers)

    def list_license_product_lines(self, license_id, headers, params=None):
        return self._request(
            "GET", f"/api/licenses/{license_id}/product-lines", headers=headers, params=params
        )

    # -- product lines ------------------------------------------------------
    def create_product_line(self, payload, headers):
        return self._request("POST", "/api/product-lines", payload, headers)

    def list_product_lines(self, headers, params=None):
        return self._request("GET", "/api/product-lines", headers=headers, params=params)

    def get_product_line(self, line_id, headers):
        return self._request("GET", f"/api/product-lines/{line_id}", headers=headers)

    def patch_product_line(self, line_id, payload, headers):
        return self._request(
            "PATCH", f"/api/product-lines/{line_id}", payload, headers
        )

    def ready_product_line(self, line_id, headers):
        return self._request(
            "POST", f"/api/product-lines/{line_id}/ready-for-approval", {}, headers
        )

    def start_product_line_production(self, line_id, headers):
        return self._request(
            "POST", f"/api/product-lines/{line_id}/start-production", {}, headers
        )

    def pack_out_product_line(self, line_id, headers):
        return self._request(
            "POST", f"/api/product-lines/{line_id}/pack-out", {}, headers
        )

    def list_line_card_sets(self, line_id, headers, params=None):
        return self._request(
            "GET", f"/api/product-lines/{line_id}/card-sets", headers=headers, params=params
        )

    def list_line_allocations(self, line_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/product-lines/{line_id}/distribution-allocations",
            headers=headers,
            params=params,
        )

    # -- card sets ----------------------------------------------------------
    def create_card_set(self, payload, headers):
        return self._request("POST", "/api/card-sets", payload, headers)

    def list_card_sets(self, headers, params=None):
        return self._request("GET", "/api/card-sets", headers=headers, params=params)

    def get_card_set(self, set_id, headers):
        return self._request("GET", f"/api/card-sets/{set_id}", headers=headers)

    def submit_card_set(self, set_id, headers):
        return self._request("POST", f"/api/card-sets/{set_id}/submit", {}, headers)

    def return_card_set_to_draft(self, set_id, headers):
        return self._request(
            "POST", f"/api/card-sets/{set_id}/return-to-draft", {}, headers
        )

    def approve_card_set(self, set_id, payload, headers):
        return self._request("POST", f"/api/card-sets/{set_id}/approve", payload, headers)

    def start_card_set_production(self, set_id, headers):
        return self._request(
            "POST", f"/api/card-sets/{set_id}/start-production", {}, headers
        )

    def pack_out_card_set(self, set_id, headers):
        return self._request("POST", f"/api/card-sets/{set_id}/pack-out", {}, headers)

    def get_card_set_approval_chain(self, set_id, headers):
        return self._request(
            "GET", f"/api/card-sets/{set_id}/approval-chain", headers=headers
        )

    def get_card_set_print_run_summary(self, set_id, headers):
        return self._request(
            "GET", f"/api/card-sets/{set_id}/print-run-summary", headers=headers
        )

    def list_set_pack_configurations(self, set_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/card-sets/{set_id}/pack-configurations",
            headers=headers,
            params=params,
        )

    def list_set_print_run_decisions(self, set_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/card-sets/{set_id}/print-run-decisions",
            headers=headers,
            params=params,
        )

    # -- artwork approvals --------------------------------------------------
    def submit_artwork(self, set_id, payload, headers):
        return self._request(
            "POST", f"/api/card-sets/{set_id}/artwork-approvals", payload, headers
        )

    def list_set_artwork(self, set_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/card-sets/{set_id}/artwork-approvals",
            headers=headers,
            params=params,
        )

    def list_artwork_approvals(self, headers, params=None):
        return self._request(
            "GET", "/api/artwork-approvals", headers=headers, params=params
        )

    def get_artwork_approval(self, artwork_id, headers):
        return self._request(
            "GET", f"/api/artwork-approvals/{artwork_id}", headers=headers
        )

    def decide_artwork(self, artwork_id, payload, headers):
        return self._request(
            "POST", f"/api/artwork-approvals/{artwork_id}/decide", payload, headers
        )

    # -- pack configurations ------------------------------------------------
    def create_pack_configuration(self, payload, headers):
        return self._request("POST", "/api/pack-configurations", payload, headers)

    def list_pack_configurations(self, headers, params=None):
        return self._request(
            "GET", "/api/pack-configurations", headers=headers, params=params
        )

    def get_pack_configuration(self, config_id, headers):
        return self._request(
            "GET", f"/api/pack-configurations/{config_id}", headers=headers
        )

    def publish_pack_configuration(self, config_id, headers):
        return self._request(
            "POST", f"/api/pack-configurations/{config_id}/publish", {}, headers
        )

    def supersede_pack_configuration(self, config_id, headers):
        return self._request(
            "POST", f"/api/pack-configurations/{config_id}/supersede", {}, headers
        )

    # -- signing sessions ---------------------------------------------------
    def create_signing_session(self, payload, headers):
        return self._request("POST", "/api/signing-sessions", payload, headers)

    def list_signing_sessions(self, headers, params=None):
        return self._request(
            "GET", "/api/signing-sessions", headers=headers, params=params
        )

    def get_signing_session(self, session_id, headers):
        return self._request(
            "GET", f"/api/signing-sessions/{session_id}", headers=headers
        )

    def prepare_signing_stock(self, session_id, headers):
        return self._request(
            "POST", f"/api/signing-sessions/{session_id}/prepare-stock", {}, headers
        )

    def ship_signing_stock(self, session_id, headers):
        return self._request(
            "POST", f"/api/signing-sessions/{session_id}/ship-stock", {}, headers
        )

    def complete_signing_session(self, session_id, payload, headers):
        return self._request(
            "POST", f"/api/signing-sessions/{session_id}/complete", payload, headers
        )

    def cancel_signing_session(self, session_id, headers):
        return self._request(
            "POST", f"/api/signing-sessions/{session_id}/cancel", {}, headers
        )

    # -- print-run decisions ------------------------------------------------
    def create_print_run_decision(self, payload, headers):
        return self._request("POST", "/api/print-run-decisions", payload, headers)

    def list_print_run_decisions(self, headers, params=None):
        return self._request(
            "GET", "/api/print-run-decisions", headers=headers, params=params
        )

    def get_print_run_decision(self, decision_id, headers):
        return self._request(
            "GET", f"/api/print-run-decisions/{decision_id}", headers=headers
        )

    def approve_print_run_decision(self, decision_id, payload, headers):
        return self._request(
            "POST", f"/api/print-run-decisions/{decision_id}/approve", payload, headers
        )

    def supersede_print_run_decision(self, decision_id, headers):
        return self._request(
            "POST", f"/api/print-run-decisions/{decision_id}/supersede", {}, headers
        )

    # -- redemptions --------------------------------------------------------
    def issue_redemption(self, set_id, payload, headers):
        return self._request(
            "POST", f"/api/card-sets/{set_id}/redemptions", payload, headers
        )

    def list_set_redemptions(self, set_id, headers, params=None):
        return self._request(
            "GET", f"/api/card-sets/{set_id}/redemptions", headers=headers, params=params
        )

    def list_redemptions(self, headers, params=None):
        return self._request("GET", "/api/redemptions", headers=headers, params=params)

    def get_redemption(self, redemption_id, headers):
        return self._request(
            "GET", f"/api/redemptions/{redemption_id}", headers=headers
        )

    def fulfill_redemption(self, redemption_id, headers):
        return self._request(
            "POST", f"/api/redemptions/{redemption_id}/fulfill", {}, headers
        )

    def close_redemption(self, redemption_id, headers):
        return self._request(
            "POST", f"/api/redemptions/{redemption_id}/close", {}, headers
        )

    def cancel_redemption(self, redemption_id, headers):
        return self._request(
            "POST", f"/api/redemptions/{redemption_id}/cancel", {}, headers
        )

    # -- collector notifications -------------------------------------------
    def serve_notification(self, redemption_id, payload, headers):
        return self._request(
            "POST", f"/api/redemptions/{redemption_id}/notifications", payload, headers
        )

    def list_redemption_notifications(self, redemption_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/redemptions/{redemption_id}/notifications",
            headers=headers,
            params=params,
        )

    def list_notifications(self, headers, params=None):
        return self._request(
            "GET", "/api/collector-notifications", headers=headers, params=params
        )

    def get_notification(self, notification_id, headers):
        return self._request(
            "GET", f"/api/collector-notifications/{notification_id}", headers=headers
        )

    def acknowledge_notification(self, notification_id, headers):
        return self._request(
            "POST",
            f"/api/collector-notifications/{notification_id}/acknowledge",
            {},
            headers,
        )

    def settle_notification(self, notification_id, payload, headers):
        return self._request(
            "POST",
            f"/api/collector-notifications/{notification_id}/settle",
            payload,
            headers,
        )

    def resolve_notification(self, notification_id, headers):
        return self._request(
            "POST", f"/api/collector-notifications/{notification_id}/resolve", {}, headers
        )

    # -- distribution allocations ------------------------------------------
    def create_allocation(self, payload, headers):
        return self._request("POST", "/api/distribution-allocations", payload, headers)

    def list_allocations(self, headers, params=None):
        return self._request(
            "GET", "/api/distribution-allocations", headers=headers, params=params
        )

    def get_allocation(self, allocation_id, headers):
        return self._request(
            "GET", f"/api/distribution-allocations/{allocation_id}", headers=headers
        )

    def mark_allocation_utf(self, allocation_id, headers):
        return self._request(
            "POST", f"/api/distribution-allocations/{allocation_id}/mark-utf", {}, headers
        )

    def ship_allocation(self, allocation_id, headers):
        return self._request(
            "POST", f"/api/distribution-allocations/{allocation_id}/ship", {}, headers
        )

    def recall_allocation(self, allocation_id, headers):
        return self._request(
            "POST", f"/api/distribution-allocations/{allocation_id}/recall", {}, headers
        )

    # -- quality claims -----------------------------------------------------
    def file_quality_claim(self, set_id, payload, headers):
        return self._request(
            "POST", f"/api/card-sets/{set_id}/quality-claims", payload, headers
        )

    def list_set_quality_claims(self, set_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/card-sets/{set_id}/quality-claims",
            headers=headers,
            params=params,
        )

    def list_quality_claims(self, headers, params=None):
        return self._request(
            "GET", "/api/quality-claims", headers=headers, params=params
        )

    def get_quality_claim(self, claim_id, headers):
        return self._request(
            "GET", f"/api/quality-claims/{claim_id}", headers=headers
        )

    def open_claim_review(self, claim_id, headers):
        return self._request(
            "POST", f"/api/quality-claims/{claim_id}/open-review", {}, headers
        )

    def approve_quality_claim(self, claim_id, headers):
        return self._request(
            "POST", f"/api/quality-claims/{claim_id}/approve", {}, headers
        )

    def deny_quality_claim(self, claim_id, headers):
        return self._request(
            "POST", f"/api/quality-claims/{claim_id}/deny", {}, headers
        )

    def credit_quality_claim(self, claim_id, headers):
        return self._request(
            "POST", f"/api/quality-claims/{claim_id}/credit", {}, headers
        )

    # -- collector complaints ----------------------------------------------
    def file_complaint(self, set_id, payload, headers):
        return self._request(
            "POST", f"/api/card-sets/{set_id}/complaints", payload, headers
        )

    def list_set_complaints(self, set_id, headers, params=None):
        return self._request(
            "GET", f"/api/card-sets/{set_id}/complaints", headers=headers, params=params
        )

    def list_complaints(self, headers, params=None):
        return self._request(
            "GET", "/api/collector-complaints", headers=headers, params=params
        )

    def get_complaint(self, complaint_id, headers):
        return self._request(
            "GET", f"/api/collector-complaints/{complaint_id}", headers=headers
        )

    def start_complaint_review(self, complaint_id, headers):
        return self._request(
            "POST", f"/api/collector-complaints/{complaint_id}/start-review", {}, headers
        )

    def approve_complaint(self, complaint_id, headers):
        return self._request(
            "POST", f"/api/collector-complaints/{complaint_id}/approve", {}, headers
        )

    def reject_complaint(self, complaint_id, headers):
        return self._request(
            "POST", f"/api/collector-complaints/{complaint_id}/reject", {}, headers
        )

    def settle_complaint(self, complaint_id, headers):
        return self._request(
            "POST", f"/api/collector-complaints/{complaint_id}/settle", {}, headers
        )


api_client = ApiClient()