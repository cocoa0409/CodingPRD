"""API client: one method per endpoint defined in the PRD (§4 endpoint table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/cinemas/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- Members ---
    def create_member(self, payload, headers):
        return self._request("POST", "/cinemas/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/cinemas/members/{member_id}", headers=headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/cinemas/members", headers=headers, params=params)

    def activate_member(self, member_id, headers):
        return self._request("POST", f"/cinemas/members/{member_id}/activate", {}, headers)

    def unsuspend_member(self, member_id, headers):
        return self._request("POST", f"/cinemas/members/{member_id}/unsuspend", {}, headers)

    def close_member(self, member_id, headers):
        return self._request("POST", f"/cinemas/members/{member_id}/close", {}, headers)

    def list_member_strikes(self, member_id, headers, params=None):
        return self._request("GET", f"/cinemas/members/{member_id}/strikes",
                             headers=headers, params=params)

    def list_member_loyalty_ledger(self, member_id, headers, params=None):
        return self._request("GET", f"/cinemas/members/{member_id}/loyalty-ledger",
                             headers=headers, params=params)

    def create_loyalty_adjustment(self, member_id, payload, headers):
        return self._request("POST", f"/cinemas/members/{member_id}/loyalty-adjustments",
                             payload, headers)

    # --- Subscription plans ---
    def create_plan(self, payload, headers):
        return self._request("POST", "/cinemas/subscription-plans", payload, headers)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"/cinemas/subscription-plans/{plan_id}", headers=headers)

    def publish_plan(self, plan_id, headers):
        return self._request("POST", f"/cinemas/subscription-plans/{plan_id}/publish", {}, headers)

    def retire_plan(self, plan_id, headers):
        return self._request("POST", f"/cinemas/subscription-plans/{plan_id}/retire", {}, headers)

    def list_plan_subscriptions(self, plan_id, headers, params=None):
        return self._request("GET", f"/cinemas/subscription-plans/{plan_id}/subscriptions",
                             headers=headers, params=params)

    # --- Subscriptions ---
    def enroll_subscription(self, member_id, payload, headers):
        return self._request("POST", f"/cinemas/members/{member_id}/subscriptions",
                             payload, headers)

    def get_subscription(self, subscription_id, headers):
        return self._request("GET", f"/cinemas/subscriptions/{subscription_id}", headers=headers)

    def list_member_subscriptions(self, member_id, headers, params=None):
        return self._request("GET", f"/cinemas/members/{member_id}/subscriptions",
                             headers=headers, params=params)

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", "/cinemas/subscriptions", headers=headers, params=params)

    def pause_subscription(self, subscription_id, payload, headers):
        return self._request("POST", f"/cinemas/subscriptions/{subscription_id}/pause",
                             payload, headers)

    def resume_subscription(self, subscription_id, headers):
        return self._request("POST", f"/cinemas/subscriptions/{subscription_id}/resume", {}, headers)

    def cancel_subscription(self, subscription_id, headers):
        return self._request("POST", f"/cinemas/subscriptions/{subscription_id}/cancel", {}, headers)

    def change_subscription_plan(self, subscription_id, payload, headers):
        return self._request("POST", f"/cinemas/subscriptions/{subscription_id}/change-plan",
                             payload, headers)

    # --- Credit buckets ---
    def list_subscription_buckets(self, subscription_id, headers, params=None):
        return self._request("GET", f"/cinemas/subscriptions/{subscription_id}/credit-buckets",
                             headers=headers, params=params)

    def get_bucket(self, bucket_id, headers):
        return self._request("GET", f"/cinemas/credit-buckets/{bucket_id}", headers=headers)

    def list_buckets(self, headers, params=None):
        return self._request("GET", "/cinemas/credit-buckets", headers=headers, params=params)

    def list_bucket_reservations(self, bucket_id, headers, params=None):
        return self._request("GET", f"/cinemas/credit-buckets/{bucket_id}/reservations",
                             headers=headers, params=params)

    # --- Theaters / auditoriums / showtimes ---
    def create_theater(self, payload, headers):
        return self._request("POST", "/cinemas/theaters", payload, headers)

    def get_theater(self, theater_id, headers):
        return self._request("GET", f"/cinemas/theaters/{theater_id}", headers=headers)

    def create_auditorium(self, theater_id, payload, headers):
        return self._request("POST", f"/cinemas/theaters/{theater_id}/auditoriums",
                             payload, headers)

    def list_theater_auditoriums(self, theater_id, headers, params=None):
        return self._request("GET", f"/cinemas/theaters/{theater_id}/auditoriums",
                             headers=headers, params=params)

    def get_auditorium(self, auditorium_id, headers):
        return self._request("GET", f"/cinemas/auditoriums/{auditorium_id}", headers=headers)

    def list_auditoriums(self, headers, params=None):
        return self._request("GET", "/cinemas/auditoriums", headers=headers, params=params)

    def list_auditorium_showtimes(self, auditorium_id, headers, params=None):
        return self._request("GET", f"/cinemas/auditoriums/{auditorium_id}/showtimes",
                             headers=headers, params=params)

    def create_showtime(self, payload, headers):
        return self._request("POST", "/cinemas/showtimes", payload, headers)

    def get_showtime(self, showtime_id, headers):
        return self._request("GET", f"/cinemas/showtimes/{showtime_id}", headers=headers)

    def list_showtimes(self, headers, params=None):
        return self._request("GET", "/cinemas/showtimes", headers=headers, params=params)

    def open_showtime_sales(self, showtime_id, headers):
        return self._request("POST", f"/cinemas/showtimes/{showtime_id}/open_sales", {}, headers)

    def cancel_showtime(self, showtime_id, headers):
        return self._request("POST", f"/cinemas/showtimes/{showtime_id}/cancel", {}, headers)

    def list_showtime_reservations(self, showtime_id, headers, params=None):
        return self._request("GET", f"/cinemas/showtimes/{showtime_id}/reservations",
                             headers=headers, params=params)

    def list_showtime_settlement_lines(self, showtime_id, headers, params=None):
        return self._request("GET", f"/cinemas/showtimes/{showtime_id}/settlement-lines",
                             headers=headers, params=params)

    # --- Reservations ---
    def create_reservation(self, payload, headers):
        return self._request("POST", "/cinemas/reservations", payload, headers)

    def get_reservation(self, reservation_id, headers):
        return self._request("GET", f"/cinemas/reservations/{reservation_id}", headers=headers)

    def list_reservations(self, headers, params=None):
        return self._request("GET", "/cinemas/reservations", headers=headers, params=params)

    def list_member_reservations(self, member_id, headers, params=None):
        return self._request("GET", f"/cinemas/members/{member_id}/reservations",
                             headers=headers, params=params)

    def list_subscription_reservations(self, subscription_id, headers, params=None):
        return self._request("GET", f"/cinemas/subscriptions/{subscription_id}/reservations",
                             headers=headers, params=params)

    def confirm_reservation(self, reservation_id, headers):
        return self._request("POST", f"/cinemas/reservations/{reservation_id}/confirm", {}, headers)

    def cancel_reservation(self, reservation_id, headers):
        return self._request("POST", f"/cinemas/reservations/{reservation_id}/cancel", {}, headers)

    def check_in_reservation(self, reservation_id, headers):
        return self._request("POST", f"/cinemas/reservations/{reservation_id}/check_in", {}, headers)

    def list_reservation_strikes(self, reservation_id, headers, params=None):
        return self._request("GET", f"/cinemas/reservations/{reservation_id}/strikes",
                             headers=headers, params=params)

    def list_reservation_settlement_lines(self, reservation_id, headers, params=None):
        return self._request("GET", f"/cinemas/reservations/{reservation_id}/settlement-lines",
                             headers=headers, params=params)

    # --- No-show strikes ---
    def get_strike(self, strike_id, headers):
        return self._request("GET", f"/cinemas/strikes/{strike_id}", headers=headers)

    def list_strikes(self, headers, params=None):
        return self._request("GET", "/cinemas/strikes", headers=headers, params=params)

    def reverse_strike(self, strike_id, payload, headers):
        return self._request("POST", f"/cinemas/strikes/{strike_id}/reverse", payload, headers)

    # --- Concessions ---
    def create_concession_purchase(self, payload, headers):
        return self._request("POST", "/cinemas/concession-purchases", payload, headers)

    def get_concession_purchase(self, purchase_id, headers):
        return self._request("GET", f"/cinemas/concession-purchases/{purchase_id}", headers=headers)

    def list_concession_purchases(self, headers, params=None):
        return self._request("GET", "/cinemas/concession-purchases", headers=headers, params=params)

    def list_member_concession_purchases(self, member_id, headers, params=None):
        return self._request("GET", f"/cinemas/members/{member_id}/concession-purchases",
                             headers=headers, params=params)

    def list_theater_concession_purchases(self, theater_id, headers, params=None):
        return self._request("GET", f"/cinemas/theaters/{theater_id}/concession-purchases",
                             headers=headers, params=params)

    # --- Loyalty ledger ---
    def list_loyalty_ledger(self, headers, params=None):
        return self._request("GET", "/cinemas/loyalty-ledger", headers=headers, params=params)

    def get_loyalty_entry(self, entry_id, headers):
        return self._request("GET", f"/cinemas/loyalty-ledger/{entry_id}", headers=headers)

    # --- Settlement ---
    def create_settlement_report(self, theater_id, payload, headers):
        return self._request("POST", f"/cinemas/theaters/{theater_id}/settlement-reports",
                             payload, headers)

    def get_settlement_report(self, report_id, headers):
        return self._request("GET", f"/cinemas/settlement-reports/{report_id}", headers=headers)

    def list_settlement_reports(self, headers, params=None):
        return self._request("GET", "/cinemas/settlement-reports", headers=headers, params=params)

    def list_theater_settlement_reports(self, theater_id, headers, params=None):
        return self._request("GET", f"/cinemas/theaters/{theater_id}/settlement-reports",
                             headers=headers, params=params)

    def list_settlement_lines(self, headers, params=None):
        return self._request("GET", "/cinemas/settlement-lines", headers=headers, params=params)

    def get_settlement_line(self, line_id, headers):
        return self._request("GET", f"/cinemas/settlement-lines/{line_id}", headers=headers)

    def list_report_lines(self, report_id, headers, params=None):
        return self._request("GET", f"/cinemas/settlement-reports/{report_id}/lines",
                             headers=headers, params=params)

    def add_settlement_line(self, report_id, payload, headers):
        return self._request("POST", f"/cinemas/settlement-reports/{report_id}/lines",
                             payload, headers)

    def submit_settlement_report(self, report_id, headers):
        return self._request("POST", f"/cinemas/settlement-reports/{report_id}/submit", {}, headers)

    def acknowledge_settlement_report(self, report_id, headers):
        return self._request("POST", f"/cinemas/settlement-reports/{report_id}/acknowledge", {}, headers)

    def dispute_settlement_report(self, report_id, payload, headers):
        return self._request("POST", f"/cinemas/settlement-reports/{report_id}/dispute",
                             payload, headers)

    def revise_settlement_report(self, report_id, headers):
        return self._request("POST", f"/cinemas/settlement-reports/{report_id}/revise", {}, headers)


api_client = ApiClient()
