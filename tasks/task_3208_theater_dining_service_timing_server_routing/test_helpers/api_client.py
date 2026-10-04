"""API client: one method per endpoint defined in the PRD (PRD §4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Test-driving: logical clock ---
    def set_current_utc(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    def get_current_utc(self, headers):
        return self._request("GET", "/_clock/current_utc", headers=headers)

    # --- Auditorium ---
    def create_auditorium(self, payload, headers):
        return self._request("POST", "/auditoriums", payload, headers)

    def list_auditoriums(self, headers, params=None):
        return self._request("GET", "/auditoriums", headers=headers, params=params)

    def get_auditorium(self, auditorium_id, headers):
        return self._request("GET", f"/auditoriums/{auditorium_id}", headers=headers)

    def get_auditorium_posture(self, auditorium_id, headers):
        return self._request(
            "GET", f"/auditoriums/{auditorium_id}/posture", headers=headers
        )

    def activate_auditorium(self, auditorium_id, headers):
        return self._request(
            "POST", f"/auditoriums/{auditorium_id}/activate", {}, headers
        )

    def close_auditorium(self, auditorium_id, headers):
        return self._request("POST", f"/auditoriums/{auditorium_id}/close", {}, headers)

    def get_auditorium_refund_liability(self, auditorium_id, headers):
        return self._request(
            "GET", f"/auditoriums/{auditorium_id}/refund-liability", headers=headers
        )

    def list_auditorium_showtimes(self, auditorium_id, headers, params=None):
        return self._request(
            "GET", f"/auditoriums/{auditorium_id}/showtimes", headers=headers, params=params
        )

    def list_auditorium_programming_events(self, auditorium_id, headers, params=None):
        return self._request(
            "GET",
            f"/auditoriums/{auditorium_id}/programming-events",
            headers=headers,
            params=params,
        )

    # --- Showtime ---
    def create_showtime(self, payload, headers):
        return self._request("POST", "/showtimes", payload, headers)

    def list_showtimes(self, headers, params=None):
        return self._request("GET", "/showtimes", headers=headers, params=params)

    def get_showtime(self, showtime_id, headers):
        return self._request("GET", f"/showtimes/{showtime_id}", headers=headers)

    def get_dining_capacity(self, showtime_id, headers):
        return self._request(
            "GET", f"/showtimes/{showtime_id}/dining-capacity", headers=headers
        )

    def list_showtime_section_assignments(self, showtime_id, headers, params=None):
        return self._request(
            "GET",
            f"/showtimes/{showtime_id}/section-assignments",
            headers=headers,
            params=params,
        )

    def list_showtime_kitchen_tickets(self, showtime_id, headers, params=None):
        return self._request(
            "GET",
            f"/showtimes/{showtime_id}/kitchen-tickets",
            headers=headers,
            params=params,
        )

    def list_showtime_order_slips(self, showtime_id, headers, params=None):
        return self._request(
            "GET", f"/showtimes/{showtime_id}/order-slips", headers=headers, params=params
        )

    def open_dining(self, showtime_id, headers):
        return self._request("POST", f"/showtimes/{showtime_id}/open-dining", {}, headers)

    def start_service(self, showtime_id, headers):
        return self._request("POST", f"/showtimes/{showtime_id}/start-service", {}, headers)

    def start_feature(self, showtime_id, headers):
        return self._request("POST", f"/showtimes/{showtime_id}/start-feature", {}, headers)

    def complete_showtime(self, showtime_id, headers):
        return self._request("POST", f"/showtimes/{showtime_id}/complete", {}, headers)

    def reopen_service(self, showtime_id, headers):
        return self._request("POST", f"/showtimes/{showtime_id}/reopen-service", {}, headers)

    def cancel_showtime(self, showtime_id, headers):
        return self._request("POST", f"/showtimes/{showtime_id}/cancel", {}, headers)

    # --- ProgrammingEvent ---
    def create_programming_event(self, payload, headers):
        return self._request("POST", "/programming-events", payload, headers)

    def list_programming_events(self, headers, params=None):
        return self._request("GET", "/programming-events", headers=headers, params=params)

    def get_programming_event(self, event_id, headers):
        return self._request("GET", f"/programming-events/{event_id}", headers=headers)

    def submit_pre_show_content(self, event_id, payload, headers):
        return self._request(
            "POST", f"/programming-events/{event_id}/pre-show-content/submit", payload, headers
        )

    def approve_pre_show_content(self, event_id, payload, headers):
        return self._request(
            "POST", f"/programming-events/{event_id}/pre-show-content/approve", payload, headers
        )

    def reject_pre_show_content(self, event_id, payload, headers):
        return self._request(
            "POST", f"/programming-events/{event_id}/pre-show-content/reject", payload, headers
        )

    def activate_programming_event(self, event_id, payload, headers):
        return self._request(
            "POST", f"/programming-events/{event_id}/activate", payload, headers
        )

    def cancel_programming_event(self, event_id, headers):
        return self._request(
            "POST", f"/programming-events/{event_id}/cancel", {}, headers
        )

    # --- ThemedMenuItem ---
    def attach_themed_menu_item(self, event_id, payload, headers):
        return self._request(
            "POST", f"/programming-events/{event_id}/themed-menu-items", payload, headers
        )

    def list_event_themed_menu_items(self, event_id, headers, params=None):
        return self._request(
            "GET",
            f"/programming-events/{event_id}/themed-menu-items",
            headers=headers,
            params=params,
        )

    def list_themed_menu_items(self, headers, params=None):
        return self._request("GET", "/themed-menu-items", headers=headers, params=params)

    def get_themed_menu_item(self, themed_menu_item_id, headers):
        return self._request(
            "GET", f"/themed-menu-items/{themed_menu_item_id}", headers=headers
        )

    # --- MenuItem ---
    def create_menu_item(self, payload, headers):
        return self._request("POST", "/menu-items", payload, headers)

    def list_menu_items(self, headers, params=None):
        return self._request("GET", "/menu-items", headers=headers, params=params)

    def get_menu_item(self, menu_item_id, headers):
        return self._request("GET", f"/menu-items/{menu_item_id}", headers=headers)

    def set_menu_item_stock(self, menu_item_id, availability_state, headers):
        return self._request(
            "POST",
            f"/menu-items/{menu_item_id}/stock",
            {"availability_state": availability_state},
            headers,
        )

    # --- Server ---
    def create_server(self, payload, headers):
        return self._request("POST", "/servers", payload, headers)

    def list_servers(self, headers, params=None):
        return self._request("GET", "/servers", headers=headers, params=params)

    def get_server(self, server_id, headers):
        return self._request("GET", f"/servers/{server_id}", headers=headers)

    def start_shift(self, server_id, headers):
        return self._request("POST", f"/servers/{server_id}/shift/start", {}, headers)

    def end_shift(self, server_id, headers):
        return self._request("POST", f"/servers/{server_id}/shift/end", {}, headers)

    def rate_server(self, server_id, payload, headers):
        return self._request("POST", f"/servers/{server_id}/rate", payload, headers)

    def clear_penalty(self, server_id, headers):
        return self._request("POST", f"/servers/{server_id}/clear-penalty", {}, headers)

    def list_server_section_assignments(self, server_id, headers, params=None):
        return self._request(
            "GET", f"/servers/{server_id}/section-assignments", headers=headers, params=params
        )

    # --- SectionAssignment ---
    def create_section_assignment(self, payload, headers):
        return self._request("POST", "/section-assignments", payload, headers)

    def list_section_assignments(self, headers, params=None):
        return self._request("GET", "/section-assignments", headers=headers, params=params)

    def get_section_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"/section-assignments/{assignment_id}", headers=headers
        )

    def reassign_section(self, assignment_id, payload, headers):
        return self._request(
            "PATCH", f"/section-assignments/{assignment_id}", payload, headers
        )

    def score_section_assignment(self, assignment_id, rating_grade, headers):
        return self._request(
            "POST",
            f"/section-assignments/{assignment_id}/score",
            {"rating_grade": rating_grade},
            headers,
        )

    def close_section_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/section-assignments/{assignment_id}/close", {}, headers
        )

    def cancel_section_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/section-assignments/{assignment_id}/cancel", {}, headers
        )

    # --- OrderSlip ---
    def create_order_slip(self, payload, headers):
        return self._request("POST", "/order-slips", payload, headers)

    def list_order_slips(self, headers, params=None):
        return self._request("GET", "/order-slips", headers=headers, params=params)

    def get_order_slip(self, slip_id, headers):
        return self._request("GET", f"/order-slips/{slip_id}", headers=headers)

    def prepare_order_slip(self, slip_id, headers):
        return self._request("POST", f"/order-slips/{slip_id}/prepare", {}, headers)

    def mark_order_slip_ready(self, slip_id, headers):
        return self._request("POST", f"/order-slips/{slip_id}/mark-ready", {}, headers)

    def deliver_order_slip(self, slip_id, headers):
        return self._request("POST", f"/order-slips/{slip_id}/deliver", {}, headers)

    def cancel_order_slip(self, slip_id, payload, headers):
        return self._request("POST", f"/order-slips/{slip_id}/cancel", payload, headers)

    # --- KitchenTicket ---
    def list_kitchen_tickets(self, headers, params=None):
        return self._request("GET", "/kitchen-tickets", headers=headers, params=params)

    def get_kitchen_ticket(self, ticket_id, headers):
        return self._request("GET", f"/kitchen-tickets/{ticket_id}", headers=headers)

    def ack_ticket_overflow(self, ticket_id, overflow_reason, headers):
        return self._request(
            "POST",
            f"/kitchen-tickets/{ticket_id}/ack-overflow",
            {"overflow_reason": overflow_reason},
            headers,
        )

    def verify_ticket_id(self, ticket_id, id_result, headers):
        return self._request(
            "POST",
            f"/kitchen-tickets/{ticket_id}/verify-id",
            {"id_result": id_result},
            headers,
        )

    def refresh_kitchen_ticket(self, ticket_id, headers):
        return self._request("POST", f"/kitchen-tickets/{ticket_id}/refresh", {}, headers)

    def void_kitchen_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/kitchen-tickets/{ticket_id}/void", payload, headers)

    # --- CheckTab ---
    def list_checks(self, headers, params=None):
        return self._request("GET", "/checks", headers=headers, params=params)

    def get_check(self, check_id, headers):
        return self._request("GET", f"/checks/{check_id}", headers=headers)

    def close_check(self, check_id, payload, headers):
        return self._request("POST", f"/checks/{check_id}/close", payload, headers)

    def refund_check(self, check_id, refund_cents, headers):
        return self._request(
            "POST", f"/checks/{check_id}/refund", {"refund_cents": refund_cents}, headers
        )

    # --- DisturbanceEvent ---
    def create_disturbance_event(self, payload, headers):
        return self._request("POST", "/disturbance-events", payload, headers)

    def list_disturbance_events(self, headers, params=None):
        return self._request("GET", "/disturbance-events", headers=headers, params=params)

    def get_disturbance_event(self, event_id, headers):
        return self._request("GET", f"/disturbance-events/{event_id}", headers=headers)

    def amend_disturbance_event(self, event_id, payload, headers):
        return self._request(
            "POST", f"/disturbance-events/{event_id}/amend", payload, headers
        )

    def approve_ejection(self, event_id, headers):
        return self._request(
            "POST", f"/disturbance-events/{event_id}/approve-ejection", {}, headers
        )


api_client = ApiClient()