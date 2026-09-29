"""Typed HTTP client - one method per endpoint in PRD section 4.

All methods return the raw ``requests.Response`` so tests can assert on status
codes. Responses are post-processed so that every ISO-8601 instant string is
canonicalised to exactly three fractional-second digits; that way an equality
comparison between two instants can never fail on sub-second *width* alone.
The untouched body remains available through :func:`raw_json`.
"""

import copy
import json
import re
from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

_INSTANT_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(\.\d+)?(Z|[+-]\d{2}:\d{2})$"
)


def canonicalize_instant(value: str) -> str:
    """Rewrite an ISO-8601 instant so its fractional part is exactly 3 digits."""
    match = _INSTANT_RE.match(value)
    if not match:
        return value
    seconds, fraction, offset = match.groups()
    digits = (fraction or ".")[1:]
    digits = (digits + "000")[:3]
    return f"{seconds}.{digits}{offset}"


def _canonicalize(node: Any) -> Any:
    if isinstance(node, str):
        return canonicalize_instant(node)
    if isinstance(node, list):
        return [_canonicalize(item) for item in node]
    if isinstance(node, dict):
        return {key: _canonicalize(value) for key, value in node.items()}
    return node


def raw_json(response: requests.Response) -> Any:
    """The response body exactly as the server serialised it, uncanonicalised."""
    return json.loads(response.text)


class ApiClient(GenericApiClient):
    """One method per endpoint of the Pediatric PDN Authorization Staffing API."""

    def _request(
        self,
        method: str,
        path: str,
        payload: Any = None,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict] = None,
    ) -> requests.Response:
        response = super()._request(method, path, payload, headers, params)
        try:
            body = response.json()
        except ValueError:
            return response
        canonical = _canonicalize(copy.deepcopy(body))
        response.json = lambda **_kwargs: canonical  # type: ignore[assignment]
        return response

    # ------------------------------------------------------------------
    # Logical clock and operations
    # ------------------------------------------------------------------
    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        """POST /pdn/_clock/set_current_utc"""
        return self._request("POST", "/pdn/_clock/set_current_utc", payload, headers)

    def run_daily_checkpoint(self, headers: Dict[str, str], payload: Any = None):
        """POST /pdn/_ops/run-daily-checkpoint"""
        return self._request(
            "POST", "/pdn/_ops/run-daily-checkpoint", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Payers
    # ------------------------------------------------------------------
    def create_payer(self, payload: Dict[str, Any], headers: Dict[str, str]):
        """POST /pdn/payers"""
        return self._request("POST", "/pdn/payers", payload, headers)

    def get_payer(self, payer_id: str, headers: Dict[str, str]):
        """GET /pdn/payers/{id}"""
        return self._request("GET", f"/pdn/payers/{payer_id}", None, headers)

    # ------------------------------------------------------------------
    # Nurses and competencies
    # ------------------------------------------------------------------
    def create_nurse(self, payload: Dict[str, Any], headers: Dict[str, str]):
        """POST /pdn/nurses"""
        return self._request("POST", "/pdn/nurses", payload, headers)

    def get_nurse(self, nurse_id: str, headers: Dict[str, str]):
        """GET /pdn/nurses/{id}"""
        return self._request("GET", f"/pdn/nurses/{nurse_id}", None, headers)

    def list_nurses(self, headers: Dict[str, str], params: Optional[Dict] = None):
        """GET /pdn/nurses"""
        return self._request("GET", "/pdn/nurses", params, headers)

    def set_nurse_status(
        self, nurse_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        """POST /pdn/nurses/{id}/status"""
        return self._request("POST", f"/pdn/nurses/{nurse_id}/status", payload, headers)

    def create_competency(
        self, nurse_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        """POST /pdn/nurses/{id}/competencies"""
        return self._request(
            "POST", f"/pdn/nurses/{nurse_id}/competencies", payload, headers
        )

    def list_competencies(
        self, nurse_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        """GET /pdn/nurses/{id}/competencies"""
        return self._request(
            "GET", f"/pdn/nurses/{nurse_id}/competencies", params, headers
        )

    def revoke_competency(
        self,
        competency_id: str,
        payload: Optional[Dict[str, Any]],
        headers: Dict[str, str],
    ):
        """POST /pdn/nurse-competencies/{id}/revoke"""
        return self._request(
            "POST",
            f"/pdn/nurse-competencies/{competency_id}/revoke",
            payload or {},
            headers,
        )

    def get_continuity_score(
        self, nurse_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        """GET /pdn/nurses/{id}/continuity-score"""
        return self._request(
            "GET", f"/pdn/nurses/{nurse_id}/continuity-score", params, headers
        )

    # ------------------------------------------------------------------
    # Patients
    # ------------------------------------------------------------------
    def create_patient(self, payload: Dict[str, Any], headers: Dict[str, str]):
        """POST /pdn/patients"""
        return self._request("POST", "/pdn/patients", payload, headers)

    def get_patient(self, patient_id: str, headers: Dict[str, str]):
        """GET /pdn/patients/{id}"""
        return self._request("GET", f"/pdn/patients/{patient_id}", None, headers)

    def list_patients(self, headers: Dict[str, str], params: Optional[Dict] = None):
        """GET /pdn/patients"""
        return self._request("GET", "/pdn/patients", params, headers)

    # ------------------------------------------------------------------
    # Plans of care
    # ------------------------------------------------------------------
    def create_plan_of_care(self, payload: Dict[str, Any], headers: Dict[str, str]):
        """POST /pdn/plans-of-care"""
        return self._request("POST", "/pdn/plans-of-care", payload, headers)

    def get_plan_of_care(self, plan_id: str, headers: Dict[str, str]):
        """GET /pdn/plans-of-care/{id}"""
        return self._request("GET", f"/pdn/plans-of-care/{plan_id}", None, headers)

    def list_plans_of_care(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        """GET /pdn/plans-of-care"""
        return self._request("GET", "/pdn/plans-of-care", params, headers)

    def submit_plan_of_care(
        self, plan_id: str, headers: Dict[str, str], payload: Any = None
    ):
        """POST /pdn/plans-of-care/{id}/submit"""
        return self._request(
            "POST", f"/pdn/plans-of-care/{plan_id}/submit", payload or {}, headers
        )

    def return_plan_of_care(
        self, plan_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        """POST /pdn/plans-of-care/{id}/return"""
        return self._request(
            "POST", f"/pdn/plans-of-care/{plan_id}/return", payload, headers
        )

    # ------------------------------------------------------------------
    # Authorizations
    # ------------------------------------------------------------------
    def create_authorization(self, payload: Dict[str, Any], headers: Dict[str, str]):
        """POST /pdn/authorizations"""
        return self._request("POST", "/pdn/authorizations", payload, headers)

    def get_authorization(self, authorization_id: str, headers: Dict[str, str]):
        """GET /pdn/authorizations/{id}"""
        return self._request(
            "GET", f"/pdn/authorizations/{authorization_id}", None, headers
        )

    def list_authorizations(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        """GET /pdn/authorizations"""
        return self._request("GET", "/pdn/authorizations", params, headers)

    def activate_authorization(
        self, authorization_id: str, headers: Dict[str, str], payload: Any = None
    ):
        """POST /pdn/authorizations/{id}/activate"""
        return self._request(
            "POST",
            f"/pdn/authorizations/{authorization_id}/activate",
            payload or {},
            headers,
        )

    def get_utilization(
        self,
        authorization_id: str,
        headers: Dict[str, str],
        params: Optional[Dict] = None,
    ):
        """GET /pdn/authorizations/{id}/utilization"""
        return self._request(
            "GET",
            f"/pdn/authorizations/{authorization_id}/utilization",
            params,
            headers,
        )

    def reduce_authorization(
        self, authorization_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        """POST /pdn/authorizations/{id}/reduce"""
        return self._request(
            "POST", f"/pdn/authorizations/{authorization_id}/reduce", payload, headers
        )

    def apply_reduction(
        self, authorization_id: str, headers: Dict[str, str], payload: Any = None
    ):
        """POST /pdn/authorizations/{id}/apply-reduction"""
        return self._request(
            "POST",
            f"/pdn/authorizations/{authorization_id}/apply-reduction",
            payload or {},
            headers,
        )

    def renew_authorization(
        self, authorization_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        """POST /pdn/authorizations/{id}/renew"""
        return self._request(
            "POST", f"/pdn/authorizations/{authorization_id}/renew", payload, headers
        )

    # ------------------------------------------------------------------
    # Authorization disputes
    # ------------------------------------------------------------------
    def create_dispute(self, payload: Dict[str, Any], headers: Dict[str, str]):
        """POST /pdn/authorization-disputes"""
        return self._request("POST", "/pdn/authorization-disputes", payload, headers)

    def get_dispute(self, dispute_id: str, headers: Dict[str, str]):
        """GET /pdn/authorization-disputes/{id}"""
        return self._request(
            "GET", f"/pdn/authorization-disputes/{dispute_id}", None, headers
        )

    def list_disputes(self, headers: Dict[str, str], params: Optional[Dict] = None):
        """GET /pdn/authorization-disputes"""
        return self._request("GET", "/pdn/authorization-disputes", params, headers)

    def review_dispute(
        self, dispute_id: str, headers: Dict[str, str], payload: Any = None
    ):
        """POST /pdn/authorization-disputes/{id}/review"""
        return self._request(
            "POST",
            f"/pdn/authorization-disputes/{dispute_id}/review",
            payload or {},
            headers,
        )

    def decide_dispute(
        self, dispute_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        """POST /pdn/authorization-disputes/{id}/decide"""
        return self._request(
            "POST", f"/pdn/authorization-disputes/{dispute_id}/decide", payload, headers
        )

    # ------------------------------------------------------------------
    # Cases and supervisory visits
    # ------------------------------------------------------------------
    def create_case(self, payload: Dict[str, Any], headers: Dict[str, str]):
        """POST /pdn/cases"""
        return self._request("POST", "/pdn/cases", payload, headers)

    def get_case(self, case_id: str, headers: Dict[str, str]):
        """GET /pdn/cases/{id}"""
        return self._request("GET", f"/pdn/cases/{case_id}", None, headers)

    def list_cases(self, headers: Dict[str, str], params: Optional[Dict] = None):
        """GET /pdn/cases"""
        return self._request("GET", "/pdn/cases", params, headers)

    def activate_case(self, case_id: str, headers: Dict[str, str], payload: Any = None):
        """POST /pdn/cases/{id}/activate"""
        return self._request(
            "POST", f"/pdn/cases/{case_id}/activate", payload or {}, headers
        )

    def hold_case(self, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        """POST /pdn/cases/{id}/hold"""
        return self._request("POST", f"/pdn/cases/{case_id}/hold", payload, headers)

    def resume_case(self, case_id: str, headers: Dict[str, str], payload: Any = None):
        """POST /pdn/cases/{id}/resume"""
        return self._request(
            "POST", f"/pdn/cases/{case_id}/resume", payload or {}, headers
        )

    def close_case(self, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        """POST /pdn/cases/{id}/close"""
        return self._request("POST", f"/pdn/cases/{case_id}/close", payload, headers)

    def create_supervisory_visit(
        self, case_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        """POST /pdn/cases/{id}/supervisory-visits"""
        return self._request(
            "POST", f"/pdn/cases/{case_id}/supervisory-visits", payload, headers
        )

    def list_supervisory_visits(
        self, case_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        """GET /pdn/cases/{id}/supervisory-visits"""
        return self._request(
            "GET", f"/pdn/cases/{case_id}/supervisory-visits", params, headers
        )

    # ------------------------------------------------------------------
    # Incident reports
    # ------------------------------------------------------------------
    def create_incident_report(self, payload: Dict[str, Any], headers: Dict[str, str]):
        """POST /pdn/incident-reports"""
        return self._request("POST", "/pdn/incident-reports", payload, headers)

    def get_incident_report(self, incident_id: str, headers: Dict[str, str]):
        """GET /pdn/incident-reports/{id}"""
        return self._request(
            "GET", f"/pdn/incident-reports/{incident_id}", None, headers
        )

    def list_case_incident_reports(
        self, case_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        """GET /pdn/cases/{id}/incident-reports"""
        return self._request(
            "GET", f"/pdn/cases/{case_id}/incident-reports", params, headers
        )

    def close_incident_report(
        self, incident_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        """POST /pdn/incident-reports/{id}/close"""
        return self._request(
            "POST", f"/pdn/incident-reports/{incident_id}/close", payload, headers
        )

    # ------------------------------------------------------------------
    # Shifts
    # ------------------------------------------------------------------
    def create_shift(self, payload: Dict[str, Any], headers: Dict[str, str]):
        """POST /pdn/shifts"""
        return self._request("POST", "/pdn/shifts", payload, headers)

    def get_shift(self, shift_id: str, headers: Dict[str, str]):
        """GET /pdn/shifts/{id}"""
        return self._request("GET", f"/pdn/shifts/{shift_id}", None, headers)

    def list_shifts(self, headers: Dict[str, str], params: Optional[Dict] = None):
        """GET /pdn/shifts"""
        return self._request("GET", "/pdn/shifts", params, headers)

    def get_staffing_candidates(
        self, shift_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        """GET /pdn/shifts/{id}/staffing-candidates"""
        return self._request(
            "GET", f"/pdn/shifts/{shift_id}/staffing-candidates", params, headers
        )

    def auto_staff_shift(
        self, shift_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        """POST /pdn/shifts/{id}/auto-staff"""
        return self._request(
            "POST", f"/pdn/shifts/{shift_id}/auto-staff", payload, headers
        )

    def escalate_shift(
        self, shift_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        """POST /pdn/shifts/{id}/escalate"""
        return self._request(
            "POST", f"/pdn/shifts/{shift_id}/escalate", payload, headers
        )

    def parent_backup_shift(
        self, shift_id: str, headers: Dict[str, str], payload: Any = None
    ):
        """POST /pdn/shifts/{id}/parent-backup"""
        return self._request(
            "POST", f"/pdn/shifts/{shift_id}/parent-backup", payload or {}, headers
        )

    def clock_in(self, shift_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        """POST /pdn/shifts/{id}/clock-in"""
        return self._request("POST", f"/pdn/shifts/{shift_id}/clock-in", payload, headers)

    def clock_out(self, shift_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        """POST /pdn/shifts/{id}/clock-out"""
        return self._request(
            "POST", f"/pdn/shifts/{shift_id}/clock-out", payload, headers
        )

    # ------------------------------------------------------------------
    # Shift assignments
    # ------------------------------------------------------------------
    def create_assignment(self, payload: Dict[str, Any], headers: Dict[str, str]):
        """POST /pdn/shift-assignments"""
        return self._request("POST", "/pdn/shift-assignments", payload, headers)

    def get_assignment(self, assignment_id: str, headers: Dict[str, str]):
        """GET /pdn/shift-assignments/{id}"""
        return self._request(
            "GET", f"/pdn/shift-assignments/{assignment_id}", None, headers
        )

    def list_assignments(self, headers: Dict[str, str], params: Optional[Dict] = None):
        """GET /pdn/shift-assignments"""
        return self._request("GET", "/pdn/shift-assignments", params, headers)

    def cancel_assignment(
        self, assignment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        """POST /pdn/shift-assignments/{id}/cancel"""
        return self._request(
            "POST", f"/pdn/shift-assignments/{assignment_id}/cancel", payload, headers
        )

    def list_assignment_timesheets(
        self, assignment_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        """GET /pdn/shift-assignments/{id}/timesheets"""
        return self._request(
            "GET", f"/pdn/shift-assignments/{assignment_id}/timesheets", params, headers
        )

    # ------------------------------------------------------------------
    # Timesheets
    # ------------------------------------------------------------------
    def get_timesheet(self, timesheet_id: str, headers: Dict[str, str]):
        """GET /pdn/timesheets/{id}"""
        return self._request("GET", f"/pdn/timesheets/{timesheet_id}", None, headers)

    def correct_timesheet(
        self, timesheet_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        """PATCH /pdn/timesheets/{id}"""
        return self._request(
            "PATCH", f"/pdn/timesheets/{timesheet_id}", payload, headers
        )

    def submit_timesheet(
        self, timesheet_id: str, headers: Dict[str, str], payload: Any = None
    ):
        """POST /pdn/timesheets/{id}/submit"""
        return self._request(
            "POST", f"/pdn/timesheets/{timesheet_id}/submit", payload or {}, headers
        )

    def billing_decision(
        self, timesheet_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        """POST /pdn/timesheets/{id}/billing-decision"""
        return self._request(
            "POST", f"/pdn/timesheets/{timesheet_id}/billing-decision", payload, headers
        )

    def void_timesheet(
        self, timesheet_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        """POST /pdn/timesheets/{id}/void"""
        return self._request(
            "POST", f"/pdn/timesheets/{timesheet_id}/void", payload, headers
        )
