"""API client: one method per endpoint defined in the PRD.

All paths are mounted under the ``/car-share`` prefix except the test-driving
capabilities, which sit at the server root.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Member lifecycle ────────────────────────────────
    def register_member(self, payload, headers):
        return self._request("POST", "/car-share/member-registrations", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/car-share/members/{member_id}", headers=headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/car-share/members", headers=headers, params=params)

    def submit_driving_record_report(self, member_id, payload, headers):
        return self._request(
            "POST", f"/car-share/members/{member_id}/driving-record-reports", payload, headers
        )

    def record_report_decision(self, report_id, payload, headers):
        return self._request(
            "POST", f"/car-share/driving-record-reports/{report_id}/decision", payload, headers
        )

    def decide_application(self, member_id, payload, headers):
        return self._request(
            "POST", f"/car-share/members/{member_id}/application-decision", payload, headers
        )

    def reopen_application(self, member_id, headers, payload=None):
        return self._request(
            "POST", f"/car-share/members/{member_id}/reopen-application", payload or {}, headers
        )

    def adjust_wallet(self, member_id, payload, headers):
        return self._request(
            "POST", f"/car-share/members/{member_id}/wallet-adjustments", payload, headers
        )

    def list_member_memberships(self, member_id, headers, params=None):
        return self._request(
            "GET", f"/car-share/members/{member_id}/memberships", headers=headers, params=params
        )

    def list_member_reports(self, member_id, headers, params=None):
        return self._request(
            "GET",
            f"/car-share/members/{member_id}/driving-record-reports",
            headers=headers,
            params=params,
        )

    def list_member_access_events(self, member_id, headers, params=None):
        return self._request(
            "GET", f"/car-share/members/{member_id}/access-events", headers=headers, params=params
        )

    def list_member_signals(self, member_id, headers, params=None):
        return self._request(
            "GET",
            f"/car-share/members/{member_id}/community-signals",
            headers=headers,
            params=params,
        )

    def list_member_incidents(self, member_id, headers, params=None):
        return self._request(
            "GET", f"/car-share/members/{member_id}/incidents", headers=headers, params=params
        )

    def list_member_entitlements(self, member_id, headers, params=None):
        return self._request(
            "GET",
            f"/car-share/members/{member_id}/tier-restore-entitlements",
            headers=headers,
            params=params,
        )

    # ─── Accounts ────────────────────────────────────────
    def list_accounts(self, headers, params=None):
        return self._request("GET", "/car-share/accounts", headers=headers, params=params)

    def create_account(self, payload, headers):
        return self._request("POST", "/car-share/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/car-share/accounts/{account_id}", headers=headers)

    def list_account_memberships(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/car-share/accounts/{account_id}/memberships", headers=headers, params=params
        )

    def list_account_members(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/car-share/accounts/{account_id}/members", headers=headers, params=params
        )

    # ─── Memberships ─────────────────────────────────────
    def list_memberships(self, headers, params=None):
        return self._request("GET", "/car-share/memberships", headers=headers, params=params)

    def create_membership(self, payload, headers):
        return self._request("POST", "/car-share/memberships", payload, headers)

    def get_membership(self, membership_id, headers):
        return self._request("GET", f"/car-share/memberships/{membership_id}", headers=headers)

    def list_membership_entitlements(self, membership_id, headers, params=None):
        return self._request(
            "GET",
            f"/car-share/memberships/{membership_id}/tier-restore-entitlements",
            headers=headers,
            params=params,
        )

    def list_tier_restore_entitlements(self, headers, params=None):
        return self._request(
            "GET", "/car-share/tier-restore-entitlements", headers=headers, params=params
        )

    def create_tier_restore_entitlement(self, membership_id, payload, headers):
        return self._request(
            "POST",
            f"/car-share/memberships/{membership_id}/tier-restore-entitlements",
            payload,
            headers,
        )

    def suspend_membership(self, membership_id, headers, payload=None):
        return self._request(
            "POST", f"/car-share/memberships/{membership_id}/suspend", payload or {}, headers
        )

    def reinstate_membership(self, membership_id, headers, payload=None):
        return self._request(
            "POST", f"/car-share/memberships/{membership_id}/reinstate", payload or {}, headers
        )

    def thaw_membership(self, membership_id, headers, payload=None):
        return self._request(
            "POST", f"/car-share/memberships/{membership_id}/thaw", payload or {}, headers
        )

    def close_membership(self, membership_id, headers, payload=None):
        return self._request(
            "POST", f"/car-share/memberships/{membership_id}/close", payload or {}, headers
        )

    # ─── Pods ────────────────────────────────────────────
    def list_pods(self, headers, params=None):
        return self._request("GET", "/car-share/pods", headers=headers, params=params)

    def create_pod(self, payload, headers):
        return self._request("POST", "/car-share/pods", payload, headers)

    def get_pod(self, pod_id, headers):
        return self._request("GET", f"/car-share/pods/{pod_id}", headers=headers)

    def reclassify_pod(self, pod_id, payload, headers):
        return self._request("POST", f"/car-share/pods/{pod_id}/reclassify", payload, headers)

    def list_pod_vehicles(self, pod_id, headers, params=None):
        return self._request(
            "GET", f"/car-share/pods/{pod_id}/vehicles", headers=headers, params=params
        )

    def list_pod_signals(self, pod_id, headers, params=None):
        return self._request(
            "GET", f"/car-share/pods/{pod_id}/community-signals", headers=headers, params=params
        )

    def list_pod_reservations(self, pod_id, headers, params=None):
        return self._request(
            "GET", f"/car-share/pods/{pod_id}/reservations", headers=headers, params=params
        )

    def list_pod_maintenance_orders(self, pod_id, headers, params=None):
        return self._request(
            "GET", f"/car-share/pods/{pod_id}/maintenance-orders", headers=headers, params=params
        )

    def list_pod_access_events(self, pod_id, headers, params=None):
        return self._request(
            "GET", f"/car-share/pods/{pod_id}/access-events", headers=headers, params=params
        )

    def list_pod_shift_bundles(self, pod_id, headers, params=None):
        return self._request(
            "GET", f"/car-share/pods/{pod_id}/shift-bundles", headers=headers, params=params
        )

    # ─── Vehicles ────────────────────────────────────────
    def create_vehicle(self, payload, headers):
        return self._request("POST", "/car-share/vehicles", payload, headers)

    def get_vehicle(self, vehicle_id, headers):
        return self._request("GET", f"/car-share/vehicles/{vehicle_id}", headers=headers)

    def list_vehicles(self, headers, params=None):
        return self._request("GET", "/car-share/vehicles", headers=headers, params=params)

    def post_availability_event(self, vehicle_id, payload, headers):
        return self._request(
            "POST", f"/car-share/vehicles/{vehicle_id}/availability-events", payload, headers
        )

    def restore_cleanliness(self, vehicle_id, headers, payload=None):
        return self._request(
            "POST", f"/car-share/vehicles/{vehicle_id}/cleanliness-restore", payload or {}, headers
        )

    def list_vehicle_maintenance_orders(self, vehicle_id, headers, params=None):
        return self._request(
            "GET",
            f"/car-share/vehicles/{vehicle_id}/maintenance-orders",
            headers=headers,
            params=params,
        )

    def list_vehicle_access_events(self, vehicle_id, headers, params=None):
        return self._request(
            "GET", f"/car-share/vehicles/{vehicle_id}/access-events", headers=headers, params=params
        )

    def list_vehicle_fuel_transactions(self, vehicle_id, headers, params=None):
        return self._request(
            "GET",
            f"/car-share/vehicles/{vehicle_id}/fuel-card-transactions",
            headers=headers,
            params=params,
        )

    # ─── Shift bundles ───────────────────────────────────
    def apply_shift_bundle(self, payload, headers):
        return self._request("POST", "/car-share/shift-bundles", payload, headers)

    def list_shift_bundles(self, headers, params=None):
        return self._request("GET", "/car-share/shift-bundles", headers=headers, params=params)

    # ─── Reservations ────────────────────────────────────
    def create_reservation(self, payload, headers):
        return self._request("POST", "/car-share/reservations", payload, headers)

    def list_reservations(self, headers, params=None):
        return self._request("GET", "/car-share/reservations", headers=headers, params=params)

    def get_reservation(self, reservation_id, headers):
        return self._request("GET", f"/car-share/reservations/{reservation_id}", headers=headers)

    def cancel_reservation(self, reservation_id, headers, payload=None):
        return self._request(
            "POST", f"/car-share/reservations/{reservation_id}/cancel", payload or {}, headers
        )

    def return_reservation(self, reservation_id, payload, headers):
        return self._request(
            "POST", f"/car-share/reservations/{reservation_id}/return", payload, headers
        )

    def close_reservation(self, reservation_id, headers, payload=None):
        return self._request(
            "POST", f"/car-share/reservations/{reservation_id}/close", payload or {}, headers
        )

    def reopen_overdue(self, reservation_id, headers, payload=None):
        return self._request(
            "POST", f"/car-share/reservations/{reservation_id}/reopen-overdue", payload or {}, headers
        )

    def resolve_overdue(self, reservation_id, headers, payload=None):
        return self._request(
            "POST", f"/car-share/reservations/{reservation_id}/resolve-overdue", payload or {}, headers
        )

    def list_reservation_access_events(self, reservation_id, headers, params=None):
        return self._request(
            "GET", f"/car-share/reservations/{reservation_id}/access-events", headers=headers, params=params
        )

    # ─── Incidents ───────────────────────────────────────
    def create_incident(self, payload, headers):
        return self._request("POST", "/car-share/incidents", payload, headers)

    def list_incidents(self, headers, params=None):
        return self._request("GET", "/car-share/incidents", headers=headers, params=params)

    def get_incident(self, incident_id, headers):
        return self._request("GET", f"/car-share/incidents/{incident_id}", headers=headers)

    def party_split(self, incident_id, payload, headers):
        return self._request("POST", f"/car-share/incidents/{incident_id}/party-split", payload, headers)

    def get_party_split(self, incident_id, headers):
        return self._request("GET", f"/car-share/incidents/{incident_id}/party-split", headers=headers)

    def create_incident_maintenance_order(self, incident_id, payload, headers):
        return self._request(
            "POST", f"/car-share/incidents/{incident_id}/maintenance-orders", payload, headers
        )

    def list_incident_maintenance_orders(self, incident_id, headers, params=None):
        return self._request(
            "GET", f"/car-share/incidents/{incident_id}/maintenance-orders", headers=headers, params=params
        )

    def waive_incident_fee(self, incident_id, payload, headers):
        return self._request("POST", f"/car-share/incidents/{incident_id}/waive-fee", payload, headers)

    # ─── Maintenance orders ──────────────────────────────
    def create_maintenance_order(self, payload, headers):
        return self._request("POST", "/car-share/maintenance-orders", payload, headers)

    def list_maintenance_orders(self, headers, params=None):
        return self._request("GET", "/car-share/maintenance-orders", headers=headers, params=params)

    def get_maintenance_order(self, order_id, headers):
        return self._request("GET", f"/car-share/maintenance-orders/{order_id}", headers=headers)

    def start_maintenance_order(self, order_id, headers, payload=None):
        return self._request(
            "POST", f"/car-share/maintenance-orders/{order_id}/start", payload or {}, headers
        )

    def complete_maintenance_order(self, order_id, headers, payload=None):
        return self._request(
            "POST", f"/car-share/maintenance-orders/{order_id}/complete", payload or {}, headers
        )

    def cancel_maintenance_order(self, order_id, payload, headers):
        return self._request("POST", f"/car-share/maintenance-orders/{order_id}/cancel", payload, headers)

    # ─── Access events ───────────────────────────────────
    def create_access_event(self, payload, headers):
        return self._request("POST", "/car-share/access-events", payload, headers)

    def list_access_events(self, headers, params=None):
        return self._request("GET", "/car-share/access-events", headers=headers, params=params)

    def get_access_event(self, event_id, headers):
        return self._request("GET", f"/car-share/access-events/{event_id}", headers=headers)

    def retry_access_event(self, event_id, headers, payload=None):
        return self._request(
            "POST", f"/car-share/access-events/{event_id}/retry", payload or {}, headers
        )

    def report_lockout(self, event_id, headers, payload=None):
        return self._request(
            "POST", f"/car-share/access-events/{event_id}/lockout-report", payload or {}, headers
        )

    # ─── Fuel card ───────────────────────────────────────
    def create_fuel_transaction(self, payload, headers):
        return self._request("POST", "/car-share/fuel-card-transactions", payload, headers)

    def list_fuel_transactions(self, headers, params=None):
        return self._request("GET", "/car-share/fuel-card-transactions", headers=headers, params=params)

    def get_fuel_transaction(self, transaction_id, headers):
        return self._request("GET", f"/car-share/fuel-card-transactions/{transaction_id}", headers=headers)

    def reverse_fuel_transaction(self, transaction_id, headers, payload=None):
        return self._request(
            "POST", f"/car-share/fuel-card-transactions/{transaction_id}/reverse", payload or {}, headers
        )

    # ─── Community signals ───────────────────────────────
    def create_community_signal(self, payload, headers):
        return self._request("POST", "/car-share/community-signals", payload, headers)

    def get_community_signal(self, signal_id, headers):
        return self._request("GET", f"/car-share/community-signals/{signal_id}", headers=headers)

    def list_community_signals(self, headers, params=None):
        return self._request("GET", "/car-share/community-signals", headers=headers, params=params)

    # ─── Citations ───────────────────────────────────────
    def validate_citation_signature(self, citation_id, payload, headers):
        return self._request("POST", f"/car-share/citations/{citation_id}/validate-signature", payload, headers)

    # ─── Test-driving capabilities ───────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    def simulate_payment(self, payload, headers):
        return self._request("POST", "/_payments/simulate", payload, headers)

    def issue_citation(self, payload, headers):
        return self._request("POST", "/_citations/issue", payload, headers)


api_client = ApiClient()