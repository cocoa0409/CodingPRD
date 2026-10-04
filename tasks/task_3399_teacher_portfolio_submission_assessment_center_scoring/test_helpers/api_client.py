"""API client: one method per endpoint in the PRD §4 endpoint inventory.

The base URL comes from the API_BASE_URL environment variable via
GenericApiClient (prd-bench-local-runner injects it before pytest runs).
"""
from typing import Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # -- logical clock (PRD §2.4) --------------------------------------------
    def set_clock(self, payload: Dict, headers: Dict):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # -- certification cycles -------------------------------------------------
    def create_cycle(self, payload: Dict, headers: Dict):
        return self._request("POST", "/cycles", payload, headers)

    def get_cycle(self, cycle_id: str, headers: Dict):
        return self._request("GET", f"/cycles/{cycle_id}", headers=headers)

    def transition_cycle(self, cycle_id: str, payload: Dict, headers: Dict):
        return self._request("POST", f"/cycles/{cycle_id}/transition", payload, headers)

    # -- calibration benchmarks ----------------------------------------------
    def create_benchmark(self, payload: Dict, headers: Dict):
        return self._request("POST", "/benchmarks", payload, headers)

    # -- candidates -----------------------------------------------------------
    def create_candidate(self, payload: Dict, headers: Dict):
        return self._request("POST", "/candidates", payload, headers)

    def get_candidate(self, candidate_id: str, headers: Dict):
        return self._request("GET", f"/candidates/{candidate_id}", headers=headers)

    def submit_eligibility(self, candidate_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/candidates/{candidate_id}/submit-eligibility", payload, headers
        )

    def verify_eligibility(self, candidate_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/candidates/{candidate_id}/verify-eligibility", payload, headers
        )

    # -- component submissions ------------------------------------------------
    def create_submission(self, cycle_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/cycles/{cycle_id}/submissions", payload, headers
        )

    def get_submission(self, submission_id: str, headers: Dict):
        return self._request("GET", f"/submissions/{submission_id}", headers=headers)

    def list_submissions(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/submissions", headers=headers, params=params)

    def submit_submission(self, submission_id: str, headers: Dict, payload: Optional[Dict] = None):
        return self._request(
            "POST", f"/submissions/{submission_id}/submit", payload or {}, headers
        )

    def tech_review_submission(self, submission_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/submissions/{submission_id}/tech-review", payload, headers
        )

    def retake_submission(self, submission_id: str, headers: Dict, payload: Optional[Dict] = None):
        return self._request(
            "POST", f"/submissions/{submission_id}/retake", payload or {}, headers
        )

    # -- artifacts ------------------------------------------------------------
    def upload_artifact(self, submission_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/submissions/{submission_id}/artifacts", payload, headers
        )

    def list_artifacts(self, submission_id: str, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"/submissions/{submission_id}/artifacts", headers=headers, params=params
        )

    # -- assessment centers and bookings --------------------------------------
    def create_assessment_center(self, payload: Dict, headers: Dict):
        return self._request("POST", "/assessment-centers", payload, headers)

    def get_assessment_center(self, center_id: str, headers: Dict):
        return self._request("GET", f"/assessment-centers/{center_id}", headers=headers)

    def create_booking(self, payload: Dict, headers: Dict):
        return self._request("POST", "/bookings", payload, headers)

    def get_booking(self, booking_id: str, headers: Dict):
        return self._request("GET", f"/bookings/{booking_id}", headers=headers)

    def list_bookings(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/bookings", headers=headers, params=params)

    def transition_booking(self, booking_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/bookings/{booking_id}/transition", payload, headers
        )

    # -- assessors ------------------------------------------------------------
    def create_assessor(self, payload: Dict, headers: Dict):
        return self._request("POST", "/assessors", payload, headers)

    def get_assessor(self, assessor_id: str, headers: Dict):
        return self._request("GET", f"/assessors/{assessor_id}", headers=headers)

    def transition_assessor(self, assessor_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/assessors/{assessor_id}/transition", payload, headers
        )

    # -- scoring assignments ---------------------------------------------------
    def create_assignment(self, payload: Dict, headers: Dict):
        return self._request("POST", "/assignments", payload, headers)

    def get_assignment(self, assignment_id: str, headers: Dict):
        return self._request("GET", f"/assignments/{assignment_id}", headers=headers)

    def list_assignments(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/assignments", headers=headers, params=params)

    def submit_score(self, assignment_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/assignments/{assignment_id}/submit-score", payload, headers
        )

    # -- certifications ---------------------------------------------------------
    def get_certification(self, certification_id: str, headers: Dict):
        return self._request("GET", f"/certifications/{certification_id}", headers=headers)

    def list_certifications(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/certifications", headers=headers, params=params)

    # -- renewals ---------------------------------------------------------------
    def create_renewal(self, certification_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/certifications/{certification_id}/renewals", payload, headers
        )

    def list_renewals(self, certification_id: str, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"/certifications/{certification_id}/renewals", headers=headers, params=params
        )

    def review_renewal(self, renewal_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/renewals/{renewal_id}/review", payload, headers
        )

    # -- incentive programs and stipends ----------------------------------------
    def create_incentive_program(self, payload: Dict, headers: Dict):
        return self._request("POST", "/incentive-programs", payload, headers)

    def get_incentive_program(self, program_id: str, headers: Dict):
        return self._request("GET", f"/incentive-programs/{program_id}", headers=headers)

    def list_program_stipends(self, program_id: str, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"/incentive-programs/{program_id}/stipends", headers=headers, params=params
        )

    def list_certification_stipends(self, certification_id: str, headers: Dict, params: Optional[Dict] = None):
        return self._request(
            "GET", f"/certifications/{certification_id}/stipends", headers=headers, params=params
        )

    def transition_stipend(self, stipend_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/stipends/{stipend_id}/transition", payload, headers
        )


api_client = ApiClient()
