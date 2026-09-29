"""HTTP client: one method per endpoint the PRD publishes under ``/lab``.

Every method returns the raw response so a test can assert on the status code as
well as the envelope. Nothing here interprets a response body.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX


def _clean(payload: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Drop keys whose value is the sentinel ``OMIT`` so optional inputs can be skipped."""
    if payload is None:
        return None
    return {k: v for k, v in payload.items() if v is not OMIT}


class _Omit:
    """Sentinel marking an optional field that should not be sent at all."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "OMIT"


OMIT = _Omit()


def canonical_instant(value: Optional[str]) -> Optional[str]:
    """Normalise an ISO-8601 UTC instant so two spellings of one moment compare equal.

    Sub-second width is not semantically meaningful, so ``2026-08-01T00:00:00Z`` and
    ``2026-08-01T00:00:00.000Z`` are folded onto the same canonical string.
    """
    if value is None:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        from datetime import timezone
        from datetime import datetime as _dt

        parsed = _dt.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        parsed = parsed.astimezone(timezone.utc)
    except ValueError:
        return str(value)
    return parsed.strftime("%Y-%m-%dT%H:%M:%S.") + f"{parsed.microsecond // 1000:03d}Z"


class LabApiClient(GenericApiClient):
    """Endpoint surface of the crime-laboratory case-management API."""

    # ─── Logical clock (PRD §2.5) ─────────────────────

    def set_clock(self, current_utc: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/_clock/set_current_utc",
            {"current_utc": current_utc},
            headers,
        )

    def set_clock_raw(self, payload: Any, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/_clock/set_current_utc", payload, headers
        )

    # ─── Analysts (PRD §3.4) ──────────────────────────

    def create_analyst(self, payload: Any, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/analysts", _clean(payload), headers)

    def update_analyst(
        self, analyst_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "PATCH", f"{API_PREFIX}/analysts/{analyst_id}", _clean(payload), headers
        )

    def reinstate_analyst(
        self, analyst_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/analysts/{analyst_id}/reinstate",
            _clean(payload),
            headers,
        )

    def get_analyst(self, analyst_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/analysts/{analyst_id}", None, headers)

    def get_analyst_workload(
        self, analyst_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/analysts/{analyst_id}/workload", None, headers
        )

    # ─── Methods (PRD §3.2) ───────────────────────────

    def create_method(self, payload: Any, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/methods", _clean(payload), headers)

    def validate_method(
        self, method_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/methods/{method_id}/validate", _clean(payload), headers
        )

    def retire_method(
        self, method_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/methods/{method_id}/retire", _clean(payload), headers
        )

    def get_method(self, method_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/methods/{method_id}", None, headers)

    # ─── Vendors (PRD §3.7) ───────────────────────────

    def create_vendor(self, payload: Any, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/vendors", _clean(payload), headers)

    def set_vendor_status(
        self, vendor_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/vendors/{vendor_id}/status", _clean(payload), headers
        )

    def get_vendor(self, vendor_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/vendors/{vendor_id}", None, headers)

    # ─── Cases (PRD §3.1, §3.9) ───────────────────────

    def create_case(self, payload: Any, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/cases", _clean(payload), headers)

    def accept_case(
        self, case_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/cases/{case_id}/accept", _clean(payload), headers
        )

    def reject_case(
        self, case_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/cases/{case_id}/reject", _clean(payload), headers
        )

    def override_case_priority(
        self, case_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/cases/{case_id}/priority-overrides",
            _clean(payload),
            headers,
        )

    def report_case(
        self, case_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/cases/{case_id}/report", _clean(payload), headers
        )

    def request_discovery(
        self, case_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/cases/{case_id}/discovery-request",
            _clean(payload),
            headers,
        )

    def respond_to_discovery(
        self, case_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/cases/{case_id}/discovery-response",
            _clean(payload),
            headers,
        )

    def get_case(self, case_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/cases/{case_id}", None, headers)

    def list_cases(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/cases", _clean(params), headers)

    # ─── Evidence items (PRD §3.1) ────────────────────

    def create_evidence_item(
        self, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/evidence-items", _clean(payload), headers
        )

    def return_evidence_item(
        self, evidence_item_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/evidence-items/{evidence_item_id}/return",
            _clean(payload),
            headers,
        )

    def get_evidence_item(
        self, evidence_item_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/evidence-items/{evidence_item_id}", None, headers
        )

    def list_evidence_items(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/evidence-items", _clean(params), headers
        )

    # ─── Examination requests (PRD §3.3, §3.5, §3.6) ───

    def create_examination_request(
        self, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/examination-requests", _clean(payload), headers
        )

    def create_assignment(
        self, examination_request_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/examination-requests/{examination_request_id}/assignments",
            _clean(payload),
            headers,
        )

    def auto_assign(
        self,
        examination_request_id: str,
        headers: Dict[str, str],
        payload: Any = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/examination-requests/{examination_request_id}/auto-assign",
            _clean(payload) if payload is not None else {},
            headers,
        )

    def start_analysis(
        self, examination_request_id: str, headers: Dict[str, str], payload: Any = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/examination-requests/{examination_request_id}/start-analysis",
            _clean(payload) if payload is not None else {},
            headers,
        )

    def complete_analysis(
        self, examination_request_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/examination-requests/{examination_request_id}/complete-analysis",
            _clean(payload),
            headers,
        )

    def technical_review(
        self, examination_request_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/examination-requests/{examination_request_id}/technical-review",
            _clean(payload),
            headers,
        )

    def disagreement_resolution(
        self, examination_request_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/examination-requests/{examination_request_id}"
            f"/disagreement-resolution",
            _clean(payload),
            headers,
        )

    def administrative_review(
        self, examination_request_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/examination-requests/{examination_request_id}"
            f"/administrative-review",
            _clean(payload),
            headers,
        )

    def create_vendor_engagement(
        self, examination_request_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/examination-requests/{examination_request_id}"
            f"/vendor-engagements",
            _clean(payload),
            headers,
        )

    def get_examination_request(
        self, examination_request_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/examination-requests/{examination_request_id}",
            None,
            headers,
        )

    def list_examination_requests(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/examination-requests", _clean(params), headers
        )

    # ─── Assignments and review records (read models) ──

    def get_assignment(
        self, assignment_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/assignments/{assignment_id}", None, headers
        )

    def list_assignments(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/assignments", _clean(params), headers)

    def get_review_record(
        self, review_record_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/review-records/{review_record_id}", None, headers
        )

    def list_review_records(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/review-records", _clean(params), headers
        )

    # ─── Vendor engagements (PRD §3.7) ────────────────

    def confirm_shipment(
        self, vendor_engagement_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/vendor-engagements/{vendor_engagement_id}/confirm-shipment",
            _clean(payload) if payload is not None else {},
            headers,
        )

    def record_return(
        self, vendor_engagement_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/vendor-engagements/{vendor_engagement_id}/record-return",
            _clean(payload),
            headers,
        )

    def cancel_vendor_engagement(
        self, vendor_engagement_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/vendor-engagements/{vendor_engagement_id}/cancel",
            _clean(payload),
            headers,
        )

    def get_vendor_engagement(
        self, vendor_engagement_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET",
            f"{API_PREFIX}/vendor-engagements/{vendor_engagement_id}",
            None,
            headers,
        )

    def list_vendor_engagements(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/vendor-engagements", _clean(params), headers
        )

    # ─── Proficiency tests (PRD §3.8) ─────────────────

    def create_proficiency_test(
        self, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/proficiency-tests", _clean(payload), headers
        )

    def submit_proficiency_test(
        self, proficiency_test_id: str, headers: Dict[str, str], payload: Any = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/proficiency-tests/{proficiency_test_id}/submit",
            _clean(payload) if payload is not None else {},
            headers,
        )

    def score_proficiency_test(
        self, proficiency_test_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/proficiency-tests/{proficiency_test_id}/score",
            _clean(payload),
            headers,
        )

    def get_proficiency_test(
        self, proficiency_test_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/proficiency-tests/{proficiency_test_id}", None, headers
        )

    def list_proficiency_tests(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/proficiency-tests", _clean(params), headers
        )

    # ─── Nonconformances (PRD §3.8) ───────────────────

    def create_nonconformance(
        self, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/nonconformances", _clean(payload), headers
        )

    def submit_root_cause(
        self, nonconformance_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/nonconformances/{nonconformance_id}/root-cause",
            _clean(payload),
            headers,
        )

    def capa_decision(
        self, nonconformance_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/nonconformances/{nonconformance_id}/capa-decision",
            _clean(payload),
            headers,
        )

    def verify_close_nonconformance(
        self, nonconformance_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/nonconformances/{nonconformance_id}/verify-close",
            _clean(payload) if payload is not None else {},
            headers,
        )

    def get_nonconformance(
        self, nonconformance_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/nonconformances/{nonconformance_id}", None, headers
        )

    def list_nonconformances(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/nonconformances", _clean(params), headers
        )

    # ─── Court events (PRD §3.9) ──────────────────────

    def create_court_event(
        self, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/court-events", _clean(payload), headers
        )

    def confirm_court_event(
        self, court_event_id: str, headers: Dict[str, str], payload: Any = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/court-events/{court_event_id}/confirm",
            _clean(payload) if payload is not None else {},
            headers,
        )

    def complete_court_event(
        self, court_event_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/court-events/{court_event_id}/complete",
            _clean(payload),
            headers,
        )

    def cancel_court_event(
        self, court_event_id: str, payload: Any, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/court-events/{court_event_id}/cancel",
            _clean(payload),
            headers,
        )

    def get_court_event(
        self, court_event_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/court-events/{court_event_id}", None, headers
        )

    def list_court_events(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/court-events", _clean(params), headers)

    # ─── Backlog reporting (PRD §3.9) ─────────────────

    def get_backlog_report(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/backlog-report", _clean(params), headers
        )
