"""API client: one method per operation declared in the product requirements."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Platform configuration -------------------------------------------
    def list_subscription_tiers(self, headers=None, params=None):
        return self._request("GET", "/wellness/subscription-tiers",
                             headers=headers, params=params)

    def create_subscription_tier(self, payload, headers):
        return self._request("POST", "/wellness/subscription-tiers", payload, headers)

    # --- Studios and subscriptions ----------------------------------------
    def create_studio(self, payload, headers):
        return self._request("POST", "/wellness/studios", payload, headers)

    def list_studios(self, headers, params=None):
        return self._request("GET", "/wellness/studios", headers=headers, params=params)

    def get_studio(self, studio_id, headers):
        return self._request("GET", f"/wellness/studios/{studio_id}", headers=headers)

    def cancel_studio(self, studio_id, payload, headers):
        return self._request("POST", f"/wellness/studios/{studio_id}/cancel",
                             payload, headers)

    def get_subscription(self, subscription_id, headers):
        return self._request("GET", f"/wellness/subscriptions/{subscription_id}",
                             headers=headers)

    def advance_renewal(self, subscription_id, payload, headers):
        return self._request("POST", f"/wellness/subscriptions/{subscription_id}/advance-renewal",
                             payload, headers)

    def change_tier(self, subscription_id, payload, headers):
        return self._request("POST", f"/wellness/subscriptions/{subscription_id}/change-tier",
                             payload, headers)

    def suspend_subscription(self, subscription_id, payload, headers):
        return self._request("POST", f"/wellness/subscriptions/{subscription_id}/suspend",
                             payload, headers)

    def resume_subscription(self, subscription_id, payload, headers):
        return self._request("POST", f"/wellness/subscriptions/{subscription_id}/resume",
                             payload, headers)

    def cancel_subscription(self, subscription_id, payload, headers):
        return self._request("POST", f"/wellness/subscriptions/{subscription_id}/cancel",
                             payload, headers)

    # --- Staff -------------------------------------------------------------
    def create_staff_member(self, payload, headers):
        return self._request("POST", "/wellness/staff-members", payload, headers)

    def get_staff_member(self, staff_id, headers):
        return self._request("GET", f"/wellness/staff-members/{staff_id}", headers=headers)

    def list_staff_members(self, headers, params=None):
        return self._request("GET", "/wellness/staff-members", headers=headers, params=params)

    def restrict_staff_to_substitute(self, staff_id, headers):
        return self._request("POST", f"/wellness/staff-members/{staff_id}/restrict-to-substitute",
                             {}, headers)

    def reinstate_staff(self, staff_id, headers):
        return self._request("POST", f"/wellness/staff-members/{staff_id}/reinstate",
                             {}, headers)

    def deactivate_staff(self, staff_id, payload, headers):
        return self._request("POST", f"/wellness/staff-members/{staff_id}/deactivate",
                             payload, headers)

    def list_staff_commission_entries(self, staff_id, headers, params=None):
        return self._request("GET", f"/wellness/staff-members/{staff_id}/commission-entries",
                             headers=headers, params=params)

    def list_staff_class_sessions(self, staff_id, headers, params=None):
        return self._request("GET", f"/wellness/staff-members/{staff_id}/class-sessions",
                             headers=headers, params=params)

    # --- Clients -----------------------------------------------------------
    def create_client(self, payload, headers):
        return self._request("POST", "/wellness/clients", payload, headers)

    def list_clients(self, headers, params=None):
        return self._request("GET", "/wellness/clients", headers=headers, params=params)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/wellness/clients/{client_id}", headers=headers)

    def list_client_bookings(self, client_id, headers, params=None):
        return self._request("GET", f"/wellness/clients/{client_id}/bookings",
                             headers=headers, params=params)

    def list_client_memberships(self, client_id, headers, params=None):
        return self._request("GET", f"/wellness/clients/{client_id}/memberships",
                             headers=headers, params=params)

    def list_client_class_packs(self, client_id, headers, params=None):
        return self._request("GET", f"/wellness/clients/{client_id}/class-packs",
                             headers=headers, params=params)

    def list_client_waitlist_entries(self, client_id, headers, params=None):
        return self._request("GET", f"/wellness/clients/{client_id}/waitlist-entries",
                             headers=headers, params=params)

    def list_client_portability_requests(self, client_id, headers, params=None):
        return self._request("GET", f"/wellness/clients/{client_id}/portability-requests",
                             headers=headers, params=params)

    # --- Class templates ---------------------------------------------------
    def create_class_template(self, payload, headers):
        return self._request("POST", "/wellness/class-templates", payload, headers)

    def list_class_templates(self, headers, params=None):
        return self._request("GET", "/wellness/class-templates", headers=headers, params=params)

    def get_class_template(self, template_id, headers):
        return self._request("GET", f"/wellness/class-templates/{template_id}", headers=headers)

    def list_template_sessions(self, template_id, headers, params=None):
        return self._request("GET", f"/wellness/class-templates/{template_id}/class-sessions",
                             headers=headers, params=params)

    def list_template_staff_members(self, template_id, headers, params=None):
        return self._request("GET", f"/wellness/class-templates/{template_id}/staff-members",
                             headers=headers, params=params)

    # --- Class sessions ----------------------------------------------------
    def create_class_session(self, payload, headers):
        return self._request("POST", "/wellness/class-sessions", payload, headers)

    def list_class_sessions(self, headers, params=None):
        return self._request("GET", "/wellness/class-sessions", headers=headers, params=params)

    def get_class_session(self, session_id, headers):
        return self._request("GET", f"/wellness/class-sessions/{session_id}", headers=headers)

    def update_class_session(self, session_id, payload, headers):
        return self._request("PUT", f"/wellness/class-sessions/{session_id}",
                             payload, headers)

    def cancel_class_session(self, session_id, payload, headers):
        return self._request("POST", f"/wellness/class-sessions/{session_id}/cancel",
                             payload, headers)

    def complete_class_session(self, session_id, headers):
        return self._request("POST", f"/wellness/class-sessions/{session_id}/complete",
                             {}, headers)

    def reassign_instructor(self, session_id, payload, headers):
        return self._request("POST", f"/wellness/class-sessions/{session_id}/reassign-instructor",
                             payload, headers)

    def list_eligible_instructors(self, session_id, headers, params=None):
        return self._request("GET", f"/wellness/class-sessions/{session_id}/eligible-instructors",
                             headers=headers, params=params)

    def list_session_bookings(self, session_id, headers, params=None):
        return self._request("GET", f"/wellness/class-sessions/{session_id}/bookings",
                             headers=headers, params=params)

    def list_session_waitlist_entries(self, session_id, headers, params=None):
        return self._request("GET", f"/wellness/class-sessions/{session_id}/waitlist-entries",
                             headers=headers, params=params)

    def list_session_cascade_sessions(self, session_id, headers, params=None):
        return self._request("GET", f"/wellness/class-sessions/{session_id}/class-sessions",
                             headers=headers, params=params)

    # --- Bookings ----------------------------------------------------------
    def create_booking(self, payload, headers):
        return self._request("POST", "/wellness/bookings", payload, headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/wellness/bookings", headers=headers, params=params)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/wellness/bookings/{booking_id}", headers=headers)

    def check_in_booking(self, booking_id, headers):
        return self._request("POST", f"/wellness/bookings/{booking_id}/check-in", {}, headers)

    def cancel_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/wellness/bookings/{booking_id}/cancel",
                             payload, headers)

    def restore_no_show(self, booking_id, payload, headers):
        return self._request("POST", f"/wellness/bookings/{booking_id}/restore-no-show",
                             payload, headers)

    def reverse_claim(self, booking_id, payload, headers):
        return self._request("POST", f"/wellness/bookings/{booking_id}/reverse-claim",
                             payload, headers)

    def list_booking_waitlist_entries(self, booking_id, headers, params=None):
        return self._request("GET", f"/wellness/bookings/{booking_id}/waitlist-entries",
                             headers=headers, params=params)

    def list_booking_commission_entries(self, booking_id, headers, params=None):
        return self._request("GET", f"/wellness/bookings/{booking_id}/commission-entries",
                             headers=headers, params=params)

    # --- Waitlist ----------------------------------------------------------
    def join_waitlist(self, payload, headers):
        return self._request("POST", "/wellness/waitlist-entries", payload, headers)

    def list_waitlist_entries(self, headers, params=None):
        return self._request("GET", "/wellness/waitlist-entries", headers=headers, params=params)

    def claim_waitlist_entry(self, entry_id, payload, headers):
        return self._request("POST", f"/wellness/waitlist-entries/{entry_id}/claim",
                             payload, headers)

    def cancel_waitlist_entry(self, entry_id, headers):
        return self._request("POST", f"/wellness/waitlist-entries/{entry_id}/cancel",
                             {}, headers)

    def confirm_waitlist_position(self, entry_id, headers):
        return self._request("POST", f"/wellness/waitlist-entries/{entry_id}/confirm-position",
                             {}, headers)

    def sweep_offers(self, payload, headers):
        return self._request("POST", "/wellness/waitlist-entries/sweep-offers",
                             payload, headers)

    # --- Class packs -------------------------------------------------------
    def create_class_pack(self, payload, headers):
        return self._request("POST", "/wellness/class-packs", payload, headers)

    def list_class_packs(self, headers, params=None):
        return self._request("GET", "/wellness/class-packs", headers=headers, params=params)

    def get_class_pack(self, pack_id, headers):
        return self._request("GET", f"/wellness/class-packs/{pack_id}", headers=headers)

    def extend_class_pack(self, pack_id, payload, headers):
        return self._request("POST", f"/wellness/class-packs/{pack_id}/extend",
                             payload, headers)

    def sweep_class_pack_expiry(self, pack_id, payload, headers):
        return self._request("POST", f"/wellness/class-packs/{pack_id}/sweep-expiry",
                             payload, headers)

    def list_pack_bookings(self, pack_id, headers, params=None):
        return self._request("GET", f"/wellness/class-packs/{pack_id}/bookings",
                             headers=headers, params=params)

    # --- Memberships -------------------------------------------------------
    def create_membership(self, payload, headers):
        return self._request("POST", "/wellness/memberships", payload, headers)

    def list_memberships(self, headers, params=None):
        return self._request("GET", "/wellness/memberships", headers=headers, params=params)

    def get_membership(self, membership_id, headers):
        return self._request("GET", f"/wellness/memberships/{membership_id}", headers=headers)

    def advance_membership_cycle(self, membership_id, payload, headers):
        return self._request("POST", f"/wellness/memberships/{membership_id}/advance-cycle",
                             payload, headers)

    def freeze_membership(self, membership_id, payload, headers):
        return self._request("POST", f"/wellness/memberships/{membership_id}/freeze",
                             payload, headers)

    def unfreeze_membership(self, membership_id, payload, headers):
        return self._request("POST", f"/wellness/memberships/{membership_id}/unfreeze",
                             payload, headers)

    def cancel_membership(self, membership_id, payload, headers):
        return self._request("POST", f"/wellness/memberships/{membership_id}/cancel",
                             payload, headers)

    def list_membership_bookings(self, membership_id, headers, params=None):
        return self._request("GET", f"/wellness/memberships/{membership_id}/bookings",
                             headers=headers, params=params)

    # --- Payroll -----------------------------------------------------------
    def create_payroll_period(self, payload, headers):
        return self._request("POST", "/wellness/payroll-periods", payload, headers)

    def list_payroll_periods(self, headers, params=None):
        return self._request("GET", "/wellness/payroll-periods", headers=headers, params=params)

    def get_payroll_period(self, period_id, headers):
        return self._request("GET", f"/wellness/payroll-periods/{period_id}", headers=headers)

    def close_payroll_period(self, period_id, payload, headers):
        return self._request("POST", f"/wellness/payroll-periods/{period_id}/close",
                             payload, headers)

    def reopen_payroll_period(self, period_id, payload, headers):
        return self._request("POST", f"/wellness/payroll-periods/{period_id}/reopen",
                             payload, headers)

    def list_period_commission_entries(self, period_id, headers, params=None):
        return self._request("GET", f"/wellness/payroll-periods/{period_id}/commission-entries",
                             headers=headers, params=params)

    def list_commission_entries(self, headers, params=None):
        return self._request("GET", "/wellness/commission-entries", headers=headers, params=params)

    def get_commission_entry(self, entry_id, headers):
        return self._request("GET", f"/wellness/commission-entries/{entry_id}", headers=headers)

    # --- Consumer marketplace ---------------------------------------------
    def browse_marketplace_classes(self, headers=None, params=None):
        return self._request("GET", "/wellness/marketplace/classes",
                             headers=headers, params=params)

    def get_marketplace_class(self, session_id, headers=None):
        return self._request("GET", f"/wellness/marketplace/classes/{session_id}",
                             headers=headers)

    def create_marketplace_booking(self, payload, headers):
        return self._request("POST", "/wellness/marketplace/bookings", payload, headers)

    def get_marketplace_settlement(self, headers, params=None):
        return self._request("GET", "/wellness/marketplace/settlement",
                             headers=headers, params=params)

    # --- Benefit networks --------------------------------------------------
    def create_benefit_network(self, payload, headers):
        return self._request("POST", "/wellness/benefit-networks", payload, headers)

    def list_benefit_networks(self, headers, params=None):
        return self._request("GET", "/wellness/benefit-networks", headers=headers, params=params)

    def list_benefit_network_claims(self, headers, params=None):
        return self._request("GET", "/wellness/benefit-network-claims",
                             headers=headers, params=params)

    def resubmit_benefit_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/wellness/benefit-network-claims/{claim_id}/resubmit",
                             payload, headers)

    # --- Client portability -------------------------------------------------
    def create_portability_request(self, payload, headers):
        return self._request("POST", "/wellness/portability-requests", payload, headers)

    def list_portability_requests(self, headers, params=None):
        return self._request("GET", "/wellness/portability-requests",
                             headers=headers, params=params)

    def get_portability_request(self, request_id, headers):
        return self._request("GET", f"/wellness/portability-requests/{request_id}",
                             headers=headers)

    def object_portability_request(self, request_id, payload, headers):
        return self._request("POST", f"/wellness/portability-requests/{request_id}/object",
                             payload, headers)

    def resolve_portability_release(self, request_id, payload, headers):
        return self._request("POST", f"/wellness/portability-requests/{request_id}/resolve-release",
                             payload, headers)

    def resolve_portability_deny(self, request_id, payload, headers):
        return self._request("POST", f"/wellness/portability-requests/{request_id}/resolve-deny",
                             payload, headers)

    def adjudicate_portability_request(self, request_id, payload, headers):
        return self._request("POST", f"/wellness/portability-requests/{request_id}/adjudicate",
                             payload, headers)

    def issue_portability_export(self, request_id, payload, headers):
        return self._request("POST", f"/wellness/portability-requests/{request_id}/issue-export",
                             payload, headers)

    def withdraw_portability_request(self, request_id, headers):
        return self._request("POST", f"/wellness/portability-requests/{request_id}/withdraw",
                             {}, headers)

    def download_portability_export(self, request_id, headers):
        return self._request("GET", f"/wellness/portability-requests/{request_id}/export",
                             headers=headers)

    # --- Sub-resource walkers ----------------------------------------------
    def list_studio_subscriptions(self, studio_id, headers, params=None):
        return self._request("GET", f"/wellness/studios/{studio_id}/business-subscriptions",
                             headers=headers, params=params)

    def list_studio_staff(self, studio_id, headers, params=None):
        return self._request("GET", f"/wellness/studios/{studio_id}/staff-members",
                             headers=headers, params=params)

    def list_studio_templates(self, studio_id, headers, params=None):
        return self._request("GET", f"/wellness/studios/{studio_id}/class-templates",
                             headers=headers, params=params)

    def list_studio_sessions(self, studio_id, headers, params=None):
        return self._request("GET", f"/wellness/studios/{studio_id}/class-sessions",
                             headers=headers, params=params)

    def list_studio_bookings(self, studio_id, headers, params=None):
        return self._request("GET", f"/wellness/studios/{studio_id}/bookings",
                             headers=headers, params=params)

    def list_studio_waitlist_entries(self, studio_id, headers, params=None):
        return self._request("GET", f"/wellness/studios/{studio_id}/waitlist-entries",
                             headers=headers, params=params)

    def list_studio_memberships(self, studio_id, headers, params=None):
        return self._request("GET", f"/wellness/studios/{studio_id}/memberships",
                             headers=headers, params=params)

    def list_studio_class_packs(self, studio_id, headers, params=None):
        return self._request("GET", f"/wellness/studios/{studio_id}/class-packs",
                             headers=headers, params=params)

    def list_studio_commission_entries(self, studio_id, headers, params=None):
        return self._request("GET", f"/wellness/studios/{studio_id}/commission-entries",
                             headers=headers, params=params)

    def list_studio_payroll_periods(self, studio_id, headers, params=None):
        return self._request("GET", f"/wellness/studios/{studio_id}/payroll-periods",
                             headers=headers, params=params)

    def list_studio_portability_requests(self, studio_id, headers, params=None):
        return self._request("GET", f"/wellness/studios/{studio_id}/portability-requests",
                             headers=headers, params=params)

    # --- Operator clock and injectors --------------------------------------
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def inject_client_history(self, payload, headers):
        return self._request("POST", "/_inject/client-history", payload, headers)

    def inject_client_entitlement(self, payload, headers):
        return self._request("POST", "/_inject/client-entitlement", payload, headers)


api_client = ApiClient()