"""API client: one method per endpoint defined in the PRD.

All business resources are mounted under the /evaluation prefix. The single
exception is the platform-level logical-clock endpoint, which lives at the
server root (POST /_clock/set_current_utc) — deliberately outside the prefix.
"""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/evaluation"


class ApiClient(GenericApiClient):
    # --- Contracts ---
    def create_contract(self, payload, headers):
        return self._request("POST", f"{PREFIX}/contracts", payload, headers)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"{PREFIX}/contracts/{contract_id}", headers=headers)

    def terminate_contract(self, contract_id, payload, headers):
        return self._request("POST", f"{PREFIX}/contracts/{contract_id}/terminate", payload, headers)

    def closeout_contract(self, contract_id, headers):
        return self._request("POST", f"{PREFIX}/contracts/{contract_id}/closeout", headers=headers)

    # --- Studies ---
    def create_study(self, contract_id, payload, headers):
        return self._request("POST", f"{PREFIX}/contracts/{contract_id}/studies", payload, headers)

    def list_studies(self, contract_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/contracts/{contract_id}/studies", headers=headers, params=params)

    def get_study(self, study_id, headers):
        return self._request("GET", f"{PREFIX}/studies/{study_id}", headers=headers)

    # --- Design plans ---
    def create_design_plan(self, study_id, payload, headers):
        return self._request("POST", f"{PREFIX}/studies/{study_id}/design-plans", payload, headers)

    def list_design_plans(self, study_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/studies/{study_id}/design-plans", headers=headers, params=params)

    def submit_design_plan(self, plan_id, headers):
        return self._request("POST", f"{PREFIX}/design-plans/{plan_id}/submit", headers=headers)

    def design_plan_agency_decision(self, plan_id, payload, headers):
        return self._request("POST", f"{PREFIX}/design-plans/{plan_id}/agency-decision", payload, headers)

    def revise_design_plan(self, plan_id, headers):
        return self._request("POST", f"{PREFIX}/design-plans/{plan_id}/revise", headers=headers)

    # --- IRB protocols ---
    def create_irb_protocol(self, study_id, payload, headers):
        return self._request("POST", f"{PREFIX}/studies/{study_id}/irb-protocols", payload, headers)

    def list_irb_protocols(self, study_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/studies/{study_id}/irb-protocols", headers=headers, params=params)

    def submit_irb_protocol(self, irb_id, headers):
        return self._request("POST", f"{PREFIX}/irb-protocols/{irb_id}/submit", headers=headers)

    def irb_decision(self, irb_id, payload, headers):
        return self._request("POST", f"{PREFIX}/irb-protocols/{irb_id}/decision", payload, headers)

    def irb_continuing_review(self, irb_id, payload, headers):
        return self._request("POST", f"{PREFIX}/irb-protocols/{irb_id}/continuing-review", payload, headers)

    # --- Sites ---
    def create_site(self, study_id, payload, headers):
        return self._request("POST", f"{PREFIX}/studies/{study_id}/sites", payload, headers)

    def list_sites(self, study_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/studies/{study_id}/sites", headers=headers, params=params)

    def site_outreach(self, site_id, payload, headers):
        return self._request("POST", f"{PREFIX}/sites/{site_id}/outreach", payload, headers)

    def sign_mou(self, site_id, headers):
        return self._request("POST", f"{PREFIX}/sites/{site_id}/sign-mou", headers=headers)

    def activate_site(self, site_id, headers):
        return self._request("POST", f"{PREFIX}/sites/{site_id}/activate", headers=headers)

    def withdraw_site(self, site_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/sites/{site_id}/withdraw", payload, headers)

    # --- Participants ---
    def create_participant(self, site_id, payload, headers):
        return self._request("POST", f"{PREFIX}/sites/{site_id}/participants", payload, headers)

    def list_participants(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/participants", headers=headers, params=params)

    def get_participant(self, participant_id, headers):
        return self._request("GET", f"{PREFIX}/participants/{participant_id}", headers=headers)

    def consent_participant(self, participant_id, payload, headers):
        return self._request("POST", f"{PREFIX}/participants/{participant_id}/consent", payload, headers)

    def randomize_participant(self, participant_id, headers):
        return self._request("POST", f"{PREFIX}/participants/{participant_id}/randomize", headers=headers)

    def withdraw_participant(self, participant_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/participants/{participant_id}/withdraw", payload, headers)

    # --- Data collection waves ---
    def create_wave(self, study_id, payload, headers):
        return self._request("POST", f"{PREFIX}/studies/{study_id}/waves", payload, headers)

    def list_study_waves(self, study_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/studies/{study_id}/waves", headers=headers, params=params)

    def list_waves(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/waves", headers=headers, params=params)

    def get_wave(self, wave_id, headers):
        return self._request("GET", f"{PREFIX}/waves/{wave_id}", headers=headers)

    def open_wave(self, wave_id, headers):
        return self._request("POST", f"{PREFIX}/waves/{wave_id}/open", headers=headers)

    def close_wave(self, wave_id, headers):
        return self._request("POST", f"{PREFIX}/waves/{wave_id}/close", headers=headers)

    def link_wave(self, wave_id, headers):
        return self._request("POST", f"{PREFIX}/waves/{wave_id}/link", headers=headers)

    # --- Response records ---
    def create_record(self, wave_id, payload, headers):
        return self._request("POST", f"{PREFIX}/waves/{wave_id}/records", payload, headers)

    def list_wave_records(self, wave_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/waves/{wave_id}/records", headers=headers, params=params)

    def list_participant_records(self, participant_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/participants/{participant_id}/records", headers=headers, params=params)

    # --- Analysis plans ---
    def create_analysis_plan(self, study_id, payload, headers):
        return self._request("POST", f"{PREFIX}/studies/{study_id}/analysis-plans", payload, headers)

    def list_analysis_plans(self, study_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/studies/{study_id}/analysis-plans", headers=headers, params=params)

    def register_analysis_plan(self, plan_id, headers):
        return self._request("POST", f"{PREFIX}/analysis-plans/{plan_id}/register", headers=headers)

    def amend_analysis_plan(self, plan_id, payload, headers):
        return self._request("POST", f"{PREFIX}/analysis-plans/{plan_id}/amend", payload, headers)

    # --- Findings reports ---
    def create_report(self, study_id, payload, headers):
        return self._request("POST", f"{PREFIX}/studies/{study_id}/reports", payload, headers)

    def list_reports(self, study_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/studies/{study_id}/reports", headers=headers, params=params)

    def submit_report(self, report_id, headers):
        return self._request("POST", f"{PREFIX}/reports/{report_id}/submit", headers=headers)

    def review_report(self, report_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/reports/{report_id}/review", payload, headers)

    def report_agency_decision(self, report_id, payload, headers):
        return self._request("POST", f"{PREFIX}/reports/{report_id}/agency-decision", payload, headers)

    def publish_report(self, report_id, headers):
        return self._request("POST", f"{PREFIX}/reports/{report_id}/publish", headers=headers)

    # --- Restricted-use files ---
    def create_restricted_use_file(self, study_id, payload, headers):
        return self._request("POST", f"{PREFIX}/studies/{study_id}/restricted-use-files", payload, headers)

    def list_restricted_use_files(self, study_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/studies/{study_id}/restricted-use-files", headers=headers, params=params)

    def submit_ruf_review(self, file_id, headers):
        return self._request("POST", f"{PREFIX}/restricted-use-files/{file_id}/submit-review", headers=headers)

    def ruf_review_decision(self, file_id, payload, headers):
        return self._request("POST", f"{PREFIX}/restricted-use-files/{file_id}/review-decision", payload, headers)

    # --- Dissemination activities ---
    def create_dissemination_activity(self, study_id, payload, headers):
        return self._request("POST", f"{PREFIX}/studies/{study_id}/dissemination-activities", payload, headers)

    def list_dissemination_activities(self, study_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/studies/{study_id}/dissemination-activities", headers=headers, params=params)

    def complete_dissemination_activity(self, activity_id, headers):
        return self._request("POST", f"{PREFIX}/dissemination-activities/{activity_id}/complete", headers=headers)

    # --- Platform logical clock (OUTSIDE the /evaluation prefix) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
