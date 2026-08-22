"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/busking"


class ApiClient(GenericApiClient):
    # ---- Districts (zones) -------------------------------------------------
    def create_zone(self, payload, headers):
        return self._request("POST", f"{PREFIX}/zones", payload, headers)

    def get_zone(self, zone_id, headers):
        return self._request("GET", f"{PREFIX}/zones/{zone_id}", headers=headers)

    # ---- Pitches -----------------------------------------------------------
    def create_pitch(self, payload, headers):
        return self._request("POST", f"{PREFIX}/pitches", payload, headers)

    def get_pitch(self, pitch_id, headers):
        return self._request("GET", f"{PREFIX}/pitches/{pitch_id}", headers=headers)

    def list_pitches(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/pitches", headers=headers, params=params)

    # ---- Performers --------------------------------------------------------
    def create_performer(self, payload, headers):
        return self._request("POST", f"{PREFIX}/performers", payload, headers)

    def get_performer(self, performer_id, headers):
        return self._request(
            "GET", f"{PREFIX}/performers/{performer_id}", headers=headers)

    # ---- Permit applications ----------------------------------------------
    def create_application(self, payload, headers):
        return self._request("POST", f"{PREFIX}/permit-applications", payload, headers)

    def get_application(self, application_id, headers):
        return self._request(
            "GET", f"{PREFIX}/permit-applications/{application_id}", headers=headers)

    def list_applications(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/permit-applications", headers=headers, params=params)

    def submit_application(self, application_id, headers):
        return self._request(
            "POST", f"{PREFIX}/permit-applications/{application_id}/submit", {}, headers)

    def review_application(self, application_id, headers):
        return self._request(
            "POST", f"{PREFIX}/permit-applications/{application_id}/review", {}, headers)

    def revise_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/permit-applications/{application_id}/revisions",
            payload, headers)

    def decide_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/permit-applications/{application_id}/decision",
            payload, headers)

    # ---- Auditions ---------------------------------------------------------
    def create_audition(self, payload, headers):
        return self._request("POST", f"{PREFIX}/auditions", payload, headers)

    def get_audition(self, audition_id, headers):
        return self._request(
            "GET", f"{PREFIX}/auditions/{audition_id}", headers=headers)

    def list_auditions(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/auditions", headers=headers, params=params)

    def create_audition_score(self, audition_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/auditions/{audition_id}/scores", payload, headers)

    def list_audition_scores(self, audition_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/auditions/{audition_id}/scores",
            headers=headers, params=params)

    def finalize_audition(self, audition_id, headers):
        return self._request(
            "POST", f"{PREFIX}/auditions/{audition_id}/finalize", {}, headers)

    # ---- Permits -----------------------------------------------------------
    def get_permit(self, permit_id, headers):
        return self._request("GET", f"{PREFIX}/permits/{permit_id}", headers=headers)

    def list_permits(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/permits", headers=headers, params=params)

    def renew_permit(self, permit_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/permits/{permit_id}/renew", payload, headers)

    def revoke_permit(self, permit_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/permits/{permit_id}/revoke", payload, headers)

    def reinstate_permit(self, permit_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/permits/{permit_id}/reinstate", payload, headers)

    def list_permit_invoices(self, permit_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/permits/{permit_id}/fee-invoices",
            headers=headers, params=params)

    # ---- Fee invoices ------------------------------------------------------
    def pay_invoice(self, invoice_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/fee-invoices/{invoice_id}/payments", payload, headers)

    # ---- Rotation draws ----------------------------------------------------
    def create_lottery_draw(self, payload, headers):
        return self._request("POST", f"{PREFIX}/lottery-draws", payload, headers)

    def get_lottery_draw(self, draw_id, headers):
        return self._request(
            "GET", f"{PREFIX}/lottery-draws/{draw_id}", headers=headers)

    def list_lottery_draws(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/lottery-draws", headers=headers, params=params)

    def create_lottery_entry(self, draw_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/lottery-draws/{draw_id}/entries", payload, headers)

    def execute_lottery_draw(self, draw_id, headers):
        return self._request(
            "POST", f"{PREFIX}/lottery-draws/{draw_id}/execute", {}, headers)

    def get_lottery_entry(self, entry_id, headers):
        return self._request(
            "GET", f"{PREFIX}/lottery-entries/{entry_id}", headers=headers)

    def list_lottery_entries(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/lottery-entries", headers=headers, params=params)

    # ---- Session bookings --------------------------------------------------
    def create_session_booking(self, payload, headers):
        return self._request("POST", f"{PREFIX}/session-bookings", payload, headers)

    def get_session_booking(self, booking_id, headers):
        return self._request(
            "GET", f"{PREFIX}/session-bookings/{booking_id}", headers=headers)

    def list_session_bookings(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/session-bookings", headers=headers, params=params)

    def cancel_session_booking(self, booking_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/session-bookings/{booking_id}/cancel", payload, headers)

    # ---- Noise readings ----------------------------------------------------
    def create_noise_reading(self, payload, headers):
        return self._request("POST", f"{PREFIX}/noise-readings", payload, headers)

    def list_noise_readings(self, booking_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/session-bookings/{booking_id}/noise-readings",
            headers=headers, params=params)

    # ---- Complaints --------------------------------------------------------
    def create_complaint(self, payload, headers):
        return self._request("POST", f"{PREFIX}/complaints", payload, headers)

    def get_complaint(self, complaint_id, headers):
        return self._request(
            "GET", f"{PREFIX}/complaints/{complaint_id}", headers=headers)

    def list_complaints(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/complaints", headers=headers, params=params)

    def triage_complaint(self, complaint_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/complaints/{complaint_id}/triage", payload, headers)

    def adjudicate_complaint(self, complaint_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/complaints/{complaint_id}/adjudicate", payload, headers)

    # ---- Closure orders ----------------------------------------------------
    def create_closure_order(self, payload, headers):
        return self._request("POST", f"{PREFIX}/closure-orders", payload, headers)

    def get_closure_order(self, closure_id, headers):
        return self._request(
            "GET", f"{PREFIX}/closure-orders/{closure_id}", headers=headers)

    def list_closure_orders(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/closure-orders", headers=headers, params=params)

    def activate_closure_order(self, closure_id, headers):
        return self._request(
            "POST", f"{PREFIX}/closure-orders/{closure_id}/activate", {}, headers)

    # ---- Operations / test-driving -----------------------------------------
    def run_epoch_advance(self, headers):
        return self._request("POST", f"{PREFIX}/ops-runs", {}, headers)

    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
