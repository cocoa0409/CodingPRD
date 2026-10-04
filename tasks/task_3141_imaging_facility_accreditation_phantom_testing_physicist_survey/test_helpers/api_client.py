"""API client: one method per endpoint exposed by the accreditation API."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Typed wrapper over the `/accreditation` REST surface."""

    # ─── Facility ─────────────────────────────────────────────────────────
    def create_facility(self, payload, headers):
        return self._request("POST", "/accreditation/facilities", payload, headers)

    def list_facilities(self, headers, params=None):
        return self._request("GET", "/accreditation/facilities", payload=params, headers=headers)

    def get_facility(self, facility_id, headers):
        return self._request("GET", f"/accreditation/facilities/{facility_id}", headers=headers)

    def get_facility_summary(self, facility_id, headers):
        return self._request(
            "GET", f"/accreditation/facilities/{facility_id}/summary", headers=headers
        )

    def register_facility(self, facility_id, payload, headers):
        return self._request(
            "POST", f"/accreditation/facilities/{facility_id}/register", payload, headers
        )

    def suspend_facility(self, facility_id, payload, headers):
        return self._request(
            "POST", f"/accreditation/facilities/{facility_id}/suspend", payload, headers
        )

    def reinstate_facility(self, facility_id, payload, headers):
        return self._request(
            "POST", f"/accreditation/facilities/{facility_id}/reinstate", payload, headers
        )

    def purchase_registry_credit(self, facility_id, payload, headers):
        return self._request(
            "POST", f"/accreditation/facilities/{facility_id}/registry-credit", payload, headers
        )

    # ─── ModalityUnit ─────────────────────────────────────────────────────
    def create_modality_unit(self, payload, headers):
        return self._request("POST", "/accreditation/modality-units", payload, headers)

    def list_modality_units(self, headers, params=None):
        return self._request("GET", "/accreditation/modality-units", payload=params, headers=headers)

    def get_modality_unit(self, unit_id, headers):
        return self._request("GET", f"/accreditation/modality-units/{unit_id}", headers=headers)

    def withdraw_modality_unit(self, unit_id, payload, headers):
        return self._request(
            "POST", f"/accreditation/modality-units/{unit_id}/withdraw", payload, headers
        )

    # ─── EquipmentItem ────────────────────────────────────────────────────
    def create_equipment(self, payload, headers):
        return self._request("POST", "/accreditation/equipment", payload, headers)

    def list_equipment(self, headers, params=None):
        return self._request("GET", "/accreditation/equipment", payload=params, headers=headers)

    def get_equipment(self, equipment_id, headers):
        return self._request("GET", f"/accreditation/equipment/{equipment_id}", headers=headers)

    def take_equipment_out_of_service(self, equipment_id, payload, headers):
        return self._request(
            "POST", f"/accreditation/equipment/{equipment_id}/take-out-of-service", payload, headers
        )

    def return_equipment_to_service(self, equipment_id, payload, headers):
        return self._request(
            "POST", f"/accreditation/equipment/{equipment_id}/return-to-service", payload, headers
        )

    def retire_equipment(self, equipment_id, payload, headers):
        return self._request(
            "POST", f"/accreditation/equipment/{equipment_id}/retire", payload, headers
        )

    # ─── ClinicalImageSubmission ──────────────────────────────────────────
    def create_clinical_image_submission(self, payload, headers):
        return self._request("POST", "/accreditation/clinical-image-submissions", payload, headers)

    def list_clinical_image_submissions(self, headers, params=None):
        return self._request(
            "GET", "/accreditation/clinical-image-submissions", payload=params, headers=headers
        )

    def get_clinical_image_submission(self, submission_id, headers):
        return self._request(
            "GET", f"/accreditation/clinical-image-submissions/{submission_id}", headers=headers
        )

    def review_clinical_image_submission(self, submission_id, payload, headers):
        return self._request(
            "POST",
            f"/accreditation/clinical-image-submissions/{submission_id}/review",
            payload,
            headers,
        )

    def resubmit_clinical_image_submission(self, submission_id, payload, headers):
        return self._request(
            "POST",
            f"/accreditation/clinical-image-submissions/{submission_id}/resubmit",
            payload,
            headers,
        )

    # ─── PhantomTest ──────────────────────────────────────────────────────
    def create_phantom_test(self, payload, headers):
        return self._request("POST", "/accreditation/phantom-tests", payload, headers)

    def list_phantom_tests(self, headers, params=None):
        return self._request("GET", "/accreditation/phantom-tests", payload=params, headers=headers)

    def get_phantom_test(self, phantom_test_id, headers):
        return self._request("GET", f"/accreditation/phantom-tests/{phantom_test_id}", headers=headers)

    def score_phantom_test(self, phantom_test_id, payload, headers):
        return self._request(
            "POST", f"/accreditation/phantom-tests/{phantom_test_id}/score", payload, headers
        )

    def void_phantom_test(self, phantom_test_id, payload, headers):
        return self._request(
            "POST", f"/accreditation/phantom-tests/{phantom_test_id}/void", payload, headers
        )

    # ─── PhysicistSurvey ──────────────────────────────────────────────────
    def create_physicist_survey(self, payload, headers):
        return self._request("POST", "/accreditation/physicist-surveys", payload, headers)

    def list_physicist_surveys(self, headers, params=None):
        return self._request("GET", "/accreditation/physicist-surveys", payload=params, headers=headers)

    def get_physicist_survey(self, survey_id, headers):
        return self._request("GET", f"/accreditation/physicist-surveys/{survey_id}", headers=headers)

    def submit_physicist_survey(self, survey_id, payload, headers):
        return self._request(
            "POST", f"/accreditation/physicist-surveys/{survey_id}/submit", payload, headers
        )

    def accept_physicist_survey(self, survey_id, payload, headers):
        return self._request(
            "POST", f"/accreditation/physicist-surveys/{survey_id}/accept", payload, headers
        )

    def reject_physicist_survey(self, survey_id, payload, headers):
        return self._request(
            "POST", f"/accreditation/physicist-surveys/{survey_id}/reject", payload, headers
        )

    def resubmit_physicist_survey(self, survey_id, payload, headers):
        return self._request(
            "POST", f"/accreditation/physicist-surveys/{survey_id}/resubmit", payload, headers
        )

    # ─── PersonnelQualification ───────────────────────────────────────────
    def create_personnel_qualification(self, payload, headers):
        return self._request("POST", "/accreditation/qualifications", payload, headers)

    def list_personnel_qualifications(self, headers, params=None):
        return self._request("GET", "/accreditation/qualifications", payload=params, headers=headers)

    def get_personnel_qualification(self, qualification_id, headers):
        return self._request(
            "GET", f"/accreditation/qualifications/{qualification_id}", headers=headers
        )

    def verify_personnel_qualification(self, qualification_id, payload, headers):
        return self._request(
            "POST", f"/accreditation/qualifications/{qualification_id}/verify", payload, headers
        )

    def revoke_personnel_qualification(self, qualification_id, payload, headers):
        return self._request(
            "POST", f"/accreditation/qualifications/{qualification_id}/revoke", payload, headers
        )

    # ─── CorrectiveActionPlan ─────────────────────────────────────────────
    def list_corrective_action_plans(self, headers, params=None):
        return self._request(
            "GET", "/accreditation/corrective-action-plans", payload=params, headers=headers
        )

    def get_corrective_action_plan(self, plan_id, headers):
        return self._request(
            "GET", f"/accreditation/corrective-action-plans/{plan_id}", headers=headers
        )

    def submit_corrective_action_plan(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/accreditation/corrective-action-plans/{plan_id}/submit", payload, headers
        )

    def accept_corrective_action_plan(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/accreditation/corrective-action-plans/{plan_id}/accept", payload, headers
        )

    def reject_corrective_action_plan(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/accreditation/corrective-action-plans/{plan_id}/reject", payload, headers
        )

    # ─── AccreditationCycle ───────────────────────────────────────────────
    def create_accreditation_cycle(self, payload, headers):
        return self._request("POST", "/accreditation/cycles", payload, headers)

    def list_accreditation_cycles(self, headers, params=None):
        return self._request("GET", "/accreditation/cycles", payload=params, headers=headers)

    def get_accreditation_cycle(self, cycle_id, headers):
        return self._request("GET", f"/accreditation/cycles/{cycle_id}", headers=headers)

    def activate_accreditation_cycle(self, cycle_id, payload, headers):
        return self._request("POST", f"/accreditation/cycles/{cycle_id}/activate", payload, headers)

    def start_cycle_renewal(self, cycle_id, payload, headers):
        return self._request(
            "POST", f"/accreditation/cycles/{cycle_id}/start-renewal", payload, headers
        )

    def renew_accreditation_cycle(self, cycle_id, payload, headers):
        return self._request("POST", f"/accreditation/cycles/{cycle_id}/renew", payload, headers)

    def reject_cycle_renewal(self, cycle_id, payload, headers):
        return self._request(
            "POST", f"/accreditation/cycles/{cycle_id}/reject-renewal", payload, headers
        )

    # ─── DoseRegistryRecord ───────────────────────────────────────────────
    def create_dose_registry_record(self, payload, headers):
        return self._request("POST", "/accreditation/dose-registry-records", payload, headers)

    def list_dose_registry_records(self, headers, params=None):
        return self._request(
            "GET", "/accreditation/dose-registry-records", payload=params, headers=headers
        )

    def get_dose_registry_record(self, record_id, headers):
        return self._request(
            "GET", f"/accreditation/dose-registry-records/{record_id}", headers=headers
        )

    def submit_dose_registry_record(self, record_id, payload, headers):
        return self._request(
            "POST", f"/accreditation/dose-registry-records/{record_id}/submit", payload, headers
        )

    def reject_dose_registry_record(self, record_id, payload, headers):
        return self._request(
            "POST", f"/accreditation/dose-registry-records/{record_id}/reject", payload, headers
        )

    # ─── Logical clock ────────────────────────────────────────────────────
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()