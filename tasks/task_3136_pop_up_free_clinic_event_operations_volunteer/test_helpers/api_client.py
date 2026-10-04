"""API client: one method per endpoint declared in the PRD's endpoint table."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --- sites ---
    def create_site(self, payload, headers):
        return self._request("POST", "/sites", payload, headers)

    def list_sites(self, headers, params=None):
        return self._request("GET", "/sites", headers=headers, params=params)

    def get_site(self, site_id, headers):
        return self._request("GET", f"/sites/{site_id}", headers=headers)

    def vet_site(self, site_id, headers):
        return self._request("POST", f"/sites/{site_id}/vet", {}, headers)

    def retire_site(self, site_id, headers):
        return self._request("POST", f"/sites/{site_id}/retire", {}, headers)

    # --- clinic events ---
    def create_event(self, payload, headers):
        return self._request("POST", "/clinic-events", payload, headers)

    def list_events(self, headers, params=None):
        return self._request("GET", "/clinic-events", headers=headers, params=params)

    def get_event(self, event_id, headers):
        return self._request("GET", f"/clinic-events/{event_id}", headers=headers)

    def open_doors(self, event_id, headers):
        return self._request(
            "POST", f"/clinic-events/{event_id}/open-doors", {}, headers
        )

    def end_service(self, event_id, headers):
        return self._request(
            "POST", f"/clinic-events/{event_id}/end-service", {}, headers
        )

    def close_event(self, event_id, headers):
        return self._request("POST", f"/clinic-events/{event_id}/close", {}, headers)

    def cancel_event(self, event_id, headers):
        return self._request("POST", f"/clinic-events/{event_id}/cancel", {}, headers)

    # --- site agreements ---
    def create_site_agreement(self, event_id, payload, headers):
        return self._request(
            "POST", f"/clinic-events/{event_id}/site-agreements", payload, headers
        )

    def list_event_agreements(self, event_id, headers, params=None):
        return self._request(
            "GET",
            f"/clinic-events/{event_id}/site-agreements",
            headers=headers,
            params=params,
        )

    def list_site_agreements(self, headers, params=None):
        return self._request("GET", "/site-agreements", headers=headers, params=params)

    def submit_agreement(self, event_id, agreement_id, headers):
        return self._request(
            "POST",
            f"/clinic-events/{event_id}/site-agreements/{agreement_id}/submit",
            {},
            headers,
        )

    def confirm_agreement(self, event_id, agreement_id, headers):
        return self._request(
            "POST",
            f"/clinic-events/{event_id}/site-agreements/{agreement_id}/confirm",
            {},
            headers,
        )

    def reject_agreement(self, event_id, agreement_id, headers):
        return self._request(
            "POST",
            f"/clinic-events/{event_id}/site-agreements/{agreement_id}/reject",
            {},
            headers,
        )

    # --- volunteers & licensing ---
    def create_volunteer(self, payload, headers):
        return self._request("POST", "/volunteers", payload, headers)

    def list_volunteers(self, headers, params=None):
        return self._request("GET", "/volunteers", headers=headers, params=params)

    def get_volunteer(self, volunteer_id, headers):
        return self._request("GET", f"/volunteers/{volunteer_id}", headers=headers)

    def request_verification(self, volunteer_id, payload, headers):
        return self._request(
            "POST", f"/volunteers/{volunteer_id}/request-verification", payload, headers
        )

    def list_volunteer_verifications(self, volunteer_id, headers, params=None):
        return self._request(
            "GET",
            f"/volunteers/{volunteer_id}/license-verifications",
            headers=headers,
            params=params,
        )

    def list_license_verifications(self, headers, params=None):
        return self._request(
            "GET", "/license-verifications", headers=headers, params=params
        )

    def approve_verification(self, volunteer_id, verification_id, headers):
        return self._request(
            "POST",
            f"/volunteers/{volunteer_id}/license-verifications/{verification_id}/approve",
            {},
            headers,
        )

    def deny_verification(self, volunteer_id, verification_id, payload, headers):
        return self._request(
            "POST",
            f"/volunteers/{volunteer_id}/license-verifications/{verification_id}/deny",
            payload,
            headers,
        )

    def authorize_volunteer(self, volunteer_id, payload, headers):
        return self._request(
            "POST", f"/volunteers/{volunteer_id}/authorize", payload, headers
        )

    def suspend_volunteer(self, volunteer_id, payload, headers):
        return self._request(
            "POST", f"/volunteers/{volunteer_id}/suspend", payload, headers
        )

    def reinstate_volunteer(self, volunteer_id, payload, headers):
        return self._request(
            "POST", f"/volunteers/{volunteer_id}/reinstate", payload, headers
        )

    # --- discipline assignments ---
    def create_assignment(self, event_id, payload, headers):
        return self._request(
            "POST", f"/clinic-events/{event_id}/assignments", payload, headers
        )

    def list_event_assignments(self, event_id, headers, params=None):
        return self._request(
            "GET",
            f"/clinic-events/{event_id}/assignments",
            headers=headers,
            params=params,
        )

    def list_assignments(self, headers, params=None):
        return self._request("GET", "/assignments", headers=headers, params=params)

    def confirm_assignment(self, event_id, assignment_id, headers):
        return self._request(
            "POST",
            f"/clinic-events/{event_id}/assignments/{assignment_id}/confirm",
            {},
            headers,
        )

    def check_in_assignment(self, event_id, assignment_id, headers):
        return self._request(
            "POST",
            f"/clinic-events/{event_id}/assignments/{assignment_id}/check-in",
            {},
            headers,
        )

    def release_assignment(self, event_id, assignment_id, headers):
        return self._request(
            "POST",
            f"/clinic-events/{event_id}/assignments/{assignment_id}/release",
            {},
            headers,
        )

    # --- service stations ---
    def create_station(self, event_id, payload, headers):
        return self._request(
            "POST", f"/clinic-events/{event_id}/stations", payload, headers
        )

    def list_event_stations(self, event_id, headers, params=None):
        return self._request(
            "GET", f"/clinic-events/{event_id}/stations", headers=headers, params=params
        )

    def list_stations(self, headers, params=None):
        return self._request("GET", "/stations", headers=headers, params=params)

    def mark_station_set_up(self, event_id, station_id, headers):
        return self._request(
            "POST",
            f"/clinic-events/{event_id}/stations/{station_id}/mark-set-up",
            {},
            headers,
        )

    def mark_station_operational(self, event_id, station_id, headers):
        return self._request(
            "POST",
            f"/clinic-events/{event_id}/stations/{station_id}/mark-operational",
            {},
            headers,
        )

    def take_station_offline(self, event_id, station_id, headers):
        return self._request(
            "POST",
            f"/clinic-events/{event_id}/stations/{station_id}/take-offline",
            {},
            headers,
        )

    def dismantle_station(self, event_id, station_id, headers):
        return self._request(
            "POST",
            f"/clinic-events/{event_id}/stations/{station_id}/dismantle",
            {},
            headers,
        )

    # --- patient tickets ---
    def issue_ticket(self, event_id, payload, headers):
        return self._request(
            "POST", f"/clinic-events/{event_id}/tickets", payload, headers
        )

    def list_event_tickets(self, event_id, headers, params=None):
        return self._request(
            "GET", f"/clinic-events/{event_id}/tickets", headers=headers, params=params
        )

    def list_tickets(self, headers, params=None):
        return self._request("GET", "/tickets", headers=headers, params=params)

    def call_ticket(self, event_id, ticket_id, headers):
        return self._request(
            "POST", f"/clinic-events/{event_id}/tickets/{ticket_id}/call", {}, headers
        )

    def begin_service(self, event_id, ticket_id, payload, headers):
        return self._request(
            "POST",
            f"/clinic-events/{event_id}/tickets/{ticket_id}/begin-service",
            payload,
            headers,
        )

    def requeue_ticket(self, event_id, ticket_id, headers):
        return self._request(
            "POST",
            f"/clinic-events/{event_id}/tickets/{ticket_id}/requeue",
            {},
            headers,
        )

    def mark_ticket_no_show(self, event_id, ticket_id, headers):
        return self._request(
            "POST",
            f"/clinic-events/{event_id}/tickets/{ticket_id}/mark-no-show",
            {},
            headers,
        )

    def withdraw_ticket(self, event_id, ticket_id, headers):
        return self._request(
            "POST",
            f"/clinic-events/{event_id}/tickets/{ticket_id}/withdraw",
            {},
            headers,
        )

    # --- encounters & referrals ---
    def list_event_encounters(self, event_id, headers, params=None):
        return self._request(
            "GET",
            f"/clinic-events/{event_id}/encounters",
            headers=headers,
            params=params,
        )

    def list_encounters(self, headers, params=None):
        return self._request("GET", "/encounters", headers=headers, params=params)

    def complete_encounter(self, event_id, encounter_id, payload, headers):
        return self._request(
            "POST",
            f"/clinic-events/{event_id}/encounters/{encounter_id}/complete",
            payload,
            headers,
        )

    def abandon_encounter(self, event_id, encounter_id, headers):
        return self._request(
            "POST",
            f"/clinic-events/{event_id}/encounters/{encounter_id}/abandon",
            {},
            headers,
        )

    def list_encounter_referrals(self, event_id, encounter_id, headers, params=None):
        return self._request(
            "GET",
            f"/clinic-events/{event_id}/encounters/{encounter_id}/referrals",
            headers=headers,
            params=params,
        )

    def list_referrals(self, headers, params=None):
        return self._request("GET", "/referrals", headers=headers, params=params)

    # --- equipment manifests & sterilization ---
    def create_manifest(self, event_id, payload, headers):
        return self._request(
            "POST", f"/clinic-events/{event_id}/manifests", payload, headers
        )

    def list_event_manifests(self, event_id, headers, params=None):
        return self._request(
            "GET",
            f"/clinic-events/{event_id}/manifests",
            headers=headers,
            params=params,
        )

    def list_manifests(self, headers, params=None):
        return self._request("GET", "/manifests", headers=headers, params=params)

    def ship_manifest(self, event_id, manifest_id, headers):
        return self._request(
            "POST",
            f"/clinic-events/{event_id}/manifests/{manifest_id}/ship",
            {},
            headers,
        )

    def deliver_manifest(self, event_id, manifest_id, headers):
        return self._request(
            "POST",
            f"/clinic-events/{event_id}/manifests/{manifest_id}/deliver",
            {},
            headers,
        )

    def unpack_manifest(self, event_id, manifest_id, headers):
        return self._request(
            "POST",
            f"/clinic-events/{event_id}/manifests/{manifest_id}/unpack",
            {},
            headers,
        )

    def repack_manifest(self, event_id, manifest_id, headers):
        return self._request(
            "POST",
            f"/clinic-events/{event_id}/manifests/{manifest_id}/repack",
            {},
            headers,
        )

    def start_sterilization_cycle(self, event_id, payload, headers):
        return self._request(
            "POST", f"/clinic-events/{event_id}/sterilization-cycles", payload, headers
        )

    def list_event_cycles(self, event_id, headers, params=None):
        return self._request(
            "GET",
            f"/clinic-events/{event_id}/sterilization-cycles",
            headers=headers,
            params=params,
        )

    def list_cycles(self, headers, params=None):
        return self._request(
            "GET", "/sterilization-cycles", headers=headers, params=params
        )

    def complete_cycle(self, event_id, cycle_id, headers):
        return self._request(
            "POST",
            f"/clinic-events/{event_id}/sterilization-cycles/{cycle_id}/complete",
            {},
            headers,
        )

    def fail_cycle(self, event_id, cycle_id, headers):
        return self._request(
            "POST",
            f"/clinic-events/{event_id}/sterilization-cycles/{cycle_id}/fail",
            {},
            headers,
        )

    # --- reports & handoff ---
    def generate_unmet_demand_report(self, event_id, payload, headers):
        return self._request(
            "POST", f"/clinic-events/{event_id}/unmet-demand-reports", payload, headers
        )

    def list_unmet_demand_reports(self, event_id, headers, params=None):
        return self._request(
            "GET",
            f"/clinic-events/{event_id}/unmet-demand-reports",
            headers=headers,
            params=params,
        )

    def create_handoff(self, event_id, payload, headers):
        return self._request(
            "POST", f"/clinic-events/{event_id}/handoffs", payload, headers
        )

    def list_event_handoffs(self, event_id, headers, params=None):
        return self._request(
            "GET", f"/clinic-events/{event_id}/handoffs", headers=headers, params=params
        )

    def list_handoffs(self, headers, params=None):
        return self._request("GET", "/handoffs", headers=headers, params=params)

    def assemble_handoff_packet(self, event_id, handoff_id, headers):
        return self._request(
            "POST",
            f"/clinic-events/{event_id}/handoffs/{handoff_id}/assemble-packet",
            {},
            headers,
        )

    def accept_handoff(self, event_id, handoff_id, headers):
        return self._request(
            "POST",
            f"/clinic-events/{event_id}/handoffs/{handoff_id}/accept",
            {},
            headers,
        )

    def dispute_handoff(self, event_id, handoff_id, headers):
        return self._request(
            "POST",
            f"/clinic-events/{event_id}/handoffs/{handoff_id}/dispute",
            {},
            headers,
        )


api_client = ApiClient()
