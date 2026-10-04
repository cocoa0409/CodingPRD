"""API client: one transport method per endpoint in the PRD endpoint table.

Every method returns the raw ``requests.Response`` so tests assert status
codes and envelopes themselves. All paths are mounted under ``/society``
(PRD section 4). The base URL comes from the runner-provided
``API_BASE_URL`` environment variable via ``GenericApiClient``; nothing
here hardcodes a port.

Conventions:
- create methods: ``(payload, headers=None)``
- reads:          ``(entity_id, headers=None)`` / ``list_*`` take params
- actions:        ``(entity_id, payload=None, headers=None)`` — bodiless
  actions send an empty JSON object, matching the documented call shape.
"""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (PRD section 2.5)
    # ------------------------------------------------------------------
    def set_clock(self, payload, headers=None):
        return self._request("POST", "/society/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # Standards catalogs (PRD sections 2.6, 3.1)
    # ------------------------------------------------------------------
    def create_standards_catalog(self, payload, headers=None):
        return self._request("POST", "/society/standards-catalogs", payload, headers)

    def get_standards_catalog(self, catalog_id, headers=None):
        return self._request("GET", f"/society/standards-catalogs/{catalog_id}", headers=headers)

    def activate_standards_catalog(self, catalog_id, payload=None, headers=None):
        return self._request(
            "POST", f"/society/standards-catalogs/{catalog_id}/activate",
            payload if payload is not None else {}, headers,
        )

    # ------------------------------------------------------------------
    # Schools, brand, dues, standing (PRD section 3.2, 3.7)
    # ------------------------------------------------------------------
    def create_school(self, payload, headers=None):
        return self._request("POST", "/society/schools", payload, headers)

    def get_school(self, school_id, headers=None):
        return self._request("GET", f"/society/schools/{school_id}", headers=headers)

    def list_schools(self, headers=None, params=None):
        return self._request("GET", "/society/schools", headers=headers, params=params)

    def update_school_brand(self, school_id, payload, headers=None):
        return self._request("POST", f"/society/schools/{school_id}/brand", payload, headers)

    def record_dues_payment(self, school_id, payload, headers=None):
        return self._request("POST", f"/society/schools/{school_id}/dues-payments", payload, headers)

    def set_school_standing(self, school_id, payload, headers=None):
        return self._request("POST", f"/society/schools/{school_id}/standing", payload, headers)

    # ------------------------------------------------------------------
    # Public directory (PRD section 3.8) — anonymous, no identity headers
    # ------------------------------------------------------------------
    def list_directory(self, headers=None, params=None):
        return self._request("GET", "/society/directory", headers=headers, params=params)

    def get_directory_school(self, school_id, headers=None):
        return self._request("GET", f"/society/directory/{school_id}", headers=headers)

    # ------------------------------------------------------------------
    # Classrooms and audits (PRD section 3.3)
    # ------------------------------------------------------------------
    def create_classroom(self, payload, headers=None):
        return self._request("POST", "/society/classrooms", payload, headers)

    def get_classroom(self, classroom_id, headers=None):
        return self._request("GET", f"/society/classrooms/{classroom_id}", headers=headers)

    def list_classrooms(self, headers=None, params=None):
        return self._request("GET", "/society/classrooms", headers=headers, params=params)

    def transfer_students(self, classroom_id, payload, headers=None):
        return self._request(
            "POST", f"/society/classrooms/{classroom_id}/transfer-students", payload, headers
        )

    def create_classroom_audit(self, payload, headers=None):
        return self._request("POST", "/society/classroom-audits", payload, headers)

    def get_classroom_audit(self, audit_id, headers=None):
        return self._request("GET", f"/society/classroom-audits/{audit_id}", headers=headers)

    def list_classroom_audits(self, headers=None, params=None):
        return self._request("GET", "/society/classroom-audits", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Teacher education programs and adult learners (PRD section 3.4)
    # ------------------------------------------------------------------
    def create_teacher_education_program(self, payload, headers=None):
        return self._request("POST", "/society/teacher-education-programs", payload, headers)

    def get_teacher_education_program(self, program_id, headers=None):
        return self._request(
            "GET", f"/society/teacher-education-programs/{program_id}", headers=headers
        )

    def set_program_status(self, program_id, payload, headers=None):
        return self._request(
            "POST", f"/society/teacher-education-programs/{program_id}/status", payload, headers
        )

    def create_adult_learner(self, payload, headers=None):
        return self._request("POST", "/society/adult-learners", payload, headers)

    def get_adult_learner(self, learner_id, headers=None):
        return self._request("GET", f"/society/adult-learners/{learner_id}", headers=headers)

    def list_adult_learners(self, headers=None, params=None):
        return self._request("GET", "/society/adult-learners", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Practicum placements (PRD section 3.4)
    # ------------------------------------------------------------------
    def create_practicum_placement(self, payload, headers=None):
        return self._request("POST", "/society/practicum-placements", payload, headers)

    def get_practicum_placement(self, placement_id, headers=None):
        return self._request("GET", f"/society/practicum-placements/{placement_id}", headers=headers)

    def list_practicum_placements(self, headers=None, params=None):
        return self._request("GET", "/society/practicum-placements", headers=headers, params=params)

    def log_placement_hours(self, placement_id, payload, headers=None):
        return self._request(
            "POST", f"/society/practicum-placements/{placement_id}/log-hours", payload, headers
        )

    def verify_practicum_placement(self, placement_id, payload=None, headers=None):
        return self._request(
            "POST", f"/society/practicum-placements/{placement_id}/verify",
            payload if payload is not None else {}, headers,
        )

    def cancel_practicum_placement(self, placement_id, payload=None, headers=None):
        return self._request(
            "POST", f"/society/practicum-placements/{placement_id}/cancel",
            payload if payload is not None else {}, headers,
        )

    # ------------------------------------------------------------------
    # Credentials, renewal, revocation (PRD section 3.5)
    # ------------------------------------------------------------------
    def create_credential(self, payload, headers=None):
        return self._request("POST", "/society/credentials", payload, headers)

    def get_credential(self, credential_id, headers=None):
        return self._request("GET", f"/society/credentials/{credential_id}", headers=headers)

    def list_credentials(self, headers=None, params=None):
        return self._request("GET", "/society/credentials", headers=headers, params=params)

    def renew_credential(self, credential_id, payload, headers=None):
        return self._request(
            "POST", f"/society/credentials/{credential_id}/renew", payload, headers
        )

    def revoke_credential(self, credential_id, payload=None, headers=None):
        return self._request(
            "POST", f"/society/credentials/{credential_id}/revoke",
            payload if payload is not None else {}, headers,
        )

    # ------------------------------------------------------------------
    # School applications (PRD section 3.7)
    # ------------------------------------------------------------------
    def create_school_application(self, payload, headers=None):
        return self._request("POST", "/society/school-applications", payload, headers)

    def get_school_application(self, application_id, headers=None):
        return self._request("GET", f"/society/school-applications/{application_id}", headers=headers)

    def list_school_applications(self, headers=None, params=None):
        return self._request("GET", "/society/school-applications", headers=headers, params=params)

    def submit_school_application(self, application_id, payload=None, headers=None):
        return self._request(
            "POST", f"/society/school-applications/{application_id}/submit",
            payload if payload is not None else {}, headers,
        )

    def review_school_application(self, application_id, payload, headers=None):
        return self._request(
            "POST", f"/society/school-applications/{application_id}/review", payload, headers
        )

    # ------------------------------------------------------------------
    # Self-studies (PRD section 3.6)
    # ------------------------------------------------------------------
    def create_self_study(self, payload, headers=None):
        return self._request("POST", "/society/self-studies", payload, headers)

    def get_self_study(self, self_study_id, headers=None):
        return self._request("GET", f"/society/self-studies/{self_study_id}", headers=headers)

    def list_self_studies(self, headers=None, params=None):
        return self._request("GET", "/society/self-studies", headers=headers, params=params)

    def submit_self_study(self, self_study_id, payload=None, headers=None):
        return self._request(
            "POST", f"/society/self-studies/{self_study_id}/submit",
            payload if payload is not None else {}, headers,
        )

    def review_self_study(self, self_study_id, payload, headers=None):
        return self._request(
            "POST", f"/society/self-studies/{self_study_id}/review", payload, headers
        )

    # ------------------------------------------------------------------
    # Verification visits (PRD section 3.6)
    # ------------------------------------------------------------------
    def create_verification_visit(self, payload, headers=None):
        return self._request("POST", "/society/verification-visits", payload, headers)

    def get_verification_visit(self, visit_id, headers=None):
        return self._request("GET", f"/society/verification-visits/{visit_id}", headers=headers)

    def list_verification_visits(self, headers=None, params=None):
        return self._request("GET", "/society/verification-visits", headers=headers, params=params)

    def cancel_verification_visit(self, visit_id, payload=None, headers=None):
        return self._request(
            "POST", f"/society/verification-visits/{visit_id}/cancel",
            payload if payload is not None else {}, headers,
        )

    def file_visit_report(self, visit_id, payload, headers=None):
        return self._request(
            "POST", f"/society/verification-visits/{visit_id}/reports", payload, headers
        )

    # ------------------------------------------------------------------
    # Improvement plans (PRD section 3.6)
    # ------------------------------------------------------------------
    def get_improvement_plan(self, plan_id, headers=None):
        return self._request("GET", f"/society/improvement-plans/{plan_id}", headers=headers)

    def list_improvement_plans(self, headers=None, params=None):
        return self._request("GET", "/society/improvement-plans", headers=headers, params=params)

    def respond_to_improvement_plan(self, plan_id, payload, headers=None):
        return self._request(
            "POST", f"/society/improvement-plans/{plan_id}/respond", payload, headers
        )

    def review_improvement_plan(self, plan_id, payload, headers=None):
        return self._request(
            "POST", f"/society/improvement-plans/{plan_id}/review", payload, headers
        )

    # ------------------------------------------------------------------
    # PD events and the CE ledger (PRD section 3.5)
    # ------------------------------------------------------------------
    def create_pd_event(self, payload, headers=None):
        return self._request("POST", "/society/pd-events", payload, headers)

    def get_pd_event(self, event_id, headers=None):
        return self._request("GET", f"/society/pd-events/{event_id}", headers=headers)

    def record_event_attendance(self, event_id, payload, headers=None):
        return self._request(
            "POST", f"/society/pd-events/{event_id}/attendance", payload, headers
        )

    def get_ce_entry(self, entry_id, headers=None):
        return self._request("GET", f"/society/ce-entries/{entry_id}", headers=headers)

    def list_ce_entries(self, headers=None, params=None):
        return self._request("GET", "/society/ce-entries", headers=headers, params=params)

    def void_ce_entry(self, entry_id, payload=None, headers=None):
        return self._request(
            "POST", f"/society/ce-entries/{entry_id}/void",
            payload if payload is not None else {}, headers,
        )


api_client = ApiClient()
