"""API client: one method per endpoint defined in the PRD (all mounted under /veteran-services)."""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/veteran-services"


class ApiClient(GenericApiClient):
    # ---- logical clock ----------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc", payload, headers)

    # ---- program tracks ---------------------------------------------------
    def create_program_track(self, payload, headers):
        return self._request("POST", f"{PREFIX}/program-tracks", payload, headers)

    def list_program_tracks(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/program-tracks", headers=headers, params=params)

    # ---- members ----------------------------------------------------------
    def create_member(self, payload, headers):
        return self._request("POST", f"{PREFIX}/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"{PREFIX}/members/{member_id}", headers=headers)

    # ---- eligibility cases --------------------------------------------------
    def create_eligibility_case(self, payload, headers):
        return self._request("POST", f"{PREFIX}/eligibility-cases", payload, headers)

    def list_eligibility_cases(self, member_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/members/{member_id}/eligibility-cases", headers=headers, params=params)

    def transition_eligibility_case(self, case_id, payload, headers):
        return self._request("POST", f"{PREFIX}/eligibility-cases/{case_id}/transition", payload, headers)

    # ---- external service records -------------------------------------------
    def create_external_service_record(self, payload, headers):
        return self._request("POST", f"{PREFIX}/external-service-records", payload, headers)

    def list_external_service_records(self, member_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/members/{member_id}/external-service-records", headers=headers, params=params)

    # ---- enrollments ---------------------------------------------------------
    def create_enrollment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/enrollments", payload, headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/enrollments", headers=headers, params=params)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"{PREFIX}/enrollments/{enrollment_id}", headers=headers)

    def create_assessment(self, enrollment_id, payload, headers):
        return self._request("POST", f"{PREFIX}/enrollments/{enrollment_id}/assessments", payload, headers)

    def list_assessments(self, enrollment_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/enrollments/{enrollment_id}/assessments", headers=headers, params=params)

    def transition_enrollment(self, enrollment_id, payload, headers):
        return self._request("POST", f"{PREFIX}/enrollments/{enrollment_id}/transition", payload, headers)

    # ---- benefits claims ------------------------------------------------------
    def create_claim(self, payload, headers):
        return self._request("POST", f"{PREFIX}/claims", payload, headers)

    def list_claims(self, member_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/members/{member_id}/claims", headers=headers, params=params)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"{PREFIX}/claims/{claim_id}", headers=headers)

    def decide_claim(self, claim_id, payload, headers):
        return self._request("POST", f"{PREFIX}/claims/{claim_id}/decide", payload, headers)

    # ---- appeals ---------------------------------------------------------------
    def create_appeal(self, payload, headers):
        return self._request("POST", f"{PREFIX}/appeals", payload, headers)

    def list_appeals(self, claim_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/claims/{claim_id}/appeals", headers=headers, params=params)

    def decide_appeal(self, appeal_id, payload, headers):
        return self._request("POST", f"{PREFIX}/appeals/{appeal_id}/decide", payload, headers)

    # ---- referrals --------------------------------------------------------------
    def create_referral(self, payload, headers):
        return self._request("POST", f"{PREFIX}/referrals", payload, headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/referrals", headers=headers, params=params)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"{PREFIX}/referrals/{referral_id}", headers=headers)

    def transition_referral(self, referral_id, payload, headers):
        return self._request("POST", f"{PREFIX}/referrals/{referral_id}/transition", payload, headers)

    # ---- partner sites ------------------------------------------------------------
    def create_partner_site(self, payload, headers):
        return self._request("POST", f"{PREFIX}/partner-sites", payload, headers)

    def list_partner_sites(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/partner-sites", headers=headers, params=params)

    # ---- employer partners -----------------------------------------------------------
    def create_employer_partner(self, payload, headers):
        return self._request("POST", f"{PREFIX}/employer-partners", payload, headers)

    def list_employer_partners(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/employer-partners", headers=headers, params=params)

    # ---- placements ---------------------------------------------------------------------
    def create_placement(self, payload, headers):
        return self._request("POST", f"{PREFIX}/placements", payload, headers)

    def list_placements(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/placements", headers=headers, params=params)

    def get_placement(self, placement_id, headers):
        return self._request("GET", f"{PREFIX}/placements/{placement_id}", headers=headers)

    def transition_placement(self, placement_id, payload, headers):
        return self._request("POST", f"{PREFIX}/placements/{placement_id}/transition", payload, headers)

    # ---- community events ------------------------------------------------------------------
    def create_community_event(self, payload, headers):
        return self._request("POST", f"{PREFIX}/community-events", payload, headers)

    def list_community_events(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/community-events", headers=headers, params=params)

    # ---- event registrations -----------------------------------------------------------------
    def create_event_registration(self, payload, headers):
        return self._request("POST", f"{PREFIX}/event-registrations", payload, headers)

    def list_event_registrations(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/event-registrations", headers=headers, params=params)

    def get_event_registration(self, registration_id, headers):
        return self._request("GET", f"{PREFIX}/event-registrations/{registration_id}", headers=headers)

    def transition_event_registration(self, registration_id, payload, headers):
        return self._request("POST", f"{PREFIX}/event-registrations/{registration_id}/transition", payload, headers)

    # ---- outcome surveys ------------------------------------------------------------------------
    def list_surveys(self, enrollment_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/enrollments/{enrollment_id}/surveys", headers=headers, params=params)

    def submit_survey(self, survey_id, payload, headers):
        return self._request("POST", f"{PREFIX}/surveys/{survey_id}/submit", payload, headers)

    # ---- donor reports -----------------------------------------------------------------------------
    def create_donor_report(self, payload, headers):
        return self._request("POST", f"{PREFIX}/donor-reports", payload, headers)

    def get_donor_report(self, report_id, headers):
        return self._request("GET", f"{PREFIX}/donor-reports/{report_id}", headers=headers)


api_client = ApiClient()
