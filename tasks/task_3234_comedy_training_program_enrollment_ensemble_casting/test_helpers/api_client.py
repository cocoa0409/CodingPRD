"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, current_utc, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"current_utc": current_utc}, headers)

    # --- CurriculumLevel ---
    def create_curriculum_level(self, payload, headers):
        return self._request("POST", "/curriculum-levels", payload, headers)

    def list_curriculum_levels(self, headers, params=None):
        return self._request("GET", "/curriculum-levels", headers=headers, params=params)

    def get_curriculum_level(self, level_id, headers):
        return self._request("GET", f"/curriculum-levels/{level_id}", headers=headers)

    # --- Term ---
    def create_term(self, payload, headers):
        return self._request("POST", "/terms", payload, headers)

    def list_terms(self, headers, params=None):
        return self._request("GET", "/terms", headers=headers, params=params)

    def get_term(self, term_id, headers):
        return self._request("GET", f"/terms/{term_id}", headers=headers)

    def open_scheduling(self, term_id, headers):
        return self._request("POST", f"/terms/{term_id}/open-scheduling", headers=headers)

    def open_enrollment(self, term_id, headers):
        return self._request("POST", f"/terms/{term_id}/open-enrollment", headers=headers)

    def start_session(self, term_id, headers):
        return self._request("POST", f"/terms/{term_id}/start-session", headers=headers)

    def close_term(self, term_id, headers):
        return self._request("POST", f"/terms/{term_id}/close", headers=headers)

    # --- Instructor ---
    def create_instructor(self, payload, headers):
        return self._request("POST", "/instructors", payload, headers)

    def list_instructors(self, headers, params=None):
        return self._request("GET", "/instructors", headers=headers, params=params)

    def get_instructor(self, instructor_id, headers):
        return self._request("GET", f"/instructors/{instructor_id}", headers=headers)

    # --- CourseSection ---
    def create_section(self, payload, headers):
        return self._request("POST", "/sections", payload, headers)

    def list_sections(self, headers, params=None):
        return self._request("GET", "/sections", headers=headers, params=params)

    def get_section(self, section_id, headers):
        return self._request("GET", f"/sections/{section_id}", headers=headers)

    def patch_section(self, section_id, payload, headers):
        return self._request("PATCH", f"/sections/{section_id}", payload, headers)

    def cancel_section(self, section_id, headers):
        return self._request("POST", f"/sections/{section_id}/cancel", headers=headers)

    # --- Student ---
    def create_student(self, payload, headers):
        return self._request("POST", "/students", payload, headers)

    def list_students(self, headers, params=None):
        return self._request("GET", "/students", headers=headers, params=params)

    def get_student(self, student_id, headers):
        return self._request("GET", f"/students/{student_id}", headers=headers)

    # --- PlacementEvaluation ---
    def create_placement_evaluation(self, payload, headers):
        return self._request("POST", "/placement-evaluations", payload, headers)

    def list_placement_evaluations(self, headers, params=None):
        return self._request("GET", "/placement-evaluations", headers=headers, params=params)

    def get_placement_evaluation(self, evaluation_id, headers):
        return self._request("GET", f"/placement-evaluations/{evaluation_id}", headers=headers)

    def begin_review_placement(self, evaluation_id, headers):
        return self._request("POST", f"/placement-evaluations/{evaluation_id}/begin-review", headers=headers)

    def grant_placement(self, evaluation_id, headers):
        return self._request("POST", f"/placement-evaluations/{evaluation_id}/grant", headers=headers)

    def deny_placement(self, evaluation_id, headers):
        return self._request("POST", f"/placement-evaluations/{evaluation_id}/deny", headers=headers)

    def appeal_placement(self, evaluation_id, headers):
        return self._request("POST", f"/placement-evaluations/{evaluation_id}/appeal", headers=headers)

    # --- Enrollment ---
    def create_enrollment(self, payload, headers):
        return self._request("POST", "/enrollments", payload, headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/enrollments", headers=headers, params=params)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/enrollments/{enrollment_id}", headers=headers)

    def confirm_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/confirm", headers=headers)

    def drop_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/drop", headers=headers)

    def transfer_enrollment(self, enrollment_id, target_section_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/transfer",
                             {"target_section_id": target_section_id}, headers)

    # --- VenueSlot ---
    def create_venue_slot(self, payload, headers):
        return self._request("POST", "/venue-slots", payload, headers)

    def list_venue_slots(self, headers, params=None):
        return self._request("GET", "/venue-slots", headers=headers, params=params)

    def get_venue_slot(self, slot_id, headers):
        return self._request("GET", f"/venue-slots/{slot_id}", headers=headers)

    # --- ShowcaseEvent ---
    def create_showcase(self, payload, headers):
        return self._request("POST", "/showcases", payload, headers)

    def list_showcases(self, headers, params=None):
        return self._request("GET", "/showcases", headers=headers, params=params)

    def get_showcase(self, showcase_id, headers):
        return self._request("GET", f"/showcases/{showcase_id}", headers=headers)

    def schedule_showcase(self, showcase_id, headers):
        return self._request("POST", f"/showcases/{showcase_id}/schedule", headers=headers)

    def stage_showcase(self, showcase_id, grade_by_enrollment, headers):
        return self._request("POST", f"/showcases/{showcase_id}/stage",
                             {"grade_by_enrollment": grade_by_enrollment}, headers)

    def archive_showcase(self, showcase_id, headers):
        return self._request("POST", f"/showcases/{showcase_id}/archive", headers=headers)

    def cancel_showcase(self, showcase_id, headers):
        return self._request("POST", f"/showcases/{showcase_id}/cancel", headers=headers)

    # --- CohortProgram ---
    def create_cohort_program(self, payload, headers):
        return self._request("POST", "/cohort-programs", payload, headers)

    def list_cohort_programs(self, headers, params=None):
        return self._request("GET", "/cohort-programs", headers=headers, params=params)

    def get_cohort_program(self, cohort_id, headers):
        return self._request("GET", f"/cohort-programs/{cohort_id}", headers=headers)

    def begin_cohort_auditions(self, cohort_id, headers):
        return self._request("POST", f"/cohort-programs/{cohort_id}/begin-auditions", headers=headers)

    def admit_to_cohort(self, cohort_id, audition_id, headers):
        return self._request("POST", f"/cohort-programs/{cohort_id}/admit",
                             {"audition_id": audition_id}, headers)

    def finalize_cohort(self, cohort_id, headers):
        return self._request("POST", f"/cohort-programs/{cohort_id}/finalize-cohort", headers=headers)

    def graduate_cohort(self, cohort_id, headers):
        return self._request("POST", f"/cohort-programs/{cohort_id}/graduate", headers=headers)

    def dissolve_cohort(self, cohort_id, headers):
        return self._request("POST", f"/cohort-programs/{cohort_id}/dissolve", headers=headers)

    # --- Audition ---
    def create_audition(self, payload, headers):
        return self._request("POST", "/auditions", payload, headers)

    def list_auditions(self, headers, params=None):
        return self._request("GET", "/auditions", headers=headers, params=params)

    def get_audition(self, audition_id, headers):
        return self._request("GET", f"/auditions/{audition_id}", headers=headers)

    def evaluate_audition(self, audition_id, headers):
        return self._request("POST", f"/auditions/{audition_id}/evaluate", headers=headers)

    def waitlist_audition(self, audition_id, headers):
        return self._request("POST", f"/auditions/{audition_id}/waitlist", headers=headers)

    def reject_audition(self, audition_id, headers):
        return self._request("POST", f"/auditions/{audition_id}/reject", headers=headers)

    # --- EnsembleCast ---
    def create_ensemble_cast(self, payload, headers):
        return self._request("POST", "/ensemble-casts", payload, headers)

    def list_ensemble_casts(self, headers, params=None):
        return self._request("GET", "/ensemble-casts", headers=headers, params=params)

    def get_ensemble_cast(self, cast_id, headers):
        return self._request("GET", f"/ensemble-casts/{cast_id}", headers=headers)

    def open_casting(self, cast_id, headers):
        return self._request("POST", f"/ensemble-casts/{cast_id}/open-casting", headers=headers)

    def cast_ensemble(self, cast_id, headers):
        return self._request("POST", f"/ensemble-casts/{cast_id}/cast", headers=headers)

    def lock_cast(self, cast_id, expected_cast_version, headers):
        return self._request("POST", f"/ensemble-casts/{cast_id}/lock-cast",
                             {"expected_cast_version": expected_cast_version}, headers)

    def open_revue(self, cast_id, headers):
        return self._request("POST", f"/ensemble-casts/{cast_id}/open-revue", headers=headers)

    def close_revue(self, cast_id, headers):
        return self._request("POST", f"/ensemble-casts/{cast_id}/close-revue", headers=headers)

    # --- TouringAssignment ---
    def create_touring_assignment(self, payload, headers):
        return self._request("POST", "/touring-assignments", payload, headers)

    def list_touring_assignments(self, headers, params=None):
        return self._request("GET", "/touring-assignments", headers=headers, params=params)

    def get_touring_assignment(self, assignment_id, headers):
        return self._request("GET", f"/touring-assignments/{assignment_id}", headers=headers)

    def accept_touring_assignment(self, assignment_id, headers):
        return self._request("POST", f"/touring-assignments/{assignment_id}/accept", headers=headers)

    def decline_touring_assignment(self, assignment_id, headers):
        return self._request("POST", f"/touring-assignments/{assignment_id}/decline", headers=headers)

    def sync_touring_assignment(self, assignment_id, headers):
        return self._request("POST", f"/touring-assignments/{assignment_id}/sync", headers=headers)

    def replace_touring_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/touring-assignments/{assignment_id}/replace", payload, headers)

    # --- ScholarshipAward ---
    def create_scholarship(self, payload, headers):
        return self._request("POST", "/scholarships", payload, headers)

    def list_scholarships(self, headers, params=None):
        return self._request("GET", "/scholarships", headers=headers, params=params)

    def get_scholarship(self, scholarship_id, headers):
        return self._request("GET", f"/scholarships/{scholarship_id}", headers=headers)

    def award_scholarship(self, scholarship_id, headers):
        return self._request("POST", f"/scholarships/{scholarship_id}/award", headers=headers)

    def deny_scholarship(self, scholarship_id, headers):
        return self._request("POST", f"/scholarships/{scholarship_id}/deny", headers=headers)

    def revoke_scholarship(self, scholarship_id, headers):
        return self._request("POST", f"/scholarships/{scholarship_id}/revoke", headers=headers)

    # --- TuitionInvoice ---
    def create_tuition_invoice(self, payload, headers):
        return self._request("POST", "/tuition-invoices", payload, headers)

    def list_tuition_invoices(self, headers, params=None):
        return self._request("GET", "/tuition-invoices", headers=headers, params=params)

    def get_tuition_invoice(self, invoice_id, headers):
        return self._request("GET", f"/tuition-invoices/{invoice_id}", headers=headers)

    def pay_tuition_invoice(self, invoice_id, amount_cents, headers):
        return self._request("POST", f"/tuition-invoices/{invoice_id}/pay",
                             {"amount_cents": amount_cents}, headers)


api_client = ApiClient()
