"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- test-driving clock ---------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- organizations --------------------------------------------------------
    def create_organization(self, payload, headers):
        return self._request("POST", "/organizations", payload, headers)

    def get_organization(self, org_id, headers):
        return self._request("GET", f"/organizations/{org_id}", headers=headers)

    def debar_organization(self, org_id, headers):
        return self._request("POST", f"/organizations/{org_id}/debar", {}, headers)

    # --- competitions ---------------------------------------------------------
    def create_competition(self, payload, headers):
        return self._request("POST", "/competitions", payload, headers)

    def get_competition(self, competition_id, headers):
        return self._request("GET", f"/competitions/{competition_id}", headers=headers)

    def close_competition(self, competition_id, headers):
        return self._request("POST", f"/competitions/{competition_id}/close", {}, headers)

    # --- applications ---------------------------------------------------------
    def create_application(self, competition_id, payload, headers):
        return self._request(
            "POST", f"/competitions/{competition_id}/applications", payload, headers
        )

    def list_applications(self, headers, params=None):
        return self._request("GET", "/applications", headers=headers, params=params)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/applications/{application_id}", headers=headers)

    def submit_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/submit", {}, headers)

    def request_clarification(self, application_id, payload, headers):
        return self._request(
            "POST", f"/applications/{application_id}/request-clarification", payload, headers
        )

    def respond_clarification(self, application_id, payload, headers):
        return self._request(
            "POST", f"/applications/{application_id}/respond-clarification", payload, headers
        )

    def award_application(self, application_id, payload, headers):
        return self._request("POST", f"/applications/{application_id}/award", payload, headers)

    def reject_application(self, application_id, payload, headers):
        return self._request("POST", f"/applications/{application_id}/reject", payload, headers)

    # --- awards ---------------------------------------------------------------
    def list_awards(self, headers, params=None):
        return self._request("GET", "/awards", headers=headers, params=params)

    def get_award(self, award_id, headers):
        return self._request("GET", f"/awards/{award_id}", headers=headers)

    def suspend_award(self, award_id, payload, headers):
        return self._request("POST", f"/awards/{award_id}/suspend", payload, headers)

    def reinstate_award(self, award_id, headers):
        return self._request("POST", f"/awards/{award_id}/reinstate", {}, headers)

    def close_award(self, award_id, headers):
        return self._request("POST", f"/awards/{award_id}/close", {}, headers)

    def create_match_report(self, award_id, payload, headers):
        return self._request("POST", f"/awards/{award_id}/match-reports", payload, headers)

    def list_slots(self, award_id, headers, params=None):
        return self._request("GET", f"/awards/{award_id}/slots", headers=headers, params=params)

    def list_award_visits(self, award_id, headers, params=None):
        return self._request(
            "GET", f"/awards/{award_id}/compliance-visits", headers=headers, params=params
        )

    def list_award_measures(self, award_id, headers, params=None):
        return self._request(
            "GET", f"/awards/{award_id}/performance-measures", headers=headers, params=params
        )

    # --- slots ----------------------------------------------------------------
    def get_slot(self, slot_id, headers):
        return self._request("GET", f"/slots/{slot_id}", headers=headers)

    # --- members & criminal history checks -------------------------------------
    def register_member(self, payload, headers):
        return self._request("POST", "/members/register", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def create_criminal_check(self, member_id, headers):
        return self._request(
            "POST", f"/members/{member_id}/criminal-history-checks", {}, headers
        )

    def list_criminal_checks(self, member_id, headers, params=None):
        return self._request(
            "GET", f"/members/{member_id}/criminal-history-checks", headers=headers, params=params
        )

    def record_component_result(self, check_id, payload, headers):
        return self._request(
            "POST", f"/criminal-history-checks/{check_id}/component-results", payload, headers
        )

    # --- enrollments ------------------------------------------------------------
    def create_enrollment(self, award_id, payload, headers):
        return self._request("POST", f"/awards/{award_id}/enrollments", payload, headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/enrollments", headers=headers, params=params)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/enrollments/{enrollment_id}", headers=headers)

    def suspend_enrollment(self, enrollment_id, payload, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/suspend", payload, headers)

    def reinstate_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/reinstate", {}, headers)

    def exit_enrollment(self, enrollment_id, payload, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/exit", payload, headers)

    def list_hour_entries(self, enrollment_id, headers, params=None):
        return self._request(
            "GET", f"/enrollments/{enrollment_id}/hour-entries", headers=headers, params=params
        )

    def list_allowance_payments(self, enrollment_id, headers, params=None):
        return self._request(
            "GET", f"/enrollments/{enrollment_id}/allowance-payments", headers=headers, params=params
        )

    def list_enrollment_grievances(self, enrollment_id, headers, params=None):
        return self._request(
            "GET", f"/enrollments/{enrollment_id}/grievances", headers=headers, params=params
        )

    # --- hour entries -----------------------------------------------------------
    def create_hour_entry(self, enrollment_id, payload, headers):
        return self._request(
            "POST", f"/enrollments/{enrollment_id}/hour-entries", payload, headers
        )

    def certify_hour_entry(self, entry_id, headers):
        return self._request("POST", f"/hour-entries/{entry_id}/certify", {}, headers)

    def reject_hour_entry(self, entry_id, payload, headers):
        return self._request("POST", f"/hour-entries/{entry_id}/reject", payload, headers)

    # --- living allowance payments ----------------------------------------------
    def create_allowance_payment(self, enrollment_id, payload, headers):
        return self._request(
            "POST", f"/enrollments/{enrollment_id}/allowance-payments", payload, headers
        )

    # --- education awards & uses -------------------------------------------------
    def list_education_awards(self, headers, params=None):
        return self._request("GET", "/education-awards", headers=headers, params=params)

    def get_education_award(self, education_award_id, headers):
        return self._request("GET", f"/education-awards/{education_award_id}", headers=headers)

    def create_award_use(self, education_award_id, payload, headers):
        return self._request(
            "POST", f"/education-awards/{education_award_id}/uses", payload, headers
        )

    def list_award_uses(self, education_award_id, headers, params=None):
        return self._request(
            "GET", f"/education-awards/{education_award_id}/uses", headers=headers, params=params
        )

    def decide_use(self, use_id, payload, headers):
        return self._request("POST", f"/education-award-uses/{use_id}/decide", payload, headers)

    def rescind_use(self, use_id, payload, headers):
        return self._request("POST", f"/education-award-uses/{use_id}/rescind", payload, headers)

    # --- compliance visits & findings ---------------------------------------------
    def create_visit(self, award_id, payload, headers):
        return self._request("POST", f"/awards/{award_id}/compliance-visits", payload, headers)

    def conduct_visit(self, visit_id, headers):
        return self._request("POST", f"/compliance-visits/{visit_id}/conduct", {}, headers)

    def create_finding(self, visit_id, payload, headers):
        return self._request("POST", f"/compliance-visits/{visit_id}/findings", payload, headers)

    def list_findings(self, headers, params=None):
        return self._request("GET", "/findings", headers=headers, params=params)

    def get_finding(self, finding_id, headers):
        return self._request("GET", f"/findings/{finding_id}", headers=headers)

    def assign_corrective_action(self, finding_id, payload, headers):
        return self._request(
            "POST", f"/findings/{finding_id}/assign-corrective-action", payload, headers
        )

    def submit_evidence(self, finding_id, payload, headers):
        return self._request("POST", f"/findings/{finding_id}/submit-evidence", payload, headers)

    def decide_finding(self, finding_id, payload, headers):
        return self._request("POST", f"/findings/{finding_id}/decide", payload, headers)

    def sweep_overdue(self, headers):
        return self._request("POST", "/compliance/sweep-overdue", {}, headers)

    # --- grievances -----------------------------------------------------------------
    def create_grievance(self, enrollment_id, payload, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/grievances", payload, headers)

    def escalate_grievance(self, grievance_id, headers):
        return self._request("POST", f"/grievances/{grievance_id}/escalate", {}, headers)

    def resolve_grievance(self, grievance_id, payload, headers):
        return self._request("POST", f"/grievances/{grievance_id}/resolve", payload, headers)

    # --- performance measures ---------------------------------------------------------
    def create_performance_measure(self, award_id, payload, headers):
        return self._request(
            "POST", f"/awards/{award_id}/performance-measures", payload, headers
        )

    def submit_measure_report(self, measure_id, payload, headers):
        return self._request(
            "POST", f"/performance-measures/{measure_id}/reports", payload, headers
        )

    def review_measure(self, measure_id, payload, headers):
        return self._request("POST", f"/performance-measures/{measure_id}/review", payload, headers)


api_client = ApiClient()
