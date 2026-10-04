"""API client: one method per endpoint defined in the PRD (§4).

All paths are mounted under /api. Methods return raw requests.Response so
tests assert status codes and envelopes themselves; fixtures wrap the same
methods with the framework's lenient get_success_data().
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- logical clock (PRD §2.5) ----------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/api/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---- program cycles (PRD §3.1) ---------------------------------------
    def create_program_cycle(self, payload, headers):
        return self._request("POST", "/api/program-cycles", payload, headers)

    def get_program_cycle(self, cycle_id, headers):
        return self._request("GET", f"/api/program-cycles/{cycle_id}", headers=headers)

    def list_state_allocations(self, cycle_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/program-cycles/{cycle_id}/state-allocations",
            headers=headers,
            params=params,
        )

    def open_entries(self, cycle_id, headers):
        return self._request(
            "POST", f"/api/program-cycles/{cycle_id}/open-entries", {}, headers
        )

    def close_entries(self, cycle_id, headers):
        return self._request(
            "POST", f"/api/program-cycles/{cycle_id}/close-entries", {}, headers
        )

    def run_semifinalist_selection(self, cycle_id, headers):
        return self._request(
            "POST",
            f"/api/program-cycles/{cycle_id}/run-semifinalist-selection",
            {},
            headers,
        )

    def publish_finalists(self, cycle_id, headers):
        return self._request(
            "POST", f"/api/program-cycles/{cycle_id}/publish-finalists", {}, headers
        )

    def run_award_matching(self, cycle_id, headers):
        return self._request(
            "POST", f"/api/program-cycles/{cycle_id}/run-award-matching", {}, headers
        )

    # ---- schools and students (PRD §3.3) ----------------------------------
    def create_school(self, payload, headers):
        return self._request("POST", "/api/schools", payload, headers)

    def create_student(self, payload, headers):
        return self._request("POST", "/api/students", payload, headers)

    def get_student(self, student_id, headers):
        return self._request("GET", f"/api/students/{student_id}", headers=headers)

    def list_students(self, headers, params=None):
        return self._request("GET", "/api/students", headers=headers, params=params)

    # ---- entries (PRD §3.3, §3.4) ------------------------------------------
    def create_entry(self, payload, headers):
        return self._request("POST", "/api/entries", payload, headers)

    def get_entry(self, entry_id, headers):
        return self._request("GET", f"/api/entries/{entry_id}", headers=headers)

    def list_entries(self, headers, params=None):
        return self._request("GET", "/api/entries", headers=headers, params=params)

    def score_entry(self, entry_id, payload, headers):
        return self._request("POST", f"/api/entries/{entry_id}/score", payload, headers)

    # ---- finalist applications (PRD §3.5) ----------------------------------
    def create_finalist_application(self, payload, headers):
        return self._request("POST", "/api/finalist-applications", payload, headers)

    def get_finalist_application(self, application_id, headers):
        return self._request(
            "GET", f"/api/finalist-applications/{application_id}", headers=headers
        )

    def list_finalist_applications(self, headers, params=None):
        return self._request(
            "GET", "/api/finalist-applications", headers=headers, params=params
        )

    def endorse_application(self, application_id, headers):
        return self._request(
            "POST", f"/api/finalist-applications/{application_id}/endorse", {}, headers
        )

    def submit_application(self, application_id, headers):
        return self._request(
            "POST", f"/api/finalist-applications/{application_id}/submit", {}, headers
        )

    def review_application(self, application_id, payload, headers):
        return self._request(
            "POST",
            f"/api/finalist-applications/{application_id}/review",
            payload,
            headers,
        )

    # ---- corporate sponsors and agreements (PRD §3.6) ----------------------
    def create_corporate_sponsor(self, payload, headers):
        return self._request("POST", "/api/corporate-sponsors", payload, headers)

    def create_sponsor_agreement(self, sponsor_id, payload, headers):
        return self._request(
            "POST", f"/api/corporate-sponsors/{sponsor_id}/agreements", payload, headers
        )

    def get_sponsor_agreement(self, agreement_id, headers):
        return self._request(
            "GET", f"/api/sponsor-agreements/{agreement_id}", headers=headers
        )

    def list_sponsor_agreements(self, headers, params=None):
        return self._request(
            "GET", "/api/sponsor-agreements", headers=headers, params=params
        )

    def amend_sponsor_agreement(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/api/sponsor-agreements/{agreement_id}/amend", payload, headers
        )

    # ---- college institutions (PRD §3.6) -----------------------------------
    def create_college_institution(self, payload, headers):
        return self._request("POST", "/api/college-institutions", payload, headers)

    def get_college_institution(self, college_id, headers):
        return self._request(
            "GET", f"/api/college-institutions/{college_id}", headers=headers
        )

    # ---- awards (PRD §3.7, §3.8) -------------------------------------------
    def get_award(self, award_id, headers):
        return self._request("GET", f"/api/awards/{award_id}", headers=headers)

    def list_awards(self, headers, params=None):
        return self._request("GET", "/api/awards", headers=headers, params=params)

    def accept_award(self, award_id, headers):
        return self._request("POST", f"/api/awards/{award_id}/accept", {}, headers)

    def decline_award(self, award_id, headers):
        return self._request("POST", f"/api/awards/{award_id}/decline", {}, headers)

    def list_award_disbursements(self, award_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/awards/{award_id}/disbursements",
            headers=headers,
            params=params,
        )

    def list_award_renewal_verifications(self, award_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/awards/{award_id}/renewal-verifications",
            headers=headers,
            params=params,
        )

    # ---- disbursements (PRD §3.8) ------------------------------------------
    def release_disbursement(self, disbursement_id, headers):
        return self._request(
            "POST", f"/api/disbursements/{disbursement_id}/release", {}, headers
        )

    # ---- renewal verifications (PRD §3.8) ----------------------------------
    def create_renewal_verification(self, award_id, payload, headers):
        return self._request(
            "POST",
            f"/api/awards/{award_id}/renewal-verifications",
            payload,
            headers,
        )

    def decide_renewal_verification(self, verification_id, payload, headers):
        return self._request(
            "POST",
            f"/api/renewal-verifications/{verification_id}/decision",
            payload,
            headers,
        )

    # ---- notifications (PRD §3.9) ------------------------------------------
    def list_student_notifications(self, student_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/students/{student_id}/notifications",
            headers=headers,
            params=params,
        )

    def release_notification(self, notification_id, headers):
        return self._request(
            "POST", f"/api/notifications/{notification_id}/release", {}, headers
        )


api_client = ApiClient()
