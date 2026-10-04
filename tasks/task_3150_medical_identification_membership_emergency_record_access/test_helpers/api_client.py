"""API client: one method per endpoint of the medical identification API."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Test-driving: logical clock and reminder dispatch -------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/medical-id/_clock/set_current_utc", payload, headers)

    def dispatch_reminders(self, headers):
        return self._request("POST", "/medical-id/_reminders/dispatch", {}, headers)

    # --- Members ---------------------------------------------------------------
    def create_member(self, payload, headers):
        return self._request("POST", "/medical-id/members", payload, headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/medical-id/members", headers=headers, params=params)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/medical-id/members/{member_id}", headers=headers)

    def renew_member(self, member_id, payload, headers):
        return self._request("POST", f"/medical-id/members/{member_id}/renew", payload, headers)

    def cancel_member(self, member_id, headers):
        return self._request("POST", f"/medical-id/members/{member_id}/cancel", {}, headers)

    # --- Guardian links ----------------------------------------------------------
    def create_guardian_link(self, member_id, payload, headers):
        return self._request("POST", f"/medical-id/members/{member_id}/guardian-links", payload, headers)

    def list_member_guardian_links(self, member_id, headers, params=None):
        return self._request("GET", f"/medical-id/members/{member_id}/guardian-links", headers=headers, params=params)

    def list_member_guardianships(self, member_id, headers, params=None):
        return self._request("GET", f"/medical-id/members/{member_id}/guardianships", headers=headers, params=params)

    def list_guardian_links(self, headers, params=None):
        return self._request("GET", "/medical-id/guardian-links", headers=headers, params=params)

    def get_guardian_link(self, link_id, headers):
        return self._request("GET", f"/medical-id/guardian-links/{link_id}", headers=headers)

    def revoke_guardian_link(self, link_id, headers):
        return self._request("POST", f"/medical-id/guardian-links/{link_id}/revoke", {}, headers)

    # --- Medical record items ------------------------------------------------------
    def create_record_item(self, member_id, payload, headers):
        return self._request("POST", f"/medical-id/members/{member_id}/record-items", payload, headers)

    def list_record_items(self, member_id, headers, params=None):
        return self._request("GET", f"/medical-id/members/{member_id}/record-items", headers=headers, params=params)

    def get_record_item(self, member_id, item_id, headers):
        return self._request("GET", f"/medical-id/members/{member_id}/record-items/{item_id}", headers=headers)

    def get_record_item_flat(self, item_id, headers):
        return self._request("GET", f"/medical-id/record-items/{item_id}", headers=headers)

    def list_record_items_flat(self, headers, params=None):
        return self._request("GET", "/medical-id/record-items", headers=headers, params=params)

    def submit_record_item_for_verification(self, member_id, item_id, payload, headers):
        return self._request(
            "POST",
            f"/medical-id/members/{member_id}/record-items/{item_id}/submit-for-verification",
            payload,
            headers,
        )

    def supersede_record_item(self, member_id, item_id, payload, headers):
        return self._request(
            "POST",
            f"/medical-id/members/{member_id}/record-items/{item_id}/supersede",
            payload,
            headers,
        )

    def list_item_tickets(self, member_id, item_id, headers, params=None):
        return self._request(
            "GET",
            f"/medical-id/members/{member_id}/record-items/{item_id}/tickets",
            headers=headers,
            params=params,
        )

    # --- Verification tickets -------------------------------------------------------
    def list_verification_tickets(self, headers, params=None):
        return self._request("GET", "/medical-id/verification-tickets", headers=headers, params=params)

    def get_verification_ticket(self, ticket_id, headers):
        return self._request("GET", f"/medical-id/verification-tickets/{ticket_id}", headers=headers)

    def resolve_verification_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/medical-id/verification-tickets/{ticket_id}/resolve", payload, headers)

    # --- Emergency contacts ----------------------------------------------------------
    def create_contact(self, member_id, payload, headers):
        return self._request("POST", f"/medical-id/members/{member_id}/contacts", payload, headers)

    def list_contacts(self, member_id, headers, params=None):
        return self._request("GET", f"/medical-id/members/{member_id}/contacts", headers=headers, params=params)

    def get_contact(self, contact_id, headers):
        return self._request("GET", f"/medical-id/contacts/{contact_id}", headers=headers)

    def list_contacts_flat(self, headers, params=None):
        return self._request("GET", "/medical-id/contacts", headers=headers, params=params)

    def remove_contact(self, member_id, contact_id, headers):
        return self._request("POST", f"/medical-id/members/{member_id}/contacts/{contact_id}/remove", {}, headers)

    # --- Advance directives ------------------------------------------------------------
    def create_directive(self, member_id, payload, headers):
        return self._request("POST", f"/medical-id/members/{member_id}/directives", payload, headers)

    def list_directives(self, member_id, headers, params=None):
        return self._request("GET", f"/medical-id/members/{member_id}/directives", headers=headers, params=params)

    def get_directive(self, directive_id, headers):
        return self._request("GET", f"/medical-id/directives/{directive_id}", headers=headers)

    def list_directives_flat(self, headers, params=None):
        return self._request("GET", "/medical-id/directives", headers=headers, params=params)

    def revoke_directive(self, member_id, directive_id, headers):
        return self._request("POST", f"/medical-id/members/{member_id}/directives/{directive_id}/revoke", {}, headers)

    # --- Product catalog -----------------------------------------------------------------
    def create_product(self, payload, headers):
        return self._request("POST", "/medical-id/products", payload, headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/medical-id/products", headers=headers, params=params)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/medical-id/products/{product_id}", headers=headers)

    # --- Product orders ---------------------------------------------------------------------
    def create_order(self, member_id, payload, headers):
        return self._request("POST", f"/medical-id/members/{member_id}/orders", payload, headers)

    def list_orders(self, member_id, headers, params=None):
        return self._request("GET", f"/medical-id/members/{member_id}/orders", headers=headers, params=params)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/medical-id/orders/{order_id}", headers=headers)

    def list_orders_flat(self, headers, params=None):
        return self._request("GET", "/medical-id/orders", headers=headers, params=params)

    def confirm_order(self, member_id, order_id, payload, headers):
        return self._request("POST", f"/medical-id/members/{member_id}/orders/{order_id}/confirm", payload, headers)

    def engrave_order(self, member_id, order_id, headers):
        return self._request("POST", f"/medical-id/members/{member_id}/orders/{order_id}/engrave", {}, headers)

    def ship_order(self, member_id, order_id, headers):
        return self._request("POST", f"/medical-id/members/{member_id}/orders/{order_id}/ship", {}, headers)

    def cancel_order(self, member_id, order_id, headers):
        return self._request("POST", f"/medical-id/members/{member_id}/orders/{order_id}/cancel", {}, headers)

    # --- Responder credentials -----------------------------------------------------------------
    def create_responder(self, payload, headers):
        return self._request("POST", "/medical-id/responders", payload, headers)

    def list_responders(self, headers, params=None):
        return self._request("GET", "/medical-id/responders", headers=headers, params=params)

    def get_responder(self, responder_id, headers):
        return self._request("GET", f"/medical-id/responders/{responder_id}", headers=headers)

    def revoke_responder(self, responder_id, headers):
        return self._request("POST", f"/medical-id/responders/{responder_id}/revoke", {}, headers)

    # --- Access events ----------------------------------------------------------------------------
    def create_access_event(self, payload, headers):
        return self._request("POST", "/medical-id/access-events", payload, headers)

    def list_member_access_events(self, member_id, headers, params=None):
        return self._request("GET", f"/medical-id/members/{member_id}/access-events", headers=headers, params=params)

    def get_access_event(self, event_id, headers):
        return self._request("GET", f"/medical-id/access-events/{event_id}", headers=headers)

    def list_access_events(self, headers, params=None):
        return self._request("GET", "/medical-id/access-events", headers=headers, params=params)

    # --- Wandering cases ----------------------------------------------------------------------------
    def create_wandering_case(self, member_id, payload, headers):
        return self._request("POST", f"/medical-id/members/{member_id}/wandering-cases", payload, headers)

    def list_wandering_cases(self, member_id, headers, params=None):
        return self._request("GET", f"/medical-id/members/{member_id}/wandering-cases", headers=headers, params=params)

    def list_wandering_cases_flat(self, headers, params=None):
        return self._request("GET", "/medical-id/wandering-cases", headers=headers, params=params)

    def get_wandering_case(self, case_id, headers):
        return self._request("GET", f"/medical-id/wandering-cases/{case_id}", headers=headers)

    def resolve_wandering_case(self, member_id, case_id, payload, headers):
        return self._request(
            "POST",
            f"/medical-id/members/{member_id}/wandering-cases/{case_id}/resolve",
            payload,
            headers,
        )

    # --- Reminders ------------------------------------------------------------------------------------
    def list_reminders(self, headers, params=None):
        return self._request("GET", "/medical-id/reminders", headers=headers, params=params)

    def get_reminder(self, reminder_id, headers):
        return self._request("GET", f"/medical-id/reminders/{reminder_id}", headers=headers)

    def list_member_reminders(self, member_id, headers, params=None):
        return self._request("GET", f"/medical-id/members/{member_id}/reminders", headers=headers, params=params)

    # --- Disputes ----------------------------------------------------------------------------------------
    def create_dispute(self, member_id, payload, headers):
        return self._request("POST", f"/medical-id/members/{member_id}/disputes", payload, headers)

    def list_disputes(self, member_id, headers, params=None):
        return self._request("GET", f"/medical-id/members/{member_id}/disputes", headers=headers, params=params)

    def list_disputes_flat(self, headers, params=None):
        return self._request("GET", "/medical-id/disputes", headers=headers, params=params)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/medical-id/disputes/{dispute_id}", headers=headers)

    def claim_dispute_for_review(self, dispute_id, headers):
        return self._request("POST", f"/medical-id/disputes/{dispute_id}/claim-for-review", {}, headers)

    def return_dispute_to_queue(self, dispute_id, headers):
        return self._request("POST", f"/medical-id/disputes/{dispute_id}/return-to-queue", {}, headers)

    def resolve_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/medical-id/disputes/{dispute_id}/resolve", payload, headers)

    def dismiss_dispute(self, dispute_id, headers):
        return self._request("POST", f"/medical-id/disputes/{dispute_id}/dismiss", {}, headers)

    # --- Audit events --------------------------------------------------------------------------------------
    def list_audit_events(self, headers, params=None):
        return self._request("GET", "/medical-id/audit-events", headers=headers, params=params)

    def get_audit_event(self, event_id, headers):
        return self._request("GET", f"/medical-id/audit-events/{event_id}", headers=headers)

    def list_member_audit_events(self, member_id, headers, params=None):
        return self._request("GET", f"/medical-id/members/{member_id}/audit-events", headers=headers, params=params)


api_client = ApiClient()
