"""API client: one method per endpoint defined in the PRD.

All business endpoints live under the /survey prefix. The single exception is
the logical-clock control, which is mounted unprefixed at /_clock/set_current_utc.
"""
from prd_bench_local_runner.testing import GenericApiClient

SURVEY_PREFIX = "/survey"
CLOCK_PATH = "/_clock/set_current_utc"  # intentionally NOT under /survey


class ApiClient(GenericApiClient):
    # -- Logical clock (unprefixed, ProgramAdmin-only) ----------------------
    def set_clock(self, payload, headers):
        return self._request("POST", CLOCK_PATH, payload, headers)

    # -- Survey programs ----------------------------------------------------
    def create_program(self, payload, headers):
        return self._request("POST", f"{SURVEY_PREFIX}/programs", payload, headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", f"{SURVEY_PREFIX}/programs", headers=headers, params=params)

    # -- Sample frames ------------------------------------------------------
    def create_sample_frame(self, payload, headers):
        return self._request("POST", f"{SURVEY_PREFIX}/sample-frames", payload, headers)

    def get_sample_frame(self, frame_id, headers):
        return self._request("GET", f"{SURVEY_PREFIX}/sample-frames/{frame_id}", headers=headers)

    def freeze_sample_frame(self, frame_id, headers, payload=None):
        return self._request("POST", f"{SURVEY_PREFIX}/sample-frames/{frame_id}/freeze",
                             payload or {}, headers)

    # -- Establishments -----------------------------------------------------
    def create_establishment(self, payload, headers):
        return self._request("POST", f"{SURVEY_PREFIX}/establishments", payload, headers)

    # -- Panel enrollments ----------------------------------------------------
    def create_enrollment(self, payload, headers):
        return self._request("POST", f"{SURVEY_PREFIX}/panel-enrollments", payload, headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", f"{SURVEY_PREFIX}/panel-enrollments", headers=headers, params=params)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"{SURVEY_PREFIX}/panel-enrollments/{enrollment_id}", headers=headers)

    def enrollment_lifecycle(self, enrollment_id, payload, headers):
        return self._request("POST", f"{SURVEY_PREFIX}/panel-enrollments/{enrollment_id}/lifecycle",
                             payload, headers)

    # -- Survey cycles --------------------------------------------------------
    def create_cycle(self, payload, headers):
        return self._request("POST", f"{SURVEY_PREFIX}/survey-cycles", payload, headers)

    def list_cycles(self, headers, params=None):
        return self._request("GET", f"{SURVEY_PREFIX}/survey-cycles", headers=headers, params=params)

    def advance_cycle(self, cycle_id, payload, headers):
        return self._request("POST", f"{SURVEY_PREFIX}/survey-cycles/{cycle_id}/advance",
                             payload, headers)

    # -- Response reports -----------------------------------------------------
    def create_report(self, payload, headers):
        return self._request("POST", f"{SURVEY_PREFIX}/response-reports", payload, headers)

    def list_reports(self, headers, params=None):
        return self._request("GET", f"{SURVEY_PREFIX}/response-reports", headers=headers, params=params)

    def get_report(self, report_id, headers):
        return self._request("GET", f"{SURVEY_PREFIX}/response-reports/{report_id}", headers=headers)

    def advance_report(self, report_id, payload, headers):
        return self._request("POST", f"{SURVEY_PREFIX}/response-reports/{report_id}/advance",
                             payload, headers)

    # -- Follow-up cases ------------------------------------------------------
    def list_follow_up_cases(self, headers, params=None):
        return self._request("GET", f"{SURVEY_PREFIX}/follow-up-cases", headers=headers, params=params)

    def get_follow_up_case(self, case_id, headers):
        return self._request("GET", f"{SURVEY_PREFIX}/follow-up-cases/{case_id}", headers=headers)

    def advance_follow_up_case(self, case_id, payload, headers):
        return self._request("POST", f"{SURVEY_PREFIX}/follow-up-cases/{case_id}/advance",
                             payload, headers)

    # -- Cell estimates -------------------------------------------------------
    def list_cell_estimates(self, headers, params=None):
        return self._request("GET", f"{SURVEY_PREFIX}/cell-estimates", headers=headers, params=params)

    def get_cell_estimate(self, estimate_id, headers):
        return self._request("GET", f"{SURVEY_PREFIX}/cell-estimates/{estimate_id}", headers=headers)

    # -- Seasonal factor sets -------------------------------------------------
    def create_factor_set(self, payload, headers):
        return self._request("POST", f"{SURVEY_PREFIX}/seasonal-factor-sets", payload, headers)

    def list_factor_sets(self, headers, params=None):
        return self._request("GET", f"{SURVEY_PREFIX}/seasonal-factor-sets", headers=headers, params=params)

    def finalize_factor_set(self, set_id, headers, payload=None):
        return self._request("POST", f"{SURVEY_PREFIX}/seasonal-factor-sets/{set_id}/finalize",
                             payload or {}, headers)

    # -- Benchmark runs -------------------------------------------------------
    def create_benchmark_run(self, payload, headers):
        return self._request("POST", f"{SURVEY_PREFIX}/benchmark-runs", payload, headers)

    def apply_benchmark_run(self, run_id, headers, payload=None):
        return self._request("POST", f"{SURVEY_PREFIX}/benchmark-runs/{run_id}/apply",
                             payload or {}, headers)

    # -- Methodology notices --------------------------------------------------
    def create_notice(self, payload, headers):
        return self._request("POST", f"{SURVEY_PREFIX}/methodology-notices", payload, headers)

    def advance_notice(self, notice_id, payload, headers):
        return self._request("POST", f"{SURVEY_PREFIX}/methodology-notices/{notice_id}/advance",
                             payload, headers)

    # -- Release events -------------------------------------------------------
    def create_release(self, payload, headers):
        return self._request("POST", f"{SURVEY_PREFIX}/release-events", payload, headers)

    def list_releases(self, headers, params=None):
        return self._request("GET", f"{SURVEY_PREFIX}/release-events", headers=headers, params=params)

    def get_release(self, release_id, headers):
        return self._request("GET", f"{SURVEY_PREFIX}/release-events/{release_id}", headers=headers)

    def advance_release(self, release_id, payload, headers):
        return self._request("POST", f"{SURVEY_PREFIX}/release-events/{release_id}/advance",
                             payload, headers)

    # -- Media outlets --------------------------------------------------------
    def create_outlet(self, payload, headers):
        return self._request("POST", f"{SURVEY_PREFIX}/media-outlets", payload, headers)

    def list_outlets(self, headers, params=None):
        return self._request("GET", f"{SURVEY_PREFIX}/media-outlets", headers=headers, params=params)

    def outlet_accreditation(self, outlet_id, payload, headers):
        return self._request("POST", f"{SURVEY_PREFIX}/media-outlets/{outlet_id}/accreditation",
                             payload, headers)

    # -- Embargo grants -------------------------------------------------------
    def list_grants(self, headers, params=None):
        return self._request("GET", f"{SURVEY_PREFIX}/embargo-grants", headers=headers, params=params)

    def get_grant(self, grant_id, headers):
        return self._request("GET", f"{SURVEY_PREFIX}/embargo-grants/{grant_id}", headers=headers)

    def get_bulletin(self, grant_id, headers):
        return self._request("GET", f"{SURVEY_PREFIX}/embargo-grants/{grant_id}/bulletin",
                             headers=headers)

    def report_breach(self, grant_id, headers, payload=None):
        return self._request("POST", f"{SURVEY_PREFIX}/embargo-grants/{grant_id}/report-breach",
                             payload or {}, headers)


api_client = ApiClient()
