"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (PRD §2.4) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)

    # --- City programs (PRD §3.1) ---
    def create_city_program(self, payload, headers):
        return self._request("POST", "/api/city-programs", payload, headers)

    def get_city_program(self, city_program_id, headers):
        return self._request("GET", f"/api/city-programs/{city_program_id}", headers=headers)

    # --- Nominating partners (PRD §3.1) ---
    def create_nominating_partner(self, payload, headers):
        return self._request("POST", "/api/nominating-partners", payload, headers)

    def list_partners(self, city_program_id, headers, params=None):
        return self._request(
            "GET", f"/api/city-programs/{city_program_id}/partners", headers=headers, params=params
        )

    # --- Nominees (PRD §3.1, §3.2) ---
    def create_nominee(self, payload, headers):
        return self._request("POST", "/api/nominees", payload, headers)

    def list_nominees(self, headers, params=None):
        return self._request("GET", "/api/nominees", headers=headers, params=params)

    def get_nominee(self, nominee_id, headers):
        return self._request("GET", f"/api/nominees/{nominee_id}", headers=headers)

    def withdraw_nominee(self, nominee_id, headers):
        return self._request("POST", f"/api/nominees/{nominee_id}/withdraw", {}, headers)

    def decide_nominee(self, nominee_id, payload, headers):
        return self._request("POST", f"/api/nominees/{nominee_id}/decision", payload, headers)

    def list_evaluations(self, nominee_id, headers, params=None):
        return self._request(
            "GET", f"/api/nominees/{nominee_id}/evaluations", headers=headers, params=params
        )

    # --- Evaluations (PRD §3.2) ---
    def create_evaluation(self, payload, headers):
        return self._request("POST", "/api/evaluations", payload, headers)

    # --- Partner colleges (PRD §3.3, §3.9) ---
    def create_partner_college(self, payload, headers):
        return self._request("POST", "/api/partner-colleges", payload, headers)

    def get_partner_college(self, college_id, headers):
        return self._request("GET", f"/api/partner-colleges/{college_id}", headers=headers)

    def get_college_outcomes(self, college_id, headers):
        return self._request("GET", f"/api/partner-colleges/{college_id}/outcomes", headers=headers)

    def list_college_agreements(self, college_id, headers, params=None):
        return self._request(
            "GET", f"/api/partner-colleges/{college_id}/agreements", headers=headers, params=params
        )

    def list_college_mentors(self, college_id, headers, params=None):
        return self._request(
            "GET", f"/api/partner-colleges/{college_id}/mentors", headers=headers, params=params
        )

    def renewal_review(self, college_id, payload, headers):
        return self._request(
            "POST", f"/api/partner-colleges/{college_id}/renewal-review", payload, headers
        )

    # --- Mentors (PRD §3.3) ---
    def create_mentor(self, payload, headers):
        return self._request("POST", "/api/mentors", payload, headers)

    # --- Partner agreements (PRD §2.6, §3.3) ---
    def create_partner_agreement(self, payload, headers):
        return self._request("POST", "/api/partner-agreements", payload, headers)

    def activate_agreement(self, agreement_id, headers):
        return self._request("POST", f"/api/partner-agreements/{agreement_id}/activate", {}, headers)

    # --- Cohorts (PRD §3.4, §3.6) ---
    def create_cohort(self, payload, headers):
        return self._request("POST", "/api/cohorts", payload, headers)

    def list_cohorts(self, headers, params=None):
        return self._request("GET", "/api/cohorts", headers=headers, params=params)

    def get_cohort(self, cohort_id, headers):
        return self._request("GET", f"/api/cohorts/{cohort_id}", headers=headers)

    def matriculate_cohort(self, cohort_id, headers):
        return self._request("POST", f"/api/cohorts/{cohort_id}/matriculate", {}, headers)

    # --- Offers (PRD §3.5) ---
    def create_offer(self, payload, headers):
        return self._request("POST", "/api/offers", payload, headers)

    def list_offers(self, headers, params=None):
        return self._request("GET", "/api/offers", headers=headers, params=params)

    def get_offer(self, offer_id, headers):
        return self._request("GET", f"/api/offers/{offer_id}", headers=headers)

    def accept_offer(self, offer_id, headers):
        return self._request("POST", f"/api/offers/{offer_id}/accept", {}, headers)

    def decline_offer(self, offer_id, headers):
        return self._request("POST", f"/api/offers/{offer_id}/decline", {}, headers)

    # --- Scholars (PRD §3.7) ---
    def list_scholars(self, headers, params=None):
        return self._request("GET", "/api/scholars", headers=headers, params=params)

    def get_scholar(self, scholar_id, headers):
        return self._request("GET", f"/api/scholars/{scholar_id}", headers=headers)

    def list_training_records(self, scholar_id, headers, params=None):
        return self._request(
            "GET", f"/api/scholars/{scholar_id}/training-records", headers=headers, params=params
        )

    def list_scholar_internships(self, scholar_id, headers, params=None):
        return self._request(
            "GET", f"/api/scholars/{scholar_id}/internships", headers=headers, params=params
        )

    def scholar_lifecycle(self, scholar_id, payload, headers):
        return self._request("POST", f"/api/scholars/{scholar_id}/lifecycle", payload, headers)

    # --- Training records (PRD §3.7) ---
    def complete_training_record(self, record_id, headers):
        return self._request("POST", f"/api/training-records/{record_id}/complete", {}, headers)

    # --- Cohort meetings (PRD §3.8) ---
    def create_cohort_meeting(self, payload, headers):
        return self._request("POST", "/api/cohort-meetings", payload, headers)

    def list_cohort_meetings(self, cohort_id, headers, params=None):
        return self._request(
            "GET", f"/api/cohorts/{cohort_id}/meetings", headers=headers, params=params
        )

    # --- Internships (PRD §3.8) ---
    def create_internship(self, payload, headers):
        return self._request("POST", "/api/internships", payload, headers)

    def transition_internship(self, internship_id, payload, headers):
        return self._request("POST", f"/api/internships/{internship_id}/transition", payload, headers)


api_client = ApiClient()
