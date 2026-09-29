"""API client: one method per endpoint defined in the PRD (§4)."""
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------------- Reference data (PRD §3.1) ----------------
    def create_patient(self, payload, headers):
        return self._request("POST", "/patients", payload, headers)

    def create_clinician(self, payload, headers):
        return self._request("POST", "/clinicians", payload, headers)

    def create_drug(self, payload, headers):
        return self._request("POST", "/drugs", payload, headers)

    def create_payer_plan(self, payload, headers):
        return self._request("POST", "/payer-plans", payload, headers)

    def create_infusion_chair(self, payload, headers):
        return self._request("POST", "/infusion-chairs", payload, headers)

    def update_infusion_chair(self, chair_id, payload, headers):
        return self._request("PATCH", f"/infusion-chairs/{chair_id}", payload, headers)

    # ---------------- Visits (PRD §3.2) ----------------
    def create_visit(self, payload, headers):
        return self._request("POST", "/visits", payload, headers)

    def check_in_visit(self, visit_id, headers, payload=None):
        return self._request("POST", f"/visits/{visit_id}/check-in", payload or {}, headers)

    def score_visit(self, visit_id, payload, headers):
        return self._request("POST", f"/visits/{visit_id}/score", payload, headers)

    def get_visit(self, visit_id, headers):
        return self._request("GET", f"/visits/{visit_id}", headers=headers)

    def list_visits(self, headers, params=None):
        return self._request("GET", "/visits", headers=headers, params=params)

    # ---------------- Screening (PRD §3.3) ----------------
    def create_screening_record(self, payload, headers):
        return self._request("POST", "/screening-records", payload, headers)

    def list_patient_screening_records(self, patient_id, headers, params=None):
        return self._request(
            "GET", f"/patients/{patient_id}/screening-records", headers=headers, params=params
        )

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/patients/{patient_id}", headers=headers)

    def get_quality_report(self, patient_id, headers, params=None):
        return self._request(
            "GET", f"/patients/{patient_id}/quality-report", headers=headers, params=params
        )

    # ---------------- Therapy episodes (PRD §3.4, §3.9) ----------------
    def create_therapy_episode(self, payload, headers):
        return self._request("POST", "/therapy-episodes", payload, headers)

    def get_therapy_episode(self, episode_id, headers):
        return self._request("GET", f"/therapy-episodes/{episode_id}", headers=headers)

    def list_therapy_episodes(self, headers, params=None):
        return self._request("GET", "/therapy-episodes", headers=headers, params=params)

    def activate_therapy_episode(self, episode_id, headers, payload=None):
        return self._request(
            "POST", f"/therapy-episodes/{episode_id}/activate", payload or {}, headers
        )

    def hold_therapy_episode(self, episode_id, payload, headers):
        return self._request("POST", f"/therapy-episodes/{episode_id}/hold", payload, headers)

    def resume_therapy_episode(self, episode_id, payload, headers):
        return self._request("POST", f"/therapy-episodes/{episode_id}/resume", payload, headers)

    def discontinue_therapy_episode(self, episode_id, payload, headers):
        return self._request(
            "POST", f"/therapy-episodes/{episode_id}/discontinue", payload, headers
        )

    def record_training(self, episode_id, payload, headers):
        return self._request(
            "POST", f"/therapy-episodes/{episode_id}/record-training", payload, headers
        )

    def get_cost_share_estimate(self, episode_id, headers, params=None):
        return self._request(
            "GET",
            f"/therapy-episodes/{episode_id}/cost-share-estimate",
            headers=headers,
            params=params,
        )

    # ---------------- Monitoring labs (PRD §3.6) ----------------
    def create_monitoring_lab(self, payload, headers):
        return self._request("POST", "/monitoring-labs", payload, headers)

    def list_episode_monitoring_labs(self, episode_id, headers, params=None):
        return self._request(
            "GET", f"/therapy-episodes/{episode_id}/monitoring-labs", headers=headers, params=params
        )

    # ---------------- Authorizations (PRD §3.5) ----------------
    def create_authorization(self, payload, headers):
        return self._request("POST", "/authorizations", payload, headers)

    def attest_exception(self, authorization_id, headers, payload=None):
        return self._request(
            "POST", f"/authorizations/{authorization_id}/attest-exception", payload or {}, headers
        )

    def submit_authorization(self, authorization_id, headers, payload=None):
        return self._request(
            "POST", f"/authorizations/{authorization_id}/submit", payload or {}, headers
        )

    def determine_authorization(self, authorization_id, payload, headers):
        return self._request(
            "POST", f"/authorizations/{authorization_id}/determination", payload, headers
        )

    def get_authorization(self, authorization_id, headers):
        return self._request("GET", f"/authorizations/{authorization_id}", headers=headers)

    def list_authorizations(self, headers, params=None):
        return self._request("GET", "/authorizations", headers=headers, params=params)

    # ---------------- Infusion appointments (PRD §3.7) ----------------
    def create_infusion_appointment(self, payload, headers):
        return self._request("POST", "/infusion-appointments", payload, headers)

    def administer_appointment(self, appointment_id, headers, payload=None):
        return self._request(
            "POST", f"/infusion-appointments/{appointment_id}/administer", payload or {}, headers
        )

    def reverse_administration(self, appointment_id, payload, headers):
        return self._request(
            "POST",
            f"/infusion-appointments/{appointment_id}/reverse-administration",
            payload,
            headers,
        )

    def cancel_appointment(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"/infusion-appointments/{appointment_id}/cancel", payload, headers
        )

    def get_infusion_appointment(self, appointment_id, headers):
        return self._request("GET", f"/infusion-appointments/{appointment_id}", headers=headers)

    def list_infusion_appointments(self, headers, params=None):
        return self._request("GET", "/infusion-appointments", headers=headers, params=params)

    # ---------------- Assistance enrollments (PRD §3.8) ----------------
    def create_assistance_enrollment(self, payload, headers):
        return self._request("POST", "/assistance-enrollments", payload, headers)

    def attest_enrollment(self, enrollment_id, headers, payload=None):
        return self._request(
            "POST", f"/assistance-enrollments/{enrollment_id}/attest", payload or {}, headers
        )

    def reauthorize_enrollment(self, enrollment_id, payload, headers):
        return self._request(
            "POST", f"/assistance-enrollments/{enrollment_id}/reauthorize", payload, headers
        )

    def get_assistance_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/assistance-enrollments/{enrollment_id}", headers=headers)

    def list_episode_assistance_enrollments(self, episode_id, headers, params=None):
        return self._request(
            "GET",
            f"/therapy-episodes/{episode_id}/assistance-enrollments",
            headers=headers,
            params=params,
        )

    # ---------------- Logical clock and deferred sweep (PRD §2.11) ----------------
    def set_clock(self, current_utc, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    def set_clock_raw(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def run_reauthorization_calendar(self, headers, payload=None):
        return self._request(
            "POST", "/_ops/run-reauthorization-calendar", payload or {}, headers
        )

    # ---------------- Generic escape hatch (raw path / raw payload) ----------------
    def raw(
        self,
        method: str,
        path: str,
        payload: Any = None,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict] = None,
    ):
        return self._request(method, path, payload, headers, params)


api_client = ApiClient()
