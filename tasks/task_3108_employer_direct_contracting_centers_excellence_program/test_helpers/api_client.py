"""API client: one method per endpoint defined in the PRD (§4 endpoint index)."""
from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (test-driving) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/coe/_clock/set_current_utc", payload, headers)

    # --- Employers ---
    def create_employer(self, payload, headers):
        return self._request("POST", "/coe/employers", payload, headers)

    def list_employers(self, headers, params=None):
        return self._request("GET", "/coe/employers", headers=headers, params=params)

    def get_employer(self, employer_id, headers):
        return self._request("GET", f"/coe/employers/{employer_id}", headers=headers)

    def terminate_employer(self, employer_id, headers):
        return self._request(
            "POST", f"/coe/employers/{employer_id}/terminate", {}, headers
        )

    def list_employer_contracts(self, employer_id, headers, params=None):
        return self._request(
            "GET", f"/coe/employers/{employer_id}/contracts",
            headers=headers, params=params,
        )

    def list_employer_patients(self, employer_id, headers, params=None):
        return self._request(
            "GET", f"/coe/employers/{employer_id}/patients",
            headers=headers, params=params,
        )

    def list_employer_reports(self, employer_id, headers, params=None):
        return self._request(
            "GET", f"/coe/employers/{employer_id}/reports",
            headers=headers, params=params,
        )

    def generate_employer_report(self, employer_id, payload, headers):
        return self._request(
            "POST", f"/coe/employers/{employer_id}/reports/generate", payload, headers
        )

    # --- Bundle templates ---
    def create_bundle_template(self, payload, headers):
        return self._request("POST", "/coe/bundle-templates", payload, headers)

    def get_bundle_template(self, template_id, headers):
        return self._request(
            "GET", f"/coe/bundle-templates/{template_id}", headers=headers
        )

    def retire_bundle_template(self, template_id, headers):
        return self._request(
            "POST", f"/coe/bundle-templates/{template_id}/retire", {}, headers
        )

    # --- Rate books ---
    def create_rate_book(self, payload, headers):
        return self._request("POST", "/coe/rate-books", payload, headers)

    def get_rate_book(self, rate_book_id, headers):
        return self._request("GET", f"/coe/rate-books/{rate_book_id}", headers=headers)

    # --- Contracts ---
    def create_contract(self, payload, headers):
        return self._request("POST", "/coe/contracts", payload, headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/coe/contracts", headers=headers, params=params)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/coe/contracts/{contract_id}", headers=headers)

    def activate_contract(self, contract_id, headers):
        return self._request(
            "POST", f"/coe/contracts/{contract_id}/activate", {}, headers
        )

    def reprice_contract(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/coe/contracts/{contract_id}/reprice", payload, headers
        )

    def terminate_contract(self, contract_id, headers):
        return self._request(
            "POST", f"/coe/contracts/{contract_id}/terminate", {}, headers
        )

    # --- Patients ---
    def create_patient(self, payload, headers):
        return self._request("POST", "/coe/patients", payload, headers)

    def list_patients(self, headers, params=None):
        return self._request("GET", "/coe/patients", headers=headers, params=params)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/coe/patients/{patient_id}", headers=headers)

    # --- Episodes ---
    def create_episode(self, payload, headers):
        return self._request("POST", "/coe/episodes", payload, headers)

    def list_episodes(self, headers, params=None):
        return self._request("GET", "/coe/episodes", headers=headers, params=params)

    def get_episode(self, episode_id, headers, params=None):
        return self._request(
            "GET", f"/coe/episodes/{episode_id}", headers=headers, params=params
        )

    # --- Screenings ---
    def submit_screening(self, episode_id, payload, headers):
        return self._request(
            "POST", f"/coe/episodes/{episode_id}/screenings", payload, headers
        )

    def list_screenings(self, episode_id, headers, params=None):
        return self._request(
            "GET", f"/coe/episodes/{episode_id}/screenings",
            headers=headers, params=params,
        )

    def get_screening(self, screening_id, headers):
        return self._request("GET", f"/coe/screenings/{screening_id}", headers=headers)

    # --- Reviews ---
    def record_review(self, episode_id, payload, headers):
        return self._request(
            "POST", f"/coe/episodes/{episode_id}/reviews", payload, headers
        )

    def list_reviews(self, episode_id, headers, params=None):
        return self._request(
            "GET", f"/coe/episodes/{episode_id}/reviews",
            headers=headers, params=params,
        )

    def get_review(self, review_id, headers):
        return self._request("GET", f"/coe/reviews/{review_id}", headers=headers)

    # --- Scheduling ---
    def schedule_episode(self, episode_id, payload, headers):
        return self._request(
            "POST", f"/coe/episodes/{episode_id}/schedule", payload, headers
        )

    # --- Care plan items ---
    def create_care_item(self, episode_id, payload, headers):
        return self._request(
            "POST", f"/coe/episodes/{episode_id}/care-items", payload, headers
        )

    def list_care_items(self, episode_id, headers, params=None):
        return self._request(
            "GET", f"/coe/episodes/{episode_id}/care-items",
            headers=headers, params=params,
        )

    def get_care_item(self, item_id, headers):
        return self._request("GET", f"/coe/care-items/{item_id}", headers=headers)

    def complete_care_item(self, item_id, headers):
        return self._request(
            "POST", f"/coe/care-items/{item_id}/complete", {}, headers
        )

    def waive_care_item(self, item_id, headers):
        return self._request("POST", f"/coe/care-items/{item_id}/waive", {}, headers)

    # --- Surgery / discharge / day counter ---
    def complete_surgery(self, episode_id, payload, headers):
        return self._request(
            "POST", f"/coe/episodes/{episode_id}/surgery-complete", payload, headers
        )

    def discharge_episode(self, episode_id, payload, headers):
        return self._request(
            "POST", f"/coe/episodes/{episode_id}/discharge", payload, headers
        )

    def advance_day(self, episode_id, headers):
        return self._request(
            "POST", f"/coe/episodes/{episode_id}/advance-day", {}, headers
        )

    # --- Readmissions ---
    def record_readmission(self, episode_id, payload, headers):
        return self._request(
            "POST", f"/coe/episodes/{episode_id}/readmissions", payload, headers
        )

    def list_readmissions(self, episode_id, headers, params=None):
        return self._request(
            "GET", f"/coe/episodes/{episode_id}/readmissions",
            headers=headers, params=params,
        )

    def get_readmission(self, readmission_id, headers):
        return self._request(
            "GET", f"/coe/readmissions/{readmission_id}", headers=headers
        )

    # --- Claims ---
    def submit_claim(self, episode_id, payload, headers):
        return self._request(
            "POST", f"/coe/episodes/{episode_id}/claims", payload, headers
        )

    def list_episode_claims(self, episode_id, headers, params=None):
        return self._request(
            "GET", f"/coe/episodes/{episode_id}/claims",
            headers=headers, params=params,
        )

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/coe/claims/{claim_id}", headers=headers)

    def adjudicate_claim(self, claim_id, headers):
        return self._request(
            "POST", f"/coe/claims/{claim_id}/adjudicate", {}, headers
        )

    def pay_claim(self, claim_id, headers):
        return self._request("POST", f"/coe/claims/{claim_id}/pay", {}, headers)

    # --- Benefits ---
    def administer_benefit(self, episode_id, payload, headers):
        return self._request(
            "POST", f"/coe/episodes/{episode_id}/benefits", payload, headers
        )

    def list_episode_benefits(self, episode_id, headers, params=None):
        return self._request(
            "GET", f"/coe/episodes/{episode_id}/benefits",
            headers=headers, params=params,
        )

    def get_benefit(self, benefit_id, headers):
        return self._request("GET", f"/coe/benefits/{benefit_id}", headers=headers)

    # --- Reports ---
    def get_report(self, report_id, headers):
        return self._request("GET", f"/coe/reports/{report_id}", headers=headers)


api_client = ApiClient()
