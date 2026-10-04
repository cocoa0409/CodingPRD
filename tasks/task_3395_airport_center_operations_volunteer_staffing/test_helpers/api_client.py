"""API client: one method per endpoint defined in the PRD.

All endpoints are mounted at the service root. Create operations return
201; reads and state-transition actions return 200.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ------------------------------------------------------
    def set_clock(self, to_iso8601: str, headers):
        return self._request(
            "POST", "/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # --- Centers ------------------------------------------------------------
    def create_center(self, payload, headers):
        return self._request("POST", "/centers", payload, headers)

    def get_center(self, center_id, headers):
        return self._request("GET", f"/centers/{center_id}", headers=headers)

    def run_ops(self, center_id, headers):
        return self._request("POST", f"/centers/{center_id}/run_ops", headers=headers)

    # --- Site agreements ------------------------------------------------------
    def create_site_agreement(self, center_id, payload, headers):
        return self._request(
            "POST", f"/centers/{center_id}/site-agreements", payload, headers
        )

    def list_site_agreements(self, center_id, headers, params=None):
        return self._request(
            "GET", f"/centers/{center_id}/site-agreements",
            headers=headers, params=params,
        )

    def activate_site_agreement(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/site-agreements/{agreement_id}/activate", payload, headers
        )

    def renew_site_agreement(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/site-agreements/{agreement_id}/renew", payload, headers
        )

    # --- Volunteers -----------------------------------------------------------
    def create_volunteer(self, payload, headers):
        return self._request("POST", "/volunteers", payload, headers)

    def get_volunteer(self, volunteer_id, headers):
        return self._request("GET", f"/volunteers/{volunteer_id}", headers=headers)

    def list_volunteers(self, headers, params=None):
        return self._request("GET", "/volunteers", headers=headers, params=params)

    # --- Background screenings --------------------------------------------------
    def create_screening(self, volunteer_id, payload, headers):
        return self._request(
            "POST", f"/volunteers/{volunteer_id}/screenings", payload, headers
        )

    def list_screenings(self, volunteer_id, headers, params=None):
        return self._request(
            "GET", f"/volunteers/{volunteer_id}/screenings",
            headers=headers, params=params,
        )

    def claim_screening(self, screening_id, headers):
        return self._request(
            "POST", f"/screenings/{screening_id}/claim", headers=headers
        )

    def decide_screening(self, screening_id, payload, headers):
        return self._request(
            "POST", f"/screenings/{screening_id}/decide", payload, headers
        )

    # --- Shifts -----------------------------------------------------------------
    def create_shift(self, center_id, payload, headers):
        return self._request("POST", f"/centers/{center_id}/shifts", payload, headers)

    def list_shifts(self, center_id, headers, params=None):
        return self._request(
            "GET", f"/centers/{center_id}/shifts", headers=headers, params=params
        )

    def get_shift(self, shift_id, headers):
        return self._request("GET", f"/shifts/{shift_id}", headers=headers)

    # --- Shift assignments --------------------------------------------------------
    def create_assignment(self, shift_id, payload, headers):
        return self._request(
            "POST", f"/shifts/{shift_id}/assignments", payload, headers
        )

    def get_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"/shift-assignments/{assignment_id}", headers=headers
        )

    def list_assignments(self, headers, params=None):
        return self._request(
            "GET", "/shift-assignments", headers=headers, params=params
        )

    def confirm_assignment(self, assignment_id, headers, payload=None):
        return self._request(
            "POST", f"/shift-assignments/{assignment_id}/confirm", payload, headers
        )

    def complete_assignment(self, assignment_id, payload, headers):
        return self._request(
            "POST", f"/shift-assignments/{assignment_id}/complete", payload, headers
        )

    def mark_no_show(self, assignment_id, headers):
        return self._request(
            "POST", f"/shift-assignments/{assignment_id}/mark-no-show",
            headers=headers,
        )

    def cancel_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/shift-assignments/{assignment_id}/cancel", headers=headers
        )

    # --- Guests -------------------------------------------------------------------
    def create_guest(self, payload, headers):
        return self._request("POST", "/guests", payload, headers)

    def get_guest(self, guest_id, headers):
        return self._request("GET", f"/guests/{guest_id}", headers=headers)

    def reverify_guest(self, guest_id, payload, headers):
        return self._request(
            "POST", f"/guests/{guest_id}/reverify", payload, headers
        )

    # --- Check-ins ------------------------------------------------------------------
    def create_check_in(self, center_id, payload, headers):
        return self._request(
            "POST", f"/centers/{center_id}/check-ins", payload, headers
        )

    def get_check_in(self, check_in_id, headers):
        return self._request("GET", f"/check-ins/{check_in_id}", headers=headers)

    def list_check_ins(self, headers, params=None):
        return self._request("GET", "/check-ins", headers=headers, params=params)

    # --- Service bookings -------------------------------------------------------------
    def create_service_booking(self, center_id, payload, headers):
        return self._request(
            "POST", f"/centers/{center_id}/service-bookings", payload, headers
        )

    def get_service_booking(self, booking_id, headers):
        return self._request(
            "GET", f"/service-bookings/{booking_id}", headers=headers
        )

    def list_service_bookings(self, headers, params=None):
        return self._request(
            "GET", "/service-bookings", headers=headers, params=params
        )

    # --- Donation lots ------------------------------------------------------------------
    def create_donation_lot(self, center_id, payload, headers):
        return self._request(
            "POST", f"/centers/{center_id}/donation-lots", payload, headers
        )

    def list_donation_lots(self, center_id, headers, params=None):
        return self._request(
            "GET", f"/centers/{center_id}/donation-lots",
            headers=headers, params=params,
        )

    def consume_donation_lot(self, lot_id, payload, headers):
        return self._request(
            "POST", f"/donation-lots/{lot_id}/consume", payload, headers
        )

    # --- Events ---------------------------------------------------------------------------
    def create_event(self, center_id, payload, headers):
        return self._request("POST", f"/centers/{center_id}/events", payload, headers)

    def list_events(self, center_id, headers, params=None):
        return self._request(
            "GET", f"/centers/{center_id}/events", headers=headers, params=params
        )

    def approve_event_security(self, event_id, headers):
        return self._request(
            "POST", f"/events/{event_id}/approve-security", headers=headers
        )

    def confirm_event(self, event_id, headers):
        return self._request("POST", f"/events/{event_id}/confirm", headers=headers)

    def cancel_event(self, event_id, headers):
        return self._request("POST", f"/events/{event_id}/cancel", headers=headers)

    # --- Funding grants and expenses ---------------------------------------------------------
    def create_funding_grant(self, payload, headers):
        return self._request("POST", "/funding-grants", payload, headers)

    def list_funding_grants(self, center_id, headers, params=None):
        return self._request(
            "GET", f"/centers/{center_id}/funding-grants",
            headers=headers, params=params,
        )

    def create_expense(self, center_id, payload, headers):
        return self._request(
            "POST", f"/centers/{center_id}/expenses", payload, headers
        )

    def get_cost_report(self, center_id, headers):
        return self._request(
            "GET", f"/centers/{center_id}/cost-report", headers=headers
        )


api_client = ApiClient()
