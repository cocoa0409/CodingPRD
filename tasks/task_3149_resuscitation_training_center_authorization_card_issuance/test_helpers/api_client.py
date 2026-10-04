"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/aha/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # --- Training centers ---
    def create_training_center(self, payload, headers):
        return self._request("POST", "/aha/training-centers", payload, headers)

    def get_training_center(self, center_id, headers):
        return self._request(
            "GET", f"/aha/training-centers/{center_id}", headers=headers)

    def activate_training_center(self, center_id, headers):
        return self._request(
            "POST", f"/aha/training-centers/{center_id}/activate", {}, headers)

    def reinstate_training_center(self, center_id, headers):
        return self._request(
            "POST", f"/aha/training-centers/{center_id}/reinstate", {}, headers)

    def suspend_training_center(self, center_id, headers):
        return self._request(
            "POST", f"/aha/training-centers/{center_id}/suspend", {}, headers)

    def revoke_training_center(self, center_id, headers):
        return self._request(
            "POST", f"/aha/training-centers/{center_id}/revoke", {}, headers)

    # --- Training sites ---
    def create_site(self, center_id, payload, headers):
        return self._request(
            "POST", f"/aha/training-centers/{center_id}/sites", payload, headers)

    def list_center_sites(self, center_id, headers, params=None):
        return self._request(
            "GET", f"/aha/training-centers/{center_id}/sites",
            headers=headers, params=params)

    def get_site(self, site_id, headers):
        return self._request("GET", f"/aha/training-sites/{site_id}", headers=headers)

    def align_site(self, site_id, payload, headers):
        return self._request(
            "POST", f"/aha/training-sites/{site_id}/align", payload, headers)

    def suspend_site(self, site_id, headers):
        return self._request(
            "POST", f"/aha/training-sites/{site_id}/suspend", {}, headers)

    def reinstate_site(self, site_id, headers):
        return self._request(
            "POST", f"/aha/training-sites/{site_id}/reinstate", {}, headers)

    def decommission_site(self, site_id, headers):
        return self._request(
            "POST", f"/aha/training-sites/{site_id}/decommission", {}, headers)

    # --- Instructors ---
    def create_instructor(self, payload, headers):
        return self._request("POST", "/aha/instructors", payload, headers)

    def get_instructor(self, instructor_id, headers):
        return self._request(
            "GET", f"/aha/instructors/{instructor_id}", headers=headers)

    def list_center_instructors(self, center_id, headers, params=None):
        return self._request(
            "GET", f"/aha/training-centers/{center_id}/instructors",
            headers=headers, params=params)

    def grant_faculty(self, instructor_id, headers):
        return self._request(
            "POST", f"/aha/instructors/{instructor_id}/grant-faculty", {}, headers)

    def monitor_instructor(self, instructor_id, payload, headers):
        return self._request(
            "POST", f"/aha/instructors/{instructor_id}/monitor", payload, headers)

    def list_monitorings(self, instructor_id, headers, params=None):
        return self._request(
            "GET", f"/aha/instructors/{instructor_id}/monitorings",
            headers=headers, params=params)

    def create_teaching_evaluation(self, instructor_id, payload, headers):
        return self._request(
            "POST", f"/aha/instructors/{instructor_id}/teaching-evaluations",
            payload, headers)

    def list_teaching_evaluations(self, instructor_id, headers, params=None):
        return self._request(
            "GET", f"/aha/instructors/{instructor_id}/teaching-evaluations",
            headers=headers, params=params)

    def certify_instructor(self, instructor_id, headers):
        return self._request(
            "POST", f"/aha/instructors/{instructor_id}/certify", {}, headers)

    def renew_instructor(self, instructor_id, headers):
        return self._request(
            "POST", f"/aha/instructors/{instructor_id}/renew", {}, headers)

    def suspend_instructor(self, instructor_id, headers):
        return self._request(
            "POST", f"/aha/instructors/{instructor_id}/suspend", {}, headers)

    def reinstate_instructor(self, instructor_id, headers):
        return self._request(
            "POST", f"/aha/instructors/{instructor_id}/reinstate", {}, headers)

    def reset_candidacy(self, instructor_id, headers):
        return self._request(
            "POST", f"/aha/instructors/{instructor_id}/reset-candidacy", {}, headers)

    # --- Alignments ---
    def create_alignment(self, center_id, payload, headers):
        return self._request(
            "POST", f"/aha/training-centers/{center_id}/alignments", payload, headers)

    def list_center_alignments(self, center_id, headers, params=None):
        return self._request(
            "GET", f"/aha/training-centers/{center_id}/alignments",
            headers=headers, params=params)

    def list_instructor_alignments(self, instructor_id, headers, params=None):
        return self._request(
            "GET", f"/aha/instructors/{instructor_id}/alignments",
            headers=headers, params=params)

    def end_alignment(self, alignment_id, headers):
        return self._request(
            "POST", f"/aha/alignments/{alignment_id}/end", {}, headers)

    # --- Guidelines versions ---
    def create_guidelines_version(self, payload, headers):
        return self._request("POST", "/aha/guidelines-versions", payload, headers)

    def list_guidelines_versions(self, headers, params=None):
        return self._request(
            "GET", "/aha/guidelines-versions", headers=headers, params=params)

    def get_guidelines_version(self, version_id, headers):
        return self._request(
            "GET", f"/aha/guidelines-versions/{version_id}", headers=headers)

    def activate_guidelines_version(self, version_id, headers):
        return self._request(
            "POST", f"/aha/guidelines-versions/{version_id}/activate", {}, headers)

    def list_guidelines_version_sessions(self, version_id, headers, params=None):
        return self._request(
            "GET", f"/aha/guidelines-versions/{version_id}/course-sessions",
            headers=headers, params=params)

    # --- Course sessions ---
    def create_course_session(self, payload, headers):
        return self._request("POST", "/aha/course-sessions", payload, headers)

    def get_course_session(self, session_id, headers):
        return self._request(
            "GET", f"/aha/course-sessions/{session_id}", headers=headers)

    def list_center_sessions(self, center_id, headers, params=None):
        return self._request(
            "GET", f"/aha/training-centers/{center_id}/course-sessions",
            headers=headers, params=params)

    def list_site_sessions(self, site_id, headers, params=None):
        return self._request(
            "GET", f"/aha/training-sites/{site_id}/course-sessions",
            headers=headers, params=params)

    def list_instructor_sessions(self, instructor_id, headers, params=None):
        return self._request(
            "GET", f"/aha/instructors/{instructor_id}/course-sessions",
            headers=headers, params=params)

    def start_session(self, session_id, headers):
        return self._request(
            "POST", f"/aha/course-sessions/{session_id}/start", {}, headers)

    def complete_session(self, session_id, headers):
        return self._request(
            "POST", f"/aha/course-sessions/{session_id}/complete", {}, headers)

    def cancel_session(self, session_id, headers):
        return self._request(
            "POST", f"/aha/course-sessions/{session_id}/cancel", {}, headers)

    # --- Roster ---
    def add_roster_entry(self, session_id, payload, headers):
        return self._request(
            "POST", f"/aha/course-sessions/{session_id}/roster", payload, headers)

    def list_roster(self, session_id, headers, params=None):
        return self._request(
            "GET", f"/aha/course-sessions/{session_id}/roster",
            headers=headers, params=params)

    def get_roster_entry(self, entry_id, headers):
        return self._request(
            "GET", f"/aha/roster-entries/{entry_id}", headers=headers)

    def cancel_roster_entry(self, entry_id, headers):
        return self._request(
            "POST", f"/aha/roster-entries/{entry_id}/cancel", {}, headers)

    # --- Skills evaluations ---
    def create_skills_evaluation(self, entry_id, payload, headers):
        return self._request(
            "POST", f"/aha/roster-entries/{entry_id}/skills-evaluations",
            payload, headers)

    def list_skills_evaluations(self, entry_id, headers, params=None):
        return self._request(
            "GET", f"/aha/roster-entries/{entry_id}/skills-evaluations",
            headers=headers, params=params)

    def list_instructor_skills_evaluations(self, instructor_id, headers, params=None):
        return self._request(
            "GET", f"/aha/instructors/{instructor_id}/skills-evaluations",
            headers=headers, params=params)

    # --- Cards ---
    def get_card(self, card_id, headers):
        return self._request("GET", f"/aha/cards/{card_id}", headers=headers)

    def list_roster_entry_cards(self, entry_id, headers, params=None):
        return self._request(
            "GET", f"/aha/roster-entries/{entry_id}/cards",
            headers=headers, params=params)

    def list_center_cards(self, center_id, headers, params=None):
        return self._request(
            "GET", f"/aha/training-centers/{center_id}/cards",
            headers=headers, params=params)

    def list_card_renewals(self, card_id, headers, params=None):
        return self._request(
            "GET", f"/aha/cards/{card_id}/renewals", headers=headers, params=params)

    def revoke_card(self, card_id, headers):
        return self._request(
            "POST", f"/aha/cards/{card_id}/revoke", {}, headers)

    def list_card_roster_entries(self, card_id, headers, params=None):
        return self._request(
            "GET", f"/aha/cards/{card_id}/roster-entries",
            headers=headers, params=params)

    def list_card_verifications(self, card_id, headers, params=None):
        return self._request(
            "GET", f"/aha/cards/{card_id}/verifications",
            headers=headers, params=params)

    # --- Employer verification ---
    def create_card_verification(self, payload, headers):
        return self._request("POST", "/aha/card-verifications", payload, headers)

    # --- Quality audits ---
    def create_quality_audit(self, payload, headers):
        return self._request("POST", "/aha/quality-audits", payload, headers)

    def get_quality_audit(self, audit_id, headers):
        return self._request("GET", f"/aha/quality-audits/{audit_id}", headers=headers)

    def list_center_audits(self, center_id, headers, params=None):
        return self._request(
            "GET", f"/aha/training-centers/{center_id}/quality-audits",
            headers=headers, params=params)

    def create_audit_finding(self, audit_id, payload, headers):
        return self._request(
            "POST", f"/aha/quality-audits/{audit_id}/findings", payload, headers)

    def list_audit_findings(self, audit_id, headers, params=None):
        return self._request(
            "GET", f"/aha/quality-audits/{audit_id}/findings",
            headers=headers, params=params)

    def close_audit(self, audit_id, payload, headers):
        return self._request(
            "POST", f"/aha/quality-audits/{audit_id}/close", payload, headers)


api_client = ApiClient()
