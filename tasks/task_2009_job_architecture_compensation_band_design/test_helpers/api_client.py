"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- CompProgram ----
    def create_program(self, payload, headers):
        return self._request("POST", "/comp/programs", payload, headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", "/comp/programs", headers=headers, params=params)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/comp/programs/{program_id}", headers=headers)

    def patch_program(self, program_id, payload, headers):
        return self._request("PATCH", f"/comp/programs/{program_id}", payload, headers)

    def transition_program(self, program_id, payload, headers):
        return self._request("POST", f"/comp/programs/{program_id}/transition", payload, headers)

    # ---- JobFamily ----
    def create_job_family(self, payload, headers):
        return self._request("POST", "/comp/job-families", payload, headers)

    def list_job_families(self, headers, params=None):
        return self._request("GET", "/comp/job-families", headers=headers, params=params)

    def get_job_family(self, family_id, headers):
        return self._request("GET", f"/comp/job-families/{family_id}", headers=headers)

    def retire_job_family(self, family_id, headers):
        return self._request("POST", f"/comp/job-families/{family_id}/retire", {}, headers)

    # ---- JobLevel ----
    def create_job_level(self, payload, headers):
        return self._request("POST", "/comp/job-levels", payload, headers)

    def list_job_levels(self, headers, params=None):
        return self._request("GET", "/comp/job-levels", headers=headers, params=params)

    def get_job_level(self, level_id, headers):
        return self._request("GET", f"/comp/job-levels/{level_id}", headers=headers)

    # ---- GeoZone ----
    def create_geo_zone(self, payload, headers):
        return self._request("POST", "/comp/geo-zones", payload, headers)

    def patch_geo_zone(self, zone_id, payload, headers):
        return self._request("PATCH", f"/comp/geo-zones/{zone_id}", payload, headers)

    def list_geo_zones(self, headers, params=None):
        return self._request("GET", "/comp/geo-zones", headers=headers, params=params)

    def get_geo_zone(self, zone_id, headers):
        return self._request("GET", f"/comp/geo-zones/{zone_id}", headers=headers)

    # ---- JobProfile ----
    def create_job_profile(self, payload, headers):
        return self._request("POST", "/comp/job-profiles", payload, headers)

    def list_job_profiles(self, headers, params=None):
        return self._request("GET", "/comp/job-profiles", headers=headers, params=params)

    def get_job_profile(self, profile_id, headers):
        return self._request("GET", f"/comp/job-profiles/{profile_id}", headers=headers)

    def determine_flsa(self, profile_id, headers):
        return self._request("POST", f"/comp/job-profiles/{profile_id}/determine-flsa", {}, headers)

    def submit_job_profile(self, profile_id, headers):
        return self._request("POST", f"/comp/job-profiles/{profile_id}/submit", {}, headers)

    def approve_job_profile(self, profile_id, headers):
        return self._request("POST", f"/comp/job-profiles/{profile_id}/approve", {}, headers)

    def return_job_profile(self, profile_id, payload, headers):
        return self._request("POST", f"/comp/job-profiles/{profile_id}/return", payload, headers)

    def revise_job_profile(self, profile_id, payload, headers):
        return self._request("POST", f"/comp/job-profiles/{profile_id}/revise", payload, headers)

    def retire_job_profile(self, profile_id, headers):
        return self._request("POST", f"/comp/job-profiles/{profile_id}/retire", {}, headers)

    # ---- MarketSurvey ----
    def create_market_survey(self, payload, headers):
        return self._request("POST", "/comp/market-surveys", payload, headers)

    def list_market_surveys(self, headers, params=None):
        return self._request("GET", "/comp/market-surveys", headers=headers, params=params)

    def get_market_survey(self, survey_id, headers):
        return self._request("GET", f"/comp/market-surveys/{survey_id}", headers=headers)

    def accept_market_survey(self, survey_id, headers):
        return self._request("POST", f"/comp/market-surveys/{survey_id}/accept", {}, headers)

    def reject_market_survey(self, survey_id, headers):
        return self._request("POST", f"/comp/market-surveys/{survey_id}/reject", {}, headers)

    # ---- MarketCut ----
    def create_market_cut(self, payload, headers):
        return self._request("POST", "/comp/market-cuts", payload, headers)

    def list_market_cuts(self, headers, params=None):
        return self._request("GET", "/comp/market-cuts", headers=headers, params=params)

    def get_market_cut(self, cut_id, headers):
        return self._request("GET", f"/comp/market-cuts/{cut_id}", headers=headers)

    def set_cut_exclusion(self, cut_id, payload, headers):
        return self._request("POST", f"/comp/market-cuts/{cut_id}/set-exclusion", payload, headers)

    # ---- ProgressionPolicy ----
    def create_progression_policy(self, payload, headers):
        return self._request("POST", "/comp/progression-policies", payload, headers)

    def list_progression_policies(self, headers, params=None):
        return self._request("GET", "/comp/progression-policies", headers=headers, params=params)

    def get_progression_policy(self, policy_id, headers):
        return self._request("GET", f"/comp/progression-policies/{policy_id}", headers=headers)

    # ---- PayBand ----
    def create_pay_band(self, payload, headers):
        return self._request("POST", "/comp/pay-bands", payload, headers)

    def list_pay_bands(self, headers, params=None):
        return self._request("GET", "/comp/pay-bands", headers=headers, params=params)

    def get_pay_band(self, band_id, headers):
        return self._request("GET", f"/comp/pay-bands/{band_id}", headers=headers)

    def price_pay_band(self, band_id, payload, headers):
        return self._request("POST", f"/comp/pay-bands/{band_id}/price", payload, headers)

    def approve_pay_band(self, band_id, headers):
        return self._request("POST", f"/comp/pay-bands/{band_id}/approve", {}, headers)

    def publish_pay_band(self, band_id, headers):
        return self._request("POST", f"/comp/pay-bands/{band_id}/publish", {}, headers)

    def reopen_pay_band(self, band_id, headers):
        return self._request("POST", f"/comp/pay-bands/{band_id}/reopen", {}, headers)

    def get_overlap_report(self, band_id, headers):
        return self._request("GET", f"/comp/pay-bands/{band_id}/overlap-report", headers=headers)

    # ---- Department ----
    def create_department(self, payload, headers):
        return self._request("POST", "/comp/departments", payload, headers)

    def list_departments(self, headers, params=None):
        return self._request("GET", "/comp/departments", headers=headers, params=params)

    def get_department(self, department_id, headers):
        return self._request("GET", f"/comp/departments/{department_id}", headers=headers)

    # ---- Employee ----
    def create_employee(self, payload, headers):
        return self._request("POST", "/comp/employees", payload, headers)

    def list_employees(self, headers, params=None):
        return self._request("GET", "/comp/employees", headers=headers, params=params)

    def get_employee(self, employee_id, headers):
        return self._request("GET", f"/comp/employees/{employee_id}", headers=headers)

    def patch_employee(self, employee_id, payload, headers):
        return self._request("PATCH", f"/comp/employees/{employee_id}", payload, headers)

    def terminate_employee(self, employee_id, headers):
        return self._request("POST", f"/comp/employees/{employee_id}/terminate", {}, headers)

    # ---- MappingDecision ----
    def create_mapping_decision(self, payload, headers):
        return self._request("POST", "/comp/mapping-decisions", payload, headers)

    def list_mapping_decisions(self, headers, params=None):
        return self._request("GET", "/comp/mapping-decisions", headers=headers, params=params)

    def get_mapping_decision(self, decision_id, headers):
        return self._request("GET", f"/comp/mapping-decisions/{decision_id}", headers=headers)

    def submit_mapping_decision(self, decision_id, headers):
        return self._request("POST", f"/comp/mapping-decisions/{decision_id}/submit", {}, headers)

    def hrbp_review_mapping_decision(self, decision_id, headers):
        return self._request("POST", f"/comp/mapping-decisions/{decision_id}/hrbp-review", {}, headers)

    def comp_triage_mapping_decision(self, decision_id, headers):
        return self._request("POST", f"/comp/mapping-decisions/{decision_id}/comp-triage", {}, headers)

    def approve_mapping_decision(self, decision_id, payload, headers):
        return self._request("POST", f"/comp/mapping-decisions/{decision_id}/approve", payload, headers)

    def reject_mapping_decision(self, decision_id, payload, headers):
        return self._request("POST", f"/comp/mapping-decisions/{decision_id}/reject", payload, headers)

    def return_mapping_decision(self, decision_id, payload, headers):
        return self._request("POST", f"/comp/mapping-decisions/{decision_id}/return", payload, headers)

    def resubmit_mapping_decision(self, decision_id, headers):
        return self._request("POST", f"/comp/mapping-decisions/{decision_id}/resubmit", {}, headers)

    def withdraw_mapping_decision(self, decision_id, headers):
        return self._request("POST", f"/comp/mapping-decisions/{decision_id}/withdraw", {}, headers)

    def reverse_mapping_decision(self, decision_id, headers):
        return self._request("POST", f"/comp/mapping-decisions/{decision_id}/reverse", {}, headers)

    # ---- ExceptionRequest ----
    def create_exception_request(self, payload, headers):
        return self._request("POST", "/comp/exception-requests", payload, headers)

    def list_exception_requests(self, headers, params=None):
        return self._request("GET", "/comp/exception-requests", headers=headers, params=params)

    def get_exception_request(self, request_id, headers):
        return self._request("GET", f"/comp/exception-requests/{request_id}", headers=headers)

    def hrbp_pass_exception_request(self, request_id, headers):
        return self._request("POST", f"/comp/exception-requests/{request_id}/hrbp-pass", {}, headers)

    def comp_pass_exception_request(self, request_id, headers):
        return self._request("POST", f"/comp/exception-requests/{request_id}/comp-pass", {}, headers)

    def finance_pass_exception_request(self, request_id, headers):
        return self._request("POST", f"/comp/exception-requests/{request_id}/finance-pass", {}, headers)

    def deny_exception_request(self, request_id, payload, headers):
        return self._request("POST", f"/comp/exception-requests/{request_id}/deny", payload, headers)

    def return_exception_request(self, request_id, payload, headers):
        return self._request("POST", f"/comp/exception-requests/{request_id}/return", payload, headers)

    def resubmit_exception_request(self, request_id, headers):
        return self._request("POST", f"/comp/exception-requests/{request_id}/resubmit", {}, headers)

    def rescind_exception_request(self, request_id, headers):
        return self._request("POST", f"/comp/exception-requests/{request_id}/rescind", {}, headers)

    # ---- RefreshCycle ----
    def create_refresh_cycle(self, payload, headers):
        return self._request("POST", "/comp/refresh-cycles", payload, headers)

    def list_refresh_cycles(self, headers, params=None):
        return self._request("GET", "/comp/refresh-cycles", headers=headers, params=params)

    def get_refresh_cycle(self, cycle_id, headers):
        return self._request("GET", f"/comp/refresh-cycles/{cycle_id}", headers=headers)

    def compute_refresh_impact(self, cycle_id, headers):
        return self._request("POST", f"/comp/refresh-cycles/{cycle_id}/compute-impact", {}, headers)

    def approve_refresh_cycle(self, cycle_id, headers):
        return self._request("POST", f"/comp/refresh-cycles/{cycle_id}/approve", {}, headers)

    def apply_refresh_cycle(self, cycle_id, payload, headers):
        return self._request("POST", f"/comp/refresh-cycles/{cycle_id}/apply", payload, headers)

    def cancel_refresh_cycle(self, cycle_id, headers):
        return self._request("POST", f"/comp/refresh-cycles/{cycle_id}/cancel", {}, headers)

    # ---- Logical clock ----
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/comp/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
