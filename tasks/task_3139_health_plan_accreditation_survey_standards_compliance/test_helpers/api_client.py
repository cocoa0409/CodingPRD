"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/accreditation/_clock/set_current_utc", payload, headers)

    # --- standards editions & elements ---
    def create_standards_edition(self, payload, headers):
        return self._request("POST", "/accreditation/standards-editions", payload, headers)

    def list_standards_editions(self, headers, params=None):
        return self._request("GET", "/accreditation/standards-editions", headers=headers, params=params)

    def get_standards_edition(self, edition_id, headers):
        return self._request("GET", f"/accreditation/standards-editions/{edition_id}", headers=headers)

    def publish_standards_edition(self, edition_id, headers):
        return self._request("POST", f"/accreditation/standards-editions/{edition_id}/publish", {}, headers)

    def supersede_standards_edition(self, edition_id, payload, headers):
        return self._request("POST", f"/accreditation/standards-editions/{edition_id}/supersede", payload, headers)

    def create_standard_element(self, edition_id, payload, headers):
        return self._request("POST", f"/accreditation/standards-editions/{edition_id}/standard-elements", payload, headers)

    def list_standard_elements(self, edition_id, headers, params=None):
        return self._request("GET", f"/accreditation/standards-editions/{edition_id}/standard-elements", headers=headers, params=params)

    def list_standard_elements_flat(self, headers, params=None):
        return self._request("GET", "/accreditation/standard-elements", headers=headers, params=params)

    def get_standard_element(self, element_id, headers):
        return self._request("GET", f"/accreditation/standard-elements/{element_id}", headers=headers)

    # --- health plans & scopes ---
    def create_health_plan(self, payload, headers):
        return self._request("POST", "/accreditation/health-plans", payload, headers)

    def list_health_plans(self, headers, params=None):
        return self._request("GET", "/accreditation/health-plans", headers=headers, params=params)

    def get_health_plan(self, plan_id, headers):
        return self._request("GET", f"/accreditation/health-plans/{plan_id}", headers=headers)

    def retire_health_plan(self, plan_id, headers):
        return self._request("POST", f"/accreditation/health-plans/{plan_id}/retire", {}, headers)

    def create_product_line_scope(self, plan_id, payload, headers):
        return self._request("POST", f"/accreditation/health-plans/{plan_id}/product-line-scopes", payload, headers)

    def list_product_line_scopes(self, plan_id, headers, params=None):
        return self._request("GET", f"/accreditation/health-plans/{plan_id}/product-line-scopes", headers=headers, params=params)

    def list_product_line_scopes_flat(self, headers, params=None):
        return self._request("GET", "/accreditation/product-line-scopes", headers=headers, params=params)

    def get_product_line_scope(self, scope_id, headers):
        return self._request("GET", f"/accreditation/product-line-scopes/{scope_id}", headers=headers)

    # --- surveyors ---
    def create_surveyor(self, payload, headers):
        return self._request("POST", "/accreditation/surveyors", payload, headers)

    def list_surveyors(self, headers, params=None):
        return self._request("GET", "/accreditation/surveyors", headers=headers, params=params)

    def get_surveyor(self, surveyor_id, headers):
        return self._request("GET", f"/accreditation/surveyors/{surveyor_id}", headers=headers)

    def list_surveyor_sessions(self, surveyor_id, headers, params=None):
        return self._request("GET", f"/accreditation/surveyors/{surveyor_id}/sessions", headers=headers, params=params)

    # --- applications ---
    def create_application(self, plan_id, payload, headers):
        return self._request("POST", f"/accreditation/health-plans/{plan_id}/applications", payload, headers)

    def list_applications_of_plan(self, plan_id, headers, params=None):
        return self._request("GET", f"/accreditation/health-plans/{plan_id}/applications", headers=headers, params=params)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/accreditation/applications", headers=headers, params=params)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/accreditation/applications/{application_id}", headers=headers)

    def submit_application(self, application_id, payload, headers):
        return self._request("POST", f"/accreditation/applications/{application_id}/submit", payload, headers)

    def begin_evidence_review(self, application_id, headers):
        return self._request("POST", f"/accreditation/applications/{application_id}/begin-evidence-review", {}, headers)

    def advance_to_survey_scheduling(self, application_id, headers):
        return self._request("POST", f"/accreditation/applications/{application_id}/advance-to-survey-scheduling", {}, headers)

    def withdraw_application(self, application_id, headers):
        return self._request("POST", f"/accreditation/applications/{application_id}/withdraw", {}, headers)

    # --- evidence items ---
    def create_evidence_item(self, application_id, payload, headers):
        return self._request("POST", f"/accreditation/applications/{application_id}/evidence-items", payload, headers)

    def list_evidence_items_of_application(self, application_id, headers, params=None):
        return self._request("GET", f"/accreditation/applications/{application_id}/evidence-items", headers=headers, params=params)

    def list_evidence_items(self, headers, params=None):
        return self._request("GET", "/accreditation/evidence-items", headers=headers, params=params)

    def get_evidence_item(self, evidence_item_id, headers):
        return self._request("GET", f"/accreditation/evidence-items/{evidence_item_id}", headers=headers)

    def accept_evidence_item(self, evidence_item_id, payload, headers):
        return self._request("POST", f"/accreditation/evidence-items/{evidence_item_id}/accept", payload, headers)

    def reject_evidence_item(self, evidence_item_id, payload, headers):
        return self._request("POST", f"/accreditation/evidence-items/{evidence_item_id}/reject", payload, headers)

    def resubmit_evidence_item(self, evidence_item_id, payload, headers):
        return self._request("POST", f"/accreditation/evidence-items/{evidence_item_id}/resubmit", payload, headers)

    # --- file review samples & cases ---
    def create_file_review_sample(self, application_id, payload, headers):
        return self._request("POST", f"/accreditation/applications/{application_id}/file-review-samples", payload, headers)

    def list_file_review_samples_of_application(self, application_id, headers, params=None):
        return self._request("GET", f"/accreditation/applications/{application_id}/file-review-samples", headers=headers, params=params)

    def list_file_review_samples(self, headers, params=None):
        return self._request("GET", "/accreditation/file-review-samples", headers=headers, params=params)

    def get_file_review_sample(self, sample_id, headers):
        return self._request("GET", f"/accreditation/file-review-samples/{sample_id}", headers=headers)

    def create_file_review_case(self, sample_id, payload, headers):
        return self._request("POST", f"/accreditation/file-review-samples/{sample_id}/cases", payload, headers)

    def list_file_review_cases(self, sample_id, headers, params=None):
        return self._request("GET", f"/accreditation/file-review-samples/{sample_id}/cases", headers=headers, params=params)

    def list_file_review_cases_flat(self, headers, params=None):
        return self._request("GET", "/accreditation/file-review-cases", headers=headers, params=params)

    def get_file_review_case(self, case_id, headers):
        return self._request("GET", f"/accreditation/file-review-cases/{case_id}", headers=headers)

    def submit_file_review_sample(self, sample_id, headers):
        return self._request("POST", f"/accreditation/file-review-samples/{sample_id}/submit", {}, headers)

    def score_file_review_sample(self, sample_id, headers):
        return self._request("POST", f"/accreditation/file-review-samples/{sample_id}/score", {}, headers)

    # --- surveys & sessions ---
    def create_survey(self, application_id, payload, headers):
        return self._request("POST", f"/accreditation/applications/{application_id}/surveys", payload, headers)

    def list_surveys_of_application(self, application_id, headers, params=None):
        return self._request("GET", f"/accreditation/applications/{application_id}/surveys", headers=headers, params=params)

    def list_surveys(self, headers, params=None):
        return self._request("GET", "/accreditation/surveys", headers=headers, params=params)

    def get_survey(self, survey_id, headers):
        return self._request("GET", f"/accreditation/surveys/{survey_id}", headers=headers)

    def confirm_survey(self, survey_id, headers):
        return self._request("POST", f"/accreditation/surveys/{survey_id}/confirm", {}, headers)

    def complete_survey(self, survey_id, headers):
        return self._request("POST", f"/accreditation/surveys/{survey_id}/complete", {}, headers)

    def cancel_survey(self, survey_id, headers):
        return self._request("POST", f"/accreditation/surveys/{survey_id}/cancel", {}, headers)

    def create_survey_session(self, survey_id, payload, headers):
        return self._request("POST", f"/accreditation/surveys/{survey_id}/sessions", payload, headers)

    def list_survey_sessions(self, survey_id, headers, params=None):
        return self._request("GET", f"/accreditation/surveys/{survey_id}/sessions", headers=headers, params=params)

    def list_survey_sessions_flat(self, headers, params=None):
        return self._request("GET", "/accreditation/survey-sessions", headers=headers, params=params)

    def get_survey_session(self, session_id, headers):
        return self._request("GET", f"/accreditation/survey-sessions/{session_id}", headers=headers)

    def complete_survey_session(self, session_id, headers):
        return self._request("POST", f"/accreditation/survey-sessions/{session_id}/complete", {}, headers)

    def cancel_survey_session(self, session_id, headers):
        return self._request("POST", f"/accreditation/survey-sessions/{session_id}/cancel", {}, headers)

    def reschedule_survey_session(self, session_id, payload, headers):
        return self._request("POST", f"/accreditation/survey-sessions/{session_id}/reschedule", payload, headers)

    # --- surveyor questions ---
    def create_surveyor_question(self, session_id, payload, headers):
        return self._request("POST", f"/accreditation/survey-sessions/{session_id}/questions", payload, headers)

    def list_surveyor_questions_of_session(self, session_id, headers, params=None):
        return self._request("GET", f"/accreditation/survey-sessions/{session_id}/questions", headers=headers, params=params)

    def list_surveyor_questions(self, headers, params=None):
        return self._request("GET", "/accreditation/surveyor-questions", headers=headers, params=params)

    def get_surveyor_question(self, question_id, headers):
        return self._request("GET", f"/accreditation/surveyor-questions/{question_id}", headers=headers)

    def adjudicate_surveyor_question(self, question_id, payload, headers):
        return self._request("POST", f"/accreditation/surveyor-questions/{question_id}/adjudicate", payload, headers)

    # --- element scores ---
    def create_element_score(self, application_id, payload, headers):
        return self._request("POST", f"/accreditation/applications/{application_id}/element-scores", payload, headers)

    def list_element_scores_of_application(self, application_id, headers, params=None):
        return self._request("GET", f"/accreditation/applications/{application_id}/element-scores", headers=headers, params=params)

    def list_element_scores(self, headers, params=None):
        return self._request("GET", "/accreditation/element-scores", headers=headers, params=params)

    def get_element_score(self, score_id, headers):
        return self._request("GET", f"/accreditation/element-scores/{score_id}", headers=headers)

    def finalize_element_score(self, score_id, headers):
        return self._request("POST", f"/accreditation/element-scores/{score_id}/finalize", {}, headers)

    def void_element_score(self, score_id, headers):
        return self._request("POST", f"/accreditation/element-scores/{score_id}/void", {}, headers)

    # --- quality measures & consumer survey scores ---
    def create_quality_measure_result(self, scope_id, payload, headers):
        return self._request("POST", f"/accreditation/product-line-scopes/{scope_id}/quality-measure-results", payload, headers)

    def list_quality_measure_results_of_scope(self, scope_id, headers, params=None):
        return self._request("GET", f"/accreditation/product-line-scopes/{scope_id}/quality-measure-results", headers=headers, params=params)

    def list_quality_measure_results(self, headers, params=None):
        return self._request("GET", "/accreditation/quality-measure-results", headers=headers, params=params)

    def get_quality_measure_result(self, result_id, headers):
        return self._request("GET", f"/accreditation/quality-measure-results/{result_id}", headers=headers)

    def create_consumer_survey_score(self, scope_id, payload, headers):
        return self._request("POST", f"/accreditation/product-line-scopes/{scope_id}/consumer-survey-scores", payload, headers)

    def list_consumer_survey_scores_of_scope(self, scope_id, headers, params=None):
        return self._request("GET", f"/accreditation/product-line-scopes/{scope_id}/consumer-survey-scores", headers=headers, params=params)

    def list_consumer_survey_scores(self, headers, params=None):
        return self._request("GET", "/accreditation/consumer-survey-scores", headers=headers, params=params)

    def get_consumer_survey_score(self, score_id, headers):
        return self._request("GET", f"/accreditation/consumer-survey-scores/{score_id}", headers=headers)

    # --- corrective action plans ---
    def create_corrective_action_plan(self, application_id, payload, headers):
        return self._request("POST", f"/accreditation/applications/{application_id}/corrective-action-plans", payload, headers)

    def list_corrective_action_plans_of_application(self, application_id, headers, params=None):
        return self._request("GET", f"/accreditation/applications/{application_id}/corrective-action-plans", headers=headers, params=params)

    def list_corrective_action_plans(self, headers, params=None):
        return self._request("GET", "/accreditation/corrective-action-plans", headers=headers, params=params)

    def get_corrective_action_plan(self, cap_id, headers):
        return self._request("GET", f"/accreditation/corrective-action-plans/{cap_id}", headers=headers)

    def submit_cap_evidence(self, cap_id, payload, headers):
        return self._request("POST", f"/accreditation/corrective-action-plans/{cap_id}/submit-evidence", payload, headers)

    def verify_corrective_action_plan(self, cap_id, payload, headers):
        return self._request("POST", f"/accreditation/corrective-action-plans/{cap_id}/verify", payload, headers)

    # --- outcomes & public display ---
    def create_outcome(self, application_id, headers):
        return self._request("POST", f"/accreditation/applications/{application_id}/outcome", {}, headers)

    def get_application_outcome(self, application_id, headers):
        return self._request("GET", f"/accreditation/applications/{application_id}/outcome", headers=headers)

    def list_outcomes(self, headers, params=None):
        return self._request("GET", "/accreditation/outcomes", headers=headers, params=params)

    def get_outcome(self, outcome_id, headers):
        return self._request("GET", f"/accreditation/outcomes/{outcome_id}", headers=headers)

    def revise_outcome(self, outcome_id, headers):
        return self._request("POST", f"/accreditation/outcomes/{outcome_id}/revise", {}, headers)

    def publish_outcome(self, outcome_id, headers):
        return self._request("POST", f"/accreditation/outcomes/{outcome_id}/publish", {}, headers)

    def get_public_accreditation_status(self, plan_id, headers):
        return self._request("GET", f"/accreditation/public/plans/{plan_id}/accreditation-status", headers=headers)

    # --- annual reports ---
    def create_annual_report(self, application_id, payload, headers):
        return self._request("POST", f"/accreditation/applications/{application_id}/annual-reports", payload, headers)

    def list_annual_reports_of_application(self, application_id, headers, params=None):
        return self._request("GET", f"/accreditation/applications/{application_id}/annual-reports", headers=headers, params=params)

    def list_annual_reports(self, headers, params=None):
        return self._request("GET", "/accreditation/annual-reports", headers=headers, params=params)

    def get_annual_report(self, report_id, headers):
        return self._request("GET", f"/accreditation/annual-reports/{report_id}", headers=headers)

    def submit_annual_report(self, report_id, headers):
        return self._request("POST", f"/accreditation/annual-reports/{report_id}/submit", {}, headers)

    def review_annual_report(self, report_id, payload, headers):
        return self._request("POST", f"/accreditation/annual-reports/{report_id}/review", payload, headers)

    def reopen_annual_report(self, report_id, headers):
        return self._request("POST", f"/accreditation/annual-reports/{report_id}/reopen", {}, headers)


api_client = ApiClient()
