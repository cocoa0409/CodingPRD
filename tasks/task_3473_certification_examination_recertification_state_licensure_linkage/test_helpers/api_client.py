"""API client: one method per endpoint defined in PRD §4.

The logical-clock endpoint is mounted OUTSIDE the /registry prefix
(POST /_clock/set_current_utc); every domain endpoint lives under /registry.
Methods return raw requests.Response objects; validation happens in the
framework validators or in fixtures.
"""
from prd_bench_local_runner.testing import GenericApiClient

REGISTRY = "/registry"


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------ clock
    def set_clock(self, payload, headers):
        """POST /_clock/set_current_utc (unprefixed platform endpoint)."""
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------- level definitions
    def create_level_definition(self, payload, headers):
        return self._request("POST", f"{REGISTRY}/level-definitions", payload, headers)

    def list_level_definitions(self, headers, params=None):
        return self._request("GET", f"{REGISTRY}/level-definitions", headers=headers, params=params)

    # --------------------------------------------------- state adoption policies
    def create_state_adoption_policy(self, payload, headers):
        return self._request("POST", f"{REGISTRY}/state-adoption-policies", payload, headers)

    def list_state_adoption_policies(self, headers, params=None):
        return self._request("GET", f"{REGISTRY}/state-adoption-policies", headers=headers, params=params)

    # ---------------------------------------------------------------- candidates
    def register_candidate(self, payload, headers=None):
        """Header-exempt self-registration (Anonymous)."""
        return self._request("POST", f"{REGISTRY}/candidates", payload, headers)

    def get_candidate(self, candidate_id, headers):
        return self._request("GET", f"{REGISTRY}/candidates/{candidate_id}", headers=headers)

    # ---------------------------------------------------------- education programs
    def create_education_program(self, payload, headers):
        return self._request("POST", f"{REGISTRY}/education-programs", payload, headers)

    def list_education_programs(self, headers, params=None):
        return self._request("GET", f"{REGISTRY}/education-programs", headers=headers, params=params)

    def get_education_program(self, program_id, headers):
        return self._request("GET", f"{REGISTRY}/education-programs/{program_id}", headers=headers)

    def record_accreditation_event(self, program_id, payload, headers):
        return self._request(
            "POST", f"{REGISTRY}/education-programs/{program_id}/accreditation-events",
            payload, headers,
        )

    # -------------------------------------------------- program completion records
    def create_program_completion_record(self, payload, headers):
        return self._request("POST", f"{REGISTRY}/program-completion-records", payload, headers)

    def list_program_completion_records(self, headers, params=None):
        return self._request("GET", f"{REGISTRY}/program-completion-records", headers=headers, params=params)

    def get_program_completion_record(self, record_id, headers):
        return self._request("GET", f"{REGISTRY}/program-completion-records/{record_id}", headers=headers)

    def decide_program_completion_record(self, record_id, payload, headers):
        return self._request(
            "POST", f"{REGISTRY}/program-completion-records/{record_id}/decision",
            payload, headers,
        )

    # ------------------------------------------------------------ exam applications
    def create_exam_application(self, payload, headers):
        return self._request("POST", f"{REGISTRY}/exam-applications", payload, headers)

    def list_exam_applications(self, headers, params=None):
        return self._request("GET", f"{REGISTRY}/exam-applications", headers=headers, params=params)

    def get_exam_application(self, application_id, headers):
        return self._request("GET", f"{REGISTRY}/exam-applications/{application_id}", headers=headers)

    def decide_exam_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"{REGISTRY}/exam-applications/{application_id}/decision",
            payload, headers,
        )

    def resubmit_exam_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"{REGISTRY}/exam-applications/{application_id}/resubmit",
            payload, headers,
        )

    # --------------------------------------------------------- authorizations to test
    def list_authorizations_to_test(self, headers, params=None):
        return self._request("GET", f"{REGISTRY}/authorizations-to-test", headers=headers, params=params)

    def get_authorization_to_test(self, att_id, headers):
        return self._request("GET", f"{REGISTRY}/authorizations-to-test/{att_id}", headers=headers)

    # --------------------------------------------------------- cognitive exam attempts
    def schedule_cognitive_exam_attempt(self, payload, headers):
        return self._request("POST", f"{REGISTRY}/cognitive-exam-attempts", payload, headers)

    def list_cognitive_exam_attempts(self, headers, params=None):
        return self._request("GET", f"{REGISTRY}/cognitive-exam-attempts", headers=headers, params=params)

    def get_cognitive_exam_attempt(self, attempt_id, headers):
        return self._request("GET", f"{REGISTRY}/cognitive-exam-attempts/{attempt_id}", headers=headers)

    def deliver_cognitive_exam_responses(self, attempt_id, payload, headers):
        return self._request(
            "POST", f"{REGISTRY}/cognitive-exam-attempts/{attempt_id}/responses",
            payload, headers,
        )

    # ---------------------------------------------------------- remedial education
    def create_remedial_education_record(self, payload, headers):
        return self._request("POST", f"{REGISTRY}/remedial-education-records", payload, headers)

    def list_remedial_education_records(self, headers, params=None):
        return self._request("GET", f"{REGISTRY}/remedial-education-records", headers=headers, params=params)

    def get_remedial_education_record(self, record_id, headers):
        return self._request("GET", f"{REGISTRY}/remedial-education-records/{record_id}", headers=headers)

    # ------------------------------------------------------ psychomotor verifications
    def create_psychomotor_verification(self, payload, headers):
        return self._request("POST", f"{REGISTRY}/psychomotor-verifications", payload, headers)

    def list_psychomotor_verifications(self, headers, params=None):
        return self._request("GET", f"{REGISTRY}/psychomotor-verifications", headers=headers, params=params)

    def get_psychomotor_verification(self, verification_id, headers):
        return self._request("GET", f"{REGISTRY}/psychomotor-verifications/{verification_id}", headers=headers)

    def decide_psychomotor_verification(self, verification_id, payload, headers):
        return self._request(
            "POST", f"{REGISTRY}/psychomotor-verifications/{verification_id}/decision",
            payload, headers,
        )

    # --------------------------------------------------------------- certifications
    def issue_certification(self, payload, headers):
        return self._request("POST", f"{REGISTRY}/certifications/issue", payload, headers)

    def list_certifications(self, headers, params=None):
        return self._request("GET", f"{REGISTRY}/certifications", headers=headers, params=params)

    def get_certification(self, certification_id, headers):
        return self._request("GET", f"{REGISTRY}/certifications/{certification_id}", headers=headers)

    # -------------------------------------------------------- recert applications
    def create_recert_application(self, payload, headers):
        return self._request("POST", f"{REGISTRY}/recert-applications", payload, headers)

    def list_recert_applications(self, headers, params=None):
        return self._request("GET", f"{REGISTRY}/recert-applications", headers=headers, params=params)

    def get_recert_application(self, application_id, headers):
        return self._request("GET", f"{REGISTRY}/recert-applications/{application_id}", headers=headers)

    def add_ce_entry(self, application_id, payload, headers):
        return self._request(
            "POST", f"{REGISTRY}/recert-applications/{application_id}/ce-entries",
            payload, headers,
        )

    def list_ce_entries(self, application_id, headers, params=None):
        return self._request(
            "GET", f"{REGISTRY}/recert-applications/{application_id}/ce-entries",
            headers=headers, params=params,
        )

    def submit_recert_application(self, application_id, headers):
        return self._request(
            "POST", f"{REGISTRY}/recert-applications/{application_id}/submit",
            {}, headers,
        )

    def decide_recert_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"{REGISTRY}/recert-applications/{application_id}/decision",
            payload, headers,
        )

    def record_audit_outcome(self, application_id, payload, headers):
        return self._request(
            "POST", f"{REGISTRY}/recert-applications/{application_id}/audit-outcome",
            payload, headers,
        )

    def reopen_recert_application(self, application_id, headers):
        return self._request(
            "POST", f"{REGISTRY}/recert-applications/{application_id}/reopen",
            {}, headers,
        )

    # --------------------------------------------------------- reentry applications
    def create_reentry_application(self, payload, headers):
        return self._request("POST", f"{REGISTRY}/reentry-applications", payload, headers)

    def list_reentry_applications(self, headers, params=None):
        return self._request("GET", f"{REGISTRY}/reentry-applications", headers=headers, params=params)

    def get_reentry_application(self, application_id, headers):
        return self._request("GET", f"{REGISTRY}/reentry-applications/{application_id}", headers=headers)

    def decide_reentry_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"{REGISTRY}/reentry-applications/{application_id}/decision",
            payload, headers,
        )

    # --------------------------------------------------------- license applications
    def create_license_application(self, payload, headers):
        return self._request("POST", f"{REGISTRY}/license-applications", payload, headers)

    def list_license_applications(self, headers, params=None):
        return self._request("GET", f"{REGISTRY}/license-applications", headers=headers, params=params)

    def get_license_application(self, application_id, headers):
        return self._request("GET", f"{REGISTRY}/license-applications/{application_id}", headers=headers)

    def decide_license_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"{REGISTRY}/license-applications/{application_id}/decision",
            payload, headers,
        )

    def respond_license_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"{REGISTRY}/license-applications/{application_id}/respond",
            payload, headers,
        )

    # ------------------------------------------------------------- state exam records
    def create_state_exam_record(self, payload, headers):
        return self._request("POST", f"{REGISTRY}/state-exam-records", payload, headers)

    def list_state_exam_records(self, headers, params=None):
        return self._request("GET", f"{REGISTRY}/state-exam-records", headers=headers, params=params)

    def get_state_exam_record(self, record_id, headers):
        return self._request("GET", f"{REGISTRY}/state-exam-records/{record_id}", headers=headers)

    # ------------------------------------------------------------- disciplinary cases
    def create_disciplinary_case(self, payload, headers):
        return self._request("POST", f"{REGISTRY}/disciplinary-cases", payload, headers)

    def list_disciplinary_cases(self, headers, params=None):
        return self._request("GET", f"{REGISTRY}/disciplinary-cases", headers=headers, params=params)

    def get_disciplinary_case(self, case_id, headers):
        return self._request("GET", f"{REGISTRY}/disciplinary-cases/{case_id}", headers=headers)

    def issue_case_notice(self, case_id, headers):
        return self._request(
            "POST", f"{REGISTRY}/disciplinary-cases/{case_id}/issue-notice",
            {}, headers,
        )

    def submit_case_response(self, case_id, payload, headers):
        return self._request(
            "POST", f"{REGISTRY}/disciplinary-cases/{case_id}/response",
            payload, headers,
        )

    def schedule_case_hearing(self, case_id, headers):
        return self._request(
            "POST", f"{REGISTRY}/disciplinary-cases/{case_id}/schedule-hearing",
            {}, headers,
        )

    def decide_case(self, case_id, payload, headers):
        return self._request(
            "POST", f"{REGISTRY}/disciplinary-cases/{case_id}/decide",
            payload, headers,
        )

    def appeal_case(self, case_id, payload, headers):
        return self._request(
            "POST", f"{REGISTRY}/disciplinary-cases/{case_id}/appeal",
            payload, headers,
        )

    def decide_appeal(self, case_id, payload, headers):
        return self._request(
            "POST", f"{REGISTRY}/disciplinary-cases/{case_id}/appeal-decision",
            payload, headers,
        )


api_client = ApiClient()
