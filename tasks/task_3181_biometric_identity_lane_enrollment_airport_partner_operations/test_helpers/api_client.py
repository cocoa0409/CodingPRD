"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- test-driving: clock, watchlist, billing, admin member actions ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    def update_watchlist(self, document_number, date_of_birth, action, headers):
        return self._request(
            "POST",
            "/_fraud/watchlist",
            {"document_number": document_number, "date_of_birth": date_of_birth,
             "action": action},
            headers,
        )

    def record_payment(self, invoice_id, outcome, headers):
        return self._request(
            "POST", "/_billing/record-payment",
            {"invoice_id": invoice_id, "outcome": outcome}, headers
        )

    def admin_suspend_member(self, member_id, headers):
        return self._request(
            "POST", f"/_admin/members/{member_id}/suspend", {}, headers
        )

    def admin_terminate_member(self, member_id, headers):
        return self._request(
            "POST", f"/_admin/members/{member_id}/terminate", {}, headers
        )

    # ---- airports ----
    def create_airport(self, payload, headers):
        return self._request("POST", "/airports", payload, headers)

    def list_airports(self, headers, params=None):
        return self._request("GET", "/airports", headers=headers, params=params)

    def get_airport(self, airport_id, headers):
        return self._request("GET", f"/airports/{airport_id}", headers=headers)

    def suspend_airport(self, airport_id, headers):
        return self._request("POST", f"/airports/{airport_id}/suspend", {}, headers)

    def activate_airport(self, airport_id, headers):
        return self._request("POST", f"/airports/{airport_id}/activate", {}, headers)

    # ---- partner agreements ----
    def create_agreement(self, payload, headers):
        return self._request("POST", "/partner-agreements", payload, headers)

    def list_agreements(self, headers, params=None):
        return self._request("GET", "/partner-agreements", headers=headers, params=params)

    def get_agreement(self, agreement_id, headers):
        return self._request(
            "GET", f"/partner-agreements/{agreement_id}", headers=headers
        )

    def activate_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"/partner-agreements/{agreement_id}/activate", {}, headers
        )

    def suspend_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"/partner-agreements/{agreement_id}/suspend", {}, headers
        )

    def terminate_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"/partner-agreements/{agreement_id}/terminate", {}, headers
        )

    # ---- lanes ----
    def create_lane(self, payload, headers):
        return self._request("POST", "/lanes", payload, headers)

    def list_lanes(self, headers, params=None):
        return self._request("GET", "/lanes", headers=headers, params=params)

    def get_lane(self, lane_id, headers):
        return self._request("GET", f"/lanes/{lane_id}", headers=headers)

    def open_lane(self, lane_id, headers):
        return self._request("POST", f"/lanes/{lane_id}/open", {}, headers)

    def close_lane(self, lane_id, mode, headers):
        return self._request("POST", f"/lanes/{lane_id}/close", {"mode": mode}, headers)

    # ---- kiosks ----
    def create_kiosk(self, payload, headers):
        return self._request("POST", "/kiosks", payload, headers)

    def list_kiosks(self, headers, params=None):
        return self._request("GET", "/kiosks", headers=headers, params=params)

    def get_kiosk(self, kiosk_id, headers):
        return self._request("GET", f"/kiosks/{kiosk_id}", headers=headers)

    def activate_kiosk(self, kiosk_id, headers):
        return self._request("POST", f"/kiosks/{kiosk_id}/activate", {}, headers)

    def suspend_kiosk(self, kiosk_id, headers):
        return self._request("POST", f"/kiosks/{kiosk_id}/suspend", {}, headers)

    def retire_kiosk(self, kiosk_id, headers):
        return self._request("POST", f"/kiosks/{kiosk_id}/retire", {}, headers)

    # ---- enrollment centers ----
    def create_enrollment_center(self, payload, headers):
        return self._request("POST", "/enrollment-centers", payload, headers)

    def list_enrollment_centers(self, headers, params=None):
        return self._request(
            "GET", "/enrollment-centers", headers=headers, params=params
        )

    def get_enrollment_center(self, center_id, headers):
        return self._request(
            "GET", f"/enrollment-centers/{center_id}", headers=headers
        )

    # ---- ambassadors ----
    def create_ambassador(self, payload, headers):
        return self._request("POST", "/ambassadors", payload, headers)

    def list_ambassadors(self, headers, params=None):
        return self._request("GET", "/ambassadors", headers=headers, params=params)

    def get_ambassador(self, ambassador_id, headers):
        return self._request("GET", f"/ambassadors/{ambassador_id}", headers=headers)

    def suspend_ambassador(self, ambassador_id, headers):
        return self._request(
            "POST", f"/ambassadors/{ambassador_id}/suspend", {}, headers
        )

    # ---- members ----
    def register_member(self, payload, headers):
        return self._request("POST", "/members/register", payload, headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/members", headers=headers, params=params)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def delete_member_biometrics(self, member_id, note, headers):
        return self._request(
            "POST", f"/members/{member_id}/biometric-deletion", {"note": note}, headers
        )

    def list_member_retention_logs(self, member_id, headers, params=None):
        return self._request(
            "GET", f"/members/{member_id}/biometric-retention-logs",
            headers=headers, params=params
        )

    def list_member_venue_access_events(self, member_id, headers, params=None):
        return self._request(
            "GET", f"/members/{member_id}/venue-access-events",
            headers=headers, params=params
        )

    # ---- enrollments ----
    def create_enrollment(self, payload, headers):
        return self._request("POST", "/enrollments", payload, headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/enrollments", headers=headers, params=params)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/enrollments/{enrollment_id}", headers=headers)

    def submit_document(self, enrollment_id, headers):
        return self._request(
            "POST", f"/enrollments/{enrollment_id}/submit-document", {}, headers
        )

    def capture_biometric(self, enrollment_id, headers):
        return self._request(
            "POST", f"/enrollments/{enrollment_id}/capture-biometric", {}, headers
        )

    def complete_enrollment(self, enrollment_id, headers):
        return self._request(
            "POST", f"/enrollments/{enrollment_id}/complete", {}, headers
        )

    def review_enrollment(self, enrollment_id, decision, headers):
        return self._request(
            "POST", f"/enrollments/{enrollment_id}/review",
            {"decision": decision}, headers
        )

    # ---- subscriptions & billing ----
    def create_subscription(self, payload, headers):
        return self._request("POST", "/subscriptions", payload, headers)

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", "/subscriptions", headers=headers, params=params)

    def get_subscription(self, subscription_id, headers):
        return self._request(
            "GET", f"/subscriptions/{subscription_id}", headers=headers
        )

    def attach_discount(self, subscription_id, discount_code, headers):
        return self._request(
            "POST", f"/subscriptions/{subscription_id}/attach-discount",
            {"discount_code": discount_code}, headers
        )

    def detach_discount(self, subscription_id, headers):
        return self._request(
            "POST", f"/subscriptions/{subscription_id}/detach-discount", {}, headers
        )

    def change_plan(self, subscription_id, new_plan, expected_subscription_version, headers):
        return self._request(
            "POST", f"/subscriptions/{subscription_id}/change-plan",
            {"new_plan": new_plan,
             "expected_subscription_version": expected_subscription_version},
            headers,
        )

    def cancel_subscription(self, subscription_id, headers):
        return self._request(
            "POST", f"/subscriptions/{subscription_id}/cancel", {}, headers
        )

    def run_invoice_cycle(self, subscription_id, headers):
        return self._request(
            "POST", f"/subscriptions/{subscription_id}/invoices/run-cycle", {}, headers
        )

    def list_invoices(self, subscription_id, headers, params=None):
        return self._request(
            "GET", f"/subscriptions/{subscription_id}/invoices",
            headers=headers, params=params
        )

    def get_invoice(self, invoice_id, headers):
        return self._request(
            "GET", f"/subscription-invoices/{invoice_id}", headers=headers
        )

    # ---- family groups ----
    def list_family_groups(self, headers, params=None):
        return self._request("GET", "/family-groups", headers=headers, params=params)

    def get_family_group(self, group_id, headers):
        return self._request("GET", f"/family-groups/{group_id}", headers=headers)

    def add_family_member(self, group_id, member_id, headers):
        return self._request(
            "POST", f"/family-groups/{group_id}/members",
            {"member_id": member_id}, headers
        )

    def remove_family_member(self, group_id, member_id, headers):
        return self._request(
            "DELETE", f"/family-groups/{group_id}/members/{member_id}", headers=headers
        )

    # ---- partner discounts ----
    def create_discount(self, payload, headers):
        return self._request("POST", "/partner-discounts", payload, headers)

    def list_discounts(self, headers, params=None):
        return self._request("GET", "/partner-discounts", headers=headers, params=params)

    def get_discount(self, discount_id, headers):
        return self._request("GET", f"/partner-discounts/{discount_id}", headers=headers)

    def suspend_discount(self, discount_id, headers):
        return self._request(
            "POST", f"/partner-discounts/{discount_id}/suspend", {}, headers
        )

    # ---- lane verifications ----
    def check_in(self, payload, headers):
        return self._request("POST", "/lane-verifications", payload, headers)

    def list_lane_verifications(self, headers, params=None):
        return self._request(
            "GET", "/lane-verifications", headers=headers, params=params
        )

    def get_lane_verification(self, verification_id, headers):
        return self._request(
            "GET", f"/lane-verifications/{verification_id}", headers=headers
        )

    def escort(self, verification_id, expected_member_version, headers):
        return self._request(
            "POST", f"/lane-verifications/{verification_id}/escort",
            {"expected_member_version": expected_member_version}, headers
        )

    # ---- venues & access ----
    def create_venue(self, payload, headers):
        return self._request("POST", "/venues", payload, headers)

    def list_venues(self, headers, params=None):
        return self._request("GET", "/venues", headers=headers, params=params)

    def get_venue(self, venue_id, headers):
        return self._request("GET", f"/venues/{venue_id}", headers=headers)

    def create_venue_event(self, payload, headers):
        return self._request("POST", "/venue-events", payload, headers)

    def list_venue_events(self, headers, params=None):
        return self._request("GET", "/venue-events", headers=headers, params=params)

    def get_venue_event(self, event_id, headers):
        return self._request("GET", f"/venue-events/{event_id}", headers=headers)

    def cancel_venue_event(self, event_id, headers):
        return self._request("POST", f"/venue-events/{event_id}/cancel", {}, headers)

    def record_venue_access(self, venue_id, member_id, headers):
        return self._request(
            "POST", "/venue-access",
            {"venue_id": venue_id, "member_id": member_id}, headers
        )

    def list_venue_access_events(self, headers, params=None):
        return self._request(
            "GET", "/venue-access-events", headers=headers, params=params
        )

    def list_venue_access_events_for_venue(self, venue_id, headers, params=None):
        return self._request(
            "GET", f"/venues/{venue_id}/access-events", headers=headers, params=params
        )

    # ---- identity disputes ----
    def open_dispute(self, payload, headers):
        return self._request("POST", "/identity-disputes", payload, headers)

    def list_disputes(self, headers, params=None):
        return self._request("GET", "/identity-disputes", headers=headers, params=params)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/identity-disputes/{dispute_id}", headers=headers)

    def investigate_dispute(self, dispute_id, headers):
        return self._request(
            "POST", f"/identity-disputes/{dispute_id}/investigate", {}, headers
        )

    def resolve_dispute(self, dispute_id, outcome, resolution_note, headers):
        return self._request(
            "POST", f"/identity-disputes/{dispute_id}/resolve",
            {"outcome": outcome, "resolution_note": resolution_note}, headers
        )

    # ---- biometric retention logs ----
    def list_retention_logs(self, headers, params=None):
        return self._request(
            "GET", "/biometric-retention-logs", headers=headers, params=params
        )

    # ---- settlements ----
    def create_agreement_settlement(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/partner-agreements/{agreement_id}/settlements", payload, headers
        )

    def create_venue_payout_settlement(self, venue_id, payload, headers):
        return self._request(
            "POST", f"/venues/{venue_id}/payout-settlements", payload, headers
        )

    def list_settlements(self, headers, params=None):
        return self._request(
            "GET", "/agreement-settlements", headers=headers, params=params
        )

    def get_settlement(self, settlement_id, headers):
        return self._request(
            "GET", f"/agreement-settlements/{settlement_id}", headers=headers
        )

    def finalize_settlement(self, settlement_id, headers):
        return self._request(
            "POST", f"/agreement-settlements/{settlement_id}/finalize", {}, headers
        )

    def mark_settlement_paid(self, settlement_id, headers):
        return self._request(
            "POST", f"/agreement-settlements/{settlement_id}/mark-paid", {}, headers
        )


api_client = ApiClient()
