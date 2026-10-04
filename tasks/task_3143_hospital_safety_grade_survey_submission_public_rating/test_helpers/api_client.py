"""API client: one method per operation the API exposes."""

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/hospital-safety-rating"


class ApiClient(GenericApiClient):
    # --- Test-driving --------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # --- Hospitals -----------------------------------------------------------
    def create_hospital(self, payload, headers):
        return self._request("POST", f"{PREFIX}/hospitals", payload, headers)

    def list_hospitals(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/hospitals", headers=headers, params=params)

    def get_hospital(self, hospital_id, headers):
        return self._request("GET", f"{PREFIX}/hospitals/{hospital_id}", headers=headers)

    def update_hospital(self, hospital_id, payload, headers):
        return self._request("PUT", f"{PREFIX}/hospitals/{hospital_id}", payload, headers)

    def list_hospital_surveys(self, hospital_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/hospitals/{hospital_id}/surveys", headers=headers, params=params
        )

    def list_hospital_grades(self, hospital_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/hospitals/{hospital_id}/grades", headers=headers, params=params
        )

    def list_hospital_reviews(self, hospital_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/hospitals/{hospital_id}/reviews", headers=headers, params=params
        )

    def list_hospital_reanalysis_requests(self, hospital_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/hospitals/{hospital_id}/reanalysis-requests",
            headers=headers, params=params,
        )

    def list_hospital_employers(self, hospital_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/hospitals/{hospital_id}/employers", headers=headers, params=params
        )

    # --- Methodology versions ------------------------------------------------
    def create_methodology_version(self, payload, headers):
        return self._request("POST", f"{PREFIX}/methodology-versions", payload, headers)

    def list_methodology_versions(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/methodology-versions", headers=headers, params=params
        )

    def get_methodology_version(self, version_id, headers):
        return self._request(
            "GET", f"{PREFIX}/methodology-versions/{version_id}", headers=headers
        )

    def publish_methodology_version(self, version_id, headers):
        return self._request(
            "POST", f"{PREFIX}/methodology-versions/{version_id}/publish", {}, headers
        )

    def pin_methodology_version(self, hospital_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/hospitals/{hospital_id}/methodology-versions", payload, headers
        )

    def list_hospital_methodology_versions(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/hospital-methodology-versions", headers=headers, params=params
        )

    def create_pending_methodology_change(self, hospital_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/hospitals/{hospital_id}/pending-methodology-changes",
            payload, headers,
        )

    def review_pending_methodology_change(self, change_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/pending-methodology-changes/{change_id}/review", payload, headers
        )

    def get_pending_methodology_change(self, change_id, headers):
        return self._request(
            "GET", f"{PREFIX}/pending-methodology-changes/{change_id}", headers=headers
        )

    # --- Surveys -------------------------------------------------------------
    def create_survey(self, hospital_id, payload, headers):
        return self._request("POST", f"{PREFIX}/hospitals/{hospital_id}/surveys", payload, headers)

    def get_survey(self, survey_id, headers):
        return self._request("GET", f"{PREFIX}/surveys/{survey_id}", headers=headers)

    def update_survey(self, survey_id, payload, headers):
        return self._request("PUT", f"{PREFIX}/surveys/{survey_id}", payload, headers)

    def create_survey_measure(self, hospital_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/hospitals/{hospital_id}/survey-measures", payload, headers
        )

    def submit_survey(self, survey_id, headers):
        return self._request("POST", f"{PREFIX}/surveys/{survey_id}/submit", {}, headers)

    def verify_survey(self, survey_id, payload, headers):
        return self._request("POST", f"{PREFIX}/surveys/{survey_id}/verify", payload, headers)

    def resolve_survey(self, survey_id, headers):
        return self._request("POST", f"{PREFIX}/surveys/{survey_id}/resolve", {}, headers)

    def create_public_source_measure(self, hospital_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/hospitals/{hospital_id}/public-source-measures", payload, headers
        )

    def list_survey_measures(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/survey-measures", headers=headers, params=params)

    # --- Measure sets and score runs -----------------------------------------
    def refresh_measures(self, hospital_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/hospitals/{hospital_id}/refresh-measures", payload, headers
        )

    def create_score_run(self, hospital_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/hospitals/{hospital_id}/score-runs", payload, headers
        )

    def list_hospital_score_runs(self, hospital_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/hospitals/{hospital_id}/score-runs", headers=headers, params=params
        )

    def list_measure_set_score_runs(self, measure_set_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/hospital-measure-sets/{measure_set_id}/score-runs",
            headers=headers, params=params,
        )

    def list_score_run_grades(self, score_run_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/score-runs/{score_run_id}/grades", headers=headers, params=params
        )

    def list_measure_sets(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/hospital-measure-sets", headers=headers, params=params
        )

    def get_measure_set(self, measure_set_id, headers):
        return self._request(
            "GET", f"{PREFIX}/hospital-measure-sets/{measure_set_id}", headers=headers
        )

    def get_composite_preview(self, hospital_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/hospitals/{hospital_id}/composite-preview",
            headers=headers, params=params,
        )

    def get_scorecard(self, hospital_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/hospitals/{hospital_id}/scorecard", headers=headers, params=params
        )

    # --- Preliminary results, reviews and corrections ------------------------
    def create_preliminary_result(self, hospital_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/hospitals/{hospital_id}/preliminary-results", payload, headers
        )

    def accept_preliminary_result(self, hospital_id, review_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/hospitals/{hospital_id}/preliminary-results/{review_id}/accept",
            payload, headers,
        )

    def create_correction(self, hospital_id, review_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/hospitals/{hospital_id}/preliminary-results/{review_id}/corrections",
            payload, headers,
        )

    def decide_correction(self, hospital_id, review_id, correction_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/hospitals/{hospital_id}/preliminary-results/{review_id}"
            f"/corrections/{correction_id}/decide",
            payload, headers,
        )

    def get_review_summary(self, hospital_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/hospitals/{hospital_id}/review-summary",
            headers=headers, params=params,
        )

    def list_corrections(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/correction-requests", headers=headers, params=params
        )

    def list_reviews(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/hospital-reviews", headers=headers, params=params)

    # --- Reanalysis requests -------------------------------------------------
    def create_reanalysis_request(self, hospital_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/hospitals/{hospital_id}/reanalysis-requests", payload, headers
        )

    def decide_reanalysis_request(self, hospital_id, request_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/hospitals/{hospital_id}/reanalysis-requests/{request_id}/decide",
            payload, headers,
        )

    def get_reanalysis_request(self, request_id, headers):
        return self._request("GET", f"{PREFIX}/reanalysis-requests/{request_id}", headers=headers)

    # --- Release cycles and grades -------------------------------------------
    def create_release_cycle(self, payload, headers):
        return self._request("POST", f"{PREFIX}/release-cycles", payload, headers)

    def list_release_cycles(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/release-cycles", headers=headers, params=params)

    def get_release_cycle(self, cycle_id, headers):
        return self._request("GET", f"{PREFIX}/release-cycles/{cycle_id}", headers=headers)

    def open_review(self, cycle_id, headers):
        return self._request("POST", f"{PREFIX}/release-cycles/{cycle_id}/open-review", {}, headers)

    def publish_release_cycle(self, cycle_id, headers):
        return self._request("POST", f"{PREFIX}/release-cycles/{cycle_id}/publish", {}, headers)

    def list_release_cycle_grades(self, cycle_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/release-cycles/{cycle_id}/grades", headers=headers, params=params
        )

    def get_grade(self, grade_id, headers):
        return self._request("GET", f"{PREFIX}/grades/{grade_id}", headers=headers)

    # --- Employers -----------------------------------------------------------
    def create_employer(self, payload, headers):
        return self._request("POST", f"{PREFIX}/employers", payload, headers)

    def list_employers(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/employers", headers=headers, params=params)

    def get_employer(self, employer_id, headers):
        return self._request("GET", f"{PREFIX}/employers/{employer_id}", headers=headers)

    def set_network_listing(self, employer_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/employers/{employer_id}/network-listings", payload, headers
        )


api_client = ApiClient()