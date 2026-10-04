"""API client: one method per endpoint defined in the PRD (PRD §4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Test clock and operational capabilities -----------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/event-cinema/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    def run_on_sale_sweep(self, headers):
        return self._request("POST", "/event-cinema/_ops/run-on-sale-sweep", {}, headers)

    def run_presale_checkpoints(self, headers):
        return self._request("POST", "/event-cinema/_ops/run-presale-checkpoints", {}, headers)

    def run_rights_expiry_sweep(self, headers):
        return self._request("POST", "/event-cinema/_ops/run-rights-expiry-sweep", {}, headers)

    def run_rekey_sweep(self, theater_id, headers):
        return self._request("POST", "/event-cinema/_ops/rekey-sweep",
                             {"theater_id": theater_id}, headers)

    # --- Distributors --------------------------------------------------------
    def create_distributor(self, payload, headers):
        return self._request("POST", "/event-cinema/distributors", payload, headers)

    def list_distributors(self, headers, params=None):
        return self._request("GET", "/event-cinema/distributors", headers=headers, params=params)

    def get_distributor(self, distributor_id, headers):
        return self._request("GET", f"/event-cinema/distributors/{distributor_id}", headers=headers)

    def suspend_distributor(self, distributor_id, headers):
        return self._request("POST", f"/event-cinema/distributors/{distributor_id}/suspend",
                             {}, headers)

    def reactivate_distributor(self, distributor_id, headers):
        return self._request("POST", f"/event-cinema/distributors/{distributor_id}/reactivate",
                             {}, headers)

    def list_distributor_bookings(self, distributor_id, headers, params=None):
        return self._request("GET", f"/event-cinema/distributors/{distributor_id}/bookings",
                             headers=headers, params=params)

    # --- Circuits ------------------------------------------------------------
    def create_circuit(self, payload, headers):
        return self._request("POST", "/event-cinema/circuits", payload, headers)

    def list_circuits(self, headers, params=None):
        return self._request("GET", "/event-cinema/circuits", headers=headers, params=params)

    def get_circuit(self, circuit_id, headers):
        return self._request("GET", f"/event-cinema/circuits/{circuit_id}", headers=headers)

    def accredit_circuit(self, circuit_id, headers):
        return self._request("POST", f"/event-cinema/circuits/{circuit_id}/accredit", {}, headers)

    def suspend_circuit(self, circuit_id, headers):
        return self._request("POST", f"/event-cinema/circuits/{circuit_id}/suspend", {}, headers)

    # --- Theaters ------------------------------------------------------------
    def create_theater(self, payload, headers):
        return self._request("POST", "/event-cinema/theaters", payload, headers)

    def list_theaters(self, headers, params=None):
        return self._request("GET", "/event-cinema/theaters", headers=headers, params=params)

    def get_theater(self, theater_id, headers):
        return self._request("GET", f"/event-cinema/theaters/{theater_id}", headers=headers)

    def go_dark(self, theater_id, headers):
        return self._request("POST", f"/event-cinema/theaters/{theater_id}/go-dark", {}, headers)

    # --- Titles --------------------------------------------------------------
    def create_title(self, payload, headers):
        return self._request("POST", "/event-cinema/titles", payload, headers)

    def list_titles(self, headers, params=None):
        return self._request("GET", "/event-cinema/titles", headers=headers, params=params)

    def get_title(self, title_id, headers):
        return self._request("GET", f"/event-cinema/titles/{title_id}", headers=headers)

    def update_title(self, title_id, payload, headers):
        return self._request("PUT", f"/event-cinema/titles/{title_id}", payload, headers)

    def publish_title(self, title_id, headers):
        return self._request("POST", f"/event-cinema/titles/{title_id}/publish", {}, headers)

    def unpublish_title(self, title_id, headers):
        return self._request("POST", f"/event-cinema/titles/{title_id}/unpublish", {}, headers)

    def clear_title(self, title_id, headers):
        return self._request("POST", f"/event-cinema/titles/{title_id}/clear", {}, headers)

    def reopen_title_bookings(self, title_id, headers):
        return self._request("POST", f"/event-cinema/titles/{title_id}/reopen-bookings", {}, headers)

    def withdraw_title(self, title_id, headers):
        return self._request("POST", f"/event-cinema/titles/{title_id}/withdraw", {}, headers)

    def archive_title(self, title_id, headers):
        return self._request("POST", f"/event-cinema/titles/{title_id}/archive", {}, headers)

    # --- Bookings ------------------------------------------------------------
    def create_booking(self, payload, headers):
        return self._request("POST", "/event-cinema/bookings", payload, headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/event-cinema/bookings", headers=headers, params=params)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/event-cinema/bookings/{booking_id}", headers=headers)

    def update_booking(self, booking_id, payload, headers):
        return self._request("PUT", f"/event-cinema/bookings/{booking_id}", payload, headers)

    def add_booking_line(self, booking_id, payload, headers):
        return self._request("POST", f"/event-cinema/bookings/{booking_id}/lines", payload, headers)

    def list_booking_lines(self, booking_id, headers, params=None):
        return self._request("GET", f"/event-cinema/bookings/{booking_id}/lines",
                             headers=headers, params=params)

    def record_presale_sales(self, booking_id, quantity, headers):
        return self._request("POST", f"/event-cinema/bookings/{booking_id}/presale-sales",
                             {"quantity": quantity}, headers)

    def submit_booking(self, booking_id, expected_booking_version, headers):
        return self._request("POST", f"/event-cinema/bookings/{booking_id}/submit",
                             {"expected_booking_version": expected_booking_version},
                             headers)

    def counter_booking(self, booking_id, proposed_guarantee_cents,
                        proposed_revenue_share_pct, expected_booking_version, headers):
        return self._request("POST", f"/event-cinema/bookings/{booking_id}/counter", {
            "proposed_guarantee_cents": proposed_guarantee_cents,
            "proposed_revenue_share_pct": proposed_revenue_share_pct,
            "expected_booking_version": expected_booking_version,
        }, headers)

    def repropose_booking(self, booking_id, expected_booking_version, headers,
                          proposed_guarantee_cents=None,
                          proposed_revenue_share_pct=None):
        payload = {"expected_booking_version": expected_booking_version}
        if proposed_guarantee_cents is not None:
            payload["proposed_guarantee_cents"] = proposed_guarantee_cents
        if proposed_revenue_share_pct is not None:
            payload["proposed_revenue_share_pct"] = proposed_revenue_share_pct
        return self._request("POST", f"/event-cinema/bookings/{booking_id}/re-propose",
                             payload, headers)

    def approve_booking(self, booking_id, expected_booking_version, headers,
                        line_id=None):
        payload = {"expected_booking_version": expected_booking_version}
        if line_id is not None:
            payload["line_id"] = line_id
        return self._request("POST", f"/event-cinema/bookings/{booking_id}/approve",
                             payload, headers)

    def cancel_booking(self, booking_id, expected_booking_version, headers):
        return self._request("POST", f"/event-cinema/bookings/{booking_id}/cancel",
                             {"expected_booking_version": expected_booking_version},
                             headers)

    def cancel_booking_with_compensation(self, booking_id, expected_booking_version,
                                         headers):
        return self._request("POST",
                             f"/event-cinema/bookings/{booking_id}/cancel-with-compensation",
                             {"expected_booking_version": expected_booking_version},
                             headers)

    def suspend_booking(self, booking_id, expected_booking_version, headers):
        return self._request("POST", f"/event-cinema/bookings/{booking_id}/suspend",
                             {"expected_booking_version": expected_booking_version},
                             headers)

    def resume_booking(self, booking_id, expected_booking_version, headers):
        return self._request("POST", f"/event-cinema/bookings/{booking_id}/resume",
                             {"expected_booking_version": expected_booking_version},
                             headers)

    def confirm_booking(self, booking_id, expected_booking_version, headers):
        return self._request("POST", f"/event-cinema/bookings/{booking_id}/confirm",
                             {"expected_booking_version": expected_booking_version},
                             headers)

    def run_presale_checkpoint(self, booking_id, expected_booking_version, headers):
        return self._request("POST", f"/event-cinema/bookings/{booking_id}/presale-checkpoint",
                             {"expected_booking_version": expected_booking_version},
                             headers)

    def release_screens(self, booking_id, line_id, expected_booking_version, headers):
        return self._request("POST", f"/event-cinema/bookings/{booking_id}/release-screens", {
            "line_id": line_id,
            "expected_booking_version": expected_booking_version,
        }, headers)

    def apply_makegood(self, booking_id, line_id, feed_event_id,
                       expected_booking_version, headers):
        return self._request("POST", f"/event-cinema/bookings/{booking_id}/apply-makegood", {
            "line_id": line_id,
            "feed_event_id": feed_event_id,
            "expected_booking_version": expected_booking_version,
        }, headers)

    def reopen_booking(self, booking_id, settlement_id, expected_booking_version,
                       headers):
        return self._request("POST", f"/event-cinema/bookings/{booking_id}/reopen", {
            "settlement_id": settlement_id,
            "expected_booking_version": expected_booking_version,
        }, headers)

    def close_booking(self, booking_id, expected_booking_version, headers):
        return self._request("POST", f"/event-cinema/bookings/{booking_id}/close",
                             {"expected_booking_version": expected_booking_version},
                             headers)

    # --- Booking lines -------------------------------------------------------
    def list_booking_lines_index(self, headers, params=None):
        return self._request("GET", "/event-cinema/booking-lines", headers=headers, params=params)

    def get_booking_line(self, line_id, headers):
        return self._request("GET", f"/event-cinema/booking-lines/{line_id}", headers=headers)

    # --- Screenings ----------------------------------------------------------
    def create_screening(self, payload, headers):
        return self._request("POST", "/event-cinema/screenings", payload, headers)

    def list_screenings(self, headers, params=None):
        return self._request("GET", "/event-cinema/screenings", headers=headers, params=params)

    def get_screening(self, screening_id, headers):
        return self._request("GET", f"/event-cinema/screenings/{screening_id}", headers=headers)

    def report_screening(self, screening_id, reported_attendance, reported_outcome,
                         headers):
        return self._request("POST", f"/event-cinema/screenings/{screening_id}/report", {
            "reported_attendance": reported_attendance,
            "reported_outcome": reported_outcome,
        }, headers)

    # --- Encryption keys -----------------------------------------------------
    def create_encryption_key(self, payload, headers):
        return self._request("POST", "/event-cinema/encryption-keys", payload, headers)

    def list_encryption_keys(self, headers, params=None):
        return self._request("GET", "/event-cinema/encryption-keys", headers=headers, params=params)

    def get_encryption_key(self, key_id, headers):
        return self._request("GET", f"/event-cinema/encryption-keys/{key_id}", headers=headers)

    def issue_key(self, key_id, headers):
        return self._request("POST", f"/event-cinema/keys/{key_id}/issue", {}, headers)

    def revoke_key(self, key_id, revocation_reason, headers):
        return self._request("POST", f"/event-cinema/keys/{key_id}/revoke",
                             {"revocation_reason": revocation_reason}, headers)

    # --- Content deliveries --------------------------------------------------
    def create_content_delivery(self, payload, headers):
        return self._request("POST", "/event-cinema/content-deliveries", payload, headers)

    def list_content_deliveries(self, headers, params=None):
        return self._request("GET", "/event-cinema/content-deliveries", headers=headers, params=params)

    def get_content_delivery(self, delivery_id, headers):
        return self._request("GET", f"/event-cinema/content-deliveries/{delivery_id}",
                             headers=headers)

    def mark_delivery_delivered(self, delivery_id, delivered_checksum, headers):
        return self._request("POST", f"/event-cinema/content-deliveries/{delivery_id}/mark-delivered",
                             {"delivered_checksum": delivered_checksum}, headers)

    def mark_delivery_failed(self, delivery_id, headers):
        return self._request("POST", f"/event-cinema/content-deliveries/{delivery_id}/mark-failed",
                             {}, headers)

    def verify_delivery(self, delivery_id, headers):
        return self._request("POST", f"/event-cinema/content-deliveries/{delivery_id}/verify",
                             {}, headers)

    # --- Encore windows ------------------------------------------------------
    def create_encore_window(self, payload, headers):
        return self._request("POST", "/event-cinema/encore-windows", payload, headers)

    def list_encore_windows(self, headers, params=None):
        return self._request("GET", "/event-cinema/encore-windows", headers=headers, params=params)

    def get_encore_window(self, window_id, headers):
        return self._request("GET", f"/event-cinema/encore-windows/{window_id}", headers=headers)

    def schedule_encore_window(self, window_id, headers):
        return self._request("POST", f"/event-cinema/encore-windows/{window_id}/schedule", {}, headers)

    def withdraw_encore_window(self, window_id, headers):
        return self._request("POST", f"/event-cinema/encore-windows/{window_id}/withdraw", {}, headers)

    # --- Feed events ---------------------------------------------------------
    def create_feed_event(self, payload, headers):
        return self._request("POST", "/event-cinema/feed-events", payload, headers)

    def list_feed_events(self, headers, params=None):
        return self._request("GET", "/event-cinema/feed-events", headers=headers, params=params)

    def get_feed_event(self, event_id, headers):
        return self._request("GET", f"/event-cinema/feed-events/{event_id}", headers=headers)

    def confirm_feed_event(self, event_id, headers):
        return self._request("POST", f"/event-cinema/feed-events/{event_id}/confirm", {}, headers)

    def void_feed_event(self, event_id, headers):
        return self._request("POST", f"/event-cinema/feed-events/{event_id}/void", {}, headers)

    def resolve_feed_event(self, event_id, resolution_outcome, headers):
        return self._request("POST", f"/event-cinema/feed-events/{event_id}/resolve",
                             {"resolution_outcome": resolution_outcome}, headers)

    # --- Settlements ---------------------------------------------------------
    def create_settlement(self, payload, headers):
        return self._request("POST", "/event-cinema/settlements", payload, headers)

    def list_settlements(self, headers, params=None):
        return self._request("GET", "/event-cinema/settlements", headers=headers, params=params)

    def get_settlement(self, settlement_id, headers):
        return self._request("GET", f"/event-cinema/settlements/{settlement_id}", headers=headers)

    def close_settlement(self, settlement_id, headers):
        return self._request("POST", f"/event-cinema/settlements/{settlement_id}/close", {}, headers)

    def reopen_settlement(self, settlement_id, headers):
        return self._request("POST", f"/event-cinema/settlements/{settlement_id}/reopen", {}, headers)

    def apply_makegood_to_settlement(self, settlement_id, line_id, feed_event_id,
                                     headers):
        return self._request("POST", f"/event-cinema/settlements/{settlement_id}/apply-makegood", {
            "line_id": line_id,
            "feed_event_id": feed_event_id,
        }, headers)


api_client = ApiClient()