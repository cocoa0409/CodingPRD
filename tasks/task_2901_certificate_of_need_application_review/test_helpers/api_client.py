"""API client: one method per endpoint defined in the PRD.

All collections are mounted at the root; there is no shared URL prefix.
"""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Planning areas ───────────────────────────────

    def create_health_service_area(self, payload, headers):
        return self._request("POST", "/health-service-areas", payload, headers)

    def get_health_service_area(self, hsa_id, headers):
        return self._request(
            "GET", f"/health-service-areas/{hsa_id}", headers=headers
        )

    # ─── State plan formulas ──────────────────────────

    def create_state_plan_formula(self, payload, headers):
        return self._request("POST", "/state-plan-formulas", payload, headers)

    def amend_state_plan_formula(self, formula_id, payload, headers):
        return self._request(
            "PATCH", f"/state-plan-formulas/{formula_id}", payload, headers
        )

    # ─── Hearing rooms ────────────────────────────────

    def create_hearing_room(self, payload, headers):
        return self._request("POST", "/hearing-rooms", payload, headers)

    # ─── Logical clock ────────────────────────────────

    def set_clock(self, to_iso8601, headers=None):
        return self._request(
            "POST",
            "/_clock/set_current_utc",
            {"to_iso8601": to_iso8601},
            headers,
        )

    # ─── Applicants ───────────────────────────────────

    def create_applicant(self, payload, headers):
        return self._request("POST", "/applicants", payload, headers)

    def get_applicant(self, applicant_id, headers):
        return self._request("GET", f"/applicants/{applicant_id}", headers=headers)

    # ─── Batching cycles ──────────────────────────────

    def create_batching_cycle(self, payload, headers):
        return self._request("POST", "/batching-cycles", payload, headers)

    def get_batching_cycle(self, cycle_id, headers):
        return self._request("GET", f"/batching-cycles/{cycle_id}", headers=headers)

    def list_batching_cycles(self, headers, params=None):
        return self._request("GET", "/batching-cycles", headers=headers, params=params)

    def advance_batching_cycle(self, cycle_id, to_status, headers):
        return self._request(
            "POST",
            f"/batching-cycles/{cycle_id}/advance",
            {"to_status": to_status},
            headers,
        )

    def recompute_need(self, cycle_id, headers, payload=None):
        return self._request(
            "POST",
            f"/batching-cycles/{cycle_id}/recompute-need",
            payload if payload is not None else {},
            headers,
        )

    def get_need_analysis(self, cycle_id, headers):
        return self._request(
            "GET", f"/batching-cycles/{cycle_id}/need-analysis", headers=headers
        )

    def run_comparative_decision(self, cycle_id, payload, headers):
        return self._request(
            "POST",
            f"/batching-cycles/{cycle_id}/comparative-decision",
            payload,
            headers,
        )

    # ─── Letters of intent ────────────────────────────

    def create_letter_of_intent(self, payload, headers):
        return self._request("POST", "/letters-of-intent", payload, headers)

    def get_letter_of_intent(self, loi_id, headers):
        return self._request("GET", f"/letters-of-intent/{loi_id}", headers=headers)

    def list_letters_of_intent(self, headers, params=None):
        return self._request(
            "GET", "/letters-of-intent", headers=headers, params=params
        )

    def withdraw_letter_of_intent(self, loi_id, payload, headers):
        return self._request(
            "POST", f"/letters-of-intent/{loi_id}/withdraw", payload, headers
        )

    # ─── Applications ─────────────────────────────────

    def create_application(self, payload, headers):
        return self._request("POST", "/applications", payload, headers)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/applications/{application_id}", headers=headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/applications", headers=headers, params=params)

    def submit_application(self, application_id, headers, payload=None):
        return self._request(
            "POST",
            f"/applications/{application_id}/submit",
            payload if payload is not None else {},
            headers,
        )

    def withdraw_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"/applications/{application_id}/withdraw", payload, headers
        )

    # ─── Completeness reviews ─────────────────────────

    def issue_deficiency_notice(self, application_id, payload, headers):
        return self._request(
            "POST",
            f"/applications/{application_id}/completeness-reviews",
            payload,
            headers,
        )

    def list_completeness_reviews(self, application_id, headers, params=None):
        return self._request(
            "GET",
            f"/applications/{application_id}/completeness-reviews",
            headers=headers,
            params=params,
        )

    def file_cure(self, completeness_review_id, payload, headers):
        return self._request(
            "POST",
            f"/completeness-reviews/{completeness_review_id}/cure",
            payload,
            headers,
        )

    def deem_application_complete(self, application_id, headers, payload=None):
        return self._request(
            "POST",
            f"/applications/{application_id}/deem-complete",
            payload if payload is not None else {},
            headers,
        )

    # ─── Public comments ──────────────────────────────

    def create_public_comment(self, application_id, payload, headers):
        return self._request(
            "POST", f"/applications/{application_id}/public-comments", payload, headers
        )

    def list_public_comments(self, application_id, headers, params=None):
        return self._request(
            "GET",
            f"/applications/{application_id}/public-comments",
            headers=headers,
            params=params,
        )

    # ─── Interventions ────────────────────────────────

    def create_intervention(self, payload, headers):
        return self._request("POST", "/interventions", payload, headers)

    def get_intervention(self, intervention_id, headers):
        return self._request(
            "GET", f"/interventions/{intervention_id}", headers=headers
        )

    def list_interventions(self, headers, params=None):
        return self._request("GET", "/interventions", headers=headers, params=params)

    def decide_intervention(self, intervention_id, payload, headers):
        return self._request(
            "POST", f"/interventions/{intervention_id}/decide", payload, headers
        )

    # ─── Public hearings ──────────────────────────────

    def create_public_hearing(self, payload, headers):
        return self._request("POST", "/public-hearings", payload, headers)

    def get_public_hearing(self, hearing_id, headers):
        return self._request("GET", f"/public-hearings/{hearing_id}", headers=headers)

    def list_public_hearings(self, headers, params=None):
        return self._request("GET", "/public-hearings", headers=headers, params=params)

    def cancel_public_hearing(self, hearing_id, payload, headers):
        return self._request(
            "POST", f"/public-hearings/{hearing_id}/cancel", payload, headers
        )

    def reschedule_public_hearing(self, hearing_id, payload, headers):
        return self._request(
            "POST", f"/public-hearings/{hearing_id}/reschedule", payload, headers
        )

    def conclude_public_hearing(self, hearing_id, payload, headers):
        return self._request(
            "POST", f"/public-hearings/{hearing_id}/conclude", payload, headers
        )

    # ─── Score sheets ─────────────────────────────────

    def create_score_sheet(self, payload, headers):
        return self._request("POST", "/score-sheets", payload, headers)

    def list_score_sheets(self, application_id, headers, params=None):
        return self._request(
            "GET",
            f"/applications/{application_id}/score-sheets",
            headers=headers,
            params=params,
        )

    # ─── Certificates ─────────────────────────────────

    def create_certificate(self, payload, headers):
        return self._request("POST", "/certificates", payload, headers)

    def get_certificate(self, certificate_id, headers):
        return self._request("GET", f"/certificates/{certificate_id}", headers=headers)

    def list_certificates(self, headers, params=None):
        return self._request("GET", "/certificates", headers=headers, params=params)

    def extend_certificate(self, certificate_id, payload, headers):
        return self._request(
            "POST", f"/certificates/{certificate_id}/extend", payload, headers
        )

    def modify_certificate(self, certificate_id, payload, headers):
        return self._request(
            "POST", f"/certificates/{certificate_id}/modify", payload, headers
        )

    def run_lapse_sweep(self, headers, payload=None):
        return self._request(
            "POST",
            "/certificates/run-lapse-sweep",
            payload if payload is not None else {},
            headers,
        )

    # ─── Progress reports ─────────────────────────────

    def create_progress_report(self, payload, headers):
        return self._request("POST", "/progress-reports", payload, headers)

    def list_progress_reports(self, certificate_id, headers, params=None):
        return self._request(
            "GET",
            f"/certificates/{certificate_id}/progress-reports",
            headers=headers,
            params=params,
        )

    # ─── Appeals ──────────────────────────────────────

    def create_appeal(self, payload, headers):
        return self._request("POST", "/appeals", payload, headers)

    def get_appeal(self, appeal_id, headers):
        return self._request("GET", f"/appeals/{appeal_id}", headers=headers)

    def list_appeals(self, headers, params=None):
        return self._request("GET", "/appeals", headers=headers, params=params)

    def advance_appeal(self, appeal_id, to_status, headers):
        return self._request(
            "POST", f"/appeals/{appeal_id}/advance", {"to_status": to_status}, headers
        )

    def set_litigation_hold(self, appeal_id, action, headers):
        return self._request(
            "POST", f"/appeals/{appeal_id}/litigation-hold", {"action": action}, headers
        )

    def decide_appeal(self, appeal_id, payload, headers):
        return self._request(
            "POST", f"/appeals/{appeal_id}/decide", payload, headers
        )


api_client = ApiClient()
