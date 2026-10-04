"""API client: one method per endpoint defined in the PRD.

All methods return the raw requests.Response so tests can assert status
codes; pass payloads through the factories and headers through test_users.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock (test-driving) --------------------------------------
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- MatchCycle ---------------------------------------------------------
    def create_cycle(self, payload, headers):
        return self._request("POST", "/cycles", payload, headers)

    def get_cycle(self, cycle_id, headers):
        return self._request("GET", f"/cycles/{cycle_id}", headers=headers)

    def advance_cycle(self, cycle_id, headers):
        return self._request("POST", f"/cycles/{cycle_id}/advance", headers=headers)

    def run_match(self, cycle_id, headers):
        return self._request("POST", f"/cycles/{cycle_id}/run-match", headers=headers)

    def get_outcome_summary(self, cycle_id, headers):
        return self._request("GET", f"/cycles/{cycle_id}/outcome-summary", headers=headers)

    # --- PartnerCollege -----------------------------------------------------
    def create_college(self, payload, headers):
        return self._request("POST", "/colleges", payload, headers)

    def list_colleges(self, headers, params=None):
        return self._request("GET", "/colleges", headers=headers, params=params)

    def get_college(self, college_id, headers):
        return self._request("GET", f"/colleges/{college_id}", headers=headers)

    def suspend_college(self, college_id, headers):
        return self._request("POST", f"/colleges/{college_id}/suspend", headers=headers)

    def reinstate_college(self, college_id, headers):
        return self._request("POST", f"/colleges/{college_id}/reinstate", headers=headers)

    def list_college_ranking_entries(self, college_id, headers, params=None):
        return self._request("GET", f"/colleges/{college_id}/ranking-entries",
                             headers=headers, params=params)

    def get_regular_pool(self, college_id, headers, params=None):
        # params must include cycle_id (required query parameter)
        return self._request("GET", f"/colleges/{college_id}/regular-pool",
                             headers=headers, params=params)

    # --- Counselor ----------------------------------------------------------
    def create_counselor(self, payload, headers):
        return self._request("POST", "/counselors", payload, headers)

    def get_counselor(self, counselor_id, headers):
        return self._request("GET", f"/counselors/{counselor_id}", headers=headers)

    # --- CommunityPartner ---------------------------------------------------
    def create_community_partner(self, payload, headers):
        return self._request("POST", "/community-partners", payload, headers)

    def get_community_partner(self, partner_id, headers):
        return self._request("GET", f"/community-partners/{partner_id}", headers=headers)

    # --- Student ------------------------------------------------------------
    def create_student(self, payload, headers):
        return self._request("POST", "/students", payload, headers)

    def get_student(self, student_id, headers):
        return self._request("GET", f"/students/{student_id}", headers=headers)

    def list_student_prep_programs(self, student_id, headers, params=None):
        return self._request("GET", f"/students/{student_id}/prep-programs",
                             headers=headers, params=params)

    # --- Referral -----------------------------------------------------------
    def create_referral(self, payload, headers):
        return self._request("POST", "/referrals", payload, headers)

    def revoke_referral(self, referral_id, headers):
        return self._request("POST", f"/referrals/{referral_id}/revoke", headers=headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", "/referrals", headers=headers, params=params)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"/referrals/{referral_id}", headers=headers)

    # --- PrepProgram --------------------------------------------------------
    def create_prep_program(self, payload, headers):
        return self._request("POST", "/prep-programs", payload, headers)

    def close_prep_program(self, prep_program_id, payload, headers):
        return self._request("POST", f"/prep-programs/{prep_program_id}/close",
                             payload, headers)

    def get_prep_program(self, prep_program_id, headers):
        return self._request("GET", f"/prep-programs/{prep_program_id}", headers=headers)

    # --- Application --------------------------------------------------------
    def create_application(self, payload, headers):
        return self._request("POST", "/applications", payload, headers)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/applications/{application_id}", headers=headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/applications", headers=headers, params=params)

    def submit_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/submit",
                             headers=headers)

    def withdraw_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/withdraw",
                             headers=headers)

    def review_application(self, application_id, payload, headers):
        return self._request("POST", f"/applications/{application_id}/review",
                             payload, headers)

    def submit_rankings(self, application_id, payload, headers):
        return self._request("POST", f"/applications/{application_id}/rankings",
                             payload, headers)

    def get_application_rankings(self, application_id, headers, params=None):
        return self._request("GET", f"/applications/{application_id}/rankings",
                             headers=headers, params=params)

    def list_application_income_verifications(self, application_id, headers, params=None):
        return self._request("GET", f"/applications/{application_id}/income-verifications",
                             headers=headers, params=params)

    def regular_decision(self, application_id, payload, headers):
        return self._request("POST", f"/applications/{application_id}/regular-decision",
                             payload, headers)

    def enroll_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/enroll",
                             headers=headers)

    # --- Match --------------------------------------------------------------
    def get_match(self, match_id, headers):
        return self._request("GET", f"/matches/{match_id}", headers=headers)

    def list_matches(self, headers, params=None):
        return self._request("GET", "/matches", headers=headers, params=params)

    def release_match(self, match_id, payload, headers):
        return self._request("POST", f"/matches/{match_id}/release", payload, headers)

    def enroll_match(self, match_id, headers):
        return self._request("POST", f"/matches/{match_id}/enroll", headers=headers)

    # --- AidPackage ---------------------------------------------------------
    def get_aid_package(self, package_id, headers):
        return self._request("GET", f"/aid-packages/{package_id}", headers=headers)

    def list_aid_packages(self, headers, params=None):
        return self._request("GET", "/aid-packages", headers=headers, params=params)

    def revise_aid_package(self, package_id, payload, headers):
        return self._request("POST", f"/aid-packages/{package_id}/revise",
                             payload, headers)

    def finalize_aid_package(self, package_id, headers):
        return self._request("POST", f"/aid-packages/{package_id}/finalize",
                             headers=headers)

    # --- IncomeVerification ---------------------------------------------------
    def create_income_verification(self, payload, headers):
        return self._request("POST", "/income-verifications", payload, headers)

    def decide_income_verification(self, verification_id, payload, headers):
        return self._request("POST", f"/income-verifications/{verification_id}/decide",
                             payload, headers)

    # --- OutcomeRecord --------------------------------------------------------
    def checkpoint_outcome(self, outcome_id, payload, headers):
        return self._request("POST", f"/outcomes/{outcome_id}/checkpoint",
                             payload, headers)

    def get_outcome(self, outcome_id, headers):
        return self._request("GET", f"/outcomes/{outcome_id}", headers=headers)

    def list_outcomes(self, headers, params=None):
        return self._request("GET", "/outcomes", headers=headers, params=params)


api_client = ApiClient()
