"""One method per endpoint of the Venue Event-Day Staffing & Guest Services API.

Every method returns the raw ``requests.Response`` so tests can assert on the
status code as well as on the envelope.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------ clock
    def set_clock(self, current_utc: str, headers: Optional[Dict] = None):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    def set_clock_raw(self, payload: Any, headers: Optional[Dict] = None):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------ events
    def create_event(self, payload: Any, headers: Optional[Dict] = None):
        return self._request("POST", "/events", payload, headers)

    def get_event(self, event_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"/events/{event_id}", None, headers)

    def list_events(self, headers: Optional[Dict] = None, params: Optional[Dict] = None):
        return self._request("GET", "/events", params, headers)

    def update_event(self, event_id: str, payload: Any, headers: Optional[Dict] = None):
        return self._request("PATCH", f"/events/{event_id}", payload, headers)

    def event_lifecycle(self, event_id: str, payload: Any, headers: Optional[Dict] = None):
        return self._request("POST", f"/events/{event_id}/lifecycle", payload, headers)

    def event_payout_run(self, event_id: str, payload: Any, headers: Optional[Dict] = None):
        return self._request("POST", f"/events/{event_id}/payout-run", payload, headers)

    def get_satisfaction_summary(
        self, event_id: str, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/events/{event_id}/satisfaction-summary", params, headers
        )

    def get_staffing_model_recommendation(
        self, event_id: str, headers: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/events/{event_id}/staffing-model-recommendation", None, headers
        )

    def list_event_satisfaction_responses(
        self, event_id: str, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/events/{event_id}/satisfaction-responses", params, headers
        )

    # ------------------------------------------------------------ position types
    def create_position_type(self, payload: Any, headers: Optional[Dict] = None):
        return self._request("POST", "/position-types", payload, headers)

    def get_position_type(self, position_type_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"/position-types/{position_type_id}", None, headers)

    def list_position_types(
        self, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ):
        return self._request("GET", "/position-types", params, headers)

    def update_position_type(
        self, position_type_id: str, payload: Any, headers: Optional[Dict] = None
    ):
        return self._request(
            "PATCH", f"/position-types/{position_type_id}", payload, headers
        )

    # ------------------------------------------------------------ staffing plans
    def create_staffing_plan(self, payload: Any, headers: Optional[Dict] = None):
        return self._request("POST", "/staffing-plans", payload, headers)

    def get_staffing_plan(self, plan_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"/staffing-plans/{plan_id}", None, headers)

    def list_staffing_plans(
        self, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ):
        return self._request("GET", "/staffing-plans", params, headers)

    def activate_staffing_plan(
        self, plan_id: str, payload: Any, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/staffing-plans/{plan_id}/activate", payload, headers
        )

    # ------------------------------------------------------------ position slots
    def create_position_slot(self, payload: Any, headers: Optional[Dict] = None):
        return self._request("POST", "/position-slots", payload, headers)

    def get_position_slot(self, slot_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"/position-slots/{slot_id}", None, headers)

    def list_position_slots(
        self, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ):
        return self._request("GET", "/position-slots", params, headers)

    def update_position_slot(
        self, slot_id: str, payload: Any, headers: Optional[Dict] = None
    ):
        return self._request("PATCH", f"/position-slots/{slot_id}", payload, headers)

    def delete_position_slot(self, slot_id: str, headers: Optional[Dict] = None):
        return self._request("DELETE", f"/position-slots/{slot_id}", None, headers)

    def run_bid_award(self, slot_id: str, headers: Optional[Dict] = None):
        return self._request("POST", f"/position-slots/{slot_id}/run-bid-award", {}, headers)

    # ------------------------------------------------------------ staff members
    def create_staff_member(self, payload: Any, headers: Optional[Dict] = None):
        return self._request("POST", "/staff-members", payload, headers)

    def get_staff_member(self, member_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"/staff-members/{member_id}", None, headers)

    def list_staff_members(
        self, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ):
        return self._request("GET", "/staff-members", params, headers)

    def update_staff_member(
        self, member_id: str, payload: Any, headers: Optional[Dict] = None
    ):
        return self._request("PATCH", f"/staff-members/{member_id}", payload, headers)

    def staff_member_status_change(
        self, member_id: str, payload: Any, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/staff-members/{member_id}/status-change", payload, headers
        )

    def list_staff_member_certifications(
        self, member_id: str, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/staff-members/{member_id}/certifications", params, headers
        )

    # ------------------------------------------------------------ certifications
    def create_certification(self, payload: Any, headers: Optional[Dict] = None):
        return self._request("POST", "/certifications", payload, headers)

    def get_certification(self, cert_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"/certifications/{cert_id}", None, headers)

    def list_certifications(
        self, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ):
        return self._request("GET", "/certifications", params, headers)

    def revoke_certification(
        self, cert_id: str, payload: Any, headers: Optional[Dict] = None
    ):
        return self._request("POST", f"/certifications/{cert_id}/revoke", payload, headers)

    # ------------------------------------------------------------ shift bids
    def create_shift_bid(self, payload: Any, headers: Optional[Dict] = None):
        return self._request("POST", "/shift-bids", payload, headers)

    def get_shift_bid(self, bid_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"/shift-bids/{bid_id}", None, headers)

    def list_shift_bids(self, headers: Optional[Dict] = None, params: Optional[Dict] = None):
        return self._request("GET", "/shift-bids", params, headers)

    def award_shift_bid(self, bid_id: str, headers: Optional[Dict] = None):
        return self._request("POST", f"/shift-bids/{bid_id}/award", {}, headers)

    def withdraw_shift_bid(self, bid_id: str, headers: Optional[Dict] = None):
        return self._request("POST", f"/shift-bids/{bid_id}/withdraw", {}, headers)

    # ------------------------------------------------------------ staff assignments
    def create_staff_assignment(self, payload: Any, headers: Optional[Dict] = None):
        return self._request("POST", "/staff-assignments", payload, headers)

    def get_staff_assignment(self, assignment_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"/staff-assignments/{assignment_id}", None, headers)

    def list_staff_assignments(
        self, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ):
        return self._request("GET", "/staff-assignments", params, headers)

    def record_attendance(
        self, assignment_id: str, payload: Any, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/staff-assignments/{assignment_id}/attendance", payload, headers
        )

    # ------------------------------------------------------------ backfill requests
    def get_backfill_request(self, request_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"/backfill-requests/{request_id}", None, headers)

    def list_backfill_requests(
        self, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ):
        return self._request("GET", "/backfill-requests", params, headers)

    def auto_fill_backfill_request(self, request_id: str, headers: Optional[Dict] = None):
        return self._request(
            "POST", f"/backfill-requests/{request_id}/auto-fill", {}, headers
        )

    def cancel_backfill_request(
        self, request_id: str, payload: Any, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/backfill-requests/{request_id}/cancel", payload, headers
        )

    # ------------------------------------------------------------ guest issues
    def create_guest_issue(self, payload: Any, headers: Optional[Dict] = None):
        return self._request("POST", "/guest-issues", payload, headers)

    def get_guest_issue(self, issue_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"/guest-issues/{issue_id}", None, headers)

    def list_guest_issues(
        self, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ):
        return self._request("GET", "/guest-issues", params, headers)

    def assign_guest_issue(
        self, issue_id: str, payload: Any, headers: Optional[Dict] = None
    ):
        return self._request("POST", f"/guest-issues/{issue_id}/assign", payload, headers)

    def resolve_guest_issue(
        self, issue_id: str, payload: Any, headers: Optional[Dict] = None
    ):
        return self._request("POST", f"/guest-issues/{issue_id}/resolve", payload, headers)

    def escalate_guest_issue(self, issue_id: str, headers: Optional[Dict] = None):
        return self._request("POST", f"/guest-issues/{issue_id}/escalate", {}, headers)

    def reopen_guest_issue(self, issue_id: str, headers: Optional[Dict] = None):
        return self._request("POST", f"/guest-issues/{issue_id}/reopen", {}, headers)

    def close_guest_issue(self, issue_id: str, headers: Optional[Dict] = None):
        return self._request("POST", f"/guest-issues/{issue_id}/close", {}, headers)

    def file_refund_request(
        self, issue_id: str, payload: Any, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/guest-issues/{issue_id}/refund-request", payload, headers
        )

    def file_refund_decision(
        self, issue_id: str, payload: Any, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/guest-issues/{issue_id}/refund-decision", payload, headers
        )

    # ------------------------------------------------------------ accessibility pools
    def create_accessibility_resource(self, payload: Any, headers: Optional[Dict] = None):
        return self._request("POST", "/accessibility-resources", payload, headers)

    def get_accessibility_resource(self, resource_id: str, headers: Optional[Dict] = None):
        return self._request(
            "GET", f"/accessibility-resources/{resource_id}", None, headers
        )

    def list_accessibility_resources(
        self, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ):
        return self._request("GET", "/accessibility-resources", params, headers)

    def update_accessibility_resource(
        self, resource_id: str, payload: Any, headers: Optional[Dict] = None
    ):
        return self._request(
            "PATCH", f"/accessibility-resources/{resource_id}", payload, headers
        )

    # ------------------------------------------------------------ accessibility bookings
    def create_accessibility_request(self, payload: Any, headers: Optional[Dict] = None):
        return self._request("POST", "/accessibility-requests", payload, headers)

    def get_accessibility_request(self, request_id: str, headers: Optional[Dict] = None):
        return self._request("GET", f"/accessibility-requests/{request_id}", None, headers)

    def list_accessibility_requests(
        self, headers: Optional[Dict] = None, params: Optional[Dict] = None
    ):
        return self._request("GET", "/accessibility-requests", params, headers)

    def transition_accessibility_request(
        self, request_id: str, payload: Any, headers: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/accessibility-requests/{request_id}/transition", payload, headers
        )

    # ------------------------------------------------------------ satisfaction
    def create_satisfaction_response(self, payload: Any, headers: Optional[Dict] = None):
        return self._request("POST", "/satisfaction-responses", payload, headers)
