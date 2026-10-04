"""API client — one method per endpoint of the treatment-network surface."""

from prd_bench_local_runner.testing import GenericApiClient

BASE = "/treatment-network"


class ApiClient(GenericApiClient):
    """Endpoint methods for the residential treatment step-down network (PRD §4)."""

    def create_facility(self, payload, headers):
        return self._request("POST", f"{BASE}/facilities", payload, headers)

    def list_facilities(self, headers, params=None):
        return self._request("GET", f"{BASE}/facilities", headers=headers, params=params)

    def get_facility(self, facility_id, headers, params=None):
        return self._request("GET", f"{BASE}/facilities/{facility_id}", headers=headers, params=params)

    def run_facility_ops(self, facility_id, payload, headers):
        return self._request("POST", f"{BASE}/facilities/{facility_id}/facility-ops/run", payload, headers)

    def set_clock(self, payload, headers):
        return self._request("POST", f"{BASE}/_clock/set_current_utc", payload, headers)

    def create_clinician(self, payload, headers):
        return self._request("POST", f"{BASE}/clinicians", payload, headers)

    def get_clinician(self, clinician_id, headers, params=None):
        return self._request("GET", f"{BASE}/clinicians/{clinician_id}", headers=headers, params=params)

    def create_clinician_facility_credential(self, clinician_id, payload, headers):
        return self._request("POST", f"{BASE}/clinicians/{clinician_id}/facility-credentials", payload, headers)

    def list_clinician_facility_credentials(self, clinician_id, headers, params=None):
        return self._request("GET", f"{BASE}/clinicians/{clinician_id}/facility-credentials", headers=headers, params=params)

    def list_clinician_assessments(self, clinician_id, headers, params=None):
        return self._request("GET", f"{BASE}/clinicians/{clinician_id}/assessments", headers=headers, params=params)

    def list_clinician_treatment_plans(self, clinician_id, headers, params=None):
        return self._request("GET", f"{BASE}/clinicians/{clinician_id}/treatment-plans", headers=headers, params=params)

    def list_clinician_sessions(self, clinician_id, headers, params=None):
        return self._request("GET", f"{BASE}/clinicians/{clinician_id}/sessions", headers=headers, params=params)

    def list_clinician_continuing_care_plans(self, clinician_id, headers, params=None):
        return self._request("GET", f"{BASE}/clinicians/{clinician_id}/continuing-care-plans", headers=headers, params=params)

    def create_payer(self, payload, headers):
        return self._request("POST", f"{BASE}/payers", payload, headers)

    def get_payer(self, payer_id, headers, params=None):
        return self._request("GET", f"{BASE}/payers/{payer_id}", headers=headers, params=params)

    def list_payer_authorizations(self, payer_id, headers, params=None):
        return self._request("GET", f"{BASE}/payers/{payer_id}/authorizations", headers=headers, params=params)

    def create_bed(self, facility_id, payload, headers):
        return self._request("POST", f"{BASE}/facilities/{facility_id}/beds", payload, headers)

    def list_beds(self, facility_id, headers, params=None):
        return self._request("GET", f"{BASE}/facilities/{facility_id}/beds", headers=headers, params=params)

    def create_service_offering(self, facility_id, payload, headers):
        return self._request("POST", f"{BASE}/facilities/{facility_id}/service-offerings", payload, headers)

    def list_service_offerings(self, facility_id, headers, params=None):
        return self._request("GET", f"{BASE}/facilities/{facility_id}/service-offerings", headers=headers, params=params)

    def get_service_offering(self, service_id, headers, params=None):
        return self._request("GET", f"{BASE}/service-offerings/{service_id}", headers=headers, params=params)

    def list_service_offering_sessions(self, service_id, headers, params=None):
        return self._request("GET", f"{BASE}/service-offerings/{service_id}/sessions", headers=headers, params=params)

    def get_level_of_care_change(self, change_id, headers, params=None):
        return self._request("GET", f"{BASE}/level-of-care-changes/{change_id}", headers=headers, params=params)

    def list_bed_level_of_care_changes(self, bed_id, headers, params=None):
        return self._request("GET", f"{BASE}/beds/{bed_id}/level-of-care-changes", headers=headers, params=params)

    def list_level_of_care_changes(self, headers, params=None):
        return self._request("GET", f"{BASE}/level-of-care-changes", headers=headers, params=params)

    def create_recovery_housing(self, facility_id, payload, headers):
        return self._request("POST", f"{BASE}/facilities/{facility_id}/recovery-housing", payload, headers)

    def list_recovery_housing(self, facility_id, headers, params=None):
        return self._request("GET", f"{BASE}/facilities/{facility_id}/recovery-housing", headers=headers, params=params)

    def get_recovery_housing(self, housing_id, headers, params=None):
        return self._request("GET", f"{BASE}/recovery-housing/{housing_id}", headers=headers, params=params)

    def list_recovery_housing_continuing_care_plans(self, housing_id, headers, params=None):
        return self._request("GET", f"{BASE}/recovery-housing/{housing_id}/continuing-care-plans", headers=headers, params=params)

    def list_facility_clinician_credentials(self, facility_id, headers, params=None):
        return self._request("GET", f"{BASE}/facilities/{facility_id}/clinician-credentials", headers=headers, params=params)

    def create_accreditation(self, facility_id, payload, headers):
        return self._request("POST", f"{BASE}/facilities/{facility_id}/accreditations", payload, headers)

    def list_accreditations(self, facility_id, headers, params=None):
        return self._request("GET", f"{BASE}/facilities/{facility_id}/accreditations", headers=headers, params=params)

    def get_accreditation(self, accreditation_id, headers, params=None):
        return self._request("GET", f"{BASE}/accreditations/{accreditation_id}", headers=headers, params=params)

    def renew_accreditation(self, facility_id, accreditation_id, payload, headers):
        return self._request("POST", f"{BASE}/facilities/{facility_id}/accreditations/{accreditation_id}/renew", payload, headers)

    def suspend_accreditation(self, facility_id, accreditation_id, payload, headers):
        return self._request("POST", f"{BASE}/facilities/{facility_id}/accreditations/{accreditation_id}/suspend", payload, headers)

    def revoke_accreditation(self, facility_id, accreditation_id, payload, headers):
        return self._request("POST", f"{BASE}/facilities/{facility_id}/accreditations/{accreditation_id}/revoke", payload, headers)

    def reinstate_accreditation(self, facility_id, accreditation_id, payload, headers):
        return self._request("POST", f"{BASE}/facilities/{facility_id}/accreditations/{accreditation_id}/reinstate", payload, headers)

    def create_episode(self, facility_id, payload, headers):
        return self._request("POST", f"{BASE}/facilities/{facility_id}/treatment-episodes", payload, headers)

    def list_episodes(self, facility_id, headers, params=None):
        return self._request("GET", f"{BASE}/facilities/{facility_id}/treatment-episodes", None, headers, params)

    def get_episode_in_facility(self, facility_id, episode_id, headers, params=None):
        return self._request("GET", f"{BASE}/facilities/{facility_id}/treatment-episodes/{episode_id}", headers=headers, params=params)

    def get_episode(self, episode_id, headers, params=None):
        return self._request("GET", f"{BASE}/treatment-episodes/{episode_id}", headers=headers, params=params)

    def get_utilization_summary(self, episode_id, headers, params=None):
        return self._request("GET", f"{BASE}/treatment-episodes/{episode_id}/utilization-summary", headers=headers, params=params)

    def admit_episode(self, facility_id, episode_id, payload, headers):
        return self._request("POST", f"{BASE}/facilities/{facility_id}/treatment-episodes/{episode_id}/admit", payload, headers)

    def complete_treatment(self, facility_id, episode_id, payload, headers):
        return self._request("POST", f"{BASE}/facilities/{facility_id}/treatment-episodes/{episode_id}/complete-treatment", payload, headers)

    def discharge_episode(self, facility_id, episode_id, payload, headers):
        return self._request("POST", f"{BASE}/facilities/{facility_id}/treatment-episodes/{episode_id}/discharge", payload, headers)

    def create_assessment(self, facility_id, episode_id, payload, headers):
        return self._request("POST", f"{BASE}/facilities/{facility_id}/treatment-episodes/{episode_id}/assessments", payload, headers)

    def list_episode_assessments(self, facility_id, episode_id, headers, params=None):
        return self._request("GET", f"{BASE}/facilities/{facility_id}/treatment-episodes/{episode_id}/assessments", headers=headers, params=params)

    def list_episode_assessments_network(self, episode_id, headers, params=None):
        return self._request("GET", f"{BASE}/treatment-episodes/{episode_id}/assessments", headers=headers, params=params)

    def complete_assessment(self, facility_id, assessment_id, payload, headers):
        return self._request("POST", f"{BASE}/facilities/{facility_id}/assessments/{assessment_id}/complete", payload, headers)

    def cancel_assessment(self, facility_id, assessment_id, payload, headers):
        return self._request("POST", f"{BASE}/facilities/{facility_id}/assessments/{assessment_id}/cancel", payload, headers)

    def create_authorization(self, facility_id, episode_id, payload, headers):
        return self._request("POST", f"{BASE}/facilities/{facility_id}/treatment-episodes/{episode_id}/authorizations", payload, headers)

    def list_episode_authorizations(self, facility_id, episode_id, headers, params=None):
        return self._request("GET", f"{BASE}/facilities/{facility_id}/treatment-episodes/{episode_id}/authorizations", headers=headers, params=params)

    def list_episode_authorizations_network(self, episode_id, headers, params=None):
        return self._request("GET", f"{BASE}/treatment-episodes/{episode_id}/authorizations", headers=headers, params=params)

    def get_authorization(self, authorization_id, headers, params=None):
        return self._request("GET", f"{BASE}/authorizations/{authorization_id}", headers=headers, params=params)

    def list_authorization_level_of_care_changes(self, authorization_id, headers, params=None):
        return self._request("GET", f"{BASE}/authorizations/{authorization_id}/level-of-care-changes", headers=headers, params=params)

    def approve_authorization(self, facility_id, authorization_id, payload, headers):
        return self._request("POST", f"{BASE}/facilities/{facility_id}/authorizations/{authorization_id}/approve", payload, headers)

    def deny_authorization(self, facility_id, authorization_id, payload, headers):
        return self._request("POST", f"{BASE}/facilities/{facility_id}/authorizations/{authorization_id}/deny", payload, headers)

    def submit_concurrent_review(self, facility_id, authorization_id, payload, headers):
        return self._request("POST", f"{BASE}/facilities/{facility_id}/authorizations/{authorization_id}/submit-concurrent-review", payload, headers)

    def create_clearance(self, facility_id, episode_id, payload, headers):
        return self._request("POST", f"{BASE}/facilities/{facility_id}/treatment-episodes/{episode_id}/medical-clearances", payload, headers)

    def list_episode_clearances(self, facility_id, episode_id, headers, params=None):
        return self._request("GET", f"{BASE}/facilities/{facility_id}/treatment-episodes/{episode_id}/medical-clearances", headers=headers, params=params)

    def list_episode_clearances_network(self, episode_id, headers, params=None):
        return self._request("GET", f"{BASE}/treatment-episodes/{episode_id}/medical-clearances", headers=headers, params=params)

    def clear_clearance(self, facility_id, clearance_id, payload, headers):
        return self._request("POST", f"{BASE}/facilities/{facility_id}/medical-clearances/{clearance_id}/clear", payload, headers)

    def fail_clearance(self, facility_id, clearance_id, payload, headers):
        return self._request("POST", f"{BASE}/facilities/{facility_id}/medical-clearances/{clearance_id}/fail", payload, headers)

    def create_withdrawal_management(self, facility_id, episode_id, payload, headers):
        return self._request("POST", f"{BASE}/facilities/{facility_id}/treatment-episodes/{episode_id}/withdrawal-management", payload, headers)

    def list_episode_withdrawal_management(self, facility_id, episode_id, headers, params=None):
        return self._request("GET", f"{BASE}/facilities/{facility_id}/treatment-episodes/{episode_id}/withdrawal-management", headers=headers, params=params)

    def list_episode_withdrawal_management_network(self, episode_id, headers, params=None):
        return self._request("GET", f"{BASE}/treatment-episodes/{episode_id}/withdrawal-management", headers=headers, params=params)

    def list_facility_withdrawal_management(self, facility_id, headers, params=None):
        return self._request("GET", f"{BASE}/facilities/{facility_id}/withdrawal-management", headers=headers, params=params)

    def get_withdrawal_management(self, plan_id, headers, params=None):
        return self._request("GET", f"{BASE}/withdrawal-management/{plan_id}", headers=headers, params=params)

    def update_withdrawal_management(self, facility_id, plan_id, payload, headers):
        return self._request("PUT", f"{BASE}/facilities/{facility_id}/withdrawal-management/{plan_id}", payload, headers)

    def create_treatment_plan(self, facility_id, episode_id, payload, headers):
        return self._request("POST", f"{BASE}/facilities/{facility_id}/treatment-episodes/{episode_id}/treatment-plans", payload, headers)

    def list_episode_treatment_plans(self, facility_id, episode_id, headers, params=None):
        return self._request("GET", f"{BASE}/facilities/{facility_id}/treatment-episodes/{episode_id}/treatment-plans", headers=headers, params=params)

    def list_episode_treatment_plans_network(self, episode_id, headers, params=None):
        return self._request("GET", f"{BASE}/treatment-episodes/{episode_id}/treatment-plans", headers=headers, params=params)

    def list_facility_treatment_plans(self, facility_id, headers, params=None):
        return self._request("GET", f"{BASE}/facilities/{facility_id}/treatment-plans", headers=headers, params=params)

    def get_treatment_plan(self, plan_id, headers, params=None):
        return self._request("GET", f"{BASE}/treatment-plans/{plan_id}", headers=headers, params=params)

    def update_treatment_plan(self, plan_id, payload, headers):
        return self._request("PUT", f"{BASE}/treatment-plans/{plan_id}", payload, headers)

    def submit_plan_for_cosign(self, facility_id, plan_id, payload, headers):
        return self._request("POST", f"{BASE}/facilities/{facility_id}/treatment-plans/{plan_id}/submit-for-cosign", payload, headers)

    def create_session(self, facility_id, episode_id, payload, headers):
        return self._request("POST", f"{BASE}/facilities/{facility_id}/treatment-episodes/{episode_id}/sessions", payload, headers)

    def list_episode_sessions(self, facility_id, episode_id, headers, params=None):
        return self._request("GET", f"{BASE}/facilities/{facility_id}/treatment-episodes/{episode_id}/sessions", headers=headers, params=params)

    def list_episode_sessions_network(self, episode_id, headers, params=None):
        return self._request("GET", f"{BASE}/treatment-episodes/{episode_id}/sessions", headers=headers, params=params)

    def get_session(self, session_id, headers, params=None):
        return self._request("GET", f"{BASE}/sessions/{session_id}", headers=headers, params=params)

    def record_attendance(self, facility_id, session_id, payload, headers):
        return self._request("POST", f"{BASE}/facilities/{facility_id}/sessions/{session_id}/record-attendance", payload, headers)

    def cancel_session(self, facility_id, session_id, payload, headers):
        return self._request("POST", f"{BASE}/facilities/{facility_id}/sessions/{session_id}/cancel", payload, headers)

    def create_level_of_care_change(self, facility_id, episode_id, payload, headers):
        return self._request("POST", f"{BASE}/facilities/{facility_id}/treatment-episodes/{episode_id}/level-of-care-changes", payload, headers)

    def list_episode_level_of_care_changes(self, facility_id, episode_id, headers, params=None):
        return self._request("GET", f"{BASE}/facilities/{facility_id}/treatment-episodes/{episode_id}/level-of-care-changes", headers=headers, params=params)

    def list_episode_level_of_care_changes_network(self, episode_id, headers, params=None):
        return self._request("GET", f"{BASE}/treatment-episodes/{episode_id}/level-of-care-changes", headers=headers, params=params)

    def complete_level_of_care_change(self, facility_id, change_id, payload, headers):
        return self._request("POST", f"{BASE}/facilities/{facility_id}/level-of-care-changes/{change_id}/complete", payload, headers)

    def cancel_level_of_care_change(self, facility_id, change_id, payload, headers):
        return self._request("POST", f"{BASE}/facilities/{facility_id}/level-of-care-changes/{change_id}/cancel", payload, headers)

    def step_up_level_of_care_change(self, facility_id, change_id, payload, headers):
        return self._request("POST", f"{BASE}/facilities/{facility_id}/level-of-care-changes/{change_id}/step-up", payload, headers)

    def create_continuing_care_plan(self, facility_id, episode_id, payload, headers):
        return self._request("POST", f"{BASE}/facilities/{facility_id}/treatment-episodes/{episode_id}/continuing-care-plans", payload, headers)

    def list_facility_continuing_care_plans(self, facility_id, headers, params=None):
        return self._request("GET", f"{BASE}/facilities/{facility_id}/continuing-care-plans", headers=headers, params=params)

    def list_episode_continuing_care_plans(self, facility_id, episode_id, headers, params=None):
        return self._request("GET", f"{BASE}/facilities/{facility_id}/treatment-episodes/{episode_id}/continuing-care-plans", headers=headers, params=params)

    def list_episode_continuing_care_plans_network(self, episode_id, headers, params=None):
        return self._request("GET", f"{BASE}/treatment-episodes/{episode_id}/continuing-care-plans", headers=headers, params=params)

    def activate_continuing_care_plan(self, facility_id, care_plan_id, payload, headers):
        return self._request("POST", f"{BASE}/facilities/{facility_id}/continuing-care-plans/{care_plan_id}/activate", payload, headers)

    def create_alumni_contact(self, facility_id, episode_id, payload, headers):
        return self._request("POST", f"{BASE}/facilities/{facility_id}/treatment-episodes/{episode_id}/alumni-contacts", payload, headers)

    def list_episode_alumni_contacts(self, facility_id, episode_id, headers, params=None):
        return self._request("GET", f"{BASE}/facilities/{facility_id}/treatment-episodes/{episode_id}/alumni-contacts", headers=headers, params=params)

    def list_episode_alumni_contacts_network(self, episode_id, headers, params=None):
        return self._request("GET", f"{BASE}/treatment-episodes/{episode_id}/alumni-contacts", headers=headers, params=params)

    def record_alumni_outcome(self, facility_id, contact_id, payload, headers):
        return self._request("POST", f"{BASE}/facilities/{facility_id}/alumni-contacts/{contact_id}/record", payload, headers)


api_client = ApiClient()
