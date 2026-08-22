"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Logical clock ────────────────────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ─── Districts ────────────────────────────────────────────────────────
    def create_district(self, payload, headers):
        return self._request("POST", "/districts", payload, headers)

    def get_district(self, district_id, headers):
        return self._request("GET", f"/districts/{district_id}", headers=headers)

    # ─── Schools ──────────────────────────────────────────────────────────
    def create_school(self, payload, headers):
        return self._request("POST", "/schools", payload, headers)

    def get_school(self, school_id, headers):
        return self._request("GET", f"/schools/{school_id}", headers=headers)

    def list_schools(self, headers, params=None):
        return self._request("GET", "/schools", headers=headers, params=params)

    # ─── Test windows ─────────────────────────────────────────────────────
    def create_test_window(self, payload, headers):
        return self._request("POST", "/test-windows", payload, headers)

    def get_test_window(self, window_id, headers):
        return self._request("GET", f"/test-windows/{window_id}", headers=headers)

    def list_test_windows(self, headers, params=None):
        return self._request("GET", "/test-windows", headers=headers, params=params)

    def transition_test_window(self, window_id, payload, headers):
        return self._request(
            "POST", f"/test-windows/{window_id}/transitions", payload, headers)

    def run_report_distribution(self, window_id, headers, payload=None):
        return self._request(
            "POST", f"/test-windows/{window_id}/report-distribution-runs",
            payload if payload is not None else {}, headers)

    # ─── Material lots and chain of custody ───────────────────────────────
    def create_material_lot(self, payload, headers):
        return self._request("POST", "/material-lots", payload, headers)

    def get_material_lot(self, material_lot_id, headers):
        return self._request(
            "GET", f"/material-lots/{material_lot_id}", headers=headers)

    def list_material_lots(self, headers, params=None):
        return self._request("GET", "/material-lots", headers=headers, params=params)

    def create_custody_event(self, material_lot_id, payload, headers):
        return self._request(
            "POST", f"/material-lots/{material_lot_id}/custody-events",
            payload, headers)

    def get_custody_event(self, custody_event_id, headers):
        return self._request(
            "GET", f"/custody-events/{custody_event_id}", headers=headers)

    def list_custody_events(self, headers, params=None):
        return self._request("GET", "/custody-events", headers=headers, params=params)

    def reconcile_material_lot(self, material_lot_id, payload, headers):
        return self._request(
            "POST", f"/material-lots/{material_lot_id}/reconciliations",
            payload, headers)

    # ─── Proctors, training and affidavits ────────────────────────────────
    def create_proctor(self, payload, headers):
        return self._request("POST", "/proctors", payload, headers)

    def get_proctor(self, proctor_id, headers):
        return self._request("GET", f"/proctors/{proctor_id}", headers=headers)

    def list_proctors(self, headers, params=None):
        return self._request("GET", "/proctors", headers=headers, params=params)

    def record_training_completion(self, proctor_id, payload, headers):
        return self._request(
            "POST", f"/proctors/{proctor_id}/training-completions", payload, headers)

    def create_security_affidavit(self, payload, headers):
        return self._request("POST", "/security-affidavits", payload, headers)

    def get_security_affidavit(self, security_affidavit_id, headers):
        return self._request(
            "GET", f"/security-affidavits/{security_affidavit_id}", headers=headers)

    def list_security_affidavits(self, headers, params=None):
        return self._request(
            "GET", "/security-affidavits", headers=headers, params=params)

    # ─── Sessions ─────────────────────────────────────────────────────────
    def create_session(self, payload, headers):
        return self._request("POST", "/sessions", payload, headers)

    def get_session(self, session_id, headers):
        return self._request("GET", f"/sessions/{session_id}", headers=headers)

    def list_sessions(self, headers, params=None):
        return self._request("GET", "/sessions", headers=headers, params=params)

    def assign_proctor(self, session_id, payload, headers):
        return self._request(
            "POST", f"/sessions/{session_id}/proctor-assignments", payload, headers)

    def transition_session(self, session_id, payload, headers):
        return self._request(
            "POST", f"/sessions/{session_id}/transitions", payload, headers)

    # ─── Registrations ────────────────────────────────────────────────────
    def create_registration(self, payload, headers):
        return self._request("POST", "/registrations", payload, headers)

    def get_registration(self, registration_id, headers):
        return self._request(
            "GET", f"/registrations/{registration_id}", headers=headers)

    def list_registrations(self, headers, params=None):
        return self._request("GET", "/registrations", headers=headers, params=params)

    def code_accommodations(self, registration_id, payload, headers):
        return self._request(
            "POST", f"/registrations/{registration_id}/accommodation-codings",
            payload, headers)

    def decide_accommodations(self, registration_id, payload, headers):
        return self._request(
            "POST", f"/registrations/{registration_id}/accommodation-decisions",
            payload, headers)

    def record_attendance(self, registration_id, payload, headers):
        return self._request(
            "POST", f"/registrations/{registration_id}/attendance", payload, headers)

    def record_score(self, registration_id, payload, headers):
        return self._request(
            "POST", f"/registrations/{registration_id}/scores", payload, headers)

    # ─── Irregularity reports ─────────────────────────────────────────────
    def create_irregularity_report(self, payload, headers):
        return self._request("POST", "/irregularity-reports", payload, headers)

    def get_irregularity_report(self, irregularity_report_id, headers):
        return self._request(
            "GET", f"/irregularity-reports/{irregularity_report_id}", headers=headers)

    def list_irregularity_reports(self, headers, params=None):
        return self._request(
            "GET", "/irregularity-reports", headers=headers, params=params)

    def transition_irregularity_report(self, irregularity_report_id, payload, headers):
        return self._request(
            "POST", f"/irregularity-reports/{irregularity_report_id}/transitions",
            payload, headers)

    # ─── Score appeals ────────────────────────────────────────────────────
    def create_score_appeal(self, payload, headers):
        return self._request("POST", "/score-appeals", payload, headers)

    def get_score_appeal(self, score_appeal_id, headers):
        return self._request(
            "GET", f"/score-appeals/{score_appeal_id}", headers=headers)

    def list_score_appeals(self, headers, params=None):
        return self._request("GET", "/score-appeals", headers=headers, params=params)

    def decide_score_appeal(self, score_appeal_id, payload, headers):
        return self._request(
            "POST", f"/score-appeals/{score_appeal_id}/decisions", payload, headers)


api_client = ApiClient()
