"""API client: one method per endpoint published by the Lockbox Property Access API."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Association --------------------------------------------------------
    def create_association(self, payload, headers):
        return self._request("POST", "/associations", payload, headers)

    def get_association(self, association_id, headers):
        return self._request("GET", f"/associations/{association_id}", headers=headers)

    def get_recovery_summary(self, association_id, headers, params=None):
        return self._request(
            "GET",
            f"/associations/{association_id}/recovery-summary",
            headers=headers,
            params=params,
        )

    def run_compliance_checkpoint(self, association_id, headers):
        return self._request(
            "POST", f"/associations/{association_id}/compliance-runs", {}, headers
        )

    # ---- Member -------------------------------------------------------------
    def create_member(self, payload, headers):
        return self._request("POST", "/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/members", headers=headers, params=params)

    def member_event(self, member_id, payload, headers):
        return self._request(
            "POST", f"/members/{member_id}/membership-events", payload, headers
        )

    # ---- Contractor ---------------------------------------------------------
    def create_contractor(self, payload, headers):
        return self._request("POST", "/contractors", payload, headers)

    def get_contractor(self, contractor_id, headers):
        return self._request("GET", f"/contractors/{contractor_id}", headers=headers)

    def list_contractors(self, headers, params=None):
        return self._request("GET", "/contractors", headers=headers, params=params)

    def contractor_state(self, contractor_id, payload, headers):
        return self._request(
            "POST", f"/contractors/{contractor_id}/state", payload, headers
        )

    # ---- Lockbox ------------------------------------------------------------
    def create_lockbox(self, payload, headers):
        return self._request("POST", "/lockboxes", payload, headers)

    def get_lockbox(self, lockbox_id, headers):
        return self._request("GET", f"/lockboxes/{lockbox_id}", headers=headers)

    def list_lockboxes(self, headers, params=None):
        return self._request("GET", "/lockboxes", headers=headers, params=params)

    def lockbox_state(self, lockbox_id, payload, headers):
        return self._request("POST", f"/lockboxes/{lockbox_id}/state", payload, headers)

    # ---- Listing ------------------------------------------------------------
    def create_listing(self, payload, headers):
        return self._request("POST", "/listings", payload, headers)

    def get_listing(self, listing_id, headers):
        return self._request("GET", f"/listings/{listing_id}", headers=headers)

    def list_listings(self, headers, params=None):
        return self._request("GET", "/listings", headers=headers, params=params)

    def listing_state(self, listing_id, payload, headers):
        return self._request("POST", f"/listings/{listing_id}/state", payload, headers)

    # ---- Lockbox placement --------------------------------------------------
    def create_placement(self, payload, headers):
        return self._request("POST", "/lockbox-placements", payload, headers)

    def get_placement(self, placement_id, headers):
        return self._request(
            "GET", f"/lockbox-placements/{placement_id}", headers=headers
        )

    def list_placements(self, headers, params=None):
        return self._request(
            "GET", "/lockbox-placements", headers=headers, params=params
        )

    def placement_state(self, placement_id, payload, headers):
        return self._request(
            "POST", f"/lockbox-placements/{placement_id}/state", payload, headers
        )

    # ---- Access credential --------------------------------------------------
    def create_credential(self, payload, headers):
        return self._request("POST", "/access-credentials", payload, headers)

    def get_credential(self, credential_id, headers):
        return self._request(
            "GET", f"/access-credentials/{credential_id}", headers=headers
        )

    def list_credentials(self, headers, params=None):
        return self._request(
            "GET", "/access-credentials", headers=headers, params=params
        )

    def credential_state(self, credential_id, payload, headers):
        return self._request(
            "POST", f"/access-credentials/{credential_id}/state", payload, headers
        )

    # ---- Access grant -------------------------------------------------------
    def create_grant(self, payload, headers):
        return self._request("POST", "/access-grants", payload, headers)

    def get_grant(self, grant_id, headers):
        return self._request("GET", f"/access-grants/{grant_id}", headers=headers)

    def list_grants(self, headers, params=None):
        return self._request("GET", "/access-grants", headers=headers, params=params)

    def grant_state(self, grant_id, payload, headers):
        return self._request(
            "POST", f"/access-grants/{grant_id}/state", payload, headers
        )

    # ---- Showing appointment ------------------------------------------------
    def create_showing(self, payload, headers):
        return self._request("POST", "/showing-appointments", payload, headers)

    def get_showing(self, appointment_id, headers):
        return self._request(
            "GET", f"/showing-appointments/{appointment_id}", headers=headers
        )

    def list_showings(self, headers, params=None):
        return self._request(
            "GET", "/showing-appointments", headers=headers, params=params
        )

    def showing_state(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"/showing-appointments/{appointment_id}/state", payload, headers
        )

    # ---- Access log ---------------------------------------------------------
    def device_access_attempt(self, payload, headers):
        return self._request("POST", "/_devices/access-attempts", payload, headers)

    def get_access_event(self, event_id, headers):
        return self._request("GET", f"/access-events/{event_id}", headers=headers)

    def list_access_events(self, headers, params=None):
        return self._request("GET", "/access-events", headers=headers, params=params)

    # ---- Incident review ----------------------------------------------------
    def create_incident_review(self, payload, headers):
        return self._request("POST", "/incident-reviews", payload, headers)

    def get_incident_review(self, review_id, headers):
        return self._request("GET", f"/incident-reviews/{review_id}", headers=headers)

    def list_incident_reviews(self, headers, params=None):
        return self._request("GET", "/incident-reviews", headers=headers, params=params)

    def incident_review_state(self, review_id, payload, headers):
        return self._request(
            "POST", f"/incident-reviews/{review_id}/state", payload, headers
        )

    # ---- Billing charge -----------------------------------------------------
    def get_billing_charge(self, charge_id, headers):
        return self._request("GET", f"/billing-charges/{charge_id}", headers=headers)

    def list_billing_charges(self, headers, params=None):
        return self._request("GET", "/billing-charges", headers=headers, params=params)

    def billing_charge_state(self, charge_id, payload, headers):
        return self._request(
            "POST", f"/billing-charges/{charge_id}/state", payload, headers
        )

    # ---- Logical clock ------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
