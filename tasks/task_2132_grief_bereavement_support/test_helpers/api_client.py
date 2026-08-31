"""API client: one method per endpoint defined in the PRD.

Every route is mounted beneath /bereavement.
"""

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/bereavement"


class ApiClient(GenericApiClient):
    # ---------------- Logical clock and operational sweep ----------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    def cadence_run(self, headers):
        return self._request("POST", f"{PREFIX}/_ops/cadence-run", {}, headers)

    # ---------------- Referrals ----------------
    def create_referral(self, payload, headers):
        return self._request("POST", f"{PREFIX}/referrals", payload, headers)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"{PREFIX}/referrals/{referral_id}", headers=headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/referrals", headers=headers, params=params)

    def screen_referral(self, referral_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/referrals/{referral_id}/screen", payload, headers)

    def accept_referral(self, referral_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/referrals/{referral_id}/accept", payload or {}, headers)

    def decline_referral(self, referral_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/referrals/{referral_id}/decline", payload, headers)

    # ---------------- Participants ----------------
    def get_participant(self, participant_id, headers):
        return self._request(
            "GET", f"{PREFIX}/participants/{participant_id}", headers=headers)

    def list_participants(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/participants", headers=headers, params=params)

    def create_assessment(self, participant_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/participants/{participant_id}/assessments", payload, headers)

    def list_assessments(self, participant_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/participants/{participant_id}/assessments",
            headers=headers, params=params)

    def get_outcome_summary(self, participant_id, headers):
        return self._request(
            "GET", f"{PREFIX}/participants/{participant_id}/outcome-summary", headers=headers)

    def withdraw_participant(self, participant_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/participants/{participant_id}/withdraw", payload or {}, headers)

    def set_outreach_hold(self, participant_id, hold, headers):
        return self._request(
            "POST", f"{PREFIX}/participants/{participant_id}/outreach-hold",
            {"hold": hold}, headers)

    def list_anniversary_outreaches(self, participant_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/participants/{participant_id}/anniversary-outreaches",
            headers=headers, params=params)

    # ---------------- Anniversary outreach touchpoints ----------------
    def send_outreach(self, outreach_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/anniversary-outreaches/{outreach_id}/send",
            payload or {}, headers)

    def acknowledge_outreach(self, outreach_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/anniversary-outreaches/{outreach_id}/acknowledge",
            payload or {}, headers)

    # ---------------- Meeting spaces ----------------
    def create_meeting_space(self, payload, headers):
        return self._request("POST", f"{PREFIX}/meeting-spaces", payload, headers)

    def get_meeting_space(self, space_id, headers):
        return self._request("GET", f"{PREFIX}/meeting-spaces/{space_id}", headers=headers)

    def set_meeting_space_status(self, space_id, status, headers):
        return self._request(
            "POST", f"{PREFIX}/meeting-spaces/{space_id}/status", {"status": status}, headers)

    # ---------------- Cohorts ----------------
    def create_cohort(self, payload, headers):
        return self._request("POST", f"{PREFIX}/cohorts", payload, headers)

    def get_cohort(self, cohort_id, headers):
        return self._request("GET", f"{PREFIX}/cohorts/{cohort_id}", headers=headers)

    def list_cohorts(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/cohorts", headers=headers, params=params)

    def open_cohort_enrollment(self, cohort_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/cohorts/{cohort_id}/open-enrollment", payload or {}, headers)

    def launch_cohort(self, cohort_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/cohorts/{cohort_id}/launch", payload or {}, headers)

    def suspend_cohort(self, cohort_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/cohorts/{cohort_id}/suspend", payload or {}, headers)

    def resume_cohort(self, cohort_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/cohorts/{cohort_id}/resume", payload or {}, headers)

    def complete_cohort(self, cohort_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/cohorts/{cohort_id}/complete", payload or {}, headers)

    def cancel_cohort(self, cohort_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/cohorts/{cohort_id}/cancel", payload or {}, headers)

    # ---------------- Enrollments ----------------
    def create_enrollment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/enrollments", payload, headers)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"{PREFIX}/enrollments/{enrollment_id}", headers=headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/enrollments", headers=headers, params=params)

    def confirm_enrollment(self, enrollment_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/enrollments/{enrollment_id}/confirm", payload or {}, headers)

    def withdraw_enrollment(self, enrollment_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/enrollments/{enrollment_id}/withdraw", payload, headers)

    def log_attendance(self, enrollment_id, sessions_delta, headers):
        return self._request(
            "POST", f"{PREFIX}/enrollments/{enrollment_id}/attendance",
            {"sessions_delta": sessions_delta}, headers)

    # ---------------- Counselors ----------------
    def create_counselor(self, payload, headers):
        return self._request("POST", f"{PREFIX}/counselors", payload, headers)

    def get_counselor(self, counselor_id, headers):
        return self._request("GET", f"{PREFIX}/counselors/{counselor_id}", headers=headers)

    def deactivate_counselor(self, counselor_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/counselors/{counselor_id}/deactivate", payload or {}, headers)

    # ---------------- Counselling referrals ----------------
    def create_counseling_referral(self, payload, headers):
        return self._request("POST", f"{PREFIX}/counseling-referrals", payload, headers)

    def get_counseling_referral(self, referral_id, headers):
        return self._request(
            "GET", f"{PREFIX}/counseling-referrals/{referral_id}", headers=headers)

    def list_counseling_referrals(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/counseling-referrals", headers=headers, params=params)

    def assign_counseling_referral(self, referral_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/counseling-referrals/{referral_id}/assign", payload, headers)

    def close_counseling_referral(self, referral_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/counseling-referrals/{referral_id}/close", payload, headers)

    # ---------------- Volunteer companions ----------------
    def create_volunteer_companion(self, payload, headers):
        return self._request("POST", f"{PREFIX}/volunteer-companions", payload, headers)

    def get_volunteer_companion(self, companion_id, headers):
        return self._request(
            "GET", f"{PREFIX}/volunteer-companions/{companion_id}", headers=headers)

    def create_training_record(self, companion_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/volunteer-companions/{companion_id}/training-records",
            payload, headers)

    def suspend_volunteer_companion(self, companion_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/volunteer-companions/{companion_id}/suspend",
            payload or {}, headers)

    def reinstate_volunteer_companion(self, companion_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/volunteer-companions/{companion_id}/reinstate",
            payload or {}, headers)

    # ---------------- Companion matches ----------------
    def create_companion_match(self, payload, headers):
        return self._request("POST", f"{PREFIX}/companion-matches", payload, headers)

    def get_companion_match(self, match_id, headers):
        return self._request("GET", f"{PREFIX}/companion-matches/{match_id}", headers=headers)

    def list_companion_matches(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/companion-matches", headers=headers, params=params)

    def respond_companion_match(self, match_id, decision, headers):
        return self._request(
            "POST", f"{PREFIX}/companion-matches/{match_id}/respond",
            {"decision": decision}, headers)

    def end_companion_match(self, match_id, end_reason, headers):
        return self._request(
            "POST", f"{PREFIX}/companion-matches/{match_id}/end",
            {"end_reason": end_reason}, headers)

    # ---------------- Remembrance events ----------------
    def create_remembrance_event(self, payload, headers):
        return self._request("POST", f"{PREFIX}/remembrance-events", payload, headers)

    def get_remembrance_event(self, event_id, headers):
        return self._request(
            "GET", f"{PREFIX}/remembrance-events/{event_id}", headers=headers)

    def list_remembrance_events(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/remembrance-events", headers=headers, params=params)

    def confirm_remembrance_event(self, event_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/remembrance-events/{event_id}/confirm", payload or {}, headers)

    def cancel_remembrance_event(self, event_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/remembrance-events/{event_id}/cancel", payload or {}, headers)

    def mark_remembrance_event_held(self, event_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/remembrance-events/{event_id}/mark-held", payload or {}, headers)

    # ---------------- Invitations ----------------
    def create_invitation(self, payload, headers):
        return self._request("POST", f"{PREFIX}/invitations", payload, headers)

    def get_invitation(self, invitation_id, headers):
        return self._request("GET", f"{PREFIX}/invitations/{invitation_id}", headers=headers)

    def list_invitations(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/invitations", headers=headers, params=params)

    def send_invitation(self, invitation_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/invitations/{invitation_id}/send", payload or {}, headers)

    def respond_invitation(self, invitation_id, response, headers):
        return self._request(
            "POST", f"{PREFIX}/invitations/{invitation_id}/respond",
            {"response": response}, headers)

    # ---------------- Grant awards ----------------
    def create_grant_award(self, payload, headers):
        return self._request("POST", f"{PREFIX}/grant-awards", payload, headers)

    def get_grant_award(self, award_id, headers):
        return self._request("GET", f"{PREFIX}/grant-awards/{award_id}", headers=headers)

    def close_grant_award(self, award_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/grant-awards/{award_id}/close", payload or {}, headers)

    # ---------------- Funding allocations ----------------
    def create_funding_allocation(self, payload, headers):
        return self._request("POST", f"{PREFIX}/funding-allocations", payload, headers)

    def get_funding_allocation(self, allocation_id, headers):
        return self._request(
            "GET", f"{PREFIX}/funding-allocations/{allocation_id}", headers=headers)

    def list_funding_allocations(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/funding-allocations", headers=headers, params=params)

    def release_funding_allocation(self, allocation_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/funding-allocations/{allocation_id}/release",
            payload or {}, headers)

    # ---------------- Grant reports ----------------
    def create_grant_report(self, payload, headers):
        return self._request("POST", f"{PREFIX}/grant-reports", payload, headers)

    def get_grant_report(self, report_id, headers):
        return self._request("GET", f"{PREFIX}/grant-reports/{report_id}", headers=headers)

    def list_grant_reports(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/grant-reports", headers=headers, params=params)

    def submit_grant_report(self, report_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/grant-reports/{report_id}/submit", payload or {}, headers)

    def return_grant_report(self, report_id, return_reason, headers):
        return self._request(
            "POST", f"{PREFIX}/grant-reports/{report_id}/return",
            {"return_reason": return_reason}, headers)

    def revise_grant_report(self, report_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/grant-reports/{report_id}/revise", payload or {}, headers)

    def accept_grant_report(self, report_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/grant-reports/{report_id}/accept", payload or {}, headers)

    # ---------------- Raw escape hatch (header-omission probes) ----------------
    def raw_post(self, path, payload, headers):
        return self._request("POST", f"{PREFIX}{path}", payload, headers)

    def raw_get(self, path, headers, params=None):
        return self._request("GET", f"{PREFIX}{path}", headers=headers, params=params)


api_client = ApiClient()
