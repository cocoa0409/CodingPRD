"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (PRD §2.4) --------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/accreditation/_clock/set_current_utc", payload, headers)

    # --- Institutions ---------------------------------------------------------
    def create_institution(self, payload, headers):
        return self._request("POST", "/accreditation/institutions", payload, headers)

    def list_institutions(self, headers, params=None):
        return self._request("GET", "/accreditation/institutions", headers=headers, params=params)

    def get_institution(self, institution_id, headers):
        return self._request("GET", f"/accreditation/institutions/{institution_id}", headers=headers)

    def update_institution(self, institution_id, payload, headers):
        return self._request("PATCH", f"/accreditation/institutions/{institution_id}", payload, headers)

    # --- Eligibility applications ----------------------------------------------
    def create_eligibility_application(self, institution_id, payload, headers):
        return self._request("POST", f"/accreditation/institutions/{institution_id}/eligibility-applications", payload, headers)

    def list_eligibility_applications(self, institution_id, headers, params=None):
        return self._request("GET", f"/accreditation/institutions/{institution_id}/eligibility-applications", headers=headers, params=params)

    def file_eligibility_application(self, application_id, payload, headers):
        return self._request("POST", f"/accreditation/eligibility-applications/{application_id}/file", payload, headers)

    def adjudicate_eligibility_application(self, application_id, payload, headers):
        return self._request("POST", f"/accreditation/eligibility-applications/{application_id}/adjudicate", payload, headers)

    # --- Review cycles -----------------------------------------------------------
    def create_review_cycle(self, institution_id, payload, headers):
        return self._request("POST", f"/accreditation/institutions/{institution_id}/review-cycles", payload, headers)

    def list_review_cycles(self, institution_id, headers, params=None):
        return self._request("GET", f"/accreditation/institutions/{institution_id}/review-cycles", headers=headers, params=params)

    def get_review_cycle(self, cycle_id, headers):
        return self._request("GET", f"/accreditation/review-cycles/{cycle_id}", headers=headers)

    def advance_review_cycle(self, cycle_id, payload, headers):
        return self._request("POST", f"/accreditation/review-cycles/{cycle_id}/advance", payload, headers)

    def record_federal_compliance(self, cycle_id, payload, headers):
        return self._request("POST", f"/accreditation/review-cycles/{cycle_id}/record-federal-compliance", payload, headers)

    # --- Assurance arguments & evidence -------------------------------------------
    def create_assurance_argument(self, cycle_id, payload, headers):
        return self._request("POST", f"/accreditation/review-cycles/{cycle_id}/assurance-arguments", payload, headers)

    def list_assurance_arguments(self, cycle_id, headers, params=None):
        return self._request("GET", f"/accreditation/review-cycles/{cycle_id}/assurance-arguments", headers=headers, params=params)

    def get_assurance_argument(self, argument_id, headers):
        return self._request("GET", f"/accreditation/assurance-arguments/{argument_id}", headers=headers)

    def submit_assurance_argument(self, argument_id, payload, headers):
        return self._request("POST", f"/accreditation/assurance-arguments/{argument_id}/submit", payload, headers)

    def request_argument_revision(self, argument_id, payload, headers):
        return self._request("POST", f"/accreditation/assurance-arguments/{argument_id}/request-revision", payload, headers)

    def lock_assurance_argument(self, argument_id, payload, headers):
        return self._request("POST", f"/accreditation/assurance-arguments/{argument_id}/lock", payload, headers)

    def create_evidence_item(self, argument_id, payload, headers):
        return self._request("POST", f"/accreditation/assurance-arguments/{argument_id}/evidence-items", payload, headers)

    def list_evidence_items(self, argument_id, headers, params=None):
        return self._request("GET", f"/accreditation/assurance-arguments/{argument_id}/evidence-items", headers=headers, params=params)

    def verify_evidence_item(self, item_id, payload, headers):
        return self._request("POST", f"/accreditation/evidence-items/{item_id}/verify", payload, headers)

    # --- Reviewer registry -----------------------------------------------------------
    def create_reviewer(self, payload, headers):
        return self._request("POST", "/accreditation/reviewers", payload, headers)

    def list_reviewers(self, headers, params=None):
        return self._request("GET", "/accreditation/reviewers", headers=headers, params=params)

    def get_reviewer(self, reviewer_id, headers):
        return self._request("GET", f"/accreditation/reviewers/{reviewer_id}", headers=headers)

    def update_reviewer(self, reviewer_id, payload, headers):
        return self._request("PATCH", f"/accreditation/reviewers/{reviewer_id}", payload, headers)

    # --- Review teams, assignments, site visit ----------------------------------------
    def assemble_review_team(self, cycle_id, payload, headers):
        return self._request("POST", f"/accreditation/review-cycles/{cycle_id}/review-teams", payload, headers)

    def list_review_teams(self, cycle_id, headers, params=None):
        return self._request("GET", f"/accreditation/review-cycles/{cycle_id}/review-teams", headers=headers, params=params)

    def get_review_team(self, team_id, headers):
        return self._request("GET", f"/accreditation/review-teams/{team_id}", headers=headers)

    def list_team_assignments(self, team_id, headers, params=None):
        return self._request("GET", f"/accreditation/review-teams/{team_id}/assignments", headers=headers, params=params)

    def list_reviewer_assignments(self, reviewer_id, headers, params=None):
        return self._request("GET", f"/accreditation/reviewers/{reviewer_id}/assignments", headers=headers, params=params)

    def respond_to_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/accreditation/team-assignments/{assignment_id}/respond", payload, headers)

    def confirm_review_team(self, team_id, payload, headers):
        return self._request("POST", f"/accreditation/review-teams/{team_id}/confirm", payload, headers)

    def schedule_visit(self, team_id, payload, headers):
        return self._request("POST", f"/accreditation/review-teams/{team_id}/schedule-visit", payload, headers)

    def file_team_report(self, team_id, payload, headers):
        return self._request("POST", f"/accreditation/review-teams/{team_id}/file-report", payload, headers)

    def cancel_visit(self, team_id, payload, headers):
        return self._request("POST", f"/accreditation/review-teams/{team_id}/cancel-visit", payload, headers)

    # --- Decision panels & action outcomes ----------------------------------------------
    def convene_decision_panel(self, cycle_id, payload, headers):
        return self._request("POST", f"/accreditation/review-cycles/{cycle_id}/decision-panels", payload, headers)

    def list_decision_panels(self, cycle_id, headers, params=None):
        return self._request("GET", f"/accreditation/review-cycles/{cycle_id}/decision-panels", headers=headers, params=params)

    def cast_panel_vote(self, panel_id, payload, headers):
        return self._request("POST", f"/accreditation/decision-panels/{panel_id}/cast-vote", payload, headers)

    def close_decision_panel(self, panel_id, payload, headers):
        return self._request("POST", f"/accreditation/decision-panels/{panel_id}/close", payload, headers)

    def list_cycle_action_outcomes(self, cycle_id, headers, params=None):
        return self._request("GET", f"/accreditation/review-cycles/{cycle_id}/action-outcomes", headers=headers, params=params)

    def list_institution_action_outcomes(self, institution_id, headers, params=None):
        return self._request("GET", f"/accreditation/institutions/{institution_id}/action-outcomes", headers=headers, params=params)

    def advance_action_outcome(self, outcome_id, payload, headers):
        return self._request("POST", f"/accreditation/action-outcomes/{outcome_id}/advance", payload, headers)

    def sanction_transition(self, outcome_id, payload, headers):
        return self._request("POST", f"/accreditation/action-outcomes/{outcome_id}/sanction-transition", payload, headers)

    # --- Substantive change requests -----------------------------------------------------
    def create_substantive_change_request(self, institution_id, payload, headers):
        return self._request("POST", f"/accreditation/institutions/{institution_id}/substantive-change-requests", payload, headers)

    def list_substantive_change_requests(self, institution_id, headers, params=None):
        return self._request("GET", f"/accreditation/institutions/{institution_id}/substantive-change-requests", headers=headers, params=params)

    def submit_substantive_change(self, change_id, payload, headers):
        return self._request("POST", f"/accreditation/substantive-change-requests/{change_id}/submit", payload, headers)

    def decide_substantive_change(self, change_id, payload, headers):
        return self._request("POST", f"/accreditation/substantive-change-requests/{change_id}/decide", payload, headers)

    # --- Indicator reports ------------------------------------------------------------------
    def create_indicator_report(self, institution_id, payload, headers):
        return self._request("POST", f"/accreditation/institutions/{institution_id}/indicator-reports", payload, headers)

    def list_indicator_reports(self, institution_id, headers, params=None):
        return self._request("GET", f"/accreditation/institutions/{institution_id}/indicator-reports", headers=headers, params=params)

    def submit_indicator_report(self, report_id, payload, headers):
        return self._request("POST", f"/accreditation/indicator-reports/{report_id}/submit", payload, headers)

    def evaluate_indicator_report(self, report_id, payload, headers):
        return self._request("POST", f"/accreditation/indicator-reports/{report_id}/evaluate", payload, headers)


api_client = ApiClient()
