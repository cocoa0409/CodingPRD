"""API client: one method per endpoint of the research API.

Every method accepts an optional `headers` argument; when it is omitted the
client falls back to the platform-administrator identity, which is authorized
for every read endpoint.
"""
from prd_bench_local_runner.testing import GenericApiClient

from .test_users import TEST_USERS

_DEFAULT_HEADERS = TEST_USERS["platform_admin_headers"]


def _h(headers=None):
    """Resolve the auth headers for a call, defaulting to PlatformAdmin."""
    return headers if headers is not None else _DEFAULT_HEADERS


class ApiClient(GenericApiClient):
    # ── Logical clock ─────────────────────────────────────────────
    def set_clock(self, current_utc, headers=None):
        """Advance the logical clock; the one operation needing no auth headers."""
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, _h(headers)
        )

    # ── ClientAccount ─────────────────────────────────────────────
    def create_client(self, payload, headers=None):
        return self._request("POST", "/research/clients", payload, _h(headers))

    def get_client(self, client_id, headers=None):
        return self._request("GET", f"/research/clients/{client_id}", headers=_h(headers))

    def create_renewal_decision(self, client_id, payload, headers=None):
        return self._request(
            "POST", f"/research/clients/{client_id}/renewal-decisions", payload, _h(headers)
        )

    # ── Seat ──────────────────────────────────────────────────────
    def create_seat(self, payload, headers=None):
        return self._request("POST", "/research/seats", payload, _h(headers))

    def get_seat(self, seat_id, headers=None):
        return self._request("GET", f"/research/seats/{seat_id}", headers=_h(headers))

    def list_seats(self, headers=None, params=None):
        return self._request("GET", "/research/seats", headers=_h(headers), params=params)

    def activate_seat(self, seat_id, headers=None):
        return self._request("POST", f"/research/seats/{seat_id}/activate", {}, _h(headers))

    def revoke_seat(self, seat_id, headers=None):
        return self._request("POST", f"/research/seats/{seat_id}/revoke", {}, _h(headers))

    # ── Analyst ───────────────────────────────────────────────────
    def create_analyst(self, payload, headers=None):
        return self._request("POST", "/research/analysts", payload, _h(headers))

    def get_analyst(self, analyst_id, headers=None):
        return self._request("GET", f"/research/analysts/{analyst_id}", headers=_h(headers))

    def list_analysts(self, headers=None, params=None):
        return self._request("GET", "/research/analysts", headers=_h(headers), params=params)

    # ── InquiryRequest ────────────────────────────────────────────
    def create_inquiry(self, payload, headers=None):
        return self._request("POST", "/research/inquiry-requests", payload, _h(headers))

    def get_inquiry(self, inquiry_id, headers=None):
        return self._request("GET", f"/research/inquiry-requests/{inquiry_id}", headers=_h(headers))

    def list_inquiries(self, headers=None, params=None):
        return self._request(
            "GET", "/research/inquiry-requests", headers=_h(headers), params=params
        )

    def schedule_inquiry(self, inquiry_id, payload, headers=None):
        return self._request(
            "POST", f"/research/inquiry-requests/{inquiry_id}/schedule", payload, _h(headers)
        )

    def decline_inquiry(self, inquiry_id, payload, headers=None):
        return self._request(
            "POST", f"/research/inquiry-requests/{inquiry_id}/decline", payload, _h(headers)
        )

    def complete_inquiry(self, inquiry_id, payload, headers=None):
        return self._request(
            "POST", f"/research/inquiry-requests/{inquiry_id}/complete", payload, _h(headers)
        )

    def cancel_inquiry(self, inquiry_id, payload, headers=None):
        return self._request(
            "POST", f"/research/inquiry-requests/{inquiry_id}/cancel", payload, _h(headers)
        )

    # ── ResearchDocument ──────────────────────────────────────────
    def create_document(self, payload, headers=None):
        return self._request("POST", "/research/documents", payload, _h(headers))

    def get_document(self, document_id, headers=None):
        return self._request("GET", f"/research/documents/{document_id}", headers=_h(headers))

    def list_documents(self, headers=None, params=None):
        return self._request("GET", "/research/documents", headers=_h(headers), params=params)

    def submit_for_review(self, document_id, payload, headers=None):
        return self._request(
            "POST", f"/research/documents/{document_id}/submit-for-review", payload, _h(headers)
        )

    def record_peer_verdict(self, document_id, payload, headers=None):
        return self._request(
            "POST", f"/research/documents/{document_id}/peer-verdicts", payload, _h(headers)
        )

    def publish_document(self, document_id, headers=None):
        return self._request("POST", f"/research/documents/{document_id}/publish", {}, _h(headers))

    def revise_document(self, document_id, payload, headers=None):
        return self._request(
            "POST", f"/research/documents/{document_id}/revise", payload, _h(headers)
        )

    # ── Vendor ────────────────────────────────────────────────────
    def create_vendor(self, payload, headers=None):
        return self._request("POST", "/research/vendors", payload, _h(headers))

    def get_vendor(self, vendor_id, headers=None):
        return self._request("GET", f"/research/vendors/{vendor_id}", headers=_h(headers))

    # ── VendorInclusion ───────────────────────────────────────────
    def create_inclusion(self, document_id, payload, headers=None):
        return self._request(
            "POST", f"/research/documents/{document_id}/vendor-inclusions", payload, _h(headers)
        )

    def get_inclusion(self, inclusion_id, headers=None):
        return self._request(
            "GET", f"/research/vendor-inclusions/{inclusion_id}", headers=_h(headers)
        )

    def list_inclusions(self, headers=None, params=None):
        return self._request(
            "GET", "/research/vendor-inclusions", headers=_h(headers), params=params
        )

    def finalize_inclusion(self, inclusion_id, payload, headers=None):
        return self._request(
            "POST", f"/research/vendor-inclusions/{inclusion_id}/finalize", payload, _h(headers)
        )

    def file_appeal(self, inclusion_id, payload, headers=None):
        return self._request(
            "POST", f"/research/vendor-inclusions/{inclusion_id}/appeals", payload, _h(headers)
        )

    def decide_appeal(self, inclusion_id, payload, headers=None):
        return self._request(
            "POST", f"/research/vendor-inclusions/{inclusion_id}/appeal-decisions",
            payload, _h(headers),
        )

    def respond_fact_check(self, inclusion_id, payload, headers=None):
        return self._request(
            "POST", f"/research/vendor-inclusions/{inclusion_id}/fact-check-responses",
            payload, _h(headers),
        )

    def decide_fact_check(self, inclusion_id, payload, headers=None):
        return self._request(
            "POST", f"/research/vendor-inclusions/{inclusion_id}/fact-check-decisions",
            payload, _h(headers),
        )

    def adjust_reprint_copies(self, inclusion_id, payload, headers=None):
        return self._request(
            "POST", f"/research/vendor-inclusions/{inclusion_id}/reprint-copy-adjustments",
            payload, _h(headers),
        )

    # ── VendorBriefing ────────────────────────────────────────────
    def create_briefing(self, payload, headers=None):
        return self._request("POST", "/research/vendor-briefings", payload, _h(headers))

    def get_briefing(self, briefing_id, headers=None):
        return self._request("GET", f"/research/vendor-briefings/{briefing_id}", headers=_h(headers))

    def list_briefings(self, headers=None, params=None):
        return self._request(
            "GET", "/research/vendor-briefings", headers=_h(headers), params=params
        )

    def record_briefing(self, briefing_id, payload, headers=None):
        return self._request(
            "POST", f"/research/vendor-briefings/{briefing_id}/record-briefing",
            payload, _h(headers),
        )

    # ── SalesRelationship ─────────────────────────────────────────
    def create_sales_relationship(self, payload, headers=None):
        return self._request("POST", "/research/sales-relationships", payload, _h(headers))

    def get_sales_relationship(self, relationship_id, headers=None):
        return self._request(
            "GET", f"/research/sales-relationships/{relationship_id}", headers=_h(headers)
        )

    def list_sales_relationships(self, headers=None, params=None):
        return self._request(
            "GET", "/research/sales-relationships", headers=_h(headers), params=params
        )

    def terminate_sales_relationship(self, relationship_id, payload, headers=None):
        return self._request(
            "POST", f"/research/sales-relationships/{relationship_id}/terminate",
            payload, _h(headers),
        )

    # ── ConferenceEvent ───────────────────────────────────────────
    def create_conference_event(self, payload, headers=None):
        return self._request("POST", "/research/conference-events", payload, _h(headers))

    def get_conference_event(self, event_id, headers=None):
        return self._request(
            "GET", f"/research/conference-events/{event_id}", headers=_h(headers)
        )

    def append_session(self, event_id, payload, headers=None):
        return self._request(
            "POST", f"/research/conference-events/{event_id}/sessions", payload, _h(headers)
        )

    def lock_agenda(self, event_id, headers=None):
        return self._request(
            "POST", f"/research/conference-events/{event_id}/lock-agenda", {}, _h(headers)
        )

    # ── Sponsorship ───────────────────────────────────────────────
    def create_sponsorship(self, payload, headers=None):
        return self._request("POST", "/research/sponsorships", payload, _h(headers))

    def get_sponsorship(self, sponsorship_id, headers=None):
        return self._request(
            "GET", f"/research/sponsorships/{sponsorship_id}", headers=_h(headers)
        )

    def list_sponsorships(self, headers=None, params=None):
        return self._request("GET", "/research/sponsorships", headers=_h(headers), params=params)

    def activate_sponsorship(self, sponsorship_id, headers=None):
        return self._request(
            "POST", f"/research/sponsorships/{sponsorship_id}/activate", {}, _h(headers)
        )

    def cancel_sponsorship(self, sponsorship_id, payload, headers=None):
        return self._request(
            "POST", f"/research/sponsorships/{sponsorship_id}/cancel", payload, _h(headers)
        )


api_client = ApiClient()
