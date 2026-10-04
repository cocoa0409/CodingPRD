"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock (PRD §2.4) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- districts ---
    def create_district(self, payload, headers):
        return self._request("POST", "/sis/districts", payload, headers)

    def list_districts(self, headers, params=None):
        return self._request("GET", "/sis/districts", headers=headers, params=params)

    def get_district(self, district_id, headers):
        return self._request("GET", f"/sis/districts/{district_id}", headers=headers)

    def activate_district(self, district_id, headers):
        return self._request("POST", f"/sis/districts/{district_id}/activate", {}, headers)

    def suspend_district(self, district_id, headers):
        return self._request("POST", f"/sis/districts/{district_id}/suspend", {}, headers)

    # --- school years ---
    def create_school_year(self, payload, headers):
        return self._request("POST", "/sis/school-years", payload, headers)

    def list_school_years(self, headers, params=None):
        return self._request("GET", "/sis/school-years", headers=headers, params=params)

    def get_school_year(self, year_id, headers):
        return self._request("GET", f"/sis/school-years/{year_id}", headers=headers)

    def open_school_year(self, year_id, headers):
        return self._request("POST", f"/sis/school-years/{year_id}/open", {}, headers)

    def close_school_year_for_reporting(self, year_id, headers):
        return self._request(
            "POST", f"/sis/school-years/{year_id}/close-for-reporting", {}, headers)

    def archive_school_year(self, year_id, headers):
        return self._request("POST", f"/sis/school-years/{year_id}/archive", {}, headers)

    # --- state collection specs ---
    def create_collection_spec(self, payload, headers):
        return self._request("POST", "/sis/collection-specs", payload, headers)

    def list_collection_specs(self, headers, params=None):
        return self._request("GET", "/sis/collection-specs", headers=headers, params=params)

    # PRD §4 defines no GET /sis/collection-specs/{id}; observe spec state via
    # the list endpoint (see fixtures.get_spec).

    def publish_collection_spec(self, spec_id, headers):
        return self._request("POST", f"/sis/collection-specs/{spec_id}/publish", {}, headers)

    def retire_collection_spec(self, spec_id, headers):
        return self._request("POST", f"/sis/collection-specs/{spec_id}/retire", {}, headers)

    # --- students ---
    def create_student(self, payload, headers):
        return self._request("POST", "/sis/students", payload, headers)

    def list_students(self, headers, params=None):
        return self._request("GET", "/sis/students", headers=headers, params=params)

    def get_student(self, student_id, headers):
        return self._request("GET", f"/sis/students/{student_id}", headers=headers)

    # --- courses ---
    def create_course(self, payload, headers):
        return self._request("POST", "/sis/courses", payload, headers)

    def list_courses(self, headers, params=None):
        return self._request("GET", "/sis/courses", headers=headers, params=params)

    def get_course(self, course_id, headers):
        return self._request("GET", f"/sis/courses/{course_id}", headers=headers)

    # --- sections ---
    def create_section(self, payload, headers):
        return self._request("POST", "/sis/sections", payload, headers)

    def list_sections(self, headers, params=None):
        return self._request("GET", "/sis/sections", headers=headers, params=params)

    def get_section(self, section_id, headers):
        return self._request("GET", f"/sis/sections/{section_id}", headers=headers)

    def get_section_roster(self, section_id, headers):
        return self._request("GET", f"/sis/sections/{section_id}/roster", headers=headers)

    def commit_section(self, section_id, headers):
        return self._request("POST", f"/sis/sections/{section_id}/commit", {}, headers)

    def cancel_section(self, section_id, headers):
        return self._request("POST", f"/sis/sections/{section_id}/cancel", {}, headers)

    def assign_teacher(self, section_id, payload, headers):
        return self._request("POST", f"/sis/sections/{section_id}/assign-teacher",
                             payload, headers)

    def roster_add(self, section_id, payload, headers):
        return self._request("POST", f"/sis/sections/{section_id}/roster-adds",
                             payload, headers)

    def roster_drop(self, section_id, payload, headers):
        return self._request("POST", f"/sis/sections/{section_id}/roster-drops",
                             payload, headers)

    # --- enrollments ---
    def create_enrollment(self, payload, headers):
        return self._request("POST", "/sis/enrollments", payload, headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/sis/enrollments", headers=headers, params=params)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/sis/enrollments/{enrollment_id}", headers=headers)

    def withdraw_enrollment(self, enrollment_id, payload, headers):
        return self._request(
            "POST", f"/sis/enrollments/{enrollment_id}/withdraw", payload, headers)

    def reenter_enrollment(self, enrollment_id, payload, headers):
        return self._request(
            "POST", f"/sis/enrollments/{enrollment_id}/reenter", payload, headers)

    def post_attendance_event(self, enrollment_id, payload, headers):
        return self._request(
            "POST", f"/sis/enrollments/{enrollment_id}/attendance-events", payload, headers)

    def list_attendance_events(self, enrollment_id, headers, params=None):
        return self._request(
            "GET", f"/sis/enrollments/{enrollment_id}/attendance-events",
            headers=headers, params=params)

    # --- discipline incidents ---
    def create_discipline_incident(self, payload, headers):
        return self._request("POST", "/sis/discipline-incidents", payload, headers)

    def list_discipline_incidents(self, headers, params=None):
        return self._request("GET", "/sis/discipline-incidents", headers=headers, params=params)

    def get_discipline_incident(self, incident_id, headers):
        return self._request("GET", f"/sis/discipline-incidents/{incident_id}",
                             headers=headers)

    def approve_discipline_incident(self, incident_id, headers):
        return self._request(
            "POST", f"/sis/discipline-incidents/{incident_id}/approve", {}, headers)

    def void_discipline_incident(self, incident_id, headers):
        return self._request(
            "POST", f"/sis/discipline-incidents/{incident_id}/void", {}, headers)

    # --- reporting extracts ---
    def create_reporting_extract(self, payload, headers):
        return self._request("POST", "/sis/reporting-extracts", payload, headers)

    def list_reporting_extracts(self, headers, params=None):
        return self._request("GET", "/sis/reporting-extracts", headers=headers, params=params)

    def get_reporting_extract(self, extract_id, headers):
        return self._request("GET", f"/sis/reporting-extracts/{extract_id}", headers=headers)

    def validate_extract(self, extract_id, headers):
        return self._request(
            "POST", f"/sis/reporting-extracts/{extract_id}/validate", {}, headers)

    def reopen_extract(self, extract_id, headers):
        return self._request(
            "POST", f"/sis/reporting-extracts/{extract_id}/reopen", {}, headers)

    def submit_extract(self, extract_id, headers):
        return self._request(
            "POST", f"/sis/reporting-extracts/{extract_id}/submit", {}, headers)

    def resolve_extract(self, extract_id, payload, headers):
        return self._request(
            "POST", f"/sis/reporting-extracts/{extract_id}/resolve", payload, headers)

    # --- portal accounts ---
    def create_portal_account(self, payload, headers):
        return self._request("POST", "/sis/portal-accounts", payload, headers)

    def list_portal_accounts(self, headers, params=None):
        return self._request("GET", "/sis/portal-accounts", headers=headers, params=params)

    def get_portal_account(self, account_id, headers):
        return self._request("GET", f"/sis/portal-accounts/{account_id}", headers=headers)

    def activate_portal_account(self, account_id, headers):
        return self._request(
            "POST", f"/sis/portal-accounts/{account_id}/activate", {}, headers)

    def revoke_portal_account(self, account_id, headers):
        return self._request(
            "POST", f"/sis/portal-accounts/{account_id}/revoke", {}, headers)

    def update_portal_account_access(self, account_id, payload, headers):
        return self._request(
            "POST", f"/sis/portal-accounts/{account_id}/update-access", payload, headers)

    # --- integration feeds ---
    def create_integration_feed(self, payload, headers):
        return self._request("POST", "/sis/integration-feeds", payload, headers)

    def list_integration_feeds(self, headers, params=None):
        return self._request("GET", "/sis/integration-feeds", headers=headers, params=params)

    def get_integration_feed(self, feed_id, headers):
        return self._request("GET", f"/sis/integration-feeds/{feed_id}", headers=headers)

    def sync_integration_feed(self, feed_id, headers):
        return self._request("POST", f"/sis/integration-feeds/{feed_id}/sync", {}, headers)

    # --- rollover runs ---
    def create_rollover_run(self, payload, headers):
        return self._request("POST", "/sis/rollover-runs", payload, headers)

    def list_rollover_runs(self, headers, params=None):
        return self._request("GET", "/sis/rollover-runs", headers=headers, params=params)

    def get_rollover_run(self, run_id, headers):
        return self._request("GET", f"/sis/rollover-runs/{run_id}", headers=headers)

    def execute_rollover_run(self, run_id, headers):
        return self._request("POST", f"/sis/rollover-runs/{run_id}/execute", {}, headers)

    def compensate_rollover_run(self, run_id, headers):
        return self._request("POST", f"/sis/rollover-runs/{run_id}/compensate", {}, headers)


api_client = ApiClient()
