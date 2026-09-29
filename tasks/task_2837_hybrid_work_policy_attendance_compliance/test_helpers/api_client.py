"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Endpoint methods for the Hybrid Work Attendance Compliance API."""

    # ---------------- logical clock ----------------
    def set_clock(self, current_utc, headers=None):
        return self._request(
            "POST", "/_clock/set_current_utc",
            {"current_utc": current_utc}, headers or {},
        )

    # ---------------- policy cycles ----------------
    def create_policy_cycle(self, payload, headers):
        return self._request("POST", "/policy-cycles", payload, headers)

    def get_policy_cycle(self, cycle_id, headers):
        return self._request("GET", f"/policy-cycles/{cycle_id}", headers=headers)

    def list_policy_cycles(self, headers, params=None):
        return self._request("GET", "/policy-cycles", headers=headers, params=params)

    def set_cycle_posture(self, cycle_id, payload, headers):
        return self._request(
            "POST", f"/policy-cycles/{cycle_id}/posture", payload, headers
        )

    # ---------------- teams ----------------
    def create_team(self, payload, headers):
        return self._request("POST", "/teams", payload, headers)

    def get_team(self, team_id, headers):
        return self._request("GET", f"/teams/{team_id}", headers=headers)

    def list_teams(self, headers, params=None):
        return self._request("GET", "/teams", headers=headers, params=params)

    # ---------------- employees ----------------
    def create_employee(self, payload, headers):
        return self._request("POST", "/employees", payload, headers)

    def get_employee(self, employee_id, headers):
        return self._request("GET", f"/employees/{employee_id}", headers=headers)

    def list_employees(self, headers, params=None):
        return self._request("GET", "/employees", headers=headers, params=params)

    def set_employee_status(self, employee_id, payload, headers):
        return self._request(
            "POST", f"/employees/{employee_id}/status", payload, headers
        )

    # ---------------- eligibility classifications ----------------
    def create_classification(self, payload, headers):
        return self._request("POST", "/eligibility-classifications", payload, headers)

    def submit_classification(self, classification_id, headers, payload=None):
        return self._request(
            "POST", f"/eligibility-classifications/{classification_id}/submit",
            payload, headers,
        )

    def decide_classification(self, classification_id, payload, headers):
        return self._request(
            "POST", f"/eligibility-classifications/{classification_id}/decision",
            payload, headers,
        )

    def get_classification(self, classification_id, headers):
        return self._request(
            "GET", f"/eligibility-classifications/{classification_id}", headers=headers
        )

    def list_classifications(self, headers, params=None):
        return self._request(
            "GET", "/eligibility-classifications", headers=headers, params=params
        )

    # ---------------- attendance weeks ----------------
    def create_attendance_week(self, payload, headers):
        return self._request("POST", "/attendance-weeks", payload, headers)

    def get_attendance_week(self, week_id, headers):
        return self._request("GET", f"/attendance-weeks/{week_id}", headers=headers)

    def list_attendance_weeks(self, headers, params=None):
        return self._request(
            "GET", "/attendance-weeks", headers=headers, params=params
        )

    def append_signal(self, week_id, payload, headers):
        return self._request(
            "POST", f"/attendance-weeks/{week_id}/signals", payload, headers
        )

    def finalize_week(self, week_id, headers, payload=None):
        return self._request(
            "POST", f"/attendance-weeks/{week_id}/finalize", payload, headers
        )

    def amend_week(self, week_id, payload, headers):
        return self._request(
            "POST", f"/attendance-weeks/{week_id}/amend", payload, headers
        )

    # ---------------- compliance signals ----------------
    def get_compliance_signal(self, signal_id, headers):
        return self._request("GET", f"/compliance-signals/{signal_id}", headers=headers)

    def list_compliance_signals(self, headers, params=None):
        return self._request(
            "GET", "/compliance-signals", headers=headers, params=params
        )

    # ---------------- exception requests ----------------
    def create_exception_request(self, payload, headers):
        return self._request("POST", "/exception-requests", payload, headers)

    def request_exception_info(self, request_id, payload, headers):
        return self._request(
            "POST", f"/exception-requests/{request_id}/request-info", payload, headers
        )

    def respond_exception_info(self, request_id, payload, headers):
        return self._request(
            "POST", f"/exception-requests/{request_id}/respond", payload, headers
        )

    def adjudicate_exception(self, request_id, payload, headers):
        return self._request(
            "POST", f"/exception-requests/{request_id}/adjudicate", payload, headers
        )

    def revoke_exception(self, request_id, payload, headers):
        return self._request(
            "POST", f"/exception-requests/{request_id}/revoke", payload, headers
        )

    def get_exception_request(self, request_id, headers):
        return self._request(
            "GET", f"/exception-requests/{request_id}", headers=headers
        )

    def list_exception_requests(self, headers, params=None):
        return self._request(
            "GET", "/exception-requests", headers=headers, params=params
        )

    # ---------------- remote location requests ----------------
    def create_relocation_request(self, payload, headers):
        return self._request("POST", "/remote-location-requests", payload, headers)

    def record_tax_review(self, request_id, payload, headers):
        return self._request(
            "POST", f"/remote-location-requests/{request_id}/tax-review",
            payload, headers,
        )

    def record_security_review(self, request_id, payload, headers):
        return self._request(
            "POST", f"/remote-location-requests/{request_id}/security-review",
            payload, headers,
        )

    def decide_relocation(self, request_id, payload, headers):
        return self._request(
            "POST", f"/remote-location-requests/{request_id}/decide", payload, headers
        )

    def get_relocation_request(self, request_id, headers):
        return self._request(
            "GET", f"/remote-location-requests/{request_id}", headers=headers
        )

    def list_relocation_requests(self, headers, params=None):
        return self._request(
            "GET", "/remote-location-requests", headers=headers, params=params
        )

    # ---------------- neighborhoods ----------------
    def create_neighborhood(self, payload, headers):
        return self._request("POST", "/neighborhoods", payload, headers)

    def get_neighborhood(self, neighborhood_id, headers):
        return self._request("GET", f"/neighborhoods/{neighborhood_id}", headers=headers)

    def list_neighborhoods(self, headers, params=None):
        return self._request("GET", "/neighborhoods", headers=headers, params=params)

    # ---------------- seat allocations ----------------
    def create_seat_allocation(self, payload, headers):
        return self._request("POST", "/seat-allocations", payload, headers)

    def commit_seat_allocation(self, allocation_id, headers, payload=None):
        return self._request(
            "POST", f"/seat-allocations/{allocation_id}/commit", payload, headers
        )

    def release_seat_allocation(self, allocation_id, payload, headers):
        return self._request(
            "POST", f"/seat-allocations/{allocation_id}/release", payload, headers
        )

    def get_seat_allocation(self, allocation_id, headers):
        return self._request(
            "GET", f"/seat-allocations/{allocation_id}", headers=headers
        )

    def list_seat_allocations(self, headers, params=None):
        return self._request("GET", "/seat-allocations", headers=headers, params=params)

    # ---------------- desk assignments ----------------
    def create_desk_assignment(self, payload, headers):
        return self._request("POST", "/desk-assignments", payload, headers)

    def auto_assign_desk(self, payload, headers):
        return self._request("POST", "/desk-assignments/auto", payload, headers)

    def vacate_desk_assignment(self, assignment_id, headers, payload=None):
        return self._request(
            "POST", f"/desk-assignments/{assignment_id}/vacate", payload, headers
        )

    def get_desk_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"/desk-assignments/{assignment_id}", headers=headers
        )

    def list_desk_assignments(self, headers, params=None):
        return self._request("GET", "/desk-assignments", headers=headers, params=params)

    # ---------------- escalation cases ----------------
    def escalate_case(self, case_id, payload, headers):
        return self._request(
            "POST", f"/escalation-cases/{case_id}/escalate", payload, headers
        )

    def de_escalate_case(self, case_id, payload, headers):
        return self._request(
            "POST", f"/escalation-cases/{case_id}/de-escalate", payload, headers
        )

    def hold_case(self, case_id, payload, headers):
        return self._request(
            "POST", f"/escalation-cases/{case_id}/hold", payload, headers
        )

    def get_escalation_case(self, case_id, headers):
        return self._request("GET", f"/escalation-cases/{case_id}", headers=headers)

    def list_escalation_cases(self, headers, params=None):
        return self._request("GET", "/escalation-cases", headers=headers, params=params)

    # ---------------- recalibration reviews ----------------
    def create_recalibration_review(self, payload, headers):
        return self._request("POST", "/recalibration-reviews", payload, headers)

    def submit_recalibration_review(self, review_id, headers, payload=None):
        return self._request(
            "POST", f"/recalibration-reviews/{review_id}/submit", payload, headers
        )

    def decide_recalibration_review(self, review_id, payload, headers):
        return self._request(
            "POST", f"/recalibration-reviews/{review_id}/decision", payload, headers
        )

    def get_recalibration_review(self, review_id, headers):
        return self._request(
            "GET", f"/recalibration-reviews/{review_id}", headers=headers
        )

    def list_recalibration_reviews(self, headers, params=None):
        return self._request(
            "GET", "/recalibration-reviews", headers=headers, params=params
        )


def canonical_instant(value):
    """Normalise an ISO 8601 UTC instant so two spellings of the same moment
    compare equal.

    The PRD requires `created_at` and `updated_at` to carry exactly three
    fractional digits, but a caller-supplied clock literal may be written
    without them. This helper strips the fractional part and normalises the
    zone suffix so tests never assert on sub-second text width.
    """
    if not isinstance(value, str) or not value:
        return value
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1]
    elif "+" in text[10:]:
        text = text[: text.index("+", 10)]
    if "." in text:
        text = text[: text.index(".")]
    return text + "Z"


def same_instant(left, right):
    """True when two ISO 8601 UTC instants denote the same second."""
    return canonical_instant(left) == canonical_instant(right)


api_client = ApiClient()
