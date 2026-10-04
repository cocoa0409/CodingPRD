"""HTTP client for the Community Center Membership API.

One method per declared endpoint. Every method returns the raw response so a
test can assert on the status code as well as the body. Query filters and
pagination are passed as ``params``; request bodies as ``payload``.

The API has no path prefix, so paths are used exactly as the PRD writes them.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Endpoint methods for every route the PRD declares."""

    # ── Logical clock ──────────────────────────────────────────────────────

    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ── Associations ───────────────────────────────────────────────────────

    def create_association(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/associations", payload, headers)

    def get_association(self, association_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/associations/{association_id}", None, headers)

    def list_association_branches(
        self, association_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/associations/{association_id}/branches", params, headers)

    def list_association_campaigns(
        self, association_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/associations/{association_id}/campaigns", params, headers)

    # ── Branches ───────────────────────────────────────────────────────────

    def create_branch(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/branches", payload, headers)

    def get_branch(self, branch_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/branches/{branch_id}", None, headers)

    def list_branches(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/branches", params, headers)

    def list_branch_memberships(
        self, branch_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/branches/{branch_id}/memberships", params, headers)

    def list_branch_categories(
        self, branch_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/branches/{branch_id}/categories", params, headers)

    def list_branch_programs(
        self, branch_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/branches/{branch_id}/programs", params, headers)

    def list_branch_spaces(
        self, branch_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/branches/{branch_id}/spaces", params, headers)

    def list_branch_applications(
        self, branch_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/branches/{branch_id}/scholarship-applications", params, headers)

    def list_branch_donations(
        self, branch_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/branches/{branch_id}/donations", params, headers)

    # ── Membership categories ──────────────────────────────────────────────

    def create_category(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/categories", payload, headers)

    def get_category(self, category_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/categories/{category_id}", None, headers)

    def list_categories(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/categories", params, headers)

    # ── Members ────────────────────────────────────────────────────────────

    def create_member(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/members", payload, headers)

    def get_member(self, member_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/members/{member_id}", None, headers)

    def list_members(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/members", params, headers)

    def list_member_registrations(
        self, member_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/members/{member_id}/registrations", params, headers)

    def list_member_memberships(
        self, member_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/members/{member_id}/memberships", params, headers)

    def list_member_applications(
        self, member_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/members/{member_id}/scholarship-applications", params, headers)

    def list_member_donations(
        self, member_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/members/{member_id}/donations", params, headers)

    def list_member_reservations(
        self, member_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/members/{member_id}/reservations", params, headers)

    # ── Memberships ────────────────────────────────────────────────────────

    def create_membership(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/memberships", payload, headers)

    def get_membership(self, membership_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/memberships/{membership_id}", None, headers)

    def list_memberships(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/memberships", params, headers)

    def update_membership(
        self, membership_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("PATCH", f"/memberships/{membership_id}", payload, headers)

    def hold_membership(
        self, membership_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/memberships/{membership_id}/hold", payload, headers)

    def resume_membership(self, membership_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/memberships/{membership_id}/resume", None, headers)

    def cancel_membership(self, membership_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/memberships/{membership_id}/cancel", None, headers)

    def reinstate_membership(self, membership_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/memberships/{membership_id}/reinstate", None, headers)

    def create_draft_for_membership(
        self, membership_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/memberships/{membership_id}/drafts", None, headers)

    def list_membership_drafts(
        self, membership_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/memberships/{membership_id}/drafts", params, headers)

    # ── Billing drafts ─────────────────────────────────────────────────────

    def get_draft(self, draft_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/drafts/{draft_id}", None, headers)

    def list_drafts(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/drafts", params, headers)

    def settle_draft(self, draft_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/drafts/{draft_id}/settle", None, headers)

    def fail_draft(self, draft_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/drafts/{draft_id}/fail", None, headers)

    # ── Scholarship applications ───────────────────────────────────────────

    def create_application(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/scholarship-applications", payload, headers)

    def get_application(self, application_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/scholarship-applications/{application_id}", None, headers)

    def list_applications(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/scholarship-applications", params, headers)

    def review_application(self, application_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/scholarship-applications/{application_id}/review", None, headers)

    def request_info_application(self, application_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/scholarship-applications/{application_id}/request-info", None, headers)

    def submit_info_application(
        self, application_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/scholarship-applications/{application_id}/submit-info", payload, headers)

    def approve_application(
        self, application_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/scholarship-applications/{application_id}/approve", payload, headers)

    def deny_application(self, application_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/scholarship-applications/{application_id}/deny", None, headers)

    # ── Programs ───────────────────────────────────────────────────────────

    def create_program(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/programs", payload, headers)

    def get_program(self, program_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/programs/{program_id}", None, headers)

    def list_programs(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/programs", params, headers)

    def list_program_sessions(
        self, program_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/programs/{program_id}/sessions", params, headers)

    # ── Program sessions ───────────────────────────────────────────────────

    def create_session(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/sessions", payload, headers)

    def get_session(self, session_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/sessions/{session_id}", None, headers)

    def list_sessions(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/sessions", params, headers)

    def close_registration(self, session_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/sessions/{session_id}/close-registration", None, headers)

    def cancel_session(self, session_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/sessions/{session_id}/cancel", None, headers)

    def assign_staff(
        self, session_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/sessions/{session_id}/staff", payload, headers)

    def list_session_registrations(
        self, session_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/sessions/{session_id}/registrations", params, headers)

    # ── Registrations ──────────────────────────────────────────────────────

    def create_registration(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/registrations", payload, headers)

    def get_registration(self, registration_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/registrations/{registration_id}", None, headers)

    def list_registrations(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/registrations", params, headers)

    def cancel_registration(self, registration_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/registrations/{registration_id}/cancel", None, headers)

    # ── Facility spaces ────────────────────────────────────────────────────

    def create_space(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/spaces", payload, headers)

    def get_space(self, space_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/spaces/{space_id}", None, headers)

    def list_spaces(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/spaces", params, headers)

    def list_space_reservations(
        self, space_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/spaces/{space_id}/reservations", params, headers)

    # ── Facility reservations ──────────────────────────────────────────────

    def create_reservation(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/reservations", payload, headers)

    def get_reservation(self, reservation_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/reservations/{reservation_id}", None, headers)

    def list_reservations(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/reservations", params, headers)

    def approve_reservation(self, reservation_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/reservations/{reservation_id}/approve", None, headers)

    def deny_reservation(self, reservation_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/reservations/{reservation_id}/deny", None, headers)

    def cancel_reservation(self, reservation_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/reservations/{reservation_id}/cancel", None, headers)

    # ── Campaigns ──────────────────────────────────────────────────────────

    def create_campaign(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/campaigns", payload, headers)

    def get_campaign(self, campaign_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/campaigns/{campaign_id}", None, headers)

    def list_campaigns(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/campaigns", params, headers)

    def activate_campaign(self, campaign_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/campaigns/{campaign_id}/activate", None, headers)

    def close_campaign(
        self, campaign_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/campaigns/{campaign_id}/close", payload, headers)

    def list_campaign_donations(
        self, campaign_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", f"/campaigns/{campaign_id}/donations", params, headers)

    # ── Donations ──────────────────────────────────────────────────────────

    def create_donation(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/donations", payload, headers)

    def get_donation(self, donation_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/donations/{donation_id}", None, headers)

    def list_donations(self, headers: Dict[str, str], params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/donations", params, headers)

    def receive_donation(self, donation_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/donations/{donation_id}/receive", None, headers)

    def refund_donation(self, donation_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/donations/{donation_id}/refund", None, headers)

    # ── Raw request escape hatch ───────────────────────────────────────────

    def raw(
        self,
        method: str,
        path: str,
        payload: Any = None,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict] = None,
    ) -> requests.Response:
        """Send an arbitrary request, for probes that need a route by hand."""
        return self._request(method, path, payload, headers, params)


api_client = ApiClient()
