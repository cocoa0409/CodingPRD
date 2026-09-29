"""HTTP client exposing one method per endpoint declared by the PRD."""

from typing import Any, Dict, Optional

import requests
from prd_bench_local_runner.testing import GenericApiClient

Headers = Optional[Dict[str, str]]
Params = Optional[Dict[str, Any]]
Payload = Optional[Dict[str, Any]]


class ApiClient(GenericApiClient):
    """One method per row of the endpoint table, plus the logical-clock control."""

    # ---------------------------------------------------------------- clock
    def set_clock(self, current_utc: str, headers: Headers = None) -> requests.Response:
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    def set_clock_raw(
        self, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------- students
    def create_student(
        self, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", "/esy/students", payload, headers)

    def get_student(
        self, student_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", f"/esy/students/{student_id}", None, headers)

    def list_student_determinations(
        self, student_id: str, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/esy/students/{student_id}/eligibility-determinations",
            None,
            headers,
            params,
        )

    def list_student_due_process_records(
        self, student_id: str, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/esy/students/{student_id}/due-process-records",
            None,
            headers,
            params,
        )

    # ----------------------------------------- eligibility determinations
    def create_determination(
        self, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", "/esy/eligibility-determinations", payload, headers
        )

    def get_determination(
        self, determination_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/esy/eligibility-determinations/{determination_id}", None, headers
        )

    def analyze_determination(
        self,
        determination_id: str,
        payload: Payload = None,
        headers: Headers = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/esy/eligibility-determinations/{determination_id}/analyze",
            payload if payload is not None else {},
            headers,
        )

    def determination_parent_response(
        self, determination_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/esy/eligibility-determinations/{determination_id}/parent-response",
            payload,
            headers,
        )

    def finalize_determination(
        self,
        determination_id: str,
        payload: Payload = None,
        headers: Headers = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/esy/eligibility-determinations/{determination_id}/finalize",
            payload if payload is not None else {},
            headers,
        )

    # -------------------------------------------------------------- programs
    def create_program(
        self, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", "/esy/programs", payload, headers)

    def get_program(
        self, program_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", f"/esy/programs/{program_id}", None, headers)

    def set_program_status(
        self, program_id: str, target_status: str, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/esy/programs/{program_id}/status",
            {"target_status": target_status},
            headers,
        )

    def cancel_program_day(
        self, program_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/esy/programs/{program_id}/cancel-day", payload, headers
        )

    def list_program_fund_allocations(
        self, program_id: str, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/esy/programs/{program_id}/fund-allocations", None, headers, params
        )

    def list_program_transportation_runs(
        self, program_id: str, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/esy/programs/{program_id}/transportation-runs",
            None,
            headers,
            params,
        )

    # ------------------------------------------------------- fund allocations
    def create_fund_allocation(
        self, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", "/esy/fund-allocations", payload, headers)

    def patch_fund_allocation(
        self, allocation_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "PATCH", f"/esy/fund-allocations/{allocation_id}", payload, headers
        )

    # ------------------------------------------------------------- providers
    def create_provider(
        self, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", "/esy/providers", payload, headers)

    def get_provider(
        self, provider_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", f"/esy/providers/{provider_id}", None, headers)

    def patch_provider(
        self, provider_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "PATCH", f"/esy/providers/{provider_id}", payload, headers
        )

    def list_provider_assignments_for_provider(
        self, provider_id: str, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/esy/providers/{provider_id}/provider-assignments",
            None,
            headers,
            params,
        )

    # -------------------------------------------------- transportation runs
    def create_transportation_run(
        self, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", "/esy/transportation-runs", payload, headers)

    # --------------------------------------------------- service commitments
    def create_commitment(
        self, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", "/esy/service-commitments", payload, headers)

    def list_commitments(
        self, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request("GET", "/esy/service-commitments", None, headers, params)

    def get_commitment(
        self, commitment_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/esy/service-commitments/{commitment_id}", None, headers
        )

    def set_commitment_status(
        self, commitment_id: str, target_status: str, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/esy/service-commitments/{commitment_id}/status",
            {"target_status": target_status},
            headers,
        )

    def list_provider_assignments_for_commitment(
        self, commitment_id: str, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/esy/service-commitments/{commitment_id}/provider-assignments",
            None,
            headers,
            params,
        )

    # -------------------------------------------------- provider assignments
    def create_provider_assignment(
        self, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", "/esy/provider-assignments", payload, headers)

    def release_provider_assignment(
        self, assignment_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/esy/provider-assignments/{assignment_id}/release",
            payload,
            headers,
        )

    # ----------------------------------------------------------- service logs
    def create_service_log(
        self, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", "/esy/service-logs", payload, headers)

    def list_service_logs(
        self, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request("GET", "/esy/service-logs", None, headers, params)

    def get_service_log(
        self, log_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request("GET", f"/esy/service-logs/{log_id}", None, headers)

    def void_service_log(
        self, log_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/esy/service-logs/{log_id}/void", payload, headers
        )

    # ---------------------------------------------------- compensatory awards
    def create_award(
        self, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", "/esy/compensatory-awards", payload, headers)

    def list_awards(
        self, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request("GET", "/esy/compensatory-awards", None, headers, params)

    def get_award(self, award_id: str, headers: Headers = None) -> requests.Response:
        return self._request(
            "GET", f"/esy/compensatory-awards/{award_id}", None, headers
        )

    def get_due_process_packet(
        self, award_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/esy/compensatory-awards/{award_id}/due-process-packet",
            None,
            headers,
        )

    def propose_award(
        self, award_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/esy/compensatory-awards/{award_id}/propose", payload, headers
        )

    def award_parent_response(
        self, award_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/esy/compensatory-awards/{award_id}/parent-response",
            payload,
            headers,
        )

    def resolve_award_dispute(
        self, award_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/esy/compensatory-awards/{award_id}/resolve-dispute",
            payload,
            headers,
        )

    # --------------------------------------------------------- makeup sessions
    def create_makeup_session(
        self, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", "/esy/makeup-sessions", payload, headers)

    def list_makeup_sessions(
        self, headers: Headers = None, params: Params = None
    ) -> requests.Response:
        return self._request("GET", "/esy/makeup-sessions", None, headers, params)

    def get_makeup_session(
        self, session_id: str, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/esy/makeup-sessions/{session_id}", None, headers
        )

    def log_makeup_outcome(
        self, session_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/esy/makeup-sessions/{session_id}/log-outcome",
            payload,
            headers,
        )

    # ------------------------------------------------------ due process records
    def create_due_process_record(
        self, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request("POST", "/esy/due-process-records", payload, headers)

    def patch_due_process_record(
        self, record_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "PATCH", f"/esy/due-process-records/{record_id}", payload, headers
        )

    # ------------------------------------------------------------- raw escape
    def request(
        self,
        method: str,
        path: str,
        payload: Payload = None,
        headers: Headers = None,
        params: Params = None,
    ) -> requests.Response:
        """Escape hatch for header-omission and malformed-request cases."""
        return self._request(method, path, payload, headers, params)

    def post_without_headers(
        self, path: str, payload: Payload = None
    ) -> requests.Response:
        """POST carrying neither X-User-ID nor X-User-Role."""
        return requests.post(f"{self.base_url}{path}", json=payload, timeout=30)

    def get_without_headers(self, path: str) -> requests.Response:
        """GET carrying neither X-User-ID nor X-User-Role."""
        return requests.get(f"{self.base_url}{path}", timeout=30)


api_client = ApiClient()
