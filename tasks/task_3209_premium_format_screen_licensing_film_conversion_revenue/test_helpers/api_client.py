"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (PRD §2.5) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/v1/_clock/set_current_utc", payload, headers)

    def get_clock(self, headers):
        return self._request("GET", "/v1/_clock/current_utc", headers=headers)

    # --- Markets ---
    def create_market(self, payload, headers):
        return self._request("POST", "/v1/markets", payload, headers)

    def list_markets(self, headers, params=None):
        return self._request("GET", "/v1/markets", headers=headers, params=params)

    def get_market(self, market_id, headers):
        return self._request("GET", f"/v1/markets/{market_id}", headers=headers)

    def list_market_agreements(self, market_id, headers, params=None):
        return self._request("GET", f"/v1/markets/{market_id}/agreements",
                             headers=headers, params=params)

    def begin_market_evaluation(self, market_id, headers):
        return self._request("POST", f"/v1/markets/{market_id}/begin-evaluation", headers=headers)

    def approve_market(self, market_id, headers):
        return self._request("POST", f"/v1/markets/{market_id}/approve", headers=headers)

    def begin_market_build(self, market_id, headers):
        return self._request("POST", f"/v1/markets/{market_id}/begin-build", headers=headers)

    def go_live_market(self, market_id, headers):
        return self._request("POST", f"/v1/markets/{market_id}/go-live", headers=headers)

    def abandon_market(self, market_id, headers):
        return self._request("POST", f"/v1/markets/{market_id}/abandon", headers=headers)

    # --- Exhibitor agreements ---
    def create_agreement(self, payload, headers):
        return self._request("POST", "/v1/agreements", payload, headers)

    def list_agreements(self, headers, params=None):
        return self._request("GET", "/v1/agreements", headers=headers, params=params)

    def get_agreement(self, agreement_id, headers):
        return self._request("GET", f"/v1/agreements/{agreement_id}", headers=headers)

    def sign_agreement(self, agreement_id, headers):
        return self._request("POST", f"/v1/agreements/{agreement_id}/sign", headers=headers)

    def activate_agreement(self, agreement_id, headers):
        return self._request("POST", f"/v1/agreements/{agreement_id}/activate", headers=headers)

    def terminate_agreement(self, agreement_id, headers):
        return self._request("POST", f"/v1/agreements/{agreement_id}/terminate", headers=headers)

    def list_agreement_auditoriums(self, agreement_id, headers, params=None):
        return self._request("GET", f"/v1/agreements/{agreement_id}/auditoriums",
                             headers=headers, params=params)

    def list_agreement_statements(self, agreement_id, headers, params=None):
        return self._request("GET", f"/v1/agreements/{agreement_id}/revenue-share-statements",
                             headers=headers, params=params)

    # --- Auditoriums ---
    def create_auditorium(self, payload, headers):
        return self._request("POST", "/v1/auditoriums", payload, headers)

    def list_auditoriums(self, headers, params=None):
        return self._request("GET", "/v1/auditoriums", headers=headers, params=params)

    def get_auditorium(self, auditorium_id, headers):
        return self._request("GET", f"/v1/auditoriums/{auditorium_id}", headers=headers)

    def begin_auditorium_construction(self, auditorium_id, headers):
        return self._request("POST", f"/v1/auditoriums/{auditorium_id}/begin-construction", headers=headers)

    def begin_auditorium_calibration(self, auditorium_id, headers):
        return self._request("POST", f"/v1/auditoriums/{auditorium_id}/begin-calibration", headers=headers)

    def certify_auditorium(self, auditorium_id, headers):
        return self._request("POST", f"/v1/auditoriums/{auditorium_id}/certify", headers=headers)

    def open_auditorium(self, auditorium_id, headers):
        return self._request("POST", f"/v1/auditoriums/{auditorium_id}/open", headers=headers)

    def return_auditorium_to_service(self, auditorium_id, headers):
        return self._request("POST", f"/v1/auditoriums/{auditorium_id}/return-to-service", headers=headers)

    def decommission_auditorium(self, auditorium_id, headers):
        return self._request("POST", f"/v1/auditoriums/{auditorium_id}/decommission", headers=headers)

    def list_auditorium_alerts(self, auditorium_id, headers, params=None):
        return self._request("GET", f"/v1/auditoriums/{auditorium_id}/qa-alerts",
                             headers=headers, params=params)

    def list_auditorium_slots(self, auditorium_id, headers, params=None):
        return self._request("GET", f"/v1/auditoriums/{auditorium_id}/screen-slots",
                             headers=headers, params=params)

    # --- Studios ---
    def create_studio(self, payload, headers):
        return self._request("POST", "/v1/studios", payload, headers)

    def list_studios(self, headers, params=None):
        return self._request("GET", "/v1/studios", headers=headers, params=params)

    def get_studio(self, studio_id, headers):
        return self._request("GET", f"/v1/studios/{studio_id}", headers=headers)

    def activate_studio(self, studio_id, headers):
        return self._request("POST", f"/v1/studios/{studio_id}/activate", headers=headers)

    def suspend_studio(self, studio_id, headers):
        return self._request("POST", f"/v1/studios/{studio_id}/suspend", headers=headers)

    def terminate_studio(self, studio_id, headers):
        return self._request("POST", f"/v1/studios/{studio_id}/terminate", headers=headers)

    def list_studio_films(self, studio_id, headers, params=None):
        return self._request("GET", f"/v1/studios/{studio_id}/films",
                             headers=headers, params=params)

    # --- Films ---
    def create_film(self, payload, headers):
        return self._request("POST", "/v1/films", payload, headers)

    def list_films(self, headers, params=None):
        return self._request("GET", "/v1/films", headers=headers, params=params)

    def get_film(self, film_id, headers):
        return self._request("GET", f"/v1/films/{film_id}", headers=headers)

    def archive_film(self, film_id, headers):
        return self._request("POST", f"/v1/films/{film_id}/archive", headers=headers)

    def list_film_conversion_orders(self, film_id, headers, params=None):
        return self._request("GET", f"/v1/films/{film_id}/conversion-orders",
                             headers=headers, params=params)

    def list_film_slots(self, film_id, headers, params=None):
        return self._request("GET", f"/v1/films/{film_id}/screen-slots",
                             headers=headers, params=params)

    # --- Conversion orders ---
    def create_conversion_order(self, payload, headers):
        return self._request("POST", "/v1/conversion-orders", payload, headers)

    def list_conversion_orders(self, headers, params=None):
        return self._request("GET", "/v1/conversion-orders", headers=headers, params=params)

    def get_conversion_order(self, order_id, headers):
        return self._request("GET", f"/v1/conversion-orders/{order_id}", headers=headers)

    def begin_post(self, order_id, headers):
        return self._request("POST", f"/v1/conversion-orders/{order_id}/begin-post", headers=headers)

    def submit_for_qc(self, order_id, headers):
        return self._request("POST", f"/v1/conversion-orders/{order_id}/submit-for-qc", headers=headers)

    def approve_release(self, order_id, headers, payload=None):
        return self._request("POST", f"/v1/conversion-orders/{order_id}/approve-release",
                             payload, headers)

    def request_rework(self, order_id, headers):
        return self._request("POST", f"/v1/conversion-orders/{order_id}/request-rework", headers=headers)

    def deliver_conversion(self, order_id, payload, headers):
        return self._request("POST", f"/v1/conversion-orders/{order_id}/deliver", payload, headers)

    def cancel_conversion(self, order_id, headers):
        return self._request("POST", f"/v1/conversion-orders/{order_id}/cancel", headers=headers)

    # --- Release windows ---
    def create_release_window(self, payload, headers):
        return self._request("POST", "/v1/release-windows", payload, headers)

    def list_release_windows(self, headers, params=None):
        return self._request("GET", "/v1/release-windows", headers=headers, params=params)

    def get_release_window(self, window_id, headers):
        return self._request("GET", f"/v1/release-windows/{window_id}", headers=headers)

    def open_release_window(self, window_id, headers):
        return self._request("POST", f"/v1/release-windows/{window_id}/open", headers=headers)

    def lock_release_window(self, window_id, headers):
        return self._request("POST", f"/v1/release-windows/{window_id}/lock", headers=headers)

    def reopen_release_window(self, window_id, headers):
        return self._request("POST", f"/v1/release-windows/{window_id}/reopen", headers=headers)

    def resume_booking(self, window_id, headers):
        return self._request("POST", f"/v1/release-windows/{window_id}/resume-booking", headers=headers)

    def list_window_slots(self, window_id, headers, params=None):
        return self._request("GET", f"/v1/release-windows/{window_id}/screen-slots",
                             headers=headers, params=params)

    def list_window_statements(self, window_id, headers, params=None):
        return self._request("GET", f"/v1/release-windows/{window_id}/revenue-share-statements",
                             headers=headers, params=params)

    # --- Screen slots ---
    def create_screen_slot(self, payload, headers):
        return self._request("POST", "/v1/screen-slots", payload, headers)

    def list_screen_slots(self, headers, params=None):
        return self._request("GET", "/v1/screen-slots", headers=headers, params=params)

    def get_screen_slot(self, slot_id, headers):
        return self._request("GET", f"/v1/screen-slots/{slot_id}", headers=headers)

    def confirm_slot(self, slot_id, headers):
        return self._request("POST", f"/v1/screen-slots/{slot_id}/confirm", headers=headers)

    def reject_slot(self, slot_id, headers):
        return self._request("POST", f"/v1/screen-slots/{slot_id}/reject", headers=headers)

    def pull_slot(self, slot_id, headers):
        return self._request("POST", f"/v1/screen-slots/{slot_id}/pull", headers=headers)

    def list_slot_reports(self, slot_id, headers, params=None):
        return self._request("GET", f"/v1/screen-slots/{slot_id}/box-office-reports",
                             headers=headers, params=params)

    # --- Box office reports ---
    def create_box_office_report(self, payload, headers):
        return self._request("POST", "/v1/box-office-reports", payload, headers)

    def list_box_office_reports(self, headers, params=None):
        return self._request("GET", "/v1/box-office-reports", headers=headers, params=params)

    def get_box_office_report(self, report_id, headers):
        return self._request("GET", f"/v1/box-office-reports/{report_id}", headers=headers)

    def validate_report(self, report_id, headers):
        return self._request("POST", f"/v1/box-office-reports/{report_id}/validate", headers=headers)

    def flag_report_discrepancy(self, report_id, headers):
        return self._request("POST", f"/v1/box-office-reports/{report_id}/flag-discrepancy", headers=headers)

    # --- Revenue share statements ---
    def create_statement(self, payload, headers):
        return self._request("POST", "/v1/revenue-share-statements", payload, headers)

    def list_statements(self, headers, params=None):
        return self._request("GET", "/v1/revenue-share-statements", headers=headers, params=params)

    def get_statement(self, statement_id, headers):
        return self._request("GET", f"/v1/revenue-share-statements/{statement_id}", headers=headers)

    def issue_statement(self, statement_id, headers):
        return self._request("POST", f"/v1/revenue-share-statements/{statement_id}/issue", headers=headers)

    def reconcile_statement(self, statement_id, headers):
        return self._request("POST", f"/v1/revenue-share-statements/{statement_id}/reconcile", headers=headers)

    def dispute_statement(self, statement_id, headers):
        return self._request("POST", f"/v1/revenue-share-statements/{statement_id}/dispute", headers=headers)

    def apply_statement_adjustment(self, statement_id, payload, headers):
        return self._request("POST", f"/v1/revenue-share-statements/{statement_id}/apply-adjustment",
                             payload, headers)

    def reissue_statement(self, statement_id, headers):
        return self._request("POST", f"/v1/revenue-share-statements/{statement_id}/reissue", headers=headers)

    # --- QA alerts ---
    def create_qa_alert(self, payload, headers):
        return self._request("POST", "/v1/qa-alerts", payload, headers)

    def list_qa_alerts(self, headers, params=None):
        return self._request("GET", "/v1/qa-alerts", headers=headers, params=params)

    def get_qa_alert(self, alert_id, headers):
        return self._request("GET", f"/v1/qa-alerts/{alert_id}", headers=headers)

    def acknowledge_alert(self, alert_id, headers):
        return self._request("POST", f"/v1/qa-alerts/{alert_id}/acknowledge", headers=headers)

    def defer_alert(self, alert_id, headers):
        return self._request("POST", f"/v1/qa-alerts/{alert_id}/defer", headers=headers)

    def list_alert_dispatches(self, alert_id, headers, params=None):
        return self._request("GET", f"/v1/qa-alerts/{alert_id}/dispatches",
                             headers=headers, params=params)

    # --- Tech dispatches ---
    def create_tech_dispatch(self, payload, headers):
        return self._request("POST", "/v1/tech-dispatches", payload, headers)

    def list_tech_dispatches(self, headers, params=None):
        return self._request("GET", "/v1/tech-dispatches", headers=headers, params=params)

    def get_tech_dispatch(self, dispatch_id, headers):
        return self._request("GET", f"/v1/tech-dispatches/{dispatch_id}", headers=headers)

    def mark_dispatch_en_route(self, dispatch_id, headers):
        return self._request("POST", f"/v1/tech-dispatches/{dispatch_id}/mark-en-route", headers=headers)

    def mark_dispatch_on_site(self, dispatch_id, headers):
        return self._request("POST", f"/v1/tech-dispatches/{dispatch_id}/mark-on-site", headers=headers)

    def complete_dispatch(self, dispatch_id, payload, headers):
        return self._request("POST", f"/v1/tech-dispatches/{dispatch_id}/complete", payload, headers)

    def abort_dispatch(self, dispatch_id, headers):
        return self._request("POST", f"/v1/tech-dispatches/{dispatch_id}/abort", headers=headers)


api_client = ApiClient()
