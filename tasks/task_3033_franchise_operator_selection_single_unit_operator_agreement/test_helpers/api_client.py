"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/franchise/_clock/set_current_utc", payload, headers)

    # --- Candidates ---
    def create_candidate(self, payload, headers):
        return self._request("POST", "/franchise/candidates", payload, headers)

    def get_candidate(self, candidate_id, headers):
        return self._request("GET", f"/franchise/candidates/{candidate_id}", headers=headers)

    def list_candidates(self, headers, params=None):
        return self._request("GET", "/franchise/candidates", headers=headers, params=params)

    def withdraw_candidate(self, candidate_id, headers):
        return self._request("POST", f"/franchise/candidates/{candidate_id}/withdraw", {}, headers)

    def disqualify_candidate(self, candidate_id, headers):
        return self._request("POST", f"/franchise/candidates/{candidate_id}/disqualify", {}, headers)

    # --- Applications ---
    def create_application(self, candidate_id, payload, headers):
        return self._request("POST", f"/franchise/candidates/{candidate_id}/applications", payload, headers)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/franchise/applications/{application_id}", headers=headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/franchise/applications", headers=headers, params=params)

    def advance_application(self, application_id, headers):
        return self._request("POST", f"/franchise/applications/{application_id}/advance", {}, headers)

    def reject_application(self, application_id, headers):
        return self._request("POST", f"/franchise/applications/{application_id}/reject", {}, headers)

    def withdraw_application(self, application_id, headers):
        return self._request("POST", f"/franchise/applications/{application_id}/withdraw", {}, headers)

    def committee_decision(self, application_id, payload, headers):
        return self._request("POST", f"/franchise/applications/{application_id}/committee-decision", payload, headers)

    # --- Interview rounds ---
    def create_interview(self, application_id, payload, headers):
        return self._request("POST", f"/franchise/applications/{application_id}/interviews", payload, headers)

    def list_interviews_of_application(self, application_id, headers):
        return self._request("GET", f"/franchise/applications/{application_id}/interviews", headers=headers)

    def list_interviews(self, headers, params=None):
        return self._request("GET", "/franchise/interviews", headers=headers, params=params)

    def get_interview(self, round_id, headers):
        return self._request("GET", f"/franchise/interviews/{round_id}", headers=headers)

    def score_interview(self, application_id, round_id, payload, headers):
        return self._request("POST", f"/franchise/applications/{application_id}/interviews/{round_id}/score", payload, headers)

    def cancel_interview(self, application_id, round_id, headers):
        return self._request("POST", f"/franchise/applications/{application_id}/interviews/{round_id}/cancel", {}, headers)

    # --- Business assessment ---
    def create_assessment(self, application_id, payload, headers):
        return self._request("POST", f"/franchise/applications/{application_id}/assessment", payload, headers)

    def get_assessment(self, application_id, headers):
        return self._request("GET", f"/franchise/applications/{application_id}/assessment", headers=headers)

    def get_assessment_by_id(self, assessment_id, headers):
        return self._request("GET", f"/franchise/assessments/{assessment_id}", headers=headers)

    def list_assessments(self, headers, params=None):
        return self._request("GET", "/franchise/assessments", headers=headers, params=params)

    def submit_assessment(self, application_id, headers):
        return self._request("POST", f"/franchise/applications/{application_id}/assessment/submit", {}, headers)

    def evaluate_assessment(self, application_id, headers):
        return self._request("POST", f"/franchise/applications/{application_id}/assessment/evaluate", {}, headers)

    # --- Restaurants ---
    def create_restaurant(self, payload, headers):
        return self._request("POST", "/franchise/restaurants", payload, headers)

    def get_restaurant(self, restaurant_id, headers):
        return self._request("GET", f"/franchise/restaurants/{restaurant_id}", headers=headers)

    def list_restaurants(self, headers, params=None):
        return self._request("GET", "/franchise/restaurants", headers=headers, params=params)

    def make_restaurant_available(self, restaurant_id, headers):
        return self._request("POST", f"/franchise/restaurants/{restaurant_id}/make-available", {}, headers)

    # --- In-restaurant experiences ---
    def create_experience(self, application_id, payload, headers):
        return self._request("POST", f"/franchise/applications/{application_id}/experiences", payload, headers)

    def list_experiences_of_application(self, application_id, headers):
        return self._request("GET", f"/franchise/applications/{application_id}/experiences", headers=headers)

    def list_experiences(self, headers, params=None):
        return self._request("GET", "/franchise/experiences", headers=headers, params=params)

    def get_experience(self, experience_id, headers):
        return self._request("GET", f"/franchise/experiences/{experience_id}", headers=headers)

    def signoff_experience(self, application_id, experience_id, headers):
        return self._request("POST", f"/franchise/applications/{application_id}/experiences/{experience_id}/signoff", {}, headers)

    def complete_experience(self, application_id, experience_id, headers):
        return self._request("POST", f"/franchise/applications/{application_id}/experiences/{experience_id}/complete", {}, headers)

    def cancel_experience(self, application_id, experience_id, headers):
        return self._request("POST", f"/franchise/applications/{application_id}/experiences/{experience_id}/cancel", {}, headers)

    # --- Operators & agreements ---
    def create_operator(self, payload, headers):
        return self._request("POST", "/franchise/operators", payload, headers)

    def get_operator(self, operator_id, headers):
        return self._request("GET", f"/franchise/operators/{operator_id}", headers=headers)

    def list_operators(self, headers, params=None):
        return self._request("GET", "/franchise/operators", headers=headers, params=params)

    def attest_operator(self, operator_id, payload, headers):
        return self._request("POST", f"/franchise/operators/{operator_id}/attest", payload, headers)

    def execute_agreement(self, operator_id, headers):
        return self._request("POST", f"/franchise/operators/{operator_id}/agreement/execute", {}, headers)

    def get_operator_agreement(self, operator_id, headers):
        return self._request("GET", f"/franchise/operators/{operator_id}/agreement", headers=headers)

    def get_agreement(self, agreement_id, headers):
        return self._request("GET", f"/franchise/agreements/{agreement_id}", headers=headers)

    def list_agreements(self, headers, params=None):
        return self._request("GET", "/franchise/agreements", headers=headers, params=params)

    def activate_operator(self, operator_id, headers):
        return self._request("POST", f"/franchise/operators/{operator_id}/activate", {}, headers)

    def suspend_operator(self, operator_id, headers):
        return self._request("POST", f"/franchise/operators/{operator_id}/suspend", {}, headers)

    def reinstate_operator(self, operator_id, headers):
        return self._request("POST", f"/franchise/operators/{operator_id}/reinstate", {}, headers)

    # --- Operating weeks ---
    def create_week(self, restaurant_id, payload, headers):
        return self._request("POST", f"/franchise/restaurants/{restaurant_id}/weeks", payload, headers)

    def list_weeks_of_restaurant(self, restaurant_id, headers, params=None):
        return self._request("GET", f"/franchise/restaurants/{restaurant_id}/weeks", headers=headers, params=params)

    def list_weeks(self, headers, params=None):
        return self._request("GET", "/franchise/weeks", headers=headers, params=params)

    def get_week(self, week_id, headers):
        return self._request("GET", f"/franchise/weeks/{week_id}", headers=headers)

    def close_week(self, restaurant_id, week_id, payload, headers):
        return self._request("POST", f"/franchise/restaurants/{restaurant_id}/weeks/{week_id}/close", payload, headers)

    # --- Scorecards ---
    def create_scorecard(self, operator_id, payload, headers):
        return self._request("POST", f"/franchise/operators/{operator_id}/scorecards", payload, headers)

    def list_scorecards_of_operator(self, operator_id, headers, params=None):
        return self._request("GET", f"/franchise/operators/{operator_id}/scorecards", headers=headers, params=params)

    def list_scorecards(self, headers, params=None):
        return self._request("GET", "/franchise/scorecards", headers=headers, params=params)

    def get_scorecard(self, scorecard_id, headers):
        return self._request("GET", f"/franchise/scorecards/{scorecard_id}", headers=headers)

    def publish_scorecard(self, operator_id, scorecard_id, headers):
        return self._request("POST", f"/franchise/operators/{operator_id}/scorecards/{scorecard_id}/publish", {}, headers)

    def dispute_scorecard(self, operator_id, scorecard_id, headers):
        return self._request("POST", f"/franchise/operators/{operator_id}/scorecards/{scorecard_id}/dispute", {}, headers)

    def republish_scorecard(self, operator_id, scorecard_id, headers):
        return self._request("POST", f"/franchise/operators/{operator_id}/scorecards/{scorecard_id}/republish", {}, headers)

    def finalize_scorecard(self, operator_id, scorecard_id, headers):
        return self._request("POST", f"/franchise/operators/{operator_id}/scorecards/{scorecard_id}/finalize", {}, headers)

    # --- Relocation requests & votes ---
    def create_relocation_request(self, operator_id, payload, headers):
        return self._request("POST", f"/franchise/operators/{operator_id}/relocation-requests", payload, headers)

    def list_relocation_requests_of_operator(self, operator_id, headers):
        return self._request("GET", f"/franchise/operators/{operator_id}/relocation-requests", headers=headers)

    def get_relocation_request(self, request_id, headers):
        return self._request("GET", f"/franchise/relocation-requests/{request_id}", headers=headers)

    def list_relocation_requests(self, headers, params=None):
        return self._request("GET", "/franchise/relocation-requests", headers=headers, params=params)

    def open_relocation_review(self, operator_id, request_id, headers):
        return self._request("POST", f"/franchise/operators/{operator_id}/relocation-requests/{request_id}/open-review", {}, headers)

    def cast_vote(self, operator_id, request_id, payload, headers):
        return self._request("POST", f"/franchise/operators/{operator_id}/relocation-requests/{request_id}/votes", payload, headers)

    def list_votes(self, request_id, headers):
        return self._request("GET", f"/franchise/relocation-requests/{request_id}/votes", headers=headers)

    def list_committee_votes(self, headers, params=None):
        return self._request("GET", "/franchise/committee-votes", headers=headers, params=params)

    def get_committee_vote(self, vote_id, headers):
        return self._request("GET", f"/franchise/committee-votes/{vote_id}", headers=headers)

    def decide_relocation(self, operator_id, request_id, headers):
        return self._request("POST", f"/franchise/operators/{operator_id}/relocation-requests/{request_id}/decide", {}, headers)

    def withdraw_relocation(self, operator_id, request_id, headers):
        return self._request("POST", f"/franchise/operators/{operator_id}/relocation-requests/{request_id}/withdraw", {}, headers)

    # --- Exit cases ---
    def create_exit(self, operator_id, payload, headers):
        return self._request("POST", f"/franchise/operators/{operator_id}/exits", payload, headers)

    def list_exits_of_operator(self, operator_id, headers):
        return self._request("GET", f"/franchise/operators/{operator_id}/exits", headers=headers)

    def get_exit(self, exit_id, headers):
        return self._request("GET", f"/franchise/exits/{exit_id}", headers=headers)

    def list_exits(self, headers, params=None):
        return self._request("GET", "/franchise/exits", headers=headers, params=params)

    def propose_successor(self, operator_id, exit_id, payload, headers):
        return self._request("POST", f"/franchise/operators/{operator_id}/exits/{exit_id}/propose-successor", payload, headers)

    def approve_successor(self, operator_id, exit_id, headers):
        return self._request("POST", f"/franchise/operators/{operator_id}/exits/{exit_id}/approve-successor", {}, headers)

    def reject_successor(self, operator_id, exit_id, headers):
        return self._request("POST", f"/franchise/operators/{operator_id}/exits/{exit_id}/reject-successor", {}, headers)

    def complete_exit(self, operator_id, exit_id, headers):
        return self._request("POST", f"/franchise/operators/{operator_id}/exits/{exit_id}/complete", {}, headers)

    def cancel_exit(self, operator_id, exit_id, headers):
        return self._request("POST", f"/franchise/operators/{operator_id}/exits/{exit_id}/cancel", {}, headers)

    # --- Revenue share statements ---
    def list_statements_of_operator(self, operator_id, headers, params=None):
        return self._request("GET", f"/franchise/operators/{operator_id}/statements", headers=headers, params=params)

    def get_statement(self, statement_id, headers):
        return self._request("GET", f"/franchise/statements/{statement_id}", headers=headers)

    def list_statements(self, headers, params=None):
        return self._request("GET", "/franchise/statements", headers=headers, params=params)

    def settle_statement(self, statement_id, headers):
        return self._request("POST", f"/franchise/statements/{statement_id}/settle", {}, headers)

    def void_statement(self, statement_id, headers):
        return self._request("POST", f"/franchise/statements/{statement_id}/void", {}, headers)

    def finalize_statement(self, statement_id, headers):
        return self._request("POST", f"/franchise/statements/{statement_id}/finalize", {}, headers)


api_client = ApiClient()
