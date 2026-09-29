"""API client: one method per endpoint defined in the PRD (§4).

Every collection sits directly at the server root — the topology is flat, so no
resource is nested under another and every relationship travels in a request
body or as a query parameter.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # ─── AcademicTerm ────────────────────────────────────────────────────
    def create_academic_term(self, payload, headers):
        return self._request("POST", "/academic-terms", payload, headers)

    def list_academic_terms(self, headers, params=None):
        return self._request("GET", "/academic-terms", headers=headers, params=params)

    def get_academic_term(self, term_id, headers):
        return self._request("GET", f"/academic-terms/{term_id}", headers=headers)

    def patch_academic_term(self, term_id, payload, headers):
        return self._request("PATCH", f"/academic-terms/{term_id}", payload, headers)

    def term_lifecycle_transition(self, term_id, payload, headers):
        return self._request(
            "POST", f"/academic-terms/{term_id}/lifecycle-transitions", payload, headers
        )

    def term_posture_change(self, term_id, payload, headers):
        return self._request(
            "POST", f"/academic-terms/{term_id}/posture-changes", payload, headers
        )

    # ─── Person ──────────────────────────────────────────────────────────
    def create_person(self, payload, headers):
        return self._request("POST", "/people", payload, headers)

    def list_people(self, headers, params=None):
        return self._request("GET", "/people", headers=headers, params=params)

    def get_person(self, person_id, headers):
        return self._request("GET", f"/people/{person_id}", headers=headers)

    def patch_person(self, person_id, payload, headers):
        return self._request("PATCH", f"/people/{person_id}", payload, headers)

    # ─── CourseShell ─────────────────────────────────────────────────────
    def create_course_shell(self, payload, headers):
        return self._request("POST", "/course-shells", payload, headers)

    def list_course_shells(self, headers, params=None):
        return self._request("GET", "/course-shells", headers=headers, params=params)

    def get_course_shell(self, shell_id, headers):
        return self._request("GET", f"/course-shells/{shell_id}", headers=headers)

    def shell_provisioning_decision(self, shell_id, payload, headers):
        return self._request(
            "POST", f"/course-shells/{shell_id}/provisioning-decisions", payload, headers
        )

    def publish_shell(self, shell_id, headers, payload=None):
        return self._request(
            "POST", f"/course-shells/{shell_id}/publish", payload or {}, headers
        )

    def unpublish_shell(self, shell_id, headers, payload=None):
        return self._request(
            "POST", f"/course-shells/{shell_id}/unpublish", payload or {}, headers
        )

    def shell_lifecycle_transition(self, shell_id, payload, headers):
        return self._request(
            "POST", f"/course-shells/{shell_id}/lifecycle-transitions", payload, headers
        )

    # ─── ContentItem ─────────────────────────────────────────────────────
    def create_content_item(self, payload, headers):
        return self._request("POST", "/content-items", payload, headers)

    def list_content_items(self, headers, params=None):
        return self._request("GET", "/content-items", headers=headers, params=params)

    def get_content_item(self, item_id, headers):
        return self._request("GET", f"/content-items/{item_id}", headers=headers)

    def patch_content_item(self, item_id, payload, headers):
        return self._request("PATCH", f"/content-items/{item_id}", payload, headers)

    def delete_content_item(self, item_id, headers):
        return self._request("DELETE", f"/content-items/{item_id}", headers=headers)

    def create_submission(self, item_id, payload, headers):
        return self._request(
            "POST", f"/content-items/{item_id}/submissions", payload, headers
        )

    # ─── Enrollment ──────────────────────────────────────────────────────
    def create_enrollment(self, payload, headers):
        return self._request("POST", "/enrollments", payload, headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/enrollments", headers=headers, params=params)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/enrollments/{enrollment_id}", headers=headers)

    def enrollment_transition(self, enrollment_id, payload, headers):
        return self._request(
            "POST", f"/enrollments/{enrollment_id}/transitions", payload, headers
        )

    # ─── EnrollmentSyncBatch ─────────────────────────────────────────────
    def create_sync_batch(self, payload, headers):
        return self._request("POST", "/enrollment-sync-batches", payload, headers)

    def list_sync_batches(self, headers, params=None):
        return self._request(
            "GET", "/enrollment-sync-batches", headers=headers, params=params
        )

    def get_sync_batch(self, batch_id, headers):
        return self._request(
            "GET", f"/enrollment-sync-batches/{batch_id}", headers=headers
        )

    def sync_batch_transition(self, batch_id, payload, headers):
        return self._request(
            "POST", f"/enrollment-sync-batches/{batch_id}/transitions", payload, headers
        )

    # ─── MergeRequest ────────────────────────────────────────────────────
    def create_merge_request(self, payload, headers):
        return self._request("POST", "/merge-requests", payload, headers)

    def list_merge_requests(self, headers, params=None):
        return self._request("GET", "/merge-requests", headers=headers, params=params)

    def get_merge_request(self, merge_id, headers):
        return self._request("GET", f"/merge-requests/{merge_id}", headers=headers)

    def merge_request_transition(self, merge_id, payload, headers):
        return self._request(
            "POST", f"/merge-requests/{merge_id}/transitions", payload, headers
        )

    # ─── RolloverJob ─────────────────────────────────────────────────────
    def create_rollover_job(self, payload, headers):
        return self._request("POST", "/rollover-jobs", payload, headers)

    def list_rollover_jobs(self, headers, params=None):
        return self._request("GET", "/rollover-jobs", headers=headers, params=params)

    def get_rollover_job(self, job_id, headers):
        return self._request("GET", f"/rollover-jobs/{job_id}", headers=headers)

    def rollover_job_transition(self, job_id, payload, headers):
        return self._request(
            "POST", f"/rollover-jobs/{job_id}/transitions", payload, headers
        )

    # ─── ToolIntegration ─────────────────────────────────────────────────
    def create_tool_integration(self, payload, headers):
        return self._request("POST", "/tool-integrations", payload, headers)

    def list_tool_integrations(self, headers, params=None):
        return self._request(
            "GET", "/tool-integrations", headers=headers, params=params
        )

    def get_tool_integration(self, tool_id, headers):
        return self._request("GET", f"/tool-integrations/{tool_id}", headers=headers)

    def patch_tool_integration(self, tool_id, payload, headers):
        return self._request("PATCH", f"/tool-integrations/{tool_id}", payload, headers)

    def tool_integration_transition(self, tool_id, payload, headers):
        return self._request(
            "POST", f"/tool-integrations/{tool_id}/transitions", payload, headers
        )

    # ─── ToolReview ──────────────────────────────────────────────────────
    def create_tool_review(self, payload, headers):
        return self._request("POST", "/tool-reviews", payload, headers)

    def list_tool_reviews(self, headers, params=None):
        return self._request("GET", "/tool-reviews", headers=headers, params=params)

    def get_tool_review(self, review_id, headers):
        return self._request("GET", f"/tool-reviews/{review_id}", headers=headers)

    # ─── ToolPlacement ───────────────────────────────────────────────────
    def create_tool_placement(self, payload, headers):
        return self._request("POST", "/tool-placements", payload, headers)

    def list_tool_placements(self, headers, params=None):
        return self._request("GET", "/tool-placements", headers=headers, params=params)

    def get_tool_placement(self, placement_id, headers):
        return self._request("GET", f"/tool-placements/{placement_id}", headers=headers)

    def tool_placement_transition(self, placement_id, payload, headers):
        return self._request(
            "POST", f"/tool-placements/{placement_id}/transitions", payload, headers
        )

    # ─── GradePassback ───────────────────────────────────────────────────
    def create_grade_passback(self, payload, headers):
        return self._request("POST", "/grade-passbacks", payload, headers)

    def list_grade_passbacks(self, headers, params=None):
        return self._request("GET", "/grade-passbacks", headers=headers, params=params)

    def get_grade_passback(self, passback_id, headers):
        return self._request("GET", f"/grade-passbacks/{passback_id}", headers=headers)

    def grade_passback_transition(self, passback_id, payload, headers):
        return self._request(
            "POST", f"/grade-passbacks/{passback_id}/transitions", payload, headers
        )

    def registrar_decision(self, passback_id, payload, headers):
        return self._request(
            "POST",
            f"/grade-passbacks/{passback_id}/registrar-decisions",
            payload,
            headers,
        )

    # ─── GradeDispute ────────────────────────────────────────────────────
    def create_grade_dispute(self, payload, headers):
        return self._request("POST", "/grade-disputes", payload, headers)

    def list_grade_disputes(self, headers, params=None):
        return self._request("GET", "/grade-disputes", headers=headers, params=params)

    def get_grade_dispute(self, dispute_id, headers):
        return self._request("GET", f"/grade-disputes/{dispute_id}", headers=headers)

    def resolve_grade_dispute(self, dispute_id, payload, headers):
        return self._request(
            "POST", f"/grade-disputes/{dispute_id}/resolve", payload, headers
        )

    # ─── ContinuityWindow ────────────────────────────────────────────────
    def create_continuity_window(self, payload, headers):
        return self._request("POST", "/continuity-windows", payload, headers)

    def list_continuity_windows(self, headers, params=None):
        return self._request(
            "GET", "/continuity-windows", headers=headers, params=params
        )

    def get_continuity_window(self, window_id, headers):
        return self._request("GET", f"/continuity-windows/{window_id}", headers=headers)

    def continuity_window_transition(self, window_id, payload, headers):
        return self._request(
            "POST", f"/continuity-windows/{window_id}/transitions", payload, headers
        )

    # ─── Underscore-namespace drivers ────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def record_grade(self, payload, headers):
        return self._request("POST", "/_grade-records", payload, headers)

    # ─── Raw helpers for path/verb-level negative tests ──────────────────
    def raw_post(self, path, payload, headers):
        return self._request("POST", path, payload, headers)

    def raw_get(self, path, headers, params=None):
        return self._request("GET", path, headers=headers, params=params)


api_client = ApiClient()
